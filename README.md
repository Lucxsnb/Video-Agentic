# Video Agent

Turns a story or prompt (any language) into a finished **vertical English video** (1080x1920, 30 fps, H.264 + AAC) for Reels / TikTok / Shorts. 100% free tools: skia-python, FFmpeg, edge-tts.

## Status

| Phase | What | State |
|---|---|---|
| 1 | Background + kinetic captions + TTS with word timestamps + mux | ✅ |
| 2 | Rigged characters, poses, expressions, lip flap | ✅ |
| 3 | SVG props/sets, camera, lighting, transitions, parallel render | ✅ |
| 4 | Overlays (series badge + story clock, speaker tags, cards, poll, end card), tall body variant | ✅ |
| 5 | Procedural SFX (auto + manual), procedural/own music with ducking, stems | ✅ |
| 6 | Agent: CLAUDE.md, slash commands, validate, preview + auto composition checks, output check, post.txt | ✅ |
| 7 | End-to-end test: `projects/zombie-outbreak-ep13` (61 shots, 2:57) | ✅ |

## Using the agent (Claude Code)

Open this folder in Claude Code and use:

- `/new-video <story file or text>` — full pipeline: script in English → screenplay → assets → validate → preview (Claude looks at the frames) → render → final check → report.
- `/revise <project> <what to change>` — edits only what's needed and re-renders.
- `/next-episode <project> <winning poll option>` — next episode of a series, keeping continuity (`series/<slug>/bible.md`).

`CLAUDE.md` holds the permanent instructions (workflow, script rules, shot cookbook, composition rules, asset conventions).

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
python scripts/new_project.py story.md --slug my-video          # or --series zombie-outbreak --episode 13
python scripts/validate.py projects/my-video --audio             # schema, assets, references, timing
python scripts/preview.py projects/my-video                      # keyframes + contact sheet + composition report
python scripts/make_video.py projects/phase1-test                # render (+ automatic final check)
python scripts/check_output.py projects/phase1-test              # format, loudness, SRT sync, random frames
python scripts/make_video.py projects/phase1-test --tts espeak      # force a backend
python scripts/make_video.py projects/phase1-test --max-seconds 5   # quick partial render
python scripts/make_video.py projects/phase3-test --workers 1       # disable parallel rendering
python scripts/character_sheet.py delivery_guy store_manager --mode poses --rig tall --out sheet.png   # or --mode expressions
python -m unittest discover tests
```

Output in `projects/<slug>/output/`: `final.mp4`, `captions.srt`, `post.txt`, `timeline.json` (shots, words, sound cues), `check/` (random frames).

## Project layout

```
CLAUDE.md                 agent instructions        .claude/commands/   /new-video /revise /next-episode
config/                   style.yaml, presets/, rig.yaml, rigs/, poses.yaml, expressions.yaml, music.yaml, voices.yaml
engine/                   schema, tts, characters, poses, props, backgrounds, camera, lighting, transitions,
                          captions, overlays, sfx, music, soundtrack, audio_mix, renderer, compose
library/                  characters/, props/, backgrounds/, fonts/, sfx/, music/, voices/
scripts/                  new_project, validate, preview, make_video, check_output, character_sheet
series/<slug>/bible.md    continuity notes per series
projects/<slug>/          story.md, screenplay.json, assets/, audio/ (cache, stems), previews/, output/
tests/                    python -m unittest discover tests
```

## How it works

1. `engine/schema.py` validates `screenplay.json`.
2. `engine/tts.py` synthesizes each line (edge-tts → Piper → espeak-ng), caches it in `projects/<slug>/audio/`, and gets per-word timestamps (edge WordBoundary → faster-whisper → energy-based estimate).
3. `engine/compose.py` sets each shot's length from its audio (+ `timing.pre_roll` / `breath_after`); `engine/soundtrack.py` mixes voice + sound effects + ducked music; the mix is normalized to −14 LUFS with a true-peak limiter.
4. `engine/renderer.py` records each frame's world (set → back props → actors → held props → lighting) while collecting anchors, applies the camera and transitions, then vignette → grain → captions, and pipes raw RGBA straight into FFmpeg.

### Characters (Phase 2)

- Reusable characters: `library/characters/<name>.json` (look, voice, label). The ones in the library are examples for tests; real characters are created per story/series. In a screenplay: `{"id": "courier", "library": "delivery_guy"}`; fields set in the screenplay override the library.
- Look: `skin`, `shirt`, `pants`, `hair`, `shoes`, `sleeves` (short/long), `build` (torso width), `height`, `accessories` (names from `config/rig.yaml`, or `kind:#color`, e.g. `cap:#2E8B57`).
- Poses (`config/poses.yaml`): idle, talk, point, hold, hold_both, hold_up, phone_ear, cross_arms, shrug, shock, run, hit, wave, nervous — joint angles + oscillations + keyframes.
- Expressions (`config/expressions.yaml`): neutral, happy, excited, worried, nervous, scared, shock, angry, sad, suspicious, confused, smug, determined, tired, embarrassed (+ extras: sweat, stubble, blush, shock lines, tear, anger).
- Automatic: blinking, breathing, lip flap from the speaker's voice loudness, head bob and gestures while talking. `facing` moves the eyes, `flip` mirrors.
- Each draw returns anchors (`hand_l`, `hand_r`, `head`, `head_top`, `mouth`, `chest`, `feet`) used by props in Phase 3.

