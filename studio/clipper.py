import json
import math
import os
import re
import time
from pathlib import Path

from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from studio.config import GEMINI_API_KEY, GROQ_API_KEY, GROQ_API_KEYS, GROQ_TEXT_MODEL


# ---------- Shape of the AI's answer (schema) ----------

class Clip(BaseModel):
    start: float = Field(description="clip start time in seconds, from the transcript")
    end: float = Field(description="clip end time in seconds, from the transcript")
    hook_score: int = Field(description="0-100: how likely viewers keep watching after the first 3 seconds")
    reason: str = Field(description="one sentence: why this moment works, and its weakness if any")
    category: str = Field(default="", description="the video's niche, e.g. podcast, education, motivation, business")
    hook_formula: str = Field(default="", description="which proven hook formula from the playbook was used")
    hook_text: str = Field(description="on-screen hook text, max 8 words, the strongest scroll-stopping line")
    title: str = Field(description="YouTube Shorts title, under 60 characters, same language as the video")
    thumb_text: str = Field(default="", description="2-4 word thumbnail text: punchy, makes sense alone, "
                                                    "creates curiosity, true to the clip")
    description: str = Field(description="1-2 sentence description with searchable keywords")
    hashtags: list[str] = Field(description="5-8 hashtags, include #shorts")


class ClipPlan(BaseModel):
    clips: list[Clip]


# ---------- Model chunna ----------

SKIP_WORDS = ("image", "tts", "audio", "live", "embedding", "thinking", "learnlm", "robotics", "omni", "banana")


def available_models(client: genai.Client) -> list[str]:
    """All models that can generate text (generateContent)."""
    names = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions:
            names.append(m.name.removeprefix("models/"))
    return names


_MODEL_LIST: list[str] | None = None    # fetch the model list once (saves a network call on every AI step)


def ranked_models(client: genai.Client) -> list[str]:
    """Flash models, best first: stable > preview, newer version > older, lite last."""
    global _MODEL_LIST
    if _MODEL_LIST is None:
        _MODEL_LIST = available_models(client)
    flash = [n for n in _MODEL_LIST
             if n.startswith("gemini-") and "flash" in n and not any(w in n for w in SKIP_WORDS)]

    def rank(name: str):
        version = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
        is_full = "lite" not in name
        is_stable = not any(w in name for w in ("preview", "exp", "latest"))
        return (is_full, is_stable, float(version.group(1)) if version else 0.0)

    return sorted(flash, key=rank, reverse=True)


def pick_model(client: genai.Client) -> str:
    """GEMINI_MODEL from .env if set, otherwise the best Flash model."""
    chosen = os.getenv("GEMINI_MODEL")
    if chosen:
        return chosen
    ranked = ranked_models(client)
    if not ranked:
        raise RuntimeError("No Gemini Flash model found. Run 'python main.py models' to see the list.")
    return ranked[0]


def models_to_try(client: genai.Client | None, limit: int = 3) -> list[str]:
    """Fallback order if the first model fails (no duplicates). Models that are out of quota are skipped.
    No Gemini key (client None): empty list, so callers go straight to Groq."""
    if client is None:
        return []
    order = [pick_model(client)] + ranked_models(client)
    unique = list(dict.fromkeys(order))
    return [m for m in unique[:limit] if not is_blocked(m)]


# ---------- Remember blocked models (lower latency: don't retry models that will just fail again) ----------

BLOCKS_FILE = Path(__file__).resolve().parent.parent / "output" / "_ai_limits.json"
_BLOCKED: dict[str, float] = {}     # model -> kab tak band (time.time())


def _load_blocks() -> None:
    try:
        saved = json.loads(BLOCKS_FILE.read_text(encoding="utf-8"))
        _BLOCKED.update({k: v for k, v in saved.items() if v > time.time()})
    except Exception:
        pass


def is_blocked(model: str) -> bool:
    return _BLOCKED.get(model, 0) > time.time()


def block(model: str, seconds: float, log=print, why: str = "limit", persist: bool = True) -> None:
    """Block a model for a while. Long blocks (daily limit) are also saved to a file so the next run skips it too.
    persist=False: only for this process (e.g. a bad key: works again on the next run once fixed)."""
    _BLOCKED[model] = time.time() + seconds
    log(f"     Paused {model}: {why}, " + (f"skipped for the next {seconds / 60:.0f} min" if persist else "skipped for this run"))
    if seconds >= 300 and persist:
        try:
            BLOCKS_FILE.parent.mkdir(exist_ok=True)
            BLOCKS_FILE.write_text(json.dumps({k: v for k, v in _BLOCKED.items() if v > time.time()}), encoding="utf-8")
        except Exception:
            pass


def gemini_block_seconds(e: Exception) -> tuple[float, str] | None:
    """From a Gemini error: how long to block. None = ordinary error, don't block."""
    text = str(e)
    if "RESOURCE_EXHAUSTED" in text or " 429" in text:
        if "PerDay" in text or "per day" in text.lower():
            return 3600, "daily limit reached"
        delay = re.search(r"retryDelay['\"]?:\s*['\"](\d+)", text)
        return (max(60, float(delay.group(1))) if delay else 600), "limit reached"
    if "DEADLINE_EXCEEDED" in text or "504" in text or "timed out" in text.lower():
        return 600, "reply took too long (time-out)"
    if "UNAVAILABLE" in text or "503" in text:
        return 120, "server busy"
    return None


def note_gemini_failure(model: str, e: Exception, log=print) -> None:
    found = gemini_block_seconds(e)
    if found:
        block(model, found[0], log, found[1])


_load_blocks()


# ---------- Helpers ----------

