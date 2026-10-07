# Scenario template

Copy into an ignored post bundle and replace the prompts with measured values.

- **Working title / audience / language:**
- **One visual idea:** what becomes recognizable and why it shows Earth2Road's value.
- **Location:** coordinates, coverage, new build or existing artifact.
- **Inputs:** world path, export path, map ID, ZIP SHA-256, source snapshot date.
- **Reference:** source page, file, creator, photo date, terms, credit text, SHA-256.
- **Camera evidence:** EXIF vs estimates; coordinate transform and vertical offset.
- **Photo crop:** normalized `[left, top, width, height]`; no stretching/warping.
- **Anchors:** at least four features with normalized photo positions, world
  positions, visible game positions and mismatch notes. Do not invent coordinates.

| Time | Visible action | Camera / scene setting | Purpose |
|---|---|---|---|
| 0–2 s | Real photograph | Fixed agreed crop | Recognizable place |
| 2–18 s | Assembly replay | Matched position/look/FOV | Geography becomes a map |
| 18–25 s | Finished map | Smooth retreat, reveal city blocks | Scale |

- **Scene JSON:** link to the configuration used by `beamng_assembly.py`.
- **Sound / overlays:** default none.
- **Post:** title, short description, assembly disclosure and source credits.
- **Probe rounds:** settings changed, comparison evidence, accept/reject; maximum 3.
- **QA:** capture result, actual frame size/count, decode result, visual review,
  known defects, final video path. Distinguish planned from observed behavior.
- **Publication:** separate request; nothing uploaded by default.
