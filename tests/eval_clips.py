"""Eval: AI ki clips ko aap ki apni chuni hui 'sahi' clips se milao. Koi video ya AI call nahi, sirf hisaab.

    python tests/eval_clips.py eval/podcast.json

eval/podcast.json (aap khud likhein, video dekh kar):
{
  "video": "podcast",
  "clips": [
    {"start": 125, "end": 180, "topic": "Pehle saal ka nuqsaan"},
    {"start": 610, "end": 655, "topic": "Pehla client kaise mila"}
  ]
}
"video" = video file ka naam bina .mp4 (output/<video>_shorts/seo_pack.json se milaya jata hai)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATCH = 0.3      # kitna overlap (IoU) ho to "mil gayi" maanein


def iou(a: dict, b: dict) -> float:
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / union if union > 0 else 0.0


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Istemal: python tests/eval_clips.py eval/podcast.json")
    gold = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    pack = ROOT / "output" / f"{gold['video']}_shorts" / "seo_pack.json"
    if not pack.exists():
        raise SystemExit(f"Nahi mila: {pack}  (pehle shorts banayein)")
    ai = json.loads(pack.read_text(encoding="utf-8"))

    print(f"\n{'Aap ki clip':38} {'Behtareen AI clip':22} {'Overlap':>7}")
    hits, total_iou = 0, 0.0
    for g in gold["clips"]:
        best = max(ai, key=lambda c: iou(g, c), default=None)
        score = iou(g, best) if best else 0.0
        total_iou += score
        hits += score >= MATCH
        name = f"{g.get('topic', '')[:22]} ({g['start']:.0f}-{g['end']:.0f}s)"
        got = f"{best.get('file', '?')} ({best['start']:.0f}-{best['end']:.0f}s)" if best else "-"
        print(f"{name:38} {got:22} {score:6.0%} {'✅' if score >= MATCH else '❌'}")

    used = sum(1 for c in ai if any(iou(g, c) >= MATCH for g in gold["clips"]))
    print(f"\nAap ki clips jo AI ne pakdin (recall):   {hits}/{len(gold['clips'])}")
    print(f"AI ki clips jo aap ki list mein (precision): {used}/{len(ai)}")
    print(f"Average overlap: {total_iou / max(len(gold['clips']), 1):.0%}")


if __name__ == "__main__":
    main()
