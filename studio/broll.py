"""Auto B-roll: the AI decides where to cut away and what to search for; footage comes from these sources
(in this order, first match wins):

1. Your folder  assets/broll/   (no key; file name = what the footage shows, e.g. money.mp4, sign_language.mp4)
                                Drop in clips downloaded from Mixkit / Videvo or your own shoots.
2. Pexels       PEXELS_API_KEY
3. Pixabay      PIXABAY_API_KEY
4. Unsplash     UNSPLASH_ACCESS_KEY  (stills only: rendered with a slow 'Ken Burns' zoom)

Credits (photographer + link + site) are saved in the SEO pack."""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

from studio.clipper import ask_with_fallback
from studio.config import ROOT, OUTPUT_DIR, PEXELS_API_KEY, PIXABAY_API_KEY, UNSPLASH_ACCESS_KEY

PEXELS_URL = "https://api.pexels.com/videos/search"
PIXABAY_URL = "https://pixabay.com/api/videos/"
UNSPLASH_URL = "https://api.unsplash.com/search/photos"
LIBRARY_DIR = ROOT / "assets" / "broll"
CACHE_DIR = OUTPUT_DIR / "_broll_cache"
BROLL_SECONDS = 2.2          # how long each B-roll shows

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


class Pick(BaseModel):
    index: int = Field(description="number of the word where the B-roll should start")
    query: str = Field(description="1-3 word English search query for a stock video site, e.g. 'counting money'")


class Picks(BaseModel):
    picks: list[Pick]


# ---------------- Apna folder (assets/broll) ----------------

def words_of(text: str) -> set[str]:
    """'Sign_Language-2' → {'sign', 'language'}  (no numbers or very short words)"""
    return {w for w in re.split(r"[^a-z]+", text.lower()) if len(w) > 1}


def library() -> list[Path]:
    """All videos/images in assets/broll (including sub-folders)."""
    if not LIBRARY_DIR.exists():
        return []
    return sorted(p for p in LIBRARY_DIR.rglob("*") if p.suffix.lower() in VIDEO_EXT | IMAGE_EXT)


def library_names() -> list[str]:
    """For the AI prompt: what footage the folder contains ('sign language', 'money', ...)."""
    names = {" ".join(sorted(words_of(p.stem), key=p.stem.lower().find)) for p in library()}
    return sorted(n for n in names if n)


def search_library(query: str) -> dict | None:
    """Match the query words against file (and folder) names. Best-matching file wins; videos beat images."""
    want = words_of(query)
    best, best_score = None, 0.0
    for p in library():
        have = words_of(p.stem) | words_of(p.parent.name if p.parent != LIBRARY_DIR else "")
        score = len(want & have) + (0.5 if p.suffix.lower() in VIDEO_EXT else 0)
        if want & have and score > best_score:
            best, best_score = p, score
    if not best:
        return None
    return {"id": f"local_{best.stem}", "path": str(best), "url": "", "user": "", "source": "Apna folder",
            "kind": "image" if best.suffix.lower() in IMAGE_EXT else "video"}


# ---------------- Pexels ----------------

