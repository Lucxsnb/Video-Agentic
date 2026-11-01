"""Mood lighting: darken the scene and cut out light pools (spots) and flashlight beams (cones),
then add a soft additive glow. Drawn in world space so it follows the camera."""
from __future__ import annotations

import math

import skia

from .camera import resolve_target
from .config import hex_to_rgba
from .schema import Lighting


def _c(hex_: str, a: float) -> int:
    return skia.Color(*hex_to_rgba(hex_, max(0.0, min(1.0, a))))


def _light_path(kind: str, ox: float, oy: float, r: float, angle: float, spread: float) -> skia.Path:
    p = skia.Path()
    if kind == "spot":
        p.addCircle(ox, oy, r)
        return p
    p.moveTo(ox, oy)
    p.arcTo(skia.Rect.MakeLTRB(ox - r, oy - r, ox + r, oy + r), angle - spread / 2, spread, False)
    p.close()
    return p


class LightingRenderer:
    """Renders the light layers at reduced resolution (they are soft anyway) and composites them
    full-size: ~10x faster than blurring full-resolution paths every frame."""

    def __init__(self, W: int, H: int, style: dict):
        self.W, self.H, self.style = W, H, style
        self.div = int(style.get("lighting", {}).get("downscale", 4))
        w, h = W // self.div, H // self.div
        self.dark = skia.Surface(w, h)
        self.glow = skia.Surface(w, h)

    def draw(self, c: skia.Canvas, lighting: Lighting | None, anchors: dict, t: float) -> None:
        if not lighting or (lighting.darkness <= 0 and not lighting.lights):
            return
        d = self.div
        dst = skia.Rect.MakeWH(self.W, self.H)
        samp = skia.SamplingOptions(skia.FilterMode.kLinear)
        if lighting.darkness > 0:
            dc = self.dark.getCanvas()
            dc.clear(skia.ColorTRANSPARENT)
            dc.save()
            dc.scale(1 / d, 1 / d)
            _draw(dc, lighting, anchors, self.W, self.H, t, self.style, "dark", d)
            dc.restore()
            c.drawImageRect(self.dark.makeImageSnapshot(), dst, samp)
        if lighting.lights:
            gc = self.glow.getCanvas()
            gc.clear(skia.ColorTRANSPARENT)
            gc.save()
            gc.scale(1 / d, 1 / d)
            _draw(gc, lighting, anchors, self.W, self.H, t, self.style, "glow", d)
            gc.restore()
            c.drawImageRect(self.glow.makeImageSnapshot(), dst, samp, skia.Paint(BlendMode=skia.BlendMode.kPlus))


def draw_lighting(c: skia.Canvas, lighting: Lighting | None, anchors: dict, W: int, H: int, t: float,
                  style: dict) -> None:
    """Full-resolution version (used by tests/one-off renders)."""
    if not lighting or (lighting.darkness <= 0 and not lighting.lights):
        return
    _draw(c, lighting, anchors, W, H, t, style, "dark", 1)
    _draw(c, lighting, anchors, W, H, t, style, "glow", 1)


def _draw(c: skia.Canvas, lighting: Lighting, anchors: dict, W: int, H: int, t: float, style: dict,
          which: str, div: int) -> None:
    cfg = style.get("lighting", {})
    dark_hex = lighting.color or cfg.get("color", "#04060B")
    edge = cfg.get("edge_blur", 18)  # world px (mask blur follows the canvas scale)
    resolved = []
    for L in lighting.lights:
        pos = resolve_target(L.source, anchors) if L.source else None
        ox, oy = pos if pos else (L.x * W, L.y * H)
        angle = L.angle
        if angle is None:
            obj = (L.source or "").split(".")[0]
            angle = anchors.get(obj, {}).get("_angle", (0.0, 0.0))[0] if obj else 90.0
        flick = 1.0 - L.flicker * (0.5 + 0.5 * math.sin(t * 37.0) * math.sin(t * 11.3))
        resolved.append((L, ox, oy, L.radius * H, angle, flick))

    # 1) darkness layer with holes
    if which == "dark" and lighting.darkness > 0:
        c.saveLayer(skia.Rect.MakeWH(W, H), None)
        c.drawColor(_c(dark_hex, lighting.darkness))
        for L, ox, oy, r, angle, flick in resolved:
            shader = skia.GradientShader.MakeRadial(
                skia.Point(ox, oy), r,
                [skia.Color(0, 0, 0, int(255 * min(1, L.intensity * flick))),
                 skia.Color(0, 0, 0, int(235 * min(1, L.intensity * flick))), skia.Color(0, 0, 0, 0)],
                [0.0, 0.7 if L.type == "cone" else 0.5, 1.0])
            paint = skia.Paint(AntiAlias=True, Shader=shader, BlendMode=skia.BlendMode.kDstOut,
                               MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, edge))
            c.drawPath(_light_path(L.type, ox, oy, r, angle, L.spread), paint)
        c.restore()

    if which != "glow":
        return
    # 2) glow (additive)
    glow_hex = cfg.get("glow", "#FFE7A8")
    for L, ox, oy, r, angle, flick in resolved:
        col = L.color or glow_hex
        a = cfg.get("glow_alpha", 0.22) * L.intensity * flick
        if L.type == "cone":
            a *= 1.6
        shader = skia.GradientShader.MakeRadial(skia.Point(ox, oy), r, [_c(col, a), _c(col, a * 0.5), _c(col, 0)],
                                                [0.0, 0.6, 1.0])
        paint = skia.Paint(AntiAlias=True, Shader=shader, BlendMode=skia.BlendMode.kPlus,
                           MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, edge))
        c.drawPath(_light_path(L.type, ox, oy, r, angle, L.spread), paint)
        if L.type == "cone":   # bright hotspot at the lens
            c.drawCircle(ox, oy, H * 0.012, skia.Paint(AntiAlias=True, Color=_c("#FFFFFF", 0.8 * flick),
                         MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, H * 0.008)))
