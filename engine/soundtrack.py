"""Builds the full soundtrack: voice bus + sound effects (explicit + automatic) + ducked music.

Automatic effects follow what happens on screen (style.audio.auto_sfx): whoosh on whip
transitions, flash, impact on camera punches, pops for cards / poll bars / popping props,
a ring for ringing phones, a boom under the end card.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import audio_mix
from .music import music_track
from .sfx import get_sfx


@dataclass
class Cue:
    t: float
    name: str
    volume: float = 1.0
    params: dict = field(default_factory=dict)
    why: str = ""


def _rule(auto: dict, key: str) -> dict | None:
    r = auto.get(key)
    return r if isinstance(r, dict) and r.get("name") else None


def sfx_cues(tl, style: dict) -> list[Cue]:
    auto = style["audio"].get("auto_sfx", {}) or {}
    on = auto.get("enabled", True)
    cues: list[Cue] = []
    poll_seen: set[int] = set()
    for i, sh in enumerate(tl.shots):
        shot = sh.shot
        for c in shot.sfx:
            cues.append(Cue(sh.start + c.at, c.name, c.volume, dict(c.params), f"{sh.scene_id}: explicit"))
        if not (on and shot.auto_sfx):
            poll_seen.update(shot.poll)
            continue
        # transition into the next shot
        r = _rule(auto, shot.transition_out) if i + 1 < len(tl.shots) else None
        if r:
            cues.append(Cue(sh.end + r.get("offset", 0.0), r["name"], r.get("volume", 1.0), {},
                            f"{shot.transition_out} transition"))
        if shot.camera.punch > 0 and (r := _rule(auto, "punch")):
            cues.append(Cue(sh.start, r["name"], r.get("volume", 1.0) * min(1.0, shot.camera.punch + 0.3), {},
                            "camera punch"))
        if shot.card and (r := _rule(auto, "card")):
            cues.append(Cue(sh.start + shot.card.at, r["name"], r.get("volume", 1.0), {}, "card"))
        new_poll = [n for n in shot.poll if n not in poll_seen]
        if new_poll and (r := _rule(auto, "poll")):
            cues.append(Cue(sh.start, r["name"], r.get("volume", 1.0), {}, f"poll option {new_poll}"))
        poll_seen.update(shot.poll)
        props_rules = auto.get("props", {}) or {}
        for pl in shot.props:
            r = props_rules.get(pl.svg) or (props_rules.get(pl.anim) if pl.anim else None)
            if not (isinstance(r, dict) and r.get("name")):
                continue
            params = {"dur": round(max(0.5, sh.duration), 1)} if r.get("loop") else {}
            cues.append(Cue(sh.start, r["name"], r.get("volume", 1.0), params, f"prop {pl.svg}"))
        if sh.is_ending and (r := _rule(auto, "ending")):
            cues.append(Cue(sh.start, r["name"], r.get("volume", 1.0), {}, "end card"))
    return sorted(cues, key=lambda c: c.t)


def build_soundtrack(sp, tl, style: dict, project_dir: Path, log=print) -> tuple[np.ndarray, dict]:
    sr = style["video"]["sample_rate"]
    a = style["audio"]
    n = int(np.ceil(tl.total * sr)) + 1

    # voice bus
    voice = np.zeros(n, dtype=np.float32)
    vg = audio_mix.db_to_gain(a.get("voice_gain_db", 0.0))
    for s in tl.shots:
        if s.voice_wav:
            audio_mix.place(voice, audio_mix.decode(s.voice_wav, sr), s.voice_start, sr, vg)

    # sfx bus
    sfx = np.zeros(n, dtype=np.float32)
    cues = sfx_cues(tl, style)
    for c in cues:
        try:
            x = get_sfx(c.name, sr, project_dir, **c.params)
        except KeyError as e:
            log(f"  ! {e}")
            continue
        audio_mix.place(sfx, x, c.t, sr, c.volume)
    sfx *= audio_mix.db_to_gain(a.get("sfx_gain_db", -5.0))

    # music bus (ducked under the voice)
    m = sp.music
    mc = a.get("music", {}) or {}
    mood = m.mood or (None if m.file else mc.get("default_mood"))
    music_src = None
    music = np.zeros(n, dtype=np.float32)
    if m.enabled and (mood or m.file):
        seed = zlib.crc32(sp.title.encode()) & 0xFFFF
        track, music_src = music_track(mood, m.file, tl.total, sr, project_dir, seed)
        music[: len(track)] = track[:n]
        # calibrate against the voice: volume 0.15 (default) = bed_db below the speech level
        def active_rms(x):
            env = audio_mix.envelope(x, sr)
            loud = env[env > max(1e-4, env.max() * 0.05)]
            return float(np.sqrt(np.mean(loud ** 2))) if len(loud) else 0.0
        v_rms, m_rms = active_rms(voice), active_rms(music)
        if v_rms > 0 and m_rms > 0:
            music *= v_rms / m_rms * audio_mix.db_to_gain(mc.get("bed_db", -12.0)) * (m.volume / 0.15)
        else:
            music *= m.volume
        duck = audio_mix.duck_gain(voice, sr, mc.get("duck_db", -11), mc.get("duck_threshold_db", -42),
                                   mc.get("duck_attack", 0.08), mc.get("duck_release", 0.45))
        music *= duck

    stems = project_dir / "audio" / "stems"
    stems.mkdir(parents=True, exist_ok=True)
    for name, buf in (("voice", voice), ("sfx", sfx), ("music", music)):
        audio_mix.write_wav(stems / f"{name}.wav", buf, sr)
    log(f"  voice + {len(cues)} sfx cues + music ({music_src or 'none'})")
    report = {"music": music_src, "sfx": [{"t": round(c.t, 2), "name": c.name, "why": c.why} for c in cues]}
    return voice + sfx + music, report
