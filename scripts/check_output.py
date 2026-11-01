#!/usr/bin/env python3
"""Final check of a rendered video: format, audio, loudness, duration, subtitle sync, black frames,
plus 3 random frames (and a strip image) to look at.

    python scripts/check_output.py projects/<slug>
Exit code 1 on failures.
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import typer  # noqa: E402

from engine.compose import load_project  # noqa: E402

app = typer.Typer(add_completion=False)


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def loudness(path: Path) -> tuple[float | None, float | None]:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    p = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", err)
    return (float(i[-1]) if i else None), (float(p[-1]) if p else None)


def black_segments(path: Path, min_d: float = 0.5) -> list[tuple[float, float]]:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", f"blackdetect=d={min_d}:pix_th=0.06",
                          "-an", "-f", "null", "-"], capture_output=True, text=True).stderr
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    def ts(s):
        h, m, rest = s.split(":")
        sec, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            a, b = [x.strip() for x in lines[1].split("-->")]
            out.append((ts(a), ts(b), " ".join(lines[2:])))
    return out


def check(project: Path, n_frames: int = 3) -> tuple[list[str], list[str], dict]:
    fails, notes = [], []
    out = project / "output"
    video = out / "final.mp4"
    if not video.exists():
        return [f"{video} not found"], notes, {}
    sp, style, _ = load_project(project)
    v = style["video"]
    info = probe(video)
    vs = [s for s in info["streams"] if s["codec_type"] == "video"]
    aus = [s for s in info["streams"] if s["codec_type"] == "audio"]
    dur = float(info["format"]["duration"])
    if not vs:
        fails.append("no video stream")
    else:
        s = vs[0]
        if (s["width"], s["height"]) != (v["width"], v["height"]):
            fails.append(f"resolution {s['width']}x{s['height']} != {v['width']}x{v['height']}")
        num, den = s["r_frame_rate"].split("/")
        if abs(int(num) / int(den) - v["fps"]) > 0.01:
            fails.append(f"fps {s['r_frame_rate']} != {v['fps']}")
        if s["codec_name"] != "h264" or s.get("pix_fmt") != "yuv420p":
            fails.append(f"video codec {s['codec_name']}/{s.get('pix_fmt')} (expected h264/yuv420p)")
    if not aus:
        fails.append("no audio stream")
    elif aus[0]["codec_name"] != "aac":
        fails.append(f"audio codec {aus[0]['codec_name']} (expected aac)")
    lufs, peak = loudness(video)
    target = style["audio"]["target_lufs"]
    if lufs is None or abs(lufs - target) > 1.0:
        fails.append(f"loudness {lufs} LUFS (target {target})")
    if peak is not None and peak > -0.5:
        fails.append(f"peak {peak} dBFS (clipping risk)")
    tl_path = out / "timeline.json"
    total = None
    if tl_path.exists():
        tl = json.loads(tl_path.read_text())
        total = tl["total"]
        if abs(dur - total) > 0.15:
            fails.append(f"duration {dur:.2f}s != timeline {total:.2f}s")
        srt = parse_srt((out / "captions.srt").read_text(encoding="utf-8")) if (out / "captions.srt").exists() else []
        if not srt:
            fails.append("captions.srt missing or empty")
        words = [(w, a) for s in tl["shots"] for w, a, _ in s["words"]]
        prev_end = 0.0
        for a, b, text in srt:
            if b <= a:
                fails.append(f"SRT entry '{text}' has end <= start")
            if a + 0.01 < prev_end:
                fails.append(f"SRT entry '{text}' overlaps the previous one")
            if b > dur + 0.05:
                fails.append(f"SRT entry '{text}' ends after the video")
            prev_end = b
        # sync: every SRT entry must start within 0.1s of a spoken word
        starts = [a for _, a in words]
        for a, b, text in srt:
            if starts and min(abs(a - s) for s in starts) > 0.1:
                fails.append(f"SRT entry '{text}' at {a:.2f}s is not aligned with any spoken word")
    blacks = black_segments(video)
    for a, b in blacks:
        notes.append(f"black frames {a:.2f}-{b:.2f}s (expected only at fades)")
    # random frames
    chk = out / "check"
    chk.mkdir(exist_ok=True)
    rng = random.Random(int(dur * 1000))
    times = sorted(rng.uniform(0.3, max(0.4, dur - 0.3)) for _ in range(n_frames))
    paths = []
    for k, t in enumerate(times):
        p = chk / f"frame_{k + 1}_{t:.2f}s.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(p)],
                       check=True)
        paths.append(p)
    strip = chk / "random_frames.png"
    inputs = sum((["-i", str(p)] for p in paths), [])
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex",
                    f"hstack={len(paths)},scale={540 * len(paths)}:-1", str(strip)], check=True)
    summary = {"duration": round(dur, 2), "lufs": lufs, "peak": peak, "frames": [str(p) for p in paths],
               "strip": str(strip), "resolution": f"{vs[0]['width']}x{vs[0]['height']}" if vs else None}
    return fails, notes, summary


@app.command()
def main(project: Path):
    fails, notes, s = check(project)
    if s:
        typer.echo(f"{s['resolution']}  {s['duration']}s  {s['lufs']} LUFS  peak {s['peak']} dBFS")
    for n in notes:
        typer.echo(f"note    {n}")
    for f in fails:
        typer.echo(f"FAIL    {f}")
    if s:
        typer.echo(f"Random frames: {s['strip']}")
    typer.echo("OK" if not fails else f"{len(fails)} failure(s)")
    raise typer.Exit(1 if fails else 0)


if __name__ == "__main__":
    app()
