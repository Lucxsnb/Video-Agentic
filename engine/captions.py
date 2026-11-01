"""Kinetic captions: words pop in one by one in sync with the voice.

Words are grouped into short "pages" (max N words, break on punctuation). A page is
visible from its first word until the next page starts (or end of line + hold).
Highlighted keywords are drawn in the highlight color.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import skia

from .config import hex_to_rgba, resolve_path


@dataclass
class CapWord:
    display: str
    start: float          # absolute seconds
    end: float
    highlight: bool = False


@dataclass
class Page:
    words: list[CapWord]
    start: float
    end: float
    lines: list[list[int]] = field(default_factory=list)  # word indexes per line
    center_y: float | None = None
    italic: bool = False
    tag: tuple[str, str] | None = None     # (label, color) speaker pill


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9']", "", s.lower())


def _ease_out_back(x: float, s: float) -> float:
    x -= 1.0
    return x * x * ((s + 1) * x + s) + 1.0


@lru_cache(maxsize=8)
def _typeface(path: str) -> skia.Typeface:
    tf = skia.Typeface.MakeFromFile(path)
    if tf is None:
        raise FileNotFoundError(f"Cannot load font {path}")
    return tf


def _color(hex_: str, alpha: float = 1.0) -> int:
    return skia.Color(*hex_to_rgba(hex_, alpha))


class CaptionTrack:
    def __init__(self, style: dict, width: int, height: int):
        self.cfg = style["caption"]
        self.pal = style["palette"]
        self.W, self.H = width, height
        self.font = skia.Font(_typeface(str(resolve_path(self.cfg["font"]))), self.cfg["size"])
        self.font.setEdging(skia.Font.Edging.kAntiAlias)
        it = self.cfg.get("dialogue_font")
        self.font_italic = skia.Font(_typeface(str(resolve_path(it))), self.cfg["size"]) if it else self.font
        self.font_italic.setEdging(skia.Font.Edging.kAntiAlias)
        tg = self.cfg.get("tag", {})
        self.tag_font = skia.Font(_typeface(str(resolve_path(tg.get("font", self.cfg["font"])))),
                                  self.cfg["size"] * tg.get("size", 0.36))
        self.pages: list[Page] = []

    # ------------------------------------------------------------------ building
    def display_text(self, token: str) -> str:
        s = token.strip(self.cfg.get("strip_punctuation", ".,;:") + "\"“”()")
        return s.upper() if self.cfg.get("uppercase", True) else s

    def add_line(self, words: list[tuple[str, float, float]], highlight: list[str], line_end: float,
                 shot_end: float, center_y: float | None = None,
                 italic: bool = False, tag: tuple[str, str] | None = None) -> None:
        """words: (token, abs_start, abs_end)."""
        hl = {_key(w) for phrase in highlight for w in phrase.split()}
        cw = [CapWord(self.display_text(t), s, e, _key(t) in hl) for t, s, e in words]
        cw = [w for w in cw if w.display]
        if not cw:
            return
        maxw = self.cfg.get("max_words_per_page", 3)
        brk = set(self.cfg.get("break_after", ".!?;:,"))
        groups, cur = [], []
        for (tok, _, _), w in zip([x for x in words if self.display_text(x[0])], cw):
            cur.append(w)
            if len(cur) >= maxw or (tok and tok[-1] in brk):
                groups.append(cur)
                cur = []
        if cur:
            groups.append(cur)
        hold = self.cfg.get("hold_after", 0.35)
        for i, g in enumerate(groups):
            lead = self.cfg.get("lead", 0.03)
            end = groups[i + 1][0].start - lead if i + 1 < len(groups) else min(line_end + hold, shot_end)
            page = Page(g, g[0].start - lead, end, center_y=center_y, italic=italic, tag=tag)
            page.lines = self._layout(g, self.font_italic if italic else self.font)
            self.pages.append(page)

    def _layout(self, words: list[CapWord], font: skia.Font) -> list[list[int]]:
        maxw = self.cfg.get("max_width", 0.84) * self.W
        gap = self._gap()
        lines, cur, cur_w = [], [], 0.0
        for i, w in enumerate(words):
            ww = font.measureText(w.display)
            add = ww if not cur else gap + ww
            if cur and cur_w + add > maxw:
                lines.append(cur)
                cur, cur_w = [i], ww
            else:
                cur.append(i)
                cur_w += add
        if cur:
            lines.append(cur)
        return lines

    def _gap(self) -> float:
        # visible gap = word_gap; the stroke spills stroke_width/2 out of each word
        return self.cfg.get("word_gap", 0.26) * self.cfg["size"] + self.cfg.get("stroke_width", 16)

    # ----------------------------------------------------------------- rendering
    def page_at(self, t: float) -> Page | None:
        for p in self.pages:
            if p.start <= t < p.end:
                return p
        return None

    def draw(self, c: skia.Canvas, t: float) -> None:
        page = self.page_at(t)
        if not page:
            return
        cfg = self.cfg
        size = cfg["size"]
        gap = self._gap()
        line_h = cfg.get("line_height", 1.12) * size
        lead = cfg.get("lead", 0.03)
        pop = cfg.get("pop", {})
        pop_d = pop.get("duration", 0.14)
        from_s = pop.get("from_scale", 0.5)
        over = pop.get("overshoot", 1.7)
        active_s = cfg.get("active_scale", 1.06)

        font = self.font_italic if page.italic else self.font
        metrics = font.getMetrics()
        cap_h = metrics.fCapHeight or size * 0.7
        block_h = line_h * len(page.lines)
        top = (page.center_y if page.center_y is not None else cfg.get("center_y", 0.7)) * self.H - block_h / 2

        fill = skia.Paint(AntiAlias=True)
        stroke = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style,
                            StrokeWidth=cfg.get("stroke_width", 16),
                            StrokeJoin=skia.Paint.kRound_Join, Color=_color(cfg.get("stroke_color", "#1d1d22")))
        sh = cfg.get("shadow", {})
        shadow = skia.Paint(AntiAlias=True, Style=skia.Paint.kStrokeAndFill_Style,
                            StrokeWidth=cfg.get("stroke_width", 16),
                            StrokeJoin=skia.Paint.kRound_Join,
                            Color=_color(self.pal.get("shadow", "#000000"), sh.get("alpha", 0.55)),
                            MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, max(0.1, sh.get("blur", 8))))

        if page.tag:
            self._draw_tag(c, page, t, top)
        for li, idxs in enumerate(page.lines):
            widths = [font.measureText(page.words[i].display) for i in idxs]
            total = sum(widths) + gap * (len(idxs) - 1)
            x = (self.W - total) / 2
            cy = top + line_h * li + line_h / 2
            for i, ww in zip(idxs, widths):
                w = page.words[i]
                local = t - (w.start - lead)
                if local < 0:
                    x += ww + gap
                    continue
                k = min(1.0, local / pop_d) if pop_d > 0 else 1.0
                s = from_s + (1 - from_s) * _ease_out_back(k, over)
                nxt = page.words[i + 1].start if i + 1 < len(page.words) else w.end
                if w.start <= t < max(nxt, w.end):
                    s *= active_s
                alpha = min(1.0, k * 2.5)
                cx = x + ww / 2
                blob = skia.TextBlob.MakeFromString(w.display, font)
                c.save()
                c.translate(cx, cy)
                c.scale(s, s)
                bx, by = -ww / 2, cap_h / 2
                if alpha < 1.0:
                    c.saveLayerAlpha(None, int(alpha * 255))
                c.drawTextBlob(blob, bx + sh.get("dx", 0), by + sh.get("dy", 10), shadow)
                c.drawTextBlob(blob, bx, by, stroke)
                fill.setColor(_color(self.pal["highlight"] if w.highlight else self.pal["text"]))
                c.drawTextBlob(blob, bx, by, fill)
                if alpha < 1.0:
                    c.restore()
                c.restore()
                x += ww + gap

    def _draw_tag(self, c: skia.Canvas, page: Page, t: float, block_top: float) -> None:
        """Speaker pill centered above the caption block, popping in with the page."""
        label, color = page.tag
        tg = self.cfg.get("tag", {})
        fs = self.tag_font.getSize()
        pad_x, h = fs * 0.7, fs * 1.6
        tw = self.tag_font.measureText(label)
        w = tw + 2 * pad_x
        cx, cy = self.W / 2, block_top - h * 0.5 - fs * tg.get("gap", 0.25)
        k = min(1.0, max(0.0, (t - page.start) / 0.15))
        s = 0.6 + 0.4 * _ease_out_back(k, 1.7)
        c.save()
        c.translate(cx, cy)
        c.scale(s, s)
        rr = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(-w / 2, -h / 2, w, h), h / 2, h / 2)
        c.drawRRect(rr.makeOffset(0, fs * 0.15) if hasattr(rr, "makeOffset") else rr,
                    skia.Paint(AntiAlias=True, Color=_color("#000000", 0.35)))
        c.drawRRect(rr, skia.Paint(AntiAlias=True, Color=_color(color)))
        c.drawRRect(rr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=fs * 0.12,
                                   Color=_color(self.cfg.get("stroke_color", "#1d1d22"))))
        cap = self.tag_font.getMetrics().fCapHeight or fs * 0.7
        c.drawString(label, -tw / 2, cap / 2, self.tag_font,
                     skia.Paint(AntiAlias=True, Color=_color(tg.get("text_color", "#FFFFFF"))))
        c.restore()

    # ----------------------------------------------------------------------- SRT
    def to_srt(self) -> str:
        def ts(x: float) -> str:
            x = max(0.0, x)
            ms = int(round(x * 1000))
            h, ms = divmod(ms, 3_600_000)
            m, ms = divmod(ms, 60_000)
            s, ms = divmod(ms, 1000)
            return f"{h:02}:{m:02}:{s:02},{ms:03}"

        out = []
        for i, p in enumerate(self.pages, 1):
            text = " ".join(w.display for w in p.words)
            out.append(f"{i}\n{ts(p.start)} --> {ts(p.end)}\n{text}\n")
        return "\n".join(out)
