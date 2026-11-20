"""AI keyword highlights + emoji: Gemini picks the 'punch' words in each clip, some with an emoji."""
from pydantic import BaseModel, Field

from studio.clipper import ask_with_fallback
from studio.emoji import emoji_map, find_png

# These words are never 'punch' words (English, Urdu, Roman Urdu)
FILLERS = ("the, a, and, is, to, of, it, "
           "hai, hain, ka, ki, ke, ko, aur, se, mein, bhi, "
           "yeh, ye, woh, wo, matlab, bas, toh, to, phir, jo, keh, ki, kya, na, hum, aap, "
           "le, lo, de, do, kiya, kar, karna, raha, rahe, rahi, tha, thi, the, gaya, gayi, ho, hota, hoti")
FILLER_SET = {f.strip() for f in FILLERS.split(",")}


def is_filler(word: str) -> bool:
    return word.strip(" .,!?;:'\"").lower() in FILLER_SET


class Mark(BaseModel):
    index: int = Field(description="the number shown before the word")
    emoji: str = Field(description="one emoji from the allowed list, or empty string for no emoji")


class Marks(BaseModel):
    marks: list[Mark]


def build_prompt(words: list[dict], allowed: list[str], max_marks: int) -> str:
    numbered = " ".join(f"{i}:{w['word'].strip()}" for i, w in enumerate(words))
    emoji_rule = (f"For about half of the picked words, add ONE fitting emoji from this list only: {' '.join(allowed)}\n"
                  "Use an empty string when no emoji fits. Do not repeat the same emoji."
                  if allowed else "Do not add any emoji: always use an empty string.")
    return f"""You are a short-form video editor adding emphasis to animated captions.
Below are the words of one short clip, each with its number.

Pick at most {max_marks} words to EMPHASIZE: numbers, money, results, strong emotions, surprising or key words.
Never pick filler words ({FILLERS}).
{emoji_rule}

Words:
{numbered}
"""


# No emoji in the video (key words are only colored). Set to True to bring them back.
VIDEO_EMOJI = False


def find_emphasis(words: list[dict], log=print) -> list[dict]:
    """Returns: [{'start': <word's original time>, 'word': 'word', 'emoji': '🔥' or ''}]"""
    if not words:
        return []
    allowed = list(emoji_map()) if VIDEO_EMOJI else []
    duration = words[-1]["end"] - words[0]["start"]
    max_marks = max(1, int(duration / 4))          # about one key word every ~4 seconds

    log("     AI is picking key words" + (" + emoji" if allowed else "") + "...")
    result = ask_with_fallback(build_prompt(words, allowed, max_marks), Marks, log, temperature=0.3)

    # don't trust the AI blindly: drop bad indexes, repeated words and emoji outside the list
    marks, seen, used_emoji = [], set(), set()
    for m in result.marks:
        if not 0 <= m.index < len(words) or m.index in seen:
            continue
        if is_filler(words[m.index]["word"]):   # AI picked a filler word despite being told not to
            continue
        seen.add(m.index)
        emoji = m.emoji.strip()
        if emoji and (not find_png(emoji) or emoji in used_emoji):
            emoji = ""
        used_emoji.add(emoji)
        w = words[m.index]
        marks.append({"start": w["start"], "word": w["word"].strip(), "emoji": emoji})
        if len(marks) >= max_marks:
            break
    return marks
