---
description: Create a new vertical video from a story file or text (full pipeline)
argument-hint: <story file or text> [--slug name] [--series slug --episode n]
---
Create a new video from: $ARGUMENTS

Follow the **Workflow** in CLAUDE.md from step 1 to step 9, without skipping the preview and check steps:

1. `python scripts/new_project.py <story> [--slug ...] [--series ... --episode ...]` (pick a short slug if none was given).
2. Read `projects/<slug>/story.md` (and the series bible + previous episode if it is a series).
3. If essential information is missing (tone/genre, target length, poll or not), ask the user briefly in Portuguese;
   otherwise choose sensible defaults and state them.
4. Write the English script and `screenplay.json` (with `post`), using the shot cookbook and composition rules.
5. Create/reuse characters, props and sets; check new ones visually.
6. `validate.py` (then `--audio`) until there are no errors and timing is in range.
7. `preview.py`, open `previews/contact_sheet.png`, fix every issue, repeat until clean.
8. `make_video.py`, open `output/check/random_frames.png`.
9. Report in Portuguese: path, duration, shots, TTS used, new library items, warnings, poll options.
