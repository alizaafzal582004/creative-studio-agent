"""Thumbnail generator: picks each Short's best frame (big, clear, sharp face), adds big hook text,
and renders two sizes: a 9:16 cover (Shorts/Reels) and a 16:9 thumbnail (YouTube).

Text is rendered with libass (FFmpeg subtitles), not Pillow: Pillow here has no 'raqm', without which Urdu
letters come out disconnected and reversed. libass shapes Urdu correctly and uses the same Google Fonts as the captions."""
import os
from pathlib import Path

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")   # silence noisy OpenCV warnings
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageEnhance  # noqa: E402

from studio.captions import clean, font_tag, has_urdu, wrap_hook  # noqa: E402
from studio.ffmpeg import run_ffmpeg  # noqa: E402
from studio.fonts import text_width  # noqa: E402
from studio.framing import ensure_model  # noqa: E402
from studio.render import subtitles_filter  # noqa: E402
from studio.styles import CaptionStyle, inline_color  # noqa: E402


# ---------------- 1) Best frame ----------------

MAX_SAMPLES = 9

def read_frame(cap: cv2.VideoCapture, t: float) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    return frame if ok else None


def frame_score(img: np.ndarray, detector) -> float:
    """A good thumbnail frame: a big face, a confident detection, and a sharp (not blurry) face.
    Sharpness = Laplacian variance: a sharp image has more edges, so more variance."""
    small_w = 360
    small = cv2.resize(img, (small_w, int(img.shape[0] * small_w / img.shape[1])))
    detector.setInputSize((small.shape[1], small.shape[0]))
    _, faces = detector.detect(small)
    if faces is None or len(faces) == 0:
        return 0.0
    x, y, w, h = faces[0][:4].astype(int)
    conf = float(faces[0][-1])
    roi = cv2.cvtColor(small[max(y, 0):y + h, max(x, 0):x + w], cv2.COLOR_BGR2GRAY)
    sharp = cv2.Laplacian(roi, cv2.CV_64F).var() if roi.size else 0
    return (w / small_w) * conf * (0.5 + min(sharp / 300, 1.0))


def best_frame(video: Path, shots: list[tuple[float, float, float]]) -> tuple[np.ndarray, float] | None:
    """Sample 3 points per shot; return the best-scoring full frame and its cx."""
    cap = cv2.VideoCapture(str(video))
    detector = cv2.FaceDetectorYN.create(str(ensure_model()), "", (360, 640), 0.6)
    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    cw = int(min(w, h * 9 / 16))

    # 3 points per shot, but MAX_SAMPLES in total (spread evenly over the clip): every seek is expensive at 1080p
    spots = [(a + (b - a) * p, cx) for a, b, cx in shots for p in (0.25, 0.5, 0.75)]
    if len(spots) > MAX_SAMPLES:
        spots = [spots[round(k * (len(spots) - 1) / (MAX_SAMPLES - 1))] for k in range(MAX_SAMPLES)]
    best, best_score = None, -1.0
    for at, cx in spots:
        frame = read_frame(cap, at)
        if frame is None:
            continue
        x = int(min(max(cx * w - cw / 2, 0), w - cw))
        score = frame_score(frame[:, x:x + cw], detector)
        if score > best_score:
            best, best_score = (frame, cx), score
    cap.release()
    return best


# ---------------- 2) Text (libass) ----------------

def shade(img: Image.Image, side: str, strength: int = 200, portion: float = 0.5) -> Image.Image:
    """Dark gradient on the text side (so the text is readable). Vectorized with numpy, no per-pixel loop."""
    w, h = img.size
    length = w if side == "left" else h
    ramp = np.clip(1 - np.arange(length) / (length * portion), 0, 1) * strength
    alpha = np.tile(ramp, (h, 1)) if side == "left" else np.tile(ramp[:, None], (1, w))
    grad = Image.fromarray(alpha.astype(np.uint8), "L")
    return Image.composite(Image.new("RGB", (w, h), "black"), img, grad)


