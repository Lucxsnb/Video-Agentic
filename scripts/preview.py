#!/usr/bin/env python3
"""Render keyframes of every shot + a labeled contact sheet, and flag composition problems.

    python scripts/preview.py projects/<slug>              # 1 keyframe per shot (middle of the line)
    python scripts/preview.py projects/<slug> --per-shot 3 # start, middle, end
    python scripts/preview.py projects/<slug> --shots s02  # only shots whose scene id starts with s02

Writes projects/<slug>/previews/{shot_*.png, contact_sheet.png, report.txt}.
Automatic checks per keyframe: caption / card / poll bars / badge covering a face, a head out of
frame, the speaking character not visible. LOOK at the contact sheet too: the checks don't see
everything (awkward poses, props in the wrong hand, unreadable signs...).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import skia  # noqa: E402
import typer  # noqa: E402

from engine.compose import build_timeline, load_project  # noqa: E402
from engine.renderer import FrameRenderer  # noqa: E402

app = typer.Typer(add_completion=False)


def _circle_rect(cx, cy, r, box) -> float:
    """Fraction-ish overlap measure: >0 if the circle intersects the rect (penetration depth / r)."""
    l, t, rr, b = box
    nx, ny = min(max(cx, l), rr), min(max(cy, t), b)
    d = math.hypot(cx - nx, cy - ny)
    return max(0.0, (r - d) / r)


def keyframe_times(sh, per_shot: int, style: dict | None = None) -> list[float]:
    """Representative times, kept out of the transition windows around the cuts."""
    tcfg = (style or {}).get("transitions", {})
    pad_out = tcfg.get(sh.shot.transition_out, {}).get("duration", 0.0) / 2 + 0.05
    a, b = sh.start + 0.2, sh.end - max(pad_out, 0.1)
    if sh.words:   # middle of the spoken line is the most representative moment
        mid = (sh.words[0][1] + sh.words[-1][2]) / 2
    else:
        mid = (a + b) / 2
    mid = min(max(mid, a), b)
    if per_shot <= 1:
        return [mid]
    return [a, mid, b][:per_shot]


NOTE = "note: "   # informational, doesn't flag the frame


def check_frame(r: FrameRenderer, sh, t: float, W: int, H: int) -> list[str]:
    issues = []
    M = getattr(r, "matrix", None)
    if M is None:
        return issues
    faces = {}
    for actor in sh.shot.actors:
        a = r.anchors.get(actor.id)
        if not a or "head" not in a:
            continue
        hc, ht = M.mapXY(*a["head"]), M.mapXY(*a["head_top"])
        rad = math.hypot(hc.x() - ht.x(), hc.y() - ht.y())
        faces[actor.id] = (hc.x(), hc.y(), rad)
        cam = sh.shot.camera
        focus = {(cam.target or "").split(".")[0], (cam.target_to or "").split(".")[0], sh.speaker}
        targets_face = actor.id in focus and (cam.target or "").partition(".")[2] in ("", "head", "head_top", "mouth")
        if hc.x() + rad < 0 or hc.x() - rad > W or hc.y() + rad < 0 or hc.y() - rad > H:
            if targets_face or actor.id == sh.speaker:
                issues.append(f"{actor.id}: head out of frame")
            else:
                issues.append(f"{NOTE}{actor.id}: head out of frame (ok for an insert / partial framing)")
        elif hc.x() - rad * 0.3 < 0 or hc.x() + rad * 0.3 > W or hc.y() - rad * 0.3 < 0:
            issues.append(f"{NOTE}{actor.id}: head cut by the frame edge (ok for over-the-shoulder)")
    boxes = []
    page = r.captions.page_at(t)
    if page:
        boxes.append(("caption", r.captions.page_box(page)))
    if r.overlays:
        boxes += r.overlays.boxes
    for aid, (x, y, rad) in faces.items():
        for name, box in boxes:
            ov = _circle_rect(x, y, rad * 0.85, box)
            if ov > 0.15:
                issues.append(f"{name} covers {aid}'s face ({ov:.0%})")
    if sh.speaker and sh.speaker != "narrator" and sh.shot.actors and sh.speaker not in faces:
        issues.append(f"{NOTE}speaker '{sh.speaker}' is not on screen (ok for an off-screen voice)")
    return issues


@app.command()
def main(project: Path, per_shot: int = typer.Option(1, help="keyframes per shot: 1 or 3"),
         shots: str = typer.Option("", help="only scenes whose id starts with this"),
         tts: str = typer.Option("", help="TTS backends to try, e.g. 'espeak'"),
         cols: int = typer.Option(6, help="contact sheet columns")):
    sp, style, voices = load_project(project)
    backends = [b for b in tts.split(",") if b] or None
    tl = build_timeline(sp, project, style, voices, backends, log=lambda *a: None)
    r = FrameRenderer(tl, style, project, sp.characters, sp)
    W, H = r.W, r.H
    out = project / "previews"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("shot_*.png"):
        old.unlink()

    frames, report = [], []
    for i, sh in enumerate(tl.shots):
        if shots and not sh.scene_id.startswith(shots):
            continue
        label_base = "ending" if sh.is_ending else f"{sh.scene_id}/{sh.index + 1}"
        for k, t in enumerate(keyframe_times(sh, per_shot, style)):
            path = out / f"shot_{i + 1:02d}_{k}.png"
            r.save_png(t, path)
            issues = check_frame(r, sh, t, W, H)
            text = sh.shot.line.text if sh.shot.line else ""
            frames.append((path, f"#{i + 1} {label_base}  {t:.1f}s", issues))
            report.append(f"#{i + 1:02d} {label_base:12s} t={t:6.2f}s  {sh.speaker or '-':10s} \"{text[:60]}\"")
            report += [f"      {'-' if x.startswith(NOTE) else '!'} {x.removeprefix(NOTE)}" for x in issues]

    # contact sheet
    tw, th = 270, 480
    rows = math.ceil(len(frames) / cols)
    surf = skia.Surface(cols * tw, rows * (th + 56))
    c = surf.getCanvas()
    c.clear(skia.Color(24, 26, 32))
    font = skia.Font(skia.Typeface.MakeFromFile("library/fonts/Montserrat-Bold.ttf"), 18)
    for n, (path, label, issues) in enumerate(frames):
        x, y = (n % cols) * tw, (n // cols) * (th + 56)
        img = skia.Image.open(str(path))
        c.drawImageRect(img, skia.Rect.MakeXYWH(x + 2, y + 2, tw - 4, th - 4),
                        skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear))
        c.drawString(label, x + 8, y + th + 22, font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
        issues = [x for x in issues if not x.startswith(NOTE)]
        if issues:
            c.drawRect(skia.Rect.MakeXYWH(x + 2, y + 2, tw - 4, th - 4),
                       skia.Paint(Style=skia.Paint.kStroke_Style, StrokeWidth=6, Color=skia.Color(230, 60, 60)))
            c.drawString(f"{len(issues)} issue(s)", x + 8, y + th + 46, font,
                         skia.Paint(AntiAlias=True, Color=skia.Color(255, 110, 110)))
    sheet = out / "contact_sheet.png"
    surf.makeImageSnapshot().save(str(sheet), skia.kPNG)
    n_issues = sum(1 for f in frames for x in f[2] if not x.startswith(NOTE))
    header = f"{sp.title}: {len(tl.shots)} shots, {tl.total:.1f}s, {len(frames)} keyframes, {n_issues} issue(s)"
    (out / "report.txt").write_text(header + "\n" + "\n".join(report) + "\n", encoding="utf-8")
    typer.echo(header)
    typer.echo("\n".join(report))
    typer.echo(f"\nContact sheet: {sheet}")


if __name__ == "__main__":
    app()
