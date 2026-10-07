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

## Director captures (portable, no captions)

Read [DIRECTOR.md](DIRECTOR.md) for the editorial/source workflow. Existing
junction/street scenes and captioned encoding retain their behavior.

`kind: "city"` animates the existing export's TSStatic batches without splitting
or rewriting their meshes, so it also supports legacy worlds without a v2 junction
report. Terrain and the generated ground
meshes (`__kyiv_ground_`) remain visible from the first frame. Roads resolve at 0–7 s, buildings at 5–15 s,
props at 12–16 s, forests at 16 s. This is a staged replay, not generation time.
Use a radius covering the desired district; batching can straddle its boundary.

Optional `resolution: [1080,1920]` sets the output frame size. BeamNG 0.39.4 measured
(07.10.2026): a window cannot be taller than the desktop (1080×1920 on a 1440p screen
became 3620×1421), cannot be narrower than 13:20 (540×960 became 624×960), and
`createScreenshot2` `superSampling` multiplies the **pixel count** (×2 gave ×√2 per side).
So set `supersampling: 2` (a per-axis factor k): the tool opens a 624×960 window, passes
k² = 4 to the engine and captures 1248×1920; `director_edit.py` crops the centre
1080 columns without scaling. The vertical FOV, and a matched camera, are unchanged.
`capture` fails when the saved frame size differs from the expected capture size.
`camera_path` contains increasing keys `{time,pos,look,fov}`, starting at zero.
Positions/look targets use BeamNG XYZ; `fov` is the engine's **vertical** FOV in degrees
(verified by projecting known anchors onto a probe, 07.10.2026).
`tools/director_camera.py --world WORLD --export EXPORT --lon LON --lat LAT
--altitude METRES` converts an estimated absolute GPS camera altitude and position
using that world's projection and the export's vertical offset.
Hold a shot by repeating its pose at a later time; smoothstep interpolates the
next segment. `capture` writes the exact sampled `camera_frames` into the profile
config, including at arbitrary `--sample-times`. The path overrides legacy views.
Probe the actual result before recording a complete take: OS window limits or
engine version can affect resolution/FOV. Never silently stretch a mismatched take.

```powershell
.venv/Scripts/python.exe tools/beamng_assembly.py prepare --world out/world --export out/export --scene posts/scene.json --output posts/probe --static
.venv/Scripts/python.exe tools/beamng_assembly.py capture --output posts/probe --sample-times 0 16 23
# Prepare a separate fresh animated take after accepting the probe.
.venv/Scripts/python.exe tools/beamng_assembly.py capture --output posts/take --frames 690
.venv/Scripts/python.exe tools/beamng_assembly.py encode --input posts/take/user/current/screenshots/assembly --output posts/clean.mp4 --clean
.venv/Scripts/python.exe tools/director_edit.py --recipe posts/edit.json --output posts/final.mp4
```

The edit JSON contains `photo`, `frames` (paths relative to the recipe),
`frame_count`, `resolution`, normalized `crop: [left,top,width,height]`,
`photo_seconds` (default 2), `transition_seconds` (default .4), `credit` and
`source_url`. Crop aspect must match the output. Photo and capture are blended
without captions or audio; credits are also stored as MP4 metadata, which does
not replace the accompanying public source credits. Preserve the original photo.
