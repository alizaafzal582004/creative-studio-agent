"""Brand: animated logo reveal for the end screen. Any PNG/JPG logo is fitted into a 360px box."""
import hashlib
from pathlib import Path

from PIL import Image

from studio.config import OUTPUT_DIR
from studio.emoji import scale_at, FPS

CACHE_DIR = OUTPUT_DIR / "_logo_cache"
LOGO_BOX = 360


def logo_frames(logo: Path, seconds: float) -> Path:
    """Logo frames: a pop in the first 0.22 s (30% → 120% → 100%), then held until the end.
    Built once and cached; a new logo (different file hash) gets new frames."""
    digest = hashlib.sha1(logo.read_bytes()).hexdigest()[:12]
    n = int(seconds * FPS)
    out = CACHE_DIR / f"{digest}_{n}"
    if (out / f"{n - 1:03}.png").exists():
        return out

    out.mkdir(parents=True, exist_ok=True)
    src = Image.open(logo).convert("RGBA")
    src.thumbnail((LOGO_BOX, LOGO_BOX), Image.LANCZOS)        # keep the aspect ratio
    canvas_size = int(LOGO_BOX * 1.25)
    for i in range(n):
        s = scale_at(i / FPS)
        w, h = max(2, int(src.width * s)), max(2, int(src.height * s))
        img = src.resize((w, h), Image.LANCZOS)
        canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        canvas.paste(img, ((canvas_size - w) // 2, (canvas_size - h) // 2), img)
        canvas.save(out / f"{i:03}.png")
    return out