def transcript_with_times(data: dict) -> str:
    """Join segments as '[12.3 - 15.8] text' so the AI knows the timing."""
    return "\n".join(
        f"[{s['start']:.1f} - {s['end']:.1f}] {s['text'].strip()}" for s in data.get("segments", [])
    )


# The hook formulas that bring the most views on viral Shorts/Reels/TikTok, and which wins in which category
HOOK_PLAYBOOK = """
PROVEN HOOK FORMULAS (the patterns behind the most-viewed Shorts, Reels and TikToks):
1. Curiosity gap      - hint at a secret, never reveal it: "Ye baat 99% log nahi jaante" / "Nobody tells you this"
2. Contrarian         - attack a common belief: "Stop doing X" / "Sab ghalat samajhte hain"
3. Warning / mistake  - fear of loss: "Ye galti aap bhi kar rahe ho" / "Never do this"
4. Call out the viewer - name their exact pain: "Agar aap ke ghar mein koi ... hai, ye suno"
5. Shocking number    - a specific, surprising figure: "1 crore log ye roz jhelte hain"
6. Story open loop    - start mid-drama: "Us din jo hua, main kabhi nahi bhoola"
7. Result first       - show the payoff up front: "Sirf 2 din mein ye seekh gaye"
8. Raw confession     - vulnerable truth: "Main ne apne bete ko kabhi nahi samjha"
9. Painful question   - a question the viewer can't ignore: "Kya aap apne bachay ki baat samajhte ho?"

WHICH FORMULAS WIN IN EACH CATEGORY (use these first):
- Podcast / interview: 1 Curiosity gap, 2 Contrarian, 8 Raw confession, 5 Shocking number
- Social issue / awareness: 4 Call out the viewer, 5 Shocking number, 9 Painful question
- Education / how-to: 3 Warning, 7 Result first, 1 Curiosity gap
- Motivation / self-help: 4 Call out the viewer, 2 Contrarian, 6 Story open loop
- Business / money / career: 7 Result first, 2 Contrarian, 3 Warning
- Health / fitness: 2 Contrarian (myth-bust), 3 Warning, 7 Result first
- Religion / family / emotional: 9 Painful question, 6 Story open loop, 8 Raw confession
- Tech / AI: 7 Result first, 2 Contrarian, 1 Curiosity gap
- Comedy / entertainment: 6 Story open loop, 1 Curiosity gap

HOOK TEXT RULES (on-screen text in the first 3 seconds):
- Max 8 words, readable in under 2 seconds. No emojis, no hashtags.
- It must be a COMPLETE, clear sentence that a stranger understands instantly WITHOUT having heard the video.
  Never a sentence fragment ("hamara is waqt", "jo maine kaha"), never vague pronouns without meaning ("ye", "woh baat").
  Name the concrete subject (deaf bachche, sign language, business, family) so the viewer knows what it is about.
- Keep the speaker's REAL meaning. Never flip it into its opposite (if they say "keep trying", never write "quitting
  is success"). Never insult the viewer or their family ("aapke bachche bekar hain" is forbidden).
- Before answering, read the hook as a stranger scrolling: does it make sense, is it respectful, would I tap? If not,
  rewrite it.
- It must create TENSION the viewer can only release by watching: never give away the answer.
- Talk to the viewer ("aap", "you") or hit an emotion (fear, guilt, surprise, anger, hope). Be specific, not generic.
- Strong and confident, never a weak or vague question like "Kya aap jaante hain?" or "X ka gap?".
- It must be TRUE to what is said in the clip. Exaggerate the emotion, never invent facts.
  NEVER use a number, statistic, time period or claim that is not literally said in the clip.
  No number in the clip? Use an emotional or curiosity formula instead of "Shocking number".
- First decide the category, then draft 3 hooks with 3 different winning formulas for that category,
  imagine a viewer scrolling fast, and keep ONLY the one that would stop the most thumbs.

Weak vs strong examples (these show the STYLE only; never copy their words or facts):
  weak: "Paisa bachane ke tips"           strong: "Ye galti aap ko gareeb rakh rahi hai"
  weak: "Subah jaldi uthna achha hai"     strong: "Aap ki subah hi aap ka din barbaad kar rahi hai"
  weak: "Bachon ki parwarish kaise karein" strong: "Aap ka bachcha aap se sach nahi bolta"
"""


SCOUT_NOTE = """
HOOKS: hook_text = the strongest scroll-stopping line (max 8 words), true to what is said. A later step polishes it,
so focus on picking the most gripping moments and honest hook_score.
"""


def language_rule(roman: bool, video_lang: str | None = None) -> str:
    """Language for hooks/titles. Roman only for Urdu/Hindi; other videos use their own language
    (name the language explicitly, otherwise a small model copies the playbook's Roman Urdu examples)."""
    if roman:
        return "Roman Urdu (Urdu written with English letters, e.g. 'Ye baat koi nahi batata')"
    if video_lang and video_lang.strip().lower() not in ("urdu", "hindi", "punjabi"):
        name = video_lang.strip().capitalize()
        return (f"{name}, the language spoken in the video. Do NOT translate and do NOT use Urdu, Hindi or "
                f"Roman Urdu words (the playbook examples are only about style)")
    return "the same language as the video"


