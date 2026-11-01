"""Render a Timeline frame by frame with skia and pipe raw RGBA straight into FFmpeg."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import skia

from . import audio_mix
from .backgrounds import Atmosphere, find_background, render_background
from .captions import CaptionTrack
from .characters import CharacterRenderer, load_rig
from .poses import PoseLibrary


def mouth_envelope(wav: Path, fps: int, rig: dict) -> np.ndarray:
    """Per-frame mouth openness 0..1 from the voice clip loudness (cartoon lip flap)."""
    sr = 16000
    y = audio_mix.decode(wav, sr)
    hop = sr // fps
    n = max(1, len(y) // hop)
    rms = np.sqrt(np.mean(y[: n * hop].reshape(n, hop) ** 2, axis=1))
    ref = np.percentile(rms, 95) or 1.0
    tk = rig["talk"]
    env = np.clip(rms / ref * tk["mouth_gain"] - 0.15, 0, 1)
    # fast attack, slower release
    out = np.zeros_like(env)
    prev = 0.0
    for i, v in enumerate(env):
        prev = v if v > prev else prev * 0.55 + v * 0.45
        out[i] = prev
    levels = tk.get("levels", 0)
    if levels:
        out = np.round(out * levels) / levels
    return out


class FrameRenderer:
    def __init__(self, timeline, style: dict, project_dir: Path, characters=None):
        self.tl = timeline
        self.style = style
        v = style["video"]
        self.W, self.H, self.fps = v["width"], v["height"], v["fps"]
        self.project_dir = project_dir
        self.atmo = Atmosphere(style, self.W, self.H)
        self._bg_cache: dict[str, skia.Image] = {}
        self.captions = CaptionTrack(style, self.W, self.H)
        for sh in timeline.shots:
            if sh.words:
                self.captions.add_line(sh.words, sh.highlight, sh.line_end, sh.end)
        self.rig = load_rig()
        self.poses = PoseLibrary()
        self.chars = {c.id: CharacterRenderer(c, style, self.rig) for c in (characters or [])}
        self.envelopes: dict[int, np.ndarray] = {}
        for i, sh in enumerate(timeline.shots):
            if sh.voice_wav and sh.speaker in self.chars:
                self.envelopes[i] = mouth_envelope(sh.voice_wav, self.fps, self.rig)
        self.anchors: dict[str, dict] = {}   # last drawn anchors per actor (props attach here)

    def background(self, name: str) -> skia.Image:
        if name not in self._bg_cache:
            spec = find_background(name, self.project_dir)
            self._bg_cache[name] = render_background(spec, self.W, self.H)
        return self._bg_cache[name]

    def draw(self, canvas: skia.Canvas, t: float) -> None:
        shot = self.tl.shot_at(t)
        canvas.clear(skia.ColorBLACK)
        canvas.drawImage(self.background(shot.background), 0, 0)
        self.draw_actors(canvas, shot, t)
        # Phase 3: props, camera, transitions
        self.atmo.draw_vignette(canvas)
        self.atmo.draw_grain(canvas, t)
        self.captions.draw(canvas, t)
        # Phase 4: overlays

    def speech_level(self, shot, actor_id: str, t: float) -> float:
        if shot.speaker != actor_id:
            return 0.0
        env = self.envelopes.get(self.tl.shots.index(shot))
        if env is None:
            return 0.0
        i = int((t - shot.voice_start) * self.fps)
        return float(env[i]) if 0 <= i < len(env) else 0.0

    def draw_actors(self, canvas: skia.Canvas, shot, t: float) -> None:
        self.anchors = {}
        local = t - shot.start
        for actor in sorted(shot.shot.actors, key=lambda a: a.y):
            ch = self.chars.get(actor.id)
            if not ch:
                continue
            level = self.speech_level(shot, actor.id, t)
            talking = 1.0 if (shot.speaker == actor.id and shot.voice_start <= t <= shot.line_end) else 0.0
            pose = self.poses.pose(actor.pose, local, speaking=talking)
            expr = self.poses.expression(actor.expression)
            self.anchors[actor.id] = ch.draw(
                canvas, actor.x * self.W, actor.y * self.H, self.H, actor.scale, pose, expr, t,
                mouth_open=level, speaking=talking, facing=actor.facing, flip=actor.flip)

    def frame(self, t: float) -> np.ndarray:
        arr = np.zeros((self.H, self.W, 4), dtype=np.uint8)
        surf = skia.Surface(arr, colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kPremul_AlphaType)
        self.draw(surf.getCanvas(), t)
        surf.flushAndSubmit()
        return arr

    def save_png(self, t: float, path: Path) -> None:
        arr = self.frame(t)
        skia.Image.fromarray(arr, colorType=skia.kRGBA_8888_ColorType).save(str(path), skia.kPNG)

    def render(self, audio_wav: Path | None, out_path: Path, audio_filter: str | None = None,
               max_seconds: float | None = None) -> Path:
        v = self.style["video"]
        total = self.tl.total if not max_seconds else min(self.tl.total, max_seconds)
        n = int(round(total * self.fps))
        cmd = ["ffmpeg", "-y", "-v", "error", "-stats",
               "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{self.W}x{self.H}", "-r", str(self.fps), "-i", "-"]
        if audio_wav:
            cmd += ["-i", str(audio_wav)]
        cmd += ["-c:v", v["codec"], "-preset", v["preset"], "-crf", str(v["crf"]), "-pix_fmt", v["pix_fmt"],
                "-r", str(self.fps)]
        if audio_wav:
            if audio_filter:
                cmd += ["-af", audio_filter]
            cmd += ["-c:a", v["audio_codec"], "-b:a", v["audio_bitrate"], "-ac", "2", "-ar", str(v["sample_rate"])]
        cmd += ["-t", f"{n / self.fps:.3f}", "-movflags", "+faststart", str(out_path)]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        arr = np.zeros((self.H, self.W, 4), dtype=np.uint8)
        surf = skia.Surface(arr, colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kPremul_AlphaType)
        canvas = surf.getCanvas()
        t0 = time.time()
        try:
            for i in range(n):
                self.draw(canvas, i / self.fps)
                surf.flushAndSubmit()
                proc.stdin.write(arr.tobytes())
                if i % (self.fps * 2) == 0:
                    el = time.time() - t0
                    print(f"\r  frame {i}/{n}  ({(i + 1) / max(el, 1e-6):.1f} fps)", end="", file=sys.stderr)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        err = proc.stderr.read().decode(errors="replace")
        rc = proc.wait()
        print(file=sys.stderr)
        if rc != 0:
            raise RuntimeError(f"FFmpeg failed ({rc}):\n{err[-3000:]}")
        return out_path
