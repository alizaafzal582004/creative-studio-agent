import csv
import json
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from groq import Groq

from studio.config import GROQ_API_KEYS
from studio.ffmpeg import run_ffmpeg

MAX_MB = 25            # Groq free tier per-file limit
SPLIT_MB = 10          # audio longer than this (~20 min) is split into chunks: stays under the limit and chunks run in parallel = faster
CHUNK_SECONDS = 600    # har tukda 10 minute (64k mp3 = ~5 MB)
WORKERS = 3            # chunks sent to Groq at once
MODEL = "whisper-large-v3-turbo"


LANG_CODES = {"urdu": "ur", "hindi": "hi", "english": "en", "arabic": "ar", "punjabi": "pa", "persian": "fa"}


def make_clients() -> list[Groq]:
    """A client for each Groq account (GROQ_API_KEY, _2, _3). When one runs out of audio quota, the next is used."""
    return [Groq(api_key=key, timeout=300, max_retries=0) for key in GROQ_API_KEYS]


def transcribe_file(client, path: Path, language: str | None, attempts: int = 4,
                    prompt: str | None = None) -> dict:
    """Transcript of one audio file. client = one Groq client or a list of clients (several accounts).
    Per-minute limit (429): wait and retry. Hourly/daily limit: next account; all exhausted = a clear error.
    prompt = text spoken just before: gives Whisper context, much better on short chunks."""
    clients = client if isinstance(client, list) else [client]
    extra = {"language": language} if language else {}
    if prompt:
        extra["prompt"] = prompt
    data = path.read_bytes()
    k, failures, longest = 0, 0, 0.0
    while True:
        try:
            result = clients[k].audio.transcriptions.create(
                file=(path.name, data), model=MODEL, response_format="verbose_json",
                timestamp_granularities=["word", "segment"], **extra,
            )
            return result.to_dict()
        except Exception as e:
            if getattr(e, "status_code", None) == 401 and k + 1 < len(clients):
                k += 1                             # bad key: next account
                continue
            if getattr(e, "status_code", None) != 429:
                failures += 1                      # network issues etc.: retry a few times
                if failures >= attempts:
                    raise
                time.sleep(2)
                continue
            found = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(e))
            wait = (int(found.group(1) or 0) * 60 + float(found.group(2))) if found else 20
            if wait <= 120:
                time.sleep(wait + 1)               # per-minute limit: wait a bit
                continue
            longest = max(longest, wait)
            if k + 1 < len(clients):
                k += 1                             # this account's hourly/daily limit is used up: next account
                continue
            tip = "" if len(clients) > 1 else " Or add GROQ_API_KEY_2 (a key from another Groq account) to .env."
            raise RuntimeError("Groq Whisper hourly/daily audio limit reached. "
                               f"Try again in about {longest / 60:.0f} minutes.{tip}") from e


def split_audio(audio_path: Path, folder: Path) -> list[tuple[Path, float]]:
    """Split audio into CHUNK_SECONDS pieces (no re-encode, instant). Returns: [(file, start offset)]."""
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    run_ffmpeg(["-y", "-i", str(audio_path), "-f", "segment", "-segment_time", str(CHUNK_SECONDS), "-c", "copy",
                "-segment_list", str(folder / "list.csv"), "-segment_list_type", "csv", str(folder / "part_%03d.mp3")])
    with open(folder / "list.csv", encoding="utf-8") as f:
        return [(folder / row[0], float(row[1])) for row in csv.reader(f) if row]


def merge(parts: list[tuple[dict, float]]) -> dict:
    """Merge the chunk transcripts: shift every word/segment time by its chunk's start."""
    words, segments, texts = [], [], []
    for data, offset in parts:
        for w in data.get("words") or []:
            words.append({**w, "start": w["start"] + offset, "end": w["end"] + offset})
        for s in data.get("segments") or []:
            segments.append({**s, "id": len(segments), "start": s["start"] + offset, "end": s["end"] + offset})
        texts.append((data.get("text") or "").strip())
    last_data, last_offset = parts[-1]
    return {
        "text": " ".join(texts),
        "language": parts[0][0].get("language"),
        "duration": last_offset + (last_data.get("duration") or 0),
        "words": words,
        "segments": segments,
    }


HOLE_SECONDS = 8.0     # a segment this long with almost no words = Whisper skipped part of it
HOLE_DENSITY = 0.5     # fewer words per second than this = empty (normal speech is ~2-3 words/s)
MAX_REPAIRS = 12
GAP_HOLE = 5.0         # a gap this long between two words = probably a skipped stretch (if it's real silence, the repair
                       # finds nothing and the original stays)


