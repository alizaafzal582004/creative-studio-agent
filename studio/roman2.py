"""Behtar Roman Urdu captions.
- Poore jumle ka context AI ko milta hai (lafz alag alag nahi), lekin jawab har lafz ka alag (timestamps wahi rahen)
- Aam lafzon ki pakki spelling (hai, nahi, ke...) AI ke baghair, har dafa ek jaisi
- English lafz English hi rahte hain
- Naam / brand: .env mein GLOSSARY
- Apni ghalti ki list: assets/roman_fixes.txt  (ghalat => sahi), har video par lagti hai
- Cache: dobara chalane par Groq ki call nahi
Sab kaam Groq par (internet): laptop ka CPU/GPU istemal nahi hota."""
import hashlib
import json
import os
import re

from pydantic import BaseModel

from studio.config import ROOT, OUTPUT_DIR
from studio.groqjson import ask_json

FIXES_FILE = ROOT / "assets" / "roman_fixes.txt"
CACHE_FILE = OUTPUT_DIR / "_roman2_cache.json"
BATCH = 90                     # ek AI call mein kitne lafz

# Urdu lafz → pakki Roman spelling (AI par bhari). Sirf wo lafz jin ka ek hi matlab hai:
# "میں" (main = I / mein = in) aur "تو" (to / tu) jaan boojh kar nahi, unhein AI jumle se samjhega.
FIXED = {
    "ہے": "hai", "ہیں": "hain", "نہیں": "nahi", "کے": "ke", "کی": "ki", "کا": "ka",
    "کو": "ko", "اور": "aur", "یہ": "ye", "وہ": "wo", "بھی": "bhi", "سے": "se", "پر": "par",
    "تھا": "tha", "تھی": "thi", "تھے": "thay", "ہو": "ho", "ہم": "hum", "آپ": "aap", "جو": "jo",
    "لیکن": "lekin", "بہت": "bohat", "کچھ": "kuch", "ابھی": "abhi", "پہلے": "pehle", "بات": "baat",
    "کام": "kaam", "پیسے": "paise", "کر": "kar", "رہا": "raha", "رہی": "rahi", "رہے": "rahe",
    "گا": "ga", "گی": "gi", "گے": "ge", "اپنے": "apne", "اپنی": "apni", "اگر": "agar", "کیونکہ": "kyunke",
    "کیوں": "kyun", "ہاں": "haan", "جی": "ji", "یعنی": "yani", "مطلب": "matlab", "سب": "sab",
}
# AI ki likhi aam ghalat spellings → standard (sirf wo jo English lafz se nahi takratin)
VARIANTS = {"hy": "hai", "hn": "hain", "nhi": "nahi", "nahin": "nahi", "nhn": "nahi", "bohot": "bohat",
            "bht": "bohat", "kiun": "kyun", "kyu": "kyun", "mn": "mein", "ky": "ke"}

PROMPT = """Convert these Urdu/Hindi words to Roman Urdu, the way Pakistanis write it on Instagram.
Rules:
- Return exactly {n} items in "words", one per number, same order. Never merge or split words.
- Read the whole sentence for meaning, so words like کیا become "kya" (question) or "kiya" (did) correctly.
- میں is "main" when it means I, and "mein" when it means in. تو is "to" (then) or "tu" (you).
- Keep English words in normal English spelling (business, video, client). Keep numbers as digits.
- Use these spellings: hai, hain, nahi, kya, ke, ki, ka, ko, aur, ye, wo, bhi, se, par, bohat, kyun, lekin.
- Names and brands, spell exactly like this: {glossary}

Words:
{numbered}
"""


class RomanBatch(BaseModel):
    words: list[str]


def is_urdu(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" or "ऀ" <= ch <= "ॿ" for ch in text)


def glossary() -> str:
    return os.getenv("GLOSSARY", "").strip() or "(none)"


def load_fixes() -> list[tuple[re.Pattern, str]]:
    """assets/roman_fixes.txt ki lines 'ghalat => sahi' (# wali lines comment)."""
    fixes = []
    if FIXES_FILE.exists():
        for line in FIXES_FILE.read_text(encoding="utf-8").splitlines():
            if "=>" in line and not line.strip().startswith("#"):
                wrong, right = (x.strip() for x in line.split("=>", 1))
                if wrong:
                    fixes.append((re.compile(rf"(?<![\w']){re.escape(wrong)}(?![\w'])", re.IGNORECASE), right))
    return fixes


def tidy(word: str, fixes) -> str:
    low = word.lower()
    if low in VARIANTS:
        word = VARIANTS[low]
    for pattern, right in fixes:
        word = pattern.sub(right, word)
    return word


def romanize_batch(texts: list[str], cache: dict, log) -> list[str]:
    key = hashlib.sha1(("\n".join(texts) + glossary()).encode("utf-8")).hexdigest()
    if key in cache and len(cache[key]) == len(texts):
        return cache[key]
    numbered = " ".join(f"{i}:{t}" for i, t in enumerate(texts))
    for attempt in range(2):
        out = ask_json(PROMPT.format(n=len(texts), glossary=glossary(), numbered=numbered), RomanBatch, log,
                       temperature=0.1).words
        if len(out) == len(texts):
            cache[key] = out
            return out
        log(f"     ⚠ Roman: {len(texts)} lafz bheje, {len(out)} aaye, dobara...")
    raise RuntimeError("Roman Urdu: lafzon ki ginti nahi mili")


def romanize_words(words: list[dict], log=print) -> list[dict]:
    """words = [{'word': ..., 'start': ..., 'end': ...}, ...]  →  wahi list, 'word' Roman Urdu mein.
    Koi batch fail ho to us hisse ke lafz waise hi rehte hain (video phir bhi banti hai)."""
    cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
    fixes = load_fixes()
    out = [dict(w) for w in words]
    for i in range(0, len(words), BATCH):
        chunk = out[i:i + BATCH]
        texts = [w["word"].strip() for w in chunk]
        if not any(is_urdu(t) for t in texts):
            roman = texts
        else:
            try:
                roman = romanize_batch(texts, cache, log)
            except Exception as e:
                log(f"     ⚠ Roman Urdu batch skip: {str(e)[:120]}")
                continue
        for w, src, r in zip(chunk, texts, roman):
            core = src.strip("،۔؟!.,?")
            if core in FIXED:                       # pakki spelling AI par bhari
                r = FIXED[core]
            elif not is_urdu(src):                  # pehle se English / number: waisa hi
                r = src
            lead = " " if w["word"].startswith(" ") else ""
            w["word"] = lead + tidy(r.strip(), fixes)
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return out


def whisper_prompt() -> str:
    """Whisper ko ishara: ye Urdu (Hindi nahi) hai, aur ye naam aa sakte hain."""
    g = os.getenv("GLOSSARY", "").strip()
    return ("یہ گفتگو اردو اور انگریزی میں ہے۔" + (f" {g}" if g else ""))[:300]