def best_file(video: dict) -> dict | None:
    """Pexels offers several sizes per video. Pick a portrait mp4 with height near 1920, at least 960."""
    files = [f for f in video.get("video_files", [])
             if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
    if not files:
        return None
    portrait = [f for f in files if f["height"] > f["width"] and f["height"] >= 960]
    pool = portrait or [f for f in files if f["height"] >= 720] or files
    return min(pool, key=lambda f: abs(f["height"] - 1920))


def search_pexels(query: str) -> dict | None:
    """First good video from Pexels. Returns: {'id', 'link' (mp4), 'url' (Pexels page), 'user' (photographer)}"""
    params = urllib.parse.urlencode({"query": query, "orientation": "portrait", "size": "medium", "per_page": 8})
    req = urllib.request.Request(f"{PEXELS_URL}?{params}",
                                 headers={"Authorization": PEXELS_API_KEY, "User-Agent": "ai-creative-studio"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))

    for video in data.get("videos", []):
        if video.get("duration", 0) < BROLL_SECONDS:
            continue
        f = best_file(video)
        if f:
            return {"id": video["id"], "link": f["link"], "url": video.get("url", ""),
                    "user": (video.get("user") or {}).get("name", ""), "source": "Pexels", "kind": "video"}
    return None


# ---------------- Pixabay ----------------

def best_size(sizes: list[dict]) -> dict | None:
    """Pixabay offers 4 sizes per video (large/medium/small/tiny). Portrait if available, otherwise the 720p+
    size closest to 1920. We crop to 9:16 ourselves later."""
    sizes = [v for v in sizes if v.get("url") and v.get("width") and v.get("height")]
    if not sizes:
        return None
    portrait = [v for v in sizes if v["height"] > v["width"] and v["height"] >= 960]
    pool = portrait or [v for v in sizes if v["height"] >= 720] or sizes
    return min(pool, key=lambda v: abs(max(v["width"], v["height"]) - 1920))


def search_pixabay(query: str) -> dict | None:
    """First good video from Pixabay. Pixabay wants the key in the URL, so errors have the key masked."""
    params = urllib.parse.urlencode({"key": PIXABAY_API_KEY, "q": query, "video_type": "film",
                                     "safesearch": "true", "per_page": 10})
    req = urllib.request.Request(f"{PIXABAY_URL}?{params}", headers={"User-Agent": "ai-creative-studio"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))

    for hit in data.get("hits", []):
        if hit.get("duration", 0) < BROLL_SECONDS:
            continue
        f = best_size(list((hit.get("videos") or {}).values()))
        if f:
            return {"id": f"pixabay_{hit['id']}", "link": f["url"], "url": hit.get("pageURL", ""),
                    "user": hit.get("user", ""), "source": "Pixabay", "kind": "video"}
    return None


# ---------------- Unsplash (tasveerein) ----------------

def search_unsplash(query: str) -> dict | None:
    """Portrait photo from Unsplash. Unsplash's terms: ping 'download_location' on download, and credit the
    photographer + Unsplash (in the SEO pack and on the website)."""
    params = urllib.parse.urlencode({"query": query, "orientation": "portrait", "per_page": 5, "content_filter": "high"})
    req = urllib.request.Request(f"{UNSPLASH_URL}?{params}",
                                 headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}",
                                          "Accept-Version": "v1", "User-Agent": "ai-creative-studio"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))

    for photo in data.get("results", []):
        raw = (photo.get("urls") or {}).get("raw")
        if not raw:
            continue
        sep = "&" if "?" in raw else "?"
        return {"id": f"unsplash_{photo['id']}", "link": f"{raw}{sep}w=1080&h=1920&fit=crop&q=85&fm=jpg",
                "url": (photo.get("links") or {}).get("html", ""), "user": (photo.get("user") or {}).get("name", ""),
                "source": "Unsplash", "kind": "image",
                "download_location": (photo.get("links") or {}).get("download_location", "")}
    return None


# ---------------- Putting it together ----------------

def sources() -> list[tuple[str, callable]]:
    """Every available source, in order: your folder → Pexels → Pixabay → Unsplash."""
    out = []
    if library():
        out.append(("Apna folder", search_library))
    if PEXELS_API_KEY:
        out.append(("Pexels", search_pexels))
    if PIXABAY_API_KEY:
        out.append(("Pixabay", search_pixabay))
    if UNSPLASH_ACCESS_KEY:
        out.append(("Unsplash", search_unsplash))
    return out


def ready() -> bool:
    """Is any B-roll source available? (files in the folder, or any key)"""
    return bool(sources())


def hide_keys(text: str) -> str:
    """Never print an API key in an error message (Pixabay's key is in the URL)."""
    for key in (PEXELS_API_KEY, PIXABAY_API_KEY, UNSPLASH_ACCESS_KEY):
        if key:
            text = text.replace(key, "***")
    return text


