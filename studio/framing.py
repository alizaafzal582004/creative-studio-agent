"""Face tracking: find faces, work out who is speaking, and keep the 9:16 frame on them."""
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")   # silence noisy OpenCV warnings
import cv2  # noqa: E402
import numpy as np  # noqa: E402

from studio import cancel
from studio.config import CPU_THREADS, ROOT

cv2.setNumThreads(CPU_THREADS)     # cool mode (see config.py): face scan + masks use about half the cores

MODEL_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
MODEL_PATH = ROOT / "models" / "face_detection_yunet_2023mar.onnx"
DETECT_WIDTH = 640  # detection is faster on a smaller image


@dataclass
class Face:
    t: float      # second
    cx: float     # face center, 0 = left edge, 1 = right edge
    size: float   # face width (fraction of the frame)
    talk: float   # lip movement: higher = probably speaking
    cy: float = 0.4   # face center top to bottom (0 = top, 1 = bottom)


@dataclass
class Track:
    """One person: all of their faces found at different times."""
    faces: list[Face] = field(default_factory=list)

    @property
    def cx(self) -> float:
        return float(np.median([f.cx for f in self.faces]))

    @property
    def cy(self) -> float:
        return float(np.median([f.cy for f in self.faces]))

    @property
    def size(self) -> float:
        return float(np.median([f.size for f in self.faces]))


def ensure_model() -> Path:
    if not MODEL_PATH.exists() or MODEL_PATH.stat().st_size < 100_000:
        MODEL_PATH.parent.mkdir(exist_ok=True)
        print("     Downloading face model (first time only, ~230 KB)...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return MODEL_PATH


def video_size(video: Path) -> tuple[int, int]:
    cap = cv2.VideoCapture(str(video))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if not w or not h:
        raise RuntimeError(f"Could not open the video: {video}")
    return w, h


def mouth_box(d: np.ndarray, img_w: int, img_h: int) -> tuple[int, int, int, int]:
    """Box around the lips from YuNet's landmarks (the two mouth corners)."""
    w, h = d[2], d[3]
    xs, ys = (d[10], d[12]), (d[11], d[13])
    x1 = int(max(0, min(xs) - 0.1 * w))
    x2 = int(min(img_w, max(xs) + 0.1 * w))
    y1 = int(max(0, min(ys) - 0.15 * h))
    y2 = int(min(img_h, max(ys) + 0.15 * h))
    return x1, y1, x2, y2


def scan_faces(video: Path, start: float, end: float, fps: float = 4) -> list[Face]:
    """Find faces ~4 times per second in the clip and measure each face's lip movement."""
    cap = cv2.VideoCapture(str(video))
    src_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    src_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    small_w, small_h = DETECT_WIDTH, int(src_h * DETECT_WIDTH / src_w)

    detector = cv2.FaceDetectorYN.create(str(ensure_model()), "", (small_w, small_h), 0.7)
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)

    step = max(2, round(src_fps / fps))   # one sample every 'step' frames
    faces: list[Face] = []
    pending = None   # (time, detections, gray image) until the next frame arrives
    i = 0
    while cap.grab():
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        if t > end:
            break
        phase = i % step
        i += 1
        if i % 60 == 0:
            cancel.pause_point()           # thermal guard: wait while the CPU cools down
        if phase > 1:
            continue

        ok, frame = cap.retrieve()
        if not ok:
            continue
        small = cv2.resize(frame, (small_w, small_h))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        if phase == 0:
            _, dets = detector.detect(small)
            pending = (t, dets if dets is not None else [], gray)
        elif pending:
            # next frame: lip difference between the two frames = a sign of talking
            t0, dets, gray0 = pending
            for d in dets:
                x1, y1, x2, y2 = mouth_box(d, small_w, small_h)
                if x2 - x1 < 3 or y2 - y1 < 3:
                    continue
                diff = cv2.absdiff(gray0[y1:y2, x1:x2], gray[y1:y2, x1:x2])
                faces.append(Face(t0, (d[0] + d[2] / 2) / small_w, d[2] / small_w, float(diff.mean()) / 255,
                                  (d[1] + d[3] / 2) / small_h))
            pending = None

    cap.release()
    return faces


