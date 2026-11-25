"""Presets: complete settings in one click. Used by both the CLI (--preset) and the website (top of the sidebar).
To add your own preset, add an entry to PRESETS: it shows up in both places automatically."""
from dataclasses import fields, replace

from studio.pipeline import Settings

PRESETS = {
    "talking_head_viral": {
        "label": "Talking Head Viral",
        "about": "One person on camera, high energy: text behind person, big Anton font, shake, B-roll, glitch",
        "settings": dict(layout="single", caption_style="viral_anton", hook_look="behind", grade="vivid",
                         transition="glitch", shake=True, punch_in=True, emphasis=True, counters=True,
                         broll=True, gap=0.4, music=None, portrait=False, teaser=True, denoise="medium"),
    },
    "podcast_pro": {
        "label": "Podcast Pro",
        "about": "Interviews and podcasts with two people: split-screen, name lower third, cinematic color, background voices removed",
        "settings": dict(layout="auto", caption_style="green_karaoke", hook_look="pill", hook_anim="slide",
                         grade="cinematic", transition="flash", shake=False, punch_in=True, emphasis=True,
                         counters=True, broll=False, music=None, portrait=False, teaser=True,
                         denoise="strong"),
    },
    "clean_minimal": {
        "label": "Clean & Minimal",
        "about": "Calm and clean: background blur, Bebas font, typewriter hook, warm color, end screen",
        "settings": dict(layout="single", caption_style="clean_bebas", hook_look="bold", hook_anim="typewriter",
                         grade="warm", transition="none", shake=False, punch_in=False, emphasis=False,
                         counters=False, broll=False, music_volume=0.05, portrait=True, end_card=True,
                         teaser=False, denoise="medium"),
    },
    "custom": {
        "label": "Custom",
        "about": "Choose everything yourself (starts from the app defaults)",
        "settings": {},
    },
}
DEFAULT_PRESET = "talking_head_viral"
FIELDS = {f.name for f in fields(Settings)}


def preset_values(key: str) -> dict:
    """A preset's settings (only real Settings fields; an unknown name fails loudly, not silently)."""
    values = PRESETS.get(key, PRESETS["custom"])["settings"]
    unknown = set(values) - FIELDS
    if unknown:
        raise ValueError(f"Invalid setting in preset '{key}': {sorted(unknown)}")
    return dict(values)


def settings_for(preset_key: str, overrides: dict | None = None) -> Settings:
    """Settings() defaults → preset → your own options (applied last, override everything).
    (The parameter is 'preset_key', not 'name': in Settings, 'name' is the guest's name.)"""
    values = preset_values(preset_key)
    values.update(overrides or {})
    unknown = set(values) - FIELDS
    if unknown:
        raise ValueError(f"Invalid setting: {sorted(unknown)}")
    return replace(Settings(), **values)
