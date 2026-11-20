"""Teaser (cold open): the clip's strongest line, spoken by the guest, played for 1-4 s BEFORE the clip.
Viewers hear the 'punch' in the first second, then stay for the full story.
Most viral Shorts/Reels do this."""
from pydantic import BaseModel, Field

from studio.clipper import ask_with_fallback

MIN_SECONDS = 1.2
MAX_SECONDS = 4.5
SKIP_START = 4.0     # don't take the teaser from the first seconds of the clip (they play at the start anyway)


class TeaserPick(BaseModel):
    start: int = Field(description="number of the FIRST word of the teaser line")
    end: int = Field(description="number of the LAST word of the teaser line (inclusive)")
    reason: str = Field(default="", description="one short sentence: why this line stops the scroll")


def build_prompt(words: list[dict], clip_start: float) -> str:
    lines = "\n".join(f"{i}|{w['start'] - clip_start:.1f}s {w['word'].strip()}" for i, w in enumerate(words))
    return f"""You edit viral Shorts. Before the clip starts we play a 1-4 second TEASER: the single most powerful line
the speaker says later in this clip (a "cold open"). It must make a fast-scrolling viewer stop and need to hear the rest.

Pick ONE line from the numbered words below (format: number|seconds-into-clip word):
- A bold claim, shocking reveal, strong emotion, confession or punchline. Not a question to the host, not filler.
- 3 to 12 words, a complete phrase on its own (starts and ends at natural speech boundaries), {MIN_SECONDS}-{MAX_SECONDS} seconds long.
- Must start after {SKIP_START:.0f}s (the clip's opening plays right after anyway).
- Do not give away the full answer: tease it.

Return the first and last word numbers.

Words:
{lines}
"""


def build_opening_prompt(words: list[dict], clip_start: float) -> str:
    lines = "\n".join(f"{i}|{w['start'] - clip_start:.1f}s {w['word'].strip()}" for i, w in enumerate(words))
    return f"""You edit viral Shorts. The Short must START on the speaker's hook line: the very first words viewers hear
must be the strongest scroll-stopping thing the speaker says (a bold claim, painful truth, surprising statement or
emotional line). Everything before that line is cut off.

Pick that OPENING line from the numbered words below (format: number|seconds-into-clip word):
- 3 to 14 words, a complete phrase that makes sense as the first thing heard (starts at a natural speech boundary).
- It must be in the FIRST HALF of the words, so enough of the story remains after it.
- Prefer a line that creates curiosity or tension for what follows. Not a question to the host, not filler.

Return the first and last word numbers.

Words:
{lines}
"""


def find_opening(words: list[dict], clip_start: float, log=print) -> list[float] | None:
    """The clip's 'spoken hook': the sentence the Short STARTS on (everything before it is cut).
    Returns: [start, end] in the source video, or None (clip unchanged)."""
    words = [w for w in words if w["word"].strip()]
    if len(words) < 10:
        return None
    log("     AI is picking the opening hook sentence (the Short starts here)...")
    pick = ask_with_fallback(build_opening_prompt(words, clip_start), TeaserPick, log, temperature=0.3)
    s, e = sorted((pick.start, pick.end))
    if not 0 <= s < len(words) or s > len(words) * 0.6:      # past the halfway point too little of the story would remain
        return None
    e = min(max(e, s + 2), len(words) - 1)
    while e > s + 2 and words[e]["end"] - words[s]["start"] > 6.0:   # keep the hook from getting too long
        e -= 1
    a, b = words[s]["start"] - 0.05, words[e]["end"] + 0.1
    log(f"     Short starts with: \"{' '.join(w['word'].strip() for w in words[s:e + 1])}\"")
    return [round(a, 3), round(b, 3)]


def find_teaser(words: list[dict], clip_start: float, log=print) -> list[float] | None:
    """Clip words (original times) → teaser (start, end) in the source video. None if not found."""
    words = [w for w in words if w["word"].strip()]
    if len(words) < 8:
        return None
    log("     AI is picking the teaser (strongest line)...")
    pick = ask_with_fallback(build_prompt(words, clip_start), TeaserPick, log, temperature=0.3)
    s, e = sorted((pick.start, pick.end))
    if not 0 <= s < len(words):
        return None
    e = min(e, len(words) - 1)

    # too short: add following words; too long: drop the last words (whole words only)
    while e + 1 < len(words) and words[e]["end"] - words[s]["start"] < MIN_SECONDS:
        e += 1
    while e > s and words[e]["end"] - words[s]["start"] > MAX_SECONDS:
        e -= 1
    a, b = words[s]["start"] - 0.06, words[e]["end"] + 0.15
    if b - a < MIN_SECONDS * 0.8 or words[s]["start"] - clip_start < 1.0:
        return None
    log(f"     Teaser: \"{' '.join(w['word'].strip() for w in words[s:e + 1])}\" ({b - a:.1f}s)")
    return [round(a, 3), round(b, 3)]
