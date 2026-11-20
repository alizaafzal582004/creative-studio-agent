import os
import tempfile
import uuid
from pathlib import Path

from studio.config import FONTS_DIR
from studio.ffmpeg import run_ffmpeg, move_into_place
from studio.framing import video_size

# Ducking: when the voice rises above the threshold, the music is pushed down by the ratio.
# Tested: ~17 dB quieter on loud speech, ~8-12 dB on normal talk. attack/release = how fast it ducks/recovers (ms)
DUCKING = "threshold=0.005:ratio=20:attack=15:release=350:knee=1"
# Every video at one loudness: quiet (-28 dB) and loud (-14 dB) both become -16 LUFS. loudnorm runs at
# 192 kHz internally, so resample back to 48 kHz.
SPEECH_LOUDNESS = "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000"



def subtitles_filter(ass_path: Path) -> str:
    """Captions filter. Paths are kept relative to avoid the Windows 'C:' issue."""
    fonts = os.path.relpath(FONTS_DIR, ass_path.parent).replace("\\", "/")
    return f"subtitles={ass_path.name}:fontsdir={fonts}"


def even(n: float) -> int:
    """Video width/height must always be even (an H.264 requirement)."""
    return int(n) // 2 * 2


def split_screen_chain(i: int, s: float, e: float, speaker_cx: float,
                       pair: tuple[float, float], w: int, h: int) -> str:
    """Turn one shot into split-screen: left person on top, right person below (both 1080x960), a thin line between.
    The speaker stays bright, the other is slightly dimmed. If unsure, both stay bright."""
    half_h = even(h * 0.85)                 # slight zoom: faces look bigger
    half_w = even(min(w, half_h * 9 / 8))   # 1080x960 = a 9:8 shape
    half_h = even(half_w * 8 / 9)
    y = int(min(max(0.45 * h - half_h / 2, 0), h - half_h))
    left, right = pair

    def crop_at(cx: float) -> str:
        x = int(min(max(cx * w - half_w / 2, 0), w - half_w))
        return f"crop={half_w}:{half_h}:{x}:{y},scale=1080:960,setsar=1"

    dist_left, dist_right = abs(speaker_cx - left), abs(speaker_cx - right)
    dim = "eq=brightness=-0.07:saturation=0.75"
    top_fx = f",{dim}" if dist_right < dist_left * 0.5 else ""      # right person speaking: dim the top
    bottom_fx = f",{dim}" if dist_left < dist_right * 0.5 else ""   # left person speaking: dim the bottom

    return (f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS,split=2[sa{i}][sb{i}];"
            f"[sa{i}]{crop_at(left)}{top_fx}[top{i}];"
            f"[sb{i}]{crop_at(right)}{bottom_fx}[bot{i}];"
            f"[top{i}][bot{i}]vstack,drawbox=x=0:y=957:w=1080:h=6:color=white@0.9:t=fill[v{i}]")


IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}   # still images in B-roll get a zoom (Ken Burns)
SHAKE_SECONDS, SHAKE_PX = 0.3, 16
FLASH_SECONDS, GLITCH_SECONDS = 0.22, 0.15


def shot_crop(w: int, h: int, cx: float, zoom: float = 1.0, cy: float | None = None,
              aspect: float = 9 / 16) -> tuple[int, int, int, int]:
    """Crop of one shot (width, height, x, y) in the source video, at the output's aspect (9:16 or 16:9).
    zoom > 1 = a smaller area (punch-in / speaker focus). cy = face height (0-1): if given, the frame is placed
    so the face sits in the top ~40% (head not cut, body visible below).
    Used by both the render and the segmentation mask so the mask lines up exactly with the video."""
    cw, ch = even(min(w, h * aspect)), even(min(h, w / aspect))
    zw, zh = even(cw / zoom), even(ch / zoom)
    x = int(min(max(cx * w - zw / 2, 0), w - zw))   # keep the frame inside the video
    if cy is not None and zoom > 1:
        zy = int(min(max(cy * h - zh * 0.40, 0), h - zh))
    elif zoom > 1:
        # faces are usually in the upper part: zoom centered at 42% height
        zy = int(min(max(0.42 * h - zh / 2, 0), h - zh))
    else:
        zy = (h - ch) // 2
    return zw, zh, x, zy


