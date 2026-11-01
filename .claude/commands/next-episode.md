---
description: Create the next episode of a series from the poll's winning option
argument-hint: <previous episode project> <winning option (number or text)> [extra notes]
---
Create the next episode. Arguments: $ARGUMENTS
(first argument: the previous episode project, e.g. `projects/zombie-outbreak-ep13`; then the winning poll option,
as a number or text; anything else is extra direction from the user).

1. Read the previous `screenplay.json` (series name/slug, episode, characters, clock, ending options) and
   `series/<series slug>/bible.md` (create it from the previous episodes if missing).
2. Resolve the winning option (number → `ending.options[n-1]`). If it doesn't match, ask the user.
3. Update the bible: previous episode summary, poll question, options and **winner**.
4. `python scripts/new_project.py "<short premise of the new episode>" --series <series slug> --episode <n+1>`,
   then write `story.md` with the premise you derived from the winning option and the user's notes.
5. Write the new `screenplay.json` keeping continuity (same `series`, `style_preset`, characters via library
   refs, voices, colors; `episode` + 1; clock continuing): open with a 1-line recap of the winning choice as the hook,
   escalate, and end with a new poll (2 options, `badge` = next episode, `cta`).
6. Continue with CLAUDE.md workflow steps 5–9 (assets, validate, preview + look, render + check, report in Portuguese).
