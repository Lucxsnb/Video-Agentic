"""Build the timeline (TTS -> shot durations -> word times) and produce final.mp4 + captions.srt."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import audio_mix, tts
from .characters import resolve_character
from .config import load_style, load_voices
from .renderer import FrameRenderer
from .soundtrack import build_soundtrack
from .schema import Lighting, Scene, Screenplay, Shot, load_screenplay


@dataclass
class ShotTiming:
    scene_id: str
    index: int
    shot: Shot
    background: str
    start: float
    end: float
    voice_wav: Path | None = None
    voice_start: float = 0.0
    line_end: float = 0.0
    words: list[tuple[str, float, float]] = field(default_factory=list)  # absolute times
    highlight: list[str] = field(default_factory=list)
    speaker: str | None = None
    scene: Scene | None = None
    clock: str | None = None             # in-story clock shown in the badge
    is_ending: bool = False

    @property
    def background_params(self) -> dict:
        base = dict(self.scene.background_params) if self.scene else {}
        base.update(self.shot.background_params)
        return base

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Timeline:
    shots: list[ShotTiming]
    total: float

    def shot_at(self, t: float) -> ShotTiming:
        for s in self.shots:
            if t < s.end:
                return s
        return self.shots[-1]


def build_timeline(sp: Screenplay, project_dir: Path, style: dict, voices_cfg: dict,
                   backends: list[str] | None = None, log=print) -> Timeline:
    tm = style["timing"]
    cache = project_dir / "audio"
    shots: list[ShotTiming] = []
    t = 0.0
    used_backends = set()
    clock = sp.series.clock if sp.series else None

    def timed(scene, i, shot, start, label) -> ShotTiming:
        st = ShotTiming(scene.id, i, shot, shot.background or scene.background, start, start, scene=scene)
        dur = shot.duration or 0.0
        if shot.line:
            ln = shot.line
            char = sp.character(ln.speaker)
            voice = tts.resolve_voice(ln.voice or (char.voice if char else None),
                                      char.gender if char else None, voices_cfg,
                                      role="narrator" if ln.speaker == "narrator" else "character")
            sp_ = tts.synthesize(ln.text, voice, cache, style, voices_cfg, backends, ln.rate, ln.pitch)
            used_backends.add(sp_.backend)
            st.voice_wav = sp_.wav
            st.voice_start = start + tm["pre_roll"]
            st.words = [(w.text, st.voice_start + w.start, st.voice_start + w.end) for w in sp_.words]
            st.line_end = st.words[-1][2] if st.words else st.voice_start + sp_.duration
            st.highlight = ln.highlight
            st.speaker = ln.speaker
            dur = max(dur, tm["pre_roll"] + sp_.duration + tm["breath_after"])
            log(f"  [{label}] {sp_.backend}:{voice}  {sp_.duration:.2f}s  \"{ln.text}\"")
        if dur <= 0:
            dur = tm["default_shot"]
        st.end = start + max(dur, tm["min_shot"])
        return st

    for scene in sp.scenes:
        clock = scene.clock or clock
        for i, shot in enumerate(scene.shots):
            clock = shot.clock or clock
            st = timed(scene, i, shot, t, f"{scene.id}/{i + 1}")
            st.clock = clock
            shots.append(st)
            t = st.end

    end = sp.ending
    if end.type != "none" and shots:
        last = shots[-1]
        ecfg = style.get("ending", {})
        eshot = Shot(line=end.line, duration=end.duration, background=last.background,
                     blur=ecfg.get("blur", 14), lighting=Lighting(darkness=ecfg.get("darkness", 0.55)),
                     background_params=last.background_params, caption_y=ecfg.get("caption_y"))
        st = timed(last.scene, len(last.scene.shots), eshot, t, "ending")
        st.clock, st.is_ending = clock, True
        shots.append(st)
        t = st.end
    if "edge" not in used_backends and used_backends:
        log(f"  ! Using fallback TTS ({', '.join(sorted(used_backends))}); quality is lower than edge-tts.")
    return Timeline(shots, t)


def normalize_audio(src: Path, dst: Path, style: dict, iterations: int = 8) -> Path:
    """Bring `src` to target integrated loudness (LUFS) with a true-peak limiter.

    Gain + alimiter, re-measured and corrected a few times (limiting lowers loudness a bit).
    """
    a = style["audio"]
    if not a.get("loudnorm", True):
        shutil.copy(src, dst)
        return dst
    target, tp = float(a["target_lufs"]), float(a["true_peak"])
    limit = max(0.0625, 10 ** (tp / 20))
    gain = 0.0
    for _ in range(iterations):
        filt = f"volume={gain:.2f}dB,alimiter=limit={limit:.4f}:attack=3:release=60:level=disabled"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", filt, str(dst)], check=True)
        lufs = measure_lufs(dst)
        if lufs is None or abs(lufs - target) < 0.3:
            break
        gain += target - lufs
    return dst


def measure_lufs(path: Path) -> float | None:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    return float(m[-1]) if m else None


def load_project(project_dir: Path):
    """screenplay (characters resolved), merged style, voices config."""
    project_dir = Path(project_dir)
    sp = load_screenplay(project_dir / "screenplay.json")
    sp.characters = [resolve_character(c, project_dir) for c in sp.characters]
    style = load_style(sp.style_preset, sp.style_overrides)
    return sp, style, load_voices()


def make_video(project_dir: Path, backends: list[str] | None = None, max_seconds: float | None = None,
               log=print, workers: int = 0) -> dict:
    project_dir = Path(project_dir)
    sp, style, voices_cfg = load_project(project_dir)
    out_dir = project_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    log("1/3 Voice (TTS + word timestamps)")
    tl = build_timeline(sp, project_dir, style, voices_cfg, backends, log)

    log(f"2/3 Audio mix ({tl.total:.2f}s)")
    sr = style["video"]["sample_rate"]
    mix, audio_report = build_soundtrack(sp, tl, style, project_dir, log)
    mix_wav = project_dir / "audio" / "mix.wav"
    audio_mix.write_wav(mix_wav, mix, sr)
    mix_wav = normalize_audio(mix_wav, project_dir / "audio" / "mix_norm.wav", style)

    log("3/3 Render video")
    r = FrameRenderer(tl, style, project_dir, sp.characters, sp)
    final = r.render(mix_wav, out_dir / "final.mp4", None, max_seconds, workers)
    (out_dir / "captions.srt").write_text(r.captions.to_srt(), encoding="utf-8")
    (out_dir / "timeline.json").write_text(json.dumps({
        "total": tl.total,
        "shots": [{"scene": s.scene_id, "shot": s.index + 1, "start": round(s.start, 3), "end": round(s.end, 3),
                   "speaker": s.speaker, "words": [[w, round(a, 3), round(b, 3)] for w, a, b in s.words]}
                  for s in tl.shots], "audio": audio_report}, indent=1), encoding="utf-8")
    (out_dir / "post.txt").write_text(post_text(sp), encoding="utf-8")
    return {"video": final, "duration": tl.total, "srt": out_dir / "captions.srt", "post": out_dir / "post.txt"}


def post_text(sp: Screenplay) -> str:
    """post.txt: the screenplay's `post` (written by the agent) or a template fallback."""
    if sp.post:
        tags = " ".join(h if h.startswith("#") else f"#{h}" for h in sp.post.hashtags)
        return f"{sp.post.caption.strip()}\n\n{tags}\n"
    head = sp.title
    if sp.series:
        head = f"{sp.series.name} · Ep {sp.series.episode}: {sp.title}" if sp.series.episode else sp.series.name
    lines = [head]
    if sp.ending.question:
        lines.append(sp.ending.question)
    if sp.ending.type == "poll" and sp.ending.options:
        lines.append(" / ".join(f"{i}) {o.text}" for i, o in enumerate(sp.ending.option_list(), 1)))
        lines.append(sp.ending.cta or "Comment 1 or 2 👇")
    tags = ["#animation", "#story", "#shorts", "#reels", "#fyp"]
    if sp.series:
        tags.insert(0, "#" + "".join(w.capitalize() for w in sp.series.name.split()))
    return "\n".join(lines) + "\n\n" + " ".join(tags) + "\n"
