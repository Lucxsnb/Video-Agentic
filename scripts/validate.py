#!/usr/bin/env python3
"""Check a project before rendering: schema, assets, references, voices, text, duration.

    python scripts/validate.py projects/<slug>          # static checks (fast, no TTS)
    python scripts/validate.py projects/<slug> --audio  # also synthesize (cached) and check timing/sync

Exit code 1 if there are errors. Warnings don't block rendering.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import typer  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from engine.backgrounds import PLAIN, find_background  # noqa: E402
from engine.config import CONFIG_DIR, load_style, load_voices  # noqa: E402
from engine.music import find_music, load_moods  # noqa: E402
from engine.poses import PoseLibrary  # noqa: E402
from engine.schema import Screenplay  # noqa: E402
from engine.sfx import GENERATORS, find_file  # noqa: E402

app = typer.Typer(add_completion=False)
ACTOR_ANCHORS = {"head", "head_top", "mouth", "chest", "feet", "hand_l", "hand_r"}
PROP_ANCHORS = {"center", "tip"}


class Report:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, m: str):
        self.errors.append(m)

    def warn(self, m: str):
        self.warnings.append(m)


def check_ref(ref: str | None, actors: set[str], props: dict[str, set[str]], where: str, rep: Report,
              what: str) -> None:
    if not ref:
        return
    obj, _, part = ref.partition(".")
    if obj in actors:
        if part and part not in ACTOR_ANCHORS:
            rep.err(f"{where}: {what} '{ref}': unknown actor anchor '{part}' (use {sorted(ACTOR_ANCHORS)})")
    elif obj in props:
        if part and part not in props[obj]:
            rep.err(f"{where}: {what} '{ref}': prop '{obj}' has no anchor '{part}' (has {sorted(props[obj])})")
    else:
        rep.err(f"{where}: {what} '{ref}' is not an actor or prop id in this shot")


def validate(project: Path, audio: bool = False, backends: list[str] | None = None) -> Report:
    rep = Report()
    path = project / "screenplay.json"
    if not path.exists():
        rep.err(f"{path} not found")
        return rep
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        sp = Screenplay.model_validate(raw)
    except json.JSONDecodeError as e:
        rep.err(f"screenplay.json is not valid JSON: {e}")
        return rep
    except ValidationError as e:
        for er in e.errors():
            rep.err(f"schema: {'/'.join(str(x) for x in er['loc'])}: {er['msg']}")
        return rep

    # style / preset
    try:
        style = load_style(sp.style_preset, sp.style_overrides)
    except FileNotFoundError as e:
        rep.err(str(e))
        return rep

    # characters
    from engine.characters import load_rig, parse_accessories, resolve_character
    chars = {}
    for ch in sp.characters:
        try:
            chars[ch.id] = resolve_character(ch, project)
        except FileNotFoundError as e:
            rep.err(f"character {ch.id}: {e}")
    rig = load_rig(style.get("character", {}).get("rig"))
    known_acc = set(rig.get("accessories", {})) | {"helmet", "cap", "hair_short", "hair_spiky", "hair_bun",
                                                   "hair_long", "glasses", "mustache", "beard", "apron", "tie",
                                                   "vest_stripes", "name_tag", "bandage"}
    voices = load_voices()
    catalog = voices.get("catalog", {})
    for cid, ch in chars.items():
        if ch.rig and not (CONFIG_DIR / "rigs" / f"{ch.rig}.yaml").exists():
            rep.err(f"character {cid}: rig variant '{ch.rig}' not found in config/rigs/")
        for a in parse_accessories(ch.look.accessories, rig):
            if a.kind not in known_acc:
                rep.err(f"character {cid}: unknown accessory '{a.kind}'")
        if ch.voice and ch.voice not in catalog:
            rep.warn(f"character {cid}: voice '{ch.voice}' not in config/voices.yaml catalog "
                     f"(fine for edge-tts if the name is right; offline fallback will guess)")
        if not ch.label:
            rep.warn(f"character {cid}: no label (speaker tag will show '{cid.upper()}')")
    voice_count: dict[str, list[str]] = {}
    for cid, ch in chars.items():
        if ch.voice:
            voice_count.setdefault(ch.voice, []).append(cid)
    for v, ids in voice_count.items():
        if len(ids) > 1:
            rep.warn(f"characters {ids} share the voice {v}")

    poses = PoseLibrary(rig.get("pose_overrides"))
    n_opts = len(sp.ending.option_list())
    words_total = 0
    for sc in sp.scenes:
        bg = find_background(sc.background, project)
        if bg is PLAIN and sc.background != "plain":
            rep.err(f"scene {sc.id}: background '{sc.background}' not found (library/backgrounds or assets)")
        for i, sh in enumerate(sc.shots):
            where = f"{sc.id}/shot{i + 1}"
            if sh.background and find_background(sh.background, project) is PLAIN and sh.background != "plain":
                rep.err(f"{where}: background '{sh.background}' not found")
            actors = {a.id for a in sh.actors}
            for a in sh.actors:
                if a.pose not in poses.poses:
                    rep.err(f"{where}: actor {a.id}: unknown pose '{a.pose}' (have {sorted(poses.poses)})")
                if a.expression not in poses.expressions:
                    rep.err(f"{where}: actor {a.id}: unknown expression '{a.expression}'")
                if not (-0.2 <= a.x <= 1.2):
                    rep.warn(f"{where}: actor {a.id} x={a.x} is far outside the frame")
            props: dict[str, set[str]] = {}
            from engine.props import PropLibrary
            plib = PropLibrary(style, project)
            for pl in sh.props:
                try:
                    m = plib.meta(pl.svg)
                    props[pl.id or pl.svg] = {"center"} | ({"tip"} if m.tip else set())
                except FileNotFoundError:
                    rep.err(f"{where}: prop svg '{pl.svg}' not found (library/props or assets/props)")
                    props[pl.id or pl.svg] = PROP_ANCHORS
                if pl.attach_to:
                    obj = pl.attach_to.split(".")[0]
                    if obj not in actors:
                        rep.err(f"{where}: prop {pl.svg} attached to '{pl.attach_to}' but '{obj}' is not in the shot")
                    else:
                        check_ref(pl.attach_to, actors, {}, where, rep, "attach_to")
            check_ref(sh.camera.target, actors, props, where, rep, "camera target")
            check_ref(sh.camera.target_to, actors, props, where, rep, "camera target_to")
            for lgt in ((sh.lighting or sc.lighting).lights if (sh.lighting or sc.lighting) else []):
                check_ref(lgt.source, actors, props, where, rep, "light source")
            for n in sh.poll:
                if not 1 <= n <= n_opts:
                    rep.err(f"{where}: poll option {n} does not exist (ending has {n_opts} options)")
            for c in sh.sfx:
                if c.name not in GENERATORS and not find_file(c.name, project):
                    rep.err(f"{where}: sound effect '{c.name}' not found (built-in: {sorted(GENERATORS)})")
            if sh.line:
                ws = sh.line.text.split()
                words_total += len(ws)
                if len(ws) > 22:
                    rep.warn(f"{where}: line has {len(ws)} words; split it (1 idea per shot keeps the pace)")
                if re.search(r"[^\x00-\x7F’‘“”—–…]", sh.line.text):
                    rep.warn(f"{where}: non-English characters in line: \"{sh.line.text}\"")
                low = {re.sub(r"[^a-z0-9']", "", w.lower()) for w in ws}
                for h in sh.line.highlight:
                    for hw in h.split():
                        if re.sub(r"[^a-z0-9']", "", hw.lower()) not in low:
                            rep.warn(f"{where}: highlight '{hw}' is not in the line")
                if sh.line.speaker != "narrator" and sh.actors and sh.line.speaker not in actors:
                    rep.warn(f"{where}: speaker '{sh.line.speaker}' is not in the shot (off-screen voice)")
            elif not sh.duration:
                rep.warn(f"{where}: no line and no duration (uses timing.default_shot)")
    if sp.ending.type == "poll" and n_opts < 2:
        rep.err("ending: a poll needs at least 2 options")
    if sp.music.file and not find_music(None, sp.music.file, project):
        rep.err(f"music file '{sp.music.file}' not found")
    if sp.music.mood and sp.music.mood not in load_moods() and not find_music(sp.music.mood, None, project):
        rep.err(f"music mood '{sp.music.mood}' not in config/music.yaml and no file in library/music/")
    first = sp.scenes[0].shots[0].line if sp.scenes and sp.scenes[0].shots else None
    if not first:
        rep.warn("the first shot has no line: the hook should start in the first 2 seconds")

    lo, hi = style.get("timing", {}).get("target_duration", [45, 75])
    est = words_total / 2.6   # ~156 wpm incl. pauses
    if not audio:
        rep.warn(f"estimated duration ~{est:.0f}s from {words_total} words (target {lo}-{hi}s); "
                 f"run with --audio for exact timing")
    else:
        from engine.compose import build_timeline, load_project
        sp2, style2, voices2 = load_project(project)
        tl = build_timeline(sp2, project, style2, voices2, backends, log=lambda *a: None)
        if not lo <= tl.total <= hi:
            rep.warn(f"duration {tl.total:.1f}s is outside the target {lo}-{hi}s")
        first_word = next((s.words[0][1] for s in tl.shots if s.words), None)
        if first_word is not None and first_word > 2.0:
            rep.warn(f"first word starts at {first_word:.1f}s (hook should land in the first 2s)")
        for s in tl.shots:
            for (w, a, b), nxt in zip(s.words, s.words[1:] + [None]):
                if b < a or (nxt and nxt[1] + 1e-3 < a):
                    rep.err(f"{s.scene_id}/shot{s.index + 1}: word timestamps out of order at '{w}'")
                    break
            if s.words and s.words[-1][2] > s.end + 1e-3:
                rep.err(f"{s.scene_id}/shot{s.index + 1}: speech runs past the end of the shot")
            if s.duration > 6:
                rep.warn(f"{s.scene_id}/shot{s.index + 1}: {s.duration:.1f}s is long for the format (1-4s per cut)")
        print(f"duration {tl.total:.1f}s, {len(tl.shots)} shots")
    return rep


@app.command()
def main(project: Path, audio: bool = typer.Option(False, help="synthesize (cached) and check timing"),
         tts: str = typer.Option("", help="TTS backends, e.g. 'espeak'")):
    rep = validate(project, audio, [b for b in tts.split(",") if b] or None)
    for e in rep.errors:
        typer.echo(f"ERROR   {e}")
    for w in rep.warnings:
        typer.echo(f"warning {w}")
    typer.echo(f"\n{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    raise typer.Exit(1 if rep.errors else 0)


if __name__ == "__main__":
    app()
