# PROJECT.md: AI Creative Studio

Handoff document. Read this first, then open the files it points to.

## 1. What the project is

AI Creative Studio turns one long video (podcast, interview, talking-head, up to 2 hours, up to 20 GB) into a batch of
ready-to-post short videos, automatically.

Outputs per upload:
- **9:16 Shorts** (1080x1920) for YouTube Shorts, Reels, TikTok
- **16:9 landscape cuts** for YouTube (optional)
- **Combined highlight reel** (all clips in original timeline order, hook shown once, transitions at joins)
- **Thumbnails**: 9:16 cover and 16:9 YouTube thumbnail per Short (sharpest face frame + hook text)
- **SEO pack** (`seo_pack.json`): title, description, hashtags, and the AI's reasoning per clip

Two front ends share one pipeline:
- **Web app**: Streamlit (`server.py` → `app.py`)
- **CLI**: `main.py` (`captions`, `shorts`, `models`, `ping`); every web option is also a CLI flag

Language: Python 3.12+ (Dockerfile uses 3.12, local dev has used 3.13). Video work is done by **FFmpeg** (libass for
captions, RNNoise `arnndn` for noise, loudnorm). Computer vision via **OpenCV** (headless).

Repo: `alizaafzal582004/creative-studio-agent` (remote). Default branch `main`. Local branch at time of writing:
`github-main`. About 10 commits so far.

## 2. Architecture

```
            +-----------------+          +-----------------+
 browser -> | server.py       |          | main.py (CLI)   |
            |  st.App mounts  |          |  argparse       |
            |  bigupload.routes()        +--------+--------+
            +--------+--------+                   |
                     |                            |
            +--------v--------+                   |
            | app.py          |  (UI: sidebar,    |
            | (Streamlit UI,  |   job runner,     |
            |  job control)   |   password gate)  |
            +--------+--------+                   |
                     | ui.py (CSS/HTML only)      |
                     |                            |
                     +------------+---------------+
                                  v
                    studio/pipeline.py  make_shorts(video, Settings)
                    (the one orchestrator, used by app.py AND main.py)
                                  |
     +----------+----------+------+-------+-----------+-----------+
     v          v          v              v           v           v
 transcribe  clipper    framing/segment  edit/      render      thumbnail/
 (Groq       (LLM       (face track,     captions/  (FFmpeg,     combine/
  Whisper)   picks,     person masks)    emoji/     parallel)   teaser/...
             hooks,                      sounds
             truth)
                                  |
                     studio/ffmpeg.py (find + run FFmpeg)
                     studio/config.py (keys, paths, CPU limits)
```

### Pipeline flow (`studio/pipeline.py: make_shorts`)

Progress is printed as `1/3`, `2/3`, `3/3` (via `log=`), with steps a) to j) inside the render stage:

1. **Transcribe** (`get_transcript` → `transcribe.transcribe_video`): Groq Whisper, word-level timestamps, chunked and
   parallel for long videos. Cached.
2. **Language and Roman Urdu**: `detect_urdu`; `roman.romanize` only for Urdu/Hindi speech. Cached.
3. **AI clip selection** (`clipper.find_clips`): LLM returns clips with hook score, reasoning, SEO. Truth check
   (`check_clip`, `numbers_ok`) rejects invented numbers/claims. Reuse of previous picks is possible (`reuse`).
4. **Hook sharpening + openings**: `clipper.sharpen_hooks` (3 hook drafts per clip, formulas), `choose_openings`
   (Short starts on the spoken hook sentence), `snap_to_sentence`.
5. **Context**: `context.context_needs` + `add_context` (setup sentences before, finish the thought after).
   `snap_ends`, `following`, `compose_ranges`.
6. **Thumbnail texts**: `clipper.fill_thumb_texts`.
7. **Background (parallel, threads)**: teaser (`teaser.find_teaser`), key words + emoji (`emphasis.find_emphasis`),
   B-roll choice (`broll.choose_moments`, `find_footage`), face scan (`framing.find_people`), noise filter build
   (`denoise.denoise_filter`, `ensure_model`).
