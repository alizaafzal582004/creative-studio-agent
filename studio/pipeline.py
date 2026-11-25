"""The whole long-video → Shorts job in one function. Used by both the CLI (main.py) and the website (app.py)."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from dataclasses import dataclass, replace
from pathlib import Path

from studio.config import OUTPUT_DIR
from studio.transcribe import transcribe_video, detect_urdu
from studio.captions import words_to_ass, LOWER_START, LOWER_SECONDS, END_SECONDS, LOGO_CENTER_Y, end_card_lines
from studio.grades import grade_filter
from studio.brand import logo_frames
from studio.clipper import Clip, find_clips, fill_thumb_texts
from studio.story import find_story_clips, to_clip_objects
from studio.edit import keep_ranges, split_at_sentences, remap_words, words_inside, total, plan_zooms
from studio.emphasis import find_emphasis, is_filler
from studio.emoji import pop_frames
from studio.styles import STYLES, DEFAULT_STYLE
from studio.sounds import sfx as sound, music_path, ensure_sounds
from studio.framing import plan_shots, find_people, split_pair
from studio.broll import choose_moments, find_footage, download, hide_keys, ready as broll_ready, BROLL_SECONDS
from studio.kinetic import find_counters, counter_lines, COUNT_SECONDS
from studio.emoji import find_png
from studio.emphasis import VIDEO_EMOJI

# 'impact' emoji: the screen shakes on these (the emoji frames folder is named after the png, e.g. '1f525')
IMPACT = {p.stem for p in map(find_png, ["🔥", "😱", "🤯", "💀", "⚡", "😤", "🚀"]) if p}
from studio.render import render_shots
from studio.roman import romanize, romanize_texts, needs_roman
from studio.teaser import find_teaser
from studio.combine import combine_clips, combined_meta
from studio.segment import mask_video
from studio.thumbnail import make_thumbnails
from studio.captions import behind_hook_ass, canvas as caption_canvas, hook_events, clean, ass_time
from studio.context import bridge_lines
from studio.framing import video_size
from studio.render import shot_crop

HOOK_SECONDS = 3.0     # how long the hook stays on screen (also captions.words_to_ass's default)


def spoken_text(words: list[dict], span: list[float]) -> str:
    """The words spoken in this span, joined (for the on-screen hook)."""
    a, b = span
    # only words fully inside this span (not the first word of the next sentence)
    text = " ".join(w["word"].strip() for w in words if a - 0.06 <= w["start"] and w["end"] <= b + 0.02)
    return text.strip().rstrip(",;:-–—").strip()     # a trailing comma etc. looks bad on a hook


RENDER_WORKERS = 1     # FFmpeg's encoder already uses every core: measured with 3 at once, render went from 327 s to
                       # 526 s and masking from 40 s to 143 s (the cores fight each other). One at a time, but in the background:
                       # the next clip's prep (AI, mask) keeps running alongside.


def render_combined(video: Path, parts: list[dict], s: "Settings", style, out_dir: Path, noise: str,
                    track, log=print, pool=None) -> Path | None:
    """All clips in one video that makes sense as a whole:
      - original order (as the conversation happened)
      - the hook ONLY at the start, once (joining finished Shorts repeated every clip's hook)
      - a transition (flash / glitch) + whoosh at every join; one continuous music track
    Each clip's source range first goes into an 'excerpt' video (fast encode), then one full render on that.
    (Rendering straight from the source would decode everything between distant clips in a 2-hour video.)"""
    import tempfile
    from studio.ffmpeg import run_ffmpeg

    parts = sorted(parts, key=lambda p: p["start"])
    if len(parts) < 2:
        return None
    log(f"     Combining {len(parts)} clips: original order, hook once, a transition at every join...")
    tmp_dir = Path(tempfile.mkdtemp(prefix="aics_combo_"))
    excerpt = tmp_dir / "excerpt.mp4"
    try:
        # 1) Excerpt: each clip's source range, one after another (each range its own input, -ss jumps straight there)
        windows = [(min(a for a, _, _ in p["shots"]), max(b for _, b, _ in p["shots"])) for p in parts]
        args, chains = ["-y"], []
        for k, (a, b) in enumerate(windows):
            args += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(video.resolve())]
            chains.append(f"[{k}:v]setpts=PTS-STARTPTS[v{k}];[{k}:a]asetpts=PTS-STARTPTS[a{k}]")
        chains.append("".join(f"[v{k}][a{k}]" for k in range(len(windows))) + f"concat=n={len(windows)}:v=1:a=1[v][a]")
        run_ffmpeg(args + ["-filter_complex", ";".join(chains), "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                           "-preset", "ultrafast", "-crf", "14", "-c:a", "aac", "-b:a", "192k", str(excerpt)])

        # 2) Everything on the new (combined) timeline: shots in excerpt time, the rest offset by each clip's start
        shots, words, emph, emoji, broll, boundaries = [], [], set(), [], [], []
        plan = {"zooms": [], "cys": [], "wide_zooms": [], "wide_cys": []}
        src_off, t_off = 0.0, 0.0
        for (a, b), p in zip(windows, parts):
            shots += [(x - a + src_off, y - a + src_off, cx) for x, y, cx in p["shots"]]
            for key in plan:
                plan[key] += p[key]
            words += [{**w, "start": w["start"] + t_off, "end": w["end"] + t_off} for w in p["words"]]
            emph |= p["emph"]
            emoji += [(f, at + t_off) for f, at, _ in p["emoji"]]
            broll += [(clip, at + t_off, d) for clip, at, d in p["broll"]]
            if t_off > 0:
                boundaries.append(t_off)
            src_off += b - a
            t_off += p["length"]
        total_len = t_off

        splits = [p["split"] for p in parts]
        split = splits[0] if all(splits) else None          # only if every clip is split (otherwise a normal crop)
        hook_style = replace(style, hook_look="bold") if style.hook_look == "behind" else style   # no mask here
        logo = Path(s.logo) if s.end_card and s.logo and Path(s.logo).exists() else None
        counters = find_counters(words) if s.counters else []

        # 3) Sounds: a ding at the start, a strong whoosh at every join, a pop on emoji, a whoosh on B-roll
        effects = []
        if s.sfx:
            effects.append((sound("ding"), 0.0, 0.35))
            effects += [(sound("whoosh"), at - 0.25, 0.6) for at in boundaries]
            effects += [(sound("pop"), at, 0.6) for _, at in emoji]
            effects += [(sound("whoosh"), at - 0.22, 0.35) for _, at, _ in broll]
            if s.end_card:
                effects.append((sound("whoosh"), total_len - 0.22, 0.4))
        # Transition: at every join (always), and when B-roll enters/leaves. Style: the preset's, flash if 'none'
        cuts = sorted(boundaries + [at for _, at, _ in broll] + [at + d for _, at, d in broll])
        style_name = s.transition if s.transition in ("flash", "glitch") else "flash"

        # Context: a short bridge line on screen before each next part, so it reads as one story
        bridges: list[str] = []
        if s.context and s.bridges:
            language = ("Roman Urdu (Urdu written with English letters)" if s.roman
                        else "the same language as the parts")
            bridges = bridge_lines([" ".join(w["word"].strip() for w in p["words"]) for p in parts], language, log)
            for k, line in enumerate(bridges, start=2):
                if line:
                    log(f"     Before part {k}: \"{line}\"")

        # 4) Vertical (Shorts) and 16:9 (YouTube) from the same excerpt, each with its own positions / focus
        variants = [((1080, 1920), "combined.mp4", plan["zooms"], plan["cys"], split)]
        if s.landscape:
            variants.append(((1920, 1080), "combined_16x9.mp4", plan["wide_zooms"], plan["wide_cys"], None))
        out, jobs = None, []
        for (W, H), fname, zooms, cys, vsplit in variants:
            with caption_canvas(W, H):
                end_lines = end_card_lines(total_len, s.cta, s.handle, logo is not None) if s.end_card else []
                lower_y = (H - 300) if W > H else 1020
                lower = (s.name, s.name_title, lower_y) if s.name.strip() and not vsplit else None
                # Bridge lines: ~2 s right after each join, near the top (pill look: distinct from the hook)
                bridge_events = []
                bridge_style = replace(hook_style, hook_look="pill")
                for t0, line in zip(boundaries, bridges):
                    if not line:
                        continue
                    for ev in hook_events(clean(line), bridge_style, "pop", 2.2):
                        bridge_events.append(ev.replace(f",{ass_time(0)},{ass_time(2.2)},",
                                                        f",{ass_time(t0 + 0.2)},{ass_time(t0 + 2.4)},", 1))
                ass = out_dir / fname.replace(".mp4", ".ass")
                ass.write_text(words_to_ass(words, hook_text=parts[0]["hook"], style=hook_style, emphasis=emph,
                                            hook_anim=s.hook_anim, margin_v=910 if vsplit else None, lower=lower,
                                            extra=counter_lines(counters, style) + end_lines + bridge_events),
                               encoding="utf-8")
            margin = int(H * 0.11) if W > H else (910 if vsplit else style.margin_v)
            emoji_y = H - margin - int(style.size * 1.4) - (200 if W > H else 250)
            overlays = [(f, at, emoji_y) for f, at in emoji]
            if logo:
                overlays.append((logo_frames(logo, END_SECONDS), total_len,
                                 round(H * LOGO_CENTER_Y / 1920) - int(360 * 1.25) // 2))
            job = partial(render_shots, excerpt, shots, out_dir / fname, ass, overlays, sfx=effects, music=track,
                          music_volume=s.music_volume, zooms=None if vsplit else zooms, split=vsplit,
                          progress_color=style.highlight if s.progress_bar else None, broll=broll,
                          shakes=[], transitions=cuts, transition_style=style_name,
                          grade=grade_filter(s.grade), end_card=END_SECONDS if s.end_card else 0.0,
                          denoise=noise, canvas=(W, H), centers_y=None if vsplit else cys)
            jobs.append(pool.submit(job) if pool else job)
        # Both sizes at once (with a pool): the excerpt must stay alive until this function returns
        for job in jobs:
            result = job.result() if hasattr(job, "result") else job()
            out = out or result
            log(f"     Combined video: {result.name} ({total_len:.0f}s, hook once, {len(boundaries)} transitions)")
        return out
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


def snap_ends(clips: list, segments: list[dict], max_extra: float = 4.0) -> None:
    """Don't end a clip mid-sentence: extend it to the end of the sentence (Whisper segment) it ends in
    (at most 4 s further, never overlapping the next clip)."""
    for c in clips:
        if any(abs(sg["end"] + 0.1 - c.end) < 0.2 or abs(sg["end"] - c.end) < 0.2 for sg in segments):
            continue                       # already at a sentence end (don't extend again on --reuse)
        seg = next((sg for sg in segments if sg["start"] < c.end <= sg["end"] + 0.05), None)
        if seg and 0 < seg["end"] - c.end <= max_extra:
            nxt = min([o.start for o in clips if o is not c and o.start >= c.end] + [1e9])
            c.end = min(seg["end"] + 0.1, nxt)


def following(c, clips: list, segments: list[dict]) -> list[dict]:
    """Sentences right after a clip ends, up to the next clip's start (at most NEXT_WINDOW s ahead)."""
    from studio.context import NEXT_WINDOW
    nxt = min([o.start for o in clips if o is not c and o.start >= c.end - 0.05] + [c.end + NEXT_WINDOW])
    return [sg for sg in segments if sg["start"] >= c.end - 0.15 and sg["end"] <= nxt + 0.15 and sg["text"].strip()]


def add_context(clips: list, openings: dict, segments: list[dict], s, log=print) -> dict[int, list | None]:
    """Every Short must make sense on its own: the AI says how many sentences before the hook (setup) are needed.
    Returns: {clip: [setup_start, hook_start] or None}. In spoken-hook mode the Short is ordered
    hook → setup → rest (compose_ranges); otherwise the clip simply starts earlier, at the setup."""
    from studio.context import BEFORE_WINDOW, MAX_BEFORE, MAX_EXTRA, MAX_NEXT, MAX_SETUP, context_needs
    items, info = [], []
    for i, c in enumerate(clips):
        op = openings.get(i) if s.hook_start else None
        start = op[0] if op else c.start
        hook_end = op[1] if op else min(c.end, start + 6)
        prev_end = max([o.end for o in clips if o is not c and o.end <= start + 0.05] + [0.0])
        before = [sg for sg in segments if sg["end"] <= start + 0.05 and sg["start"] >= max(start - BEFORE_WINDOW, prev_end - 0.05)
                  and sg["text"].strip()][-MAX_BEFORE:]
        items.append({"before": [sg["text"].strip() for sg in before],
                      "hook": " ".join(sg["text"].strip() for sg in segments
                                       if sg["start"] < hook_end and sg["end"] > start),
                      "after": " ".join(sg["text"].strip() for sg in segments
                                        if hook_end - 0.1 <= sg["start"] < c.end),
                      "next": [sg["text"].strip() for sg in following(c, clips, segments)][:MAX_NEXT]})
        info.append((start, before, op))
    log("     Making each Short one complete topic: finding where each topic starts and ends...")
    needs, finish = context_needs(items, log)
    # Finish the thought: extend the clip end over the needed following sentences (never into the next clip,
    # never more than max_len + a little)
    for i, (c, n) in enumerate(zip(clips, finish)):
        nxt = following(c, clips, segments)[:n]
        if nxt:
            new_end = min(nxt[-1]["end"] + 0.1, c.start + s.max_len + 5)
            if new_end > c.end + 0.3:
                log(f"     clip {i + 1}: +{new_end - c.end:.1f}s so the topic is complete ({len(nxt)} more sentence(s))")
                c.end = new_end
    found: dict[int, list | None] = {}
    for i, (c, n, (start, before, op)) in enumerate(zip(clips, needs, info)):
        chosen = before[-n:] if n > 0 else []
        # room for the setup: always MAX_EXTRA, more while the Short stays within max_len (never over MAX_SETUP)
        room = min(MAX_SETUP, max(MAX_EXTRA, s.max_len - (c.end - start)))
        while chosen and start - chosen[0]["start"] > room:      # setup too long: use the nearest sentences
            chosen = chosen[1:]
        prev_end = max([o.end for o in clips if o is not c and o.end <= start] + [0.0])
        a = max(chosen[0]["start"], prev_end) if chosen else start
        if start - a < 0.5:
            found[i] = None
            continue
        found[i] = [round(a, 3), round(start, 3)]
        log(f"     clip {i + 1}: starts {start - a:.1f}s earlier, where the topic starts ({len(chosen)} sentence(s))")
        if not op:
            c.start = a                    # not hook-start: the clip starts at the setup directly
    return found


def compose_ranges(words: list[dict], clip, opening, context, s) -> list[tuple[float, float]]:
    """The Short's ranges in this order: spoken hook → setup (earlier context) → the rest. The hook isn't repeated.
    Without a setup: just the clip (silences cut)."""
    def keep(a, b):
        return keep_ranges(words, a, b, max_gap=s.gap) if s.cut_silence else [(a, b)]
    if s.hook_start and opening and context and opening[1] < clip.end:
        op0, op1 = opening
        ctx0, ctx1 = context
        return keep(op0, op1) + keep(ctx0, min(ctx1, op0)) + keep(op1, clip.end)
    return keep(clip.start, clip.end)


FOCUS_TARGET = {"vertical": 0.30, "landscape": 0.13}   # target face width as a fraction of the output width (close-up)


def focus_plan(shots: list, people: list, w: int, h: int, aspect: float, out_w: int,
               punch: list[float] | None) -> tuple[list[float], list[float | None]]:
    """Speaker focus: if the face of the person on camera is small in a shot (sitting far away), move in
    (zoom) and frame it so the face sits in the top ~40%.
    - Limits: source quality (upscaling too far gets blurry) and 2x.
    - No zoom when two people share the frame (so no face gets cut).
    Returns: (zoom per shot = focus x punch-in, face height per shot or None)."""
    cw = min(w, h * aspect)
    zmax = max(1.0, min(2.0, cw * 2.5 / out_w))
    target = FOCUS_TARGET["landscape" if aspect > 1 else "vertical"]
    crop_frac = cw / w
    zooms, cys = [], []
    for k, (_, _, cx) in enumerate(shots):
        pz = punch[k] if punch else 1.0
        if not people:
            zooms.append(pz)
            cys.append(None)
            continue
        person = min(people, key=lambda p: abs(p.cx - cx))
        crowd = sum(1 for p in people if abs(p.cx - cx) < crop_frac / 2)   # people in the frame
        frac = person.size * w / cw                                          # face size as a fraction of the output
        fz = 1.0 if crowd > 1 or frac <= 0 else min(max(target / frac, 1.0), zmax)
        zooms.append(round(min(fz * pz, zmax * 1.12), 3))
        cys.append(person.cy if fz > 1.0 else None)
    return zooms, cys


def snap_to_sentence(span: list[float], segments: list[dict], max_len: float = 7.0) -> list[float]:
    """The AI's chosen sentence often started mid-sentence ("hamara is waqt"): snap it to the start and end of
    Whisper's sentence (segment) so the Short starts on a full sentence (if that's too long, keep the AI's)."""
    a, b = span
    first = next((s for s in segments if s["start"] - 0.1 <= a < s["end"]), None)
    last = next((s for s in segments if s["start"] < b <= s["end"] + 0.1), None)
    na = first["start"] if first else a
    nb = last["end"] if last else b
    if nb - na > max_len:                  # the full sentence is too long: at least start at the beginning of the first sentence
        nb = b if b - na <= max_len else nb
        if nb - na > max_len:
            return [a, b]
    return [round(na, 3), round(nb, 3)]


def choose_openings(clips: list, words: list[dict], cached: dict, min_len: float, duration: float,
                    log=print, segments: list[dict] | None = None) -> dict[int, list | None]:
    """Each clip's spoken hook sentence (all at once, in parallel). The clip start moves to that sentence; if
    the clip becomes shorter than min_len, following words are added (without overlapping other clips).
    On --reuse: the previous sentence (the clip already starts there, no new AI call)."""
    from studio.teaser import find_opening

    todo = [i for i in range(len(clips)) if not cached.get(i)]
    found: dict[int, list | None] = {i: cached.get(i) for i in range(len(clips)) if cached.get(i)}
    if todo:
        def job(i):
            notes: list[str] = []
            c = clips[i]
            inside = [w for w in words if c.start <= w["start"] and w["end"] <= c.end + 0.2]
            try:
                return find_opening(inside, c.start, notes.append), notes
            except Exception as e:
                notes.append(f"     Warning: spoken hook not found (clip unchanged): {str(e)[:120]}")
                return None, notes
        with ThreadPoolExecutor(max_workers=4) as pool:
            for i, (span, notes) in zip(todo, pool.map(job, todo)):
                for line in notes:
                    log(line)
                if span and segments:
                    span = snap_to_sentence(span, segments)
                    log(f"     clip {i + 1}: full sentence \"{spoken_text(words, span)}\"")
                found[i] = span

    for i, span in found.items():
        c = clips[i]
        if not span or span[0] <= c.start + 0.05:
            continue
        c.start = span[0]                              # the Short says the hook from its very first word
        if c.end - c.start < min_len:                  # too short now: add following words (up to the next clip)
            limit = min([o.start for o in clips if o is not c and o.start >= c.end] + [duration or c.end + min_len])
            tail = [w for w in words if c.end < w["end"] <= min(c.start + min_len, limit)]
            if tail:
                c.end = tail[-1]["end"] + 0.15
    return found


def head_height(people: list, cx: float, crop: tuple[int, int, int, int], w: int, h: int) -> float:
    """Bottom edge of the text-behind text: the forehead of the person in the first shot (in the new 1080x1920 video).
    Most of the text sits above the head, the bottom part behind it. No face found = the upper part of the screen."""
    if not people:
        return 640
    person = min(people, key=lambda p: abs(p.cx - cx))
    zw, zh, x, zy = crop
    fy = (person.cy * h - zy) / zh * 1920       # face center
    fw = person.size * w / zw * 1080            # face width
    return float(min(max(fy - 0.55 * fw, 480), 1100))   # hairline: only the top of the head comes in front
from studio.denoise import denoise_filter, gate_floor, speech_gate, speech_spans
from studio.fonts import ensure_font, apply_font, URDU as URDU_FONT_FILE


@dataclass
class Settings:
    lang: str | None = None     # None = auto-detect
    clips: int = 5
    min_len: int = 20
    max_len: int = 60
    auto_len: bool = True       # the AI decides each Short's length (min_len..max_len = outer bounds only)
    gap: float = 0.6            # cut silences longer than this
    cut_silence: bool = True
    track_faces: bool = True
    reuse: bool = False         # reuse the previous AI clips
    caption_style: str = "bold_pop"  # from studio/styles.py
    roman: bool = False         # captions in Roman Urdu (Latin letters)
    emphasis: bool = True       # AI key words + emoji
    sfx: bool = True            # whoosh / pop / ding
    music: str | None = "lofi_chill"   # file name in assets/music, or None
    music_volume: float = 0.12
    punch_in: bool = True       # jump cuts par zoom
    hook_anim: str | None = None   # None = from the style; or slide / pop / typewriter / fade
    layout: str = "auto"        # auto / single / split (two people, top and bottom)
    progress_bar: bool = True   # progress bar along the bottom
    name: str = ""              # lower third: guest name (empty = off)
    name_title: str = ""        # lower third: title, e.g. "Founder, Acme Inc."
    broll: bool = True          # stock cutaways (needs PIXABAY_API_KEY or PEXELS_API_KEY)
    counters: bool = True       # numbers count up from 0
    shake: bool = True          # screen shake on big moments
    transition: str = "flash"   # camera badalne / B-roll par: flash / glitch / none
    grade: str = "none"         # color grade: none / warm / cinematic / moody / vivid / bw
    end_card: bool = False      # 2.5 s end screen at the end
    cta: str = "Follow for more"
    handle: str = ""            # e.g. @yourname
    logo: str | None = None     # path to a logo file (PNG/JPG)
    portrait: bool = False      # background blur: speaker sharp, background blurred (AI mask)
    thumbnails: bool = True     # a cover (9:16) + YouTube thumbnail (16:9) for every Short
    combine: bool = True        # join all Shorts into one video at the end (original order)
    focus: bool = True          # speaker focus: move the camera closer to a distant speaker (zoom)
    context: bool = True        # every Short stands alone: needed earlier context (setup) and a finished thought
    bridges: bool = False       # combined video: on-screen connecting line before each part (off: hook shown only once)
    landscape: bool = True      # a 16:9 (YouTube) version of every Short and the combined video too
    combine_smooth: bool = False   # crossfade between clips when joining (re-encode: ~1-2 min more)
    teaser: bool = False        # the strongest line (in the guest's voice) before the clip (it is heard twice)
    story: bool = True          # har clip mukammal kahani: topic → jawab → faida
    hook_start: bool = True     # the Short starts on the sentence where the guest says the hook; those words on screen
    font: str = ""              # caption Google Font ("" = from the style)
    hook_look: str = ""         # hook look: bold / pill / sticker / box / none ("" = from the style)
    denoise: str = "medium"     # background noise hatao: light / medium / strong, "" = band


def get_transcript(video: Path, lang: str | None, log=print, roman: bool = False) -> dict:
    """Reuse an existing transcript (saves free API quota).
    roman = Roman Urdu wanted and language 'Auto': if Whisper said 'English', check that it didn't write an English
    TRANSLATION of Urdu/Hindi speech (Roman Urdu would be impossible then); if so, transcribe again as Urdu."""
    cached = OUTPUT_DIR / f"{video.stem}_transcript.json"
    data = json.loads(cached.read_text(encoding="utf-8")) if cached.exists() else None
    check = roman and not lang
    if data is not None:
        detected = str(data.get("language") or "").lower()
        if not check or detected in ("urdu", "hindi") or data.get("lang_checked"):
            log("     (found a saved transcript, reusing it)")
            return data
        if not detect_urdu(video, OUTPUT_DIR, log):
            data["lang_checked"] = True                 # real English: no further check needed
            cached.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            log("     (found a saved transcript, reusing it)")
            return data
        log("     Saved transcript was an English translation: transcribing again as Urdu...")
        lang = "ur"
    elif check and detect_urdu(video, OUTPUT_DIR, log):
        lang = "ur"

    # short video: the whole audio at once. Long (1-2 hours): chunks straight from the video, in parallel (transcribe_video)
    data = transcribe_video(video, OUTPUT_DIR, language=lang, log=log)
    if check:
        data["lang_checked"] = True
        cached.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


class Timer:
    """How long each step takes (measure first to bring latency down)."""
    def __init__(self):
        self.parts: dict[str, float] = {}
        self.t0 = time.time()

    def add(self, name: str, since: float) -> float:
        now = time.time()
        self.parts[name] = self.parts.get(name, 0.0) + now - since
        return now

    def summary(self) -> str:
        total = time.time() - self.t0
        return f"Total {total:.0f}s: " + " | ".join(f"{k} {v:.0f}s" for k, v in self.parts.items() if v >= 0.5)


def make_shorts(video: Path, s: Settings, log=print) -> tuple[Path, list[dict]]:
    """Long video → Shorts. Returns: (output folder, per-clip report)."""
    from studio import thermal
    thermal.notify = log               # cooling pauses show up in the job log
    out_dir = OUTPUT_DIR / f"{video.stem}_shorts"
    out_dir.mkdir(exist_ok=True)
    seo_path = out_dir / "seo_pack.json"
    timer = Timer()
    tick = time.time()

    log("1/3  Transcribing...")
    data = get_transcript(video, s.lang, log, roman=s.roman)
    tick = timer.add("transcript", tick)
    words = data.get("words", [])
    segments = data.get("segments", [])
    if not words:
        raise RuntimeError("No words found. Does the video have audio?")

    # Roman Urdu only for Urdu/Hindi speech: an English video keeps English hooks/titles
    if s.roman and not needs_roman(words):
        log("     (video is in a Latin-script language: hooks and captions in that language)")
        s = replace(s, roman=False)

    old_marks: dict[int, list | None] = {}     # --reuse par pichle emphasis marks
    old_broll: dict[int, list | None] = {}     # --reuse: previous B-roll (no new search)
    old_teaser: dict[int, list | None] = {}    # --reuse: previous teaser (no new AI call)
    old_open: dict[int, list | None] = {}      # --reuse: previous spoken hook (the clip already starts there)
    old_ctx: dict[int, list | None] = {}       # --reuse: previous setup (earlier context)
    if s.reuse and seo_path.exists():
        log("2/3  Reusing previous AI clips...")
        old = json.loads(seo_path.read_text(encoding="utf-8"))
        clips = [Clip(**{k: v for k, v in item.items() if k in Clip.model_fields}) for item in old]
        # reuse marks only if they were made on words in this same script (Roman or original)
        old_marks = {i: item.get("emphasis") for i, item in enumerate(old)
                     if item.get("emphasis_roman", False) == s.roman}
        # search again for empty B-roll (nothing found / no key last time); keep what was found
        old_broll = {i: item.get("broll") or None for i, item in enumerate(old)}
        old_teaser = {i: item.get("teaser") for i, item in enumerate(old)}
        # only reuse the new full-sentence openings (v2), not the old fragments ("hamara is waqt")
        old_open = {i: item.get("opening") for i, item in enumerate(old) if item.get("opening_v") == 2}
        # setup (earlier context) already decided: reuse it (no new AI call; the clip doesn't move back every run)
        if all("context" in item for item in old):
            old_ctx = {i: item.get("context") for i, item in enumerate(old)}
    else:
        log(f"2/3  AI is finding the best moments ({s.clips} clips)...")
        if s.story:
            log("     Story mode: har clip mukammal kahani (topic → jawab → faida)")
            clips = to_clip_objects(find_story_clips(data, n=s.clips, min_len=s.min_len,
                                                     max_len=s.max_len, log=log), Clip)
        else:
            clips = find_clips(data, n=s.clips, min_len=s.min_len, max_len=s.max_len, log=log, roman=s.roman,
                               auto=s.auto_len)
    if not clips:
        raise RuntimeError("AI found no good clip. Try a shorter minimum clip length.")

    # Spoken hook: the Short starts on the sentence where the guest says the hook (everything before is cut).
    # All clips at once (parallel), BEFORE Roman Urdu (so new words from a longer clip get converted too)
    tick = timer.add("AI clips + hooks", tick)
    openings: dict[int, list | None] = {}
    if s.hook_start and not s.story:
        openings = choose_openings(clips, words, old_open, s.min_len, data.get("duration", 0), log, segments)
        tick = timer.add("spoken hook", tick)
    # Every Short stands alone: clip extended to the sentence end, needed earlier context (setup) included
    snap_ends(clips, segments)
    contexts: dict[int, list | None] = {i: old_ctx.get(i) for i in range(len(clips))} if old_ctx else {}
    if s.context and not old_ctx:
        contexts = add_context(clips, openings, segments, s, log)
        tick = timer.add("context (setup)", tick)
    # the thumbnail's own short text (2-4 words); created here for old packs / AI failures
    if s.thumbnails:
        fill_thumb_texts(clips, data, s.roman, log)

    if s.roman:
        # only the chosen clips' words (converting a long video's full transcript takes a long time)
        words = romanize(words, OUTPUT_DIR / f"{video.stem}_roman.json", log,
                         ranges=[(min(c.start, (contexts.get(i) or [c.start])[0]), c.end)
                                 for i, c in enumerate(clips)])
        # hooks and titles both (a small AI model sometimes writes the title in Urdu script)
        n = len(clips)
        texts = romanize_texts([c.hook_text for c in clips] + [c.title for c in clips]
                               + [c.thumb_text or "-" for c in clips], log)
        for k, clip in enumerate(clips):
            clip.hook_text, clip.title = texts[k], texts[n + k]
            clip.thumb_text = "" if texts[2 * n + k] == "-" else texts[2 * n + k]
    tick = timer.add("thumbnail text + Roman", tick)

    style = STYLES.get(s.caption_style, STYLES[DEFAULT_STYLE])
    style = apply_font(style, s.font, log)
    no_hook = s.hook_look == "none"        # 'None': no hook text on screen (the hook still goes in the title)
    if s.hook_look and not no_hook:        # hook look chosen separately from the style (bold / pill / sticker / box)
        style = replace(style, hook_look=s.hook_look)
    ensure_font(URDU_FONT_FILE, log)       # Nastaliq too, for Urdu script
    use_broll = s.broll and broll_ready()
    if s.broll and not use_broll:
        log("     (B-roll off: assets/broll is empty and there is no PIXABAY / PEXELS / UNSPLASH key in .env)")
    ensure_sounds()   # create the sounds on first run, otherwise music_path won't find lofi_chill
    track = music_path(s.music) if s.music else None
    if s.music and track is None:
        log(f"     Warning: music '{s.music}' not found in assets/music, continuing without music")

    # Background noise: build the filter once (model downloaded the first time), same for every clip
    noise = denoise_filter(s.denoise, cwd=out_dir, log=log) if s.denoise else ""
    if noise:
        how = "RNNoise lq+sh" if noise.count("arnndn") > 1 else "RNNoise lq" if "arnndn" in noise else "FFT filter"
        gated = " + speech gate in pauses" if gate_floor(s.denoise) is not None else ""
        log(f"     Removing background noise ({how}{gated}, {s.denoise})")

    log(f"3/3  Editing + rendering {len(clips)} clips...")
    tick = timer.add("prep", tick)

    # Latency: each clip's AI work (teaser, key words, B-roll) and face scan don't depend on each other.
    # Start them all in parallel (threads) right at the BEGINNING: while clip 1 renders, the other
    # clips' AI work is already done. Threads don't log directly (it wouldn't show on the website): each clip's
    # messages go into a list and are shown in order when that clip's turn comes.
    pool = ThreadPoolExecutor(max_workers=4)

    def guarded(say, what: str, fn, default):
        def run():
            try:
                return fn()
            except Exception as e:      # the Short still gets made if one job fails
                say(f"     Warning: skipped {what}: {hide_keys(str(e))[:150]}")
                return default
        return pool.submit(run)

    plans = []
    for idx, clip in enumerate(clips):
        # a) Silence removal: spoken parts only (spoken hook → setup → rest, if a setup is needed)
        rngs = compose_ranges(words, clip, openings.get(idx), contexts.get(idx), s)
        notes: list[str] = []
        say = notes.append
        jobs = {}
        if s.track_faces:                  # faces scanned once (the teaser is inside this clip too)
            jobs["people"] = guarded(say, "Face scan", lambda r=rngs: find_people(video, min(a for a, _ in r),
                                                                                   max(b for _, b in r)), [])
        if s.teaser and not s.hook_start and old_teaser.get(idx) is None:   # no teaser when there is a spoken hook
            jobs["teaser"] = guarded(say, "Teaser", lambda r=rngs, c=clip, say=say:
                                     find_teaser(words_inside(words, r), c.start, say), None)
        if s.emphasis and old_marks.get(idx) is None:
            jobs["marks"] = guarded(say, "Emphasis", lambda r=rngs, say=say: find_emphasis(words_inside(words, r), say), [])
        if use_broll and old_broll.get(idx) is None:
            def broll_job(r=rngs, say=say):
                inside = words_inside(words, r)
                # don't even give the AI the hook's words (first 3 s): B-roll can't go there
                pickable = [w for w in inside if w["start"] >= inside[0]["start"] + 3.0] if inside else []
                return find_footage(choose_moments(pickable, say), say)
            jobs["broll"] = guarded(say, "B-roll", broll_job, [])
        plans.append((rngs, notes, jobs))

    report, thumb_jobs = [], []
    # Latency: most FFmpeg filters (captions, blur, overlay) run on a single CPU core. Running 3 renders
    # at once puts the other cores to work too (Shorts + 16:9 + combined video all use this pool).
    render_pool = ThreadPoolExecutor(max_workers=RENDER_WORKERS)
    render_jobs: list[tuple[int, str, object]] = []
    combo_parts: list[dict] = []        # each clip's plan for the combined video (no new AI call, same everything)
    vw, vh = video_size(video)          # source video size (for focus and crop math)
    for i, clip in enumerate(clips, start=1):
        name = f"clip_{i:02}"
        ranges, notes, jobs = plans[i - 1]
        tick = time.time()
        results = {k: f.result() for k, f in jobs.items()}     # usually ready already (it ran in parallel)
        for line in notes:
            log(line)
        notes.clear()
        tick = timer.add("AI + faces (wait)", tick)
        main_ranges = ranges
        ctx = contexts.get(i - 1)
        setup_len = (ctx[1] - ctx[0]) if ctx else 0.0     # added earlier context (logged separately from silence cuts)

        # a2) Teaser: the strongest line (in the guest's own voice) before the clip
        teaser = None
        if s.teaser and not s.hook_start:
            teaser = old_teaser.get(i - 1)
            if teaser is None:
                teaser = results.get("teaser")
            if teaser:
                ranges = [tuple(teaser)] + ranges
        teaser_len = teaser[1] - teaser[0] if teaser else 0.0

        # The Short starts on the guest's spoken hook sentence; on screen, the AI's strong, complete (stand-alone)
        # hook. Writing the spoken words directly produced fragments ("hamara is waqt").
        # the hook stays as long as the opening sentence is being spoken (at least 3 s, at most 5)
        opening = openings.get(i - 1)
        spoken = spoken_text(words, opening) if opening else ""
        on_screen = "" if no_hook else clip.hook_text
        hook_secs = min(max(opening[1] - opening[0] + 0.4, HOOK_SECONDS), 5.0) if opening else HOOK_SECONDS

        # b) Every sentence is a 'shot'; face tracking frames each shot (faces were already scanned)
        pieces = split_at_sentences(ranges, segments)
        people = results.get("people", []) if s.track_faces else []
        shots = plan_shots(video, pieces, track=s.track_faces, tracks=people)
        moves = sum(1 for k in range(1, len(shots)) if abs(shots[k][2] - shots[k - 1][2]) > 0.05)

        # Layout: split when two people sit far apart and (in auto) the conversation went back and forth at least twice
        pair = split_pair(video, people) if s.track_faces and s.layout != "single" else None
        split = pair if pair and (s.layout == "split" or moves >= 2) else None
        caption_margin = 910 if split else None     # in split mode the captions sit on the center line

        # c) AI key words + emoji (reuse the previous ones if present, saves an AI call)
        marks = []
        if s.emphasis:
            marks = old_marks.get(i - 1)
            if marks is None:
                marks = results.get("marks") or []          # already made in parallel
            marks = [m for m in marks if not is_filler(m["word"])]   # clean old saved marks too

        # d) Captions on the new timeline (+ lower third if a name is given and the clip is long enough)
        new_words = remap_words(words, ranges)
        lower = None
        if s.name.strip() and total(ranges) >= LOWER_START + LOWER_SECONDS + 1:
            lower_y = 990 if split else 1020      # split: above the bottom (right) person
            lower = (s.name, s.name_title, lower_y)
        counters = find_counters(new_words) if s.counters else []
        logo = Path(s.logo) if s.end_card and s.logo and Path(s.logo).exists() else None
        end_lines = end_card_lines(total(ranges), s.cta, s.handle, logo is not None) if s.end_card else []
        ass_path = out_dir / f"{name}.ass"
        # Text behind person: the hook in a separate file (the render pastes the person on top). Not in split mode
        # (two people, half the screen each): a normal 'bold' hook there.
        behind = style.hook_look == "behind" and not split
        clip_style = style if style.hook_look != "behind" or behind else replace(style, hook_look="bold")

        def write_main_ass(with_hook: bool):
            ass_path.write_text(words_to_ass(new_words, hook_text=on_screen if with_hook else "", hook_seconds=hook_secs,
                                             style=clip_style, emphasis={m["start"] for m in marks},
                                             hook_anim=s.hook_anim, margin_v=caption_margin, lower=lower,
                                             extra=counter_lines(counters, style) + end_lines),
                                encoding="utf-8")
        write_main_ass(with_hook=not behind)

        # e) Emoji pop: a little above the captions, at the word's time; at least 1.2 s between emoji
        new_time = {round(w["orig_start"], 2): w["start"] for w in new_words}
        emoji_y = 1920 - (caption_margin or style.margin_v) - int(style.size * 1.4) - 250
        overlays, last = [], -10.0
        for m in sorted(marks, key=lambda m: m["start"]):
            at = new_time.get(round(m["start"], 2))
            # old saved marks may contain emoji: skip them too when VIDEO_EMOJI is off
            frames = pop_frames(m["emoji"]) if m["emoji"] and VIDEO_EMOJI else None
            if at is None or frames is None or at < 3.0 or at - last < 1.2:
                continue    # the first 3 s belong to the hook: no emoji there
            if lower and LOWER_START - 0.5 <= at <= LOWER_START + LOWER_SECONDS:
                continue    # no emoji while the name lower third shows (they'd overlap)
            overlays.append((frames, at, emoji_y))
            last = at

        # e2) Auto B-roll: not during the hook (first 3 s) or the lower third, at least 2 s between B-roll
        items, broll_inputs = [], []
        if use_broll:
            items = old_broll.get(i - 1)
            if items is None:
                items = results.get("broll") or []          # already found in parallel
            clip_len, last_end = total(ranges), -10.0
            def fits(at):
                if at < 3.0 or at + BROLL_SECONDS > clip_len - 0.5 or at - last_end < 2.0:
                    return False
                return not (lower and at < LOWER_START + LOWER_SECONDS and at + BROLL_SECONDS > LOWER_START)

            starts = sorted(new_time.values())
            for it in sorted(items, key=lambda it: it["start"]):
                at = new_time.get(round(it["start"], 2))
                if at is None or not fits(at):
                    # pick in a bad spot (hook / lower third / end): move it to the next valid word
                    moved = next((t for t in starts if t >= (at or 0) and fits(t)), None)
                    if moved is None:
                        log(f"     Warning: no room for B-roll '{it['query']}' ({at}s), skipped")
                        continue
                    at = moved
                try:
                    broll_inputs.append((download(it), at, BROLL_SECONDS))
                    last_end = at + BROLL_SECONDS
                except Exception as e:
                    log(f"     Warning: B-roll download failed: {hide_keys(str(e))[:120]}")

        # e3) End screen logo: pops in as soon as the content ends and stays to the end
        n_emoji = len(overlays)                 # for the log (the logo isn't an emoji)
        if logo:
            frames = logo_frames(logo, END_SECONDS)
            canvas = int(360 * 1.25)
            overlays.append((frames, total(ranges), LOGO_CENTER_Y - canvas // 2))

        # f) Sound effects: a ding at the start (hook), a pop on every emoji, a whoosh on camera switches
        effects = []
        if s.sfx:
            effects.append((sound("ding"), 0.0, 0.35))
            if s.end_card:
                effects.append((sound("whoosh"), total(ranges) - 0.22, 0.4))      # when the end screen comes in
            effects += [(sound("pop"), at, 0.6) for _, at, _ in overlays]
            t, last_whoosh = 0.0, -10.0
            for k, (a, b, cx) in enumerate(shots if not split else []):   # the camera doesn't move in split mode
                if k > 0 and abs(cx - shots[k - 1][2]) > 0.05 and t - last_whoosh > 1.5:
                    effects.append((sound("whoosh"), t - 0.22, 0.45))   # center the whoosh on the cut
                    last_whoosh = t
                t += b - a
            effects += [(sound("whoosh"), at - 0.22, 0.35) for _, at, _ in broll_inputs]   # when B-roll comes in
            if teaser:
                effects.append((sound("whoosh"), teaser_len - 0.22, 0.5))   # teaser over, the real clip starts

        # f2) Shake (when a number lands + on 'impact' emoji) and transitions (camera / B-roll changes)
        shakes = []
        if s.shake:
            candidates = [at + COUNT_SECONDS for at, _ in counters]                  # number land hone par
            candidates += [at for frames, at, _ in overlays if frames.name in IMPACT]   # on 🔥😱🤯 emoji
            for t in sorted(candidates):
                if not shakes or t - shakes[-1] > 1.0:        # at least 1 s between shakes
                    shakes.append(t)
            shakes = shakes[:4]
        cuts, t = [], 0.0
        for k, (a, b, cx) in enumerate(shots if not split else []):
            if k > 0 and abs(cx - shots[k - 1][2]) > 0.05:
                cuts.append(t)
            t += b - a
        cuts += [at for _, at, _ in broll_inputs] + [at + d for _, at, d in broll_inputs]
        if teaser:
            cuts.append(teaser_len)        # teaser → clip: flash/glitch, so it's clear the real clip starts now
        cuts = sorted(cuts) if s.transition in ("flash", "glitch") else []
        if s.sfx:
            effects += [(sound("pop"), at + COUNT_SECONDS, 0.4) for at, _ in counters]

        # g) Zoom punch-ins + speaker focus (distant speaker: the camera moves closer)
        punch = plan_zooms(shots) if s.punch_in and not split else None
        zooms, cys = punch, None
        if s.focus and people and not split:
            zooms, cys = focus_plan(shots, people, vw, vh, 9 / 16, 1080, punch)
        punches = sum(1 for z in (punch or []) if z > 1)
        focused = sum(1 for c in (cys or []) if c is not None)

        # g2) Clean voice: noise models + (on Strong) a speech gate: background muted in every pause
        audio_fx = noise
        floor = gate_floor(s.denoise) if noise else None
        if floor is not None:
            gate = speech_gate(speech_spans(new_words), floor)
            audio_fx = f"{noise},{gate}" if gate else noise

        tick = timer.add("captions, emoji, sfx plan", tick)

        # g3) Segmentation mask (AI, on CPU): background blur and/or text behind person
        portrait = s.portrait and not split
        mask_path, behind_path = None, None
        if portrait or behind:
            w, h = vw, vh
            crops = [shot_crop(w, h, cx, z, cy) for (_, _, cx), z, cy in
                     zip(shots, zooms or [1.0] * len(shots), cys or [None] * len(shots))]
            try:
                log(f"     Building person mask ({'full clip, blur' if portrait else '3 s hook'})...")
                mask_path = mask_video(video, shots, crops, out_dir / f"{name}_mask.avi",
                                       until=None if portrait else hook_secs + 0.2, log=log)
            except Exception as e:      # no mask: blur off, hook in the normal (bold) look
                log(f"     Warning: mask failed ({type(e).__name__}: {str(e)[:100]}): blur / text-behind off")
                portrait = False
                if behind:
                    behind, clip_style = False, replace(style, hook_look="bold")
                    write_main_ass(with_hook=True)
            if behind and mask_path:
                behind_path = out_dir / f"{name}_behind.ass"
                behind_path.write_text(behind_hook_ass(on_screen, style, hook_secs,
                                                       head_height(people, shots[0][2], crops[0], w, h),
                                                       caption_margin), encoding="utf-8")
        tick = timer.add("person mask", tick)

        # h) Render: in the background (render pool). The loop keeps preparing the next clip.
        mp4 = out_dir / f"{name}.mp4"

        def vertical_job(mp4=mp4, ass_path=ass_path, overlays=list(overlays), effects=list(effects), zooms=zooms,
                         split=split, broll_inputs=list(broll_inputs), shakes=list(shakes), cuts=list(cuts),
                         audio_fx=audio_fx, mask_path=mask_path, portrait=portrait, behind_path=behind_path,
                         hook_secs=hook_secs, cys=cys, shots=shots):
            try:
                return render_shots(video, shots, mp4, ass_path, overlays,
                                    sfx=effects, music=track, music_volume=s.music_volume, zooms=zooms, split=split,
                                    progress_color=style.highlight if s.progress_bar else None,
                                    broll=broll_inputs, shakes=shakes, transitions=cuts,
                                    transition_style=s.transition, grade=grade_filter(s.grade),
                                    end_card=END_SECONDS if s.end_card else 0.0, denoise=audio_fx,
                                    person_mask=mask_path, portrait=portrait, behind_ass=behind_path,
                                    behind_until=hook_secs, centers_y=cys)
            finally:
                if mask_path:
                    mask_path.unlink(missing_ok=True)     # the mask was only needed for the render (a big file)
        render_jobs.append((len(report), "vertical", render_pool.submit(vertical_job)))
        tick = timer.add("render start (background)", tick)

        # h2) 16:9 (landscape, YouTube) version: same plan, captions / focus / positions adapted to landscape
        wide_file = None
        lz, lcy = (focus_plan(shots, people, vw, vh, 16 / 9, 1920, punch) if s.focus and people
                   else (punch, None))
        if s.landscape:
            try:
                with caption_canvas(1920, 1080):
                    wide_ass = out_dir / f"{name}_16x9.ass"
                    wide_style = clip_style if clip_style.hook_look != "behind" else replace(clip_style, hook_look="bold")
                    wide_lower = (s.name, s.name_title, 1080 - 300) if lower else None
                    wide_end = end_card_lines(total(ranges), s.cta, s.handle, logo is not None) if s.end_card else []
                    wide_ass.write_text(words_to_ass(new_words, hook_text=on_screen, hook_seconds=hook_secs,
                                                     style=wide_style, emphasis={m["start"] for m in marks},
                                                     hook_anim=s.hook_anim, lower=wide_lower,
                                                     extra=counter_lines(counters, style) + wide_end),
                                        encoding="utf-8")
                wide_y = 1080 - int(1080 * 0.11) - int(style.size * 1.4) - 200
                wide_overlays = [(f, at, wide_y) for f, at, _ in overlays[:n_emoji]]
                if logo:
                    wide_overlays.append((logo_frames(logo, END_SECONDS), total(ranges),
                                          round(1080 * LOGO_CENTER_Y / 1920) - int(360 * 1.25) // 2))
                wide_job = partial(render_shots, video, shots, out_dir / f"{name}_16x9.mp4", wide_ass, wide_overlays,
                                   sfx=list(effects), music=track, music_volume=s.music_volume, zooms=lz, split=None,
                                   progress_color=style.highlight if s.progress_bar else None,
                                   broll=list(broll_inputs), shakes=list(shakes), transitions=list(cuts),
                                   transition_style=s.transition, grade=grade_filter(s.grade),
                                   end_card=END_SECONDS if s.end_card else 0.0, denoise=audio_fx,
                                   canvas=(1920, 1080), centers_y=lcy)
                render_jobs.append((len(report), "landscape", render_pool.submit(wide_job)))
                wide_file = f"{name}_16x9.mp4"          # render khatam hone par pakka (fail ho to None)
            except Exception as e:      # even if landscape fails, the vertical Short is done
                log(f"     Warning: 16:9 version failed: {type(e).__name__}: {str(e)[:120]}")
            tick = timer.add("16:9 prep", tick)

        # i) Thumbnails: in the background (ready while the next clip renders); the Short is done even if they fail
        thumbs = []
        if s.thumbnails:
            thumb_notes: list[str] = []
            thumb_jobs.append((len(report), thumb_notes, guarded(
                thumb_notes.append, "Thumbnail",
                lambda sh=shots, hk=clip.thumb_text or clip.hook_text, nm=name: [p.name for p in make_thumbnails(video, sh, hk, style,
                                                                                              out_dir, nm)], [])))

        before, after = clip.end - clip.start, total(ranges)
        log(f"     {name}  score {clip.hook_score:>3}  {before:4.1f}s → {after:4.1f}s  "
            f"({max(0.0, before - total(main_ranges) + setup_len):.1f}s silence cut, {f'+{setup_len:.1f}s setup (context), ' if setup_len else ''}{f'{teaser_len:.1f}s teaser, ' if teaser else ''}{moves} camera moves, {len(marks)} key words, "
            f"{n_emoji} emoji, {len(effects)} sfx, {punches} zoom, {len(broll_inputs)} b-roll, {len(counters)} counter, {len(shakes)} shake{', SPLIT' if split else ''}{', end screen' if s.end_card else ''}{', blur' if portrait else ''}{', text behind' if behind_path else ''}{f', focus {focused} shots' if focused else ''}{', +16:9' if wide_file else ''})  {clip.title}")
        report.append({"file": mp4.name, **clip.model_dump(),
                       "original_seconds": round(before, 2), "final_seconds": round(after, 2),
                       "emphasis": marks, "emphasis_roman": s.roman,
                       "layout": "split" if split else "single", "teaser": teaser,
                       "opening": opening, "opening_v": 2, "spoken_hook": spoken, "landscape": wide_file,
                       "context": contexts.get(i - 1),
                       "broll": items,    # credits (photographer + link + site) go here too
                       "thumbnails": thumbs})
        combo_parts.append({"start": clip.start, "file": mp4.name, "hook": on_screen, "shots": shots,
                            "zooms": zooms or [1.0] * len(shots), "cys": cys or [None] * len(shots),
                            "wide_zooms": lz or [1.0] * len(shots), "wide_cys": lcy or [None] * len(shots),
                            "words": new_words,
                            "emph": {m["start"] for m in marks}, "emoji": overlays[:n_emoji],
                            "broll": broll_inputs, "split": split, "length": total(ranges)})
        tick = timer.add("other", tick)

    # The combined video at the same time (excerpt + both sizes, in the render pool), alongside the Shorts' renders
    tick = time.time()
    for old_file in ("combined.mp4", "combined_16x9.mp4", "combined.json"):        # remove the old one (from a previous run)
        (out_dir / old_file).unlink(missing_ok=True)
    combined = None
    if s.combine and len(report) >= 2:
        try:
            # Main method: one render, the hook only at the start, a transition + whoosh at every join
            combined = render_combined(video, combo_parts, s, style, out_dir, noise, track, log, pool=render_pool)
        except Exception as e:
            log(f"     Warning: combined video render failed ({type(e).__name__}: {str(e)[:120]}): "
                "joining Shorts directly")

    # wait for the Shorts' renders (usually done together with the combined video)
    for idx, kind, fut in render_jobs:
        if kind == "vertical":
            fut.result()                        # if a vertical Short fails, the whole run fails (as before)
            continue
        try:
            fut.result()
        except Exception as e:                  # even if 16:9 fails, the vertical one is done
            report[idx]["landscape"] = None
            log(f"     Warning: 16:9 version of {report[idx]['file']} failed: {type(e).__name__}: {str(e)[:100]}")
    render_pool.shutdown(wait=True)
    log(f"     {len(render_jobs) + (2 if combined and s.landscape else 1 if combined else 0)} videos rendered "
        f"({RENDER_WORKERS} at a time)")
    timer.add("render (all)", tick)

    # thumbnails (made in the background): add them to the report
    tick = time.time()
    for idx, thumb_notes, job in thumb_jobs:
        report[idx]["thumbnails"] = job.result()
        for line in thumb_notes:
            log(line)
    if thumb_jobs:
        log(f"     {sum(len(r['thumbnails']) for r in report)} thumbnails ready")
    timer.add("thumbnails (remaining wait)", tick)
    pool.shutdown(wait=True)

    seo_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # j) Combined video title / description (and if its render failed, join the Shorts directly)
    tick = time.time()
    if s.combine and len(report) >= 2:
        try:
            if combined is None:
                combined = combine_clips(out_dir, report, END_SECONDS if s.end_card else 0.0, log=log,
                                         smooth=s.combine_smooth)
            if combined:
                order = sorted(report, key=lambda r: r.get("start", 0))
                language = ("Roman Urdu (Urdu written with English letters)" if s.roman
                            else (data.get("language") or "the same language as the clips"))
                meta = combined_meta(order, language, log)
                wide = out_dir / "combined_16x9.mp4"
                info = {"file": combined.name, "landscape": wide.name if wide.exists() else None,
                        "order": [r["file"] for r in order], **meta}
                (out_dir / "combined.json").write_text(json.dumps(info, ensure_ascii=False, indent=2),
                                                       encoding="utf-8")
                log(f"     Combined video title: {meta['title']}")
        except Exception as e:      # even if joining fails, the individual Shorts are ready
            log(f"     Warning: could not join clips: {type(e).__name__}: {str(e)[:150]}")
        timer.add("joining clips", tick)

    log(f"     {timer.summary()}")
    return out_dir, report
