"""Removing background noise / other people's voices so only the speaker's voice stays clear.

RNNoise (FFmpeg's 'arnndn' filter): a small neural network with several trained models, chosen by measuring
real videos (how much the background drops in pauses vs. how much the voice is kept):
  - 'std' (previous): 0 dB on a podcast's background (other people, room noise), i.e. no effect
  - 'lq'            : background -17 dB, voice only -2 dB
  - 'lq' + 'sh'     : background -34 dB (~50x quieter), voice -2.3 dB (gain restored afterwards)
Speech gate ('strong' only): Whisper's word timings tell us when the speaker is talking, so the leftover
background is pushed down in every pause (with an 80 ms ramp, so there is no audible click).
If the model can't be downloaded (no internet), FFmpeg's 'afftdn' (FFT noise reduction) is used: weaker, but always available."""
import os
import urllib.request
from pathlib import Path

from studio.config import ROOT

BASE_URL = "https://raw.githubusercontent.com/richardpl/arnndn-models/master/"
MODELS_DIR = ROOT / "models"

# level: (label, RNNoise models, mix, speech gate floor or None)
STRENGTHS = {
    "light": ("Light", ("lq",), 0.85, None),
    "medium": ("Medium", ("lq", "sh"), 1.0, None),
    "strong": ("Strong", ("lq", "sh"), 1.0, 0.12),     # background in pauses ~18 dB lower still
}
DEFAULT_STRENGTH = "medium"
MAKEUP_DB = 2.0     # the models lower the voice by ~2 dB: bring it back up (the limiter prevents clipping)


def ensure_model(name: str, log=print) -> Path | None:
    """RNNoise model file (~300 KB). Downloaded the first time, then loaded from models/."""
    path = MODELS_DIR / f"rn_{name}.rnnn"
    if path.exists() and path.stat().st_size > 100_000:
        return path
    try:
        log(f"     Downloading noise-removal model '{name}'...")
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(BASE_URL + f"{name}.rnnn", headers={"User-Agent": "ai-creative-studio"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path
    except Exception as e:
        log(f"     Warning: RNNoise model '{name}' not found ({type(e).__name__})")
        return None


def denoise_filter(strength: str = DEFAULT_STRENGTH, cwd: Path | None = None, log=print) -> str:
    """FFmpeg audio filter chain (without the speech gate; that is built per clip from its words).
    cwd = FFmpeg's working directory: the model path is relative to it (a 'C:' path breaks inside a filter)."""
    _, names, mix, _ = STRENGTHS.get(strength, STRENGTHS[DEFAULT_STRENGTH])
    # highpass: remove rumble below 80 Hz (AC / traffic / mic bumps); the human voice sits above that
    chain = ["highpass=f=80"]
    for name in names:
        model = ensure_model(name, log)
        if model:
            rel = os.path.relpath(model, cwd or Path.cwd()).replace("\\", "/")
            chain.append(f"arnndn=m={rel}:mix={mix:.2f}")
    if len(chain) == 1:                        # no model available: use the FFT filter
        chain.append(f"afftdn=nr={int(10 + 14 * mix)}:nf=-30:tn=1")
    chain += [f"volume={MAKEUP_DB}dB", "alimiter=limit=0.95"]
    return ",".join(chain)


def gate_floor(strength: str) -> float | None:
    return STRENGTHS.get(strength, STRENGTHS[DEFAULT_STRENGTH])[3]


def speech_spans(words: list[dict], join_gap: float = 0.3, pre: float = 0.12,
                 post: float = 0.2) -> list[tuple[float, float]]:
    """Word times (new video timeline) → speech ranges. Nearby words merge into one range, with a little padding."""
    spans: list[list[float]] = []
    for w in sorted(words, key=lambda w: w["start"]):
        a, b = max(0.0, w["start"] - pre), w["end"] + post
        if spans and a - spans[-1][1] <= join_gap:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    return [(a, b) for a, b in spans]


def speech_gate(spans: list[tuple[float, float]], floor: float, ramp: float = 0.08) -> str:
    """FFmpeg 'volume' filter: full volume while speaking, 'floor' in pauses (e.g. 0.12 = -18 dB).
    Each range opens/closes on a soft ramp so there is no audible click."""
    if not spans:
        return ""
    terms = "+".join(f"clip((t-{a - ramp:.3f})/{ramp},0,1)*clip(({b + ramp:.3f}-t)/{ramp},0,1)" for a, b in spans)
    return f"volume='{floor}+{1 - floor:.3f}*min(1,{terms})':eval=frame"
