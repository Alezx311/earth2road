# BeamNG presentation captures

`tools/beamng_assembly.py` prepares an isolated presentation copy of an existing
BeamNG export. Normal exports, installed mods, source worlds and user settings are
not edited. Drafts and generated media belong in ignored `posts/`.

Requires the project's venv (Pillow, Shapely, imageio-ffmpeg), Windows, and an
installed BeamNG. The runtime Lua module uses the same screenshot/free-camera APIs
as `beamng_promo.lua`. Do not run concurrent captures on one GPU.

## Scene

Save JSON containing `kind` (`junction` or `street`), a v2 `junction` ID from
`roadgen_report.json`, `center` in **BeamNG XYZ** including the export's vertical
offset, `radius` in metres, and camera `heading` (degrees from +X), `distance`,
`height` (metres relative to center). The world and export must be from the same
build, with socket details in the report. The captured export uses identity
rotation and scale for generated surface chunks.

```powershell
.venv/Scripts/python.exe tools/beamng_assembly.py prepare --world out/example-world --export out/example-beamng --scene posts/scene.json --output posts/take-01
.venv/Scripts/python.exe tools/beamng_assembly.py capture --output posts/take-01 --sample-times 0 3.5 8 12 17 24
```

Inspect the probe. Prepare another fresh output for a full take, then:

```powershell
.venv/Scripts/python.exe tools/beamng_assembly.py capture --output posts/take-02
.venv/Scripts/python.exe tools/beamng_assembly.py encode --input posts/take-02/user/current/screenshots/assembly --output posts/video/junction-25s.mp4 --kind junction
```

The full take is 750 frames at 30 fps (25 seconds). `capture` checks process status,
Lua completion, missing objects and frame count. It refuses to overwrite captures.
Runtime evidence is in `result.json`, `preparation.json`, the isolated engine log
and screenshots. Launch requires normal desktop/GPU access outside a restrictive
sandbox. Only the process started by this tool may be terminated on timeout.

`prepare --static` copies the original export without partitioning for visual
control shots. Optional `views: [{pos: [x,y,z], look: [x,y,z]}]` uses view N at
sample time N-1; supply `--sample-times 0 1 2` for three views.

## What the animation represents

This is a visual replay, not a recording of generation time or physical road
construction. Source COLLADA triangles are grouped by material and 8 m centroid
cells. Long triangles are not subdivided. Socket boundaries distinguish the
selected core and transition areas; other road pieces are spatial groups.
Every original position, normal, UV and material is retained literally, including
duplicate triangles. The test compares expanded triangle multisets, not just counts.

Parts descend from above onto their original positions. Original terrain stays
visible; scenery and engine-batched forests appear near the end. Physics is paused
and split presentation meshes have no collision, so this copy is **not a playable
release artifact**. A completed capture proves visual loading only, not driving
quality, performance, AI correctness or whole-map acceptance.

The default captions clearly identify BeamNG and say that this is an assembly
visualization, not generation time. The captions include OSM/Terrain attribution.
The current Ukrainian edit is dated 06.10.2026; update its labels for a new devlog.
