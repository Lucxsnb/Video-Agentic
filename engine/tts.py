"""Text-to-speech with per-word timestamps and on-disk cache.

Backends (tried in the order of style.tts.backends):
  edge   -> edge-tts (online, free). Word timestamps from WordBoundary events.
  piper  -> Piper CLI (offline). Needs library/voices/piper/<model>.onnx.
  espeak -> espeak-ng (offline, robotic). Last resort.
Non-edge backends get timestamps from faster-whisper if installed, otherwise an
energy-based estimate.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from . import audio_mix
from .config import resolve_path

SR = 48000


@dataclass
class Word:
    text: str      # token as written in the script (with punctuation)
    start: float   # seconds, relative to clip start
    end: float


@dataclass
class Speech:
    wav: Path
    duration: float
    words: list[Word]
    backend: str
    voice: str


class TTSError(RuntimeError):
    pass


def tokenize(text: str) -> list[str]:
    return [t for t in text.split() if t.strip()]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


# --------------------------------------------------------------------------- edge
def _edge(text: str, voice: str, rate: str, pitch: str, out_wav: Path) -> list[tuple[str, float, float]]:
    try:
        import edge_tts
    except ImportError as e:  # pragma: no cover
        raise TTSError("edge-tts not installed") from e

    async def run():
        kw = {"boundary": "WordBoundary"}
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:
            kw["proxy"] = proxy
        com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, **kw)
        audio = bytearray()
        bounds = []
        async for ch in com.stream():
            if ch["type"] == "audio":
                audio.extend(ch["data"])
            elif ch["type"] == "WordBoundary":
                st = ch["offset"] / 1e7
                bounds.append((ch["text"], st, st + ch["duration"] / 1e7))
        return bytes(audio), bounds

    try:
        audio, bounds = asyncio.run(run())
    except Exception as e:
        raise TTSError(f"edge-tts failed: {type(e).__name__}: {e}") from e
    if not audio:
        raise TTSError("edge-tts returned no audio")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio)
        mp3 = f.name
    try:
        audio_mix.write_wav(out_wav, audio_mix.decode(mp3, SR), SR)
    finally:
        os.unlink(mp3)
    return bounds


# -------------------------------------------------------------------------- piper
def _piper(text: str, voice: str, voices_cfg: dict, out_wav: Path) -> None:
    exe = shutil.which("piper")
    if not exe:
        raise TTSError("piper not installed")
    model_name = voices_cfg.get("catalog", {}).get(voice, {}).get("piper")
    models_dir = resolve_path(voices_cfg.get("piper", {}).get("models_dir", "library/voices/piper"))
    model = models_dir / f"{model_name}.onnx" if model_name else None
    if not model or not model.exists():
        cands = sorted(models_dir.glob("*.onnx")) if models_dir.exists() else []
        if not cands:
            raise TTSError(f"no piper model in {models_dir}")
        model = cands[0]
    tmp = out_wav.with_suffix(".raw.wav")
    subprocess.run([exe, "--model", str(model), "--output_file", str(tmp)],
                   input=text.encode(), check=True, capture_output=True)
    audio_mix.write_wav(out_wav, audio_mix.decode(tmp, SR), SR)
    tmp.unlink(missing_ok=True)


# ------------------------------------------------------------------------- espeak
def _espeak(text: str, voice: str, voices_cfg: dict, out_wav: Path) -> None:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        raise TTSError("espeak-ng not installed")
    info = voices_cfg.get("catalog", {}).get(voice, {})
    ecfg = voices_cfg.get("espeak", {})
    gender = info.get("gender", "male")
    ev = info.get("espeak") or ecfg.get(f"default_{gender}", "en-us")
    pitch = str(info.get("espeak_pitch", 50))
    tmp = out_wav.with_suffix(".raw.wav")
    subprocess.run([exe, "-v", ev, "-s", str(ecfg.get("speed", 160)), "-p", pitch, "-w", str(tmp), text],
                   check=True, capture_output=True)
    audio_mix.write_wav(out_wav, audio_mix.decode(tmp, SR), SR)
    tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------- alignment
def _align_whisper(wav: Path, tokens: list[str]) -> list[tuple[str, float, float]] | None:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    try:
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(str(wav), word_timestamps=True, language="en")
        return [(w.word.strip(), w.start, w.end) for s in segs for w in (s.words or [])]
    except Exception:
        return None


def _align_estimate(wav: Path, tokens: list[str]) -> list[Word]:
    """Spread words over the voiced span, weighted by length + punctuation pauses.

    Uses detected internal silences as anchors for sentence/comma breaks.
    """
    y = audio_mix.decode(wav, SR)
    hop = int(0.01 * SR)
    n = max(1, len(y) // hop)
    rms = np.sqrt(np.mean(y[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    thr = max(rms.max() * 0.06, 1e-4)
    voiced = np.where(rms > thr)[0]
    if len(voiced) == 0:
        dur = len(y) / SR
        step = dur / max(1, len(tokens))
        return [Word(t, i * step, (i + 1) * step) for i, t in enumerate(tokens)]
    t0, t1 = voiced[0] * 0.01, (voiced[-1] + 1) * 0.01

    def weight(tok: str) -> float:
        letters = len(norm(tok)) or 1
        vowels = len(re.findall(r"[aeiouy]+", tok.lower())) or 1
        return 0.6 * vowels + 0.15 * letters + 0.25

    def pause(tok: str) -> float:
        if tok[-1:] in ".!?":
            return 1.6
        if tok[-1:] in ",;:":
            return 0.9
        return 0.0

    ws = [weight(t) for t in tokens]
    ps = [pause(t) for t in tokens[:-1]] + [0.0]
    total = sum(ws) + sum(ps)
    scale = (t1 - t0) / total
    out, cur = [], t0
    for tok, w, p in zip(tokens, ws, ps):
        out.append(Word(tok, cur, cur + w * scale))
        cur += (w + p) * scale
    return out


def _merge_to_tokens(tokens: list[str], bounds: list[tuple[str, float, float]], dur: float) -> list[Word] | None:
    """Map backend word boundaries onto the script's whitespace tokens."""
    if not bounds:
        return None
    words: list[Word] = []
    bi = 0
    for tok in tokens:
        target = norm(tok)
        if not target:  # pure punctuation like "—"
            prev_end = words[-1].end if words else 0.0
            words.append(Word(tok, prev_end, prev_end))
            continue
        if bi >= len(bounds):
            return None
        start, end, acc = bounds[bi][1], bounds[bi][2], norm(bounds[bi][0])
        bi += 1
        while len(acc) < len(target) and bi < len(bounds) and target.startswith(acc):
            acc += norm(bounds[bi][0])
            end = bounds[bi][2]
            bi += 1
        words.append(Word(tok, start, min(end, dur)))
    return words


