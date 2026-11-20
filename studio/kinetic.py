"""Number counter: when a number is spoken ("$100k", "50%", "10,000"), it pops up big and counts up from 0.
Numbers are found in the transcript with a regex, so no AI call is needed."""
import re
from dataclasses import dataclass

from studio.captions import CANVAS, ass_time
from studio.styles import CaptionStyle, inline_color

COUNT_SECONDS = 0.6      # time to count from 0 up to the number
HOLD_SECONDS = 0.9       # how long the full number stays
STEPS = 14               # number of counting steps
COUNTER_Y = 760          # vertical position on screen (out of 1920)

URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
NUMBER = re.compile(r"^(?P<pre>[$₹£€]|rs\.?|pkr)?(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?"
                    r"(?P<suf>k|m|b|bn|%|\+|x)?$", re.IGNORECASE)


@dataclass
class Number:
    prefix: str
    value: float
    decimals: int
    commas: bool
    suffix: str

    def show(self, v: float) -> str:
        """Format any value in this number's style: '$37K', '12.5%', '37,500'."""
        body = f"{v:,.{self.decimals}f}" if self.commas else f"{v:.{self.decimals}f}"
        return f"{self.prefix}{body}{self.suffix}"


def parse_number(word: str) -> Number | None:
    """Number if the word is a number, else None. Skips small numbers (under 10) and years (1900-2100)."""
    text = word.strip().translate(URDU_DIGITS).strip(".,!?;:\"'()")
    m = NUMBER.match(text)
    if not m:
        return None
    raw = m["num"].replace(",", "")
    value = float(raw + (m["dec"] or ""))
    pre, suf = m["pre"] or "", m["suf"] or ""
    has_unit = bool(pre or suf)
    if not has_unit and (value < 10 or (1900 <= value <= 2100 and "," not in m["num"])):
        return None
    decimals = len(m["dec"]) - 1 if m["dec"] else 0
    return Number(pre, value, decimals, "," in m["num"] or (value >= 10_000 and not suf), suf)


def find_counters(words: list[dict], max_count: int = 3, min_gap: float = 3.0) -> list[tuple[float, Number]]:
    """Find numbers in the clip's words (new timeline). Returns: [(time, Number), ...]"""
    found, last = [], -10.0
    for w in words:
        n = parse_number(w["word"])
        if n and w["start"] - last >= min_gap:
            found.append((w["start"], n))
            last = w["start"]
            if len(found) >= max_count:
                break
    return found


def ease_out(p: float) -> float:
    """Fast at first, slow at the end (like a car braking)."""
    return 1 - (1 - p) ** 3


def counter_lines(counters: list[tuple[float, Number]], style: CaptionStyle) -> list[str]:
    """ASS lines for each number: STEPS short lines (the count), then the final number with a pop."""
    color = inline_color(style.highlight)
    pos = rf"{{\an5\pos({CANVAS['w'] // 2},{round(CANVAS['h'] * COUNTER_Y / 1920)})\1c{color}}}"
    lines = []
    for at, n in counters:
        step = COUNT_SECONDS / STEPS
        for k in range(STEPS):
            v = n.value * ease_out(k / STEPS)
            lines.append(f"Dialogue: 3,{ass_time(at + k * step)},{ass_time(at + (k + 1) * step)},"
                         f"Counter,,0,0,0,,{pos}{n.show(v)}\n")
        land = at + COUNT_SECONDS
        pop = r"\fscx100\fscy100\t(0,80,\fscx122\fscy122)\t(80,200,\fscx100\fscy100)\fad(0,200)"
        lines.append(f"Dialogue: 3,{ass_time(land)},{ass_time(land + HOLD_SECONDS)},Counter,,0,0,0,,"
                     f"{{\\an5\\pos({CANVAS['w'] // 2},{round(CANVAS['h'] * COUNTER_Y / 1920)})\\1c{color}{pop}}}{n.show(n.value)}\n")
    return lines
