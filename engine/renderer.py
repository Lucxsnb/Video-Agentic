"""Render a Timeline frame by frame with skia and pipe raw RGBA straight into FFmpeg."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import skia

from .backgrounds import Atmosphere, find_background, render_background
from .captions import CaptionTrack


class FrameRenderer:
    def __init__(self, timeline, style: dict, project_dir: Path):
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

    def background(self, name: str) -> skia.Image:
        if name not in self._bg_cache:
            spec = find_background(name, self.project_dir)
            self._bg_cache[name] = render_background(spec, self.W, self.H)
        return self._bg_cache[name]

    def draw(self, canvas: skia.Canvas, t: float) -> None:
        shot = self.tl.shot_at(t)
        canvas.clear(skia.ColorBLACK)
        canvas.drawImage(self.background(shot.background), 0, 0)
        # Phase 2+: characters, props, camera, transitions
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