def build_prompt(transcript: str, n: int, min_len: int, max_len: int, roman: bool = False,
                 playbook: bool = True, video_lang: str | None = None) -> str:
    """playbook=False: a lighter prompt for long-video parts (saves tokens); hooks are sharpened later."""
    language = language_rule(roman, video_lang)
    guide = HOOK_PLAYBOOK if playbook else SCOUT_NOTE
    return f"""You are a top short-form video editor and copywriter whose Shorts and Reels get millions of views.
Below is a timestamped transcript of a long video. Pick the {n} best moments to turn into standalone Shorts.

CLIP RULES:
- Each clip must be {min_len}-{max_len} seconds long.
- The first spoken words must already grab attention: a bold claim, question, surprising fact or emotion.
  Never start with greetings, filler or context-setting.
- Each clip must be a complete thought that makes sense without the rest of the video, and must not end mid-sentence.
- Clips must not overlap.
- Use start and end times from the transcript segments.
- Be honest with hook_score: most moments are 40-70. Only truly gripping hooks get 85+.
{guide}
Write hook_text and title in {language}. The title should use the same winning formula as the hook.

Transcript:
{transcript}
"""


def snap_to_words(start: float, end: float, words: list[dict]) -> tuple[float, float] | None:
    """Snap a clip to whole words so no word is cut in half."""
    inside = [w for w in words if w["start"] >= start - 0.3 and w["end"] <= end + 0.3]
    if not inside:
        return None
    return inside[0]["start"], inside[-1]["end"] + 0.15


def remove_overlaps(clips: list[Clip]) -> list[Clip]:
    """Keep the highest-scoring clips and drop any that overlap clips already chosen."""
    chosen: list[Clip] = []
    for c in sorted(clips, key=lambda c: c.hook_score, reverse=True):
        if all(c.end <= k.start or c.start >= k.end for k in chosen):
            chosen.append(c)
    return chosen


# ---------- Talking to the AI ----------

def make_client(timeout_ms: int = 120_000) -> genai.Client | None:
    """Client with a timeout: if no answer arrives in time (default 2 minutes), stop; never retry silently.
    Gemini is optional: returns None without GEMINI_API_KEY (everything then runs on Groq)."""
    if not GEMINI_API_KEY:
        return None
    return genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(
            timeout=timeout_ms,                               # milliseconds
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def ask_gemini(client: genai.Client, model: str, prompt: str, schema: type[BaseModel] = ClipPlan,
               temperature: float = 0.4):
    """Answer from Gemini, shaped like 'schema' (a Pydantic class). Default: ClipPlan."""
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
    )
    if model.startswith("gemini-3"):
        # Gemini 3 models 'think' first; LOW gets the answer faster
        config.thinking_config = types.ThinkingConfig(thinking_level="LOW")

    response = client.models.generate_content(model=model, contents=prompt, config=config)
    return response.parsed or schema.model_validate_json(response.text)


GROQ_MODELS = list(dict.fromkeys([GROQ_TEXT_MODEL, "openai/gpt-oss-20b"]))   # pehla na chale to doosra (alag limit)
GROQ_MAX_WAIT = 65     # waiting this long is fine for a per-minute limit; longer = daily limit, move to the next model


def groq_wait(e: Exception) -> float | None:
    """Seconds to wait on a Groq rate limit (429). None if it isn't a rate-limit error."""
    if getattr(e, "status_code", None) != 429:
        return None
    response = getattr(e, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    found = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(e))
    return (int(found.group(1) or 0) * 60 + float(found.group(2))) if found else 30.0


GROQ_TOTAL_WAIT = 180  # total wait per request (per-minute limits) before giving up


def groq_slots() -> list[tuple[str, str, str]]:
    """Every (model, key) pair is a 'slot': (name, model, key). Each key (a separate Groq account) has its own limits.
    The first key's slot is named after the model only (so older saved blocks keep working), others 'model#2', 'model#3'."""
    return [(model if k == 0 else f"{model}#{k + 1}", model, key)
            for model in GROQ_MODELS for k, key in enumerate(GROQ_API_KEYS)]


class GroqBusy(Exception):
    """Per-minute limit hit: seconds until this slot opens again."""
    def __init__(self, wait: float, detail: str):
        super().__init__(detail)
        self.wait = wait


def ask_groq(prompt: str, schema: type[BaseModel] = ClipPlan, attempts: int = 3, temperature: float = 0.6,
             model: str = GROQ_TEXT_MODEL, log=print, api_key: str | None = None, patient: bool = True):
    """Backup: when Gemini is busy or out of quota, send the same prompt to a Groq text model.
    Groq's JSON/strict mode often failed on this long prompt (the server rejected it).
    So we ask for JSON in plain text and validate it ourselves; retry on a bad answer (attempts).
    Per-minute limit (429): with patient=True, wait and retry (the wait doesn't count as an attempt);
    with patient=False, raise GroqBusy immediately (so another key / model can be tried)."""
    from groq import Groq

    client = Groq(api_key=api_key or GROQ_API_KEY, timeout=120, max_retries=0)
    full_prompt = (prompt + "\nReply with ONLY a JSON object (no markdown, no extra text) matching this JSON schema:\n"
                   + json.dumps(schema.model_json_schema()))
    # Groq counts the tokens reserved for the answer against the per-minute limit (8000): prompt + answer over it = 413.
    # So for a big prompt, leave less room for the answer and use lighter reasoning.
    prompt_tokens = int(len(full_prompt) / 2.2)
    max_tokens = max(1500, min(8000, 7600 - prompt_tokens))
    effort = "medium" if max_tokens >= 4000 else "low"
    failures, waited = 0, 0.0
    while True:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": full_prompt}],
                temperature=temperature, reasoning_effort=effort, max_completion_tokens=max_tokens,
            )
            text = response.choices[0].message.content or ""
            found = re.search(r"\{.*\}", text, re.S)   # in case the AI wrote something before or after the JSON
            return schema.model_validate_json(found.group(0) if found else text)
        except Exception as e:
            if getattr(e, "status_code", None) == 413:      # resending won't help either
                raise
            wait = groq_wait(e)
            if wait is not None:                            # rate limit: not a 'failure', doesn't count as an attempt
                if wait > GROQ_MAX_WAIT:
                    raise                                   # daily limit: ask_ai will block this slot
                if not patient:
                    raise GroqBusy(wait, str(e)) from e
                if waited + wait > GROQ_TOTAL_WAIT:
                    raise
                log(f"     Groq per-minute limit: retrying in {wait:.0f}s...")
                time.sleep(wait + 1)
                waited += wait + 1
                continue
            failures += 1                                   # a real failure (incomplete / invalid JSON, network)
            if failures >= attempts:
                raise
            # an incomplete answer is usually from too little room: next time, lighter reasoning, more room for the answer
            effort = "low"