def find_holes(data: dict) -> list[tuple[float, float]]:
    """Whisper sometimes writes 2-3 words for a 20-30 s 'segment' and skips the rest. Find those stretches."""
    words = data.get("words") or []
    holes = []
    for s in data.get("segments") or []:
        length = s["end"] - s["start"]
        if length < HOLE_SECONDS:
            continue
        inside = sum(1 for w in words if s["start"] <= w["start"] < s["end"])
        if inside / length < HOLE_DENSITY:
            holes.append((s["start"], s["end"]))
    # long gaps between words too (a skipped stretch is sometimes split into several short segments)
    for a, b in zip(words, words[1:]):
        if b["start"] - a["end"] >= GAP_HOLE and not any(h0 <= a["end"] and b["start"] <= h1 for h0, h1 in holes):
            holes.append((a["end"], b["start"]))
    # longest first (Whisper allows 20 requests/minute: repair a few, the most important ones).
    # shorter leftovers are protected by edit.MAX_CUT (long pauses are never cut)
    holes = sorted(holes, key=lambda h: h[1] - h[0], reverse=True)[:MAX_REPAIRS]
    return sorted(holes)


def repair_holes(client, audio_path: Path, data: dict, language: str | None, folder: Path, log=print) -> dict:
    """Re-transcribe an empty stretch on its own (a short chunk); use the result if it has more words.
    For real silence / music the retry finds nothing and the original stays."""
    holes = find_holes(data)
    if not holes:
        return data
    log(f"     Whisper skipped {len(holes)} part(s), transcribing them again...")
    folder.mkdir(parents=True, exist_ok=True)
    # language: the user's choice, otherwise what Whisper detected on the whole video (it guesses wrong on short chunks)
    lang = language or LANG_CODES.get(str(data.get("language") or "").lower())

    def redo(k_hole):
        k, (a, b) = k_hole
        start = max(0.0, a - 0.5)
        part = folder / f"hole_{k:02}.mp3"
        # audio_path may be an audio file or the video itself (-vn: audio only)
        run_ffmpeg(["-y", "-ss", f"{start:.2f}", "-i", str(audio_path), "-t", f"{b - start + 0.5:.2f}", "-vn",
                    "-ac", "1", "-ar", "16000", "-b:a", "64k", str(part)])
        before = " ".join(s["text"].strip() for s in data["segments"] if s["end"] <= a + 0.1)[-400:]
        clients = client if isinstance(client, list) else [client]
        return start, transcribe_file(rotated(clients, k), part, lang, prompt=before or None)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(redo, enumerate(holes)))

    words, segments, fixed = data["words"], data["segments"], 0
    for (a, b), (start, new) in zip(holes, results):
        new_words = [{**w, "start": w["start"] + start, "end": w["end"] + start} for w in new.get("words") or []
                     if a - 0.2 <= w["start"] + start < b]
        old_count = sum(1 for w in words if a <= w["start"] < b)
        if len(new_words) <= old_count:
            continue
        new_segs = [{**s, "start": max(a, s["start"] + start), "end": min(b, s["end"] + start)}
                    for s in new.get("segments") or [] if a - 0.2 <= s["start"] + start < b]
        words = [w for w in words if not a <= w["start"] < b] + new_words
        segments = [s for s in segments if not (s["start"] == a and s["end"] == b)] + new_segs
        fixed += 1
    words.sort(key=lambda w: w["start"])
    segments.sort(key=lambda s: s["start"])
    for i, s in enumerate(segments):
        s["id"] = i
    log(f"     {fixed}/{len(holes)} parts fixed")
    return {**data, "words": words, "segments": segments}


LONG_SECONDS = 20 * 60   # videos longer than this: audio chunks cut straight from the video, in parallel
VIDEO_WORKERS = 4        # chunks at once (extract + Groq); Whisper allows 20 requests/minute per account


def rotated(clients: list, k: int) -> list:
    """Chunk k goes to client (k % n) first, so 2 hours (7200 s) of audio doesn't eat one account's hourly
    limit (~7200 s) but is spread evenly. If it fails, the other accounts are tried in turn."""
    n = len(clients)
    return clients[k % n:] + clients[:k % n]


URDU_WORD_RATIO = 1.1   # an Urdu transcript with this many times more words than the English one = the speech is really Urdu


def detect_urdu(video: Path, out_dir: Path, log=print) -> bool:
    """Whisper sometimes treats Urdu/Hindi speech (mixed with English) as 'English' and writes an English
    TRANSLATION, which can't be turned into Roman Urdu. Take two 30 s samples and transcribe each as both Urdu
    and English. The transcript in the real language is LONGER (every spoken word); a translation is SHORTER.
    Measured (Urdu words / English words): Urdu-English mixed video 1.73, 1.62 | real English video 0.11, 0.73 |
    Urdu videos 1.18 to 100+. (Whisper's confidence and asking an AI both proved unreliable for this.)"""
    from studio.ffmpeg import media_duration
    clients = make_clients()
    dur = media_duration(video)
    starts = [min(60.0, dur * 0.2), dur * 0.5] if dur > 90 else [0.0]
    parts = [out_dir / f"{video.stem}_langtest{k}.mp3" for k in range(len(starts))]
    try:
        for start, part in zip(starts, parts):
            run_ffmpeg(["-y", "-ss", f"{start:.1f}", "-i", str(video), "-t", "30", "-vn", "-ac", "1", "-ar", "16000",
                        "-b:a", "64k", str(part)])
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = [(pool.submit(transcribe_file, rotated(clients, k), p, "ur"),
                     pool.submit(transcribe_file, rotated(clients, k + 1), p, "en")) for k, p in enumerate(parts)]
            ratios = [len(ur.result().get("words") or []) / max(1, len(en.result().get("words") or []))
                      for ur, en in jobs]
    finally:
        for p in parts:
            p.unlink(missing_ok=True)
    ratio = sum(ratios) / len(ratios)
    is_urdu = ratio > URDU_WORD_RATIO
    log(f"     Language check: Urdu/English word ratio {', '.join(f'{r:.2f}' for r in ratios)} "
        f"→ {'Urdu (original spoken words, not an English translation)' if is_urdu else 'English'}")
    return is_urdu


