"""Caption style preview: rendered by the same engine (FFmpeg + libass) as the real video, so preview = video.
A fake 2-second video: hook on top, captions below (one word 'being spoken', one AI key word)."""
from pathlib import Path

from studio.captions import words_to_ass
from studio.config import OUTPUT_DIR
from studio.ffmpeg import run_ffmpeg
from studio.fonts import apply_font, ensure_font, URDU
from studio.render import subtitles_filter
from studio.styles import STYLES

SAMPLE_HOOK = "Ye galti aap bhi roz kar rahe ho"
SAMPLE_WORDS = ["ye", "baat", "koi", "nahi", "batata", "sach"]
SHOW_AT = 1.0      # frame at this moment: hook animation done, third word being spoken


def style_preview(style_key: str, font_key: str | None = None, hook_look: str | None = None,
                  width: int = 300) -> bytes:
    """PNG bytes. If hook_look is given, preview the style with that hook look."""
    from dataclasses import replace
    style = apply_font(STYLES[style_key], font_key, log=lambda *_: None)
    if hook_look:
        style = replace(style, hook_look=hook_look)
    ensure_font(URDU, log=lambda *_: None)
    words = [{"word": w, "start": 0.4 * k, "end": 0.4 * k + 0.38, "orig_start": 0.4 * k}
             for k, w in enumerate(SAMPLE_WORDS)]
    folder = OUTPUT_DIR / "_preview"
    folder.mkdir(exist_ok=True)
    name = f"{style_key}_{font_key or 'auto'}_{hook_look or 'auto'}"
    ass = folder / f"{name}.ass"
    png = folder / f"{name}.png"
    ass.write_text(words_to_ass(words, hook_text=SAMPLE_HOOK, hook_seconds=3, style=style,
                                emphasis={0.4}), encoding="utf-8")
    background = "gradients=s=1080x1920:c0=0x2b2d42:c1=0x5b3a6e:x0=0:y0=0:x1=1080:y1=1920:d=2:r=30"
    run_ffmpeg(["-y", "-f", "lavfi", "-i", background, "-vf", f"{subtitles_filter(ass)},scale={width}:-2",
                "-ss", f"{SHOW_AT}", "-frames:v", "1", png.name], cwd=folder)
    return Path(png).read_bytes()
