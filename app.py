"""AI Creative Studio: the website (Streamlit). Run with:  streamlit run server.py"""
import hashlib
import hmac
import html
import json
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="AI Creative Studio", page_icon=":material/movie:", layout="wide")

REQUIRED_KEYS = ("GROQ_API_KEY", "GEMINI_API_KEY")


def load_secrets() -> tuple[list[str], str | None]:
    """Copy Streamlit "Secrets" (cloud hosting) into the environment so studio/config.py reads them like .env.
    Runs on every page load, so Secrets saved after the app started are picked up without a reboot.
    Accepts keys at the top level or under a [section], in any letter case.
    Returns (secret names found, error text if the Secrets could not be parsed)."""
    try:
        data = st.secrets.to_dict()
    except Exception as e:                       # no secrets file (local run) or invalid TOML
        return [], f"{type(e).__name__}: {e}"
    found: dict[str, str] = {}
    empty: list[str] = []

    def walk(d: dict) -> None:
        for k, v in d.items():
            if isinstance(v, dict):
                walk(v)
            elif v is not None and str(v).strip():
                found[str(k).strip().upper()] = str(v).strip()
            else:
                empty.append(str(k).strip().upper())

    walk(data)
    for k, v in found.items():
        os.environ[k] = v
    return sorted(found) + [f"{k} (empty)" for k in sorted(set(empty) - set(found))], None


SECRET_NAMES, SECRETS_ERROR = load_secrets()

# studio/config.py reads the keys once, at import. If the Secrets were saved or changed after the app process
# started, those cached values are stale: re-import the studio modules so they see the current keys (no reboot).
_cfg = sys.modules.get("studio.config")
_groq_env = [k for k in (os.getenv("GROQ_API_KEY"), os.getenv("GROQ_API_KEY_2"), os.getenv("GROQ_API_KEY_3")) if k]
if _cfg and (_cfg.GEMINI_API_KEY != os.getenv("GEMINI_API_KEY") or _cfg.GROQ_API_KEYS != _groq_env):
    for _name in [m for m in sys.modules if m == "studio" or m.startswith("studio.")]:
        del sys.modules[_name]

from studio.config import INPUT_DIR, missing_keys  # noqa: E402
from studio.broll import ready as broll_ready  # noqa: E402
from dataclasses import replace  # noqa: E402

from studio.pipeline import make_shorts  # noqa: E402
from studio import cancel  # noqa: E402
from studio import bigupload  # noqa: E402
from studio.presets import PRESETS, DEFAULT_PRESET, settings_for  # noqa: E402
from studio.styles import STYLES, HOOK_ANIMS  # noqa: E402
from studio.sounds import music_tracks  # noqa: E402
from studio.grades import GRADES  # noqa: E402
from studio.fonts import FONTS  # noqa: E402
from studio.preview import style_preview as render_preview  # noqa: E402
from studio.styles import HOOK_LOOKS  # noqa: E402
import ui  # noqa: E402


@st.cache_data(show_spinner=False)
def style_preview(style_key: str, font_key: str, look_key: str) -> bytes:
    """Preview image of style + font + hook look, rendered by the real video engine (built once, cached)."""
    return render_preview(style_key, font_key or None, look_key or None)

LANGUAGES = {"Auto-detect": None, "Urdu": "ur", "English": "en", "Hindi": "hi"}
MAX_MB = 4096          # matches maxUploadSize in .streamlit/config.toml (fits an hour-long video)
VIDEO_TYPES = ["mp4", "mov", "m4v", "webm", "mkv", "avi", "3gp"]   # phone (iPhone .mov / HEVC, Android .mp4 / .3gp)


# ---------------- Design: violet glass (ui.py) ----------------
st.session_state.setdefault("theme", "dark")
st.markdown(ui.css(st.session_state["theme"]), unsafe_allow_html=True)


# ---------------- Password (so strangers can't burn through your free API quota) ----------------
def check_password() -> bool:
    password = os.getenv("APP_PASSWORD")
    if not password or st.session_state.get("authed"):
        return True
    st.title("AI Creative Studio")
    entered = st.text_input("Password", type="password")
    if entered and hmac.compare_digest(entered.encode(), password.encode()):
        st.session_state["authed"] = True
        st.rerun()
    elif entered:
        st.error("Wrong password")
    return False


