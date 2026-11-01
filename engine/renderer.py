"""Render a Timeline frame by frame with skia and pipe raw RGBA straight into FFmpeg."""
from __future__ import annotations

import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import skia

from . import audio_mix
from .backgrounds import Atmosphere, background_image, find_background
from .camera import camera_matrix, camera_zoom, resolve_target
from .captions import CaptionTrack
from .characters import CharacterRenderer, load_rig
from .lighting import LightingRenderer
from .poses import PoseLibrary
from .props import PropLibrary, prop_motion
from .transitions import active_transition, draw_transition


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
    """Per frame: record the world (bg, props, actors, light) into a skia Picture while collecting
    anchors -> apply the camera -> blend transitions -> screen-space vignette, grain, captions."""

    def __init__(self, timeline, style: dict, project_dir: Path, characters=None):
        self.tl = timeline
        self.style = style
        self._characters = characters
        v = style["video"]
        self.W, self.H, self.fps = v["width"], v["height"], v["fps"]
        self.project_dir = project_dir
        self.atmo = Atmosphere(style, self.W, self.H)
        self._bg_cache: dict[tuple, skia.Image] = {}
        self.captions = CaptionTrack(style, self.W, self.H)
        for sh in timeline.shots:
            if sh.words:
                self.captions.add_line(sh.words, sh.highlight, sh.line_end, sh.end, sh.shot.caption_y)
        self.rig = load_rig()
        self.poses = PoseLibrary()
        self.props = PropLibrary(style, project_dir)
        self.chars = {c.id: CharacterRenderer(c, style, self.rig) for c in (characters or [])}
        self._index = {id(sh): i for i, sh in enumerate(timeline.shots)}
        self.envelopes: dict[int, np.ndarray] = {}
        for i, sh in enumerate(timeline.shots):
            if sh.voice_wav and sh.speaker in self.chars:
                self.envelopes[i] = mouth_envelope(sh.voice_wav, self.fps, self.rig)
        self.anchors: dict[str, dict] = {}
        self._off = [skia.Surface(self.W, self.H), skia.Surface(self.W, self.H)]
        self.lights = LightingRenderer(self.W, self.H, style)

    # ------------------------------------------------------------------ assets
    def background(self, name: str, blur: float, hires: bool) -> skia.Image:
        """1x image for wide shots (fast blit), render_scale image for close-ups (sharp)."""
        scale = self.style.get("background", {}).get("render_scale", 1.5) if hires else 1.0
        key = (name, round(blur, 2), scale)
        if key not in self._bg_cache:
            spec = find_background(name, self.project_dir)
            self._bg_cache[key] = background_image(spec, self.W, self.H, scale, blur).makeRasterImage()
        return self._bg_cache[key]

    def shot_blur(self, shot) -> float:
        for v in (shot.shot.blur, getattr(shot.scene, "blur", None)):
            if v is not None:
                return v
        return self.style.get("background", {}).get("blur", 0.0)

    def shot_lighting(self, shot):
        return shot.shot.lighting or getattr(shot.scene, "lighting", None)

    # ------------------------------------------------------------------- world
    def speech_level(self, shot, actor_id: str, t: float) -> float:
        if shot.speaker != actor_id:
            return 0.0
        env = self.envelopes.get(self._index[id(shot)])
        if env is None:
            return 0.0
        i = int((t - shot.voice_start) * self.fps)
        return float(env[i]) if 0 <= i < len(env) else 0.0

    def draw_actors(self, c: skia.Canvas, shot, t: float, anchors: dict) -> None:
        local = t - shot.start
        for actor in sorted(shot.shot.actors, key=lambda a: a.y):
            ch = self.chars.get(actor.id)
            if not ch:
                continue
            level = self.speech_level(shot, actor.id, t)
            talking = 1.0 if (shot.speaker == actor.id and shot.voice_start <= t <= shot.line_end) else 0.0
            pose = self.poses.pose(actor.pose, local, speaking=talking)
            expr = self.poses.expression(actor.expression)
            anchors[actor.id] = ch.draw(
                c, actor.x * self.W, actor.y * self.H, self.H, actor.scale, pose, expr, t,
                mouth_open=level, speaking=talking, facing=actor.facing, flip=actor.flip)

    def draw_prop(self, c: skia.Canvas, pl, t_local: float, anchors: dict) -> None:
        m = self.props.meta(pl.svg)
        rot, bob, smul = prop_motion(pl.anim, t_local)
        h = m.height * self.H * pl.scale * smul
        w = h * m.vb_w / m.vb_h
        if pl.attach_to:
            pos = resolve_target(pl.attach_to, anchors)
            if pos is None:
                return
            x, y = pos
        else:
            x, y = pl.x * self.W, pl.y * self.H
        x += pl.dx * self.H
        y += pl.dy * self.H + bob * h
        sup = self.style.get("props", {}).get("supersample", 2.0)
        img = self.props.image(pl.svg, pl.params, h * sup)
        c.save()
        c.translate(x, y)
        c.rotate(pl.rotation + rot)
        if pl.flip:
            c.scale(-1, 1)
        ax, ay = m.anchor
        paint = skia.Paint(AntiAlias=True)
        if pl.opacity < 1:
            paint.setAlphaf(pl.opacity)
        c.drawImageRect(img, skia.Rect.MakeXYWH(-ax * w, -ay * h, w, h),
                        skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear), paint)
        M = c.getTotalMatrix()
        ctr = M.mapXY(-ax * w + w / 2, -ay * h + h / 2)
        a = {"center": (ctr.x(), ctr.y())}
        if m.tip:
            tp = M.mapXY(-ax * w + m.tip[0] * w, -ay * h + m.tip[1] * h)
            a["tip"] = (tp.x(), tp.y())
            ang = m.tip_angle + pl.rotation + rot
            a["_angle"] = ((180 - ang) if pl.flip else ang, 0.0)
        anchors[pl.id or pl.svg] = a
        c.restore()

    def record_world(self, shot, t: float) -> tuple[skia.Picture, dict]:
        rec = skia.PictureRecorder()
        c = rec.beginRecording(skia.Rect.MakeWH(self.W, self.H))
        zoom = camera_zoom(shot.shot.camera, max(0.0, t - shot.start), shot.duration)
        bg = self.background(shot.background, self.shot_blur(shot), zoom > 1.2)
        c.drawImageRect(bg, skia.Rect.MakeWH(self.W, self.H), skia.SamplingOptions(skia.FilterMode.kLinear))
        anchors: dict = {}
        local = t - shot.start
        props = shot.shot.props
        for pl in props:
            if pl.layer == "back" and not pl.attach_to:
                self.draw_prop(c, pl, local, anchors)
        self.draw_actors(c, shot, t, anchors)
        for pl in props:
            if pl.layer == "front" or pl.attach_to:
                self.draw_prop(c, pl, local, anchors)
        self.lights.draw(c, self.shot_lighting(shot), anchors, t)
        return rec.finishRecordingAsPicture(), anchors

    def draw_scene(self, canvas: skia.Canvas, shot, t: float) -> None:
        pic, anchors = self.record_world(shot, t)
        self.anchors = anchors
        M = camera_matrix(shot.shot.camera, max(0.0, t - shot.start), shot.duration, self.W, self.H,
                          anchors, self.style)
        canvas.clear(skia.ColorBLACK)
        canvas.save()
        canvas.concat(M)
        canvas.drawPicture(pic)
        canvas.restore()

    # ------------------------------------------------------------------ screen
    def draw(self, canvas: skia.Canvas, t: float) -> None:
        tr = active_transition(self.tl.shots, t, self.style)
        if tr:
            kind, p, out_shot, in_shot = tr
            self.draw_scene(self._off[0].getCanvas(), out_shot, min(t, out_shot.end))
            self.draw_scene(self._off[1].getCanvas(), in_shot, max(t, in_shot.start))
            canvas.clear(skia.ColorBLACK)
            draw_transition(canvas, kind, p, self._off[0].makeImageSnapshot(), self._off[1].makeImageSnapshot(),
                            self.W, self.H, self.style)
        else:
            self.draw_scene(canvas, self.tl.shot_at(t), t)
        self.atmo.draw_vignette(canvas)
        self.atmo.draw_grain(canvas, t)
        self.captions.draw(canvas, t)
        # Phase 4: overlays

    def frame(self, t: float) -> np.ndarray:
        arr = np.zeros((self.H, self.W, 4), dtype=np.uint8)
        surf = skia.Surface(arr, colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kPremul_AlphaType)
        self.draw(surf.getCanvas(), t)
        surf.flushAndSubmit()
        return arr

    def save_png(self, t: float, path: Path) -> None:
        arr = self.frame(t)
        skia.Image.fromarray(arr, colorType=skia.kRGBA_8888_ColorType).save(str(path), skia.kPNG)

    # ------------------------------------------------------------------ output
    def _ffmpeg_cmd(self, out_path: Path, n_frames: int, audio_wav: Path | None = None,
                    audio_filter: str | None = None) -> list[str]:
        v = self.style["video"]
        cmd = ["ffmpeg", "-y", "-v", "error",
               "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{self.W}x{self.H}", "-r", str(self.fps), "-i", "-"]
        if audio_wav:
            cmd += ["-i", str(audio_wav)]
        cmd += ["-c:v", v["codec"], "-preset", v["preset"], "-crf", str(v["crf"]), "-pix_fmt", v["pix_fmt"],
                "-r", str(self.fps)]
        if audio_wav:
            if audio_filter:
                cmd += ["-af", audio_filter]
            cmd += ["-c:a", v["audio_codec"], "-b:a", v["audio_bitrate"], "-ac", "2", "-ar", str(v["sample_rate"])]
        cmd += ["-frames:v", str(n_frames), "-movflags", "+faststart", str(out_path)]
        return cmd

    def render_frames(self, start: int, end: int, out_path: Path, audio_wav: Path | None = None,
                      audio_filter: str | None = None, progress: bool = True) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(self._ffmpeg_cmd(out_path, end - start, audio_wav, audio_filter),
                                stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        arr = np.zeros((self.H, self.W, 4), dtype=np.uint8)
        surf = skia.Surface(arr, colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kPremul_AlphaType)
        canvas = surf.getCanvas()
        t0 = time.time()
        try:
            for k, i in enumerate(range(start, end)):
                self.draw(canvas, i / self.fps)
                surf.flushAndSubmit()
                proc.stdin.write(arr.tobytes())
                if progress and k % (self.fps * 2) == 0:
                    el = time.time() - t0
                    print(f"\r  frame {k}/{end - start}  ({(k + 1) / max(el, 1e-6):.1f} fps)", end="", file=sys.stderr)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        err = proc.stderr.read().decode(errors="replace")
        rc = proc.wait()
        if progress:
            print(file=sys.stderr)
        if rc != 0:
            raise RuntimeError(f"FFmpeg failed ({rc}):\n{err[-3000:]}")
        return out_path

    def render(self, audio_wav: Path | None, out_path: Path, audio_filter: str | None = None,
               max_seconds: float | None = None, workers: int = 0) -> Path:
        """workers: 0 = auto (CPU count), 1 = single process. Parallel mode renders frame ranges in
        separate processes, then joins the segments losslessly and muxes the audio."""
        total = self.tl.total if not max_seconds else min(self.tl.total, max_seconds)
        n = int(round(total * self.fps))
        workers = workers or self.style.get("render", {}).get("workers", 0) or (os.cpu_count() or 1)
        workers = max(1, min(workers, n // (self.fps * 2) or 1))
        if workers == 1:
            return self.render_frames(0, n, out_path, audio_wav, audio_filter)

        tmp = out_path.parent / ".segments"
        tmp.mkdir(parents=True, exist_ok=True)
        bounds = [round(n * k / workers) for k in range(workers + 1)]
        jobs = [(self.tl, self.style, self.project_dir, self._characters, bounds[k], bounds[k + 1],
                 tmp / f"seg{k:02d}.mp4") for k in range(workers)]
        t0 = time.time()
        print(f"  rendering {n} frames in {workers} processes...", file=sys.stderr)
        ctx = mp.get_context("spawn")
        with ctx.Pool(workers) as pool:
            segs = pool.map(_render_segment, jobs)
        print(f"  {n / (time.time() - t0):.1f} fps overall", file=sys.stderr)
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in segs))
        v = self.style["video"]
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
        if audio_wav:
            cmd += ["-i", str(audio_wav), "-map", "0:v", "-map", "1:a"]
            if audio_filter:
                cmd += ["-af", audio_filter]
            cmd += ["-c:a", v["audio_codec"], "-b:a", v["audio_bitrate"], "-ac", "2", "-ar", str(v["sample_rate"])]
        cmd += ["-c:v", "copy", "-t", f"{n / self.fps:.3f}", "-movflags", "+faststart", str(out_path)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed:\n{r.stderr[-3000:]}")
        for p in segs:
            p.unlink(missing_ok=True)
        lst.unlink(missing_ok=True)
        return out_path


def _render_segment(job) -> Path:
    tl, style, project_dir, characters, a, b, out = job
    r = FrameRenderer(tl, style, project_dir, characters)
    return r.render_frames(a, b, out, progress=False)
