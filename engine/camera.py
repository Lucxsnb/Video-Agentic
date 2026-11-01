"""Virtual camera: zoom, pan, follow a target (actor/prop anchor), shake, punch, dutch angle.

The scene is drawn in world space (= frame-sized coordinates). The camera returns a matrix that
maps world -> screen. Zoom is clamped to >= 1 and the view is kept inside the world so no
empty borders ever show.
"""
from __future__ import annotations

import math

import skia

from .schema import Camera


def ease(kind: str, x: float) -> float:
    x = min(1.0, max(0.0, x))
    if kind == "linear":
        return x
    if kind == "in":
        return x * x * x
    if kind == "out":
        return 1 - (1 - x) ** 3
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def _noise(t: float, seed: float) -> float:
    return (math.sin(2 * math.pi * (7.3 * t + seed)) + 0.6 * math.sin(2 * math.pi * (13.1 * t + 2 * seed))
            + 0.3 * math.sin(2 * math.pi * (23.7 * t + 3 * seed))) / 1.9


def resolve_target(name: str | None, anchors: dict[str, dict[str, tuple[float, float]]]
                   ) -> tuple[float, float] | None:
    """'courier' -> head, 'courier.hand_r', 'flashlight1' -> its center, 'flashlight1.tip'."""
    if not name:
        return None
    obj, _, part = name.partition(".")
    a = anchors.get(obj)
    if not a:
        return None
    return a.get(part or ("head" if "head" in a else "center"))


def camera_zoom(cam: Camera, t_local: float, duration: float) -> float:
    k = ease(cam.ease, t_local / max(duration, 1e-6))
    z0 = cam.from_
    z1 = cam.to if cam.to is not None else z0
    if cam.type.startswith("pan_"):
        z0 = z1 = max(z0, z1, 1.0 + cam.pan + 0.02)
    return max(1.0, z0 + (z1 - z0) * k)


def camera_matrix(cam: Camera, t_local: float, duration: float, W: int, H: int,
                  anchors: dict, style: dict) -> skia.Matrix:
    cfg = style.get("camera", {})
    k = ease(cam.ease, t_local / max(duration, 1e-6))
    zoom = camera_zoom(cam, t_local, duration)

    # what we look at (world px) and where it lands on screen
    tgt0 = resolve_target(cam.target, anchors)
    tgt1 = resolve_target(cam.target_to, anchors) or tgt0
    if tgt0:
        fx = tgt0[0] + (tgt1[0] - tgt0[0]) * k
        fy = tgt0[1] + (tgt1[1] - tgt0[1]) * k
        sy = (cam.frame_y if cam.frame_y is not None else cfg.get("target_frame_y", 0.42)) * H
    else:
        fx, fy = cam.focus_x * W, cam.focus_y * H
        sy = (cam.frame_y if cam.frame_y is not None else 0.5) * H
    sx = W / 2
    if cam.type.startswith("pan_"):
        d = cam.pan * (W if cam.type in ("pan_left", "pan_right") else H)
        off = (k - 0.5) * d
        if cam.type == "pan_right":
            fx += off
        elif cam.type == "pan_left":
            fx -= off
        elif cam.type == "pan_down":
            fy += off
        else:
            fy -= off

    # top-left of the view in world coords, clamped inside the world
    vx = min(max(fx - sx / zoom, 0.0), W - W / zoom)
    vy = min(max(fy - sy / zoom, 0.0), H - H / zoom)

    # shake (screen px)
    amp = cam.shake * cfg.get("shake_amp", 0.012) * W
    amp += cam.punch * cfg.get("punch_amp", 0.04) * W * math.exp(-t_local / cfg.get("punch_decay", 0.22))
    dx, dy = amp * _noise(t_local, 0.17), amp * _noise(t_local, 0.61)
    rot = cam.rotate + (cam.shake + cam.punch * math.exp(-t_local / 0.22)) * 0.8 * _noise(t_local, 0.9)

    m = skia.Matrix()
    m.preTranslate(W / 2 + dx, H / 2 + dy)
    if rot:
        m.preRotate(rot)
        m.preScale(1 + abs(math.radians(rot)) * 1.2, 1 + abs(math.radians(rot)) * 1.2)  # hide corners
    m.preTranslate(-W / 2, -H / 2)
    m.preScale(zoom, zoom)
    m.preTranslate(-vx, -vy)
    return m
