import argparse
import sys
import time
from pathlib import Path

from studio.config import OUTPUT_DIR
from studio.captions import words_to_srt
from studio.clipper import available_models, ranked_models, pick_model, ping, make_client
from studio.pipeline import get_transcript, make_shorts
from studio.roman import romanize
from studio.styles import STYLES, DEFAULT_STYLE, HOOK_ANIMS, HOOK_LOOKS
from studio.grades import GRADES, DEFAULT_GRADE
from studio.fonts import FONTS
from studio.presets import PRESETS, DEFAULT_PRESET, settings_for


# ---------------- Command 1: captions ----------------

def cmd_captions(args):
    video = Path(args.video)
    print("1/2  Transcript...")
    data = get_transcript(video, args.lang)
    words = data.get("words", [])
    if not words:
        raise SystemExit("No words found. Does the video have audio?")
    if args.roman:
        words = romanize(words, OUTPUT_DIR / f"{video.stem}_roman.json")

    print("2/2  Writing captions...")
    srt_path = OUTPUT_DIR / f"{video.stem}.srt"
    srt_path.write_text(words_to_srt(words, args.words), encoding="utf-8")
    print(f"\n✅ Captions: {srt_path}")


# ---------------- Command 2: shorts ----------------

def cli_values(args) -> dict[str, tuple[str, object]]:
    """Every Settings field: (its CLI option name, value)."""
    return {
        "lang": ("lang", args.lang), "clips": ("clips", args.clips), "min_len": ("min", args.min),
        "max_len": ("max", args.max), "gap": ("gap", args.gap), "cut_silence": ("no_cut", not args.no_cut),
        "track_faces": ("no_track", not args.no_track), "reuse": ("reuse", args.reuse),
        "roman": ("roman", args.roman), "caption_style": ("style", args.style),
        "emphasis": ("no_emphasis", not args.no_emphasis), "sfx": ("no_sfx", not args.no_sfx),
        "music": ("music", None if args.music == "none" else args.music),
        "music_volume": ("music_volume", args.music_volume), "punch_in": ("no_punch", not args.no_punch),
        "hook_anim": ("hook_anim", args.hook_anim), "layout": ("layout", args.layout),
        "progress_bar": ("no_progress", not args.no_progress), "name": ("name", args.name),
        "name_title": ("name_title", args.name_title), "broll": ("no_broll", not args.no_broll),
        "counters": ("no_counter", not args.no_counter), "shake": ("no_shake", not args.no_shake),
        "transition": ("transition", args.transition), "grade": ("grade", args.grade),
        "end_card": ("end_card", args.end_card), "cta": ("cta", args.cta), "handle": ("handle", args.handle),
        "logo": ("logo", args.logo), "portrait": ("blur", args.blur), "thumbnails": ("no_thumbs", not args.no_thumbs),
        "teaser": ("no_teaser", not args.no_teaser), "font": ("font", args.font or ""),
        "hook_start": ("no_hook_start", not args.no_hook_start),
        "combine": ("no_combine", not args.no_combine),
        "combine_smooth": ("smooth_combine", args.smooth_combine),
        "focus": ("no_focus", not args.no_focus), "landscape": ("no_landscape", not args.no_landscape),
        "context": ("no_context", not args.no_context),
        "denoise": ("denoise", "" if args.denoise == "off" else args.denoise),
        "hook_look": ("hook_look", args.hook_look or ""),
    }


def given_options(parser: argparse.ArgumentParser) -> set[str]:
    """Options you typed on the command line (only these override the preset)."""
    words = sys.argv[1:]
    given = set()
    for action in parser._actions:
        for opt in action.option_strings:
            if any(w == opt or w.startswith(opt + "=") for w in words):
                given.add(action.dest)
    return given


def cmd_shorts(args):
    given = given_options(args.parser)
    overrides = {field: value for field, (dest, value) in cli_values(args).items() if dest in given}
    settings = settings_for(args.preset, overrides)
    print(f"Preset: {PRESETS[args.preset]['label']}" + (f"  (+ aap ki {len(overrides)} options)" if overrides else ""))
    out_dir, _ = make_shorts(Path(args.video), settings)
    print(f"\n✅ Shorts tayyar: {out_dir}")
    print(f"   SEO pack: {out_dir / 'seo_pack.json'}")


# ---------------- Command 3: models ----------------

def cmd_models(args):
    client = make_client()
    print("Models available for your key:\n")
    for name in available_models(client):
        print("  ", name)
    print(f"\nTry karne ki tarteeb: {ranked_models(client)[:3]}")
    print(f"Pehla model: {pick_model(client)}")


# ---------------- Command 4: ping ----------------

def cmd_ping(args):
    ping(args.model)


# ---------------- Command-line setup ----------------

