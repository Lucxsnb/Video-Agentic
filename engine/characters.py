"""Rigged flat-vector characters drawn with skia.

Big round head, dot eyes, line mouth, rounded-rect body, tube limbs, thick dark outline,
flat colors with one soft shade. Proportions/colors: config/rig.yaml.
Poses/expressions: engine/poses.py.

Coordinates: the canvas is translated to the actor's feet and scaled by U (character unit),
so body geometry is in U units; the face is drawn in head-radius (R) units.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

import skia
import yaml

from .config import CONFIG_DIR, ROOT, hex_to_rgba
from .poses import Blinker, Expression, PoseState
from .schema import Character


# ----------------------------------------------------------------------------- helpers
def col(hex_: str, alpha: float = 1.0) -> int:
    return skia.Color(*hex_to_rgba(hex_, alpha))


def shade(hex_: str, amount: float) -> str:
    r, g, b, _ = hex_to_rgba(hex_)
    f = 1 - amount
    return "#{:02x}{:02x}{:02x}".format(int(r * f), int(g * f), int(b * f))


def fill(color: int) -> skia.Paint:
    return skia.Paint(AntiAlias=True, Color=color, Style=skia.Paint.kFill_Style)


def stroke(color: int, width: float, cap=skia.Paint.kRound_Cap) -> skia.Paint:
    return skia.Paint(AntiAlias=True, Color=color, Style=skia.Paint.kStroke_Style, StrokeWidth=width,
                      StrokeCap=cap, StrokeJoin=skia.Paint.kRound_Join)


def circle(x: float, y: float, r: float) -> skia.Path:
    p = skia.Path()
    p.addCircle(x, y, r)
    return p


def rect_path(l: float, t: float, r: float, b: float) -> skia.Path:
    p = skia.Path()
    p.addRect(skia.Rect.MakeLTRB(l, t, r, b))
    return p


def op(a: skia.Path, b: skia.Path, kind) -> skia.Path:
    out = skia.Op(a, b, kind)
    return out if out is not None else skia.Path()


INTERSECT = skia.PathOp.kIntersect_PathOp
DIFF = skia.PathOp.kDifference_PathOp
UNION = skia.PathOp.kUnion_PathOp


def direction(side: int, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return side * math.sin(a), math.cos(a)


def load_rig(variant: str | None = None) -> dict:
    """Base rig (config/rig.yaml), optionally deep-merged with config/rigs/<variant>.yaml."""
    from .config import deep_merge
    with open(CONFIG_DIR / "rig.yaml", encoding="utf-8") as f:
        rig = yaml.safe_load(f)
    if variant and variant != "default":
        p = CONFIG_DIR / "rigs" / f"{variant}.yaml"
        if not p.exists():
            raise FileNotFoundError(f"Rig variant not found: {p}")
        with open(p, encoding="utf-8") as f:
            rig = deep_merge(rig, yaml.safe_load(f) or {})
    return rig


def resolve_character(char: Character, project_dir: Path | None = None) -> Character:
    """Merge library/characters/<name>.json (or project assets) under the screenplay's fields."""
    if not char.library:
        return char
    cands = []
    if project_dir:
        cands.append(project_dir / "assets" / "characters" / f"{char.library}.json")
    cands.append(ROOT / "library" / "characters" / f"{char.library}.json")
    for p in cands:
        if p.exists():
            base = json.loads(p.read_text(encoding="utf-8"))
            base.pop("id", None)
            own = char.model_dump(by_alias=True, exclude_unset=True)
            look = {**base.get("look", {}), **own.get("look", {})}
            merged = {**base, **own, "look": look, "id": char.id}
            return Character.model_validate(merged)
    raise FileNotFoundError(f"Character library entry '{char.library}' not found")


@dataclass
class Accessory:
    kind: str
    params: dict = field(default_factory=dict)


