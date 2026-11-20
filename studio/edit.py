"""Silence removal: use word timestamps to find the pauses and keep only the spoken parts."""


MAX_CUT = 3.0   # never cut a 'pause' longer than this: it's usually a stretch Whisper skipped (people are still talking,
                # the words just weren't transcribed) or a deliberate dramatic pause. Cutting either is wrong.


def keep_ranges(words: list[dict], start: float, end: float,
                max_gap: float = 0.6, pad: float = 0.12) -> list[tuple[float, float]]:
    """Spoken ranges inside a clip. A pause longer than max_gap (and shorter than MAX_CUT) between words is cut."""
    ws = [w for w in words if w["start"] >= start and w["end"] <= end]
    if not ws:
        return [(start, end)]

    ranges = []
    cur_start = max(start, ws[0]["start"] - pad)
    cur_end = ws[0]["end"]
    for w in ws[1:]:
        if max_gap < w["start"] - cur_end <= MAX_CUT:   # found a pause (not too long)
            ranges.append((cur_start, min(cur_end + pad, end)))
            cur_start = w["start"] - pad
        cur_end = w["end"]
    ranges.append((cur_start, min(cur_end + pad, end)))
    return ranges


def split_at_sentences(ranges: list[tuple[float, float]], segments: list[dict],
                       min_len: float = 1.0) -> list[tuple[float, float]]:
    """Split long ranges at sentence (segment) boundaries so the camera can switch speakers per sentence."""
    cuts = sorted(s["start"] for s in segments)
    pieces = []
    for a, b in ranges:
        current = a
        for c in cuts:
            if current + min_len <= c <= b - min_len:
                pieces.append((current, c))
                current = c
        pieces.append((current, b))
    return pieces


def remap_words(words: list[dict], ranges: list[tuple[float, float]]) -> list[dict]:
    """New timeline after cutting silences: each word's time in the new video."""
    out = []
    offset = 0.0
    for a, b in ranges:
        for w in words:
            if w["start"] >= a and w["end"] <= b:
                out.append({"word": w["word"], "start": w["start"] - a + offset, "end": w["end"] - a + offset,
                            "orig_start": w["start"]})   # keep the original time (AI marks are matched on it)
        offset += b - a
    return out


def words_inside(words: list[dict], ranges: list[tuple[float, float]]) -> list[dict]:
    """Only the words inside the kept ranges, with their original times."""
    return [w for w in words if any(a <= w["start"] and w["end"] <= b for a, b in ranges)]


def total(ranges: list[tuple[float, float]]) -> float:
    return sum(b - a for a, b in ranges)


def plan_zooms(shots: list[tuple[float, float, float]], punch: float = 1.12) -> list[float]:
    """Zoom punch-in: alternate between 'wide' (1.0) and 'close' (1.12) on every cut to hide the jump cut.
    When the camera switches to another person, go back to wide (that is already a big cut). Skip very short shots."""
    zooms, current = [], 1.0
    for k, (a, b, cx) in enumerate(shots):
        if k == 0 or abs(cx - shots[k - 1][2]) > 0.05:
            current = 1.0
        elif b - a >= 0.8:
            current = punch if current == 1.0 else 1.0
        zooms.append(current)
    return zooms
