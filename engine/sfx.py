"""Procedural sound effects (numpy only, no downloads).

get_sfx(name, sr, **params) returns mono float32. A file in library/sfx/<name>.(wav|mp3|ogg) or
projects/<slug>/assets/sfx/ overrides the generator with the same name.

Available: whoosh, pop, hit, boom, ring, vibrate, notify, riser, flash, tick, heartbeat,
footstep, door_slam, drop.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from .config import ROOT

SR = 48000


# ------------------------------------------------------------------------- dsp utils
def _t(dur: float, sr: int) -> np.ndarray:
    return np.arange(int(dur * sr)) / sr


def noise(n: int, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def fft_filter(x: np.ndarray, sr: int, lo: float | None = None, hi: float | None = None,
               order: int = 2) -> np.ndarray:
    """Zero-phase Butterworth-like magnitude filter in the frequency domain."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / sr) + 1e-6
    g = np.ones_like(f)
    if hi:
        g /= np.sqrt(1 + (f / hi) ** (2 * order))
    if lo:
        g /= np.sqrt(1 + (lo / f) ** (2 * order))
    return np.fft.irfft(X * g, len(x)).astype(np.float32)


def sweep_bandpass(x: np.ndarray, sr: int, centers: np.ndarray, width_oct: float = 1.0) -> np.ndarray:
    """Time-varying band-pass via STFT: `centers` (Hz) is sampled along the signal."""
    n_fft, hop = 2048, 512
    win = np.hanning(n_fft).astype(np.float32)
    pad = np.concatenate([np.zeros(n_fft), x, np.zeros(n_fft)]).astype(np.float32)
    out = np.zeros_like(pad)
    norm = np.zeros_like(pad)
    f = np.fft.rfftfreq(n_fft, 1 / sr) + 1e-6
    for start in range(0, len(pad) - n_fft, hop):
        frame = pad[start:start + n_fft] * win
        pos = min(len(centers) - 1, max(0, int((start - n_fft + n_fft / 2) / max(1, len(x)) * len(centers))))
        fc = centers[pos]
        g = np.exp(-0.5 * (np.log2(f / fc) / (width_oct / 2)) ** 2)
        y = np.fft.irfft(np.fft.rfft(frame) * g, n_fft) * win
        out[start:start + n_fft] += y
        norm[start:start + n_fft] += win ** 2
    out = out / np.maximum(norm, 1e-3)
    return out[n_fft:n_fft + len(x)].astype(np.float32)


def normalize(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.max(np.abs(x))) or 1.0
    return (x / m * peak).astype(np.float32)


def fade(x: np.ndarray, sr: int, fin: float = 0.003, fout: float = 0.01) -> np.ndarray:
    x = x.copy()
    a, b = int(fin * sr), int(fout * sr)
    if a:
        x[:a] *= np.linspace(0, 1, a)
    if b:
        x[-b:] *= np.linspace(1, 0, b)
    return x


def tone(freq, t: np.ndarray, sr: int, harmonics=(1.0,), phase0: float = 0.0) -> np.ndarray:
    """freq: scalar or per-sample array; harmonics: amplitudes of partials 1..n."""
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), t.shape)
    ph = 2 * np.pi * np.cumsum(f) / sr + phase0
    return sum(a * np.sin(ph * (k + 1)) for k, a in enumerate(harmonics)).astype(np.float32)


# ------------------------------------------------------------------------- generators
def whoosh(sr=SR, dur=0.45, low=250.0, high=3200.0, seed=1):
    n = int(dur * sr)
    u = np.linspace(0, 1, 64)
    centers = np.exp(np.log(low) + (np.log(high) - np.log(low)) * np.sin(np.pi * np.clip(u * 1.1, 0, 1)) ** 1.3)
    x = sweep_bandpass(noise(n, seed), sr, centers, 1.4)
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * np.clip(t, 0, 1)) ** 2 * np.exp(-((t - 0.55) ** 2) / 0.12)
    return fade(normalize(x * env), sr)


def pop(sr=SR, dur=0.13, f0=1100.0, f1=320.0):
    t = _t(dur, sr)
    f = f1 + (f0 - f1) * np.exp(-t * 40)
    x = tone(f, t, sr, (1.0, 0.25)) * np.exp(-t * 32)
    x[: int(0.002 * sr)] += noise(int(0.002 * sr), 3) * 0.4
    return fade(normalize(x, 0.85), sr, 0.001)


def hit(sr=SR, dur=0.6, seed=2):
    t = _t(dur, sr)
    body = tone(45 + 70 * np.exp(-t * 18), t, sr, (1.0, 0.3)) * np.exp(-t * 7)
    crack = fft_filter(noise(len(t), seed), sr, hi=2200) * np.exp(-t * 35)
    x = np.tanh((body + 0.9 * crack) * 1.8)
    return fade(normalize(x), sr, 0.001)


def boom(sr=SR, dur=2.2, seed=4):
    t = _t(dur, sr)
    body = tone(32 + 60 * np.exp(-t * 10), t, sr, (1.0, 0.4, 0.15)) * np.exp(-t * 2.2)
    rumble = fft_filter(noise(len(t), seed), sr, hi=400) * np.exp(-t * 1.6)
    x = np.tanh((body + 1.6 * rumble) * 1.5)
    return fade(normalize(x), sr, 0.002, 0.2)