### Props, sets, camera, lighting, transitions (Phase 3)

- **Props**: SVGs in `library/props/` (phone, phone_incoming_call, cardboard_sign, hammer, key, flashlight, cardboard_box, sack, bottle, sign). Placeholders `{{key|default}}` are filled from `params`; a `text` param auto-wraps into `{{line1..N}}` with auto-fit font size. `attach_to: "courier.hand_r"` keeps a prop in a hand; `layer: back` puts it behind actors; `anim`: ring, bob, pulse, swing, pop, drop.
- **Sets**: SVG backgrounds in `library/backgrounds/` (supermarket_aisle, storage_room, back_alley) or YAML layer sets. `blur` (scene/shot) gives depth of field.
- **Camera**: `zoom_in/zoom_out/pan_*/static`, `from`/`to` zoom, `target` (`"manager.head"`, `"phone1"`, `"flashlight1.tip"`) with `target_to` rack, `frame_y`, `shake`, `punch` (impact), `rotate` (dutch angle). Never shows outside the set.
- **Lighting** (scene/shot): `darkness` + `lights` (`spot` or flashlight `cone` from `"<prop>.tip"`), with flicker.
- **Transitions**: `transition_out`: cut, whip (motion-blur pan), flash, fade.
- `caption_y` per shot moves captions off a sign or a face.
- Presets: `miniseries` (bright) and `dark_miniseries` (moody night look: blurred sets, heavy vignette/grain, mid-low captions).
- Rendering runs in parallel processes (`render.workers`, default = CPU cores) and joins segments losslessly.

### Overlays and body variants (Phase 4)

- **Series badge** (top-left): `series.name` + episode, with an in-story **clock** (`series.clock`, changed per scene/shot with `clock`) or a running timer (`show_timer`). `"overlays": false` on a shot hides it (full-screen inserts).
- **Dialogue**: character lines get a colored **speaker pill** (`label`, `tag_color`, or automatic colors) and *italic* captions; narration stays upright.
- **Card** per shot: `{"title": "RULE #9", "text": "...", "highlight": [...], "at": 0.6}`.
- **Poll**: `ending.options` (text or `{text, detail}`); `"poll": [1]` / `[1, 2]` on shots reveals the numbered bars as the narrator explains them.
- **End card** (`ending.type` poll / cliffhanger / cta): headline (default "THE MAJORITY DECIDES"), big `badge` pill (e.g. "DAY 14"), `cta`, all options, optional narration `line`; drawn over the last set, blurred and darkened.
- **Phone insert**: set `phone_lockscreen` with `background_params` (`time`, `date`, `battery`...) + prop `notification` (`title`, `text`, `app`, `anim: pop`).
- **Body variants**: `config/rigs/<name>.yaml` deep-merged over `rig.yaml` (with `pose_overrides`). `tall` = taller figure, long limbs, smaller head/eyes; used by `dark_miniseries` (`character.rig`), or per character with `"rig": "tall"`.

### Audio (Phase 5)

- **Sound effects** (`engine/sfx.py`, numpy only): whoosh, pop, hit, boom, ring, vibrate, notify, riser, flash, tick, heartbeat, footstep, door_slam, drop. A file `library/sfx/<name>.wav|mp3` (or `projects/<slug>/assets/sfx/`) overrides the generator with the same name.
- **Manual cues** per shot: `"sfx": [{"name": "heartbeat", "at": 0.3, "volume": 0.8, "params": {"dur": 1.0}}]`.
- **Automatic cues** (`audio.auto_sfx`): whoosh on whip, flash on flash cuts, impact on camera `punch`, pop on cards / new poll options / popping props, ring for `anim: ring`, notify for the `notification` prop, boom under the end card. `"auto_sfx": false` turns them off for a shot.
- **Music**: `"music": {"mood": "tense"}` → procedural bed from `config/music.yaml` (tense, mystery, sad, upbeat, comedy, action), or your own track (`"file": "..."`, or any file in `library/music/<mood>/`), looped and faded. Level calibrated to the voice (`bed_db`), ducked under speech (`duck_db`). `dark_miniseries` defaults to `tense`.
- Stems are saved in `projects/<slug>/audio/stems/` (voice, sfx, music); the cue list is in `output/timeline.json`. Final mix normalized to −14 LUFS with a true-peak limiter.

All visual/timing values live in `config/style.yaml` (+ `config/presets/*.yaml`); character rig in `config/rig.yaml`, `poses.yaml`, `expressions.yaml`; voices in `config/voices.yaml`.

Fonts: Montserrat (SIL Open Font License, `library/fonts/OFL.txt`), Permanent Marker (Apache 2.0). They are registered with fontconfig automatically for SVG text (Linux/macOS).