def parse_accessories(names: list[str], rig: dict) -> list[Accessory]:
    reg = rig.get("accessories", {})
    out = []
    for n in names:
        if ":" in n:
            kind, *colors = n.split(":")
            spec = dict(reg.get(kind, {"kind": kind}))
            if colors:
                spec["color"] = colors[0]
            if len(colors) > 1:
                spec["stripe"] = colors[1]
        else:
            spec = dict(reg.get(n, {"kind": n}))
        kind = spec.pop("kind", n)
        out.append(Accessory(kind, spec))
    return out


# ------------------------------------------------------------------------------ renderer
class CharacterRenderer:
    HAIR_KINDS = {"hair_short", "hair_spiky", "hair_bun", "hair_long"}
    HAT_KINDS = {"helmet", "cap"}

    def __init__(self, char: Character, style: dict, rig: dict | None = None):
        self.char = char
        self.rig = load_rig(char.rig) if char.rig else (rig or load_rig())
        self.look = char.look
        self.outline_hex = style["palette"]["outline"]
        self.outline_px = style.get("outline_width", 8) * self.rig.get("outline_scale", 1.0)
        self.acc = parse_accessories(self.look.accessories, self.rig)
        kinds = {a.kind for a in self.acc}
        if self.look.hair and not (kinds & (self.HAIR_KINDS | self.HAT_KINDS)):
            self.acc.append(Accessory("hair_short"))
        self.hair_hex = self.look.hair or self.rig["colors"]["default_hair"]
        b = self.rig["blink"]
        self.blinker = Blinker(char.id, b["min_gap"], b["max_gap"], b["duration"])
        self._stubble = [(random.Random(char.id + str(i)).uniform(-0.75, 0.75),
                          random.Random(char.id + "y" + str(i)).uniform(0.3, 0.85)) for i in range(40)]

    def acc_of(self, *kinds: str) -> list[Accessory]:
        return [a for a in self.acc if a.kind in kinds]

    # -------------------------------------------------------------------- main entry
    def draw(self, c: skia.Canvas, x: float, y: float, frame_h: float, scale: float, pose: PoseState,
             expr: Expression, t: float, mouth_open: float = 0.0, speaking: float = 0.0,
             facing: str = "front", flip: bool = False) -> dict[str, tuple[float, float]]:
        rig = self.rig
        U = rig["height"] * frame_h * scale * self.look.height
        ow = self.outline_px / U
        self.ow = ow
        self.O = col(self.outline_hex)
        anchors: dict[str, tuple[float, float]] = {}

        def mark(name: str, px: float, py: float) -> None:
            pt = c.getTotalMatrix().mapXY(px, py)
            anchors[name] = (pt.x(), pt.y())

        c.save()
        c.translate(x, y)
        c.scale(-U if flip else U, U)
        mark("feet", 0, 0)

        # ground shadow (stays on the floor)
        gs = rig["ground_shadow"]
        shrink = max(0.5, 1 - pose.bob * 6)
        c.drawOval(skia.Rect.MakeXYWH(-gs["w"] / 2 * shrink, -gs["h"] / 2, gs["w"] * shrink, gs["h"]),
                   fill(col("#000000", gs["alpha"])))

        c.translate(0, -pose.bob)
        self._legs(c, pose)

        hip_y = rig["leg"]["hip_y"]
        c.save()
        c.translate(0, hip_y)
        c.rotate(pose.lean)
        c.translate(0, -hip_y)
        breath = 1 + rig["breath"]["amp"] * math.sin(2 * math.pi * rig["breath"]["freq"] * t + len(self.char.id))
        top = self._torso(c, breath)
        mark("chest", 0, (top + rig["torso"]["bottom_y"]) / 2)

        # head (tilt around the neck)
        hd = rig["head"]
        R = hd["r"]
        bob = rig["talk"]["head_bob"] * speaking * math.sin(t * 2 * math.pi * 3.1)
        c.save()
        c.translate(0, top)
        c.rotate(pose.head_tilt)
        c.translate(0, hd["cy"] - rig["torso"]["top_y"] - bob)
        mark("head", 0, 0)
        mark("head_top", 0, -R)
        mark("mouth", 0, hd["mouth_y"] * R)
        c.scale(R, R)
        self._head(c, expr, t, mouth_open, facing, R)
        c.restore()

        # arms last: they go over torso and (when raised) next to the head
        for side, name in ((-1, "l"), (1, "r")):
            hand = self._arm(c, side, getattr(pose, f"arm_{name}"))
            mark(f"hand_{name}", *hand)
        c.restore()  # lean
        c.restore()
        return anchors

    # ------------------------------------------------------------------------- body
    def _tube(self, c: skia.Canvas, pts: list[tuple[float, float]], color: str, thick: float) -> None:
        path = skia.Path()
        path.moveTo(*pts[0])
        for p in pts[1:]:
            path.lineTo(*p)
        c.drawPath(path, stroke(self.O, thick + 2 * self.ow))
        c.drawPath(path, stroke(col(color), thick))

    def _legs(self, c: skia.Canvas, pose: PoseState) -> None:
        L = self.rig["leg"]
        F = self.rig["foot"]
        pants = self.look.pants
        shoes = self.look.shoes or F["color"]
        for side, (a, k) in ((-1, pose.leg_l), (1, pose.leg_r)):
            hip = (side * L["hip_dx"] * self.look.build, L["hip_y"])
            dx, dy = direction(side, a)
            knee = (hip[0] + L["thigh"] * dx, hip[1] + L["thigh"] * dy)
            dx2, dy2 = direction(side, a + k)
            foot = (knee[0] + L["shin"] * dx2, knee[1] + L["shin"] * dy2)
            self._tube(c, [hip, knee, foot], pants, L["thickness"])
            r = skia.Rect.MakeXYWH(foot[0] - F["w"] / 2 + side * 0.015, foot[1] - F["h"] * 0.75, F["w"], F["h"])
            c.drawOval(r, fill(col(shoes)))
            c.drawOval(r, stroke(self.O, self.ow))

    def _torso(self, c: skia.Canvas, breath: float) -> float:
        T = self.rig["torso"]
        w = T["w"] * self.look.build
        bottom = T["bottom_y"]
        top = bottom + (T["top_y"] - bottom) * breath
        rr = skia.RRect.MakeRectXY(skia.Rect.MakeLTRB(-w / 2, top, w / 2, bottom), T["radius"], T["radius"])
        body = skia.Path()
        body.addRRect(rr)
        c.drawPath(body, fill(col(self.look.shirt)))
        c.save()
        c.clipPath(body, doAntiAlias=True)
        # pants band
        c.drawRect(skia.Rect.MakeLTRB(-w, bottom - T["pants_h"], w, bottom + 0.1), fill(col(self.look.pants)))
        self._torso_accessories(c, w, top, bottom)
        # soft side shade
        sd = self.rig["shading"]
        sx = sd["side"] * w * 0.22
        c.drawRect(skia.Rect.MakeLTRB(sx, top - 1, w, bottom + 1) if sd["side"] > 0 else
                   skia.Rect.MakeLTRB(-w, top - 1, sx, bottom + 1), fill(col("#000000", sd["amount"])))
        c.restore()
        c.drawLine(-w / 2, bottom - T["pants_h"], w / 2, bottom - T["pants_h"], stroke(self.O, self.ow * 0.6))
        c.drawPath(body, stroke(self.O, self.ow))
        return top

    def _torso_accessories(self, c: skia.Canvas, w: float, top: float, bottom: float) -> None:
        h = bottom - top
        for a in self.acc:
            p = a.params
            if a.kind == "vest_stripes":
                for fy in (0.38, 0.55):
                    y0 = top + h * fy
                    c.drawRect(skia.Rect.MakeLTRB(-w, y0, w, y0 + h * 0.07), fill(col(p.get("color", "#E8E35A"))))
            elif a.kind == "apron":
                ap = skia.RRect.MakeRectXY(skia.Rect.MakeLTRB(-w * 0.36, top + h * 0.18, w * 0.36, bottom + 0.05),
                                           0.02, 0.02)
                c.drawRRect(ap, fill(col(p.get("color", "#2E8B57"))))
                c.drawRRect(ap, stroke(self.O, self.ow * 0.6))
                for s in (-1, 1):
                    c.drawLine(s * w * 0.30, top + h * 0.19, s * w * 0.22, top, stroke(col(p.get("color", "#2E8B57")),
                                                                                         0.022))
                pk = skia.Rect.MakeLTRB(-w * 0.18, top + h * 0.55, w * 0.18, top + h * 0.72)
                c.drawRect(pk, stroke(self.O, self.ow * 0.5))
            elif a.kind == "tie":
                tie = skia.Path()
                tie.moveTo(0, top + 0.005)
                tie.lineTo(0.03, top + 0.04)
                tie.lineTo(0.022, top + h * 0.62)
                tie.lineTo(0, top + h * 0.7)
                tie.lineTo(-0.022, top + h * 0.62)
                tie.lineTo(-0.03, top + 0.04)
                tie.close()
                c.drawPath(tie, fill(col(p.get("color", "#B8322E"))))
                c.drawPath(tie, stroke(self.O, self.ow * 0.6))
            elif a.kind == "name_tag":
                r = skia.Rect.MakeXYWH(-w * 0.36, top + h * 0.2, w * 0.24, h * 0.09)
                c.drawRect(r, fill(col(p.get("color", "#FFFFFF"))))
                c.drawRect(r, stroke(self.O, self.ow * 0.5))
        # collar / neckline
        neck = skia.Path()
        neck.moveTo(-0.045, top)
        neck.lineTo(0, top + 0.05)
        neck.lineTo(0.045, top)
        neck.close()
        c.drawPath(neck, fill(col(self.look.skin)))
        c.drawPath(neck, stroke(self.O, self.ow * 0.6))

    def _arm(self, c: skia.Canvas, side: int, angles: list[float]) -> tuple[float, float]:
        A = self.rig["arm"]
        a, e = angles
        sh = (side * A["shoulder_dx"] * self.look.build, A["shoulder_y"])
        dx, dy = direction(side, a)
        el = (sh[0] + A["upper"] * dx, sh[1] + A["upper"] * dy)
        dx2, dy2 = direction(side, a + e)
        hand = (el[0] + A["lower"] * dx2, el[1] + A["lower"] * dy2)
        thick = A["thickness"]
        sleeve = self.look.shirt
        lower_col = sleeve if self.look.sleeves == "long" else self.look.skin
        # outline of the whole arm first, then the two colored segments (no seam outline)
        path = skia.Path()
        path.moveTo(*sh)
        path.lineTo(*el)
        path.lineTo(*hand)
        c.drawPath(path, stroke(self.O, thick + 2 * self.ow))
        lower = skia.Path()
        lower.moveTo(*el)
        lower.lineTo(*hand)
        c.drawPath(lower, stroke(col(lower_col), thick))
        upper = skia.Path()
        upper.moveTo(*sh)
        upper.lineTo(*el)
        c.drawPath(upper, stroke(col(sleeve), thick * 1.08))
        for b in self.acc_of("bandage"):
            if b.params.get("side", "l") == ("l" if side < 0 else "r"):
                p0 = (el[0] + (hand[0] - el[0]) * 0.3, el[1] + (hand[1] - el[1]) * 0.3)
                p1 = (el[0] + (hand[0] - el[0]) * 0.72, el[1] + (hand[1] - el[1]) * 0.72)
                band = skia.Path()
                band.moveTo(*p0)
                band.lineTo(*p1)
                c.drawPath(band, stroke(self.O, thick * 1.12 + 2 * self.ow * 0.6, skia.Paint.kButt_Cap))
                c.drawPath(band, stroke(col(b.params.get("color", "#F4F1EA")), thick * 1.12, skia.Paint.kButt_Cap))
                mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
                c.drawCircle(mid[0] + 0.006, mid[1], thick * 0.22, fill(col(b.params.get("stain", "#B3262B"), 0.85)))
        c.drawCircle(*hand, A["hand_r"], fill(col(self.look.skin)))
        c.drawCircle(*hand, A["hand_r"], stroke(self.O, self.ow))
        return hand

    # ------------------------------------------------------------------------- head
    def _head(self, c: skia.Canvas, expr: Expression, t: float, mouth_open: float, facing: str,
              R: float) -> None:
        hd = self.rig["head"]
        ow = self.ow / R
        self.owR = ow
        skin = self.look.skin
        fshift = {"left": -0.12, "right": 0.12}.get(facing, 0.0)
        look = (expr.look[0] + {"left": -0.6, "right": 0.6}.get(facing, 0.0), expr.look[1])

        # back layers
        for a in self.acc_of("hair_long"):
            hl = skia.RRect.MakeRectXY(skia.Rect.MakeLTRB(-1.12, -0.7, 1.12, 1.15), 0.5, 0.5)
            c.drawRRect(hl, fill(col(a.params.get("color", self.hair_hex))))
            c.drawRRect(hl, stroke(self.O, ow))
        for a in self.acc_of("hair_bun"):
            c.drawCircle(0, -1.08, 0.32, fill(col(a.params.get("color", self.hair_hex))))
            c.drawCircle(0, -1.08, 0.32, stroke(self.O, ow))
        er = hd["ear_r"] / hd["r"]
        for s in (-1, 1):
            c.drawCircle(s * 0.98, 0.05, er, fill(col(skin)))
            c.drawCircle(s * 0.98, 0.05, er, stroke(self.O, ow))

        head = circle(0, 0, 1.0)
        c.drawPath(head, fill(col(skin)))
        sd = self.rig["shading"]
        crescent = op(head, circle(-sd["side"] * 0.16, -0.1, 1.0), DIFF)
        c.drawPath(crescent, fill(col("#000000", sd["amount"] * 0.8)))

        for a in self.acc_of("beard"):
            beard = op(circle(0, 0, 1.0), rect_path(-2, 0.25, 2, 2), INTERSECT)
            c.drawPath(beard, fill(col(a.params.get("color", self.hair_hex))))
        if "stubble" in expr.extras:
            p = fill(col(self.rig["colors"]["stubble"], 0.35))
            for sx, sy in self._stubble:
                if sx * sx + sy * sy < 0.9:
                    c.drawCircle(sx + fshift, sy, 0.025, p)
        c.drawPath(head, stroke(self.O, ow))

        c.save()
        c.translate(fshift, 0)
        self._eyes(c, expr, look, t)
        for a in self.acc_of("mustache"):
            for s in (-1, 1):
                c.drawOval(skia.Rect.MakeXYWH(s * 0.16 - 0.15, hd["mouth_y"] - 0.2, 0.3, 0.13),
                           fill(col(a.params.get("color", self.hair_hex))))
        self._mouth(c, expr, mouth_open)
        if "blush" in expr.extras:
            for s in (-1, 1):
                c.drawOval(skia.Rect.MakeXYWH(s * 0.55 - 0.13, 0.2, 0.26, 0.11),
                           fill(col(self.rig["colors"]["blush"], 0.5)))
        if "tear" in expr.extras:
            ty = hd["eye_y"] + 0.3 + (t * 0.5) % 0.5
            self._drop(c, -hd["eye_dx"] - 0.05, ty, 0.08, self.rig["colors"]["sweat"])
        c.restore()

        self._hair_and_hats(c)
        c.save()
        c.translate(fshift, 0)
        self._brows(c, expr)  # after hats so expressions stay readable
        c.restore()
        for a in self.acc_of("glasses"):
            gp = stroke(col(a.params.get("color", "#1d1d22")), ow * 0.8)
            for s in (-1, 1):
                c.drawCircle(s * hd["eye_dx"] + fshift, hd["eye_y"], hd["eye_r"] * 1.45, gp)
            c.drawLine(-hd["eye_dx"] + hd["eye_r"] * 1.45 + fshift, hd["eye_y"],
                       hd["eye_dx"] - hd["eye_r"] * 1.45 + fshift, hd["eye_y"], gp)

        if "sweat" in expr.extras:
            sy = -0.45 + (t * 0.35) % 0.45
            self._drop(c, 0.88, sy, 0.13, self.rig["colors"]["sweat"])
        if "shock_lines" in expr.extras:
            p = stroke(self.O, ow * 0.9)
            for ang in (-150, -120, -90, -60, -30):
                a = math.radians(ang)
                c.drawLine(1.3 * math.cos(a), 1.3 * math.sin(a) - 0.1, 1.6 * math.cos(a), 1.6 * math.sin(a) - 0.1, p)
        if "anger" in expr.extras:
            p = stroke(col("#D23B3B"), ow * 0.9)
            cx, cy = 0.62, -0.62
            for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                path = skia.Path()
                path.moveTo(cx + sx * 0.05, cy + sy * 0.15)
                path.quadTo(cx + sx * 0.05, cy + sy * 0.05, cx + sx * 0.15, cy + sy * 0.05)
                c.drawPath(path, p)

    def _drop(self, c: skia.Canvas, x: float, y: float, r: float, color: str) -> None:
        p = skia.Path()
        p.moveTo(x, y - r * 2.0)
        p.quadTo(x + r * 1.1, y - r * 0.4, x + r, y)
        p.arcTo(skia.Rect.MakeXYWH(x - r, y - r, 2 * r, 2 * r), 0, 180, False)
        p.quadTo(x - r * 1.1, y - r * 0.4, x, y - r * 2.0)
        p.close()
        c.drawPath(p, fill(col(color)))
        c.drawPath(p, stroke(self.O, self.owR * 0.6))

    def _eyes(self, c: skia.Canvas, expr: Expression, look: tuple[float, float], t: float) -> None:
        hd = self.rig["head"]
        C = self.rig["colors"]
        blink = self.blinker.closed(t)
        r = hd["eye_r"] * (min(expr.eyes, 1.45) if expr.eyes > 1 else 1.0)
        open_ = min(1.0, expr.eyes) * (1 - blink)
        for s in (-1, 1):
            ex, ey = s * hd["eye_dx"], hd["eye_y"]
            if open_ < 0.15:
                p = skia.Path()
                p.moveTo(ex - r, ey)
                p.quadTo(ex, ey + r * 0.45, ex + r, ey)
                c.drawPath(p, stroke(self.O, self.owR * 0.8))
                continue
            oval = skia.Rect.MakeXYWH(ex - r, ey - r * open_, 2 * r, 2 * r * open_)
            c.drawOval(oval, fill(col(C["eye_white"])))
            c.save()
            c.clipRRect(skia.RRect.MakeOval(oval), doAntiAlias=True)
            pr = hd["pupil_r"] * expr.pupil
            px, py = ex + look[0] * r * 0.45, ey + look[1] * r * 0.45
            c.drawCircle(px, py, pr, fill(col(C["pupil"])))
            c.drawCircle(px + pr * 0.35, py - pr * 0.35, pr * 0.3, fill(col("#FFFFFF")))
            c.restore()
            c.drawOval(oval, stroke(self.O, self.owR * 0.7))

    def _brows(self, c: skia.Canvas, expr: Expression) -> None:
        hd = self.rig["head"]
        L = hd["brow_len"]
        p = stroke(self.O, hd["brow_w"])
        lift_wide = max(0.0, expr.eyes - 1) * hd["eye_r"]
        for s in (-1, 1):
            cx = s * hd["eye_dx"]
            cy = hd["brow_y"] - expr.brow_lift - lift_wide - (expr.brow_asym if s > 0 else 0)
            th = math.radians(-expr.brow_angle if s < 0 else expr.brow_angle)
            dx, dy = math.cos(th) * L / 2, math.sin(th) * L / 2
            c.drawLine(cx - dx, cy - dy, cx + dx, cy + dy, p)

    def _mouth(self, c: skia.Canvas, expr: Expression, mouth_open: float) -> None:
        hd = self.rig["head"]
        C = self.rig["colors"]
        y = hd["mouth_y"]
        mw = hd["mouth_w"]
        ow = self.owR
        line = stroke(self.O, ow * 0.9)
        shape = expr.mouth
        base_open = {"open": 0.85, "o": 0.5}.get(shape, 0.0)
        o = max(mouth_open, base_open)
        if o > self.rig["talk"]["mouth_floor"]:
            w = mw * (0.55 if shape == "o" else (1.1 if shape in ("smile", "grin") else 0.9))
            h = 0.06 + o * 0.36
            oval = skia.Rect.MakeXYWH(-w / 2, y - h * 0.4, w, h)
            c.drawOval(oval, fill(col(C["mouth_inside"])))
            c.save()
            c.clipRRect(skia.RRect.MakeOval(oval), doAntiAlias=True)
            c.drawOval(skia.Rect.MakeXYWH(-w * 0.35, y + h * 0.3, w * 0.7, h * 0.6), fill(col(C["tongue"])))
            if shape in ("smile", "grin", "grit"):
                c.drawRect(skia.Rect.MakeXYWH(-w / 2, y - h * 0.4, w, h * 0.22), fill(col(C["teeth"])))
            c.restore()
            c.drawOval(oval, line)
            return
        p = skia.Path()
        if shape == "smile":
            p.moveTo(-mw / 2, y - 0.04)
            p.quadTo(0, y + 0.2, mw / 2, y - 0.04)
            c.drawPath(p, line)
        elif shape == "grin":
            p.moveTo(-mw * 0.6, y - 0.05)
            p.lineTo(mw * 0.6, y - 0.05)
            p.quadTo(0, y + 0.32, -mw * 0.6, y - 0.05)
            p.close()
            c.drawPath(p, fill(col(C["mouth_inside"])))
            c.save()
            c.clipPath(p, doAntiAlias=True)
            c.drawRect(skia.Rect.MakeLTRB(-mw, y - 0.06, mw, y + 0.04), fill(col(C["teeth"])))
            c.restore()
            c.drawPath(p, line)
        elif shape == "frown":
            p.moveTo(-mw / 2, y + 0.07)
            p.quadTo(0, y - 0.12, mw / 2, y + 0.07)
            c.drawPath(p, line)
        elif shape == "wavy":
            p.moveTo(-mw / 2, y)
            p.cubicTo(-mw / 3, y - 0.08, -mw / 6, y + 0.08, 0, y)
            p.cubicTo(mw / 6, y - 0.08, mw / 3, y + 0.08, mw / 2, y)
            c.drawPath(p, line)
        elif shape == "grit":
            r = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(-mw * 0.55, y - 0.08, mw * 1.1, 0.17), 0.05, 0.05)
            c.drawRRect(r, fill(col(C["teeth"])))
            thin = stroke(self.O, ow * 0.45)
            c.drawLine(-mw * 0.55, y + 0.005, mw * 0.55, y + 0.005, thin)
            for fx in (-0.25, 0, 0.25):
                c.drawLine(fx * mw, y - 0.08, fx * mw, y + 0.09, thin)
            c.drawRRect(r, line)
        elif shape == "smirk":
            p.moveTo(-mw / 2, y + 0.02)
            p.quadTo(mw * 0.15, y + 0.08, mw / 2, y - 0.08)
            c.drawPath(p, line)
        else:  # flat
            p.moveTo(-mw / 2, y)
            p.quadTo(0, y + 0.03, mw / 2, y)
            c.drawPath(p, line)

    def _hair_and_hats(self, c: skia.Canvas) -> None:
        ow = self.owR
        for a in self.acc:
            colr = a.params.get("color", self.hair_hex)
            if a.kind in ("hair_short", "hair_bun", "hair_long", "hair_spiky"):
                edge = skia.Path()
                edge.moveTo(-1.3, -2)
                edge.lineTo(1.3, -2)
                edge.lineTo(1.3, -0.2)
                n = 5
                for i in range(n):
                    x0 = 1.3 - 2.6 * i / n
                    x1 = 1.3 - 2.6 * (i + 1) / n
                    edge.quadTo((x0 + x1) / 2, -0.52 + (0.06 if i % 2 else 0), x1, -0.32)
                edge.close()
                hair = op(circle(0, -0.03, 1.06), edge, INTERSECT)
                if a.kind == "hair_spiky":
                    sp = skia.Path()
                    for i, sx in enumerate((-0.7, -0.35, 0.0, 0.35, 0.7)):
                        top = -1.0 - math.cos(sx * 1.3) * 0.32
                        sp.moveTo(sx - 0.26, -0.7)
                        sp.lineTo(sx + 0.05, top)
                        sp.lineTo(sx + 0.26, -0.7)
                        sp.close()
                    hair = op(hair, sp, UNION)
                c.drawPath(hair, fill(col(colr)))
                c.drawPath(hair, stroke(self.O, ow))
            elif a.kind == "helmet":
                dome = op(circle(0, 0.04, 1.12), rect_path(-2, -2, 2, -0.42), INTERSECT)
                c.drawPath(dome, fill(col(a.params.get("color", "#E9C23A"))))
                if a.params.get("stripe"):
                    c.save()
                    c.clipPath(dome, doAntiAlias=True)
                    c.drawRect(skia.Rect.MakeLTRB(-0.16, -2, 0.16, 0), fill(col(a.params["stripe"])))
                    c.restore()
                c.save()
                c.clipPath(dome, doAntiAlias=True)
                c.drawRect(skia.Rect.MakeLTRB(0.3, -2, 2, 0), fill(col("#000000", 0.12)))
                c.restore()
                c.drawPath(dome, stroke(self.O, ow))
                brim = skia.RRect.MakeRectXY(skia.Rect.MakeLTRB(-1.18, -0.52, 1.18, -0.38), 0.07, 0.07)
                c.drawRRect(brim, fill(col(shade(a.params.get("color", "#E9C23A"), 0.18))))
                c.drawRRect(brim, stroke(self.O, ow))
            elif a.kind == "cap":
                colr = a.params.get("color", "#2E8B57")
                dome = op(circle(0, 0.0, 1.07), rect_path(-2, -2, 2, -0.48), INTERSECT)
                c.drawPath(dome, fill(col(colr)))
                c.save()
                c.clipPath(dome, doAntiAlias=True)
                c.drawRect(skia.Rect.MakeLTRB(0.3, -2, 2, 0), fill(col("#000000", 0.12)))
                c.restore()
                c.drawPath(dome, stroke(self.O, ow))
                c.drawCircle(0, -1.05, 0.08, fill(col(colr)))
                c.drawCircle(0, -1.05, 0.08, stroke(self.O, ow * 0.7))
                bill = skia.Rect.MakeXYWH(-0.95, -0.6, 1.9, 0.24)
                c.drawOval(bill, fill(col(shade(colr, 0.2))))
                c.drawOval(bill, stroke(self.O, ow))
