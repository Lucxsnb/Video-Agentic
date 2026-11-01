"""SVG props: load, fill template params, rasterize (cached) and place/animate them.

An SVG prop lives in library/props/<name>.svg (or projects/<slug>/assets/props/). Root attributes:
  data-height   default height as a fraction of the frame height (scale 1)
  data-anchor   "x,y" pivot/attach point as fractions of the SVG box (e.g. a hammer's grip)
  data-tip      "x,y" optional emission point (flashlight lens), exposed as anchor "<id>.tip"
  data-tip-angle  direction of the tip in degrees (0 = right, 90 = down), before rotation
  data-wrap     max characters per line when splitting the "text" param into {{line1}}..{{lineN}}
Template placeholders: {{key}} or {{key|default}}. {{ow}} = outline width in viewBox units
(keeps a constant pixel outline at any size).
"""
from __future__ import annotations

import math
import re
import textwrap
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

import skia

from .config import ROOT
from .fonts import ensure_fonts

PH = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*(?:\|([^}]*))?\}\}")


@dataclass
class PropMeta:
    path: Path
    vb_w: float
    vb_h: float
    height: float
    anchor: tuple[float, float]
    tip: tuple[float, float] | None
    tip_angle: float
    wrap: int


def _attr(svg: str, name: str) -> str | None:
    m = re.search(rf'{name}="([^"]*)"', svg[: svg.find(">") + 1])
    return m.group(1) if m else None


def _pair(s: str | None, default: tuple[float, float] | None) -> tuple[float, float] | None:
    if not s:
        return default
    a, b = s.split(",")
    return float(a), float(b)


def fill_template(svg: str, params: dict) -> str:
    """Replace {{key}} / {{key|default}} placeholders (values XML-escaped, colors as-is)."""
    params = {k: str(v) for k, v in (params or {}).items()}

    def sub(mt):
        k, d = mt.group(1), mt.group(2)
        v = params.get(k, d if d is not None else "")
        return v if v.startswith("#") else escape(v)

    return PH.sub(sub, svg)


class PropLibrary:
    def __init__(self, style: dict, project_dir: Path | None = None):
        ensure_fonts()
        self.style = style
        self.project_dir = project_dir
        self.outline_px = style.get("props", {}).get("outline_px", style.get("outline_width", 8))
        self._meta: dict[str, PropMeta] = {}
        self._img: dict[tuple, skia.Image] = {}

    def find(self, name: str) -> Path:
        dirs = []
        if self.project_dir:
            dirs.append(self.project_dir / "assets" / "props")
        dirs.append(ROOT / "library" / "props")
        for d in dirs:
            p = d / f"{name}.svg"
            if p.exists():
                return p
        raise FileNotFoundError(f"Prop '{name}' not found in {[str(d) for d in dirs]}")

    def meta(self, name: str) -> PropMeta:
        if name not in self._meta:
            p = self.find(name)
            svg = p.read_text(encoding="utf-8")
            vb = [float(v) for v in (_attr(svg, "viewBox") or "0 0 100 100").replace(",", " ").split()]
            self._meta[name] = PropMeta(
                p, vb[2], vb[3], float(_attr(svg, "data-height") or 0.1),
                _pair(_attr(svg, "data-anchor"), (0.5, 0.5)), _pair(_attr(svg, "data-tip"), None),
                float(_attr(svg, "data-tip-angle") or 0), int(_attr(svg, "data-wrap") or 14))
        return self._meta[name]

    def render_svg(self, name: str, params: dict, px_h: int) -> str:
        m = self.meta(name)
        svg = m.path.read_text(encoding="utf-8")
        params = {k: str(v) for k, v in (params or {}).items()}
        if "text" in params and "{{line1" in svg:
            n = len(set(re.findall(r"\{\{\s*line(\d+)", svg)))
            wrap = m.wrap
            while True:   # widen the wrap until the text fits in the available lines
                lines = []
                for para in params["text"].split("\n"):
                    lines += textwrap.wrap(para, wrap) or [""]
                if len(lines) <= n or wrap > 60:
                    break
                wrap += 2
            lines = lines[:n]
            # auto-fit font size: data-text-width (viewBox units), data-font-size, ~0.62 em per char
            tw = float(_attr(svg, "data-text-width") or m.vb_w * 0.9)
            base = float(_attr(svg, "data-font-size") or 40)
            longest = max((len(x) for x in lines), default=1) or 1
            params.setdefault("fs", f"{min(base, tw / (longest * 0.62)):.1f}")
            pad = (n - len(lines)) // 2           # vertically center the block
            for i in range(n):
                j = i - pad
                params.setdefault(f"line{i + 1}", lines[j] if 0 <= j < len(lines) else "")
        ow = self.outline_px * m.vb_h / max(1, px_h)
        params.setdefault("ow", f"{ow:.2f}")
        params.setdefault("ow2", f"{ow / 2:.2f}")

        def sub(mt):
            k, d = mt.group(1), mt.group(2)
            v = params.get(k, d if d is not None else "")
            return v if k in ("ow", "ow2") or v.startswith("#") else escape(v)

        return PH.sub(sub, svg)

    def image(self, name: str, params: dict, px_h: float) -> skia.Image:
        px = max(8, int(round(px_h / 8)) * 8)         # quantize so animated scale doesn't thrash the cache
        key = (name, tuple(sorted((params or {}).items())), px)
        if key not in self._img:
            self._img[key] = rasterize(self.render_svg(name, params, px), px)
        return self._img[key]


def rasterize(svg: str, px_h: int, px_w: int | None = None) -> skia.Image:
    import cairosvg

    kw = {"output_height": px_h}
    if px_w:
        kw["output_width"] = px_w
    png = cairosvg.svg2png(bytestring=svg.encode("utf-8"), **kw)
    return skia.Image.MakeFromEncoded(skia.Data.MakeWithCopy(png))


# ------------------------------------------------------------------------- animation
def prop_motion(anim: str | None, t: float) -> tuple[float, float, float]:
    """Returns (rotation_deg, dy_fraction_of_height, scale_mul)."""
    if not anim:
        return 0.0, 0.0, 1.0
    if anim == "ring":       # vibrating phone: bursts of shaking
        on = (t % 1.0) < 0.6
        return (7 * math.sin(2 * math.pi * 22 * t) if on else 0.0), 0.0, 1.0
    if anim == "bob":
        return 0.0, 0.08 * math.sin(2 * math.pi * 0.8 * t), 1.0
    if anim == "pulse":
        return 0.0, 0.0, 1 + 0.06 * math.sin(2 * math.pi * 1.6 * t)
    if anim == "swing":
        return 12 * math.sin(2 * math.pi * 0.9 * t), 0.0, 1.0
    if anim == "pop":        # pops in at shot start
        k = min(1.0, t / 0.22)
        s = 1 + 2.70158 * (k - 1) ** 3 + 1.70158 * (k - 1) ** 2 if k < 1 else 1.0
        return 0.0, 0.0, max(0.01, s)
    if anim == "drop":       # falls in from above
        k = min(1.0, t / 0.3)
        return 0.0, -(1 - k) ** 2 * 2.0, 1.0
    return 0.0, 0.0, 1.0
