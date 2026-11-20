"""Join all Shorts into one video (a compilation) that still makes sense as a whole.

- Order: original timeline (as the conversation happened), so the story connects naturally. Ordering by AI
  score would make the conversation jump back and forth.
- Optional soft crossfade between clips (picture + sound, 0.4 s) to avoid jarring cuts. Each clip's hook
  acts as that part's 'chapter title'.
- The end screen (if any) stays only at the very end: it is trimmed from the clips in between.
- The AI writes the combined video's own title, description and hashtags."""
import tempfile
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from studio.clipper import ask_with_fallback
from studio.ffmpeg import media_duration, move_into_place, run_ffmpeg

FADE = 0.4          # crossfade between two clips (seconds)
FPS = 30


class CombinedMeta(BaseModel):
    title: str = Field(description="title for the combined video, under 70 characters")
    description: str = Field(description="2-3 sentence description with searchable keywords")
    hashtags: list[str] = Field(description="5-8 hashtags")


def combined_meta(parts: list[dict], language: str, log=print) -> dict:
    """Title / description / hashtags for the combined video (AI). Falls back to the first clip's."""
    blocks = "\n".join(f"{k}. {p['title']}  (hook: {p['hook_text']})" for k, p in enumerate(parts, start=1))
    prompt = f"""These short clips are joined in this order into one video. Write a title, description and hashtags
for the COMBINED video that tells viewers what the whole thing is about (the common thread), so it makes sense as
one video. Be true to the clips, no invented facts or numbers. Write in {language}.

Clips in order:
{blocks}
"""
    try:
        meta = ask_with_fallback(prompt, CombinedMeta, log, temperature=0.5)
        return meta.model_dump()
    except Exception as e:
        log(f"     Warning: combined video title failed ({str(e)[:80]}): using the first clip's")
        first = parts[0]
        return {"title": first["title"], "description": first["description"], "hashtags": first["hashtags"]}


def combine_fast(files: list[Path], out: Path, log=print) -> Path:
    """Join without re-encoding (stream copy): a 55 s video in ~1 s (vs ~80-100 s re-encoded).
    All clips come from the same pipeline with identical settings, so they join cleanly. Each clip starts
    with its own hook + 'ding' and the music fades at the end: every part feels like a new 'chapter'."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="aics_comb_"))
    tmp = tmp_dir / "combined.mp4"
    lst = tmp_dir / "list.txt"
    lst.write_text("".join(f"file '{f.resolve().as_posix()}'\n" for f in files), encoding="utf-8")
    try:
        run_ffmpeg(["-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart",
                    str(tmp)])
        move_into_place(tmp, out.resolve())
    finally:
        lst.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
        tmp_dir.rmdir()
    log(f"     Combined video: {out.name} ({media_duration(out):.0f}s, instant: no re-encode)")
    return out


def combine_clips(out_dir: Path, report: list[dict], end_seconds: float = 0.0, name: str = "combined.mp4",
                  log=print, smooth: bool = False) -> Path | None:
    """report = per-clip report (file, start, ...). end_seconds = length of the end screen at the end of each
    clip (trimmed from all but the last). smooth = crossfade between clips (re-encode: slower).
    Returns: path of the combined video (None if fewer than 2 clips)."""
    parts = sorted((r for r in report if (out_dir / r["file"]).exists()), key=lambda r: r.get("start", 0))
    if len(parts) < 2:
        return None
    files = [out_dir / r["file"] for r in parts]
    if not smooth and end_seconds <= 0:
        log(f"     Joining {len(files)} clips into one video (original order)...")
        try:
            return combine_fast(files, out_dir / name, log)
        except Exception as e:      # if a direct join ever fails: fall back to the re-encoding method
            log(f"     (direct join failed: {str(e)[:80]}; re-encoding to join)")
    lengths = [media_duration(f) for f in files]
    # trim the end screen from the clips in between (keep only the last one's)
    uses = [max(0.5, d - (end_seconds if k < len(files) - 1 else 0.0)) for k, d in enumerate(lengths)]

    args, chains = ["-y"], []
    for k, f in enumerate(files):
        args += ["-i", str(f.resolve())]
        chains.append(f"[{k}:v]trim=end={uses[k]:.3f},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p,"
                      f"settb=AVTB[v{k}]")
        chains.append(f"[{k}:a]atrim=end={uses[k]:.3f},asetpts=PTS-STARTPTS,"
                      f"aformat=sample_rates=48000:channel_layouts=stereo[a{k}]")
    v, a, t = "[v0]", "[a0]", uses[0]
    for k in range(1, len(files)):
        offset = t - FADE
        chains.append(f"{v}[v{k}]xfade=transition=fade:duration={FADE}:offset={offset:.3f}[vx{k}]")
        chains.append(f"{a}[a{k}]acrossfade=d={FADE}[ax{k}]")
        v, a, t = f"[vx{k}]", f"[ax{k}]", offset + uses[k]
    out = out_dir / name
    tmp = Path(tempfile.gettempdir()) / f"aics_comb_{uuid.uuid4().hex[:8]}.mp4"   # write outside OneDrive, then move
    args += ["-filter_complex", ";".join(chains), "-map", v, "-map", a,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "128k",
             "-movflags", "+faststart", str(tmp)]
    log(f"     Joining {len(files)} clips into one video (original order, smooth transitions)...")
    try:
        run_ffmpeg(args)
        move_into_place(tmp, out.resolve())
    finally:
        tmp.unlink(missing_ok=True)
    log(f"     Combined video: {out.name} ({t:.0f}s)")
    return out
