<div align="center">

# 🎬 AI Creative Studio

**Turn one long video into a batch of scroll-stopping Shorts, automatically.**

Drop in a podcast, interview or talking-head video (up to 2 hours). AI finds the most gripping moments, writes
honest hooks, edits, captions, frames and mixes every clip, and hands back ready-to-post 9:16 Shorts, 16:9
YouTube cuts, a combined highlight reel, thumbnails and an SEO pack.

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.67-FF4B4B?logo=streamlit&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-libass%20%7C%20RNNoise-007808?logo=ffmpeg&logoColor=white)
![Gemini](https://img.shields.io/badge/Google-Gemini-4285F4?logo=google&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-Whisper%20%2B%20LLMs-F55036)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)

</div>

---

## Why it exists

Repurposing long-form content is the highest-leverage growth move for podcasters, coaches and creators, and the
most tedious one. A single hour of video hides 5 to 10 viral moments, but finding them, cutting them, captioning
them, reframing them for vertical and writing hooks takes an editor a full day.

AI Creative Studio does that pass in minutes, on a laptop CPU, with no GPU and no subscription editing tools.

## What you get from one upload

| Output | Details |
|---|---|
| **Vertical Shorts (9:16)** | 1080x1920, ready for YouTube Shorts, Instagram Reels and TikTok |
| **Landscape cuts (16:9)** | The same clips reframed for YouTube (optional) |
| **Combined highlight reel** | All clips in original order, hook shown once, transitions at every join, bridge lines between parts |
| **Thumbnails** | A 9:16 cover and a 16:9 YouTube thumbnail per Short, picked from the sharpest, clearest face frame |
| **SEO pack** | Title, description, hashtags and the AI's reasoning for every clip (JSON) |

## Features

### 🧠 AI editing
- **Viral moment detection.** Scores every candidate moment for hook strength and keeps the best, never overlapping.
- **Honest hooks.** The AI drafts 3 hooks per clip using proven formulas and keeps the strongest. A built-in
  truth check rejects any number, statistic or time claim that was not actually said in the video.
- **Starts on the spoken hook.** Each Short opens on the exact sentence where the speaker delivers the hook.
- **Stand-alone context.** If a Short needs earlier context to make sense, the AI adds the minimum setup sentences.
  Clips always end on a complete sentence.
- **Long videos.** Videos of 1 to 2 hours are transcribed in parallel chunks and analyzed in parallel parts, so
  the wait is the length of the longest part, not the sum.

### 🎥 Visuals
- **Face tracking and active-speaker detection**, using lip movement to tell who is talking.
- **Automatic split-screen** for two-person interviews, plus **speaker focus**, which zooms in on a distant speaker.
- **10 caption styles** with word-by-word highlight and pop, and 6 Google Fonts.
- **5 hook looks:** bold, pill, sticker, box, and **text behind the person** (AI segmentation).
- **Portrait-mode background blur**, zoom punch-ins on jump cuts, screen shake, flash and glitch transitions.
- **Auto B-roll** from your own folder, Pexels, Pixabay or Unsplash, with photographer credits saved.
- **Animated number counters**, lower thirds, an end screen with logo and CTA, and 6 color grades.

### 🔊 Audio
- **Silence removal** that never cuts real speech.
- **Background noise removal** (RNNoise) with an optional speech gate for noisy rooms.
- **Loudness normalized to -16 LUFS**, the Shorts and YouTube standard.
- **Background music with automatic ducking**, plus synthesized sound effects with no licensing issues.

### 🌍 Languages
- **English, Urdu and Hindi.** Language is detected automatically, and the hooks and titles follow it.
- **Roman Urdu captions** (Urdu written in Latin letters, the way millions of viewers actually type), word-synced.

### 🖥️ Web app
- Clean **glassmorphism UI** with dark and light themes.
- **Large uploads up to 20 GB**, streamed to disk in chunks. The upload is resumable and shows a progress bar
  with speed and time left. A 2-hour 1080p video uploads with flat memory use.
- **Upload from a phone.** The sidebar shows a QR code to open the app on any device on the same Wi-Fi.
- A **Stop button** that cancels a run and kills its render processes within seconds.
- **Live progress log**, and settings can be changed mid-run without breaking the job.
- **One-click presets:** Talking Head Viral, Podcast Pro, Clean & Minimal, or Custom.
- **Optional password gate**, so a public deployment can't burn through your API quota.

## How it works

```mermaid
flowchart LR
    A[Long video] --> B[Groq Whisper<br/>parallel transcription]
    B --> C[Language check<br/>+ Roman Urdu]
    C --> D[Gemini / Groq LLMs<br/>moments, hooks, context]
    D --> E[Truth check<br/>no invented numbers]
    E --> F[Face tracking<br/>segmentation, framing]
    F --> G[FFmpeg render<br/>captions, audio, effects]
    G --> H[Shorts 9:16 + 16:9<br/>reel, thumbnails, SEO]
```

**Built for reliability on free API tiers.**
- **Two AI providers.** Gemini and Groq back each other up. Requests are routed by size: small prompts go to
  the fastest model, large prompts to the biggest context.
- **Rate limits handled for you.** Several Groq accounts rotate automatically. Rate-limited or exhausted models
  are remembered and skipped, and per-minute limits are waited out instead of failing the run.
- **Work is cached.** Transcripts, Roman Urdu conversions and AI picks are reused, so re-runs cost almost nothing.

## Quick start

**Requirements:** Python 3.12+ and FFmpeg (`winget install Gyan.FFmpeg`, `brew install ffmpeg` or
`apt install ffmpeg`). If FFmpeg is missing, the bundled `imageio-ffmpeg` binary is used.

```bash
git clone https://github.com/alizaafzal582004/creative-studio-agent.git
cd creative-studio-agent
python -m venv venv
# Windows: venv\Scripts\activate    macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then add your API keys
streamlit run server.py     # opens http://localhost:8501
```

### API keys

Both required keys have free tiers.

| Variable | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | ✅ | Whisper transcription + backup LLM ([console.groq.com](https://console.groq.com)) |
| `GEMINI_API_KEY` | ✅ | Clip selection and hooks ([aistudio.google.com](https://aistudio.google.com)) |
| `GROQ_API_KEY_2`, `GROQ_API_KEY_3` | | Extra Groq **accounts**; limits are per account, so each one adds quota |
| `GEMINI_MODEL` | | Pin a specific Gemini model (default: best available Flash model) |
| `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `UNSPLASH_ACCESS_KEY` | | Stock B-roll sources |
| `APP_PASSWORD` | | Password-protect the web app |

## Step-by-step setup

Follow the section for your operating system. Expect about 10 minutes from a fresh machine.

### 1. Install the prerequisites

<details open>
<summary><b>Windows 10 / 11</b></summary>

Open **PowerShell** and run:

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install Git.Git
```

Close and reopen PowerShell so the new commands are on your PATH. Then check them with
`python --version`, `ffmpeg -version` and `git --version`.
</details>

<details>
<summary><b>macOS</b></summary>

Install [Homebrew](https://brew.sh) if you don't have it, then:

```bash
brew install python@3.12 ffmpeg git
```
</details>

<details>
<summary><b>Linux (Ubuntu / Debian)</b></summary>

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg git
```
</details>

> **Use a full FFmpeg build** (the commands above install one). It includes `libass` for captions and
> `arnndn` for noise removal. Without a system FFmpeg, the app falls back to the bundled `imageio-ffmpeg` binary,
> which works but may lack some filters.

### 2. Get the code and install dependencies

```bash
git clone https://github.com/alizaafzal582004/creative-studio-agent.git
cd creative-studio-agent
python -m venv venv
```

Activate the virtual environment, then install:

```bash
# Windows (PowerShell)
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Add your API keys

```bash
cp .env.example .env          # Windows: copy .env.example .env
```

Open `.env` in any text editor and paste in your keys:

1. **Groq.** Sign in at [console.groq.com](https://console.groq.com), go to **API Keys**, click
   **Create API Key**, and paste it as `GROQ_API_KEY`.
2. **Gemini.** Sign in at [aistudio.google.com](https://aistudio.google.com), click **Get API key**, then
   **Create API key**, and paste it as `GEMINI_API_KEY`.

### 4. Run it

```bash
streamlit run server.py
```

Your browser opens **http://localhost:8501**. To try it, pick a preset in the sidebar, upload a video, and
click **Create Shorts**. The results appear on the same page, with download buttons.

The first run downloads three small AI models (face detection, segmentation, noise removal; about 7 MB in
total). Later runs start instantly.

**Use it from your phone.** Open the **Open on your phone** section in the sidebar and scan the QR code with
any device on the same Wi-Fi.

## Make it fast (low latency)

Rendering runs on your CPU through FFmpeg, and the AI steps run in the cloud. Here is what actually moves the
needle, from biggest impact to smallest:

| Tip | Impact | Why |
|---|---|---|
| **Turn off "16:9 landscape version"** (Output section) when you only need Shorts | ~2x faster render | Every clip is otherwise rendered twice |
| **Turn off "Background blur"** unless you need it | Large | The AI masks every frame of the clip |
| **Leave "Smooth crossfade" off** | Saves 1-2 min | Crossfades need an extra re-encode of the joined clips |
| **Add `GROQ_API_KEY_2` / `_3`** (free keys from separate Groq accounts) | Fewer waits on long videos | Transcription chunks and AI calls are spread across accounts, avoiding rate-limit pauses |
| **Run on a machine with more CPU cores** | Scales with cores | FFmpeg encoding and face scanning are CPU-bound |
| **Laptops: plug in and use "Best performance" / "High performance" power mode** | Up to ~2x | Battery saver throttles the CPU heavily during renders |
| **Big local files: use "Pick from the input/ folder"** instead of uploading | Skips the upload | Copy the video into `input/` and pick it from the list |
| **Re-runs are nearly free** | Seconds instead of minutes | Transcripts, Roman Urdu and AI picks are cached; re-uploading the same video reuses them. On the CLI, `--reuse` re-renders with no AI calls |
| **Fewer or shorter Shorts** ("How many Shorts?", length range) | Linear | Render time is proportional to total output length |

**Reference timing:** a 1-hour interview producing 3 Shorts with 16:9 versions took about 20 minutes end to end
on a mid-range laptop CPU, and about 80% of that was rendering. Turning off the 16:9 versions roughly halves the
render part.

**Hosting for a team:** run the Docker image (see [Deployment](#deployment)) on a cloud VM with 8+ vCPUs
(e.g. AWS `c7i.2xlarge`, GCP `c3-standard-8`, Azure `F8s v2`) in a US or Canada region close to your users.
Uploads and downloads then stay fast, and the AI APIs are a short hop away.

## Troubleshooting

| Problem | Fix |
|---|---|
| `API keys missing: GROQ_API_KEY ...` | Make sure `.env` is in the project folder (next to `server.py`) and has both required keys. Restart the app |
| `FFmpeg not found` | Install FFmpeg (step 1), then open a new terminal so it's on your PATH |
| `Groq ... limit reached` / long pauses | You hit a free-tier limit. Wait a few minutes, or add `GROQ_API_KEY_2` from another Groq account |
| `Neither Gemini nor Groq replied` | Both providers are busy or out of quota. Try again shortly; check your keys in the provider dashboards |
| Phone can't open the QR link | Make sure the phone is on the same Wi-Fi, and allow Python through the firewall when your OS asks |
| `Could not write ... another program is holding it` | A video player or OneDrive/Dropbox sync is locking the output file. Close it and run again |
| Port 8501 already in use | Run `streamlit run server.py --server.port 8502` |
| Uploads fail with 403 behind a proxy or iframe | Start with `--server.enableXsrfProtection false --server.enableCORS false` (the Dockerfile already does this) |

## Command line

Everything in the web app is also available from the terminal:

```bash
python main.py shorts input/video.mp4                                   # default preset: Talking Head Viral
python main.py shorts input/video.mp4 --preset podcast_pro --name "Jane Doe" --name-title "Founder, Acme Inc."
python main.py shorts input/video.mp4 --reuse --preset clean_minimal --grade bw   # re-render, no new AI calls
python main.py captions input/video.mp4 --roman                         # just an SRT file
python main.py shorts --help                                            # every option
```

## Deployment

**Docker** (any host):
```bash
docker build -t ai-creative-studio .
docker run -p 7860:7860 --env-file .env ai-creative-studio
```

**Hugging Face Spaces** (free CPU hosting): add `HF_TOKEN` (a *Write* token) to `.env`, then run
`python deploy_hf.py`. The script creates the Space, uploads the code, and stores your API keys as Space
**secrets**. Keys never go into the code or the repo.

## Project structure

```
server.py              Entry point: Streamlit app + streaming upload route
app.py                 Web UI (layout and logic)
ui.py                  Design system: themes, glass styling, upload widget
main.py                Command-line interface
studio/
  pipeline.py          Orchestrates long video → Shorts end to end
  transcribe.py        Parallel Whisper transcription, gap repair, language detection
  clipper.py           LLM routing (Gemini ↔ Groq), moment selection, hooks, truth checks
  context.py           Stand-alone context and bridge lines
  teaser.py            Spoken-hook opening and teaser
  framing.py           Face tracking and active-speaker detection
  segment.py           Person segmentation (blur, text behind person)
  render.py            FFmpeg filter graph: crops, captions, effects, audio mix
  captions.py          ASS captions, hook looks, lower thirds, end screen
  roman.py             Urdu/Hindi script → Roman Urdu, word-synced
  denoise.py           RNNoise noise removal and speech gate
  broll.py             B-roll from your folder / Pexels / Pixabay / Unsplash
  thumbnail.py         Best-frame picking and thumbnail rendering
  combine.py           Combined highlight reel
  bigupload.py         Chunked, resumable large-file upload
  cancel.py            Stop button: cancellation and process cleanup
  styles.py, fonts.py, grades.py, presets.py, sounds.py, kinetic.py, emoji.py, ...
tests/smoke_test.py    End-to-end test of every preset
```

## Testing

```bash
python tests/smoke_test.py input/video.mp4 --mock   # offline: fake AI answers, every preset + split-screen
python tests/smoke_test.py input/video.mp4          # with the real AI providers
```

The smoke test runs the full pipeline for every preset. It checks that each video exists, has the right length,
and contains both audio and video, and that the thumbnails were created. It works on a copy and cleans up after itself.

## Privacy and security

- **Videos stay on your machine.** Only audio (for transcription) and text (for the AI) are sent to the AI providers.
- **Keys are never committed or logged.** They are read from `.env` or platform secrets, and masked in error messages.
- **Uploads are isolated.** Each browser session gets a random upload token. Remote visitors can only upload,
  never browse the server's files.

## Credits

[FFmpeg](https://ffmpeg.org) · [Streamlit](https://streamlit.io) · [OpenCV](https://opencv.org) (YuNet, PP-HumanSeg) ·
[RNNoise models](https://github.com/GregorR/rnnoise-models) · [Google Fonts](https://fonts.google.com) (OFL / Apache) ·
[Groq](https://groq.com) · [Google Gemini](https://ai.google.dev)
