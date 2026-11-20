"""Website design: graphite 'glass' look (frosted glass cards, a silky shimmering wave background, silver buttons).
app.py only holds layout and logic; colors, shapes and HTML live here.

Two themes: 'dark' (the main design) and 'light'. Every color is a CSS variable; switching themes only swaps variables."""
from urllib.parse import quote

THEMES = {
    "dark": {
        "bg": "linear-gradient(155deg, #07080b 0%, #0d1016 40%, #121722 70%, #0a0c11 100%)",
        "glow1": "rgba(150,170,210,0.10)", "glow2": "rgba(200,210,230,0.06)",
        "silk": "205,215,235", "silk_alpha": 1.0,
        "glass": "rgba(20,23,31,0.55)", "glass_strong": "rgba(24,28,38,0.70)",
        "border": "rgba(255,255,255,0.11)", "text": "#eef0f6", "muted": "#a2a8b8",
        "field": "rgba(8,10,14,0.60)", "field_border": "rgba(255,255,255,0.15)",
        "shadow": "0 14px 44px rgba(0,0,0,0.50)",
        "accent": "#d6dce8", "accent2": "#e8ecf4", "accent_rgb": "214,220,232",
        "btn": "linear-gradient(90deg, #f4f6fa 0%, #d9dee8 45%, #aeb7c8 100%)", "btn_text": "#0f1218",
    },
    "light": {
        "bg": "linear-gradient(155deg, #f7f8fb 0%, #eceff5 45%, #dfe3ec 100%)",
        "glow1": "rgba(150,170,210,0.20)", "glow2": "rgba(120,135,165,0.10)",
        "silk": "120,135,165", "silk_alpha": 0.9,
        "glass": "rgba(255,255,255,0.60)", "glass_strong": "rgba(255,255,255,0.78)",
        "border": "rgba(30,40,60,0.12)", "text": "#151a24", "muted": "#5a6274",
        "field": "rgba(255,255,255,0.82)", "field_border": "rgba(30,40,60,0.16)",
        "shadow": "0 12px 36px rgba(30,40,60,0.12)",
        "accent": "#2b3242", "accent2": "#3b4457", "accent_rgb": "43,50,66",
        "btn": "linear-gradient(90deg, #1b2030 0%, #2e3547 55%, #49526a 100%)", "btn_text": "#f4f6fa",
    },
}


def _silk(rgb: str, strength: float) -> str:
    """Silky shimmering waves (SVG data URI): many thin lines together read as a folded piece of fabric, with
    a broad soft glow on top. No external image."""
    def ribbon(n, x0, y0, c1, c2, x3, y3, dy, spread, peak, width=1.4):
        out = []
        for k in range(n):
            f = k / (n - 1)
            alpha = peak * strength * (1 - abs(f - 0.55) * 1.6) ** 2      # brightest in the middle
            if alpha <= 0.004:
                continue
            o = k * dy
            d = (f"M{x0},{y0 + o} C{c1[0]},{c1[1] + o * spread} {c2[0]},{c2[1] - o * spread * 0.6} "
                 f"{x3},{y3 + o * 0.7}")
            out.append(f'<path d="{d}" fill="none" stroke="rgba({rgb},{alpha:.3f})" stroke-width="{width}"/>')
        return "".join(out)

    main = ribbon(46, -100, 640, (420, 420), (980, 1060), 1750, 520, 7, 1.5, 0.30)
    back = ribbon(30, 300, 1000, (760, 700), (1150, 980), 1750, 640, 6, 1.2, 0.14)
    top = ribbon(22, 700, -60, (1050, 160), (1350, 40), 1750, 260, 5, 1.0, 0.07, 1.0)
    glow = (f'<path d="M-100,700 C420,480 980,1120 1750,560 L1750,760 C980,1260 420,700 -100,900 Z" '
            f'fill="rgba({rgb},{0.07 * strength:.3f})" filter="url(#g)"/>')
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMid slice">'
           '<defs><filter id="g" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="40"/></filter>'
           '<filter id="s"><feGaussianBlur stdDeviation="0.6"/></filter></defs>'
           f'{glow}<g filter="url(#s)">{back}{main}{top}</g></svg>')
    return f'url("data:image/svg+xml;utf8,{quote(svg)}")' 