def gate(times: list[float], dur: float) -> str:
    """FFmpeg expression that is 1 at those times and 0 otherwise: between(t,a,a+dur)+..."""
    return "+".join(f"between(t,{t:.3f},{t + dur:.3f})" for t in times) or "0"


def render_shots(video: Path, shots: list[tuple[float, float, float]], out_path: Path,
                 ass_path: Path | None = None,
                 overlays: list[tuple[Path, float, int]] | None = None,
                 sfx: list[tuple[Path, float, float]] | None = None,
                 music: Path | None = None, music_volume: float = 0.12,
                 zooms: list[float] | None = None,
                 split: tuple[float, float] | None = None,
                 progress_color: str | None = None,
                 broll: list[tuple[Path, float, float]] | None = None,
                 shakes: list[float] | None = None,
                 transitions: list[float] | None = None, transition_style: str = "flash",
                 grade: str = "", end_card: float = 0.0, denoise: str = "",
                 person_mask: Path | None = None, portrait: bool = False,
                 behind_ass: Path | None = None, behind_until: float = 3.0,
                 canvas: tuple[int, int] = (1080, 1920), centers_y: list[float | None] | None = None) -> Path:
    """Advanced version: crop each shot (a, b, cx) from its own position, skip the silent parts,
    join everything (concat), then burn in captions.
    overlays = [(frames_folder, start_second, y_position), ...]  e.g. emoji pop.
    sfx      = [(wav_file, play_second, volume), ...]            e.g. whoosh, pop, ding.
    music    = background music file; ducks automatically under speech.
    zooms    = zoom per shot (1.0 = wide, 1.12 = punch-in), one per shot.
    split    = (left person's cx, right person's cx): screen split into top and bottom halves.
    progress_color = a color like 'FFE000': bottom progress bar that fills with the video; None = off.
    broll    = [(stock_video, start_second, duration), ...]: full-screen cutaway, below the captions.
    shakes   = [second, ...]: screen shakes for 0.3 s at those times (big moments).
    transitions = [second, ...]: a 'flash' (white) or 'glitch' (color shift) at those times.
    grade    = FFmpeg color grade chain (studio/grades.py), "" = none.
    end_card = end screen of this many seconds: the last frame freezes, blurs and darkens.
               Its text/logo come from the captions (ASS) and overlays.
    denoise  = voice noise filter (studio/denoise.py), "" = off.
    person_mask = segmentation mask video (studio/segment.py): white = person. Enables:
      portrait    = True: person sharp, background blurred (portrait mode)
      behind_ass  = separate ASS file for the hook: text BEHIND the person (until behind_until seconds).
    canvas   = output size: (1080, 1920) vertical Shorts or (1920, 1080) landscape (YouTube).
    centers_y = face height per shot (0-1, speaker focus) or None."""
    W, H = canvas
    aspect = W / H
    if W > H:
        split = None                     # split-screen only on vertical (top/bottom)
    broll = broll or []
    shakes = shakes or []
    transitions = transitions or []
    overlays = overlays or []
    sfx = sfx or []
    zooms = zooms or [1.0] * len(shots)
    w, h = video_size(video)

    # a teaser (a line from mid-clip) can come first, so shots aren't in time order: use min/max
    clip_start = min(a for a, _, _ in shots)
    clip_end = max(b for _, b, _ in shots)

    parts, labels = [], []
    for i, (a, b, cx) in enumerate(shots):
        s, e = a - clip_start, b - clip_start             # after -ss, time starts at 0
        if split:
            parts.append(split_screen_chain(i, s, e, cx, split, w, h))
            parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
            labels.append(f"[v{i}][a{i}]")
            continue

        if w / h < aspect * 0.75:
            # landscape (16:9) version of a portrait (9:16) video: the full video centered over a blurred copy of itself
            # (cropping would leave only a thin strip around the face)
            parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS,split=2[pa{i}][pb{i}];"
                         f"[pa{i}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2[pg{i}];"
                         f"[pb{i}]scale=-2:{H}[pf{i}];[pg{i}][pf{i}]overlay=(W-w)/2:0,setsar=1[v{i}]")
        else:
            cy = centers_y[i] if centers_y and i < len(centers_y) else None
            zw, zh, x, zy = shot_crop(w, h, cx, zooms[i], cy, aspect)
            parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS,"
                         f"crop={zw}:{zh}:{x}:{zy},scale={W}:{H},setsar=1[v{i}]")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")

    parts.append(f"{''.join(labels)}concat=n={len(shots)}:v=1:a=1[cv][ca]")
    vout = "[cv]"
    content = sum(b - a for a, b, _ in shots)          # actual video length (without the end screen)

    # Voice: (1) remove background noise, (2) normalize loudness (-16 LUFS, the Shorts/YouTube standard).
    # Otherwise, on a quiet video the music sounds as loud as the speaker ("there's noise in the background").
    voice_fx = [f for f in (denoise, SPEECH_LOUDNESS) if f]
    parts.append(f"[ca]{','.join(voice_fx)}[cad]")
    speech = "[cad]"

    # Segmentation mask (the last input, after all others): portrait blur and/or text behind person
    use_portrait = bool(person_mask and portrait)
    use_behind = bool(person_mask and behind_ass)
    if use_portrait or use_behind:
        n_audio = (len(sfx) + (1 if music else 0)) if (sfx or music) else 0
        mask_idx = 1 + len(broll) + len(overlays) + n_audio
        prep = f"[{mask_idx}:v]scale={W}:{H},format=gray,setpts=PTS-STARTPTS"
        if use_portrait and use_behind:
            parts.append(f"{prep},split=2[pm1][pm2]")
        else:
            parts.append(f"{prep}[{'pm1' if use_portrait else 'pm2'}]")

    # Portrait mode: one blurred copy, one sharp; the mask shows the sharp copy only where the person is
    if use_portrait:
        parts.append(f"{vout}split=2[pa][pb];[pb]boxblur=20:2[pbb];[pa][pm1]alphamerge[pfg];"
                     f"[pbb][pfg]overlay=format=auto:eof_action=pass,format=yuv420p[pv]")
        vout = "[pv]"

    # End screen: freeze the last frame for end_card seconds, then blur + darken it (so the text is readable)
    # (use the previous label, not [cv] directly: otherwise blur + end screen both claim [cv] and FFmpeg crashes)
    if end_card > 0:
        on = f"gte(t,{content:.3f})"
        parts.append(f"{vout}tpad=stop_mode=clone:stop_duration={end_card:.3f},"
                     f"boxblur=20:enable='{on}',eq=brightness=-0.28:saturation=0.6:enable='{on}'[ecv]")
        parts.append(f"{speech}apad=pad_dur={end_card:.3f}[eca]")
        vout = "[ecv]"

    extra_inputs = []

    # Shake: scale the video up 4%, then move the crop back and forth only during shakes
    if shakes:
        g = gate(shakes, SHAKE_SECONDS)
        sw, sh = even(W * 1.04), even(H * 1.04)          # 4% bigger, then a moving crop
        parts.append(f"{vout}scale={sw}:{sh},crop={W}:{H}:"
                     f"x='{(sw - W) // 2}+{SHAKE_PX}*sin(2*PI*t*23)*({g})':y='{(sh - H) // 2}+{SHAKE_PX * 0.7:.0f}*cos(2*PI*t*31)*({g})'[shk]")
        vout = "[shk]"

    # B-roll: crop the stock video to 9:16, shift it to the right time, and overlay it BEFORE the captions
    # (so the captions also show on top of the B-roll). The stock video's audio is never used.
    for k, (clip, at, dur) in enumerate(broll, start=1):
        cover = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        if clip.suffix.lower() in IMAGE_EXT:
            # Still image (Unsplash / your folder): 'Ken Burns' = a slow 8% zoom-in so it feels alive
            extra_inputs += ["-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", str(clip.resolve())]
            cover += (f",scale=w='trunc({W}*(1+0.08*t/{dur:.3f})/2)*2':h='trunc({H}*(1+0.08*t/{dur:.3f})/2)*2'"
                      f":eval=frame,crop={W}:{H}")
        else:
            extra_inputs += ["-t", f"{dur:.3f}", "-i", str(clip.resolve())]
        parts.append(f"[{k}:v]setpts=PTS-STARTPTS,{cover},"
                     f"setsar=1,fps=30,format=yuv420p,setpts=PTS+{at:.3f}/TB[br{k}]")
        parts.append(f"{vout}[br{k}]overlay=0:0:eof_action=pass[b{k}]")
        vout = f"[b{k}]"

    # Color grade: over the whole video including B-roll, before the captions (so caption colors stay true)
    if grade:
        parts.append(f"{vout}{grade}[grd]")
        vout = "[grd]"

    # Transitions (camera switches / B-roll in and out): above the B-roll, below the captions
    if transitions and transition_style == "glitch":
        g = gate(transitions, GLITCH_SECONDS)
        parts.append(f"{vout}rgbashift=rh=-14:bh=14:enable='{g}',noise=alls=30:allf=t:enable='{g}'[tr]")
        vout = "[tr]"
    elif transitions and transition_style == "flash":
        for n, at in enumerate(transitions):
            start = max(at - 0.05, 0)
            parts.append(f"color=c=white:s={W}x{H}:r=30:d={FLASH_SECONDS},format=rgba,"
                         f"colorchannelmixer=aa=0.75,fade=t=out:d={FLASH_SECONDS}:alpha=1,"
                         f"setpts=PTS+{start:.3f}/TB[fl{n}]")
            parts.append(f"{vout}[fl{n}]overlay=0:0:eof_action=pass[f{n}]")
            vout = f"[f{n}]"

    # Text behind person: draw the hook separately, then paste the person (cut out by the mask) ON TOP, only during the hook.
    # The rest of the captions come after this (otherwise the bottom captions would hide behind the person too).
    # Latency: the person layer is only built for the first behind_until seconds (trimmed). It used to run over
    # the whole video and took half the render time of a 24 s clip (9 of 19 s).
    if use_behind:
        until = f"{behind_until:.3f}"
        parts.append(f"{vout}split=2[ba][bb];[ba]{subtitles_filter(behind_ass)}[bt];"
                     f"[bb]trim=end={until},setpts=PTS-STARTPTS[bbt];[pm2]trim=end={until},setpts=PTS-STARTPTS[pmt];"
                     f"[bbt][pmt]alphamerge[bp];[bt][bp]overlay=eof_action=pass,format=yuv420p[bv]")
        vout = "[bv]"

    if ass_path:
        parts.append(f"{vout}{subtitles_filter(ass_path)}[subs]")
        vout = "[subs]"

    # Overlays (emoji): each is its own input (PNG frames), shifted to the right time and laid on top
    for n, (frames_dir, at, y_pos) in enumerate(overlays, start=1):
        k = len(broll) + n                       # input index (after the B-roll)
        extra_inputs += ["-framerate", "30", "-i", str((frames_dir / "%03d.png").resolve())]
        parts.append(f"[{k}:v]setpts=PTS-STARTPTS+{at:.3f}/TB[ov{k}]")
        parts.append(f"{vout}[ov{k}]overlay=x=(W-w)/2:y={y_pos}:eof_action=pass[o{k}]")
        vout = f"[o{k}]"

    # Progress bar: a faint black strip at the bottom with a colored bar filling left to right
    total_len = content
    if progress_color:
        bar_h, bar_y = 12, H - 12
        parts.append(f"color=c=0x{progress_color}:s={W}x{bar_h}:r=30:d={total_len:.3f}[pbar]")
        parts.append(f"{vout}drawbox=x=0:y={bar_y}:w={W}:h={bar_h}:color=black@0.45:t=fill:"
                     f"enable='lt(t,{content:.3f})'[pbg]")      # no progress bar on the end screen
        parts.append(f"[pbg][pbar]overlay=x='-w+w*t/{total_len:.3f}':y={bar_y}:eval=frame:eof_action=pass[prog]")
        vout = "[prog]"

    # ---------------- Audio: voice + sound effects + music ----------------
    aout = "[eca]" if end_card > 0 else speech
    if sfx or music:
        total = content + end_card
        same = "aformat=sample_rates=44100:channel_layouts=stereo"   # every sound in the same format
        idx = 1 + len(broll) + len(overlays)    # first the video, then B-roll, then emoji inputs
        parts.append(f"{aout}{same},asplit=2[speech][sidechain]")
        mix = ["[speech]"]

        for (wav, at, vol) in sfx:                                    # every effect at the right time
            extra_inputs += ["-i", str(wav.resolve())]
            ms = int(max(at, 0) * 1000)
            parts.append(f"[{idx}:a]{same},adelay={ms}:all=1,volume={vol:.2f}[sx{idx}]")
            mix.append(f"[sx{idx}]")
            idx += 1

        if music:
            extra_inputs += ["-stream_loop", "-1", "-i", str(music.resolve())]   # loop short music
            fade_out = max(total - 1.5, 0)
            parts.append(f"[{idx}:a]{same},atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume={music_volume:.2f},"
                         f"afade=t=in:d=1,afade=t=out:st={fade_out:.3f}:d=1.5[music]")
            # Ducking: push the music down whenever the 'sidechain' (the voice) is active
            parts.append(f"[music][sidechain]sidechaincompress={DUCKING}[ducked]")
            mix.append("[ducked]")
        else:
            parts.append("[sidechain]anullsink")                     # unused: discard it

        # mix everything; length = the voice's length; limiter = no clipping
        parts.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95[mixed]")
        aout = "[mixed]"

    if use_portrait or use_behind:
        extra_inputs += ["-i", str(person_mask.resolve())]      # the very last input (mask_idx)

    # Write outside OneDrive (TEMP) first: OneDrive grabs a new file immediately and FFmpeg's last step
    # (+faststart: reopening the file to move the index to the front) fails. Move it once finished.
    tmp_out = Path(tempfile.gettempdir()) / f"aics_{uuid.uuid4().hex[:10]}.mp4"
    cmd = [
        "-y",
        "-ss", f"{clip_start:.3f}", "-t", f"{clip_end - clip_start + 0.5:.3f}",
        "-i", str(video.resolve()),
        *extra_inputs,
        "-filter_complex", ";".join(parts),
        "-map", vout, "-map", aout,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(tmp_out),
    ]
    if os.getenv("STUDIO_DEBUG_CMD"):          # latency check: dump the full FFmpeg command to a file (run it yourself to time it)
        import json
        out_path.with_suffix(".cmd.json").write_text(json.dumps(cmd, ensure_ascii=False), encoding="utf-8")
    try:
        run_ffmpeg(cmd, cwd=ass_path.parent if ass_path else None)
        move_into_place(tmp_out, out_path.resolve())
    finally:
        tmp_out.unlink(missing_ok=True)
    return out_path
