import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Optional: keys from a second / third Groq ACCOUNT. Limits are per account: when one runs out, the next is used.
# (A new key on the same account doesn't help: limits apply per account.)
GROQ_API_KEYS = [k for k in (GROQ_API_KEY, os.getenv("GROQ_API_KEY_2"), os.getenv("GROQ_API_KEY_3")) if k]
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")   # optional: extra AI provider; without it everything runs on Groq
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")     # optional: B-roll only
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")   # optional: B-roll source instead of Pexels
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")   # optional: still images for B-roll
# backup Groq text model when Gemini is busy or out of quota
GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-120b")

# project root folder (two levels above config.py)
ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
FONTS_DIR = ROOT / "assets" / "fonts"
INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


def missing_keys() -> list[str]:
    """Which required API keys are missing (empty list = all good). Only Groq is required."""
    return [] if GROQ_API_KEY else ["GROQ_API_KEY"]