def css(theme: str = "dark") -> str:
    t = THEMES.get(theme, THEMES["dark"])
    waves = _silk(t["silk"], t["silk_alpha"])
    return f"""
<style>
  :root {{
    --glass: {t['glass']}; --glass-strong: {t['glass_strong']}; --border: {t['border']};
    --text: {t['text']}; --muted: {t['muted']}; --field: {t['field']}; --field-border: {t['field_border']};
    --shadow: {t['shadow']}; --accent: {t['accent']}; --accent2: {t['accent2']}; --accent-rgb: {t['accent_rgb']};
    --btn: {t['btn']}; --btn-text: {t['btn_text']};
  }}
  .stApp .cs-ico {{font-family: 'Material Symbols Rounded'; font-weight: normal; font-size: 1.15em; vertical-align: -0.2em; color: var(--accent2);}}
  .st-key-theme_toggle button p {{display: none;}}
  #MainMenu, footer {{visibility: hidden;}}
  header[data-testid="stHeader"] {{background: transparent;}}
  .stApp {{
    background: radial-gradient(1100px 620px at 85% -10%, {t['glow1']}, transparent 60%),
                radial-gradient(900px 520px at -10% 110%, {t['glow2']}, transparent 60%),
                {waves} center / cover no-repeat,
                {t['bg']};
    background-attachment: fixed;
    color: var(--text);
  }}
  .block-container {{padding-top: 1.4rem; max-width: 1240px;}}
  .stApp p, .stApp label, .stApp li, .stApp span, [data-testid="stMarkdownContainer"],
  [data-testid="stWidgetLabel"] * {{color: var(--text);}}
  [data-testid="stCaptionContainer"], .stApp small {{color: var(--muted) !important;}}

  /* ---- Sidebar: one large glass panel ---- */
  section[data-testid="stSidebar"] {{background: transparent; border: 0;}}
  section[data-testid="stSidebar"] > div:first-child {{
    background: var(--glass); backdrop-filter: blur(22px) saturate(140%);
    -webkit-backdrop-filter: blur(22px) saturate(140%);
    border: 1px solid var(--border); border-radius: 26px; margin: 12px;
    height: calc(100% - 24px); box-shadow: var(--shadow), inset 0 1px 0 rgba(255,255,255,0.08);
  }}
  section[data-testid="stSidebar"] h2 {{font-size: 1.15rem; font-weight: 700;}}

  /* ---- Glass cards (main cards, results, expanders) ---- */
  .st-key-hero, .st-key-source, .st-key-empty, .st-key-combined, [class*="st-key-card_"] {{
    background: var(--glass); backdrop-filter: blur(20px) saturate(140%);
    -webkit-backdrop-filter: blur(20px) saturate(140%);
    border: 1px solid var(--border) !important; border-radius: 24px; box-shadow: var(--shadow),
      inset 0 1px 0 rgba(255,255,255,0.07);
  }}
  .st-key-hero, .st-key-source, .st-key-empty, .st-key-combined, [class*="st-key-card_"] {{padding: 18px 22px;}}
  .st-key-hero [data-testid="stHorizontalBlock"] {{align-items: center;}}
  [data-testid="stExpander"] details {{
    background: rgba(255,255,255,0.035); border: 1px solid var(--border); border-radius: 16px;
  }}
  [data-testid="stExpander"] summary {{font-weight: 600;}}

  /* ---- Fields: rounded corners, soft glow ---- */
  [data-baseweb="select"] > div, [data-baseweb="input"] > div, [data-baseweb="textarea"],
  [data-testid="stFileUploaderDropzone"] {{
    background: var(--field) !important; border: 1px solid var(--field-border) !important;
    border-radius: 12px !important; box-shadow: 0 0 14px rgba(var(--accent-rgb),0.12);
  }}
  [data-baseweb="select"] *, [data-baseweb="input"] input {{color: var(--text) !important;}}

  /* ---- Upload "Browse files" button: accent gradient, readable in both themes ---- */
  [data-testid="stFileUploaderDropzone"] button {{
    background: var(--btn) !important;
    color: var(--btn-text) !important; border: 0 !important; border-radius: 12px !important;
    padding: 0.5rem 1.1rem !important; font-weight: 600;
    box-shadow: 0 6px 18px rgba(var(--accent-rgb),0.35);
  }}
  [data-testid="stFileUploaderDropzone"] button * {{color: var(--btn-text) !important;}}
  [data-testid="stFileUploaderDropzone"] button:hover {{filter: brightness(1.08);}}
  [data-testid="stFileUploaderDropzoneInstructions"] *, [data-testid="stFileUploaderFile"] * {{color: var(--muted) !important;}}
  [data-testid="stFileUploaderDropzoneInstructions"] svg {{fill: var(--accent2) !important;}}

  /* ---- Radio: unselected = empty glass circle, selected = accent ---- */
  [role="radiogroup"] label:has(input:not(:checked)) > div:first-child {{
    background: var(--field) !important; border: 2px solid var(--field-border) !important;
  }}

  /* ---- Big gradient button ---- */
  .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
    background: var(--btn);
    border: 0; border-radius: 16px; min-height: 58px; font-size: 1.08rem; font-weight: 650; color: var(--btn-text);
    box-shadow: 0 10px 30px rgba(var(--accent-rgb),0.45), inset 0 1px 0 rgba(255,255,255,0.35);
    transition: transform .15s ease, filter .15s ease;
  }}
  .stButton > button[kind="primary"]:hover {{filter: brightness(1.08); transform: translateY(-1px);}}
  .stButton > button[kind="primary"] p, .stButton > button[kind="primary"] span {{color: var(--btn-text) !important;}}
  .stDownloadButton > button, .stButton > button[kind="secondary"] {{
    background: var(--glass-strong); border: 1px solid var(--border); border-radius: 12px; color: var(--text);
  }}

  /* ---- Phone QR ---- */
  .cs-qr {{display: flex; justify-content: center; margin: 6px 0 10px;}}
  .cs-qr svg {{border-radius: 14px; box-shadow: 0 8px 24px rgba(0,0,0,0.35);}}

  /* ---- Stop button ---- */
  .st-key-stop_run button {{
    background: rgba(239,68,68,0.10) !important; border: 1px solid rgba(239,68,68,0.55) !important;
    border-radius: 14px !important; min-height: 48px; font-weight: 600;
  }}
  .st-key-stop_run button, .st-key-stop_run button * {{color: #f87171 !important;}}
  .st-key-stop_run button:hover {{background: rgba(239,68,68,0.18) !important;}}

  /* ---- Header ---- */
  .cs-head {{display: flex; align-items: center; gap: 16px;}}
  .cs-logo, .cs-brand-logo {{
    width: 60px; height: 60px; border-radius: 18px; flex: none; display: grid; place-items: center;
    background: rgba(var(--accent-rgb),0.08); border: 1px solid rgba(var(--accent-rgb),0.22);
    box-shadow: 0 0 24px rgba(var(--accent-rgb),0.25), inset 0 1px 0 rgba(255,255,255,0.10);
  }}
  .cs-logo-ico, .cs-big-ico, .cs-spark-ico {{font-family: 'Material Symbols Rounded'; line-height: 1;}}
  .stApp .cs-logo-ico {{font-size: 34px; color: var(--accent2);}}
  .stApp .cs-brand .cs-logo-ico {{font-size: 28px;}}
  .cs-brand-logo {{width: 50px; height: 50px; border-radius: 15px;}}
  .cs-empty-ico {{position: relative; display: inline-block;}}
  .stApp .cs-big-ico {{font-size: 130px; color: var(--accent2); filter: drop-shadow(0 0 22px rgba(var(--accent-rgb),0.55));}}
  .stApp .cs-spark-ico {{position: absolute; top: -6px; right: -30px; font-size: 40px; color: var(--accent2);}}
  .cs-title {{font-size: 2.1rem; font-weight: 750; letter-spacing: -0.02em; line-height: 1.1; color: var(--text);}}
  .cs-sub {{color: var(--muted); font-size: 0.92rem; margin-top: 4px;}}
  .st-key-theme_toggle button {{
    width: 46px; height: 46px; min-height: 46px; border-radius: 50% !important; padding: 0;
    background: var(--glass-strong); border: 1px solid var(--border); font-size: 1.15rem;
    box-shadow: 0 0 18px rgba(var(--accent-rgb),0.18);
  }}

  /* ---- Sidebar brand ---- */
  .cs-brand {{display: flex; align-items: center; gap: 12px; margin: 2px 0 8px;}}
  .cs-brand-name {{font-weight: 700; font-size: 1.12rem; line-height: 1.15; color: var(--text);}}

  /* ---- Empty state (no results yet) ---- */
  .cs-empty {{text-align: center; padding: 70px 10px 80px;
    background: radial-gradient(260px 200px at 50% 38%, rgba(190,205,235,0.10), transparent 70%);}}
  .cs-clapper {{animation: cs-float 5s ease-in-out infinite; filter: drop-shadow(0 0 26px rgba(190,205,235,0.18));}}
  @keyframes cs-float {{0%, 100% {{transform: translateY(0);}} 50% {{transform: translateY(-8px);}}}}
  .cs-empty h3 {{font-size: 1.6rem; font-weight: 650; line-height: 1.35; color: var(--text); margin-top: 18px;}}

  /* ---- Small result elements ---- */
  .muted {{color: var(--muted); font-size: 0.95rem;}}
  .hook {{font-weight: 600; font-size: 0.95rem;}}
  .tag {{display: inline-block; padding: 2px 9px; margin: 2px; border-radius: 999px; font-size: 0.78rem;
         background: rgba(var(--accent-rgb),0.08); color: var(--accent2); border: 1px solid rgba(var(--accent-rgb),0.22);}}
</style>
"""


