"""Context: every Short makes sense on its own, and the combined video reads like one story.

1) context_needs: gives the AI the Short's opening (hook) sentence and what follows, plus the sentences from
   BEFORE and AFTER it. The AI finds where the TOPIC starts (often the interviewer's question) and where its answer
   concludes, so every Short covers one topic that makes sense on its own.
   The pipeline then builds the Short as: hook sentence → setup → the rest (the hook is not repeated).
2) bridge_lines: in the combined video, a short connecting line on screen before each next part, e.g.
   "But what's the real problem?", so the parts flow like one story."""
from pydantic import BaseModel, Field

from studio.clipper import ask_ai

MAX_BEFORE = 14        # show / add at most this many earlier sentences (Whisper sentences are short: ~2-3 s each)
BEFORE_WINDOW = 75.0   # ...from at most this many seconds before the clip
MAX_EXTRA = 15.0       # setup may always add this many seconds; more if the Short stays within max_len
MAX_SETUP = 45.0       # but never more than this
MAX_NEXT = 10          # show / add at most this many following sentences (to finish the topic)
NEXT_WINDOW = 60.0     # ...from at most this many seconds after the clip


class ContextNeeds(BaseModel):
    topics: list[str] = Field(default_factory=list, description="for each clip: its topic in 3-8 words")
    needs: list[int] = Field(description=f"for each clip: how many BEFORE sentences (0-{MAX_BEFORE}) to add so the "
                                         "Short starts where its topic starts")
    finish: list[int] = Field(default_factory=list,
                              description=f"for each clip: how many NEXT sentences (0-{MAX_NEXT}) to add so the "
                                          "topic is complete")


class Bridges(BaseModel):
    lines: list[str] = Field(description="one short connecting line per transition, same order")


def context_needs(items: list[dict], log=print) -> tuple[list[int], list[int]]:
    """items: [{'before': [sentences, oldest first], 'hook': ..., 'after': ..., 'next': [sentences after the clip]}]
    → (earlier sentences to add, following sentences to add) per clip."""
    zeros = [0] * len(items)
    if not items:
        return [], []
    blocks = []
    for k, it in enumerate(items, start=1):
        before = "\n".join(f"  B{len(it['before']) - j}: {s}" for j, s in enumerate(it["before"]))
        nxt = "\n".join(f"  N{j}: {s}" for j, s in enumerate(it.get("next", []), start=1))
        blocks.append(f"CLIP {k}\nBEFORE (B1 = the sentence right before the hook):\n{before or '  (none)'}\n"
                      f"HOOK (the Short starts here): {it['hook']}\nAFTER (the rest of the clip): {it['after'][:1200]}\n"
                      f"NEXT (said right after the clip ends, N1 first):\n{nxt or '  (none)'}")
    prompt = f"""You edit viral Shorts from interviews and talks. Every Short must cover ONE TOPIC so that a stranger
who never saw the full video understands what is being discussed and why, from the first second to the last.

For each clip:
1. Name its topic in 3-8 words ("topics"), e.g. "which ad platform to use", "how to sell an online product".
2. "needs": how many BEFORE sentences (counting back from B1) to add so the Short starts WHERE THIS TOPIC STARTS:
   the question that is being answered (often the interviewer's question), or the sentence that introduces the
   subject. Without it the answer makes no sense ("agar aap ki service hai..." needs the question "online product
   kaise sell karun?").
   - 0 if the clip already starts at the topic's start.
   - Never go back into a DIFFERENT, earlier topic. Max {MAX_BEFORE}.
3. "finish": how many NEXT sentences (counting from N1) to add so the TOPIC IS COMPLETE: the question fully answered,
   the example or story finished, the conclusion said.
   - 0 if the clip already ends where the topic concludes.
   - Stop at the last sentence of this topic: never add the next question or a new topic. Max {MAX_NEXT}.
Return exactly {len(items)} items in each of "topics", "needs" and "finish", in order.

{chr(10).join(blocks)}
"""
    try:
        result = ask_ai(prompt, ContextNeeds, log, fast=False)
        for k, topic in enumerate(result.topics[:len(items)], start=1):
            log(f"     clip {k} topic: {topic}")
        needs = [max(0, min(MAX_BEFORE, int(n))) for n in result.needs]
        finish = [max(0, min(MAX_NEXT, len(it.get("next", [])), int(n))) for n, it in zip(result.finish, items)]
        return (needs if len(needs) == len(items) else zeros), (finish if len(finish) == len(items) else zeros)
    except Exception as e:
        log(f"     Warning: context check failed (Shorts unchanged): {str(e)[:100]}")
        return zeros, zeros


def bridge_lines(parts: list[str], language: str, log=print) -> list[str]:
    """parts = text of each part (original order). Returns len(parts)-1 bridge lines (each ~8 words max)."""
    if len(parts) < 2:
        return []
    blocks = "\n\n".join(f"PART {k}: {p[:900]}" for k, p in enumerate(parts, start=1))
    prompt = f"""These parts are joined into ONE video, in this order. Before each part from PART 2 onward, a short
on-screen line connects it to what came before, so the whole video feels like one story.
Rules: max 8 words, natural and curious (e.g. "Lekin asal masla kya hai?", "Ab baat aati hai apps ki"),
true to the content, no invented facts or numbers. Write in {language}.
Return exactly {len(parts) - 1} lines (for PART 2 ... PART {len(parts)}).

{blocks}
"""
    try:
        result = ask_ai(prompt, Bridges, log, fast=False)
        lines = [ln.strip() for ln in result.lines][:len(parts) - 1]
        return lines + [""] * (len(parts) - 1 - len(lines))
    except Exception as e:
        log(f"     Warning: bridge lines failed: {str(e)[:100]}")
        return [""] * (len(parts) - 1)
