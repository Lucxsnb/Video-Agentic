#!/usr/bin/env python3
"""Full pipeline: python scripts/make_video.py projects/<slug>"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import typer  # noqa: E402

from engine.compose import make_video  # noqa: E402

app = typer.Typer(add_completion=False)


@app.command()
def main(
    project: Path = typer.Argument(..., help="Project folder, e.g. projects/my-video"),
    tts: str = typer.Option("", help="Comma-separated TTS backends to try, e.g. 'edge' or 'espeak'"),
    max_seconds: float = typer.Option(0, help="Render only the first N seconds (0 = all)"),
    workers: int = typer.Option(0, help="Parallel render processes (0 = all CPU cores, 1 = off)"),
):
    backends = [b.strip() for b in tts.split(",") if b.strip()] or None
    res = make_video(project, backends=backends, max_seconds=max_seconds or None, workers=workers)
    typer.echo(f"\nDone: {res['video']}  ({res['duration']:.2f}s)\nSRT:  {res['srt']}")


if __name__ == "__main__":
    app()