def gemini_ready() -> bool:
    """Can any Gemini model run right now (a key exists and not all are out of quota)?"""
    if not GEMINI_API_KEY:
        return False
    try:
        return bool(models_to_try(make_client()))
    except Exception:
        return False


SMALL_PROMPT = 9000        # requests smaller than this (teaser, key words, B-roll, hooks) count as 'small'
GEMINI_SMALL_TIMEOUT = 30  # max Gemini wait on a small request (seconds); big requests get 120


def _gemini(prompt, schema, temperature, log, timeout_s: int):
    """Try the Gemini models in turn. Returns the answer or None."""
    if not GEMINI_API_KEY:
        return None
    client = make_client(timeout_s * 1000)
    try:
        models = models_to_try(client)
    except Exception as e:
        log(f"     Warning: could not list Gemini models: {type(e).__name__}")
        return None
    for model in models:
        log(f"     Model: {model} (waiting up to {timeout_s}s)...")
        t0 = time.time()
        try:
            result = ask_gemini(client, model, prompt, schema, 0.4 if temperature is None else temperature)
            log(f"     Got a reply ({time.time() - t0:.0f}s)")
            return result
        except Exception as e:
            log(f"     Warning: {model} failed ({time.time() - t0:.0f}s): {type(e).__name__}: {str(e)[:120]}")
            note_gemini_failure(model, e, log)
            if time.time() - t0 > timeout_s * 0.8:
                # Timeout: Gemini is stuck right now, and the other Gemini models are usually stuck at the same time.
                # Instead of waiting the full time on each model (3 x 60 s), go straight to Groq
                log("     (Gemini is stuck, skipping other Gemini models: using Groq)")
                return None
    return None


def _groq_quick(prompt, schema, temperature, log, groq_start):
    """Every Groq slot (model + key) without waiting: if rate-limited, move on. Returns: (answer or None, busy slots)."""
    temp = 0.6 if temperature is None else temperature
    slots = [s for s in groq_slots() if not is_blocked(s[0])]
    k = groq_start % max(1, len(slots))    # round-robin: each slot has its own per-minute limit, so use them all
    slots = slots[k:] + slots[:k]
    busy: list[tuple[float, tuple]] = []
    for slot in slots:
        name, model, key = slot
        log(f"     AI: Groq ({name})...")
        t0 = time.time()
        try:
            result = ask_groq(prompt, schema, temperature=temp, model=model, log=log, api_key=key, patient=False)
            log(f"     Groq replied ({time.time() - t0:.0f}s)")
            return result, busy
        except GroqBusy as e:
            log(f"     {name}: per-minute limit ({e.wait:.0f}s), trying the next one...")
            busy.append((e.wait, slot))
        except Exception as e:
            note_groq_failure(name, e, t0, log)
    return None, busy


def _groq_patient(prompt, schema, temperature, log, busy):
    """Every Groq slot hit its per-minute limit: wait for whichever opens first."""
    temp = 0.6 if temperature is None else temperature
    for _, (name, model, key) in sorted(busy):
        log(f"     AI: Groq ({name}), waiting for the limit to reset...")
        t0 = time.time()
        try:
            result = ask_groq(prompt, schema, temperature=temp, model=model, log=log, api_key=key, patient=True)
            log(f"     Groq replied ({time.time() - t0:.0f}s)")
            return result
        except Exception as e:
            note_groq_failure(name, e, t0, log)
    return None


def ask_ai(prompt: str, schema: type[BaseModel], log=print, temperature: float | None = None,
           use_groq: bool = True, groq_start: int = 0, fast: bool | None = None,
           gemini_timeout: int | None = None):
    """Answer from the AI: whichever of Gemini and Groq (several keys) returns a valid answer first.
    Order depends on request size, for latency:
      - small request (teaser, key words, B-roll, hooks): Groq first (1-4 s), then Gemini (up to 30 s)
      - big request (clips from the full transcript): Gemini first (big context, up to 2 min), then Groq
    Models that run out of quota (or time out) are remembered and skipped on the next request.
    Default temperature: Gemini 0.4, Groq 0.6 (the original values)."""
    small = len(prompt) < SMALL_PROMPT
    fast = small if fast is None else fast
    can_groq = bool(GROQ_API_KEYS and use_groq)
    busy: list = []
    if fast and can_groq:
        result, busy = _groq_quick(prompt, schema, temperature, log, groq_start)
        if result is not None:
            return result
    result = _gemini(prompt, schema, temperature, log, gemini_timeout or (GEMINI_SMALL_TIMEOUT if small else 120))
    if result is not None:
        return result
    if can_groq:
        if not fast:
            result, busy = _groq_quick(prompt, schema, temperature, log, groq_start)
            if result is not None:
                return result
        result = _groq_patient(prompt, schema, temperature, log, busy)
        if result is not None:
            return result

    hint = "" if len(GROQ_API_KEYS) > 1 else (" Tip: add GROQ_API_KEY_2 (a key from another Groq account) to .env "
                                              "to double the limit.")
    raise RuntimeError("Neither Gemini nor Groq replied. Please try again in a little while." + hint)


