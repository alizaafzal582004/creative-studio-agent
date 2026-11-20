"""Google Fonts: popular caption fonts. Downloaded once from google/fonts (GitHub) into assets/fonts,
then loaded from there. All fonts are free (OFL / Apache license) and allowed in videos."""
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from functools import lru_cache

from studio.config import FONTS_DIR

BASE = "https://raw.githubusercontent.com/google/fonts/main/"


@dataclass(frozen=True)
class GoogleFont:
    family: str          # family name inside the TTF: captions (ASS) look the font up by this name
    label: str           # name shown on the website
    files: tuple         # paths in the google/fonts repo
    bold: bool = True    # don't apply fake bold to single-weight heavy fonts (Anton etc.)
    scale: float = 1.0   # condensed fonts look smaller at the same size: scale up a bit


FONTS = {
    "poppins": GoogleFont("Poppins", "Poppins (clean, modern)",
                          ("ofl/poppins/Poppins-Regular.ttf", "ofl/poppins/Poppins-Bold.ttf")),
    "anton": GoogleFont("Anton", "Anton (tall, heavy: the viral Shorts look)", ("ofl/anton/Anton-Regular.ttf",),
                        bold=False, scale=1.25),
    "bebas": GoogleFont("Bebas Neue", "Bebas Neue (tall, clean)", ("ofl/bebasneue/BebasNeue-Regular.ttf",),
                        bold=False, scale=1.3),
    "archivo": GoogleFont("Archivo Black", "Archivo Black (heavy, bold)",
                          ("ofl/archivoblack/ArchivoBlack-Regular.ttf",), bold=False),
    "luckiest": GoogleFont("Luckiest Guy", "Luckiest Guy (cartoon, playful)",
                           ("apache/luckiestguy/LuckiestGuy-Regular.ttf",), bold=False),
    "bangers": GoogleFont("Bangers", "Bangers (comic)", ("ofl/bangers/Bangers-Regular.ttf",), bold=False),
}
URDU = GoogleFont("Noto Nastaliq Urdu", "Noto Nastaliq Urdu", ("ofl/notonastaliqurdu/NotoNastaliqUrdu[wght].ttf",))


def ensure_font(font: GoogleFont, log=print) -> bool:
    """Make sure the font files are in assets/fonts, downloading if needed. False = internet/GitHub problem (fallback font)."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    for path in font.files:
        target = FONTS_DIR / path.rsplit("/", 1)[1]
        if target.exists() and target.stat().st_size > 10_000:
            continue
        url = BASE + path.replace("[", "%5B").replace("]", "%5D")
        try:
            log(f"     Downloading Google Font: {font.family} ({target.name})...")
            req = urllib.request.Request(url, headers={"User-Agent": "ai-creative-studio"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            tmp = target.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(target)
        except Exception as e:
            log(f"     Warning: font {font.family} download failed ({type(e).__name__}), using the default font")
            ok = False
    return ok


def apply_font(style, override: str | None = None, log=print):
    """Combine a style with a font. Empty override = the style's own font (same size it was tuned for).
    Given override (e.g. 'anton') = that font, with bold/size adjusted for it. If the download fails, the style is unchanged."""
    chosen = font_for(override)
    own = font_for(style.font)
    font = chosen or own
    if not font or not ensure_font(font, log):
        return style
    if chosen and chosen != own:
        base = style.size / (own.scale if own else 1.0)      # by making the style's size 'Poppins-equivalent'
        return replace(style, font=font.family, bold=font.bold, size=round(base * font.scale))
    return replace(style, font=font.family, bold=font.bold)


@lru_cache(maxsize=64)
def _measure_font(family: str, size: int, bold: bool):
    """A PIL font as large as libass renders it: ASS size = the font's full height (ascent + descent), PIL's = 'em'."""
    from PIL import ImageFont
    font = font_for(family)
    if not font or not font_file(font, bold).exists():
        return None
    path = str(font_file(font, bold))
    a, d = ImageFont.truetype(path, 100).getmetrics()
    return ImageFont.truetype(path, max(8, round(size * 100 / (a + d))))


CALIBRATION_FILE = FONTS_DIR / "_libass_widths.json"
_CALIBRATION: dict | None = None
CAL_TEXT = "HAMBURGEFONTS nahi baat 0123"


def libass_ratio(family: str, bold: bool) -> float:
    """How wide libass actually renders text compared to PIL's estimate (measured once per font, then cached
    in a file). This puts the highlight box behind the spoken word and the hook lines exactly in place."""
    global _CALIBRATION
    import json
    if _CALIBRATION is None:
        try:
            _CALIBRATION = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
        except Exception:
            _CALIBRATION = {}
    key = f"{family}|{int(bold)}"
    if key in _CALIBRATION:
        return _CALIBRATION[key]
    ratio = 1.0
    try:
        ratio = _calibrate(family, bold)
        _CALIBRATION[key] = ratio
        CALIBRATION_FILE.write_text(json.dumps(_CALIBRATION, indent=1), encoding="utf-8")
    except Exception:
        pass
    return ratio


def _calibrate(family: str, bold: bool) -> float:
    """Render CAL_TEXT with libass (FFmpeg subtitles) at size 100, white on black, and measure its width."""
    import os
    import tempfile
    from PIL import Image
    from studio.ffmpeg import run_ffmpeg
    pil = _measure_font(family, 100, bold)
    if pil is None:
        return 1.0
    with tempfile.TemporaryDirectory(dir=FONTS_DIR) as tmp:
        tmp = Path(tmp)
        (tmp / "c.ass").write_text(
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 2400\nPlayResY: 300\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            f"Style: C,{family},100,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,{-1 if bold else 0},0,0,0,100,100,"
            "0,0,1,0,0,7,0,0,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            f"Effect, Text\nDialogue: 0,0:00:00.00,0:00:01.00,C,,0,0,0,,{{\\pos(20,20)}}{CAL_TEXT}\n",
            encoding="utf-8")
        fonts = os.path.relpath(FONTS_DIR, tmp).replace("\\", "/")
        run_ffmpeg(["-y", "-f", "lavfi", "-i", "color=c=black:s=2400x300:d=0.1", "-vf",
                    f"subtitles=c.ass:fontsdir={fonts}", "-frames:v", "1", "c.png"], cwd=tmp)
        box = Image.open(tmp / "c.png").convert("L").point(lambda v: 255 if v > 60 else 0).getbbox()
    if not box:
        return 1.0
    return (box[2] - box[0]) / pil.getlength(CAL_TEXT)


def text_width(text: str, family: str, size: int, bold: bool = True) -> float:
    """Width of the text in the video in pixels (for the hook box / spoken-word box).
    Estimated (~0.55 × size per character) if the font file is missing."""
    f = _measure_font(family, size, bold)
    return f.getlength(text) * libass_ratio(family, bold) if f else 0.55 * size * len(text)


def font_file(font: GoogleFont, bold: bool = True):
    """TTF file for previews: the Bold file if bold is wanted and available, otherwise the first one."""
    files = [FONTS_DIR / p.rsplit("/", 1)[1] for p in font.files]
    return files[-1] if bold else files[0]


def font_for(key: str | None) -> GoogleFont | None:
    """'anton' → GoogleFont. The family name ('Bebas Neue') works too."""
    if not key:
        return None
    key = key.strip()
    return FONTS.get(key.lower()) or next((f for f in FONTS.values() if f.family.lower() == key.lower()), None)
