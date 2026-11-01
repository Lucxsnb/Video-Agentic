"""Make library/fonts visible to fontconfig so SVG text (cairosvg) can use them."""
from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

from .config import ROOT

_done = False


def ensure_fonts() -> None:
    global _done
    if _done:
        return
    _done = True
    src = ROOT / "library" / "fonts"
    system = platform.system()
    if system == "Darwin":
        dst = Path.home() / "Library" / "Fonts"
    elif system == "Linux":
        dst = Path.home() / ".local" / "share" / "fonts" / "video-agent"
    else:  # Windows: cairosvg uses system fonts; install the .ttf files manually if needed
        return
    dst.mkdir(parents=True, exist_ok=True)
    changed = False
    for f in src.glob("*.ttf"):
        target = dst / f.name
        if not target.exists() or target.stat().st_size != f.stat().st_size:
            shutil.copy(f, target)
            changed = True
    if changed and shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f", str(dst)], capture_output=True)
