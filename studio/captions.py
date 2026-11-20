import re
from contextlib import contextmanager

from studio.styles import STYLES, DEFAULT_STYLE, CaptionStyle, ass_color, inline_color

# ---------------- Canvas: video size (vertical 1080x1920 or landscape 1920x1080) ----------------
# Every caption position (hook, captions, end screen, boxes) derives from this. Default: vertical (Shorts).
CANVAS = {"w": 1080, "h": 1920}


@contextmanager
def canvas(w: int, h: int):
    """ASS files built inside this block use this size (e.g. landscape 1920x1080). Restored afterwards."""
    old = dict(CANVAS)
    CANVAS.update(w=w, h=h)
    try:
        yield
    finally:
        CANVAS.update(old)


def landscape() -> bool:
    return CANVAS["w"] > CANVAS["h"]


def cx_mid() -> float:
    return CANVAS["w"] / 2


def hook_top() -> float:
    """Hook distance from the top: 300 on vertical (below the phone's UI), 70 on landscape."""
    return 70 if landscape() else 300


def caption_margin(style_margin: int) -> int:
    """Caption distance from the bottom: the style's value on vertical, ~11% on landscape (YouTube-like)."""
    return int(CANVAS["h"] * 0.11) if landscape() else style_margin


HOOK_X, HOOK_Y = 540, 300      # legacy names (vertical): new code uses the canvas-aware functions


def format_time(seconds: float) -> str:
    """Convert 3.5 seconds to the SRT format '00:00:03,500'."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def words_to_srt(words: list[dict], max_words: int = 3) -> str:
    """Build one caption block per 2-3 words (TikTok/Reels style)."""
    blocks = []
    for i in range(0, len(words), max_words):
        chunk = words[i:i + max_words]
        start = format_time(chunk[0]["start"])
        end = format_time(chunk[-1]["end"])
        text = " ".join(w["word"].strip() for w in chunk)
        blocks.append(f"{len(blocks) + 1}\n{start} --> {end}\n{text}\n")
    return "\n".join(blocks)


def ass_time(seconds: float) -> str:
    """ASS time format: H:MM:SS.cc"""
    cs = int(round(max(seconds, 0) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


# Emoji / pictographs (no emoji in the video): 🔥 ✨ ❤️ ✅ etc., plus their joiners (skin tone, ZWJ, ️)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍\U0001F3FB-\U0001F3FF]")


def clean(text: str) -> str:
    """Strip ASS special characters and emoji so the text can't break."""
    text = _EMOJI.sub("", text)
    return re.sub(r"\s{2,}", " ", text.replace("{", "").replace("}", "").replace("\\", "")).strip()


# separate font for Urdu (in assets/fonts); everything else uses the style's font
URDU_FONT = "Noto Nastaliq Urdu"   # Google Font: downloaded automatically by studio/fonts.py


