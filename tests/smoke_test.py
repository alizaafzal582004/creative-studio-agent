"""End-to-end test: run every preset through the full pipeline and check the result (video exists, length is
right, both audio and video, thumbnails). Features that work alone can still break together: this catches that.

    python tests/smoke_test.py input/podcast.mp4 --mock     # no internet / AI (fake AI answers), ~2-3 minutes
    python tests/smoke_test.py input/podcast.mp4            # with real AI (Gemini / Groq)

Never touches real output: it works on a copy named 'smoke_<name>' and deletes everything at the end."""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from studio import pipeline  # noqa: E402
from studio.clipper import Clip  # noqa: E402
from studio.config import OUTPUT_DIR  # noqa: E402
from studio.ffmpeg import FFMPEG  # noqa: E402
from studio.presets import PRESETS, settings_for  # noqa: E402

CASES = [(p, {}) for p in PRESETS if p != "custom"] + [
    ("podcast_pro", {"layout": "split"}),            # split-screen separately
    ("talking_head_viral", {"layout": "split"}),     # split uses a normal hook instead of text-behind
]


# ---------------- Nakli AI (--mock) ----------------

def install_mock() -> None:
    """Fake versions of the pipeline's AI steps: always the same, instant, no internet."""
    def fake_clips(data, n=5, min_len=20, max_len=60, log=print, roman=False):
        words = data.get("words", [])
        start = words[min(5, len(words) - 1)]["start"] if words else 1.0
        end = min(start + 11, data.get("duration", start + 11))
        return [Clip(start=start, end=end, hook_score=70, reason="mock", category="test",
                     hook_text="Ye galti aap bhi roz kar rahe ho", title="Mock title",
                     description="Mock description", hashtags=["#shorts", "#test"])][:n]

    def fake_teaser(words, clip_start, log=print):
        inside = [w for w in words if w["start"] > clip_start + 4][:6]
        return [inside[0]["start"] - 0.05, inside[-1]["end"] + 0.1] if len(inside) >= 3 else None

    def fake_moments(words, log=print):
        late = [w for w in words if w["start"] > words[0]["start"] + 5]
        return [{"start": late[0]["start"], "word": late[0]["word"], "query": "sign language class"}] if late else []

    def fake_opening(words, clip_start, log=print):
        inside = [w for w in words if w["start"] > clip_start + 1][:6]
        return [inside[0]["start"] - 0.05, inside[-1]["end"] + 0.1] if len(inside) >= 3 else None

    import studio.teaser as teaser_module
    teaser_module.find_opening = fake_opening
    def fake_thumb_texts(clips, data, roman=False, log=print):
        for c in clips:
            c.thumb_text = c.thumb_text or "MOCK THUMB"

    pipeline.fill_thumb_texts = fake_thumb_texts
    import studio.context as context_module
    context_module.context_needs = lambda items, log=print: ([1] * len(items), [0] * len(items))   # (earlier, following) per clip: exercise the setup path
    pipeline.bridge_lines = lambda parts, language, log=print: ["Mock bridge"] * (len(parts) - 1)
    pipeline.find_clips = fake_clips
    pipeline.find_teaser = fake_teaser
    pipeline.find_emphasis = lambda words, log=print: []
    pipeline.choose_moments = fake_moments
    pipeline.romanize = lambda words, cache_path, log=print, ranges=None: words
    pipeline.romanize_texts = lambda texts, log=print: texts

    # Story mode (default on): fake story clips, then the real to_clip_objects turns them into Clip objects.
    def fake_story(data, n=5, min_len=20, max_len=60, log=print):
        words = data.get("words", [])
        start = words[min(5, len(words) - 1)]["start"] if words else 1.0
        end = min(start + 11, data.get("duration", start + 11))
        return [dict(start=start, end=end, topic="mock", setup="mock setup", payoff="mock payoff",
                     takeaway="mock takeaway", hooks=["Ye galti aap bhi roz kar rahe ho"],
                     hook_text="Ye galti aap bhi roz kar rahe ho", hook_score=70, hook_why="",
                     title="Mock title", description="Mock description", hashtags=["#shorts"])][:n]
    pipeline.find_story_clips = fake_story