if not check_password():
    st.stop()


# ---------------- Who is viewing ----------------
# Streamlit reports an empty IP for a localhost visitor. Only the person on this machine can browse input/:
# a phone / another computer / an internet visitor can only upload their own video (never see anyone else's).
IS_LOCAL = st.context.ip_address in (None, "", "127.0.0.1", "::1")


def lan_url() -> str | None:
    """Address for opening the app from a phone on the same Wi-Fi, e.g. http://192.168.1.5:8501 (nothing is sent out)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))       # UDP connect sends no packets; it only reveals our own IP
            ip = sock.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else f"http://{ip}:{st.get_option('server.port')}"


@st.cache_data(show_spinner=False)
def qr_svg(url: str) -> str:
    import segno
    return segno.make(url, error="m").svg_inline(scale=5, dark="#0f1218", light="#ffffff", border=2)


# ---------------- Header ----------------
def toggle_theme():
    st.session_state["theme"] = "light" if st.session_state["theme"] == "dark" else "dark"


with st.container(key="hero"):
    title_col, theme_col = st.columns([12, 1], vertical_alignment="center")
    title_col.markdown(ui.header_html("Drop in a long video. AI finds the best moments and turns them into viral Shorts "
                                      "with hook scores, captions, face tracking and an SEO pack."),
                       unsafe_allow_html=True)
    dark = st.session_state["theme"] == "dark"
    theme_col.button("", icon=":material/light_mode:" if dark else ":material/dark_mode:", key="theme_toggle",
                     help="Switch to light theme" if dark else "Switch to dark theme", on_click=toggle_theme)

if missing_keys():
    lines = [f"**API keys missing:** {', '.join(missing_keys())}.",
             "Locally: add them to the `.env` file. On Streamlit Cloud: app menu **⋮ → Settings → Secrets**, "
             "one per line, values in double quotes:",
             "```toml\nGROQ_API_KEY = \"gsk_...\"\nGEMINI_API_KEY = \"...\"\n```"]
    if SECRET_NAMES:                     # names only, never values
        lines.append(f"Secrets found: `{', '.join(SECRET_NAMES)}`. Check the spelling of the missing names.")
    elif SECRETS_ERROR and "no secrets found" not in SECRETS_ERROR.lower():   # a real formatting error
        lines.append(f"The Secrets could not be read (formatting error): `{SECRETS_ERROR[:200]}`")
    st.error("\n\n".join(lines))
    st.stop()


# ---------------- Sidebar: preset + 5 sections ----------------
# Only the essentials up top; everything else in collapsed sections. Every widget's default comes from the chosen preset;
# each widget 'key' includes the preset name, so switching presets resets all values to the new preset's.
with st.sidebar:
    st.markdown(ui.brand_html(), unsafe_allow_html=True)
    st.header("Settings")
    preset = st.selectbox("Preset", list(PRESETS), index=list(PRESETS).index(DEFAULT_PRESET),
                          format_func=lambda k: PRESETS[k]["label"])
    st.caption(PRESETS[preset]["about"])
    base = settings_for(preset)                         # Settings() + preset
    key = lambda name: f"{preset}_{name}"               # noqa: E731

    lang_label = st.selectbox("Video language", list(LANGUAGES))
    n_clips = st.slider("How many Shorts?", 1, 8, 3)
    min_len, max_len = st.slider("Length of each Short (seconds)", 10, 90, (20, 60))

    with st.expander("Captions", icon=":material/subtitles:"):
        style_key = st.selectbox("Caption style", list(STYLES), index=list(STYLES).index(base.caption_style),
                                 format_func=lambda k: STYLES[k].label, key=key("style"))
        font_key = st.selectbox("Font (Google Fonts)", ["auto", *FONTS],
                                index=(["auto", *FONTS].index(base.font) if base.font else 0),
                                format_func=lambda k: "Style default" if k == "auto" else FONTS[k].label,
                                key=key("font"), help="Downloaded the first time it is used (a few seconds).")
        font_key = "" if font_key == "auto" else font_key
        looks = ["auto", *HOOK_LOOKS]
        look_key = st.selectbox("Hook look", looks, index=looks.index(base.hook_look or "auto"),
                                format_func=lambda k: "Style default" if k == "auto" else HOOK_LOOKS[k],
                                key=key("look"), help="'Text behind person': the big hook text sits behind the speaker "
                                                      "(best with one person facing the camera)")
        look_key = "" if look_key == "auto" else look_key
        try:
            st.image(style_preview(style_key, font_key, look_key if look_key != "behind" else ""),
                     caption="Preview (as in the final video)" + (" · in the video, text-behind appears behind the person"
                                                              if look_key == "behind" else ""), width="stretch")
        except Exception as e:      # the rest of the website keeps working even if the preview fails
            st.caption(f"Preview unavailable: {str(e)[:120]}")
        anims = ["auto", *HOOK_ANIMS]
        hook_names = {"auto": "Style default", "slide": "Slide + bounce", "pop": "Pop",
                      "typewriter": "Typewriter", "fade": "Fade"}
        hook_choice = st.selectbox("Hook animation", anims, index=anims.index(base.hook_anim or "auto"),
                                   format_func=lambda k: hook_names[k], key=key("anim"))
        roman = st.toggle("Roman Urdu captions (English letters)", value=True, key=key("roman"),
                          help="Urdu/Hindi speech is written in Latin letters, like 'aap kaise hain'")
        hook_start = st.toggle(":material/my_location: Start on the spoken hook", value=base.hook_start, key=key("hookstart"),
                               help="The clip starts on the sentence where the speaker says the hook (everything before it is cut). "
                                    "The AI-written hook goes in the title.")
        context_on = st.toggle(":material/extension: Each Short makes sense alone (context)", value=base.context, key=key("context"),
                               help="Adds the needed earlier setup after the hook, ends clips on a full sentence, "
                                    "and adds a bridge line before each part of the combined video.")
        teaser_on = st.toggle(":material/movie: Teaser: strongest line first", value=base.teaser, key=key("teaser"),
                              disabled=hook_start,
                              help="Not available with the spoken-hook start (both go at the beginning). Turn that off to use it.")
        emphasis = st.toggle(":material/bolt: AI key-word highlights", value=base.emphasis, key=key("emph"))
        counters_on = st.toggle("Number counter ($0 → $100k)", value=base.counters, key=key("counter"))
        progress = st.toggle("Progress bar (bottom)", value=base.progress_bar, key=key("progress"))

    with st.expander("Video effects", icon=":material/movie_edit:"):
        grade = st.selectbox("Color grade", list(GRADES), index=list(GRADES).index(base.grade),
                             format_func=lambda k: GRADES[k][0], key=key("grade"))
        trans_names = {"flash": "Flash (white)", "glitch": "Glitch", "none": "None"}
        transition = st.selectbox("Transition", list(trans_names), index=list(trans_names).index(base.transition),
                                  format_func=lambda k: trans_names[k], key=key("trans"))
        cut_silence = st.toggle("Cut silences (jump cuts)", value=base.cut_silence, key=key("cut"))
        gap = st.slider("Cut silences longer than (sec)", 0.3, 1.5, float(base.gap), 0.1,
                        disabled=not cut_silence, key=key("gap"))
        track_faces = st.toggle("Face tracking (camera follows the speaker)", value=base.track_faces, key=key("track"))
        layouts = {"auto": "Auto (split during conversation)", "single": "Always one person",
                   "split": "Always split-screen"}
        layout = st.selectbox("Layout (interview)", list(layouts), index=list(layouts).index(base.layout),
                              format_func=lambda k: layouts[k], disabled=not track_faces, key=key("layout"))
        punch_in = st.toggle("Zoom punch-ins (on jump cuts)", value=base.punch_in, key=key("punch"))
        shake_on = st.toggle("Screen shake (big moments)", value=base.shake, key=key("shake"))
        focus_on = st.toggle(":material/center_focus_strong: Focus on the speaker (zoom in if far away)", value=base.focus, key=key("focus"),
                             help="If the speaker looks small, the camera moves closer with the face in the upper part. "
                                  "No zoom when two people share the frame (so no face gets cut).",
                             disabled=not track_faces)
        portrait = st.toggle("Background blur (portrait mode, AI)", value=base.portrait, key=key("blur"),
                             help="Person stays sharp, background is blurred. AI masks every frame (a bit slower)")
        can_broll = broll_ready()
        broll_on = st.toggle("Auto B-roll (your folder / stock)", value=can_broll and base.broll,
                             disabled=not can_broll, key=key("broll"),
                             help=None if can_broll else "Put videos in assets/broll, or add a PIXABAY / PEXELS / "
                                                         "UNSPLASH key (.env or Secrets)")

    with st.expander("Sound", icon=":material/volume_up:"):
        noise_names = {"medium": "Medium (background ~50x quieter)", "strong": "Strong (+ full silence in pauses)",
                       "light": "Light (voice stays natural)", "": "Off"}
        denoise = st.selectbox(":material/noise_control_off: Remove background noise", list(noise_names),
                               index=list(noise_names).index(base.denoise), format_func=lambda k: noise_names[k],
                               key=key("noise"), help="Fans, AC, traffic, people talking in the background "
                                                      "(RNNoise lq + sh). 'Strong': background muted in pauses.")
        sfx_on = st.toggle("Sound effects (whoosh, pop, ding)", value=base.sfx, key=key("sfx"))
        tracks = ["No music"] + music_tracks()
        music_choice = st.selectbox("Background music", tracks,
                                    index=tracks.index(base.music) if base.music in tracks else 0, key=key("music"))
        music_volume = st.slider("Music volume", 0.05, 0.5, float(base.music_volume), 0.01,
                                 disabled=music_choice == tracks[0], key=key("vol"),
                                 help="Pick 'No music' above to turn it off.")

    with st.expander("Brand", icon=":material/sell:"):
        st.caption("Name lower third: leave empty to hide it")
        guest_name = st.text_input("Guest name", max_chars=40, key=key("gname"))
        guest_title = st.text_input("Title", max_chars=50, placeholder="Founder, Quick Fox", key=key("gtitle"))
        end_card = st.toggle("End screen (Follow + logo)", value=base.end_card, key=key("end"))
        cta = st.text_input("End screen text", value=base.cta, max_chars=30, disabled=not end_card, key=key("cta"))
        handle = st.text_input("Your @handle", max_chars=30, placeholder="@yourname", disabled=not end_card,
                               key=key("handle"))
        logo_file = st.file_uploader("Logo (PNG/JPG, optional)", type=["png", "jpg", "jpeg"], disabled=not end_card,
                                     key=key("logo"))

    with st.expander("Output", icon=":material/inventory_2:"):
        thumbs_on = st.toggle("Make thumbnails (9:16 cover + YouTube 16:9)", value=base.thumbnails,
                              key=key("thumbs"))
        combine_on = st.toggle(":material/video_library: Combine all clips into one video", value=base.combine, key=key("combine"),
                               help="In the original order of the conversation, with its own title / description.")
        smooth_on = st.toggle("Smooth crossfade when combining (+1-2 min)", value=base.combine_smooth,
                              disabled=not combine_on, key=key("smooth"))
        landscape_on = st.toggle(":material/desktop_windows: Also make a 16:9 landscape version (YouTube)", value=base.landscape, key=key("wide"),
                                 help="A 16:9 version of every Short and the combined video. Roughly doubles render time.")
    st.caption("Tip: 5–15 minute videos give the best results.")
    url = lan_url() if IS_LOCAL else None
    if url:
        with st.expander("Open on your phone", icon=":material/smartphone:"):
            st.caption("Connect your phone or other laptop to the same Wi-Fi, then scan this code "
                       "or open the link. You can upload videos straight from that device.")
            st.markdown(f'<div class="cs-qr">{qr_svg(url)}</div>', unsafe_allow_html=True)
            st.code(url, language=None)

# ---------------- Running in the background (thread), with Stop ----------------
# make_shorts runs in its own thread; the page shows new messages every half second. Benefits:
# Stop works instantly (FFmpeg is killed), and changing a sidebar setting doesn't interrupt the running job.
def start_run(video: Path, settings, name: str) -> None:
    cancel.reset()
    run = {"logs": [], "done": False, "out": None, "error": None, "stopped": False, "stopping": False,
           "t0": time.time(), "t1": None, "name": name}

    def log(msg: str) -> None:
        cancel.check()                       # stop right here if Stop was pressed
        run["logs"].append(msg.strip())

    def work() -> None:
        try:
            run["out"] = make_shorts(video, settings, log=log)
        except cancel.Cancelled:
            run["stopped"] = True
        except Exception as e:
            run["stopped"] = cancel.stopped()    # an FFmpeg error caused by Stop is not a real error
            run["error"] = None if run["stopped"] else str(e)[:600]
        finally:
            run["t1"] = time.time()
            run["done"] = True

    threading.Thread(target=work, daemon=True, name="make_shorts").start()
    st.session_state["run"] = run


def stop_run() -> None:
    cancel.stop()
    run = st.session_state.get("run")
    if run:
        run["stopping"] = True


def show_run() -> None:
    run = st.session_state.get("run")
    if not run:
        return
    if not run["done"]:
        label = "Stopping..." if run["stopping"] else "Working... (this can take a few minutes)"
        status = st.status(label, expanded=True)
        st.button("Stop", icon=":material/stop_circle:", key="stop_run", on_click=stop_run, width="stretch",
                  disabled=run["stopping"], help="Stop this run (renders are cancelled right away)")
        clock = st.empty()
        shown = 0
        while not run["done"]:
            while shown < len(run["logs"]):
                status.write(run["logs"][shown])
                shown += 1
            clock.caption(f"Elapsed: {time.time() - run['t0']:.0f}s")   # har chakkar ek st call: Stop foran sunai de
            time.sleep(0.5)
        st.rerun()
    secs = (run["t1"] or time.time()) - run["t0"]
    if run["out"]:
        out_dir, report = run["out"]
        st.session_state["result"] = {"out_dir": str(out_dir), "report": report, "name": run["name"]}
        label, state = f"{len(report)} Shorts ready ({secs:.0f}s)", "complete"
    elif run["stopped"]:
        label, state = f"Stopped after {secs:.0f}s", "error"
    else:
        label, state = "Something went wrong", "error"
    with st.status(label, state=state, expanded=bool(run["error"])):
        for line in run["logs"]:
            st.write(line)
    if run["error"]:
        st.error(run["error"])


# ---------------- Large video upload (with server.py: chunked, straight to disk) ----------------
BIG_UPLOAD = os.getenv("BIG_UPLOAD") == "1"


@st.fragment(run_every=2)
def wait_for_upload(token: str) -> None:
    """Every 2 seconds: has the browser finished the upload? Then rerun the whole page so the video is selected."""
    if bigupload.result(token):
        st.rerun(scope="app")


def new_upload() -> None:
    old = st.session_state.pop("up_token", None)
    if old:
        bigupload.forget(old)


def big_upload() -> tuple[Path | None, str | None]:
    token = st.session_state.setdefault("up_token", secrets.token_urlsafe(24))
    done = bigupload.result(token)
    if done and (INPUT_DIR / done["file"]).exists():
        st.markdown(f"**Video ready:** {html.escape(done['name'])} · {done['size'] / 1_048_576:,.0f} MB")
        st.button("Use a different video", icon=":material/swap_horiz:", on_click=new_upload, key="up_new")
        return INPUT_DIR / done["file"], done["name"]
    st.markdown("Upload a video")
    # our own HTML (no user input inside), so running JS in the iframe is safe
    st.iframe(ui.big_upload_html(token, st.session_state["theme"], VIDEO_TYPES, bigupload.MAX_BYTES),
              height=128)
    wait_for_upload(token)
    return None, None


# ---------------- Upload ----------------
with st.container(key="source"):
    if IS_LOCAL:
        source = st.radio("Video source", ["Upload", "Pick from the input/ folder (faster for big videos)"],
                          horizontal=True)
    else:
        source = "Upload"
    video_path, video_name = None, None
    if source == "Upload" and BIG_UPLOAD:
        video_path, video_name = big_upload()
    elif source == "Upload":
        uploaded = st.file_uploader("Upload a video", type=VIDEO_TYPES,
                                    help=f"Up to {MAX_MB // 1024} GB. Hour-long videos work too.")
        if uploaded:
            # 'fingerprint' file name: re-uploading the same video reuses its transcript,
            # and two different videos never collide. Big file: hashed in chunks (never fully copied in RAM)
            sha = hashlib.sha1()
            uploaded.seek(0)
            for block in iter(lambda: uploaded.read(8 * 1_048_576), b""):
                sha.update(block)
            video_path = INPUT_DIR / f"{sha.hexdigest()[:16]}{Path(uploaded.name).suffix.lower()}"
            if not video_path.exists():
                uploaded.seek(0)
                with open(video_path, "wb") as f:
                    for block in iter(lambda: uploaded.read(8 * 1_048_576), b""):
                        f.write(block)
            video_name = uploaded.name
            st.caption(f":material/folder: {uploaded.name} · {uploaded.size / 1_048_576:.1f} MB")
    else:
        files = sorted((p for p in INPUT_DIR.iterdir() if p.suffix.lower().lstrip(".") in VIDEO_TYPES),
                       key=lambda p: p.stat().st_mtime, reverse=True) if INPUT_DIR.exists() else []
        if not files:
            st.info(f"No videos in `{INPUT_DIR}`. Copy a video there, then refresh the page.")
        else:
            picked = st.selectbox("Choose a video", files,
                                  format_func=lambda p: f"{p.name}  ({p.stat().st_size / 1_048_576:.0f} MB)")
            video_path, video_name = picked, picked.name

    run = st.session_state.get("run")
    busy = bool(run and not run["done"])
    if video_path:
        if st.button("Create Shorts", icon=":material/auto_awesome:", type="primary", width="stretch",
                     disabled=busy):
            logo_path = None
            if end_card and logo_file:
                raw = logo_file.getvalue()
                logo_path = INPUT_DIR / f"logo_{hashlib.sha1(raw).hexdigest()[:12]}{Path(logo_file.name).suffix.lower()}"
                logo_path.write_bytes(raw)
            # the preset's settings + whatever was changed in the sidebar (every sidebar value starts from the preset)
            settings = replace(
                base,
                lang=LANGUAGES[lang_label], clips=n_clips, min_len=min_len, max_len=max_len,
                gap=gap, cut_silence=cut_silence, track_faces=track_faces, roman=roman, caption_style=style_key,
                emphasis=emphasis, sfx=sfx_on,
                music=None if music_choice == tracks[0] else music_choice, music_volume=music_volume,
                punch_in=punch_in, hook_anim=None if hook_choice == "auto" else hook_choice, layout=layout,
                progress_bar=progress, name=guest_name, name_title=guest_title, broll=broll_on,
                counters=counters_on, shake=shake_on, transition=transition,
                grade=grade, end_card=end_card, cta=cta, handle=handle, logo=str(logo_path) if logo_path else None,
                teaser=teaser_on, hook_start=hook_start, font=font_key, denoise=denoise, hook_look=look_key,
                portrait=portrait, thumbnails=thumbs_on, combine=combine_on, combine_smooth=smooth_on,
                focus=focus_on, landscape=landscape_on, context=context_on,
            )
            start_run(video_path, settings, video_name)
            st.rerun()

    show_run()

# ---------------- Results ----------------
result = st.session_state.get("result")
if not result:
    with st.container(key="empty"):
        st.markdown(ui.empty_html(), unsafe_allow_html=True)
else:
    out_dir, report = Path(result["out_dir"]), result["report"]

    st.divider()
    st.subheader(f"Your Shorts · {result['name']}")

    saved = sum(r.get("original_seconds", 0) - r.get("final_seconds", 0) for r in report)
    m1, m2, m3 = st.columns(3)
    m1.metric("Shorts", len(report))
    m2.metric("Average hook score", f"{sum(r['hook_score'] for r in report) / len(report):.0f}/100")
    m3.metric("Silence cut", f"{saved:.0f}s")

    # combined video (all clips together, in original order)
    combined_info = out_dir / "combined.json"
    if combined_info.exists() and (out_dir / "combined.mp4").exists():
        info = json.loads(combined_info.read_text(encoding="utf-8"))
        with st.container(key="combined"):
            st.markdown(f"#### :material/video_library: All clips in one video · {html.escape(info['title'])}")
            left, right = st.columns([1, 2])
            with left:
                st.video(str(out_dir / "combined.mp4"))
            with right:
                st.caption("Order (as in the conversation): " + " → ".join(info["order"]))
                st.write(info["description"])
                st.markdown("".join(f'<span class="tag">{html.escape(t)}</span>' for t in info["hashtags"]),
                            unsafe_allow_html=True)
                st.code(f"{info['title']}\n\n{info['description']}\n\n{' '.join(info['hashtags'])}", language=None)
                st.download_button("Download combined video (9:16)", icon=":material/download:", data=(out_dir / "combined.mp4").read_bytes(),
                                   file_name=f"{Path(result['name']).stem}_combined.mp4", mime="video/mp4",
                                   width="stretch", key="dl_combined")
                wide = out_dir / (info.get("landscape") or "")
                if info.get("landscape") and wide.exists():
                    with st.expander("16:9 landscape (YouTube) version", icon=":material/desktop_windows:"):
                        st.video(str(wide))
                        st.download_button("Download 16:9", icon=":material/download:", data=wide.read_bytes(),
                                           file_name=f"{Path(result['name']).stem}_combined_16x9.mp4",
                                           mime="video/mp4", width="stretch", key="dl_combined_wide")

    cols = st.columns(3)
    for i, r in enumerate(sorted(report, key=lambda r: r["hook_score"], reverse=True)):
        with cols[i % 3].container(key=f"card_{i}"):
            mp4 = out_dir / r["file"]
            st.video(str(mp4))
            st.progress(r["hook_score"] / 100, text=f"Hook score: **{r['hook_score']}/100**")
            st.markdown(f"**{r['title']}**")
            st.markdown(f'<p class="hook">{ui.icon("phishing")} {html.escape(r["hook_text"])}</p>', unsafe_allow_html=True)
            st.markdown("".join(f'<span class="tag">{html.escape(t)}</span>' for t in r["hashtags"]),
                        unsafe_allow_html=True)
            with st.expander("Details: why it was picked, description"):
                st.write(f"**Why:** {r['reason']}")
                st.write(f"**Description:** {r['description']}")
                st.caption(f"{r.get('original_seconds', 0):.0f}s → {r.get('final_seconds', 0):.0f}s")
                for b in r.get("broll") or []:      # Pexels/Pixabay/Unsplash terms: show credit and link
                    site = b.get("source", "Pexels")
                    if not b.get("url"):            # your own folder: no credit needed
                        st.caption(f":material/movie: B-roll '{b['query']}': {site}")
                    else:
                        kind = "photo" if b.get("kind") == "image" else "video"
                        st.caption(f":material/movie: B-roll '{b['query']}': [{kind} by {b['user'] or site} on {site}]({b['url']})")
                st.code(f"{r['title']}\n\n{r['description']}\n\n{' '.join(r['hashtags'])}", language=None)
            wide = out_dir / (r.get("landscape") or "")
            if r.get("landscape") and wide.exists():
                with st.expander("16:9 landscape version", icon=":material/desktop_windows:"):
                    st.video(str(wide))
                    st.download_button(wide.name, icon=":material/download:", data=wide.read_bytes(), mime="video/mp4",
                                       file_name=f"{Path(result['name']).stem}_{wide.name}", key=f"wide_{i}_{wide.name}")
            thumbs = [out_dir / t for t in r.get("thumbnails") or [] if (out_dir / t).exists()]
            if thumbs:
                with st.expander("Thumbnails (cover + YouTube)", icon=":material/image:"):
                    for t in thumbs:
                        st.image(str(t))
                        st.download_button(t.name, icon=":material/download:", data=t.read_bytes(), file_name=t.name,
                                           mime="image/jpeg", key=f"th_{i}_{t.name}")
            st.download_button("Download", icon=":material/download:", data=mp4.read_bytes(), file_name=f"{Path(result['name']).stem}_{r['file']}",
                               mime="video/mp4", width="stretch", key=f"dl_{i}_{r['file']}")

    st.download_button("Full SEO pack (JSON)", icon=":material/data_object:", data=json.dumps(report, ensure_ascii=False, indent=2),
                       file_name="seo_pack.json", mime="application/json")
