"""Awaaz saaf karna: final video ki sirf audio dobara banti hai, video copy hoti hai (re-encode nahi).
Is liye ye laptop par bohot halka hai (sirf audio ka kaam, ek do second).
Chain: 80 Hz se neeche ki gunj hatao → halka compressor (dheemi awaaz upar, tez awaaz neeche)
→ loudness -14 LUFS (YouTube / Instagram / TikTok ka standard)."""
from pathlib import Path

from studio.ffmpeg import run_ffmpeg

VOICE_CHAIN = ("highpass=f=80,"
               "acompressor=threshold=-20dB:ratio=3:attack=10:release=200:makeup=2,"
               "loudnorm=I=-14:TP=-1.5:LRA=11")


def polish_audio(mp4: Path) -> Path:
    tmp = mp4.with_name(f"{mp4.stem}_voice{mp4.suffix}")
    run_ffmpeg(["-y", "-i", str(mp4), "-map", "0:v", "-map", "0:a", "-c:v", "copy",
                "-af", VOICE_CHAIN, "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                "-movflags", "+faststart", str(tmp)])
    tmp.replace(mp4)
    return mp4
