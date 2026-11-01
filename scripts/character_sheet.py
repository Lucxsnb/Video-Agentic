#!/usr/bin/env python3
"""Render a contact sheet of a character's poses and expressions.

python scripts/character_sheet.py delivery_guy --out sheet.png
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import skia  # noqa: E402
import typer  # noqa: E402

from engine.characters import CharacterRenderer, resolve_character  # noqa: E402
from engine.config import load_style  # noqa: E402
from engine.poses import PoseLibrary  # noqa: E402
from engine.schema import Character  # noqa: E402

app = typer.Typer(add_completion=False)


@app.command()
def main(characters: list[str] = typer.Argument(..., help="library character names"),
         out: Path = typer.Option(Path("character_sheet.png")),
         mode: str = typer.Option("poses", help="poses | expressions"),
         t: float = typer.Option(0.6, help="time inside the pose (s)"),
         rig: str = typer.Option("default", help="body variant: default | tall")):
    style = load_style("miniseries")
    from engine.characters import load_rig
    rig_cfg = load_rig(rig)
    lib = PoseLibrary(rig_cfg.get("pose_overrides"))
    items = lib.names() if mode == "poses" else list(lib.expressions)
    cell_w, cell_h = 360, 620
    cols = len(items)
    W, H = cell_w * cols, cell_h * len(characters)
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    c.clear(skia.Color(78, 155, 116))
    font = skia.Font(skia.Typeface.MakeFromFile("library/fonts/Montserrat-Bold.ttf"), 26)
    for row, name in enumerate(characters):
        ch = resolve_character(Character(id=name, library=name))
        r = CharacterRenderer(ch, style, rig_cfg)
        for i, item in enumerate(items):
            pose = lib.pose(item if mode == "poses" else "idle", t)
            expr = lib.expression(item if mode == "expressions" else "neutral")
            r.draw(c, cell_w * i + cell_w / 2, cell_h * row + cell_h - 40, 1920, 0.55, pose, expr, t,
                   mouth_open=0.0)
            c.drawString(item, cell_w * i + 12, cell_h * row + 34, font, skia.Paint(Color=skia.ColorWHITE))
    surf.makeImageSnapshot().save(str(out), skia.kPNG)
    typer.echo(out)


if __name__ == "__main__":
    app()
