#!/usr/bin/env python3
"""Create a project folder from a story file or text.

    python scripts/new_project.py stories/my_story.md --slug my-video
    python scripts/new_project.py "A cat runs a bakery..." --slug cat-bakery
    python scripts/new_project.py story.md --series zombie-outbreak --episode 13   # -> projects/zombie-outbreak-ep13
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import typer  # noqa: E402

from engine.config import ROOT  # noqa: E402

app = typer.Typer(add_completion=False)


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "video"


@app.command()
def main(story: str = typer.Argument(..., help="path to a story file, or the story text itself"),
         slug: str = typer.Option("", help="project folder name"),
         series: str = typer.Option("", help="series slug (creates/uses series/<slug>/bible.md)"),
         episode: int = typer.Option(0, help="episode number (with --series)")):
    p = Path(story)
    text = p.read_text(encoding="utf-8") if p.exists() else story
    if not slug:
        slug = f"{slugify(series)}-ep{episode}" if series and episode else slugify(p.stem if p.exists() else text[:40])
    proj = ROOT / "projects" / slug
    if (proj / "screenplay.json").exists():
        typer.echo(f"{proj} already has a screenplay.json; not overwriting.", err=True)
        raise typer.Exit(1)
    for d in ("assets/props", "assets/backgrounds", "assets/characters", "assets/sfx", "audio", "previews", "output"):
        (proj / d).mkdir(parents=True, exist_ok=True)
    (proj / "story.md").write_text(text.strip() + "\n", encoding="utf-8")
    if series:
        sdir = ROOT / "series" / slugify(series)
        sdir.mkdir(parents=True, exist_ok=True)
        bible = sdir / "bible.md"
        if not bible.exists():
            bible.write_text(f"# {series} — series bible\n\n## Format\n\n## Characters\n\n## Places\n\n"
                             f"## Rules / running gags\n\n## Episodes\n", encoding="utf-8")
        (ROOT / "library" / "characters" / slugify(series)).mkdir(parents=True, exist_ok=True)
    typer.echo(str(proj.relative_to(ROOT)))


if __name__ == "__main__":
    app()
