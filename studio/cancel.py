"""Cancelling a running job (the website's Stop button).

stop() raises a flag and immediately kills every running FFmpeg process. The pipeline's log() and every new
FFmpeg call check this flag and raise Cancelled. Cancelled is a BaseException so the pipeline's
'except Exception' handlers (which tolerate small failures and carry on) can't swallow it."""
import subprocess
import sys
import threading

from studio import thermal
from studio.config import FFMPEG_AT_ONCE

_event = threading.Event()
_procs: set[subprocess.Popen] = set()
_lock = threading.Lock()
_slots = threading.BoundedSemaphore(FFMPEG_AT_ONCE)    # cool mode: only this many heavy processes at once
# Below-normal priority: the laptop stays responsive (browser, music) while videos render
_PRIORITY = {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS} if sys.platform == "win32" else {}


class Cancelled(BaseException):
    """The user pressed Stop."""


def reset() -> None:
    """New job starting: clear any previous Stop flag."""
    _event.clear()


def stop() -> None:
    _event.set()
    with _lock:
        procs = list(_procs)
    for p in procs:
        try:
            p.kill()
        except OSError:
            pass


def stopped() -> bool:
    return _event.is_set()


def check() -> None:
    if _event.is_set():
        raise Cancelled("Stopped by user")


def running() -> list[subprocess.Popen]:
    with _lock:
        return list(_procs)


def pause_point() -> None:
    """Wait here while the thermal guard is cooling the CPU down (Stop still works), then check for Stop."""
    thermal.start(running)
    while not thermal._cool.wait(1):
        check()
    check()


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Like subprocess.run (capture_output + text), but the process is killed immediately on Stop.
    The thermal guard can suspend it while the CPU cools down."""
    pause_point()
    with _slots:
        pause_point()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **{**_PRIORITY, **kwargs})
        with _lock:
            _procs.add(proc)
        try:
            out, err = proc.communicate()
        finally:
            with _lock:
                _procs.discard(proc)
    check()
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
