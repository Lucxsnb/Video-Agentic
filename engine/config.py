"""Load YAML configuration (style + preset + voices)."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_style(preset: str | None = None, overrides: dict | None = None) -> dict:
    style = _load(CONFIG_DIR / "style.yaml")
    if preset:
        p = CONFIG_DIR / "presets" / f"{preset}.yaml"
        if not p.exists():
            raise FileNotFoundError(f"Preset not found: {p}")
        style = deep_merge(style, _load(p))
    if overrides:
        style = deep_merge(style, overrides)
    return style


def load_voices() -> dict:
    return _load(CONFIG_DIR / "voices.yaml")


def resolve_path(p: str | Path) -> Path:
    """Paths in config are relative to the repo root."""
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def hex_to_rgba(color: str, alpha: float = 1.0) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    a = int(c[6:8], 16) if len(c) == 8 else round(alpha * 255)
    return r, g, b, a


def get(d: dict, dotted: str, default: Any = None) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur
