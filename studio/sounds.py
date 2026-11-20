"""Sound effects + music synthesized in code. No licensing issues: they're yours.
You can also drop your own royalty-free .mp3 music into assets/music/."""
import wave
from pathlib import Path

import numpy as np

from studio.config import ROOT
from studio.ffmpeg import run_ffmpeg

SFX_DIR = ROOT / "assets" / "sfx"
MUSIC_DIR = ROOT / "assets" / "music"
RATE = 44100


def save_wav(path: Path, audio: np.ndarray) -> None:
    """Write numpy audio (-1 to 1, mono or stereo) to a 16-bit WAV file."""
    audio = np.clip(audio, -1, 1)
    if audio.ndim == 1:
        audio = audio[:, None]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(audio.shape[1])
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((audio * 32767).astype("<i2").tobytes())


def timeline(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * RATE)) / RATE


def lowpass(x: np.ndarray, cutoff: np.ndarray | float) -> np.ndarray:
    """Simple one-pole low-pass filter: tames high frequencies. The cutoff can change per sample."""
    cutoff = np.broadcast_to(cutoff, x.shape)
    a = np.exp(-2 * np.pi * cutoff / RATE)
    y = np.zeros_like(x)
    prev = 0.0
    for i in range(len(x)):
        prev = (1 - a[i]) * x[i] + a[i] * prev
        y[i] = prev
    return y


# ---------------- Sound effects ----------------

def make_pop() -> np.ndarray:
    """Pop: a 0.09 s sound whose pitch drops fast (900 Hz → 250 Hz)."""
    t = timeline(0.09)
    freq = 250 + 650 * np.exp(-t * 45)
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    env = np.minimum(t / 0.004, 1) * np.exp(-t * 38)
    return 0.8 * np.sin(phase) * env


def make_whoosh() -> np.ndarray:
    """Whoosh: noise that swells then fades while panning left to right (stereo)."""
    rng = np.random.default_rng(7)
    t = timeline(0.45)
    env = np.sin(np.pi * t / t[-1]) ** 2
    noise = rng.uniform(-1, 1, len(t))
    cutoff = 400 + 5000 * env                # more 'air' in the middle
    mono = lowpass(noise, cutoff) * env * 1.6
    pan = t / t[-1]                          # 0 = left, 1 = right
    return np.stack([mono * (1 - pan), mono * pan], axis=1)


def make_ding() -> np.ndarray:
    """Ding: a bell-like sound (several partials, slow decay)."""
    t = timeline(1.2)
    tone = (np.sin(2 * np.pi * 1320 * t) + 0.5 * np.sin(2 * np.pi * 2640 * t)
            + 0.25 * np.sin(2 * np.pi * 3960 * t * 1.003))
    env = np.minimum(t / 0.005, 1) * np.exp(-t * 4.5)
    return 0.35 * tone * env


# ---------------- Music: simple lo-fi loop ----------------

def make_lofi(bars: int = 8, bpm: int = 80) -> np.ndarray:
    """Soft lo-fi music: 4 chords (Am7, Fmaj7, Cmaj7, G) + kick + hi-hat. Loopable."""
    beat = 60 / bpm
    bar = 4 * beat
    total = timeline(bars * bar)
    out = np.zeros((len(total), 2))
    rng = np.random.default_rng(3)

    chords = [[220.0, 261.63, 329.63, 392.0],     # Am7
              [174.61, 220.0, 261.63, 329.63],    # Fmaj7
              [130.81, 164.81, 196.0, 246.94],    # Cmaj7
              [196.0, 246.94, 293.66, 392.0]]     # G
    for b in range(bars):
        start = int(b * bar * RATE)
        t = timeline(bar)
        env = np.minimum(t / 0.3, 1) * np.minimum((bar - t) / 0.3, 1)   # soft start, soft end
        pad = sum(np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t) for f in chords[b % 4])
        pad = 0.06 * pad * env
        out[start:start + len(t), 0] += pad
        out[start:start + len(t), 1] += pad

        for k in range(4):                                   # har beat
            s = start + int(k * beat * RATE)
            if k in (0, 2):                                  # kick on beats 1 and 3
                kt = timeline(0.35)
                kf = 50 + 70 * np.exp(-kt * 25)
                kick = 0.5 * np.sin(2 * np.pi * np.cumsum(kf) / RATE) * np.exp(-kt * 9)
                out[s:s + len(kt)] += kick[:, None]
            hs = s + int(beat / 2 * RATE)                    # hi-hat between beats
            ht = timeline(0.05)
            hat = 0.05 * rng.uniform(-1, 1, len(ht)) * np.exp(-ht * 90)
            out[hs:hs + len(ht)] += hat[:, None]

    crackle = (rng.random(len(total)) > 0.99993) * rng.uniform(-0.05, 0.05, len(total))  # soft vinyl crackle (~3 per second)
    out += crackle[:, None]
    return out / np.max(np.abs(out)) * 0.8


def ensure_sounds() -> None:
    """Create the sounds if missing (once). Music is converted to mp3 to keep it small."""
    makers = {"pop.wav": make_pop, "whoosh.wav": make_whoosh, "ding.wav": make_ding}
    for name, make in makers.items():
        if not (SFX_DIR / name).exists():
            save_wav(SFX_DIR / name, make())

    lofi = MUSIC_DIR / "lofi_chill.mp3"
    if not lofi.exists():
        tmp = MUSIC_DIR / "lofi_chill.wav"
        save_wav(tmp, make_lofi())
        run_ffmpeg(["-y", "-i", str(tmp), "-b:a", "128k", str(lofi)])
        tmp.unlink()


def sfx(name: str) -> Path:
    ensure_sounds()
    return SFX_DIR / f"{name}.wav"


def music_tracks() -> list[str]:
    """Names (without extension) of the mp3/wav files in assets/music."""
    ensure_sounds()
    return sorted(p.stem for p in MUSIC_DIR.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a"))


def music_path(name: str) -> Path | None:
    for p in MUSIC_DIR.glob(f"{name}.*"):
        return p
    return None
