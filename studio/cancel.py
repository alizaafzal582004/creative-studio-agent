"""Cancelling a running job (the website's Stop button).

stop() raises a flag and immediately kills every running FFmpeg process. The pipeline's log() and every new
FFmpeg call check this flag and raise Cancelled. Cancelled is a BaseException so the pipeline's
'except Exception' handlers (which tolerate small failures and carry on) can't swallow it."""
import subprocess
import threading

_event = threading.Event()
_procs: set[subprocess.Popen] = set()
_lock = threading.Lock()


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


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Like subprocess.run (capture_output + text), but the process is killed immediately on Stop."""
    check()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    with _lock:
        _procs.add(proc)
    try:
        out, err = proc.communicate()
    finally:
        with _lock:
            _procs.discard(proc)
    check()
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