def build_prompt(words: list[dict], max_picks: int, names: list[str], only_names: bool) -> str:
    numbered = " ".join(f"{i}:{w['word'].strip()}" for i, w in enumerate(words))
    if names and only_names:
        lib = (f"The only available footage is: {', '.join(names)}.\n"
               "The query MUST be exactly one of these names. If none fits a moment, do not pick it.\n")
    elif names:
        lib = (f"The user's own footage library has: {', '.join(names)}.\n"
               "When one of these fits, use that exact name as the query (it is preferred over stock sites).\n")
    else:
        lib = ""
    return f"""You are a short-form video editor choosing B-roll (stock footage cutaways) for one clip.
Below are the words of the clip, each with its number.

Pick at most {max_picks} moments where a 2-second cutaway would make the clip more engaging.
Only pick concrete, visual things the speaker mentions (money, city, laptop, gym, coffee, team meeting, airplane, phone).
Do NOT pick abstract or emotional moments where the speaker's face matters.
For each, give the number of the word where the B-roll should start and a short English search query (1-3 words).
The video may be in Urdu, Hindi or English, but the query must always be in English.
{lib}
Words:
{numbered}
"""


def clean_query(q: str) -> str:
    q = re.sub(r"[^A-Za-z0-9 ]+", " ", q)
    return " ".join(q.split())[:40]


def choose_moments(words: list[dict], log=print) -> list[dict]:
    """Moments from the AI. Returns: [{'start': <word's original time>, 'word': ..., 'query': ...}]"""
    if not words:
        return []
    duration = words[-1]["end"] - words[0]["start"]
    max_picks = int((duration - 4) / 8)            # about one every ~8 seconds; too much B-roll feels cluttered
    if max_picks < 1:
        return []

    names = library_names()
    only_names = bool(names) and len(sources()) == 1      # only your folder is available: the AI picks from its names
    log("     AI is picking B-roll moments...")
    result = ask_with_fallback(build_prompt(words, max_picks, names, only_names), Picks, log, temperature=0.3)

    picks, seen = [], set()
    for p in result.picks:
        q = clean_query(p.query)
        if not 0 <= p.index < len(words) or p.index in seen or not q:
            continue
        seen.add(p.index)
        w = words[p.index]
        picks.append({"start": w["start"], "word": w["word"].strip(), "query": q})
        if len(picks) >= max_picks:
            break
    return picks


def download(item: dict) -> Path:
    """Local file for a piece of footage. Your folder: that file. Online: downloaded once (cached after)."""
    if item.get("path"):
        path = Path(item["path"])
        if not path.exists():
            raise FileNotFoundError(f"file no longer in assets/broll: {path.name}")
        return path

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ext = ".jpg" if item.get("kind") == "image" else ".mp4"
    path = CACHE_DIR / f"{item['id']}{ext}"
    if not path.exists() or path.stat().st_size < 10_000:
        if item.get("download_location") and UNSPLASH_ACCESS_KEY:     # Unsplash terms: count the download
            ping = urllib.request.Request(item["download_location"],
                                          headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}",
                                                   "User-Agent": "ai-creative-studio"})
            try:
                urllib.request.urlopen(ping, timeout=20).close()
            except Exception:
                pass
        tmp = path.with_suffix(".part")
        req = urllib.request.Request(item["link"], headers={"User-Agent": "ai-creative-studio"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            f.write(r.read())
        tmp.replace(path)
    return path


def find_footage(picks: list[dict], log=print) -> list[dict]:
    """Try the sources one by one for each pick; first match wins. If none has it, drop the pick."""
    items, srcs = [], sources()
    for p in picks:
        found, where = None, ""
        for name, search in srcs:
            try:
                found = search(p["query"])
            except Exception as e:
                log(f"     Warning: {name} search failed ({p['query']}): {hide_keys(str(e))[:120]}")
                continue
            if found:
                where = name
                break
        if found:
            items.append({**p, **found})
            who = f" ({found['user']})" if found.get("user") else ""
            log(f"     B-roll: '{p['query']}' → {where} {found['id']}{who}")
        else:
            log(f"     Warning: no footage found for '{p['query']}'")
    return items