8. **Per clip, in order**:
   - a) Silence removal: `edit.keep_ranges`, `split_at_sentences`, `remap_words`
   - b) Shot framing: `framing.plan_shots` / `split_pair`; split-screen for two speakers
   - c) Key words and emoji
   - d) Captions: `captions.words_to_ass` (+ lower third, hook look, end card)
   - e) Emoji pop: `emoji.pop_frames`
   - f) Sound effects: `sounds.sfx` (ding on hook, pop on emoji, whoosh on camera switch), music with ducking
   - g) Zoom punch-ins (`edit.plan_zooms`), speaker focus (`focus_plan`), counters (`kinetic`), shake
   - h) Render (`render.render_shots`) in a render pool, so the loop keeps preparing the next clip
   - i) Thumbnails (`thumbnail.make_thumbnails`), in background; a failure doesn't fail the Short
9. **Combined reel** (`combine.combine_clips` / `combine_fast`, plus `render_combined`), and combined title/description.
10. Write `seo_pack.json`; return `(out_dir, report)`.

Cancellation: `cancel.py` sets a flag and kills all FFmpeg processes. `Cancelled` is a `BaseException` so
`except Exception` handlers in the pipeline can't swallow it.

## 3. File-by-file

### Entry points and web UI

| File | Role |
|---|---|
| `server.py` | Entry point (`streamlit run server.py`). Creates `st.App("app.py", routes=routes())` and sets `BIG_UPLOAD=1`. Mounts the large-upload HTTP routes next to the Streamlit app. |
| `app.py` (~540 lines) | The website. `st.set_page_config`, `load_secrets()` (copies Streamlit Secrets into env on every load), `check_password` (APP_PASSWORD gate, HMAC), `lan_url` and `qr_svg` (phone access QR), `toggle_theme`, `start_run` / `stop_run` / `show_run` (background job control, live progress), `wait_for_upload`, `new_upload`, `big_upload` (upload UI). Layout and logic only; visuals live in `ui.py`. |
| `ui.py` (~400 lines) | All visuals: `THEMES` dict (dark = main, light), CSS variables, "glass" cards, shimmering "silk" background, silver buttons. Functions: `css`, `icon`, `header_html`, `brand_html`, `empty_html`, `big_upload_html`. |
| `main.py` | CLI. `cmd_captions` (SRT only), `cmd_shorts` (all Settings as flags; a flag only overrides the preset if typed, via `given_options`), `cmd_models` and `cmd_ping` (Gemini checks). Prints progress (`1/2`, `2/2`) and total time. |
| `deploy_hf.py` | Deploys to Hugging Face Spaces (Docker SDK): creates Space, uploads code (not `.env`, `input/`, `output/`, `models/`), stores API keys as Space Secrets. Needs `HF_TOKEN`. |
| `Dockerfile` | `python:3.12-slim` + `ffmpeg`; runs as uid 1000; `streamlit run server.py` on port 7860, XSRF and CORS disabled (Spaces iframe). |
| `.dockerignore` | Keeps the image small and excludes local secrets/outputs. |
| `packages.txt` | System packages for Streamlit Cloud (`ffmpeg`). |
| `requirements.txt` | Pinned deps: `streamlit==1.67.0`, `groq==1.7.0`, `google-genai==3.3.0`, `opencv-python-headless`, `numpy`, `pillow`, `pydantic`, `python-dotenv`, `imageio-ffmpeg`, `segno` (QR). |
| `.env.example` | Template. Keys: `GROQ_API_KEY` (required), `GROQ_API_KEY_2/3` (optional, extra accounts), `GEMINI_API_KEY`, `GEMINI_MODEL`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `UNSPLASH_ACCESS_KEY`, `APP_PASSWORD`, `HF_TOKEN`, `CPU_THREADS`, `FFMPEG_AT_ONCE`, `TEMP_PAUSE`, `TEMP_RESUME`. Never commit real values. |
| `.streamlit/secrets.toml.example` | Example Streamlit Cloud Secrets file. |
| `.streamlit/config.toml` | Streamlit theme/server config. **Currently shown as deleted in git status** (see section 6). |
| `.gitignore` | Ignores `.env`, `.streamlit/secrets.toml`, `venv/`, `__pycache__/`, `input/`, `output/`, `models/`, `*.mp4`, `*.mp3`. |
| `README.md` | User-facing docs: features, roadmap, setup per OS, deployment. |
| `LICENSE` | Project license. |

