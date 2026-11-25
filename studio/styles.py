"""Caption styles (presets). Colors are written as normal RGB hex, e.g. "FFE000" = yellow."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CaptionStyle:
    name: str
    label: str                    # name shown on the website
    font: str = "Poppins"
    size: int = 84
    color: str = "FFFFFF"         # normal word color
    highlight: str = "FFE000"     # the word being spoken right now
    outline: str = "000000"
    outline_width: int = 6
    uppercase: bool = True
    max_words: int = 3            # words on screen at a time
    pop: bool = True              # the spoken word 'pops'
    margin_v: int = 450           # distance from the bottom (out of 1920)
    hook_color: str = "FFE000"
    emphasis_color: str = "39FF14"  # color of the AI-picked key words
    emphasis_scale: int = 120       # key word scale (%)
    hook_anim: str = "slide"        # hook text kaise aaye: slide / pop / typewriter / fade
    bold: bool = True               # bold or not: False only for single-weight heavy Google Fonts (Anton etc.)
    # --- Hook look (first 3 s, the big text on top) ---
    hook_look: str = "bold"         # bold: no box, thick outline / pill: a colored rounded box per line /
                                    # sticker: one tilted white box / box: classic black box
    hook_size: int = 100
    hook_bg: str = "FFFFFF"         # box color for pill / sticker
    hook_ink: str = "111111"        # text color on pill / sticker
    # --- Extra caption effects ---
    glow: int = 0                   # neon glow: blur the outline this much (0 = off)
    shadow: int = 0                 # 3D shadow distance (pixels, 0 = off)
    shadow_color: str = "000000"
    word_box: str = ""              # colored box behind the spoken word (e.g. "FFE000"), "" = off


# Each style has its own Google Font (studio/fonts.py downloads it on first use) and its own hook look.
STYLES = {
    "bold_pop": CaptionStyle("bold_pop", "Bold Pop (Poppins, yellow, pop)", hook_look="bold"),
    "viral_anton": CaptionStyle("viral_anton", "Viral (Anton, big, yellow + green)", font="Anton", size=110,
                                bold=False, outline_width=7, max_words=2, emphasis_color="39FF14",
                                emphasis_scale=125, hook_anim="pop", hook_look="bold", hook_size=120),
    "box_highlight": CaptionStyle("box_highlight", "Box Highlight (Poppins, yellow box behind the spoken word)",
                                  size=78, highlight="111111", pop=False, outline_width=5, max_words=3,
                                  emphasis_color="FFE000", emphasis_scale=100, word_box="FFE000",
                                  hook_look="pill", hook_bg="FFE000", hook_ink="111111", hook_anim="pop"),
    "neon": CaptionStyle("neon", "Neon Glow (Bebas Neue, glowing blue)", font="Bebas Neue", size=118, bold=False,
                         color="FFFFFF", highlight="00F0FF", outline="00C8FF", outline_width=4, glow=8,
                         max_words=3, emphasis_color="FF4FD8", emphasis_scale=115, hook_look="pill",
                         hook_bg="00E5FF", hook_ink="0A0A14", hook_anim="slide", hook_size=112),
    "shadow_3d": CaptionStyle("shadow_3d", "3D Shadow (Archivo Black, pink shadow)", font="Archivo Black", size=76,
                              bold=False, highlight="FFE000", outline_width=4, shadow=7, shadow_color="E1306C",
                              max_words=3, emphasis_color="00F0FF", hook_look="sticker", hook_bg="FFFFFF",
                              hook_ink="111111", hook_anim="pop", hook_size=84),
    "one_word": CaptionStyle("one_word", "One Word (Anton, center screen, very big)", font="Anton", size=160,
                             bold=False, highlight="FFFFFF", outline_width=9, max_words=1, margin_v=760,
                             emphasis_color="FFE000", emphasis_scale=115, hook_look="sticker",
                             hook_bg="FFE000", hook_ink="111111", hook_anim="pop", hook_size=110),
    "green_karaoke": CaptionStyle("green_karaoke", "Green Karaoke (Archivo Black, green, 4 words)",
                                  font="Archivo Black", size=74, bold=False, highlight="39FF14", max_words=4,
                                  emphasis_color="FFE000", hook_anim="pop", hook_look="pill",
                                  hook_bg="39FF14", hook_ink="0A0A0A", hook_size=84),
    "comic": CaptionStyle("comic", "Comic (Luckiest Guy, blue, playful)", font="Luckiest Guy", size=92,
                          bold=False, highlight="00E5FF", outline_width=8, max_words=2, emphasis_color="FF4FD8",
                          emphasis_scale=125, hook_color="00E5FF", hook_anim="pop", hook_look="sticker",
                          hook_bg="FFFFFF", hook_ink="111111"),
    "clean_bebas": CaptionStyle("clean_bebas", "Clean (Bebas Neue, white, tall)", font="Bebas Neue", size=112,
                                bold=False, highlight="FFFFFF", outline_width=5, max_words=3, pop=False,
                                emphasis_color="FFE000", emphasis_scale=110, hook_color="FFFFFF",
                                hook_anim="slide", hook_look="bold", hook_size=122),
    "minimal": CaptionStyle("minimal", "Minimal (Poppins, simple, small)", size=64, highlight="FFFFFF", pop=False,
                            uppercase=False, outline_width=3, margin_v=380, emphasis_color="FFE000",
                            emphasis_scale=100, hook_anim="typewriter", hook_look="pill", hook_bg="FFFFFF",
                            hook_ink="111111", hook_size=72),
}
DEFAULT_STYLE = "bold_pop"
HOOK_ANIMS = ["slide", "pop", "typewriter", "fade"]
HOOK_LOOKS = {"bold": "Bold (no box, thick outline)", "pill": "Pill (colored rounded box per line)",
              "sticker": "Sticker (tilted white box)", "box": "Box (plain black box)",
              "behind": "Text behind person (big text behind the speaker)",
              "none": "None (no hook text on screen)"}


def ass_color(rgb: str, alpha: str = "00") -> str:
    """Convert 'FFE000' (RGB) to ASS's reversed format '&H0000E0FF' (alpha, Blue, Green, Red)."""
    r, g, b = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"&H{alpha}{b}{g}{r}"


def inline_color(rgb: str) -> str:
    """Inline color-change format inside text: '&H00E0FF&'"""
    r, g, b = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"&H{b}{g}{r}&"
