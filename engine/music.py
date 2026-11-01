"""Background music: a user file (looped) or a procedural bed generated from a mood preset
(config/music.yaml). Deterministic for a given seed so re-renders sound the same."""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import yaml

from .config import CONFIG_DIR, ROOT
from .sfx import fft_filter, noise, tone

SCALES = {"minor": [0, 2, 3, 5, 7, 8, 10], "major": [0, 2, 4, 5, 7, 9, 11]}


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def load_moods() -> dict:
    with open(CONFIG_DIR / "music.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def degree_note(key: int, scale: list[int], degree: int) -> int:
    d = degree - 1
    return key + 12 * (d // 7) + scale[d % 7]


def triad(key: int, scale: list[int], degree: int) -> list[int]:
    return [degree_note(key, scale, degree + k) for k in (0, 2, 4)]


def _env(n: int, sr: int, attack: float, release: float) -> np.ndarray:
    e = np.ones(n, dtype=np.float32)
    a, r = min(n, int(attack * sr)), min(n, int(release * sr))
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def _pluck(freq: float, dur: float, sr: int, decay: float, harm=(1.0, 0.4, 0.2)) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return tone(freq, t, sr, harm) * np.exp(-t * decay) * (1 - np.exp(-t * 400))


def _add(buf: np.ndarray, x: np.ndarray, start: float, sr: int, gain: float = 1.0) -> None:
    i = int(start * sr)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(x))
    buf[i:j] += x[: j - i] * gain


def generate(mood: str, duration: float, sr: int = 48000, seed: int = 0) -> np.ndarray:
    moods = load_moods()
    cfg = moods.get(mood) or moods.get("tense")
    rng = random.Random(seed)
    key, scale = int(cfg["key"]), SCALES[cfg.get("scale", "minor")]
    beat = 60.0 / cfg.get("bpm", 80)
    seg = cfg.get("bars_per_chord", 1) * 4 * beat
    L = cfg.get("layers", {})
    n = int(duration * sr) + 1
    layers = {k: np.zeros(n, dtype=np.float32) for k in L}
    t_all = np.arange(n) / sr

    if "drone" in L:
        root = midi_hz(key - 12)
        lfo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.07 * t_all)
        d = tone(root, t_all, sr, (1.0, 0.5, 0.25, 0.1)) + 0.6 * tone(root * 1.5, t_all, sr, (1.0, 0.3))
        d += 0.5 * tone(root * 1.003, t_all, sr, (1.0, 0.4))
        layers["drone"] += d * lfo

    chords = cfg.get("chords", [1])
    start, ci = 0.0, 0
    while start < duration:
        notes = triad(key, scale, chords[ci % len(chords)])
        seg_n = int(seg * sr)
        t = np.arange(seg_n) / sr
        if "pad" in L:
            env = _env(seg_n, sr, 0.5, 0.5)
            pad = sum(tone(midi_hz(m + 12) * det, t, sr, (1.0, 0.35, 0.15, 0.06))
                      for m in notes for det in (0.997, 1.003))
            _add(layers["pad"], pad * env, start, sr)
        if "bass" in L:
            for b in range(int(seg / beat)):
                if b % 2 == 0:
                    _add(layers["bass"], _pluck(midi_hz(notes[0] - 12), beat * 1.8, sr, 3.5, (1.0, 0.5, 0.1)),
                         start + b * beat, sr)
        if "arp" in L:
            pattern = [0, 1, 2, 1]
            for k in range(int(seg / (beat / 2))):
                m = notes[pattern[k % 4]] + 24
                _add(layers["arp"], _pluck(midi_hz(m), beat * 1.5, sr, 7.0), start + k * beat / 2, sr)
        for b in range(int(seg / beat)):
            tb = start + b * beat
            if "kick" in L:
                tt = np.arange(int(0.35 * sr)) / sr
                _add(layers["kick"], tone(45 + 90 * np.exp(-tt * 30), tt, sr) * np.exp(-tt * 9) * (1 - np.exp(-tt * 500)),
                     tb, sr)
            if "pulse" in L and b % 4 == 0:
                for off, a in ((0.0, 1.0), (0.24, 0.65)):
                    tt = np.arange(int(0.4 * sr)) / sr
                    _add(layers["pulse"], a * tone(50 + 25 * np.exp(-tt * 25), tt, sr) * np.exp(-tt * 10) * (1 - np.exp(-tt * 500)),
                         tb + off, sr)
            if "hat" in L:
                hn = int(0.05 * sr)
                hat = fft_filter(noise(hn, int(tb * 1000) % 9973), sr, lo=6000) * np.exp(-np.arange(hn) / sr * 70)
                _add(layers["hat"], hat, tb + beat / 2, sr)
            if "bells" in L and b % 2 == 0 and rng.random() < 0.45:
                deg = rng.choice([1, 3, 4, 5, 7])
                m = degree_note(key, scale, deg) + 36
                _add(layers["bells"], _pluck(midi_hz(m), 2.5, sr, 1.6, (1.0, 0.0, 0.3, 0.0, 0.1)), tb, sr)
        start += seg
        ci += 1

    out = np.zeros(n, dtype=np.float32)
    for k, buf in layers.items():
        peak = float(np.max(np.abs(buf))) or 1.0
        out += buf / peak * float(L[k])
    out = fft_filter(out, sr, hi=9000)
    out *= _env(n, sr, 1.0, 1.5)
    return (out / (float(np.max(np.abs(out))) or 1.0) * 0.8).astype(np.float32)


def find_music(mood: str | None, file: str | None, project_dir: Path | None) -> Path | None:
    if file:
        for base in ([project_dir] if project_dir else []) + [ROOT]:
            p = Path(file) if Path(file).is_absolute() else base / file
            if p.exists():
                return p
    if mood:
        exts = (".mp3", ".wav", ".ogg", ".m4a", ".flac")
        d = ROOT / "library" / "music" / mood
        if d.is_dir():
            files = sorted(f for f in d.iterdir() if f.suffix.lower() in exts)
            if files:
                return files[0]
        for ext in exts:
            p = ROOT / "library" / "music" / f"{mood}{ext}"
            if p.exists():
                return p
    return None


def music_track(mood: str | None, file: str | None, duration: float, sr: int, project_dir: Path | None,
                seed: int = 0) -> tuple[np.ndarray, str]:
    """Returns (samples, source description)."""
    from .audio_mix import decode
    n = int(duration * sr) + 1
    path = find_music(mood, file, project_dir)
    if path:
        x = decode(path, sr)
        if len(x) < n:   # loop with a short crossfade
            xf = int(0.5 * sr)
            out = x.copy()
            while len(out) < n:
                ramp = np.linspace(0, 1, xf, dtype=np.float32)
                out[-xf:] = out[-xf:] * (1 - ramp) + x[:xf] * ramp
                out = np.concatenate([out, x[xf:]])
            x = out
        x = x[:n].copy()
        f = int(1.5 * sr)
        x[-f:] *= np.linspace(1, 0, f)
        return x, str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
    return generate(mood or "tense", duration, sr, seed), f"procedural:{mood or 'tense'}"