def icon(name: str, cls: str = "cs-ico") -> str:
    """Material Symbols icon (Streamlit's own font), inside HTML."""
    return f'<span class="{cls}">{name}</span>'


def header_html(subtitle: str) -> str:
    return (f'<div class="cs-head"><div class="cs-logo">{icon("movie", "cs-logo-ico")}</div><div>'
            f'<div class="cs-title">AI Creative Studio</div><div class="cs-sub">{subtitle}</div></div></div>')


def brand_html() -> str:
    return (f'<div class="cs-brand"><div class="cs-brand-logo">{icon("movie_edit", "cs-logo-ico")}</div>'
            '<div class="cs-brand-name">AI Creative<br>Studio</div></div>')


# Glossy 3D clapperboard (center of the empty card): metallic gradient, open clapper on top, play button,
# glassy highlight, soft shadow below, sparkles around
CLAPPER_3D = """
<svg width="210" height="190" viewBox="0 0 210 190" xmlns="http://www.w3.org/2000/svg" class="cs-clapper">
  <defs>
    <linearGradient id="cm" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#f4f6fb"/><stop offset="0.45" stop-color="#b9c2d6"/><stop offset="1" stop-color="#5d6880"/>
    </linearGradient>
    <linearGradient id="cf" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#3a4256"/><stop offset="1" stop-color="#161b26"/>
    </linearGradient>
    <linearGradient id="ct" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#e9edf6"/><stop offset="1" stop-color="#8e99b2"/>
    </linearGradient>
    <linearGradient id="gl" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.28"/><stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="pl" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#c9d2e6"/>
    </linearGradient>
    <radialGradient id="sh" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#000" stop-opacity="0.55"/><stop offset="1" stop-color="#000" stop-opacity="0"/>
    </radialGradient>
    <filter id="soft" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="6"/><feOffset dy="8"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.45"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="spk"><feGaussianBlur stdDeviation="1.2" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <ellipse cx="105" cy="176" rx="72" ry="9" fill="url(#sh)"/>
  <g filter="url(#soft)">
    <!-- body -->
    <rect x="34" y="76" width="142" height="90" rx="16" fill="url(#cf)" stroke="url(#cm)" stroke-width="3"/>
    <rect x="38" y="80" width="134" height="40" rx="13" fill="url(#gl)"/>
    <!-- lower striped bar -->
    <rect x="34" y="64" width="142" height="18" rx="5" fill="url(#ct)"/>
    <path d="M50 64 h16 l-10 18 h-16 z M86 64 h16 l-10 18 h-16 z M122 64 h16 l-10 18 h-16 z M158 64 h16 l-10 18 h-16 z"
          fill="#1c2230"/>
    <!-- open clapper on top -->
    <g transform="rotate(-16 38 60)">
      <rect x="34" y="40" width="142" height="20" rx="5" fill="url(#ct)"/>
      <path d="M44 40 h16 l10 20 h-16 z M80 40 h16 l10 20 h-16 z M116 40 h16 l10 20 h-16 z M152 40 h16 l8 16 v4 h-14 z"
            fill="#1c2230"/>
      <rect x="34" y="40" width="142" height="7" rx="3.5" fill="#ffffff" opacity="0.35"/>
    </g>
    <circle cx="38" cy="61" r="5" fill="url(#cm)" stroke="#1c2230" stroke-width="1.5"/>
    <!-- play -->
    <circle cx="105" cy="122" r="25" fill="#ffffff" fill-opacity="0.08" stroke="#ffffff" stroke-opacity="0.35" stroke-width="1.5"/>
    <path d="M97 109 L120 122 L97 135 Z" fill="url(#pl)" stroke-linejoin="round"/>
  </g>
  <!-- sparkles -->
  <g filter="url(#spk)" fill="#eef1f8">
    <path d="M18 92 l3 -9 l3 9 l9 3 l-9 3 l-3 9 l-3 -9 l-9 -3 z"/>
    <path d="M186 26 l2.2 -6.5 l2.2 6.5 l6.5 2.2 l-6.5 2.2 l-2.2 6.5 l-2.2 -6.5 l-6.5 -2.2 z" opacity="0.9"/>
    <path d="M192 112 l1.6 -4.8 l1.6 4.8 l4.8 1.6 l-4.8 1.6 l-1.6 4.8 l-1.6 -4.8 l-4.8 -1.6 z" opacity="0.75"/>
    <path d="M30 30 l1.4 -4 l1.4 4 l4 1.4 l-4 1.4 l-1.4 4 l-1.4 -4 l-4 -1.4 z" opacity="0.6"/>
  </g>
</svg>
"""


