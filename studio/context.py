"""Context: every Short makes sense on its own, and the combined video reads like one story.

1) context_needs: gives the AI the Short's opening (hook) sentence and what follows, plus a few sentences from
   BEFORE it. The AI says how many earlier sentences (0-4) a stranger needs to follow along ('setup').
   The pipeline then builds the Short as: hook sentence → setup → the rest (the hook is not repeated).
2) bridge_lines: in the combined video, a short connecting line on screen before each next part, e.g.
   "But what's the real problem?", so the parts flow like one story."""
from pydantic import BaseModel, Field

from studio.clipper import ask_ai

MAX_BEFORE = 4         # show / add at most this many earlier sentences
MAX_EXTRA = 15.0       # setup may make a Short at most this many seconds longer


class ContextNeeds(BaseModel):
    needs: list[int] = Field(description="for each clip: how many BEFORE sentences (0-4) a stranger needs")


class Bridges(BaseModel):
    lines: list[str] = Field(description="one short connecting line per transition, same order")


def context_needs(items: list[dict], log=print) -> list[int]:
    """items: [{'before': [sentences, oldest first], 'hook': ..., 'after': ...}] → 0-4 per clip."""
    if not items:
        return []
    blocks = []
    for k, it in enumerate(items, start=1):
        before = "\n".join(f"  B{len(it['before']) - j}: {s}" for j, s in enumerate(it["before"]))
        blocks.append(f"CLIP {k}\nBEFORE (B1 = the sentence right before the hook):\n{before or '  (none)'}\n"
                      f"HOOK (the Short starts here): {it['hook']}\nAFTER: {it['after'][:1200]}")
    prompt = f"""You edit viral Shorts that must make sense to a stranger who never saw the full video.
Each clip below starts with its HOOK line. For each clip decide how many BEFORE sentences (counting back from B1)
must be added after the hook so a stranger understands who/what is being talked about and why it matters.
- 0 if HOOK + AFTER already make full sense on their own.
- Add only what is truly needed (setup, who "he/they/it" refers to, the question being answered). Max {MAX_BEFORE}.
Return exactly {len(items)} numbers in order.

{chr(10).join(blocks)}
"""
    try:
        result = ask_ai(prompt, ContextNeeds, log, fast=False)
        needs = [max(0, min(MAX_BEFORE, int(n))) for n in result.needs]
        return needs if len(needs) == len(items) else [0] * len(items)
    except Exception as e:
        log(f"     Warning: context check failed (Shorts unchanged): {str(e)[:100]}")
        return [0] * len(items)


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