MIN_FACE = 0.025   # face smaller than 2.5% of the frame width = probably a picture on a poster/screen


def group_tracks(faces: list[Face], max_dist: float = 0.12) -> list[Track]:
    """Faces that keep appearing in the same place = the same person."""
    tracks: list[Track] = []
    for f in sorted((f for f in faces if f.size >= MIN_FACE), key=lambda f: f.t):
        nearest = min(tracks, key=lambda tr: abs(tr.cx - f.cx), default=None)
        if nearest and abs(nearest.cx - f.cx) < max_dist:
            nearest.faces.append(f)
        else:
            tracks.append(Track([f]))
    return [tr for tr in tracks if len(tr.faces) >= 2]   # seen only once: probably a false detection


def choose_center(tracks: list[Track], a: float, b: float, crop_frac: float, prev: float | None) -> float:
    """Where should the frame be for this time span (a to b)? On the speaker, else the biggest face, else where it was."""
    seen = []
    for tr in tracks:
        fs = [f for f in tr.faces if a - 0.25 <= f.t <= b + 0.25]
        if fs:
            seen.append({
                "cx": float(np.median([f.cx for f in fs])),
                "talk": float(np.mean([f.talk for f in fs])),
                "size": float(np.mean([f.size for f in fs])),
                "count": len(fs),
            })

    # ignore faces that only appeared briefly in this shot
    if seen:
        most = max(s["count"] for s in seen)
        seen = [s for s in seen if s["count"] >= 0.4 * most]

    if not seen:
        return prev if prev is not None else 0.5
    if len(seen) == 1:
        return seen[0]["cx"]

    # if everyone fits in one 9:16 frame, show them all
    xs = [s["cx"] for s in seen]
    if max(xs) - min(xs) < crop_frac * 0.7:
        return (max(xs) + min(xs)) / 2

    by_talk = sorted(seen, key=lambda s: s["talk"], reverse=True)
    if by_talk[0]["talk"] > 1.3 * by_talk[1]["talk"]:
        return by_talk[0]["cx"]                       # clearly know who is speaking
    if prev is not None:
        return prev                                   # not sure: don't move the camera
    return max(seen, key=lambda s: s["size"])["cx"]   # the biggest face


def crop_fraction(video: Path) -> float:
    """Fraction of the video width covered by a 9:16 frame (~0.32 on a 16:9 video)."""
    w, h = video_size(video)
    return min(w, h * 9 / 16) / w


def find_people(video: Path, start: float, end: float) -> list[Track]:
    """All people (tracks) found in the clip. Scanned once, then reused everywhere."""
    return group_tracks(scan_faces(video, start, end))


def plan_shots(video: Path, pieces: list[tuple[float, float]], track: bool = True,
               tracks: list[Track] | None = None) -> list[tuple[float, float, float]]:
    """Frame center for each span (a, b): [(a, b, cx), ...]"""
    if not track:
        return [(a, b, 0.5) for a, b in pieces]

    crop_frac = crop_fraction(video)
    if tracks is None:
        tracks = find_people(video, min(a for a, _ in pieces), max(b for _, b in pieces))

    shots, prev = [], None
    for a, b in pieces:
        cx = choose_center(tracks, a, b, crop_frac, prev)
        shots.append((a, b, cx))
        prev = cx
    return shots


def split_pair(video: Path, tracks: list[Track]) -> tuple[float, float] | None:
    """Two people for split-screen: the two most-seen faces, far enough apart that one 9:16 frame
    can't hold both. Returns: (left person's cx, right person's cx), or None."""
    w, h = video_size(video)
    if w <= h or len(tracks) < 2:          # portrait video or a single person: split-screen doesn't help
        return None
    top_two = sorted(tracks, key=lambda tr: len(tr.faces), reverse=True)[:2]
    left, right = sorted(tr.cx for tr in top_two)
    if right - left < crop_fraction(video) * 0.7:
        return None                        # both already fit in one frame
    return left, right