def ring(sr=SR, dur=2.0):
    """Generic two-tone phone ring: bursts of alternating beeps."""
    t = _t(dur, sr)
    x = np.zeros_like(t, dtype=np.float32)
    beep, cycle = 0.07, 1.4
    notes = (1318.5, 1568.0)
    for c0 in np.arange(0, dur, cycle):
        for i in range(8):
            s = c0 + i * beep * 1.05
            if s >= dur:
                break
            a, b = int(s * sr), min(len(t), int((s + beep) * sr))
            tt = t[a:b] - s
            x[a:b] += tone(notes[i % 2], tt, sr, (1.0, 0.3, 0.12)) * np.exp(-tt * 12) * (1 - np.exp(-tt * 900))
    return fade(normalize(x, 0.7), sr)


def vibrate(sr=SR, dur=1.2):
    t = _t(dur, sr)
    buzz = np.tanh(4 * np.sin(2 * np.pi * 175 * t)) + 0.4 * np.sin(2 * np.pi * 350 * t)
    gate = ((t % 0.55) < 0.35).astype(np.float32)
    gate = np.convolve(gate, np.ones(480) / 480, mode="same")
    x = fft_filter(buzz * gate, sr, hi=900)
    return fade(normalize(x, 0.6), sr)


def notify(sr=SR, dur=0.7):
    t = _t(dur, sr)
    x = tone(1568, t, sr, (1.0, 0.2)) * np.exp(-t * 9)
    t2 = np.clip(t - 0.11, 0, None)
    x += (t >= 0.11) * tone(2093, t2, sr, (1.0, 0.2)) * np.exp(-t2 * 7)
    return fade(normalize(x, 0.7), sr, 0.001)


def riser(sr=SR, dur=2.0, seed=5):
    n = int(dur * sr)
    t = np.linspace(0, 1, n)
    centers = np.exp(np.log(200) + (np.log(6000) - np.log(200)) * np.linspace(0, 1, 64) ** 1.5)
    air = sweep_bandpass(noise(n, seed), sr, centers, 1.2)
    sw = tone(110 * 2 ** (3 * t ** 1.4), _t(dur, sr)[:n], sr, (1.0, 0.5, 0.25))
    x = (0.8 * air / (np.max(np.abs(air)) + 1e-6) + 0.35 * sw) * t ** 2.2
    return fade(normalize(x), sr, 0.01, 0.02)


def flash(sr=SR, dur=0.35, seed=6):
    t = _t(dur, sr)
    x = fft_filter(noise(len(t), seed), sr, lo=2500) * np.exp(-t * 14)
    x += 0.3 * tone(3200, t, sr) * np.exp(-t * 10)
    return fade(normalize(x, 0.7), sr, 0.002)


def tick(sr=SR, dur=0.04, seed=7):
    t = _t(dur, sr)
    x = fft_filter(noise(len(t), seed), sr, lo=2000, hi=6000) * np.exp(-t * 180)
    return fade(normalize(x, 0.6), sr, 0.0005)


def heartbeat(sr=SR, dur=1.0):
    t = _t(dur, sr)
    x = np.zeros_like(t, dtype=np.float32)
    for s, a in ((0.0, 1.0), (0.26, 0.7)):
        m = t >= s
        tt = t[m] - s
        x[m] += a * tone(48 + 30 * np.exp(-tt * 30), tt, sr) * np.exp(-tt * 14)
    return fade(normalize(np.tanh(x * 2)), sr)


def footstep(sr=SR, dur=0.18, seed=8):
    t = _t(dur, sr)
    x = fft_filter(noise(len(t), seed), sr, lo=80, hi=900) * np.exp(-t * 40)
    x += 0.6 * tone(70, t, sr) * np.exp(-t * 35)
    return fade(normalize(x, 0.7), sr, 0.001)


def door_slam(sr=SR, dur=0.9, seed=9):
    t = _t(dur, sr)
    rattle = sweep_bandpass(noise(len(t), seed), sr, np.full(16, 1800.0), 1.0) * np.exp(-t * 9)
    rattle *= 0.6 + 0.4 * np.sin(2 * np.pi * 23 * t)
    h = hit(sr, dur)
    return fade(normalize(np.tanh(h + 0.5 * rattle / (np.max(np.abs(rattle)) + 1e-6))), sr)


def drop(sr=SR, dur=0.45):
    t = _t(dur, sr)
    x = tone(600 * np.exp(-t * 5) + 70, t, sr, (1.0, 0.3)) * np.exp(-t * 4)
    return fade(normalize(x, 0.7), sr)


GENERATORS = {f.__name__: f for f in (whoosh, pop, hit, boom, ring, vibrate, notify, riser, flash, tick,
                                      heartbeat, footstep, door_slam, drop)}


# ----------------------------------------------------------------------------- lookup
def find_file(name: str, project_dir: Path | None = None) -> Path | None:
    dirs = ([project_dir / "assets" / "sfx"] if project_dir else []) + [ROOT / "library" / "sfx"]
    for d in dirs:
        for ext in (".wav", ".mp3", ".ogg", ".flac"):
            p = d / f"{name}{ext}"
            if p.exists():
                return p
    return None


@lru_cache(maxsize=64)
def _cached(name: str, sr: int, params: tuple, project_dir: str | None) -> np.ndarray:
    f = find_file(name, Path(project_dir) if project_dir else None)
    if f:
        from .audio_mix import decode
        return decode(f, sr)
    gen = GENERATORS.get(name)
    if not gen:
        raise KeyError(f"Unknown sound effect '{name}'. Built-in: {', '.join(sorted(GENERATORS))}")
    return gen(sr=sr, **dict(params))


def get_sfx(name: str, sr: int = SR, project_dir: Path | None = None, **params) -> np.ndarray:
    return _cached(name, sr, tuple(sorted(params.items())), str(project_dir) if project_dir else None)
