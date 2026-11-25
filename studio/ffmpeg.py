"""Finding and running FFmpeg. Uses the system install if present, otherwise the imageio-ffmpeg binary (for cloud)."""
import shutil
from pathlib import Path

from studio import cancel
from studio.config import CPU_THREADS


def find_ffmpeg() -> str:
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise RuntimeError("FFmpeg not found. Run 'pip install imageio-ffmpeg'.") from e


FFMPEG = find_ffmpeg()


def media_duration(path: Path) -> float:
    """Length of a video / audio file in seconds (from FFmpeg's 'Duration: 01:02:03.45' line; no ffprobe needed)."""
    import re
    out = cancel.run([FFMPEG, "-hide_banner", "-i", str(path)], text=True,
                         encoding="utf-8", errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def move_into_place(tmp: Path, target: Path, tries: int = 8) -> None:
    """Move a finished file into place. If OneDrive / a video player is holding the file, wait a bit and retry."""
    import os
    import time
    for attempt in range(tries):
        try:
            os.replace(tmp, target)       # same drive par foran; doosri drive par copy + delete
            return
        except OSError:
            try:
                shutil.copyfile(tmp, target)
                tmp.unlink(missing_ok=True)
                return
            except OSError:
                if attempt == tries - 1:
                    raise RuntimeError(f"Could not write {target.name}: another program (OneDrive / video "
                                       "player) is holding it. Close that file and run again.")
                time.sleep(1 + attempt)


def run_ffmpeg(args: list[str], cwd: Path | None = None) -> None:
    """Pass args without 'ffmpeg' itself. Raises a clear error on failure."""
    # log real errors only (not the "frame=... time=..." progress lines) so problems are easy to spot
    quiet = ["-hide_banner", "-nostats", "-loglevel", "error"]
    if "-threads" not in args and args:
        # cool mode: filters and the encoder use CPU_THREADS cores, not all of them (output file = last arg)
        n = str(CPU_THREADS)
        args = ["-filter_threads", n, "-filter_complex_threads", n, *args[:-1], "-threads", n, args[-1]]
    result = cancel.run([FFMPEG, *quiet, *args], text=True,
                            encoding="utf-8", errors="replace", cwd=cwd)
    if result.returncode != 0 and not result.stderr.strip():
        # Exiting with no message is usually a transient crash (many jobs at once). Retry once,
        # this time with warnings enabled so the cause is visible if it fails again.
        result = cancel.run([FFMPEG, "-hide_banner", "-nostats", "-loglevel", "warning", *args],
                            text=True, encoding="utf-8", errors="replace", cwd=cwd)
    if result.returncode != 0:
        code = result.returncode & 0xFFFFFFFF
        raise RuntimeError(f"FFmpeg failed (exit code {code:#x}):\n{result.stderr.strip()[-1200:] or '(no message)'}")
