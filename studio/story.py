"""Mukammal kahani wali clips.
1) Poori video ka topic map (har topic: sawal, jawab, faida).
2) Sab se kaam ke topics chuno.
3) Har topic se ek clip jo akeli samajh aaye: Setup (topic/sawal) → Payoff (jawab) → Takeaway (faida).
4) Har clip ke 3 hooks, phir alag AI 'judge' sab se strong hook chunta hai.
Sab kaam Groq par (internet): laptop ka CPU/GPU istemal nahi hota."""
import dataclasses
import re

from pydantic import BaseModel, Field

from studio.groqjson import ask_json

WINDOW_SECONDS = 12 * 60        # lambi video ko 12 minute ke hisson mein AI ko dikhate hain
GENERIC = ("won't believe", "wont believe", "watch till", "till the end", "must watch", "aakhir tak",
           "zaroor dekhein", "zaroor dekho", "shocking", "you need to see")


# ---------------- AI ke jawab ki shapes ----------------

class Topic(BaseModel):
    start: float = Field(description="topic start time in seconds, from the transcript")
    end: float = Field(description="topic end time in seconds, from the transcript")
    title: str = Field(description="short topic name, 3-6 words")
    question: str = Field(description="the question or problem being discussed")
    answer: str = Field(description="the main answer or insight given")
    takeaway: str = Field(description="what the viewer gains, one sentence")
    value: int = Field(description="0-10: how useful or interesting this is as a standalone short video")


class TopicMap(BaseModel):
    topics: list[Topic]


class StoryClip(BaseModel):
    start: float = Field(description="clip start, a transcript line's start time")
    end: float = Field(description="clip end, a transcript line's end time")
    setup: str = Field(description="what the viewer hears first: the topic or question")
    payoff: str = Field(description="the answer, result or story ending the clip delivers")
    takeaway: str = Field(description="the benefit for the viewer, one sentence")
    complete: bool = Field(description="true only if the clip makes full sense alone")
    hooks: list[str] = Field(description="3 different hook texts, max 8 words each")
    title: str
    description: str
    hashtags: list[str]


class HookPick(BaseModel):
    clip: int
    best: int = Field(description="index 0-2 of the strongest hook")
    score: int = Field(description="0-10, be strict")
    why: str


class HookVerdicts(BaseModel):
    verdicts: list[HookPick]


# ---------------- Prompts ----------------

TOPIC_PROMPT = """You are mapping a long video (podcast, interview or talk) into topics.
Below is part of its timestamped transcript. List every distinct topic discussed in this part.
For each topic give its start and end time (from the transcript), a short title, the question or problem,
the main answer, the takeaway for a viewer, and a value score 0-10 for how good it would be as a standalone
short video (clear question + clear answer + useful or surprising = high; small talk, greetings, ads = low).

Transcript:
{transcript}
"""

CLIP_PROMPT = """You are an expert short-form video editor. From this part of a long video (topic: "{title}"),
cut ONE clip that a stranger can fully understand with no other context.

The clip must contain, in this order:
1. SETUP: the sentence(s) that say what the topic or question is,
2. PAYOFF: the answer, result or story ending,
3. a natural ending (never stop mid-thought).
Length: {min_len}-{max_len} seconds. Use the start/end times of the transcript lines exactly.
Start where the topic or question is introduced, never mid-sentence. Set complete=false if that is impossible.

Write 3 different hooks (max 8 words each) that promise the PAYOFF to the viewer. Each hook must be specific
(a real result, number, mistake or surprising claim that is actually said in the clip), make the viewer curious,
and must not invent anything. No generic hooks like "You won't believe this" or "Watch till the end".
{lang_rule}
title: max 60 characters and names the topic. description: 1-2 sentences with searchable keywords.
hashtags: 5-8, including #shorts.

Topic summary: question = {question} | answer = {answer}

Transcript:
{transcript}
"""

JUDGE_PROMPT = """You are a strict judge of short-video hooks (the text on screen in the first 3 seconds).
For every clip, pick the strongest of its hooks and score it 0-10:
- specific: names a concrete result, number, mistake or claim (not vague)
- curiosity: the viewer must keep watching to get the answer
- promise: clearly points to the payoff the clip delivers
- honest: matches what is said, no exaggeration
- short and natural to read in 2 seconds
Generic hooks score at most 4.

{blocks}
"""


# ---------------- Helpers ----------------

def has_urdu(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" or "ऀ" <= ch <= "ॿ" for ch in text)


def language_rule(segments: list[dict], language: str) -> str:
    sample = " ".join(s["text"] for s in segments[:60])
    lang = (language or "").lower()
    if has_urdu(sample) or lang.startswith(("ur", "hi")):
        return ("Write hooks, title and description in Roman Urdu (Urdu in Latin letters, e.g. 'Ye galti "
                "mat karna'). Keep English words in English.")
    return "Write hooks, title and description in the same language as the video."


def lines(segments: list[dict], a: float | None = None, b: float | None = None) -> str:
    return "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text'].strip()}" for s in segments
                     if (a is None or s["end"] > a) and (b is None or s["start"] < b))


def snap(start: float, end: float, segments: list[dict], min_len: float, max_len: float) -> tuple[float, float]:
    """Clip ko poore jumlon par set karo: shuru jumle ki shuruaat par, aakhir jumle ke aakhir par."""
    before = [s for s in segments if s["start"] <= start + 0.5]
    a = before[-1]["start"] if before else segments[0]["start"]
    after = [s for s in segments if s["end"] >= end - 0.5 and s["start"] >= a]
    b = after[0]["end"] if after else segments[-1]["end"]
    if b - a > max_len * 1.15:                               # bohot lambi: aakhri pura jumla jo had mein aaye
        inside = [s["end"] for s in segments if a < s["end"] <= a + max_len]
        if inside:
            b = inside[-1]
    if b - a < min_len:                                       # bohot chhoti: agle jumle jodo
        for s in segments:
            if s["end"] > b:
                b = s["end"]
                if b - a >= min_len:
                    break
    return a, b


