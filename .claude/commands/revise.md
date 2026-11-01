---
description: Change an existing video (script, staging, assets, audio) and re-render
argument-hint: <project slug or path> <what to change>
---
Revise a video. Arguments: $ARGUMENTS
(the first argument is the project — `projects/<slug>` or just `<slug>` — the rest is the requested change, usually in Portuguese).

1. Read `projects/<slug>/screenplay.json`, `previews/report.txt` and the latest `output/timeline.json`.
2. Restate the requested change in one line. If it is ambiguous, ask before editing.
3. Edit only what is needed (screenplay and/or assets). Keep everything else identical so cached voices are reused.
   If a reusable library asset changes, make sure other projects that use it are not broken (or copy it into
   `projects/<slug>/assets/` and change it there).
4. `python scripts/validate.py projects/<slug> --audio` → no errors.
5. `python scripts/preview.py projects/<slug> --shots <changed scene ids>` (or the whole video if timing moved);
   open the contact sheet and check the change looks right and nothing else broke.
6. `python scripts/make_video.py projects/<slug>`; open `output/check/random_frames.png`.
7. Report in Portuguese: what changed, new duration, anything to watch.
