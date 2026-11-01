"""Shot transitions: cut, whip (fast blurred slide), flash (white pop), fade (dip to black).

A transition is centred on the cut point between a shot and the next one, so the audio timing
is unchanged; only the picture blends.
"""
from __future__ import annotations

import math

import skia

from .config import hex_to_rgba


def active_transition(shots, t: float, style: dict):
    """Returns (type, progress 0..1, outgoing_shot, incoming_shot) or None."""
    cfg = style.get("transitions", {})
    for i, sh in enumerate(shots[:-1]):
        kind = sh.shot.transition_out
        if kind == "cut":
            continue
        d = cfg.get(kind, {}).get("duration", 0.25)
        b = sh.end
        if b - d / 2 <= t < b + d / 2:
            return kind, (t - (b - d / 2)) / d, sh, shots[i + 1]
    return None


def draw_transition(c: skia.Canvas, kind: str, p: float, out_img: skia.Image, in_img: skia.Image,
                    W: int, H: int, style: dict) -> None:
    cfg = style.get("transitions", {}).get(kind, {})
    if kind == "whip":
        # outgoing and incoming side by side, swept left like a fast pan, with motion blur
        e = 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2
        off = -W * e
        blur = cfg.get("blur", 70) * math.sin(math.pi * p) + 0.1
        paint = skia.Paint(ImageFilter=skia.ImageFilters.Blur(blur, 0.1, skia.TileMode.kClamp))
        c.drawImage(out_img, off, 0, skia.SamplingOptions(), paint)
        c.drawImage(in_img, off + W, 0, skia.SamplingOptions(), paint)
        return
    img = out_img if p < 0.5 else in_img
    c.drawImage(img, 0, 0)
    alpha = 1 - abs(p - 0.5) * 2
    if kind == "flash":
        alpha = alpha ** 0.6
        col = cfg.get("color", "#FFFFFF")
    else:  # fade
        col = cfg.get("color", "#000000")
    c.drawColor(skia.Color(*hex_to_rgba(col, alpha)))