def text_ass(text: str, style: CaptionStyle, size_wh: tuple[int, int], box: tuple[int, int, int],
             start_size: int, align: str = "center", max_lines: int = 3) -> str:
    """ASS that writes big text on the image. box = (x, y, width). The largest size where up to max_lines
    lines fit the box. Lines alternate white and the style's color, with a thick black outline."""
    W, H = size_wh
    x0, y0, max_w = box
    text = clean(text)
    urdu = has_urdu(text)
    words = text.split() if urdu else text.upper().split()
    size = start_size
    while True:
        lines = wrap_hook(words, style, size, max_w=max_w)
        widest = max(text_width(" ".join(ln), style.font, size, style.bold) for ln in lines)
        if (len(lines) <= max_lines and widest <= max_w) or size <= 40:
            break
        size -= 6
    an, x = (8, x0 + max_w // 2) if align == "center" else (7, x0)
    b = -1 if style.bold else 0
    out = [f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\n\n[V4+ Styles]\n"
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
           "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
           "MarginL, MarginR, MarginV, Encoding\n"
           f"Style: T,{style.font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H90000000,{b},0,0,0,100,100,0,0,1,"
           f"{max(4, size // 11)},{max(2, size // 25)},{an},0,0,0,1\n\n[Events]\n"
           "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"]
    colors = ["&HFFFFFF&", inline_color(style.highlight if style.highlight.upper() not in ("FFFFFF", "111111")
                                        else style.hook_color)]
    y = y0
    for k, ln in enumerate(lines):
        line = " ".join(ln)
        out.append(f"Dialogue: 0,0:00:00.00,0:00:05.00,T,,0,0,0,,{{\\pos({x},{y:.0f})\\1c{colors[k % 2]}}}"
                   f"{font_tag(line)}{line}\n")
        y += size * 1.05
    return "".join(out)


def burn_text(img: Image.Image, ass: str, out_path: Path) -> Path:
    """Image + ASS → JPG (FFmpeg subtitles filter; Urdu renders correctly too)."""
    folder = out_path.parent
    base = folder / f"{out_path.stem}_base.png"
    ass_file = folder / f"{out_path.stem}_text.ass"
    img.save(base)
    ass_file.write_text(ass, encoding="utf-8")
    try:
        run_ffmpeg(["-y", "-i", base.name, "-vf", subtitles_filter(ass_file), "-frames:v", "1", "-q:v", "2",
                    out_path.name], cwd=folder)
    finally:
        base.unlink(missing_ok=True)
        ass_file.unlink(missing_ok=True)
    return out_path


# ---------------- 3) Compose ----------------

def make_thumbnails(video: Path, shots: list[tuple[float, float, float]], text: str, style: CaptionStyle,
                    out_dir: Path, name: str) -> list[Path]:
    """Returns: paths of [9:16 cover, 16:9 thumbnail] (empty list if no frame was found)."""
    found = best_frame(video, shots)
    if not found:
        return []
    frame, cx = found
    src = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    src = ImageEnhance.Color(ImageEnhance.Contrast(src).enhance(1.08)).enhance(1.15)   # thora "pop"
    w, h = src.size
    paths = []

    # 9:16 cover: person centered, text on top
    cw = int(min(w, h * 9 / 16))
    x = int(min(max(cx * w - cw / 2, 0), w - cw))
    ch = min(h, int(cw * 16 / 9))
    cover = src.crop((x, (h - ch) // 2, x + cw, (h - ch) // 2 + ch)).resize((1080, 1920), Image.LANCZOS)
    cover = shade(cover, "top", 210, 0.45)
    # short text (2-4 words) in a narrow space: 2 lines, very big (one thin line looked small)
    paths.append(burn_text(cover, text_ass(text, style, (1080, 1920), (140, 150, 800), 230), out_dir / f"{name}_cover.jpg"))

    # 16:9 thumbnail: person on the right (~68%), text on the left. For portrait (9:16) video, a blurred background
    th = int(min(h, w * 9 / 16))
    tw = int(th * 16 / 9)
    if w >= h * 1.3:          # chauri (16:9 jaisi) video: seedha kaat lo
        tx = int(min(max(cx * w - tw * 0.68, 0), w - tw))
        ty = int(max(0, (h - th) * 0.3))
        thumb = src.crop((tx, ty, tx + tw, ty + th)).resize((1280, 720), Image.LANCZOS)
    else:
        # portrait video: the whole person doesn't fit in 16:9. Blurred copy of the same frame behind, person on the right
        from PIL import ImageFilter
        bg = src.resize((1280, int(1280 * h / w)), Image.LANCZOS).crop((0, 0, 1280, 720)).filter(ImageFilter.GaussianBlur(24))
        person = src.resize((int(720 * w / h), 720), Image.LANCZOS)
        bg.paste(person, (1280 - person.width - 40, 0))
        thumb = bg
    thumb = shade(thumb, "left", 220, 0.6)
    paths.append(burn_text(thumb, text_ass(text, style, (1280, 720), (50, 110, 600), 160, align="left"),
                           out_dir / f"{name}_thumb.jpg"))
    return paths
