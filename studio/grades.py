"""Color grade presets: change the video's mood in one click. Each preset is a chain of FFmpeg filters."""

GRADES = {
    "none": ("None (original)", ""),
    "warm": ("Warm (sunny)",
             "colorbalance=rs=0.06:gs=0.02:bs=-0.06:rm=0.04:bm=-0.04,eq=saturation=1.1:contrast=1.04"),
    "cinematic": ("Cinematic (teal-orange)",
                  "colorbalance=rs=-0.08:bs=0.10:rh=0.08:bh=-0.08,eq=contrast=1.08:saturation=1.05,vignette=PI/5"),
    "moody": ("Moody (dark, muted)",
              "eq=contrast=1.12:brightness=-0.04:saturation=0.75,colorbalance=bs=0.05,vignette=PI/4"),
    "vivid": ("Vivid (strong colors)", "eq=brightness=0.03:contrast=1.05:saturation=1.25"),
    "bw": ("Black & White", "hue=s=0,eq=contrast=1.15"),
}
DEFAULT_GRADE = "none"


def grade_filter(name: str) -> str:
    return GRADES.get(name, GRADES[DEFAULT_GRADE])[1]
