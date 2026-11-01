"""Screen-space overlays (not affected by the camera):

- series badge (top-left): "SERIES · EP 13" + in-story clock ("18:30") or running timer
- text card: centered dark card with a colored title pill (rules, warnings, facts)
- poll bars: numbered options at the bottom, revealed shot by shot (`shot.poll`)
- end card: headline + big badge pill + call to action + all poll options
All sizes/colors in style.yaml `overlays`.
"""
from __future__ import annotations

import re
from functools import lru_cache

import skia

from .config import hex_to_rgba, resolve_path
from .schema import Screenplay


def _col(hex_: str, a: float = 1.0) -> int:
    return skia.Color(*hex_to_rgba(hex_, max(0.0, min(1.0, a))))


@lru_cache(maxsize=16)
def _font(path: str, size: float) -> skia.Font:
    f = skia.Font(skia.Typeface.MakeFromFile(str(resolve_path(path))), size)
    f.setEdging(skia.Font.Edging.kAntiAlias)
    return f


def _ease_back(k: float, s: float = 1.7) -> float:
    k = min(1.0, max(0.0, k)) - 1
    return k * k * ((s + 1) * k + s) + 1


def _key(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower())


def wrap(text: str, font: skia.Font, max_w: float) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        trial = f"{cur} {w}".strip()
        if cur and font.measureText(trial) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