def note_groq_failure(name: str, e: Exception, t0: float, log=print) -> None:
    """Log a Groq failure clearly (account id hidden). Daily limit = block the slot."""
    msg = re.sub(r"org_\w+", "org_***", str(e))      # never show the account id
    wait = groq_wait(e)
    kind = re.search(r"on (tokens per \w+|requests per \w+)[^.]*", msg)   # kaun si limit: minute ya din
    detail = f"limit: {kind.group(0)[3:]}, {wait:.0f}s" if kind and wait else msg[:120]
    log(f"     Warning: Groq {name} failed ({time.time() - t0:.0f}s): {type(e).__name__}: {detail}")
    if getattr(e, "status_code", None) == 401:        # bad key: forget this key for today
        block(name, 24 * 3600, log, "invalid API key (copy it into .env again)", persist=False)
    elif wait is not None and wait > GROQ_MAX_WAIT:   # daily limit: keep skipping this slot
        block(name, wait, log, "token limit reached")


def ask_with_fallback(prompt: str, schema, log=print, temperature: float = 0.4):
    """Legacy name: AI answer for any schema (Gemini → Groq backup)."""
    return ask_ai(prompt, schema, log, temperature)


def ping(model: str | None = None) -> None:
    """Quick test: is the model answering, and how fast?"""
    client = make_client()
    if client is None:
        raise RuntimeError("GEMINI_API_KEY is not set (Gemini is optional; the app runs on Groq without it).")
    model = model or pick_model(client)
    print(f"Ping: {model} ...")
    t0 = time.time()
    response = client.models.generate_content(model=model, contents="Reply with just: OK")
    print(f"Reply: {response.text.strip()!r}  ({time.time() - t0:.1f}s)")


# ---------- Sharpening hooks: write 3 options, keep the strongest ----------

class SharpHook(BaseModel):
    candidates: list[str] = Field(description="3 new hooks, each using a different winning formula for this category")
    hook_formula: str = Field(description="the formula of the winning hook")
    hook_text: str = Field(description="the single strongest hook from the candidates, max 8 words")
    title: str = Field(description="Shorts title under 60 characters, using the same formula as the winning hook")
    thumbnail_text: str = Field(default="", description="2-4 words for the thumbnail (different from the hook): "
                                                        "huge, punchy, makes sense alone, creates curiosity")


class SharpHooks(BaseModel):
    hooks: list[SharpHook]


def clip_text(data: dict, clip: Clip) -> str:
    """Only the text spoken inside the clip."""
    return " ".join(s["text"].strip() for s in data.get("segments", [])
                    if s["end"] > clip.start and s["start"] < clip.end)


def build_hook_prompt(clips: list[Clip], data: dict, roman: bool) -> str:
    language = language_rule(roman, data.get("language"))
    blocks = "\n\n".join(
        f"CLIP {i}  (category: {c.category or 'unknown'})\nCurrent hook: {c.hook_text}\nWhat is said:\n{clip_text(data, c)}"
        for i, c in enumerate(clips, start=1)
    )
    return f"""You are the copywriter behind the most-viewed Shorts and Reels in Pakistan and India.
Your only job: make each clip's on-screen hook so strong that a fast-scrolling viewer stops and feels they MUST watch.
{HOOK_PLAYBOOK}
For EACH clip below:
1. Write 3 new hooks, each with a different winning formula for that clip's category.
2. Judge them like a ruthless viral editor. Reject anything vague, generic, a soft question, or a hook that gives
   away the answer. The current hook is the bar: the winner must clearly beat it.
3. Return the winner as hook_text, its formula, and a matching title.
4. Write thumbnail_text: 2-4 words in huge letters on the thumbnail. It must make sense ALONE, name the topic or the
   emotion, and make people tap. Good: "DEAF BACHCHA, AKELA?", "SAB GALAT SAMJHE", "YE GALTI MAT KARNA".
   Bad (never): sentence fragments, "suno", generic words, a long sentence.

Write candidates, hook_text, title and thumbnail_text in {language}.
Return exactly {len(clips)} items, in the same order as the clips.

{blocks}
"""


def sharpen_hooks(clips: list[Clip], data: dict, roman: bool = False, log=print) -> list[Clip]:
    """Second AI step: 3 new hooks per clip, keep the strongest. On failure the original hooks stay."""
    if not clips:
        return clips
    log("     Strengthening hooks (3 options per clip, keeping the strongest)...")
    try:
        # Hook writing is the most important creative step: a better model first (Gemini, then Groq) over a fast small one
        result = ask_ai(build_hook_prompt(clips, data, roman), SharpHooks, log, fast=False)
    except RuntimeError as e:
        log(f"     Warning: kept the original hooks: {e}")
        return clips
    if len(result.hooks) != len(clips):
        log(f"     Warning: got {len(result.hooks)} hooks, needed {len(clips)}. Kept the original hooks.")
        return clips
    for clip, h in zip(clips, result.hooks):
        # the AI's chosen hook first, then the other options: use the first that doesn't state a made-up number
        said = clip_text(data, clip)
        honest = [t.strip() for t in [h.hook_text, *h.candidates] if t.strip() and numbers_ok(t, said)]
        if honest:
            clip.hook_text, clip.hook_formula = honest[0], h.hook_formula
            if numbers_ok(h.title, said):
                clip.title = h.title.strip()
        else:
            log(f"     Warning: new hook had numbers not said in the video. Kept the original hook.")
        thumb = h.thumbnail_text.strip()
        if thumb and len(thumb.split()) <= 5 and numbers_ok(thumb, said):
            clip.thumb_text = thumb             # separate, short (2-4 words) thumbnail text
    for clip in clips:
        said = clip_text(data, clip)
        # if the hook (written on screen) still states a made-up number: drop the number phrase
        if not numbers_ok(clip.hook_text, said):
            clip.hook_text = soften_numbers(clip.hook_text, roman or not data.get("language", "").lower().startswith("en"))
            log(f"     Warning: hook had a made-up number, fixed: {clip.hook_text}")
        # same truth check on the title: if it has a made-up number, the hook becomes the title
        if not numbers_ok(clip.title, said):
            clip.title = clip.hook_text if numbers_ok(clip.hook_text, said) else re.sub(r"\d+\s*", "", clip.title).strip()
    return clips


