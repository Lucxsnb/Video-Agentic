"""Audio I/O and mixing (numpy + FFmpeg).

Phase 1: place voice clips on the timeline, export WAV. SFX/music/ducking come in Phase 5.
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np


def decode(path: str | Path, sr: int = 48000) -> np.ndarray:
    """Decode any audio file to mono float32 at `sr` via FFmpeg."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def write_wav(path: str | Path, samples: np.ndarray, sr: int = 48000) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def db_to_gain(db: float) -> float:
    return float(10 ** (db / 20.0))


def mix_timeline(clips: list[tuple[float, Path, float]], total: float, sr: int = 48000) -> np.ndarray:
    """clips: (start_seconds, wav_path, gain_db). Returns mono float32 buffer."""
    buf = np.zeros(int(np.ceil(total * sr)) + 1, dtype=np.float32)
    for start, path, gain_db in clips:
        s = decode(path, sr) * db_to_gain(gain_db)
        i0 = max(0, int(round(start * sr)))
        i1 = min(len(buf), i0 + len(s))
        if i1 > i0:
            buf[i0:i1] += s[: i1 - i0]
    return buf


def envelope(x: np.ndarray, sr: int, win: float = 0.02) -> np.ndarray:
    """RMS envelope sampled every `win` seconds."""
    hop = max(1, int(win * sr))
    n = max(1, len(x) // hop)
    return np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)


def duck_gain(voice: np.ndarray, sr: int, depth_db: float = -10.0, threshold_db: float = -40.0,
              attack: float = 0.08, release: float = 0.4, win: float = 0.02) -> np.ndarray:
    """Per-sample gain for the music: drops by depth_db while the voice is active."""
    env = envelope(voice, sr, win)
    active = 20 * np.log10(env) > threshold_db
    low = db_to_gain(depth_db)
    g = np.ones(len(env), dtype=np.float32)
    cur = 1.0
    a = 1 - np.exp(-win / max(attack, 1e-3))
    r = 1 - np.exp(-win / max(release, 1e-3))
    for i, on in enumerate(active):
        target = low if on else 1.0
        cur += (target - cur) * (a if target < cur else r)
        g[i] = cur
    xs = (np.arange(len(env)) + 0.5) * win * sr
    return np.interp(np.arange(len(voice)), xs, g).astype(np.float32)


def place(buf: np.ndarray, x: np.ndarray, start: float, sr: int, gain: float = 1.0) -> None:
    i = int(round(start * sr))
    if i < 0:
        x, i = x[-i:], 0
    j = min(len(buf), i + len(x))
    if j > i:
        buf[i:j] += x[: j - i] * gain