class OverlayRenderer:
    def __init__(self, sp: Screenplay, timeline, style: dict):
        self.sp, self.tl, self.style = sp, timeline, style
        self.cfg = style.get("overlays", {})
        v = style["video"]
        self.W, self.H = v["width"], v["height"]
        self.pal = style["palette"]
        self.O = _col(self.pal["outline"])
        self.options = sp.ending.option_list()
        # when each poll option first appears (for the slide-in animation)
        self.poll_start: dict[int, float] = {}
        for sh in timeline.shots:
            shown = list(range(1, len(self.options) + 1)) if sh.is_ending else sh.shot.poll
            for n in shown:
                self.poll_start.setdefault(n, sh.start)

    # ---------------------------------------------------------------- helpers
    def _text(self, c, s, x, y, font, color, stroke=0.0, align="left", shadow=True):
        w = font.measureText(s)
        if align == "center":
            x -= w / 2
        elif align == "right":
            x -= w
        if shadow:
            c.drawString(s, x, y + font.getSize() * 0.06, font, skia.Paint(
                AntiAlias=True, Color=_col("#000000", 0.5),
                MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, font.getSize() * 0.06)))
        if stroke:
            c.drawString(s, x, y, font, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style,
                                                   StrokeWidth=stroke, StrokeJoin=skia.Paint.kRound_Join,
                                                   Color=self.O))
        c.drawString(s, x, y, font, skia.Paint(AntiAlias=True, Color=_col(color)))
        return w

    # ----------------------------------------------------------------- badge
    def draw_badge(self, c: skia.Canvas, shot, t: float) -> None:
        s = self.sp.series
        b = self.cfg.get("badge", {})
        if not s or not s.badge or not shot.shot.overlays:
            return
        x, y = b.get("x", 0.065) * self.W, b.get("y", 0.07) * self.H
        small = _font(b.get("font", "library/fonts/Montserrat-Black.ttf"), b.get("label_size", 30))
        label = s.name.upper() + (f" · EP {s.episode}" if s.episode is not None else "")
        self._text(c, label, x, y, small, b.get("label_color", self.pal["highlight"]), stroke=6)
        clock = shot.clock
        if not clock and s.show_timer:
            m, sec = divmod(int(t), 60)
            clock = f"{m:02d}:{sec:02d}"
        if clock:
            big = _font(b.get("font", "library/fonts/Montserrat-Black.ttf"), b.get("clock_size", 84))
            self._text(c, clock, x - 2, y + big.getSize() * 0.98, big, b.get("clock_color", "#FFFFFF"), stroke=9)

    # ------------------------------------------------------------------ card
    def draw_card(self, c: skia.Canvas, shot, t: float) -> None:
        card = shot.shot.card
        if not card:
            return
        local = t - shot.start - card.at
        if local < 0:
            return
        k = cfg_k = min(1.0, local / 0.22)
        cc = self.cfg.get("card", {})
        title_f = _font(cc.get("title_font", "library/fonts/Montserrat-Black.ttf"), cc.get("title_size", 40))
        body_f = _font(cc.get("font", "library/fonts/Montserrat-Black.ttf"), cc.get("size", 66))
        maxw = self.W * cc.get("width", 0.8)
        pad = cc.get("padding", 44)
        lines = wrap(card.text.upper(), body_f, maxw - 2 * pad)
        lh = body_f.getSize() * 1.12
        th = title_f.getSize() * 1.7 if card.title else 0
        h = pad * 2 + th + (pad * 0.5 if card.title else 0) + lh * len(lines)
        cx, cy = self.W / 2, card.y * self.H
        s = 0.7 + 0.3 * _ease_back(cfg_k)
        c.save()
        c.translate(cx, cy)
        c.scale(s, s)
        if k < 1:
            c.saveLayerAlpha(None, int(255 * min(1.0, k * 2)))
        r = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(-maxw / 2, -h / 2, maxw, h), 30, 30)
        c.drawRRect(r, skia.Paint(AntiAlias=True, Color=_col(cc.get("bg", "#121418"), cc.get("bg_alpha", 0.93))))
        c.drawRRect(r, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4,
                                  Color=_col("#FFFFFF", 0.12)))
        y = -h / 2 + pad
        if card.title:
            tw = title_f.measureText(card.title.upper())
            pw, ph = tw + title_f.getSize() * 1.2, th
            pr = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(-pw / 2, y, pw, ph), ph / 2, ph / 2)
            c.drawRRect(pr, skia.Paint(AntiAlias=True, Color=_col(card.color or cc.get("title_bg", "#D93A3A"))))
            cap = title_f.getMetrics().fCapHeight
            self._text(c, card.title.upper(), 0, y + ph / 2 + cap / 2, title_f, "#FFFFFF", align="center",
                       shadow=False)
            y += ph + pad * 0.5
        hl = {_key(w) for p in card.highlight for w in p.split()}
        cap = body_f.getMetrics().fCapHeight
        for line in lines:
            words = line.split()
            gap = body_f.measureText(" ")
            total = sum(body_f.measureText(w) for w in words) + gap * (len(words) - 1)
            x = -total / 2
            for w in words:
                color = self.pal["highlight"] if _key(w) in hl else "#FFFFFF"
                x += self._text(c, w, x, y + lh / 2 + cap / 2, body_f, color, shadow=False) + gap
            y += lh
        if k < 1:
            c.restore()
        c.restore()

    # ------------------------------------------------------------------ poll
    def draw_poll(self, c: skia.Canvas, shot, t: float) -> None:
        if not self.options:
            return
        shown = list(range(1, len(self.options) + 1)) if shot.is_ending else shot.shot.poll
        if not shown:
            return
        pc = self.cfg.get("poll", {})
        f = _font(pc.get("font", "library/fonts/Montserrat-Black.ttf"), pc.get("size", 38))
        fd = _font(pc.get("detail_font", "library/fonts/Montserrat-Bold.ttf"), pc.get("detail_size", 24))
        bw, bh = self.W * pc.get("width", 0.84), pc.get("height", 112)
        gap = pc.get("gap", 22)
        n = len(self.options)
        y0 = pc.get("bottom", 0.905) * self.H - n * bh - (n - 1) * gap
        active = max(shown)
        for i, opt in enumerate(self.options, 1):
            if i not in shown:
                continue
            k = min(1.0, (t - self.poll_start.get(i, shot.start)) / 0.28)
            x = (self.W - bw) / 2 - (1 - _ease_back(k, 1.3)) * self.W * 1.1
            y = y0 + (i - 1) * (bh + gap)
            is_active = i == active and not shot.is_ending
            r = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, bw, bh), 22, 22)
            c.drawRRect(r.makeOffset(0, 8), skia.Paint(AntiAlias=True, Color=_col("#000000", 0.35)))
            bg = pc.get("active_bg", self.pal["highlight"]) if is_active else pc.get("bg", "#F6F3EC")
            c.drawRRect(r, skia.Paint(AntiAlias=True, Color=_col(bg)))
            c.drawRRect(r, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=6, Color=self.O))
            # number bubble
            rad = bh * 0.32
            bx, by = x + bh * 0.5, y + bh / 2
            c.drawCircle(bx, by, rad, skia.Paint(AntiAlias=True, Color=self.O))
            cap = f.getMetrics().fCapHeight
            self._text(c, str(i), bx, by + cap / 2, f, "#FFFFFF", align="center", shadow=False)
            tx = x + bh * 0.95
            txt_col = pc.get("text_color", "#1d1d22")
            if opt.detail:
                self._text(c, opt.text.upper(), tx, y + bh * 0.47, f, txt_col, shadow=False)
                self._text(c, opt.detail, tx, y + bh * 0.80, fd, pc.get("detail_color", "#6B6258"), shadow=False)
            else:
                self._text(c, opt.text.upper(), tx, by + cap / 2, f, txt_col, shadow=False)

    # ------------------------------------------------------------- end card
    def draw_end(self, c: skia.Canvas, shot, t: float) -> None:
        if not shot.is_ending:
            return
        e = self.sp.ending
        ec = self.cfg.get("end", {})
        local = t - shot.start
        k = min(1.0, local / 0.3)
        headline = e.headline or ("THE MAJORITY DECIDES" if e.type == "poll" else None)
        y = ec.get("y", 0.2) * self.H
        if headline:
            f = _font(ec.get("font", "library/fonts/Montserrat-Black.ttf"), ec.get("headline_size", 74))
            for line in wrap(headline.upper(), f, self.W * 0.8):
                self._text(c, line, self.W / 2, y, f, "#FFFFFF", stroke=10, align="center")
                y += f.getSize() * 1.08
        if e.badge:
            f = _font(ec.get("font", "library/fonts/Montserrat-Black.ttf"), ec.get("badge_size", 92))
            tw = f.measureText(e.badge.upper())
            pw, ph = tw + f.getSize() * 1.0, f.getSize() * 1.45
            s = 0.6 + 0.4 * _ease_back(min(1.0, max(0.0, (local - 0.15) / 0.3)))
            c.save()
            c.translate(self.W / 2, y + ph / 2)
            c.scale(s, s)
            r = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(-pw / 2, -ph / 2, pw, ph), ph / 2, ph / 2)
            c.drawRRect(r, skia.Paint(AntiAlias=True, Color=_col(ec.get("badge_bg", self.pal["highlight"]))))
            c.drawRRect(r, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=8,
                                      Color=_col("#FFFFFF")))
            cap = f.getMetrics().fCapHeight
            self._text(c, e.badge.upper(), 0, cap / 2, f, "#FFFFFF", align="center", stroke=0)
            c.restore()
            y += ph + 30
        if e.cta:
            f = _font(ec.get("font", "library/fonts/Montserrat-Black.ttf"), ec.get("cta_size", 40))
            self._text(c, e.cta.upper(), self.W / 2, y + f.getSize(), f, self.pal["highlight"], stroke=7,
                       align="center")
        _ = k

    # ------------------------------------------------------------------ all
    def draw(self, c: skia.Canvas, shot, t: float) -> None:
        self.draw_badge(c, shot, t)
        self.draw_card(c, shot, t)
        self.draw_end(c, shot, t)
        self.draw_poll(c, shot, t)