class ThumbTexts(BaseModel):
    texts: list[str] = Field(description="one 2-4 word thumbnail text per clip, same order")


def fill_thumb_texts(clips: list[Clip], data: dict, roman: bool = False, log=print) -> None:
    """Thumbnail text for clips that don't have one (old SEO pack / AI failure), in a single AI call.
    The full hook sentence looked long and weak on a thumbnail: it needs 2-4 big words."""
    todo = [c for c in clips if not c.thumb_text.strip()]
    if not todo:
        return
    language = language_rule(roman, data.get("language"))
    blocks = "\n\n".join(f"CLIP {i}\nHook: {c.hook_text}\nWhat is said:\n{clip_text(data, c)[:1500]}"
                         for i, c in enumerate(todo, start=1))
    prompt = f"""You design viral YouTube/Shorts thumbnails. For each clip write the thumbnail text: 2-4 words shown huge.
Rules: it must make sense ALONE to a stranger, name the topic or the emotion, create curiosity, and be TRUE to what
is said (no invented numbers or claims). Never a sentence fragment, never just "suno", never a long sentence.
Good examples (style only): "DEAF BACHCHA, AKELA?", "SAB GALAT SAMJHE", "YE GALTI MAT KARNA", "MAA KA RAAZ".
Write in {language}. Return exactly {len(todo)} texts in the same order.

{blocks}
"""
    try:
        result = ask_ai(prompt, ThumbTexts, log, fast=False)     # creative work: better model first
    except RuntimeError as e:
        log(f"     Warning: thumbnail text failed, using the hook: {e}")
        return
    for clip, text in zip(todo, result.texts):
        text = text.strip()
        if text and len(text.split()) <= 5 and numbers_ok(text, clip_text(data, clip)):
            clip.thumb_text = text


# Numbers written as words (Roman Urdu / English / Urdu script). 'ek / one' is excluded: it's common in
# honest hooks like "ek din pachtaoge" ("one day you'll regret it").
NUMBER_WORDS = {
    "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4, "four": 4, "paanch": 5, "panch": 5, "five": 5,
    "chhe": 6, "che": 6, "six": 6, "saat": 7, "seven": 7, "aath": 8, "eight": 8, "nau": 9, "nine": 9,
    "das": 10, "ten": 10, "bees": 20, "twenty": 20, "sau": 100, "hundred": 100, "hazaar": 1000, "hazar": 1000,
    "thousand": 1000, "lakh": 100000, "crore": 10000000, "karor": 10000000,
    "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8, "نو": 9, "دس": 10, "بیس": 20,
    "سو": 100, "ہزار": 1000, "لاکھ": 100000, "کروڑ": 10000000,
}
# A number word only counts when followed by a unit ("do din" = 2 days); otherwise "do" can mean "give" ("mujhe do")
NUMBER_UNITS = {
    "din", "dinon", "day", "days", "saal", "sal", "year", "years", "mahine", "mahina", "month", "months",
    "hafte", "hafta", "week", "weeks", "ghante", "ghanta", "hour", "hours", "minute", "minutes", "mint",
    "log", "logon", "people", "baar", "bar", "times", "rupay", "rupees", "crore", "lakh", "hazaar",
    "دن", "دنوں", "سال", "مہینے", "مہینہ", "ہفتے", "ہفتہ", "گھنٹے", "گھنٹہ", "منٹ", "لوگ", "لوگوں", "بار", "روپے",
}


# "ek / one" only counts with these units ("ek hafte mein" = a time claim); "ek din" is free (an idiom)
ONE_WORDS = {"ek", "aik", "one", "ایک"}
ONE_UNITS = NUMBER_UNITS - {"din", "dinon", "day", "days", "دن", "دنوں", "baar", "bar", "بار", "log", "logon", "لوگ"}


def number_at(tokens: list[str], i: int) -> int | None:
    """Is tokens[i] a number (and the next word a unit)? Then its value."""
    if i + 1 >= len(tokens):
        return None
    tok, nxt = tokens[i], tokens[i + 1]
    if tok.isdigit() and nxt in NUMBER_UNITS:
        return int(tok)
    if tok in NUMBER_WORDS and nxt in NUMBER_UNITS:
        return NUMBER_WORDS[tok]
    if tok in ONE_WORDS and nxt in ONE_UNITS:
        return 1
    return None


def claimed_numbers(text: str) -> set[str]:
    """Numbers in the text: digits (2, 99) and word + unit ("do din" = 2, "ek hafte" = 1)."""
    urdu_digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    text = text.translate(urdu_digits).lower()
    found = set(re.findall(r"\d+", text))
    tokens = re.findall(r"\w+", text)
    for i in range(len(tokens)):
        value = number_at(tokens, i)
        if value is not None:
            found.add(str(value))
    return found


POSTPOSITIONS = {"mein", "me", "main", "mai", "tak", "se", "ke", "ki", "ka", "baad", "andar"}
PREPOSITIONS = {"in", "within", "for", "after", "just", "only", "sirf", "bas"}


