"""Thermal guard: keeps a laptop from overheating (Windows hibernates it at the CPU's critical temperature).

A background thread reads the CPU temperature every 2 seconds (Windows 'Thermal Zone' counter, no admin needed).
At TEMP_PAUSE °C every running FFmpeg process is suspended and new work waits; at TEMP_RESUME °C everything
continues exactly where it stopped. The video comes out the same, it just takes a little longer.
Not on Windows, or no temperature sensor: does nothing."""
import ctypes
import os
import sys
import threading
import time

TEMP_PAUSE = float(os.getenv("TEMP_PAUSE", "") or 88)     # 0 = guard off
TEMP_RESUME = float(os.getenv("TEMP_RESUME", "") or 75)
CHECK_EVERY = 2.0

_cool = threading.Event()
_cool.set()                              # set = cool enough to work
_started = False
_lock = threading.Lock()
_procs_fn = None                         # returns the running Popen objects (from cancel.py)
paused_seconds = 0.0                     # total time spent cooling down (for the log)
notify = None                            # the running job's log (the website shows it); set by make_shorts


def _say(msg: str) -> None:
    print(msg, flush=True)
    try:
        if notify:
            notify(msg)
    except BaseException:                # the job's log raises Cancelled after Stop: never kill the guard
        pass


class _Pdh:
    """Minimal PDH reader for '\\Thermal Zone Information(*)\\Temperature' (Kelvin), via ctypes.
    The zone names contain a backslash (\\_tz.cpuz), so read all zones (wildcard) and keep the CPU ones."""
    FMT_DOUBLE = 0x00000200
    MORE_DATA = 0x800007D2

    class _Value(ctypes.Structure):
        _fields_ = [("CStatus", ctypes.c_ulong), ("doubleValue", ctypes.c_double)]

    class _Item(ctypes.Structure):
        pass

    _Item._fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _Value)]

    def __init__(self):
        self.pdh = ctypes.WinDLL("pdh")
        self.pdh.PdhGetFormattedCounterArrayW.restype = ctypes.c_ulong
        self.query, self.counter = ctypes.c_void_p(), ctypes.c_void_p()
        if self.pdh.PdhOpenQueryW(None, None, ctypes.byref(self.query)):
            raise OSError("PdhOpenQuery failed")
        if self.pdh.PdhAddEnglishCounterW(self.query, "\\Thermal Zone Information(*)\\Temperature", None,
                                          ctypes.byref(self.counter)):
            raise OSError("no thermal zone counter")
        self.pdh.PdhCollectQueryData(self.query)

    def read(self) -> float | None:
        if self.pdh.PdhCollectQueryData(self.query):
            return None
        size, count = ctypes.c_ulong(0), ctypes.c_ulong(0)
        rc = self.pdh.PdhGetFormattedCounterArrayW(self.counter, self.FMT_DOUBLE, ctypes.byref(size),
                                                   ctypes.byref(count), None)
        if rc != self.MORE_DATA or not size.value:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if self.pdh.PdhGetFormattedCounterArrayW(self.counter, self.FMT_DOUBLE, ctypes.byref(size),
                                                 ctypes.byref(count), buf):
            return None
        items = ctypes.cast(buf, ctypes.POINTER(self._Item))
        temps = [items[i].FmtValue.doubleValue - 273.15 for i in range(count.value)
                 if "cpu" in (items[i].szName or "").lower() and items[i].FmtValue.doubleValue > 200]
        return max(temps) if temps else None


_reader: _Pdh | None = None


def cpu_temp() -> float | None:
    """CPU temperature in °C, or None if it can't be read."""
    global _reader
    if sys.platform != "win32":
        return None
    try:
        if _reader is None:
            _reader = _Pdh()
        return _reader.read()
    except Exception:
        return None


def _suspend(procs, resume: bool) -> None:
    ntdll = ctypes.WinDLL("ntdll")
    fn = ntdll.NtResumeProcess if resume else ntdll.NtSuspendProcess
    for p in procs:
        handle = getattr(p, "_handle", None)
        if handle and p.poll() is None:
            fn(ctypes.c_void_p(int(handle)))


def _watch() -> None:
    global paused_seconds
    while True:
        t = cpu_temp()
        if t is None:
            time.sleep(10)
            continue
        if _cool.is_set() and t >= TEMP_PAUSE:
            _cool.clear()
            t0 = time.time()
            _say(f"     CPU {t:.0f}°C: pausing so the laptop cools down (continues at {TEMP_RESUME:.0f}°C)...")
            _suspend(_procs_fn() if _procs_fn else [], resume=False)
            while (cpu_temp() or 0) > TEMP_RESUME:
                time.sleep(CHECK_EVERY)
                _suspend(_procs_fn() if _procs_fn else [], resume=False)   # processes started meanwhile
            _suspend(_procs_fn() if _procs_fn else [], resume=True)
            paused_seconds += time.time() - t0
            _say(f"     Cooled down after {time.time() - t0:.0f}s, continuing")
            _cool.set()
        time.sleep(CHECK_EVERY)


def start(procs_fn) -> None:
    """Start the guard once. procs_fn() returns the running subprocesses to suspend when hot."""
    global _started, _procs_fn
    if TEMP_PAUSE <= 0 or sys.platform != "win32":
        return
    with _lock:
        _procs_fn = procs_fn
        if not _started and cpu_temp() is not None:
            threading.Thread(target=_watch, name="thermal-guard", daemon=True).start()
            _started = True


def wait() -> None:
    """Block while the CPU is cooling down (call this in long Python loops and before new heavy work)."""
    _cool.wait()