### `studio/` (core engine)

| File | Role |
|---|---|
| `__init__.py` | Empty package marker. |
| `config.py` | Loads `.env`. Reads all keys (`GROQ_API_KEYS` list from 1-3 accounts, Gemini, Pexels, Pixabay, Unsplash), `GROQ_TEXT_MODEL` (default `openai/gpt-oss-120b`), paths `ROOT`, `INPUT_DIR`, `OUTPUT_DIR`, `FONTS_DIR`, CPU limits (`CPU_THREADS` defaults to half the cores, `FFMPEG_AT_ONCE` 2 or 8). `missing_keys()` (only Groq is required). |
| `pipeline.py` (~950 lines) | **The orchestrator.** `Settings` dataclass (every option; see section 4), `make_shorts`, `get_transcript`, `render_combined`, `add_context`, `compose_ranges`, `focus_plan`, `choose_openings`, `head_height`, `snap_to_sentence`, `snap_ends`. Runs the pipeline in section 2. |
| `presets.py` | `PRESETS`: `talking_head_viral` (default), `podcast_pro`, `clean_minimal`, `custom`. `settings_for(preset, overrides)`: defaults → preset → user overrides. Shows in both CLI and web sidebar. Unknown setting names fail loudly. |
| `styles.py` | `STYLES`: 10 caption styles (`bold_pop` default, `viral_anton`, `box_highlight`, `neon`, `shadow_3d`, `one_word`, `green_karaoke`, `comic`, `clean_bebas`, `minimal`). `CaptionStyle` dataclass (font, size, colors, highlight, pop). `HOOK_LOOKS`, `HOOK_ANIMS`. Colors are RGB hex in, ASS format out (`ass_color`, `inline_color`). |
| `captions.py` (~450 lines) | ASS subtitle generation: `words_to_srt` (CLI SRT), `words_to_ass` (main), word-by-word pop highlight, `kinetic_hook` (slide, pop, typewriter, fade), `behind_hook_ass`, `lower_third`, `end_card_lines`, `word_boxes` for box highlight, `wrap_hook`, `format_time`/`ass_time`, Urdu detection (`has_urdu`). |
| `clipper.py` (~950 lines) | **The AI layer.** Model selection and fallback: `available_models`, `ranked_models`, `pick_model`, `models_to_try`, rate-limit memory (`block`, `is_blocked`, `note_gemini_failure`, `note_groq_failure`). Calls: `ask_gemini`, `ask_groq` (with `GroqBusy`, `groq_wait`, `groq_slots`), `ask_ai`, `ask_with_fallback`. Logic: `Clip`/`ClipPlan` dataclasses, `build_prompt`, `find_clips` (main entry), `check_clip` (truth check), `numbers_ok`, `soften_numbers`, `claimed_numbers`, `remove_overlaps`, `fill_gaps`, `grow_short`, `sharpen_hooks` (`SharpHook(s)`), `fill_thumb_texts` (`ThumbTexts`), `transcript_windows` (chunking for long videos), `ping`. |
| `transcribe.py` (~300 lines) | Groq Whisper. `transcribe_video` (long videos: chunks straight from video, in parallel), `split_audio`, `transcribe_file`, `merge`, `find_holes` / `repair_holes` (re-transcribes gaps), `detect_urdu`, `make_clients` (rotates across Groq keys on rate limit). |
| `context.py` | Makes each Short stand alone: `context_needs` (AI finds the topic start and where the answer ends), `bridge_lines` (minimal setup sentences), `ContextNeeds`, `Bridges`. |
| `edit.py` | Silence removal from word timestamps: `keep_ranges` (keep spoken parts), `split_at_sentences`, `remap_words` (timeline after cuts), `words_inside`, `total`, `plan_zooms` (punch-in positions). |
| `framing.py` (~220 lines) | Face tracking and speaker detection. `Face`, `Track`, `scan_faces` (OpenCV DNN face detector, `ensure_model` downloads it), `mouth_box` + motion for who is talking (`find_people`), `group_tracks`, `choose_center`, `crop_fraction`, `plan_shots` (9:16 crop per sentence), `split_pair` (two-person split screen). |
| `segment.py` | Person segmentation (PP-HumanSeg, ~6 MB, CPU). `ensure_model`, `person_prob`, `mask_video`. Powers background blur (portrait mode) and "text behind person". |
| `render.py` (~340 lines) | FFmpeg filter-graph builders and the parallel renderer: `render_shots` (main), `subtitles_filter`, `shot_crop`, `split_screen_chain`, `gate` (time-gated overlays), `even`. |
| `combine.py` | Joins all Shorts into one reel in timeline order: `combine_clips`, `combine_fast` (concat, no re-encode), optional crossfade (`--smooth-combine`), `combined_meta` (title/description/chapters). |
| `thumbnail.py` (~180 lines) | Thumbnails: `best_frame` / `frame_score` (sharp, big, clear face), `shade`, `text_ass` + `burn_text`. Text is drawn with libass, not Pillow, because Pillow here lacks raqm and breaks Urdu shaping. `make_thumbnails` → 9:16 and 16:9. |
| `teaser.py` | Cold open: `find_teaser` picks the strongest line (1-4 s, played before the Short). `find_opening` for the hook sentence. `build_prompt`, `build_opening_prompt`. |
| `emphasis.py` | AI key-word highlights and emoji: `find_emphasis`, `Mark`/`Marks`, `is_filler` (filters "um", "uh" etc.), `VIDEO_EMOJI`. |
| `emoji.py` | Emoji pop: `pop_frames` (animation from Twemoji PNGs in `assets/emoji`-style folders), `find_png`, `emoji_map`, `normalize`, `EMOJI_DIR` (emoji PNG folder). |
| `kinetic.py` | Number counter: `find_counters` (regex on transcript, no AI call), `parse_number` ("$100k", "50%"), `counter_lines`, `ease_out`. |
| `broll.py` (~300 lines) | Auto B-roll. Source order: your folder `assets/broll/` (filename = subject), then Pexels, Pixabay, Unsplash. `library`, `search_library`, `search_pexels`, `search_pixabay`, `search_unsplash`, `choose_moments` (AI picks where to cut away and what to search), `find_footage`, `download`, `ready`, `hide_keys` (keys hidden from UI). |
| `denoise.py` | Background noise: RNNoise via FFmpeg `arnndn`. Levels `light`, `medium`, `strong` (models `std`/`lq`/...). `ensure_model`, `denoise_filter`, `speech_gate` (optional gate for noisy rooms), `speech_spans`, `gate_floor`. |
| `audio.py` | `extract_audio` (video to mp3/wav for transcription). |
| `sounds.py` | Sound effects and music synthesized in code (no licensing): `make_pop`, `make_whoosh`, `make_ding`, `make_lofi`, `ensure_sounds`, `sfx`, `music_tracks`, `music_path`. Users can drop royalty-free mp3s in `assets/music/`. |
| `grades.py` | Color grades (6 looks): `grade_filter` returns an FFmpeg filter chain. Default from `DEFAULT_GRADE`. |
| `fonts.py` | Google Fonts for captions. `ensure_font` downloads from `google/fonts` on GitHub once into `assets/fonts`. `GoogleFont`, `FONTS`, `font_for`, `font_file`, `text_width`, `_calibrate` / `libass_ratio` (matches libass width measurements; `assets/fonts/_libass_widths.json` caches them). |
| `preview.py` | `style_preview`: renders a 2-second sample video with the real engine (preview = output). Used for the style picker. |
| `brand.py` | `logo_frames`: animated logo reveal for the end card (PNG/JPG in a 360px box). |
| `bigupload.py` (~150 lines) | Resumable large-file upload, streamed to disk in 16 MB chunks (never in RAM). Routes mounted by `server.py`. `_token`, `_fingerprint`, `_part`, `_done`, `result`, `forget`, `_clean_stale`. |
| `cancel.py` | Stop button: `stop()`, `check()`, `pause_point()`, `run()`; kills FFmpeg. `Cancelled(BaseException)`. |
| `thermal.py` (new, untracked) | Thermal guard for laptops (Windows). Background thread reads CPU temperature every 2 s (`cpu_temp` via PDH counter, no admin). At `TEMP_PAUSE` (default 88 °C) it suspends every FFmpeg process (`_suspend`), and resumes at `TEMP_RESUME` (default 75 °C). `start()`, `wait()`. Does nothing on non-Windows or with no sensor. |
| `ffmpeg.py` | `find_ffmpeg` (system install first, else `imageio-ffmpeg` binary), `media_duration`, `run_ffmpeg` (cancellable), `move_into_place` (atomic-ish output write). |
| `roman.py` | Urdu/Hindi script to Roman Urdu (Latin letters), word by word so timestamps stay aligned. `romanize`, `romanize_texts`, `needs_roman`, `ask_groq` (uses the Groq text model), cache (`load_cache`). |
| `grades.py`, `presets.py`, `styles.py`, `fonts.py` | See above. |

