# Video Agent

Turns a story or prompt (any language) into a finished **vertical English video** (1080x1920, 30 fps, H.264 + AAC) for Reels / TikTok / Shorts. 100% free tools: skia-python, FFmpeg, edge-tts.

## Status

| Phase | What | State |
|---|---|---|
| 1 | Background + kinetic captions + TTS with word timestamps + mux | ✅ |
| 2 | Rigged characters, poses, expressions, lip flap | ✅ |
| 3 | SVG props/sets, camera, transitions | ⏳ |
| 4 | Overlays (series badge, timer, speaker tag, poll), grain/vignette polish | ⏳ |
| 5 | Procedural SFX, music + ducking | ⏳ |
| 6 | Agent: CLAUDE.md, slash commands, preview/validate | ⏳ |
| 7 | End-to-end test | ⏳ |

## Setup

Requires **Python 3.11+** and **FFmpeg** on PATH.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

- FFmpeg: macOS `brew install ffmpeg` · Ubuntu `sudo apt install ffmpeg` · Windows `winget install ffmpeg`
- Linux only, if `import skia` fails with `libEGL.so.1`: `sudo apt install libegl1 libgl1`
- Optional offline voice fallback: `sudo apt install espeak-ng` (robotic) or Piper (`pip install piper-tts` + a voice `.onnx` in `library/voices/piper/`).

## Usage

```bash
python scripts/make_video.py projects/phase1-test
python scripts/make_video.py projects/phase1-test --tts espeak      # force a backend
python scripts/make_video.py projects/phase1-test --max-seconds 5   # quick partial render
python scripts/character_sheet.py delivery_guy store_manager --mode poses --out sheet.png   # or --mode expressions
python -m unittest discover tests
```

Output in `projects/<slug>/output/`: `final.mp4`, `captions.srt`, `timeline.json`.

## How it works

1. `engine/schema.py` validates `screenplay.json`.
2. `engine/tts.py` synthesizes each line (edge-tts → Piper → espeak-ng), caches it in `projects/<slug>/audio/`, and gets per-word timestamps (edge WordBoundary → faster-whisper → energy-based estimate).
3. `engine/compose.py` sets each shot's length from its audio (+ `timing.pre_roll` / `breath_after`), mixes voice, normalizes to −14 LUFS with a true-peak limiter.
4. `engine/renderer.py` draws each frame with skia (background → vignette → grain → captions) and pipes raw RGBA straight into FFmpeg.

### Characters (Phase 2)

- Reusable characters: `library/characters/<name>.json` (look, voice, label). In a screenplay: `{"id": "courier", "library": "delivery_guy"}`; fields set in the screenplay override the library.
- Look: `skin`, `shirt`, `pants`, `hair`, `shoes`, `sleeves` (short/long), `build` (torso width), `height`, `accessories` (names from `config/rig.yaml`, or `kind:#color`, e.g. `cap:#2E8B57`).
- Poses (`config/poses.yaml`): idle, talk, point, hold, hold_both, hold_up, phone_ear, cross_arms, shrug, shock, run, hit, wave, nervous — joint angles + oscillations + keyframes.
- Expressions (`config/expressions.yaml`): neutral, happy, excited, worried, nervous, scared, shock, angry, sad, suspicious, confused, smug, determined, tired, embarrassed (+ extras: sweat, stubble, blush, shock lines, tear, anger).
- Automatic: blinking, breathing, lip flap from the speaker's voice loudness, head bob and gestures while talking. `facing` moves the eyes, `flip` mirrors.
- Each draw returns anchors (`hand_l`, `hand_r`, `head`, `head_top`, `mouth`, `chest`, `feet`) used by props in Phase 3.

All visual/timing values live in `config/style.yaml` (+ `config/presets/*.yaml`); character rig in `config/rig.yaml`, `poses.yaml`, `expressions.yaml`; voices in `config/voices.yaml`.

Fonts: Montserrat (SIL Open Font License, `library/fonts/OFL.txt`).
