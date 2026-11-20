from pathlib import Path

from studio.ffmpeg import run_ffmpeg


def extract_audio(video_path: Path, out_dir: Path) -> Path:
    """Extracts mono 16 kHz mp3 audio from a video. Enough for Whisper, and the file stays small."""
    audio_path = out_dir / f"{video_path.stem}.mp3"
    run_ffmpeg([
        "-y",                     # overwrite an existing file
        "-i", str(video_path),    # input video
        "-vn",                    # drop the video stream, audio only
        "-ac", "1",               # mono
        "-ar", "16000",           # 16 kHz
        "-b:a", "64k",            # lower quality = smaller file
        str(audio_path),
    ])
    return audio_path