def empty_html() -> str:
    return (f'<div class="cs-empty">{CLAPPER_3D}'
            f'<h3>Select your video<br>and let the magic begin {icon("auto_awesome")}</h3></div>')


# ---------------- Large video upload (works with studio/bigupload.py) ----------------
# Runs in a Streamlit iframe (same origin) and sends the file in 16 MB chunks to /api/bigupload.
# Progress, speed, time left; if the connection drops it retries 5 times, resuming where it stopped.
BIG_UPLOAD = r"""
<div id="box" class="box">
  <input id="file" type="file" accept="__ACCEPT__" hidden>
  <div id="idle">
    <svg class="ico" width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 18a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 8.5a4 4 0 0 1-.5 9.5"/><path d="M12 12v8M8.5 15.5 12 12l3.5 3.5"/></svg>
    <div class="txt"><b>Choose a video</b> from this device<br><span>Up to __MAXGB__ GB: long videos (2 hours) work too</span></div>
    <button id="pick">Browse</button>
  </div>
  <div id="busy" hidden>
    <div class="row"><span id="fname"></span><span id="pct">0%</span></div>
    <div class="bar"><div id="fill"></div></div>
    <div class="row sub"><span id="info">Starting...</span><button id="cancel" class="ghost">Cancel</button></div>
  </div>
</div>
<style>
  * {box-sizing: border-box; font-family: "Source Sans Pro", "Segoe UI", sans-serif;}
  body {margin: 0; background: transparent; color: __TEXT__;}
  .box {border: 1.5px dashed __BORDER__; border-radius: 14px; background: __FIELD__; padding: 16px 18px;
        min-height: 92px; display: flex; flex-direction: column; justify-content: center;}
  .box.drag {border-color: __ACCENT__; background: __FIELD_HI__;}
  #idle {display: flex; align-items: center; gap: 14px;}
  #idle[hidden], #busy[hidden] {display: none;}
  .ico {color: __ACCENT__; flex: none;}
  .txt {flex: 1; font-size: 15px; line-height: 1.4;} .txt span {color: __MUTED__; font-size: 13px;}
  button {border: 0; border-radius: 11px; padding: 9px 18px; font-weight: 600; font-size: 14px; cursor: pointer;
          background: __BTN__; color: __BTN_TEXT__;}
  button.ghost {background: transparent; color: __MUTED__; border: 1px solid __BORDER__; padding: 5px 12px;}
  .row {display: flex; justify-content: space-between; align-items: center; gap: 10px; font-size: 14px;}
  .row.sub {color: __MUTED__; font-size: 13px; margin-top: 8px;}
  #fname {overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600;}
  .bar {height: 10px; border-radius: 99px; background: __TRACK__; margin-top: 10px; overflow: hidden;}
  #fill {height: 100%; width: 0; border-radius: 99px; background: __BTN__; transition: width .3s;}
  .err {color: #f87171 !important;}
</style>
<script>
const TOKEN = "__TOKEN__", CHUNK = 16 * 1024 * 1024, MAX = __MAXBYTES__;
const EXT = "__ACCEPT__".split(",");
let base = "";
try { base = window.parent.location.origin + window.parent.location.pathname.replace(/\/+$/, ""); } catch (e) {}
const api = base + "/api/bigupload/" + TOKEN;
const $ = id => document.getElementById(id);
let stop = false;

function fmt(b) { return b >= 1073741824 ? (b / 1073741824).toFixed(2) + " GB" : (b / 1048576).toFixed(0) + " MB"; }
function eta(s) { s = Math.round(s); return s >= 3600 ? Math.floor(s / 3600) + "h " + Math.round(s % 3600 / 60) + "m"
                  : s >= 60 ? Math.floor(s / 60) + "m " + (s % 60) + "s" : s + "s"; }
function fail(msg) { $("info").textContent = msg; $("info").classList.add("err"); $("cancel").textContent = "Try again"; }
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function send(file) {
  const ext = "." + file.name.split(".").pop().toLowerCase();
  if (!EXT.includes(ext)) { alert("Unsupported file type " + ext); return; }
  if (file.size > MAX) { alert("File is larger than " + fmt(MAX)); return; }
  stop = false;
  $("idle").hidden = true; $("busy").hidden = false; $("fname").textContent = file.name;
  $("info").classList.remove("err"); $("cancel").textContent = "Cancel";
  let offset = 0;
  try { offset = (await (await fetch(api + "/status")).json()).offset || 0; } catch (e) {}
  if (offset > file.size) offset = 0;
  const t0 = performance.now(), start = offset;
  let tries = 0;
  while (offset < file.size) {
    if (stop) return;
    try {
      const r = await fetch(api + "?offset=" + offset, {method: "PUT", body: file.slice(offset, offset + CHUNK)});
      const j = await r.json();
      if (r.status === 409) { offset = j.offset; continue; }
      if (!r.ok) throw new Error(j.error || r.status);
      offset = j.offset; tries = 0;
    } catch (e) {
      if (++tries > 5) { fail("Upload failed: " + e.message); return; }
      $("info").textContent = "Connection problem, retrying (" + tries + "/5)...";
      await sleep(2000 * tries);
      try { offset = (await (await fetch(api + "/status")).json()).offset || offset; } catch (e2) {}
      continue;
    }
    const pct = offset / file.size * 100, secs = (performance.now() - t0) / 1000;
    const speed = (offset - start) / Math.max(secs, 0.1);
    $("fill").style.width = pct.toFixed(1) + "%"; $("pct").textContent = pct.toFixed(0) + "%";
    $("info").textContent = fmt(offset) + " of " + fmt(file.size) + " · " + fmt(speed) + "/s · "
                          + eta((file.size - offset) / Math.max(speed, 1)) + " left";
  }
  $("info").textContent = "Finishing...";
  const r = await fetch(api + "/done", {method: "POST", headers: {"Content-Type": "application/json"},
                                        body: JSON.stringify({name: file.name, size: file.size})});
  if (!r.ok) { fail("Upload failed: " + ((await r.json()).error || r.status)); return; }
  $("fill").style.width = "100%"; $("pct").textContent = "100%";
  $("info").textContent = "Uploaded. Loading...";
}

$("pick").onclick = () => $("file").click();
$("file").onchange = e => e.target.files[0] && send(e.target.files[0]);
$("cancel").onclick = () => { stop = true; $("busy").hidden = true; $("idle").hidden = false; $("file").value = ""; };
const box = $("box");
box.ondragover = e => { e.preventDefault(); box.classList.add("drag"); };
box.ondragleave = () => box.classList.remove("drag");
box.ondrop = e => { e.preventDefault(); box.classList.remove("drag"); e.dataTransfer.files[0] && send(e.dataTransfer.files[0]); };
</script>
"""


def big_upload_html(token: str, theme: str, accept: list[str], max_bytes: int) -> str:
    t = THEMES.get(theme, THEMES["dark"])
    dark = theme != "light"
    values = {
        "__TOKEN__": token, "__ACCEPT__": ",".join(f".{e}" for e in accept), "__MAXBYTES__": str(max_bytes),
        "__MAXGB__": str(max_bytes // 1024 ** 3), "__TEXT__": t["text"], "__MUTED__": t["muted"],
        "__BORDER__": t["field_border"], "__FIELD__": t["field"], "__ACCENT__": t["accent"],
        "__FIELD_HI__": "rgba(255,255,255,0.06)" if dark else "rgba(0,0,0,0.04)",
        "__TRACK__": "rgba(255,255,255,0.10)" if dark else "rgba(0,0,0,0.08)",
        "__BTN__": t["btn"], "__BTN_TEXT__": t["btn_text"],
    }
    html = BIG_UPLOAD
    for k, v in values.items():
        html = html.replace(k, v)
    return html