### Tests and assets

| Path | Role |
|---|---|
| `tests/smoke_test.py` | End-to-end test: runs every preset through `make_shorts` and checks outputs (video exists, length, audio and video streams, thumbnails). `--mock` uses fake AI answers (~2-3 min, no internet). Run: `python tests/smoke_test.py input/podcast.mp4 --mock`. |
| `assets/fonts/` | Caption fonts: Anton, Archivo Black, Bangers, Bebas Neue, Luckiest Guy, Poppins, Noto Nastaliq Urdu, plus `_libass_widths.json`. |
| `assets/sfx/` | `ding.wav`, `pop.wav`, `whoosh.wav` (generated). |
| `assets/broll/` | User's own B-roll clips (`README.txt` explains naming). |
| `assets/music/` | Background music tracks (`--music lofi_chill` default; or your own mp3). |
| `input/`, `output/`, `models/` | Created at runtime, git-ignored. Videos, results, AI model files. |

## 4. Key settings (`studio/pipeline.py: Settings`)

Main fields (defaults in code): `lang` (auto), `clips` (5), `min_len` (20), `max_len` (60), `auto_len` (AI picks
length), `gap` (0.6 s silence cut threshold), `cut_silence`, `track_faces`, `roman`, `caption_style` (`bold_pop`),
`emphasis`, `sfx`, `music`, `music_volume` (0.12), `punch_in`, `hook_anim`, `hook_look`, `layout` (`auto` / `single` /
`split`), `progress_bar`, `name` and `name_title` (lower third), `broll`, `counters`, `shake`, `transition` (`flash` /
`glitch` / `none`), `grade`, `end_card`, `cta`, `handle`, `logo`, `portrait` (background blur), `thumbnails`,
`teaser`, `font`, `hook_start`, `combine`, `combine_smooth`, `focus`, `landscape`, `context`, `denoise`
(`off`/`light`/`medium`/`strong`).