# ---------------- Checks ----------------

def probe(path: Path) -> dict:
    ffprobe = str(Path(FFMPEG).with_name("ffprobe" + Path(FFMPEG).suffix))
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                          "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(out.stdout or "{}")


def check(report: list[dict], out_dir: Path, s) -> tuple[list[str], float, int]:
    issues, length, thumbs = [], 0.0, 0
    if not report:
        return ["no Short was created"], length, thumbs
    r = report[0]
    mp4 = out_dir / r["file"]
    if not mp4.exists() or mp4.stat().st_size < 50_000:
        return [f"{r['file']} missing / empty"], length, thumbs
    info = probe(mp4)
    length = float(info.get("format", {}).get("duration", 0))
    kinds = {st["codec_type"] for st in info.get("streams", [])}
    if not {"video", "audio"} <= kinds:
        issues.append(f"streams: {sorted(kinds)}")
    expected = r["final_seconds"] + (pipeline.END_SECONDS if s.end_card else 0)
    if abs(length - expected) > 1.0:
        issues.append(f"length {length:.1f}s, expected ~{expected:.1f}s")
    thumbs = sum(1 for t in r.get("thumbnails") or [] if (out_dir / t).exists())
    if s.thumbnails and thumbs != 2:
        issues.append(f"thumbnails {thumbs}/2")
    return issues, length, thumbs


# ---------------- Main ----------------

def main():
    ap = argparse.ArgumentParser(description="End-to-end test of every preset")
    ap.add_argument("video")
    ap.add_argument("--mock", action="store_true", help="fake AI (no internet)")
    args = ap.parse_args()

    src = Path(args.video)
    if not src.exists():
        raise SystemExit(f"File not found: {src}")
    video = src.with_name(f"smoke_{src.stem}{src.suffix}")
    shutil.copy(src, video)
    cached = OUTPUT_DIR / f"{src.stem}_transcript.json"           # avoid re-transcribing
    if cached.exists():
        shutil.copy(cached, OUTPUT_DIR / f"{video.stem}_transcript.json")
    elif args.mock:
        raise SystemExit("--mock needs one real run first (transcript cache), or drop --mock")
    if args.mock:
        install_mock()

    out_dir = OUTPUT_DIR / f"{video.stem}_shorts"
    rows, failed = [], False
    try:
        for preset, extra in CASES:
            s = settings_for(preset, {"clips": 1, "min_len": 8, "max_len": 14, "reuse": False, "roman": True,
                                      **extra})
            label = preset + (f" ({', '.join(f'{k}={v}' for k, v in extra.items())})" if extra else "")
            t0 = time.time()
            try:
                _, report = pipeline.make_shorts(video, s, log=lambda *_: None)
                issues, length, thumbs = check(report, out_dir, s)
                layout = report[0].get("layout", "?") if report else "-"
            except Exception as e:
                issues, length, thumbs, layout = [f"{type(e).__name__}: {str(e)[:160]}"], 0.0, 0, "-"
            failed |= bool(issues)
            rows.append((label, not issues, time.time() - t0, length, layout, thumbs, "; ".join(issues)))
            print(f"  {'✅' if not issues else '❌'} {label}", flush=True)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
        (OUTPUT_DIR / f"{video.stem}_transcript.json").unlink(missing_ok=True)
        (OUTPUT_DIR / f"{video.stem}.mp3").unlink(missing_ok=True)
        video.unlink(missing_ok=True)

    print(f"\n{'Preset':38} {'':2} {'Time':>5} {'Length':>7} {'Layout':>7} {'Thumbs':>6}  Issues")
    for label, ok, secs, length, layout, thumbs, issues in rows:
        print(f"{label:38} {'✅' if ok else '❌'} {secs:4.0f}s {length:6.1f}s {layout:>7} {thumbs:>6}  {issues}")
    print("\n✅ All presets pass" if not failed else "\n❌ Some presets failed (see 'Issues' above)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
