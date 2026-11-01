"""Backgrounds (layered flat sets), film grain and vignette.

A background lives in library/backgrounds/<name>.yaml (or projects/<slug>/assets/backgrounds/):

    layers:
      - {rect: [0, 0, 1, 0.64], color: "#3E8E6A", gradient: "#2F6F52"}   # x0,y0,x1,y1 as fractions
      - {rect: [0, 0.36, 1, 0.44], color: "#F2EDE1"}
      - {hline: 0.64, color: "#1d1d22", width: 8}
or as an SVG (library/backgrounds/<name>.svg, viewBox 0 0 1080 1920). SVG wins if both exist.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import skia
import yaml

from .config import ROOT, hex_to_rgba

PLAIN = {"layers": [{"rect": [0, 0, 1, 1], "color": "#3A4A5C", "gradient": "#232C38"}]}


def _color(hex_: str, alpha: float = 1.0) -> int:
    r, g, b, a = hex_to_rgba(hex_, alpha)
    return skia.Color(r, g, b, a)


def find_background(name: str, project_dir: Path | None = None) -> dict:
    """Returns a layer spec dict, or {"svg": Path} for SVG backgrounds."""
    dirs = []
    if project_dir:
        dirs.append(project_dir / "assets" / "backgrounds")
    dirs.append(ROOT / "library" / "backgrounds")
    for d in dirs:
        svg = d / f"{name}.svg"
        if svg.exists():
            return {"svg": svg}
        p = d / f"{name}.yaml"
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8"))
    return PLAIN


def background_image(spec: dict, w: int, h: int, scale: float = 1.0, blur: float = 0.0) -> skia.Image:
    """Render a background at `scale` x frame size (extra pixels for camera close-ups), optionally blurred
    (depth of field; `blur` is in frame pixels)."""
    if "svg" in spec:
        from .fonts import ensure_fonts
        from .props import rasterize
        ensure_fonts()
        img = rasterize(Path(spec["svg"]).read_text(encoding="utf-8"), int(h * scale), int(w * scale))
    else:
        img = render_background(spec, w, h, scale)
    if blur > 0:
        surf = skia.Surface(img.width(), img.height())
        c = surf.getCanvas()
        sigma = blur * scale
        c.drawImage(img, 0, 0, skia.SamplingOptions(),
                    skia.Paint(ImageFilter=skia.ImageFilters.Blur(sigma, sigma, skia.TileMode.kClamp)))
        img = surf.makeImageSnapshot()
    return img


def render_background(spec: dict, w: int, h: int, scale: float = 1.0) -> skia.Image:
    """Render a background spec once into an image `scale` times larger than the frame
    (headroom for camera zoom/pan later)."""
    W, H = int(w * scale), int(h * scale)
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    c.clear(skia.ColorBLACK)
    for layer in spec.get("layers", []):
        if "rect" in layer:
            x0, y0, x1, y1 = layer["rect"]
            r = skia.Rect.MakeLTRB(x0 * W, y0 * H, x1 * W, y1 * H)
            p = skia.Paint(AntiAlias=True)
            if layer.get("gradient"):
                p.setShader(skia.GradientShader.MakeLinear(
                    [skia.Point(0, r.top()), skia.Point(0, r.bottom())],
                    [_color(layer["color"]), _color(layer["gradient"])]))
            else:
                p.setColor(_color(layer["color"], layer.get("alpha", 1.0)))
            c.drawRect(r, p)
        elif "hline" in layer:
            y = layer["hline"] * H
            p = skia.Paint(AntiAlias=True, Color=_color(layer.get("color", "#1d1d22")),
                           StrokeWidth=layer.get("width", 8) * scale, Style=skia.Paint.kStroke_Style)
            c.drawLine(0, y, W, y, p)
    return surf.makeImageSnapshot()


class Atmosphere:
    """Pre-generated grain frames + vignette overlay."""

    def __init__(self, style: dict, w: int, h: int, seed: int = 7):
        self.w, self.h = w, h
        g = style.get("grain", {})
        v = style.get("vignette", {})
        self.grain_on = g.get("enabled", True)
        self.grain_fps = g.get("fps", 12)
        self.grain: list[skia.Image] = []
        if self.grain_on:
            rng = np.random.default_rng(seed)
            amount = float(g.get("amount", 0.07))
            gw, gh = w, h
            for _ in range(int(g.get("variants", 6))):
                n = rng.integers(0, 256, size=(gh, gw), dtype=np.uint8)
                arr = np.empty((gh, gw, 4), dtype=np.uint8)
                arr[..., 0] = arr[..., 1] = arr[..., 2] = n
                arr[..., 3] = int(amount * 255)
                self.grain.append(skia.Image.fromarray(arr, colorType=skia.kRGBA_8888_ColorType))
        self.vignette_on = v.get("enabled", True)
        self.vig_paint = None
        self.vig_img = None
        if self.vignette_on:
            strength = float(v.get("strength", 0.55))
            inner = float(v.get("inner", 0.45))
            radius = float(np.hypot(w, h)) / 2
            self.vig_paint = skia.Paint(Shader=skia.GradientShader.MakeRadial(
                skia.Point(w / 2, h / 2), radius,
                [skia.Color(0, 0, 0, 0), skia.Color(0, 0, 0, 0), skia.Color(0, 0, 0, int(strength * 255))],
                [0.0, inner, 1.0]))

    def draw_vignette(self, c: skia.Canvas) -> None:
        if not self.vig_paint:
            return
        if self.vig_img is None:   # pre-render once (a gradient per frame is slow)
            s = skia.Surface(self.w, self.h)
            s.getCanvas().clear(skia.ColorTRANSPARENT)
            s.getCanvas().drawRect(skia.Rect.MakeWH(self.w, self.h), self.vig_paint)
            self.vig_img = s.makeImageSnapshot()
        c.drawImage(self.vig_img, 0, 0)

    def draw_grain(self, c: skia.Canvas, t: float) -> None:
        if not self.grain:
            return
        img = self.grain[int(t * self.grain_fps) % len(self.grain)]
        p = skia.Paint(BlendMode=skia.BlendMode.kOverlay)
        c.drawImage(img, 0, 0, skia.SamplingOptions(), p)
