"""Pose and expression evaluation (data in config/poses.yaml and config/expressions.yaml)."""
from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field

import yaml

from .config import CONFIG_DIR

LIMBS = ("arm_l", "arm_r", "leg_l", "leg_r")
SCALARS = ("lean", "head_tilt", "bob")


def _load(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


@dataclass
class PoseState:
    arm_l: list[float] = field(default_factory=lambda: [8.0, -4.0])
    arm_r: list[float] = field(default_factory=lambda: [8.0, -4.0])
    leg_l: list[float] = field(default_factory=lambda: [3.0, 0.0])
    leg_r: list[float] = field(default_factory=lambda: [3.0, 0.0])
    lean: float = 0.0
    head_tilt: float = 0.0
    bob: float = 0.0

    def get(self, key: str) -> float:
        if "." in key:
            limb, i = key.split(".")
            return getattr(self, limb)[int(i)]
        return getattr(self, key)

    def add(self, key: str, v: float) -> None:
        if "." in key:
            limb, i = key.split(".")
            getattr(self, limb)[int(i)] += v
        else:
            setattr(self, key, getattr(self, key) + v)

    def mirrored(self) -> "PoseState":
        return PoseState(list(self.arm_r), list(self.arm_l), list(self.leg_r), list(self.leg_l),
                         -self.lean, -self.head_tilt, self.bob)


@dataclass
class Expression:
    eyes: float = 1.0
    pupil: float = 1.0
    look: tuple[float, float] = (0.0, 0.0)
    brow_angle: float = 0.0
    brow_lift: float = 0.0
    brow_asym: float = 0.0
    mouth: str = "flat"
    extras: list[str] = field(default_factory=list)


class PoseLibrary:
    def __init__(self, overrides: dict | None = None):
        """overrides: per-pose values from a rig variant (rig['pose_overrides'])."""
        from .config import deep_merge
        self.poses = deep_merge(_load("poses.yaml"), overrides or {})
        self.expressions = _load("expressions.yaml")

    def names(self) -> list[str]:
        return list(self.poses)

    def pose(self, name: str, t: float, speaking: float = 0.0) -> PoseState:
        spec = self.poses.get(name) or self.poses["idle"]
        st = PoseState()
        for k in LIMBS:
            if k in spec:
                setattr(st, k, [float(v) for v in spec[k]])
        for k in SCALARS:
            if k in spec:
                setattr(st, k, float(spec[k]))
        keys = spec.get("keys")
        if keys:
            self._apply_keys(st, keys, t)
        for key, (amp, freq, *ph) in (spec.get("anim") or {}).items():
            st.add(key, amp * math.sin(2 * math.pi * (freq * t + (ph[0] if ph else 0))))
        if speaking > 0:
            for key, (amp, freq, *ph) in (spec.get("talk_anim") or {}).items():
                st.add(key, speaking * amp * math.sin(2 * math.pi * (freq * t + (ph[0] if ph else 0))))
        return st

    @staticmethod
    def _apply_keys(st: PoseState, keys: list[dict], t: float) -> None:
        """Per-channel keyframe interpolation with smoothstep easing; holds the last value."""
        channels: dict[str, list[tuple[float, object]]] = {}
        for k in keys:
            for ch, v in k.items():
                if ch != "t":
                    channels.setdefault(ch, []).append((float(k["t"]), v))
        for ch, pts in channels.items():
            pts.sort(key=lambda p: p[0])
            if t <= pts[0][0]:
                val = pts[0][1]
            elif t >= pts[-1][0]:
                val = pts[-1][1]
            else:
                for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
                    if t0 <= t <= t1:
                        e = _ease((t - t0) / max(1e-6, t1 - t0))
                        if isinstance(v0, list):
                            val = [a + (b - a) * e for a, b in zip(v0, v1)]
                        else:
                            val = v0 + (v1 - v0) * e
                        break
            setattr(st, ch, copy.copy(val) if isinstance(val, list) else float(val))

    def expression(self, name: str) -> Expression:
        spec = self.expressions.get(name) or self.expressions["neutral"]
        b = spec.get("brows", {})
        return Expression(
            eyes=float(spec.get("eyes", 1.0)),
            pupil=float(spec.get("pupil", 1.0)),
            look=tuple(spec.get("look", (0.0, 0.0))),
            brow_angle=float(b.get("angle", 0)),
            brow_lift=float(b.get("lift", 0)),
            brow_asym=float(b.get("asym", 0)),
            mouth=spec.get("mouth", "flat"),
            extras=list(spec.get("extras", [])),
        )


class Blinker:
    """Deterministic per-character blink schedule."""

    def __init__(self, seed: str, min_gap: float, max_gap: float, duration: float, length: float = 600):
        rng = random.Random(seed)
        self.duration = duration
        self.times = []
        t = rng.uniform(0.3, max_gap)
        while t < length:
            self.times.append(t)
            t += rng.uniform(min_gap, max_gap)

    def closed(self, t: float) -> float:
        """0 = open, 1 = fully closed."""
        for bt in self.times:
            if bt > t:
                break
            d = t - bt
            if d < self.duration:
                return 1.0 - abs(d / self.duration * 2 - 1)
        return 0.0