def has_urdu(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


def font_tag(text: str) -> str:
    """Urdu font tag for an Urdu line ({\\fn...} = 'switch font'), otherwise nothing."""
    return f"{{\\fn{URDU_FONT}}}" if has_urdu(text) else ""


def ass_header(style: CaptionStyle, margin_v: int | None = None) -> str:
    s = style
    mv = caption_margin(s.margin_v) if margin_v is None else margin_v
    b = -1 if s.bold else 0     # no fake bold on single-weight heavy fonts (Anton etc.)
    # 3D shadow: BackColour = shadow color, Shadow = distance; otherwise a light black shadow
    back = ass_color(s.shadow_color) if s.shadow else "&H64000000"
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {CANVAS["w"]}
PlayResY: {CANVAS["h"]}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{s.font},{s.size},{ass_color(s.color)},&H000000FF,{ass_color(s.outline)},{back},{b},0,0,0,100,100,0,0,1,{s.outline_width},{s.shadow},2,60,60,{mv},1
Style: Hook,{s.font},70,{ass_color(s.hook_color)},&H000000FF,&H00000000,&H96000000,{b},0,0,0,100,100,0,0,3,18,0,8,90,90,300,1
Style: HookText,{s.font},{s.hook_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,{b},0,0,0,100,100,0,0,1,7,4,5,0,0,0,1
Style: Shape,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Counter,{s.font},150,{ass_color(s.highlight)},&H000000FF,&H00000000,&H64000000,{b},0,0,0,100,100,0,0,1,9,0,5,0,0,0,1
Style: EndCTA,{s.font},96,{ass_color(s.highlight)},&H000000FF,&H00000000,&H64000000,{b},0,0,0,100,100,0,0,1,6,0,5,0,0,0,1
Style: EndHandle,{s.font},58,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,4,0,5,0,0,0,1
Style: LowerName,{s.font},62,&H00111111,&H000000FF,{ass_color(s.highlight)},&H00000000,{b},0,0,0,100,100,0,0,3,14,0,7,0,0,0,1
Style: LowerTitle,{s.font},44,&H00FFFFFF,&H000000FF,&H28000000,&H00000000,0,0,0,0,100,100,0,0,3,12,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def pop_tag(base: int) -> str:
    """Pop animation: word small (85%) → swell (115%) → normal (100%), all within 0.15 s.
    'base' = the word's normal size (%), 120 for key words."""
    small, big = round(base * 0.85), round(base * 1.15)
    return rf"\fscx{small}\fscy{small}\t(0,70,\fscx{big}\fscy{big})\t(70,150,\fscx{base}\fscy{base})"


def highlighted_line(texts: list[str], active: int | None, style: CaptionStyle, emph: list[bool]) -> str:
    """A full line. The 'active' word is highlighted + pops. 'emph' words (picked by the AI) get their own color and size."""
    reset = f"{{\\1c{inline_color(style.color)}\\fscx100\\fscy100}}"
    parts = []
    for k, t in enumerate(texts):
        base = style.emphasis_scale if emph[k] else 100
        if k == active:
            if style.word_box:            # dark text on a colored box: no outline/shadow (keeps it readable)
                parts.append(f"{{\\1c{inline_color(style.highlight)}\\bord0\\shad0\\blur0}}{t}"
                             f"{{\\1c{inline_color(style.color)}\\bord{style.outline_width}\\shad{style.shadow}}}")
                continue
            color = style.emphasis_color if emph[k] else style.highlight
            pop = pop_tag(base) if style.pop else f"\\fscx{base}\\fscy{base}"
            parts.append(f"{{\\1c{inline_color(color)}{pop}}}{t}{reset}")
        elif emph[k]:
            parts.append(f"{{\\1c{inline_color(style.emphasis_color)}\\fscx{base}\\fscy{base}}}{t}{reset}")
        else:
            parts.append(t)
    return " ".join(parts)


def kinetic_hook(hook: str, anim: str) -> str:
    """Hook entry animation (ASS tags). All fade out over the last 0.25 s.
    \\an8 = top-center anchor, \\pos = position, \\move = move from one point to another."""
    x, y = round(cx_mid()), round(hook_top())
    if anim == "slide":       # slide down from above, then a small bounce
        return (rf"{{\an8\move({x},{y - 240},{x},{y},0,220)\t(220,300,\fscx108\fscy108)"
                rf"\t(300,380,\fscx100\fscy100)\fad(0,250)}}{hook}")
    if anim == "pop":         # grow from small to big, then settle
        return (rf"{{\an8\pos({x},{y})\fscx20\fscy20\t(0,160,\fscx112\fscy112)"
                rf"\t(160,260,\fscx100\fscy100)\fad(0,250)}}{hook}")
    if anim == "typewriter":  # words appear one by one (every 0.12 s)
        words = hook.split()
        shown = "".join(rf"{{\alpha&HFF&\t({i * 120},{i * 120 + 1},\alpha&H00&)}}{w} " for i, w in enumerate(words))
        return rf"{{\an8\pos({x},{y})\fad(0,250)}}" + shown.strip()
    return rf"{{\an8\pos({x},{y})\fad(200,250)}}{hook}"      # fade: gentle entrance


# ---------------- New hook: bold / pill / sticker ----------------

HOOK_MAX_W = 760          # maximum width of one hook line (out of 1080 on vertical)
HOOK_STAGGER = 90         # each next line appears this many ms later (not all at once, feels more alive)


def hook_max_w() -> float:
    """Max width of one hook line: 760 on vertical (of 1080), 1300 on landscape (of 1920)."""
    return 1300 if landscape() else HOOK_MAX_W


def rounded_rect(w: float, h: float, r: float) -> str:
    """ASS drawing (\\p1): a rounded box of w x h pixels. Corners are rounded with 'b' (bezier curves)."""
    w, h, r = round(w), round(h), round(min(r, h / 2, w / 2))
    return (f"m {r} 0 l {w - r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h - r} b {w} {h} {w} {h} {w - r} {h} "
            f"l {r} {h} b 0 {h} 0 {h} 0 {h - r} l 0 {r} b 0 0 0 0 {r} 0")


def wrap_hook(words: list[str], style: CaptionStyle, size: int | None = None,
              max_w: float | None = None) -> list[list[str]]:
    """Break the hook into lines: each narrower than max_w, and lines balanced (not one long, one short)."""
    from studio.fonts import text_width
    size = size or style.hook_size
    max_w = max_w or hook_max_w()
    width = lambda ws: text_width(" ".join(ws), style.font, size, style.bold)   # noqa: E731
    if width(words) <= max_w or len(words) < 2:
        return [words]
    from itertools import combinations
    best = None
    for n in (2, 3, 4):
        best = None
        # try every possible split and keep the one whose widest line is narrowest
        for cut in combinations(range(1, len(words)), n - 1):
            edges = (0, *cut, len(words))
            lines = [words[edges[k]:edges[k + 1]] for k in range(n)]
            widest = max(width(line) for line in lines)
            if best is None or widest < best[0]:
                best = (widest, lines)
        if best and best[0] <= max_w:
            return best[1]
    return best[1] if best else [words]


TOP_SAFE = 130     # no text above this (phone status bar / app buttons)


def behind_hook_ass(hook: str, style: CaptionStyle, seconds: float = 3.0, bottom_y: float = 640,
                    margin_v: int | None = None) -> str:
    """Separate ASS file for text-behind-person: a very big hook (up to 3 lines). The text's BOTTOM edge sits
    at the forehead (bottom_y), so most of the text shows above the head and only the bottom part hides behind
    it (still readable). Less room above (close-up) = smaller text. The render pastes the person (cut out with
    the mask) on top of this."""
    from studio.fonts import text_width
    hook = clean(hook)
    words = hook.upper().split() if style.uppercase or not has_urdu(hook) else hook.split()
    size = round(style.hook_size * 1.9)
    room = max(bottom_y - TOP_SAFE, 200)
    while True:            # the largest size with 3 lines or fewer that fits the width and the space above the head
        lines = wrap_hook(words, style, size, max_w=980)
        widest = max(text_width(" ".join(ln), style.font, size, style.bold) for ln in lines)
        if (len(lines) <= 3 and widest <= 1000 and len(lines) * size * 0.98 <= room) or size <= 80:
            break
        size -= 6
    line_h = size * 0.98
    top = max(TOP_SAFE, bottom_y - line_h * len(lines))
    hl = inline_color(style.hook_color)
    out = [ass_header(style, margin_v)]
    for k, ln in enumerate(lines):
        y = top + line_h * (k + 0.5)
        color = "&HFFFFFF&" if k % 2 == 0 else hl
        out.append(f"Dialogue: 3,{ass_time(0)},{ass_time(seconds)},HookText,,0,0,0,,"
                   f"{{{anim_tags('pop', cx_mid(), y, k * HOOK_STAGGER)}\\fs{size}\\1c{color}\\bord3\\shad0}}"
                   f"{font_tag(' '.join(ln))}{' '.join(ln)}\n")
    return "".join(out)


def key_words(words: list[str]) -> set[int]:
    """The hook's 1-2 important words (longest, 4+ letters): colored in the 'bold' look."""
    ranked = sorted(range(len(words)), key=lambda i: len(words[i].strip(".,!?'\"")), reverse=True)
    return {i for i in ranked[:2] if len(words[i].strip(".,!?'\"")) >= 4}


def anim_tags(anim: str, x: float, y: float, delay: int) -> str:
    """Entry animation (\\an5 = center anchor). Hidden for delay ms, then appears. Fades out at the end."""
    hide = rf"\alpha&HFF&\t({delay},{delay + 1},\alpha&H00&)" if delay else ""
    x, y = round(x), round(y)
    if anim == "slide":       # slide in from above with a small bounce
        return (rf"\an5\move({x},{y - 200},{x},{y},{delay},{delay + 220}){hide}"
                rf"\t({delay + 220},{delay + 300},\fscx108\fscy108)\t({delay + 300},{delay + 380},\fscx100\fscy100)"
                r"\fad(0,250)")
    if anim == "fade":
        return rf"\an5\pos({x},{y})\fad({200 + delay},250)"
    # pop (and the typewriter box): grow from small to big, then settle
    return (rf"\an5\pos({x},{y}){hide}\fscx20\fscy20\t({delay},{delay + 160},\fscx112\fscy112)"
            rf"\t({delay + 160},{delay + 260},\fscx100\fscy100)\fad(0,250)")


def hook_events(hook: str, style: CaptionStyle, anim: str, seconds: float) -> list[str]:
    """ASS lines for the hook (first 3 s), according to the style's hook_look."""
    from studio.fonts import text_width
    start, end = ass_time(0), ass_time(seconds)
    if style.hook_look == "box" or has_urdu(hook):        # classic black box (also used for Urdu script)
        return [f"Dialogue: 3,{start},{end},Hook,,0,0,0,,{font_tag(hook)}{kinetic_hook(hook, anim)}\n"]

    words = hook.upper().split() if style.uppercase and style.hook_look != "pill" else hook.split()
    lines = wrap_hook(words, style)
    line_h = style.hook_size * 1.12
    pad_x, pad_y = style.hook_size * 0.42, style.hook_size * 0.16
    top = hook_top() - 20
    out = []
    ink, bg = inline_color(style.hook_ink), inline_color(style.hook_bg)
    hl = inline_color(style.hook_color)

    if style.hook_look == "sticker":
        # one white (or style-colored) box behind all lines, tilted 3 degrees, popping in
        widths = [text_width(" ".join(ln), style.font, style.hook_size, style.bold) for ln in lines]
        bw, bh = max(widths) + 2 * pad_x, len(lines) * line_h + 2 * pad_y
        cx, cy = round(cx_mid()), top + bh / 2
        tilt = rf"\org({cx},{cy:.0f})\frz3"
        out.append(f"Dialogue: 2,{start},{end},Shape,,0,0,0,,{{{anim_tags('pop', cx, cy, 0)}{tilt}\\1c{bg}"
                   f"\\bord0\\shad6\\4c&H000000&\\4a&H70&\\p1}}{rounded_rect(bw, bh, 26)}\n")
        for k, ln in enumerate(lines):
            y = cy - bh / 2 + pad_y + line_h * (k + 0.5)
            text = " ".join(ln)
            out.append(f"Dialogue: 3,{start},{end},HookText,,0,0,0,,{{{anim_tags('pop', cx, y, 0)}{tilt}"
                       f"\\1c{ink}\\bord0\\shad0}}{text}\n")
        return out

    for k, ln in enumerate(lines):
        y = top + line_h * (k + 0.5) + (k * pad_y * 2.2 if style.hook_look == "pill" else 0)
        delay = k * HOOK_STAGGER
        text = " ".join(ln)
        if style.hook_look == "pill":
            # TikTok look: each line in its own colored rounded box, dark text
            w = text_width(text, style.font, style.hook_size, style.bold) + 2 * pad_x
            out.append(f"Dialogue: 2,{start},{end},Shape,,0,0,0,,{{{anim_tags(anim if anim != 'typewriter' else 'pop', cx_mid(), y, delay)}"
                       f"\\1c{bg}\\bord0\\shad5\\4c&H000000&\\4a&H80&\\p1}}"
                       f"{rounded_rect(w, line_h + pad_y, 22)}\n")
            out.append(f"Dialogue: 3,{start},{end},HookText,,0,0,0,,{{{anim_tags(anim if anim != 'typewriter' else 'pop', cx_mid(), y, delay)}"
                       f"\\1c{ink}\\bord0\\shad0}}{text}\n")
        else:
            # bold: no box, thick white text, thick black outline + shadow, key words in the style's color
            first = sum(len(lines[j]) for j in range(k))
            keys = key_words(words)
            colored = " ".join(f"{{\\1c{hl}}}{wd}{{\\1c&HFFFFFF&}}" if first + j in keys else wd
                               for j, wd in enumerate(ln))
            out.append(f"Dialogue: 3,{start},{end},HookText,,0,0,0,,{{{anim_tags(anim if anim != 'typewriter' else 'pop', cx_mid(), y, delay)}}}"
                       f"{colored}\n")
    return out


def in_order(words: list[dict]) -> list[dict]:
    """Whisper sometimes gives a word a start time before the previous word's (e.g. 'TRAINING' 19.96 while the
    word before it, 'KI', is 20.32). That puts two caption lines on screen at once. Make sure no word starts
    before the previous one, changing only that (word order stays the same)."""
    fixed, prev = [], 0.0
    for w in words:
        start = max(w["start"], prev)
        fixed.append({**w, "start": start, "end": max(w["end"], start)})
        prev = start
    return fixed


LOWER_START, LOWER_SECONDS = 3.2, 3.5     # appears after the hook, stays 3.5 seconds


def lower_third(name: str, title: str, y: int) -> list[str]:
    """Name lower third: slides in from the left, name on top (colored box), title below.
    Returns: ASS Dialogue lines."""
    name, title = clean(name), clean(title)
    if not name:
        return []
    start, end = ass_time(LOWER_START), ass_time(LOWER_START + LOWER_SECONDS)
    lines = [f"Dialogue: 2,{start},{end},LowerName,,0,0,0,,"
             f"{{\\move(-700,{y},70,{y},0,300)\\fad(0,300)}}{font_tag(name)}{name}\n"]
    if title:
        ty = y + 100
        lines.append(f"Dialogue: 2,{start},{end},LowerTitle,,0,0,0,,"
                     f"{{\\move(-700,{ty},70,{ty},120,420)\\fad(0,300)}}{font_tag(title)}{title}\n")
    return lines


END_SECONDS = 2.5          # end screen kitni der
LOGO_CENTER_Y = 700        # center of the logo (on the end screen)


def end_card_lines(start: float, cta: str, handle: str, has_logo: bool) -> list[str]:
    """End screen text: CTA (e.g. 'Follow for more') with a pop, @handle below with a fade."""
    cta, handle = clean(cta), clean(handle)
    y = round(CANVAS["h"] * (0.536 if has_logo else 0.458))     # vertical: 1030 / 880 (out of 1920)
    end = ass_time(start + END_SECONDS)
    lines = []
    if cta:
        pop = r"\fscx30\fscy30\t(0,160,\fscx112\fscy112)\t(160,260,\fscx100\fscy100)"
        lines.append(f"Dialogue: 4,{ass_time(start + 0.15)},{end},EndCTA,,0,0,0,,"
                     f"{{\\an5\\pos({round(cx_mid())},{y}){pop}}}{font_tag(cta)}{cta}\n")
    if handle:
        lines.append(f"Dialogue: 4,{ass_time(start + 0.45)},{end},EndHandle,,0,0,0,,"
                     f"{{\\an5\\pos({round(cx_mid())},{y + 115})\\fad(250,0)}}{font_tag(handle)}{handle}\n")
    return lines


def words_to_ass(words: list[dict], hook_text: str = "", hook_seconds: float = 3.0,
                 style: CaptionStyle | str = DEFAULT_STYLE, emphasis: set[float] | None = None,
                 hook_anim: str | None = None, margin_v: int | None = None,
                 lower: tuple[str, str, int] | None = None, extra: list[str] | None = None) -> str:
    """Reel-style captions: each word highlights + pops as it's spoken. Hook text on top (first 3 s).
    emphasis = original start times (orig_start) of the AI-picked key words."""
    if isinstance(style, str):
        style = STYLES.get(style, STYLES[DEFAULT_STYLE])
    emphasis = {round(t, 2) for t in (emphasis or set())}

    lines = [ass_header(style, margin_v)]
    if lower:                                   # (naam, title, y)
        lines += lower_third(*lower)
    lines += extra or []                        # extra ASS lines, e.g. the number counter

    if hook_text:
        lines += hook_events(clean(hook_text), style, hook_anim or style.hook_anim, hook_seconds)

    words = in_order(words)
    n = style.max_words
    mv = caption_margin(style.margin_v) if margin_v is None else margin_v
    for i in range(0, len(words), n):
        chunk = words[i:i + n]
        texts = [clean(w["word"]) for w in chunk]
        if style.uppercase:
            texts = [t.upper() for t in texts]
        emph = [round(w.get("orig_start", -1), 2) in emphasis for w in chunk]
        ftag = font_tag(" ".join(texts)) + (f"{{\\blur{style.glow}}}" if style.glow else "")
        boxes = word_boxes(texts, style, mv) if style.word_box and not has_urdu(" ".join(texts)) else None
        # when the next line starts: this line must end before it, so two lines never show at once
        next_start = words[i + n]["start"] if i + n < len(words) else None

        # simple style (no pop, no highlight): the whole line at once (key words still colored)
        if not style.pop and style.highlight == style.color:
            end = chunk[-1]["end"] if next_start is None else min(chunk[-1]["end"], next_start)
            if ass_time(end) <= ass_time(chunk[0]["start"]):    # must not be zero even after rounding (0.01 s)
                continue
            lines.append(f"Dialogue: 1,{ass_time(chunk[0]['start'])},{ass_time(end)},"
                         f"Caption,,0,0,0,,{ftag}{highlighted_line(texts, None, style, emph)}\n")
            continue

        # one 'slice' per word: from this word's start to the next word's start
        for k, w in enumerate(chunk):
            start = w["start"]
            if k + 1 < len(chunk):
                end = chunk[k + 1]["start"]
            else:
                end = w["end"] if next_start is None else min(w["end"], next_start)
            # this word has zero duration: skip it. Compare ROUNDED times (0.01 s, as written to the file):
            # 15.341 and 15.344 both became "0:00:15.34" and produced a zero-length line, and FFmpeg would then
            # drop another line (e.g. the hook's first line)
            if ass_time(end) <= ass_time(start):
                continue
            if boxes:                 # colored rounded box behind the spoken word (a layer below the text)
                bx, by, bw, bh = boxes[k]
                lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Shape,,0,0,0,,"
                             f"{{\\an5\\pos({bx:.0f},{by:.0f})\\1c{inline_color(style.word_box)}\\bord0\\shad0"
                             f"\\fscx92\\fscy92\\t(0,80,\\fscx100\\fscy100)\\p1}}{rounded_rect(bw, bh, 18)}\n")
            lines.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,"
                         f"{ftag}{highlighted_line(texts, k, style, emph)}\n")
    return "".join(lines)


def word_boxes(texts: list[str], style: CaptionStyle, margin_v: int) -> list[tuple] | None:
    """Box position for each word (center x, center y, width, height). If the line is too wide (libass would
    wrap it), returns None: the box would land in the wrong place, so no box at all."""
    from studio.fonts import text_width
    widths = [text_width(t, style.font, style.size, style.bold) for t in texts]
    space = text_width(" ", style.font, style.size, style.bold)
    total = sum(widths) + space * (len(texts) - 1)
    if total > CANVAS["w"] - 2 * 60 - 20:
        return None
    x, cy = cx_mid() - total / 2, CANVAS["h"] - margin_v - style.size * 0.5
    out = []
    for w in widths:
        out.append((x + w / 2, cy, w + style.size * 0.24, style.size * 0.98))
        x += w + space
    return out