CLI flag names differ slightly: `--no-cut`, `--no-track`, `--min`, `--max`, `--style`, `--blur`, `--no-thumbs`,
`--no-broll`, `--no-combine`, etc. The mapping is `cli_values()` in `main.py`.

## 5. Config and secrets

- Keys go in `.env` locally, or in Streamlit Cloud Secrets, or as HF Space Secrets (via `deploy_hf.py`).
- `app.py: load_secrets()` copies Streamlit Secrets into `os.environ` on every page load, so keys added after startup work
  without a reboot. Top-level or `[section]` keys, any case.
- `APP_PASSWORD` enables the password gate (public deployments, to protect API quota).
- Rate limits: several Groq accounts rotate automatically (`GROQ_API_KEY_2/3`). Rate-limited models are remembered
  and skipped; per-minute limits are waited out.
- Caching: transcripts, Roman Urdu, AI picks and face scans are cached in `output/`, so re-runs are cheap.
  `--reuse` re-renders previous AI clips.

## 6. Current state (as of the handoff)

Git status shows **18 changed paths**, all uncommitted:
- Modified: `.env.example`, `README.md`, `app.py`, `main.py`, `studio/cancel.py`, `studio/clipper.py`,
  `studio/config.py`, `studio/context.py`, `studio/ffmpeg.py`, `studio/framing.py`, `studio/pipeline.py`,
  `studio/presets.py`, `studio/render.py`, `studio/segment.py`, `studio/styles.py`