def soften_numbers(text: str, urdu_like: bool = True) -> str:
    """Remove the whole made-up number phrase (even saying 'some' would still be a time claim):
    "Ek hafte mein gap khatam karo" → "Gap khatam karo", "Learn it in 2 days" → "Learn it", a lone "99%" too."""
    words = text.split()
    cores = [re.sub(r"\W", "", w.lower()) for w in words]
    out: list[str] = []
    i = 0
    while i < len(words):
        if number_at(cores, i) is not None:
            while out and re.sub(r"\W", "", out[-1].lower()) in PREPOSITIONS:     # "in 2 days": the "in" too
                out.pop()
            i += 2                                                                 # number + ikai
            if i < len(words) and cores[i] in POSTPOSITIONS:                       # "do din mein": the "mein" too
                i += 1
            continue
        if re.fullmatch(r"\d+%?", cores[i]):
            i += 1                                                                 # akela number
            continue
        out.append(words[i])
        i += 1
    if not out:
        return text
    out[0] = out[0][:1].upper() + out[0][1:]
    return " ".join(out)


def numbers_ok(text: str, said: str) -> bool:
    """Every number in the hook (2, 99%, "do din") must be said in the video. A made-up number = a fake hook.
    In the video's text a number word counts even without a unit (lenient, so true hooks aren't rejected)."""
    urdu_digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    said_low = said.translate(urdu_digits).lower()
    # in the video too, a number only counts with a unit ("دو گھنٹے"): a lone "دو" usually means "give" ("mujhe do"),
    # and that leniency once let a fake "2 ghante" (2 hours) hook through
    said_numbers = set(re.findall(r"\d+", said_low)) | claimed_numbers(said)
    return claimed_numbers(text) <= said_numbers


# ---------- Main function ----------

CHARS_PER_TOKEN = 2.0     # in Urdu script one token is ~2.2 characters (measured); 2.0 = a slightly safe estimate
WINDOW_TOKENS = 3500      # long video: each part this many tokens (+ ~900 prompt + answer: fits Groq's 8000/minute)


def est_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def transcript_windows(data: dict, overlap: float, max_tokens: int | None = None) -> list[str]:
    """Split a long video's transcript into small parts. Parts overlap slightly so a great moment on the
    border between two parts is still found. Times in whole seconds: saves tokens."""
    segs = [s for s in data.get("segments", []) if s["text"].strip()]
    lines = [(s["start"], f"[{s['start']:.0f} - {s['end']:.0f}] {s['text'].strip()}") for s in segs]
    windows, i = [], 0
    limit = max_tokens or WINDOW_TOKENS
    while i < len(lines):
        j, size = i, 0
        while j < len(lines) and (j == i or size + est_tokens(lines[j][1]) <= limit):
            size += est_tokens(lines[j][1])
            j += 1
        windows.append("\n".join(text for _, text in lines[i:j]))
        if j >= len(lines):
            break
        back = j   # the next part starts a bit earlier: the previous part's last `overlap` seconds again
        while back - 1 > i and lines[back - 1][0] > lines[j][0] - overlap:
            back -= 1
        i = back
    return windows


def check_clip(clip: Clip, words: list[dict], duration: float, max_len: int) -> Clip | None:
    """Snap an AI clip to whole words; None if too short, trimmed to max_len if too long."""
    snapped = snap_to_words(clip.start, min(clip.end, duration or clip.end), words)
    if not snapped:
        return None
    clip.start, clip.end = snapped
    if clip.end - clip.start < 5:
        return None
    if clip.end - clip.start > max_len + 15:
        cut = snap_to_words(clip.start, clip.start + max_len, words)
        if not cut:
            return None
        clip.start, clip.end = cut
    clip.hook_score = max(0, min(100, clip.hook_score))
    return clip


def fill_gaps(data: dict, chosen: list[Clip], missing: int, min_len: int, max_len: int, roman: bool,
              lang: str | None, log=print) -> list[Clip]:
    """The AI's clips overlapped and too few remain: send only the parts of the video not in any clip
    and ask for more clips there (they can never overlap the clips already chosen)."""
    free = [s for s in data.get("segments", [])
            if all(s["end"] <= c.start or s["start"] >= c.end for c in chosen)]
    if sum(s["end"] - s["start"] for s in free) < min(min_len, 15):
        return []
    log(f"     {missing} clip(s) short: searching the rest of the video...")
    text = "\n".join(f"[{s['start']:.1f} - {s['end']:.1f}] {s['text'].strip()}" for s in free)
    try:
        plan = ask_ai(build_prompt(text, missing + 1, min(min_len, 15), max_len, roman=roman, video_lang=lang),
                      ClipPlan, log)
    except RuntimeError as e:
        log(f"     Warning: no more clips found: {e}")
        return []
    words, duration, extra = data.get("words", []), data.get("duration", 0), []
    for clip in sorted(plan.clips, key=lambda c: c.hook_score, reverse=True):
        clip = check_clip(clip, words, duration, max_len)
        if clip and all(clip.end <= c.start or clip.start >= c.end for c in chosen + extra):
            extra.append(clip)
        if len(extra) >= missing:
            break
    return extra


def grow_short(clips: list[Clip], min_len: float, duration: float, words: list[dict]) -> list[Clip]:
    """If the AI returned a clip shorter than min_len, extend it with neighboring words, but only up to the
    neighboring clips (never overlapping). Extend forward first, backward if there's no room."""
    ordered = sorted(clips, key=lambda c: c.start)
    for i, c in enumerate(ordered):
        if c.end - c.start >= min_len:
            continue
        lo = ordered[i - 1].end if i > 0 else 0.0
        hi = ordered[i + 1].start if i + 1 < len(ordered) else (duration or c.end + min_len)
        end = min(hi, c.start + min_len)
        start = max(lo, min(c.start, end - min_len))
        inside = [w for w in words if w["start"] >= start and w["end"] <= end]
        if inside and inside[-1]["end"] - inside[0]["start"] > c.end - c.start:
            c.start, c.end = inside[0]["start"], min(inside[-1]["end"] + 0.15, hi)
    return clips


