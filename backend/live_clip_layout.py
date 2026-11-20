"""Deterministic 9:16 live layout: enlarged streamer cam above gameplay.

Source facecam anchors are explicit (no claim of universal camera detection).
Original licensed source is used twice from the same input; SFX and loudness
are handled by the existing render. No camera footage is synthesized.
"""
from __future__ import annotations

from dataclasses import dataclass

ANCHORS = {
    # Includes inset overlays such as the Patife webcam in left gameplay corner.
    "bottom_left": (0.0, 0.39, 0.19, 0.36),
    "top_left": (0.0, 0.02, 0.22, 0.36),
    "bottom_right": (0.78, 0.60, 0.22, 0.36),
    "top_right": (0.78, 0.02, 0.22, 0.36),
}
DEFAULT_ANCHOR = "bottom_left"
LAYOUT_NAME = "streamer_top_gameplay_bottom"
FRAME_RATE = 30


def validate_anchor(anchor: str) -> str:
    if anchor not in ANCHORS:
        raise ValueError("Posição da webcam inválida.")
    return anchor


def camera_rect(anchor: str):
    return ANCHORS[validate_anchor(anchor)]


def graph(subtitle_path: str, anchor: str = DEFAULT_ANCHOR) -> str:
    """FFmpeg filter_complex with a real webcam extraction on top and game below.

    At top: 1000x655 (x40,y130). At bottom: 1000x770 (x40,y830).
    Kinetic captions occupy their own band around y1710. The in-stream
    webcam is excluded from the bottom gameplay crop for side corners.
    """
    x,y,w,h=camera_rect(anchor)
    image_crop=(f"crop=iw*{w:.4f}:ih*{h:.4f}:iw*{x:.4f}:ih*{y:.4f}")
    game_x=0.20 if x < .5 else 0.0
    game_width=0.80
    game_crop=f"crop=iw*{game_width:.4f}:ih:iw*{game_x:.4f}:0"
    safe_subtitle=subtitle_path.replace("\\", "\\\\").replace(":", r"\:").replace("'",r"\'")
    return (
        "[0:v]split=2[camerain][gamein];"
        f"[camerain]{image_crop},"
        "scale=1000:655:force_original_aspect_ratio=increase,"
        "crop=1000:655,unsharp=5:5:0.40[camera];"
        f"[gamein]{game_crop},"
        "scale=1000:770:force_original_aspect_ratio=increase,"
        "crop=1000:770[game];"
        "color=c=0x0c1524:s=1080x1920:r=30[canvas];"
        "[canvas][camera]overlay=x=40:y=130:shortest=1[withcamera];"
        "[withcamera][game]overlay=x=40:y=830:shortest=1,"
        "drawbox=x=35:y=125:w=1010:h=665:color=0x35d5d9:t=5,"
        "drawbox=x=35:y=825:w=1010:h=780:color=0x35d5d9:t=5,"
        "drawbox=x=0:y=1620:w=1080:h=230:color=0x101b2b@0.9:t=fill,"
        f"ass={safe_subtitle}[v];"
        "[0:a]highpass=f=80,acompressor=threshold=0.12:ratio=2.2:"
        "attack=12:release=110,loudnorm=I=-14:TP=-1.5:LRA=9[a]"
    )