- Deleted (tracked, not on disk): `.streamlit/config.toml`, `.streamlit/secrets.toml.example`
- Untracked: `studio/thermal.py`

Recent commits (newest first):
- `34c6650` Make Gemini optional: the app runs on a single Groq key
- `dd192f8` Missing-key message: flag secrets that are present but empty
- `3126382` Cloud: pick up Streamlit Secrets saved or changed after startup; clearer missing-key message
- `f51d669` README: Streamlit Community Cloud deployment steps
- `27a0f08` Remove MIT license badge from README

Open items to confirm before committing:
1. Are the deleted `.streamlit/*` files intentional? The README and `.gitignore` reference them.
2. `studio/thermal.py` is new and untracked. It is already imported by `studio/cancel.py` (line 10) and
   `studio/pipeline.py` (line 454, inside `make_shorts`), so committing it is required or the tracked code will fail to import on a clean checkout.
3. Gemini is now optional. Confirm `clipper.py` and `main.py models` handle a missing `GEMINI_API_KEY` everywhere.

## 7. Roadmap (from README, not built yet)

- Phase 2 leftover: 3D text and particle effects (Remotion)
- Phase 3, Style Match: analyze an inspiration reel's style (pacing, captions, colors, music tempo), apply to clips
- Phase 4, Carousel Maker: hook/value/CTA slides, PNG/PDF export
- Phase 5, Real website: accounts, database, file storage, dashboard, Next.js UI
- Phase 6, Publish: YouTube and Instagram connect, approval queue, scheduler
- Phase 7, Grow: analytics, weak-point diagnosis, auto re-edit, learning loop
- Phase 8, AI UGC: voice clone, AI script writer, lip-synced avatar, consent verification
- Phase 9, Product Ad: product hero shots, 3 sizes, A/B hook variants
- Phase 10, Launch: payments, credits, landing page, privacy policy, beta onboarding

## 8. Conventions and gotchas

- **Laptop safety (owner's rule):** never add CPU/GPU-heavy local work by default. Prefer API calls (Groq).
  Keep CPU_THREADS=2, FFMPEG_AT_ONCE=1. Heavy features (blur, segmentation) stay off by default.
- **Keep the pipeline single-sourced.** Both the web app and the CLI call `make_shorts(video, Settings)`. Don't add
  pipeline logic to `app.py` or `main.py`; add it to `studio/` and expose it as a `Settings` field.
- **New preset:** add an entry to `PRESETS` in `presets.py`. It appears in both CLI and web automatically.
- **New caption style:** add a `CaptionStyle` to `STYLES` in `styles.py`; a font goes in `fonts.py` (`FONTS` dict).
- **UI changes:** visuals go in `ui.py` (CSS variables for both themes), layout logic in `app.py`.
- **Cancellation:** raise through `cancel.check()` inside long loops; use `Cancelled` (BaseException) so pipeline
  `except Exception` blocks don't swallow a Stop.
- **Thumbnails use libass, not Pillow**, because of Urdu shaping.
- **Windows console encoding:** scripts that print Urdu/arrows can crash under cp1252. Set `PYTHONIOENCODING=utf-8`
  or use `encoding="utf-8"` in `open()`. Docker sets this already.
- **FFmpeg:** a full build (with libass and arnndn) is recommended. `imageio-ffmpeg` is the fallback and may lack filters.
- **Models download on first use** (face, segmentation, RNNoise, fonts, sounds). They're git-ignored (`models/`, `assets/fonts` is tracked).
- **Don't commit** `.env`, `input/`, `output/`, `models/`, or media files.
- **Tests:** run the `--mock` smoke test after pipeline changes. It catches features that work alone but break together.

## 9. How to run

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # then set GROQ_API_KEY
streamlit run server.py          # http://localhost:8501

python main.py shorts input/video.mp4 --preset podcast_pro --clips 5
python tests/smoke_test.py input/podcast.mp4 --mock
```