def transcribe_video(video: Path, out_dir: Path, language: str | None = None, log=print) -> dict:
    """Transcript straight from the video. Long videos (1-2 hours): each 10-minute chunk is cut by its OWN FFmpeg
    process, all IN PARALLEL, and each finished chunk goes to Groq right away (no waiting for the full audio).
    Before: the full audio in one process (2 hours ~1 min), then the chunks. Now: both happen at once."""
    from studio.audio import extract_audio
    from studio.ffmpeg import media_duration
    if not GROQ_API_KEYS:
        raise RuntimeError("GROQ_API_KEY not found (add it to .env or Streamlit secrets)")
    duration = media_duration(video)
    if duration and duration <= LONG_SECONDS:
        log("     Extracting audio...")
        audio = extract_audio(video, out_dir)
        log("     Transcribing with Groq Whisper...")
        return transcribe(audio, out_dir, language, log)

    clients = make_clients()
    folder = out_dir / f"{video.stem}_chunks"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    n = max(1, int((duration + CHUNK_SECONDS - 1) // CHUNK_SECONDS))
    log(f"     Long video ({duration / 60:.0f} min): {n} chunks, {min(VIDEO_WORKERS, n)} at a time "
        f"(extract audio + transcribe), spread across {len(clients)} Groq account(s)...")

    def job(k: int) -> dict:
        part = folder / f"part_{k:03}.mp3"
        run_ffmpeg(["-y", "-ss", str(k * CHUNK_SECONDS), "-i", str(video), "-t", str(CHUNK_SECONDS), "-vn",
                    "-ac", "1", "-ar", "16000", "-b:a", "64k", str(part)])
        return transcribe_file(rotated(clients, k), part, language)

    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=min(VIDEO_WORKERS, n)) as pool:
            results = list(pool.map(job, range(n)))
        log(f"     {n} chunks transcribed ({time.time() - t0:.0f}s)")
        data = merge([(r, k * CHUNK_SECONDS) for k, r in enumerate(results)])
        try:
            data = repair_holes(clients, video, data, language, folder, log)
        except Exception as e:      # even if the repair fails, we still have a transcript
            log(f"     Warning: could not fix empty parts: {type(e).__name__}: {str(e)[:120]}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    json_path = out_dir / f"{video.stem}_transcript.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def transcribe(audio_path: Path, out_dir: Path, language: str | None = None, log=print) -> dict:
    """Transcribe with Groq Whisper, with start/end times for every word.
    Long videos (e.g. 1 hour): audio in chunks, 3 at a time, then merged into one transcript."""
    if not GROQ_API_KEYS:
        raise RuntimeError("GROQ_API_KEY not found (add it to .env or Streamlit secrets)")
    client = make_clients()

    size_mb = audio_path.stat().st_size / (1024 * 1024)
    if size_mb <= SPLIT_MB:
        data = transcribe_file(client, audio_path, language)
    else:
        folder = out_dir / f"{audio_path.stem}_chunks"
        chunks = split_audio(audio_path, folder)
        too_big = [p.name for p, _ in chunks if p.stat().st_size / (1024 * 1024) > MAX_MB]
        if too_big:
            raise ValueError(f"Audio chunks are larger than {MAX_MB} MB: {too_big}")
        log(f"     Long audio ({size_mb:.0f} MB): transcribing {len(chunks)} chunks, {WORKERS} at a time...")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(lambda c: transcribe_file(client, c[0], language), chunks))
        log(f"     {len(chunks)} chunks transcribed ({time.time() - t0:.0f}s)")
        data = merge([(r, offset) for r, (_, offset) in zip(results, chunks)])

    folder = out_dir / f"{audio_path.stem}_chunks"
    try:
        data = repair_holes(client, audio_path, data, language, folder, log)
    except Exception as e:      # even if the repair fails, we still have a transcript
        log(f"     Warning: could not fix empty parts: {type(e).__name__}: {str(e)[:120]}")
    shutil.rmtree(folder, ignore_errors=True)

    json_path = out_dir / f"{audio_path.stem}_transcript.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
