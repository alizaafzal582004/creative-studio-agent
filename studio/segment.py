"""Segmentation: which pixels in each frame belong to a person (not just the face: body, hands, hair).
Model: PP-HumanSeg (OpenCV Zoo, ~6 MB, 192x192), runs on a laptop CPU.

It powers two features:
  - Background blur (portrait mode): person sharp, background blurred
  - Text behind person: the big hook text sits BEHIND the person (really: the person is pasted back on top of the text)

The mask becomes a small grayscale video passed to FFmpeg (white = person). Each shot is cropped/zoomed exactly
like the real video (render.shot_crop) so the mask lines up with the person."""
import os
import urllib.request
from pathlib import Path

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

from studio import cancel
from studio.config import ROOT

MODEL_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "human_segmentation_pphumanseg/human_segmentation_pphumanseg_2023mar.onnx")
MODEL_PATH = ROOT / "models" / "human_segmentation_pphumanseg_2023mar.onnx"
NET_SIZE = 192
MASK_W, MASK_H = 360, 640      # mask video size (FFmpeg scales it up to 1080x1920; the edges are soft anyway)
SMOOTH = 0.4                   # new mask = 60% this frame + 40% previous (no flickering edges); reset on every cut


def ensure_model(log=print) -> Path:
    if not MODEL_PATH.exists() or MODEL_PATH.stat().st_size < 1_000_000:
        MODEL_PATH.parent.mkdir(exist_ok=True)
        log("     Downloading segmentation model (first time only, ~6 MB)...")
        req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "ai-creative-studio"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        tmp = MODEL_PATH.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(MODEL_PATH)
    return MODEL_PATH


def _forward(net, rgb: np.ndarray) -> np.ndarray:
    blob = ((rgb.astype(np.float32) / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None]
    net.setInput(blob)
    return net.forward()[0][1]                 # (192, 192): person probability (the model applies softmax itself)


def person_prob(net, crop: np.ndarray) -> np.ndarray:
    """One frame (BGR) → person probability per pixel (0..1), NET_SIZE x NET_SIZE.
    On OpenCV this model shifts the mask ~10% to the right (measured: center 0.52 on the frame, 0.40 on the
    mirrored frame). So run both and average: the bias cancels out and the mask sits on the person."""
    rgb = cv2.cvtColor(cv2.resize(crop, (NET_SIZE, NET_SIZE), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    return (_forward(net, rgb) + _forward(net, rgb[:, ::-1].copy())[:, ::-1]) / 2


def mask_video(video: Path, shots: list[tuple[float, float, float]], crops: list[tuple[int, int, int, int]],
               out_path: Path, until: float | None = None, log=print) -> Path:
    """Mask video for the whole clip (shots in the same order the render joins them).
    With until (text-behind only needs the first few seconds): the mask is only that long (the render trims too)."""
    net = cv2.dnn.readNet(str(ensure_model(log)))
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (MASK_W, MASK_H), isColor=False)
    blank = np.zeros((MASK_H, MASK_W), np.uint8)
    done = 0.0            # time already written in the new video
    for (a, b, _), (zw, zh, x, zy) in zip(shots, crops):
        frames = max(1, round((b - a) * fps))
        if until is not None and done >= until + 0.3:
            break                      # only the first 'until' seconds are needed (the render doesn't use the mask after that)
        cap.set(cv2.CAP_PROP_POS_MSEC, a * 1000)
        prev = None                                 # restart smoothing on every shot (cut)
        # Run the AI on every other frame (15x/s at 30 fps is enough) and reuse the previous mask in between: with
        # smoothing the difference is invisible and mask time is halved
        stride = 2
        for k in range(frames):
            if until is not None and done + k / fps > until + 0.3:
                break                  # don't even decode the remaining frames
            if k % 30 == 0:
                cancel.pause_point()       # thermal guard: wait while the CPU cools down
            ok, frame = cap.read()
            if not ok:
                writer.write(blank if prev is None else prev)
                continue
            if prev is not None and k % stride:
                writer.write(prev)
                continue
            prob = person_prob(net, frame[zy:zy + zh, x:x + zw])
            prob = cv2.resize(prob, (MASK_W, MASK_H), interpolation=cv2.INTER_LINEAR)
            prob = prob if prev is None else (1 - SMOOTH) * prob + SMOOTH * (prev.astype(np.float32) / 255)
            # harden the edges a bit (otherwise the person looks semi-transparent), then soften slightly
            m = np.clip((prob - 0.35) / 0.3, 0, 1)
            m = cv2.GaussianBlur((m * 255).astype(np.uint8), (0, 0), 1.5)
            writer.write(m)
            prev = m
        done += b - a
    writer.release()
    cap.release()
    return out_path