GEMINI_PARTS = 3     # a long video goes to Gemini in this many parts, all at once (one big request ~94 s, three small ~30 s)


def find_in_parts(data: dict, want: int, min_len: int, max_len: int, roman: bool, lang: str | None,
                  log=print) -> list[Clip]:
    """Long video (e.g. 1 hour): transcript in parts, and ALL parts sent to the AI AT ONCE (threads).
    The wait = the longest single part, not the sum.
      - Gemini available: ~3 big parts (~20 min each), with the full hook playbook
      - Gemini down: small parts that fit Groq's per-minute limit (8000 tokens), spread round-robin over all
        Groq slots (keys x models)
    Each part's messages (logs) are collected and printed in order at the end (the website can't write from threads)."""
    from concurrent.futures import ThreadPoolExecutor
    minutes = data.get("duration", 0) / 60
    total = est_tokens(transcript_with_times(data))
    gemini = gemini_ready()
    if gemini:
        # each Gemini part up to ~15k tokens (1 hour = 3 parts, 2 hours = 5): all at once, each one quick
        parts = max(GEMINI_PARTS, math.ceil(total / 15000))
        windows = transcript_windows(data, overlap=max_len, max_tokens=max(WINDOW_TOKENS, total // parts + 1))
    else:
        windows = transcript_windows(data, overlap=max_len)
    per = max(2, math.ceil(want * 1.5 / len(windows)))
    log(f"     Long video ({minutes:.0f} min): {len(windows)} parts sent to {'Gemini' if gemini else 'Groq'} together, "
        f"{per} best moments from each...")

    def small_chunks(part: str) -> list[str]:
        """A big (Gemini-sized) part split into chunks within Groq's limit (WINDOW_TOKENS)."""
        chunks, cur, size = [], [], 0
        for line in part.splitlines():
            if cur and size + est_tokens(line) > WINDOW_TOKENS:
                chunks.append("\n".join(cur))
                cur, size = [], 0
            cur.append(line)
            size += est_tokens(line)
        return chunks + (["\n".join(cur)] if cur else [])

    def one(k: int, part: str):
        notes: list[str] = []
        say = notes.append
        if gemini:
            try:
                # Gemini usually returns a ~15k-token part in ~30 s: over 60 s = stuck,
                # move to Groq (we used to wait 120 s: 2 minutes lost on a 2-hour video)
                plan = ask_ai(build_prompt(part, per, min_len, max_len, roman=roman, video_lang=lang),
                              ClipPlan, say, use_groq=False, fast=False, gemini_timeout=60)
                return plan.clips, notes
            except RuntimeError:
                say(f"     Part {k + 1}: no answer from Gemini, retrying on Groq in small chunks...")
            parts = small_chunks(part)     # a big part returns 413 on Groq: use small chunks
        else:
            parts = [part]
        found = []
        for j, piece in enumerate(parts):
            try:
                found += ask_ai(build_prompt(piece, per if len(parts) == 1 else 2, min_len, max_len, roman=roman,
                                             playbook=False, video_lang=lang),
                                ClipPlan, say, groq_start=k + j).clips
            except RuntimeError as e:
                say(f"     Warning: skipped part {k + 1}.{j + 1}: {e}")
        return found, notes

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=min(4, len(windows))) as pool:
        results = list(pool.map(one, range(len(windows)), windows))
    candidates = []
    for k, (clips, notes) in enumerate(results, start=1):
        for line in notes:
            log(line)
        candidates += clips
    log(f"     {len(windows)} parts in {time.time() - t0:.0f}s, {len(candidates)} moments found")
    if not candidates:
        raise RuntimeError("Neither Gemini nor Groq replied. Please try again in a little while.")
    return candidates


def find_clips(data: dict, n: int = 5, min_len: int = 20, max_len: int = 60, log=print,
               roman: bool = False) -> list[Clip]:
    """Send the transcript to the AI, get the best moments back, then validate and clean them.
    Long video (e.g. 1 hour): in one go on Gemini, otherwise search in parts and keep the best."""
    if not GEMINI_API_KEY and not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not found in the .env file")

    want = n + max(1, n // 2)      # ask for a few extra: some clips fail validation, but we still end up with n
    lang = None if roman else data.get("language")     # the language Whisper detected (e.g. English)
    transcript = transcript_with_times(data)
    candidates: list[Clip] | None = None
    if est_tokens(transcript) <= WINDOW_TOKENS:
        candidates = ask_ai(build_prompt(transcript, want, min_len, max_len, roman=roman, video_lang=lang),
                            ClipPlan, log).clips
    else:
        candidates = find_in_parts(data, want, min_len, max_len, roman, lang, log)

    # don't trust the AI blindly: validate every clip
    duration = data.get("duration", 0)
    words = data.get("words", [])
    good = [c for c in (check_clip(clip, words, duration, max_len) for clip in candidates) if c]

    best = remove_overlaps(good)[:n]
    if len(best) < n:
        best += fill_gaps(data, best, n - len(best), min_len, max_len, roman, lang, log)
    best = grow_short(best, min_len, duration, words)
    if len(best) < n:
        log(f"     (only {len(best)} good clips found, {n} requested: the video is short or the length range is strict)")
    return sharpen_hooks(best, data, roman, log)