def main():
    parser = argparse.ArgumentParser(description="AI Creative Studio")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("captions", help="generate SRT captions from a video")
    p1.add_argument("video")
    p1.add_argument("--lang", default=None, help="en, ur, hi")
    p1.add_argument("--words", type=int, default=3)
    p1.add_argument("--roman", action="store_true", help="captions in Roman Urdu (Latin letters)")
    p1.set_defaults(func=cmd_captions)

    p2 = sub.add_parser("shorts", help="turn a long video into viral Shorts")
    p2.add_argument("video")
    p2.add_argument("--lang", default=None, help="en, ur, hi")
    p2.add_argument("--clips", type=int, default=5, help="number of Shorts")
    p2.add_argument("--min", type=int, default=20, help="minimum clip length in seconds")
    p2.add_argument("--max", type=int, default=60, help="maximum clip length in seconds")
    p2.add_argument("--gap", type=float, default=0.6, help="cut silences longer than this many seconds")
    p2.add_argument("--no-cut", action="store_true", help="don't cut silences")
    p2.add_argument("--no-track", action="store_true", help="disable face tracking (center crop)")
    p2.add_argument("--reuse", action="store_true", help="re-render the previous AI clips")
    p2.add_argument("--style", default=DEFAULT_STYLE, choices=list(STYLES), help="caption style")
    p2.add_argument("--no-emphasis", action="store_true", help="disable AI key-word highlights")
    p2.add_argument("--no-sfx", action="store_true", help="sound effects band")
    p2.add_argument("--music", default="lofi_chill", help="track name in assets/music, or 'none'")
    p2.add_argument("--music-volume", type=float, default=0.12, help="music kitni oonchi (0.05 - 0.5)")
    p2.add_argument("--no-punch", action="store_true", help="jump cuts par zoom band")
    p2.add_argument("--layout", default="auto", choices=["auto", "single", "split"],
                    help="auto: split during conversations; single: always one person; split: two people stacked")
    p2.add_argument("--no-counter", action="store_true", help="disable the number counter")
    p2.add_argument("--no-shake", action="store_true", help="screen shake band")
    p2.add_argument("--transition", default="flash", choices=["flash", "glitch", "none"],
                    help="camera badalne / B-roll par transition")
    p2.add_argument("--grade", default=DEFAULT_GRADE, choices=list(GRADES), help="color grade")
    p2.add_argument("--end-card", action="store_true", help="add an end screen (CTA + handle + logo)")
    p2.add_argument("--cta", default="Follow for more", help="end screen headline")
    p2.add_argument("--handle", default="", help="your @username on the end screen")
    p2.add_argument("--logo", default=None, help="path to a logo file (PNG/JPG)")
    p2.add_argument("--blur", action="store_true", help="background blur (speaker sharp, background blurred)")
    p2.add_argument("--no-thumbs", action="store_true", help="don't generate thumbnails")
    p2.add_argument("--no-broll",action="store_true", help="B-roll (apna folder / Pexels / Pixabay / Unsplash) band")
    p2.add_argument("--no-progress", action="store_true", help="disable the bottom progress bar")
    p2.add_argument("--name", default="", help="lower third: guest name")
    p2.add_argument("--name-title", default="", help="lower third: title, e.g. 'Founder, Acme Inc.'")
    p2.add_argument("--hook-anim", default=None, choices=HOOK_ANIMS, help="hook animation (default: from the style)")
    p2.add_argument("--hook-look", default=None, choices=list(HOOK_LOOKS),
                    help="hook look: bold / pill / sticker / box (default: from the style)")
    p2.add_argument("--roman", action="store_true", help="captions in Roman Urdu (Latin letters)")
    p2.add_argument("--preset", default=DEFAULT_PRESET, choices=list(PRESETS),
                    help="one-click settings (options you type override it): "
                         + ", ".join(PRESETS))
    p2.add_argument("--no-combine", action="store_true",
                    help="don't join all Shorts into one video (combined.mp4)")
    p2.add_argument("--no-context", action="store_true",
                    help="disable context setup in each Short and bridge lines in the combined video")
    p2.add_argument("--no-focus", action="store_true", help="disable speaker focus (zoom on a distant speaker)")
    p2.add_argument("--no-landscape", action="store_true", help="don't render 16:9 (YouTube) versions")
    p2.add_argument("--smooth-combine", action="store_true",
                    help="crossfade between clips in the combined video (re-encode, +1-2 min)")
    p2.add_argument("--no-hook-start", action="store_true",
                    help="don't start the Short on the guest's spoken hook (old mode: teaser + AI hook)")
    p2.add_argument("--no-teaser", action="store_true", help="disable the teaser (strongest line first)")
    p2.add_argument("--font", default=None, choices=list(FONTS), help="caption Google Font (default: from the style)")
    p2.add_argument("--denoise", default="medium", choices=["off", "light", "medium", "strong"],
                    help="background noise (pankha, AC, traffic) hatao")
    p2.set_defaults(func=cmd_shorts, parser=p2)

    p3 = sub.add_parser("models", help="list available Gemini models")
    p3.set_defaults(func=cmd_models, video=None)

    p4 = sub.add_parser("ping", help="check that Gemini is responding")
    p4.add_argument("--model", default=None, help="test a specific model")
    p4.set_defaults(func=cmd_ping, video=None)

    args = parser.parse_args()
    if args.video and not Path(args.video).exists():
        raise SystemExit(f"File not found: {args.video}")

    t0 = time.time()
    try:
        args.func(args)
    except RuntimeError as e:
        raise SystemExit(f"\n❌ {e}")
    print(f"   Total time: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
