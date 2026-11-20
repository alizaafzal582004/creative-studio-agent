"""Converting Urdu/Hindi-script captions to Roman Urdu (Latin letters).
Each word is converted on its own, so every word keeps its start/end time and captions stay in sync."""
import json
import time
from pathlib import Path

from google.genai import types
from pydantic import BaseModel

import re

from studio.clipper import (GEMINI_SMALL_TIMEOUT, make_client, models_to_try, note_gemini_failure, is_blocked, block, groq_wait,
                            groq_slots, GROQ_MAX_WAIT)
from studio.config import GROQ_TEXT_MODEL

BATCH = 300  # words sent to Gemini per request
ROUNDS = 3   # rounds of retrying all models when Gemini is busy (503)
WAIT = 20    # seconds to wait before each round
GROQ_MODEL = GROQ_TEXT_MODEL  # backup when Gemini is busy


class RomanWords(BaseModel):
    words: list[str]


def needs_roman(words: list[dict]) -> bool:
    """Does the transcript contain Urdu/Arabic or Hindi (Devanagari) script?"""
    return any("؀" <= ch <= "ۿ" or "ऀ" <= ch <= "ॿ" for w in words for ch in w["word"])


def build_prompt(items: list[str]) -> str:
    return f"""Transliterate every item of this JSON list into Roman Urdu: Urdu written with English letters,
the way Pakistanis type on WhatsApp (e.g. "نہیں" -> "nahi", "سمجھ" -> "samajh", "ہے" -> "hai", "میں" -> "mein").
- English words written in Urdu script become normal English spelling ("سائن" -> "sign", "ٹیچرز" -> "teachers").
- Items already in English letters stay as they are. Keep punctuation and numbers.
- Return exactly {len(items)} items in the same order: one output per input item. Never merge, split or skip items.

Items:
{json.dumps(items, ensure_ascii=False)}
"""


def ask_groq(items: list[str], model: str = GROQ_MODEL, api_key: str | None = None) -> list[str]:
    """Same job on Groq. One numbered word per line ('12. nahi'); the numbers map answers back to words."""
    from groq import Groq
    from studio.config import GROQ_API_KEY

    numbered = "\n".join(f"{i + 1}. {w}" for i, w in enumerate(items))
    prompt = (build_prompt(items).split("Items:")[0]
              + f"Reply with exactly {len(items)} lines in the format 'N. roman', nothing else.\n\nItems:\n{numbered}")
    client = Groq(api_key=api_key or GROQ_API_KEY, timeout=120, max_retries=0)
    response = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        temperature=0.1, reasoning_effort="low",
    )
    found: dict[int, str] = {}
    for line in response.choices[0].message.content.splitlines():
        num, dot, text = line.strip().partition(". ")
        if dot and num.isdigit():
            found[int(num)] = text.strip()
    return [found[i + 1] for i in range(len(items)) if i + 1 in found]


def ask(client, items: list[str], log=print) -> list[str]:
    """A list of words in Roman Urdu. Latency: Groq first (small job, 1-3 s), then Gemini (up to 30 s)."""
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=RomanWords,
        temperature=0.1,
    )
    for attempt in range(ROUNDS):
        if attempt:
            log(f"     AI is busy, retrying in {WAIT}s...")
            time.sleep(WAIT)

        # Groq text models first (those with quota left): fastest for small jobs
        for model, groq_model, key in [s for s in groq_slots() if not is_blocked(s[0])]:
            t0 = time.time()
            try:
                result = ask_groq(items, groq_model, key)
                if len(result) == len(items):
                    log(f"     Groq ({model}) done ({time.time() - t0:.0f}s)")
                    return [w.strip() or orig for w, orig in zip(result, items)]
                log(f"     Warning: Groq {model}: got {len(result)} words, needed {len(items)}.")
            except Exception as e:
                msg = re.sub(r"org_\w+", "org_***", str(e))
                log(f"     Warning: Groq {model} failed ({time.time() - t0:.0f}s): {type(e).__name__}: {msg[:120]}")
                wait = groq_wait(e)
                if getattr(e, "status_code", None) == 401:
                    block(model, 24 * 3600, log, "invalid API key", persist=False)
                elif wait is not None and wait > GROQ_MAX_WAIT:
                    block(model, wait, log, "token limit reached")

        # Backup: Gemini
        for model in models_to_try(client):
            if model.startswith("gemini-3"):
                config.thinking_config = types.ThinkingConfig(thinking_level="LOW")
            t0 = time.time()
            try:
                response = client.models.generate_content(model=model, contents=build_prompt(items), config=config)
                result = response.parsed or RomanWords.model_validate_json(response.text)
                if len(result.words) == len(items):
                    return [w.strip() or orig for w, orig in zip(result.words, items)]
                log(f"     Warning: {model}: got {len(result.words)} words, needed {len(items)}.")
            except Exception as e:
                log(f"     Warning: {model} failed ({time.time() - t0:.0f}s): {type(e).__name__}: {str(e)[:120]}")
                note_gemini_failure(model, e, log)
    raise RuntimeError("Roman Urdu conversion failed (AI busy). Run again in a little while: "
                       "progress so far is saved and will resume from there.")


def romanize_texts(texts: list[str], log=print) -> list[str]:
    """Whole sentences (e.g. hook text) in Roman Urdu. Text already in Latin letters is kept as is."""
    if not needs_roman([{"word": t} for t in texts]):
        return texts
    log("     Converting hook text to Roman Urdu...")
    return ask(make_client(GEMINI_SMALL_TIMEOUT * 1000), texts, log)


def load_cache(cache_path: Path, n_words: int) -> dict[int, str]:
    """Cache: {word index: roman}. Older cache files (a full list) still load."""
    if not cache_path.exists():
        return {}
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    if isinstance(cached, list):
        return dict(enumerate(cached)) if len(cached) <= n_words else {}
    return {int(k): v for k, v in cached.items() if int(k) < n_words}


def romanize(words: list[dict], cache_path: Path, log=print,
             ranges: list[tuple[float, float]] | None = None) -> list[dict]:
    """Words in Roman Urdu (same timing). Cached once converted, to save API quota.
    With ranges (e.g. the chosen clips) only those words are converted: saves a lot of time on a 1-hour video."""
    if not needs_roman(words):
        log("     (captions are already in Latin letters)")
        return words

    # reuse what was converted last time, send only the remaining words to the AI
    roman = load_cache(cache_path, len(words))
    needed = [i for i, w in enumerate(words)
              if i not in roman and (ranges is None or any(a - 1 <= w["start"] <= b + 1 for a, b in ranges))]
    if not needed:
        log("     (found saved Roman Urdu, reusing it)")
    else:
        client = make_client(GEMINI_SMALL_TIMEOUT * 1000)
        for k in range(0, len(needed), BATCH):
            chunk = needed[k:k + BATCH]
            log(f"     Writing Roman Urdu ({min(k + BATCH, len(needed))}/{len(needed)} words)...")
            roman.update(zip(chunk, ask(client, [words[i]["word"].strip() for i in chunk], log)))
            cache_path.write_text(json.dumps({str(i): r for i, r in sorted(roman.items())}, ensure_ascii=False,
                                             indent=1), encoding="utf-8")

    # converted words become Roman; the rest (outside the clips) stay original and are never shown
    return [{**w, "word": roman.get(i, w["word"])} for i, w in enumerate(words)]