# --------------------------------------------------------------------------- API
def resolve_voice(voice: str | None, gender: str | None, voices_cfg: dict, role: str = "narrator") -> str:
    if voice:
        return voice
    d = voices_cfg.get("defaults", {})
    if role == "narrator":
        return d.get("narrator", "en-US-AndrewNeural")
    return d.get(gender or "male", d.get("narrator", "en-US-AndrewNeural"))


def synthesize(text: str, voice: str, cache_dir: Path, style: dict, voices_cfg: dict,
               backends: list[str] | None = None, rate: str | None = None,
               pitch: str | None = None) -> Speech:
    tcfg = style.get("tts", {})
    backends = backends or tcfg.get("backends", ["edge", "piper", "espeak"])
    rate = rate or tcfg.get("rate", "+0%")
    pitch = pitch or tcfg.get("pitch", "+0Hz")
    align = tcfg.get("align", "auto")
    tokens = tokenize(text)
    cache_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    for backend in backends:
        key = hashlib.sha1(json.dumps([text, voice, rate, pitch, backend, align]).encode()).hexdigest()[:16]
        wav, meta = cache_dir / f"{key}.wav", cache_dir / f"{key}.json"
        if wav.exists() and meta.exists():
            m = json.loads(meta.read_text())
            return Speech(wav, m["duration"], [Word(**w) for w in m["words"]], backend, voice)
        try:
            bounds = None
            if backend == "edge":
                bounds = _edge(text, voice, rate, pitch, wav)
            elif backend == "piper":
                _piper(text, voice, voices_cfg, wav)
            elif backend == "espeak":
                _espeak(text, voice, voices_cfg, wav)
            else:
                raise TTSError(f"unknown backend {backend}")
        except (TTSError, subprocess.CalledProcessError) as e:
            errors.append(f"{backend}: {e}")
            wav.unlink(missing_ok=True)
            continue
        dur = audio_mix.duration(wav)
        words = None
        if bounds and align in ("auto", "edge"):
            words = _merge_to_tokens(tokens, bounds, dur)
        if words is None and align in ("auto", "whisper"):
            words = _merge_to_tokens(tokens, _align_whisper(wav, tokens) or [], dur)
        if words is None:
            words = _align_estimate(wav, tokens)
        meta.write_text(json.dumps({"text": text, "voice": voice, "backend": backend,
                                    "duration": dur, "words": [asdict(w) for w in words]}, indent=1))
        return Speech(wav, dur, words, backend, voice)
    raise TTSError("All TTS backends failed:\n  " + "\n  ".join(errors))
