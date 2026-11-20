"""Emoji pop: a short animation of an emoji image (Twemoji PNG) overlaid on the video.
The caption library (libass) can't render color emoji, so emoji are added as separate images."""
import json
from functools import lru_cache
from pathlib import Path

from PIL import Image

from studio.config import ROOT, OUTPUT_DIR

EMOJI_DIR = ROOT / "assets" / "emoji"
CACHE_DIR = OUTPUT_DIR / "_emoji_cache"
FPS = 30
SIZE = 200          # typical emoji width (pixels, on a 1080-wide video)
DURATION = 1.0      # how long it stays on screen (seconds)


@lru_cache(maxsize=1)
def emoji_map() -> dict[str, str]:
    """{'🔥': '1f525.png', ...}  the only emoji available.
    Without the assets/emoji folder this is empty: key words are still colored, just without emoji."""
    path = EMOJI_DIR / "emoji_map.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(e: str) -> str:
    """Treat '❤️' and '❤' as the same (FE0F is the invisible 'render in color' character)."""
    return e.replace("️", "").strip()


def find_png(e: str) -> Path | None:
    table = {normalize(k): v for k, v in emoji_map().items()}
    name = table.get(normalize(e))
    return EMOJI_DIR / name if name else None


def scale_at(t: float) -> float:
    """Pop size: 30% → 120% in 0.12 s, then settle at 100% in 0.1 s."""
    if t < 0.12:
        return 0.3 + 0.9 * t / 0.12
    if t < 0.22:
        return 1.2 - 0.2 * (t - 0.12) / 0.10
    return 1.0


def alpha_at(t: float) -> float:
    """Fade out over the last 0.2 seconds."""
    return max(0.0, min(1.0, (DURATION - t) / 0.2))


def pop_frames(e: str) -> Path | None:
    """Build the emoji pop animation frames (000.png, 001.png, ...) and return the folder. Built once (cached)."""
    png = find_png(e)
    if not png or not png.exists():
        return None
    out = CACHE_DIR / png.stem
    n = int(DURATION * FPS)
    if (out / f"{n - 1:03}.png").exists():
        return out

    out.mkdir(parents=True, exist_ok=True)
    src = Image.open(png).convert("RGBA")
    canvas_size = int(SIZE * 1.25)   # leave room for the 120% pop
    for i in range(n):
        t = i / FPS
        side = max(2, int(SIZE * scale_at(t)))
        img = src.resize((side, side), Image.LANCZOS)
        if alpha_at(t) < 1:
            r, g, b, a = img.split()
            a = a.point(lambda v: int(v * alpha_at(t)))
            img = Image.merge("RGBA", (r, g, b, a))
        canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        canvas.paste(img, ((canvas_size - side) // 2, (canvas_size - side) // 2), img)
        canvas.save(out / f"{i:03}.png")
    return out