def hook_is_ok(hook: str, clip_text: str) -> bool:
    """Hook ke numbers clip mein bole gaye hon, aur hook generic na ho."""
    low = hook.lower()
    if any(g in low for g in GENERIC):
        return False
    said = clip_text.replace(",", "")
    nums = [n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,.]*", hook)]
    return all(re.search(rf"(?<!\d){re.escape(n)}(?!\d)", said) for n in nums)   # '9' ko '19' mein mat gino


# ---------------- Steps ----------------

def topic_map(segments: list[dict], log=print) -> list[Topic]:
    total = segments[-1]["end"]
    topics, t = [], 0.0
    while t < total:
        part = lines(segments, t, t + WINDOW_SECONDS)
        if part.strip():
            log(f"     Topic map: {t / 60:.0f}-{min(t + WINDOW_SECONDS, total) / 60:.0f} min...")
            for tp in ask_json(TOPIC_PROMPT.format(transcript=part), TopicMap, log).topics:
                tp.start, tp.end = max(0.0, tp.start), min(total, tp.end)
                if tp.end - tp.start >= 10:
                    topics.append(tp)
        t += WINDOW_SECONDS
    return sorted(topics, key=lambda tp: tp.start)


def judge_hooks(clips: list[dict], log=print) -> None:
    blocks = "\n\n".join(
        f"Clip {i}:\nPayoff: {c['payoff']}\nTakeaway: {c['takeaway']}\nHooks: "
        + " | ".join(f"{k}) {h}" for k, h in enumerate(c["hooks"]))
        for i, c in enumerate(clips))
    log("     AI judge hooks check kar raha hai...")
    for v in ask_json(JUDGE_PROMPT.format(blocks=blocks), HookVerdicts, log, temperature=0.1).verdicts:
        if 0 <= v.clip < len(clips):
            c = clips[v.clip]
            k = v.best if 0 <= v.best < len(c["hooks"]) else 0
            c["hook_text"], c["hook_score"], c["hook_why"] = c["hooks"][k], max(0, min(100, v.score * 10)), v.why


def find_story_clips(data: dict, n: int = 5, min_len: int = 20, max_len: int = 60, log=print) -> list[dict]:
    """Wapas: clips ki list (dict), har ek mein start, end, topic, setup, payoff, takeaway, hook_text, hook_score,
    title, description, hashtags."""
    segments = [s for s in data.get("segments", []) if s.get("text", "").strip()]
    if not segments:
        raise RuntimeError("Transcript mein jumle nahi mile")
    rule = language_rule(segments, str(data.get("language", "")))

    log("     1) Poori video ka topic map ban raha hai...")
    topics = topic_map(segments, log)
    if not topics:
        raise RuntimeError("AI ko koi topic nahi mila")
    ranked = sorted(topics, key=lambda tp: tp.value, reverse=True)
    log(f"     {len(topics)} topics mile. Sab se achhe: " + " | ".join(tp.title for tp in ranked[:n]))

    clips: list[dict] = []
    for tp in ranked:
        if len(clips) >= n:
            break
        if tp.value < 4:
            break                                              # kamzor topics se clip mat banao
        log(f"     2) Clip: {tp.title}...")
        try:
            c = ask_json(CLIP_PROMPT.format(title=tp.title, question=tp.question, answer=tp.answer,
                                            min_len=min_len, max_len=max_len, lang_rule=rule,
                                            transcript=lines(segments, tp.start - 20, tp.end + 20)),
                         StoryClip, log, temperature=0.4)
        except Exception as e:
            log(f"     ⚠ '{tp.title}' skip: {str(e)[:120]}")
            continue
        if not c.complete or not c.payoff.strip() or not c.takeaway.strip():
            log(f"     ✖ '{tp.title}': akeli samajh nahi aati, reject")
            continue
        a, b = snap(c.start, c.end, segments, min_len, max_len)
        if any(a < x["end"] and b > x["start"] for x in clips):
            continue                                           # pehle wali clip se takrati hai
        text = " ".join(s["text"] for s in segments if s["end"] > a and s["start"] < b)
        hooks = [h.strip() for h in c.hooks if h.strip() and hook_is_ok(h, text)][:3] or [tp.title]
        clips.append(dict(start=a, end=b, topic=tp.title, setup=c.setup, payoff=c.payoff, takeaway=c.takeaway,
                          hooks=hooks, hook_text=hooks[0], hook_score=50, hook_why="",
                          title=c.title[:70], description=c.description, hashtags=c.hashtags[:8]))

    if clips:
        try:
            judge_hooks(clips, log)
        except Exception as e:                                  # judge fail ho to pehla hook rakho
            log(f"     ⚠ Hook judge skip: {str(e)[:120]}")
    return sorted(clips, key=lambda c: c["start"])


def to_clip_objects(items: list[dict], Clip) -> list:
    """Story clips ko project ki apni Clip class mein badlo (sirf wo fields jo Clip mein hain)."""
    names = set(getattr(Clip, "model_fields", {})) or {f.name for f in dataclasses.fields(Clip)}
    out = []
    for it in items:
        values = {**it, "reason": f"Topic: {it['topic']}. Faida: {it['takeaway']}. Hook: {it.get('hook_why', '')}"}
        try:
            out.append(Clip(**{k: v for k, v in values.items() if k in names}))
        except Exception as e:
            raise RuntimeError(f"Clip class mein koi zaroori field missing hai: {e}. "
                               "studio/clipper.py ki 'class Clip' bhej dein.") from e
    return out
