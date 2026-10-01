# TerraDrive handoff

## 2026-10-01 — `export_optimize`: profile of a 1 × 1 km map (Livoberezhna)

Goal: a BeamNG level for a whole Kyiv district. `kyiv_shuliavka` (8 × 8 km, 3.8 GB DAE,
13.5 M triangles) does not load on a 32 GB machine.

- Map `kyiv_livoberezhna_1km` (`tools/generate_map.py --lat 50.4515 --lon 30.5983 --size-km 1`,
  ~1.5 min). Exports `out/livo-balanced` (52 s, ZIP 14.9 MB) and `out/livo-legacy` (47 s, 13.4 MB).
- New `tools/beamng_profile.py <export> --area-km2 N [--json]`: per category, material,
  flat/vertical faces, triangles < 1 cm², DAE text bytes per attribute, scene objects.

Balanced, 1 km² (density is close to Shuliavka: 80 vs 59 MB DAE per km²):

| category | tris | verts | col tris | DAE MB |
|---|---|---|---|---|
| sidewalks | 112 k | 244 k | 72 k | 34.7 |
| surfaces | 120 k | 319 k | (visible) | 27.4 |
| ground | 37 k | 104 k | (visible) | 8.8 |
| markings | 33 k | 86 k | 0 | 7.6 |
| buildings | 7 k | 12 k | (visible) | 1.3 |

Findings:
1. **Kerb over-tessellation.** `kyiv_curb` is 97.5 k triangles for 3.3 k m², of which
   57 k are under 1 cm² (the 8 mm bevel ring and 14 cm kerb top are CDT-triangulated along
   every patch boundary). Concrete is 14 k triangles for 15 k m². The sidewalk stage takes 35 of 52 s.
2. **Vertices are hardly shared** (2.2–2.8 vertices per triangle) because every face has
   its own flat normal at 6 decimals. Unique positions at 1 mm are 30–35 % of the written
   vertices on surfaces/ground/sidewalks. Positions, normals and UVs are 90 % of DAE text.
3. Ground is 37 k triangles (8.8 MB/km²): a candidate for a native TerrainBlock heightmap.
4. Scene per km²: 942 TSStatic, 377 DecalRoad (4.7 k nodes), 2.6 k forest instances.

Three paths to test in order, each measured with the profiler on this map:
A. COLLADA writer: shared smooth normals on flat surfaces + mm/3-decimal positions.
B. Kerb rebuild: a boundary strip (top + face quads per segment) instead of CDT rings and bevel.
C. Ground → TerrainBlock heightmap (then markings/surface decimation if still needed).

### Path A — `--optimization compact` (COLLADA writer)

Same geometry as `balanced`; only `Mesh.write` changes (`_compact_geometry` in
`beamng_geometry.py`): positions rounded to 1 mm, normals smoothed across faces within
30° (`CREASE_DEG`; kerb/wall edges stay sharp), UVs at 4 decimals in the vertex key,
shortest number text, triangles collapsing at 1 mm dropped, Colmesh keyed by position only.
`balanced` stays the default until checked in BeamNG.

Livoberezhna 1 km² (`out/livo-compact`, 52 s like balanced):

| | balanced | compact |
|---|---|---|
| visual triangles | 310 k | 306 k (sidewalk slivers) |
| vertices | 767 k | 300 k (−61 %) |
| DAE / unpacked level | 80 MB / 81 MB | 24 MB / 27 MB (−70 %) |
| ZIP | 14.9 MB | 7.6 MB (−49 %) |

- Tests: 2 new in `test_beamng_optimization`; BeamNG suites 54 OK.
- **Not checked in BeamNG**: shading of smoothed normals, load time/RAM. Extrapolated
  Shuliavka 8 × 8 would be ~1.1 GB DAE instead of 3.8 GB; triangle count (and so
  collision/GPU load) is unchanged — that is path B/C.

### Path B — compact kerbs (`beamng_curbs.py`, also under `--optimization compact`)

- No 8 mm bevel: the visual kerb is the collider, so the separate sidewalk Colmesh is gone
  (`export_map` passes no collision mesh for `compact`; TSStatic uses the visible mesh).
- Patch outlines are densified to 2 m and then simplified (`simplify_patch` gained
  `xy_tolerance`; 1 cm XY, unchanged 2 mm Z), so long straight/flat edges keep no 2 m
  stations; layers are not re-segmentized. Kerb corner arcs: 1 cm sagitta. A ring that
  simplifies below 3 points keeps the original patch (crashed before the guard).
- Measured on saved `build_sidewalks` inputs for Livoberezhna (variants, sidewalk tris incl. Colmesh):
  balanced 183.5 k (25.5 s) → no bevel 71.8 k (14.3 s) → + 1 cm XY with 2 m step 52.0 k →
  densify-then-simplify 22.8 k (9.6 s).
- Height check vs balanced on 20 000 random points: median 0.2 mm, p99 19 mm, 2 % > 1 cm,
  max 1.6 m. The large ones are where two OSM sidewalks overlap at different heights
  (1.2 / 1.6 m near −8, 89): `vertex()` takes the nearest source triangle, so the height
  field itself is discontinuous there and neither mesh is "right". Exact-XY variants still
  reach 0.38 m. Steep top faces (slope > 15 %): balanced 380 m² (mostly the bevel),
  no-bevel exact 164 m², chosen variant 186 m².

Livoberezhna 1 km², A+B (`out/livo-compact`; A-only kept as `out/livo-compact-a`):

| | balanced | compact A | compact A+B |
|---|---|---|---|
| sidewalk tris (visual + Colmesh) | 112 k + 72 k | 108 k + 70 k | 22 k |
| all generated visual tris | 310 k | 306 k | 220 k |
| DAE / unpacked level | 80 / 81 MB | 24 / 27 MB | 15 / 19 MB |
| ZIP | 14.9 MB | 7.6 MB | 5.2 MB |
| export | 52 s | 52 s | 30 s (sidewalks 14 s) |

- Tests: `test_compact_kerb_is_its_own_collider_and_lighter`; BeamNG suites 55 OK.
  `tools/export_beamng.py --validate` passes for balanced and compact.
- Pre-existing, not from this branch: `python -m akadem_maps validate --target beamng` on a
  `tools/export_beamng.py --map` ZIP fails with "Materials without level prefix" (only the
  `--world` path namespaces materials); and `.venv` holds a non-editable copy of
  `akadem_maps`, so `.venv/Scripts/terra-drive` runs stale code (it still rejects licence plates).
- Now the largest category is road surfaces (120 k tris, 46 % of DAE) — path C.
- **Not checked in BeamNG**: kerb look without bevel, kerb/wheel collision, load time/RAM.

### Separate variants: `--optimization balanced+writer|kerbs|terrain`

`--optimization` now composes features with `+` (`optimization_mode`/`features` in
`beamng_geometry.py`): `writer` (A), `kerbs` (B), `terrain` (C); `compact` = all three.
`balanced` (default) and `legacy` are unchanged. Accepted by `terra-drive export`,
`tools/export_beamng.py` and `tools/export_beamng_gui.py`.

### Path C — `terrain`: ground as a native TerrainBlock (`GroundTerrain`, `beamng_terrain.py`)

- Tile ground triangles are rasterised (vectorised numpy, batched by span) into a
  power-of-two heightmap from the bounds' min corner: 1 m cells up to 4096 cells, then
  stretched cells (`terrain_grid`: 8.3 km → 4096 × 2.25 m). Holes (roads, buildings) are
  filled from their edges; beyond the data the edge repeats.
- Every other surface mesh (roads, junctions, parking, greens, sidewalks) is a cap: within
  one cell of a cap the terrain is pulled 5 cm (`SINK`) below its lowest point. Heights are
  quantised with floor(). It replaces the ground meshes and the low substrate
  (`ground.ter`, `KyivGroundTerrain`); grass + dirt detail TerrainMaterial (11 m / 2 m).
- Livoberezhna: 2048² at 1 m, 1.8 s. Measured against the balanced meshes' vertices:
  never above any road/sidewalk/green vertex (max −0.05 m); vs ground vertices median
  −6 cm (most ground vertices border roads), p99 +5 mm, 0.15 % more than 2 cm above.
- Source data defect, also in balanced: ground/road vertices at −174…+66 m near (−420, 118)
  and a building at −126 m; they set maxHeight 227 m (3.5 mm steps).
- Expected look issue to check in game: a shallow trench (≤ 1 cell wide) along road and
  sidewalk edges where the terrain dips under the mesh.
- Failed experiment: a Python edit written with the cp1251 default emptied
  `beamng_terrain.py` and put cp1251 dashes in `beamng_geometry.py`; both restored, all
  touched files checked as UTF-8. Use `encoding='utf-8'` for scripted edits on this machine.

### All variants, Livoberezhna 1 km² (`out/livo-variants/livo_<variant>.zip`, distinct level IDs)

| variant | visible tris | vertices | static collision tris | DAE MB | .ter MB | level MB | ZIP MB |
|---|---|---|---|---|---|---|---|
| 0 balanced (reference) | 310 k | 767 k | 237 k | 80.1 | — | 83.3 | 14.8 |
| A writer | 306 k | 301 k | 235 k | 24.0 | — | 27.2 | 7.6 |
| B kerbs | 221 k | 582 k | 188 k | 50.4 | — | 53.6 | 9.1 |
| C terrain | 273 k | 663 k | 200 k + terrain | 71.3 | 12.6 | 87.0 | 14.5 |
| A+B+C compact | 184 k | 177 k | 150 k + terrain | 12.6 | 12.6 | 28.3 | 5.5 |

Full suite `python -m unittest discover -s tests`: 337 run, OK (1 skipped), 377 s (`logs/export-optimize-unittest.log`).
Static collision = TSStatic Colmesh or visible mesh (markings excluded). C gains little
at 1 km (ground is 11 % of DAE here) but on Shuliavka ground was 1.65 M triangles.
 (`--optimization balanced|legacy`)

Started by Codex (ran out of quota mid-benchmark), finished by Claude.

- `balanced` is the default for `terra-drive export`, `tools/export_beamng.py` and the GUI tool;
  `legacy` keeps the previous writer and geometry.
- `Mesh.write` streams indexed COLLADA: only identical (position, normal, UV) tuples at the
  legacy six decimals are shared, so expanded triangles equal the legacy output exactly.
- `simplify_ground` (`adapters/beamng/optimization.py`) replaces interior vertex fans that lie
  in a ≤5 cm slab; boundary/tile/material edges stay exact, uncertain topology is kept.
  Ground is now its own `kyiv_ground` chunk set instead of part of `kyiv_surface`.
- Sidewalks: collinear boundary stations removed only when the height profile agrees (RDP,
  2 mm Z); arc segment count from a 2 mm sagitta bound; a separate `Colmesh-1` collision mesh
  without the bevel. Walk cells with no collider triangles get `collisionType: None`
  (previously an empty `Collision Mesh`).
- Stock lamp/highway-lamp/guardrail instances switch to `Collision Mesh` (Codex: those shapes
  ship a Colmesh-1). **Not verified in BeamNG** — check lamps still collide in-game.
- `performance.json` (per-category triangles/vertices/bytes, stage timings) goes to
  `reports/` (world/GUI export) or beside `--map` output. It is outside the deterministic ZIP.
- Claude: removed unused `MeshSpool`/`sink` plumbing; sped up the indexed writer's key
  (normal rounded once per triangle). ZIP content was byte-identical before/after this change.

Checks (tiny, `tools/export_beamng.py --map tiny`):

| | legacy | balanced |
|---|---|---|
| collision triangles (generated) | 109 467 | 78 488 (−28%) |
| DAE vertices | 330 777 | 180 509 (−45%) |
| unpacked level | 28 MB | 17 MB |
| ZIP | 3.81 MB | 3.71 MB |
| export time | 20 s | 22 s (sidewalk stage +2–3 s) |

- BeamNG tests (`test_beamng_optimization`, `_export`, `_curbs`, `_gui`): 52 OK.
- Full `.venv/Scripts/python.exe -m unittest discover -s tests`: 331 run, OK (1 skipped),
  343.5 s. Log: `logs/beamng-opt-unittest.log`.
- No BeamNG runtime test. Codex's interrupted attempt left `out/beamng-stage-a362…`
  (ignored, safe to delete).

Real map `kyiv_shuliavka` (sequential runs, same machine; `out/cmp-shul-*`, `logs/cmp-shul-*`):

| | legacy | balanced |
|---|---|---|
| collision triangles (generated) | 13.55 M | 10.84 M (−20%) |
| DAE vertices | 43.4 M | 42.7 M (−1.6%) |
| DAE bytes / unpacked | 3.81 GB / 3.7 GB | 3.80 GB / 3.7 GB |
| ZIP | 595 MB | 685 MB (**+15%**) |
| export time | 44 min | 52 min (**+18%**; sidewalks 32→38 min) |

- The tiny-map gains mostly do not carry over. Ground reduction is ~0.4% here
  (1.657 M → 1.651 M triangles) versus 18% on tiny. The sidewalk collision mesh
  (4.0 M triangles) adds more vertices than indexing saves (20.1 M → 22.1 M), and the ZIP
  grows. The real win is −20% static collision triangles (sidewalk visual 6.70 M → collision 4.00 M).
- Before making `balanced` the default for large maps, consider: dropping UV/normal
  attributes from Colmesh geometry, finding out why `simplify_ground` rejects real fans
  (probably fan size >12 or ear-clipping dropping collinear points), and the export-time regression.
- Remaining: balanced sidewalks are slower (height evaluation of all boundary stations in
  `simplify_patch`, extra collision layers); in-game FPS/physics not measured.

## 2026-10-01 — BeamNG ZIP export from the map menu

- Maps now has an **Export to BeamNG…** action beside each installed map. The modal
  selects/persists an output folder, shows stages and elapsed time, supports cancellation,
  and offers Open folder / Copy ZIP path on success. English and Ukrainian; ZIP only,
  no BeamNG installation or launch. Exporting does not load or activate the selected map.
- `tools/export_beamng_gui.py` exports the installed snapshot through the existing adapter,
  checks the network hash, namespaces resources, separates technical reports, validates the
  ZIP and publishes a unique run directory atomically. It preserves the installed name and
  attribution rather than labelling every map as Kyiv. Sources and earlier exports stay intact.
  JSONL events and per-run logs live under ignored `logs/`; the default output is `out/beamng`.
- The adapter's optional `emit` callback reports actual stages without invented percentages.
  Process ownership/cancellation reuses generator lifecycle handling. The UI waits for process
  exit before accepting a terminal result; a completed export wins a late cancel request.
- Fixed a validator mismatch exposed by the new path: Ukrainian ZIPs contain generated
  `vehicles/common/licenseplates/<level_id>/` artwork. ZIP validation now accepts that
  level's plates while rejecting other level IDs and unrelated vehicle paths.

Checks:
- `tests.test_beamng_export`: 32 passed. New `tests.test_beamng_gui`: 6 passed, including
  real reproducible ZIPs, Unicode/spaced paths, unchanged sources, repeat exports, missing
  data/hash mismatch, cancellation/failure cleanup, packaging failure and bad destinations.
- Full `.venv/Scripts/python.exe -m unittest discover -s tests -v`: 327 run in 349.945 s;
  324 passed, 1 skipped, 1 failure and 1 error under the sandbox. The two failures were
  existing Godot subprocess checks (vehicle availability native crash; asset smoke timeout).
  Both passed individually outside the sandbox (0.466 s / 0.635 s). Full-run log:
  `logs/beamng-gui-unittest.log`. Do not describe the original full run as passing.
- Godot import passed. `validate_beamng_export.gd --runtime` passed headless and in rendered
  1280×720 / 1920×1080 windows: tiny ZIP, retry after missing data, immediate cancellation,
  partial JSONL reads, search filtering, focus/Escape and duplicate-start prevention.
  The final 1920×1080 run also checks removal of the export UI stops its child process.
  EN/UK screenshots under `logs/qa-beamng-ui/` were inspected.
- Follow-up: folder chooser opening/selection and final styling passed at 1280×720;
  the 6 Python tests passed again after strengthening cancellation coverage to interrupt
  the actual geometry stage rather than mocking the exporter entry point.
- Existing `validate_ui.gd --offline` on tiny passed outside the sandbox; Godot's dummy
  renderer printed RID/mesh warnings but the UI assertions completed with no failures.
- Failed experiments: first headless launch without an explicit writable log crashed in
  Godot before the script; retry with an explicit log passed. The existing UI harness could
  not write its `user://` fixture inside the sandbox and stalled; its owned test process was
  stopped and the same harness passed outside the sandbox. No user's game was stopped.
- Source publication check passed. No BeamNG runtime test or real-map geometry certification
  was performed for this UI change.

## 2026-09-30 — BeamNG export from a user's report

Report: "`terra-drive` doesn't exist" and `tools/export_beamng.py` "says the map ID/level ID
is invalid".

- `terra-drive` exists, but `setup.ps1`/`setup.sh`/`TerraDrive.cmd` install it into `.venv`,
  not onto `PATH`; README only showed the bare command. README (en/uk) now names
  `.venv\Scripts\terra-drive`, venv activation and `python -m akadem_maps`; setup prints the
  BeamNG export command with the venv path.
- `tools/export_beamng.py --map` takes an installed map ID; a world folder path
  (`out/generated/<id>`) failed with a bare `Invalid map id`. The tool now has `--world`, and a
  `--map` value that is a folder with `config.json` goes the same way; both call
  `adapters.beamng.export.export_world` (the CLI's path). Map/level ID errors now show the value
  and the `[a-z0-9_]` rule.
- Checks: tiny world built from `examples/tiny`; `tools/export_beamng.py --map <world>` ZIP
  SHA-256 equals `terra-drive export --target beamng` on the same world (d15c36ea…) and
  `terra-drive validate --target beamng` passes; `--level-id My-Level` gives the new message.
  `python -m unittest discover -s tests`: 321 passed, 1 skipped (2 new tests in
  `test_beamng_export`). Not checked in BeamNG.drive itself.

## 2026-09-29 — double-click Windows launcher

- `TerraDrive.cmd` at the root: first run calls `setup.ps1`, later runs `start.ps1`
  (both with `-ExecutionPolicy Bypass`, so a downloaded ZIP works). Missing Python 3.11+ →
  offers `winget install Python.Python.3.14 --scope user`, otherwise points to python.org.
  Arguments go to start.ps1; `-File` keeps `--`, so `TerraDrive.cmd --map tiny -- -- --seconds=5`.
- A real `.exe` in Git was not added: binaries are excluded by DECISIONS and `.gitignore`.
- Fixed `setup.ps1`: the committed file held a BEL byte instead of `\a` in
  `game\data\active_map`; Test-Path threw, so setup failed at its last step on every run.
- Checks: fresh clone in a temp folder, first `TerraDrive.cmd` run from zero 176 s
  (setup, Godot import, tiny map, game with bridge on port 8796, exit 0); second run 13 s
  without setup; setup rerun keeps the installed map; the old setup.ps1 exits 1 on the same
  clone. `start_rivne.ps1` was removed at the user's request (also from MANIFEST.in).

## 2026-09-29 — opaque vehicles (uncommitted)

Symptom: cars were partly see-through. Cause: the procedural kit (`game/visuals/vehicles.gd`)
built triangles with mixed winding, so Godot culled whole body sides, glass and hubs, and
`generate_normals` inverted their shading.

- Kenney Car Kit GLB (CC0, already pinned in `config/assets.json` and fetched by
  `tools/fetch_assets.py`) is now the primary model source, rescaled to `config/vehicles.json`
  sizes as before. The procedural kit remains the fallback when the pack is not fetched;
  `Vehicles.use_glb = false` forces it for comparisons.
- Procedural kit fixed as well: each primitive sets an interior reference point and every
  triangle is turned to face away from it (boxes, loft sections and caps, glass, wheels).
- Lamp boxes were placed on the nominal catalogue ends and floated in front of tapered
  Kenney bumpers. `lamp_spots` now rays along Z through the body triangles and moves
  inwards on a miss.
- Physics is unchanged: collision boxes and wheels still come from the catalogue sizes.
- New `game/scripts/validate_vehicle_looks.gd`: three close views of every catalogue model on
  a neutral stage (`--procedural` for the fallback). Sheets under `logs/qa-20260929/`
  (`vehicles-before`, `vehicles-kenney`, `vehicles-after`, `vehicles-procedural`) reviewed:
  before showed see-through sides; after both sources are solid and lamps sit on the body.
- `tests.test_vehicle_availability tests.test_asset_dependencies`: 13 passed.
  `AKADEM_MAP=tiny tools/check_drive.ps1`: all six scenarios passed.
- Not done: an in-game akadem screenshot with traffic. One attempt crashed while building
  the world (`world.gd:55` SurfaceTool out of memory; 16 GB RAM free, file not touched here)
  while a stray test game from port 8794 was still open; not yet repeated. Full suite and
  the FPS comparison are also still to run after this change.

## 2026-09-29 — simulator UI redesign

Separate commit on top of the PR integration. Physics, geometry and world formats unchanged;
`akadem_maps`/`akadem-maps`, map IDs, hotkeys, English/Українська and OSM attribution kept.

- Style: graphite surfaces, teal accent, amber warnings, 8 px rhythm, radius 8, no blur
  (`ui_theme.gd`). `ui_modal.gd`: input shield, Tab-contained focus, focus return; a
  `compact` variant fits its content (Pause). `hud.gd`: visible Maps/Pause/Camera/Spectator/
  Traffic/Help buttons, speed and gear at the bottom, minimap on the right.
- Map menu: search, empty state. Fixed: Godot's `"" in text` is false, so the empty query
  hid every installed map. Pause and structured help are separate modals; modals also
  block raw Input polling (player controller, spectator camera).
- Picker: scrollable side panel with a scrollbar gutter; empty search rows hidden; plain
  translated status per generator stage (raw `phase · stage` moved to Technical details);
  connection hint only for download failures, "move or enlarge the area" otherwise;
  Retry keeps the fields; per-run log path printed (the shared `logs/generate.log` was stale).
- Language switches from the Pause/Maps buttons now also refresh formatted texts
  (density label, speed-limit items) via NOTIFICATION_TRANSLATION_CHANGED.
- follow_focus scrolled the picker and traffic panel against an unsorted first-frame
  layout; both return to the top one frame after focusing.
- Generator fix (`tools/generate_map.py`): the build reuses
  `out/generated/.akadem-inputs/<id>.osm` by id, so after deleting a generated map a new
  map with the same name elsewhere silently got the old area's OSM. `free_id` now treats
  such an id as taken. Found by the real picker harness; unit test added.

Checks (Windows, RTX 2070 SUPER):
- `validate_ui.gd --ui-shots --offline` (tiny): passed at 1280x720, 1920x1080 and
  2560x1440 requested; the OS clamped the last window to 2560x1421. Screenshots of HUD,
  traffic, pause, help, maps, empty search, generator, progress and error in both languages
  under `logs/qa-20260929/ui/` (ignored) were reviewed; Ukrainian text fits everywhere.
- New `validate_generator.gd` (needs network, installs and activates a map): real picker
  runs. Error via unreachable proxy (25.5 s, connection hint, Retry, name kept, process
  exited), Cancel during an Overpass download (0.5 s, "Generation cancelled", Back
  restored), then a complete 0.6 km build of a new map ID (33 s). No python/curl/netconvert
  left afterwards. The QA map was deleted and `active_map` restored to `khreshatyk`.
  Earlier harness runs were invalid: cached inputs made the "error" run succeed, and an
  over-large jitter picked an area without roads (netconvert / "No suitable start road").
- Full `python -m unittest discover -s tests` outside the sandbox: 319 tests OK, 1 skip
  (325.0 s; the Windows-skipped DuckDB shebang fixture). `tools/check_publication.py`: ok.
- Not done: same-conditions FPS comparison. The first attempt passed `--` directly to
  `.\start.ps1` inside PowerShell, which consumes a bare `--`, so `--seconds=30`/`--no-vsync`
  reached Godot as engine options and the game never quit. That instance (port 8793) was
  left open for the user to close. From a PowerShell prompt three separators are needed
  (PowerShell, start.ps1, then Godot's user arguments): `.\start.ps1 --map akadem
  --density 100 -- -- --resolution 1920x1080 -- --seconds=30 --no-vsync`; compare with
  `logs/qa-20260929/baseline-akadem.json` (median 154.29 FPS); investigate a drop above 5%.
- Keyboard focus, Tab containment, Escape return and click actions are checked with
  synthetic Godot events only; Windows Computer Use was unavailable, so no native input.
## 2026-09-29 — PR integration and Windows generator ownership

User requested merging PR #1 then #2 without further tests and continuing to the UI redesign.
Both original commits and their handoff entries below are preserved. GitHub returned no
check runs on either original PR head; both had an approval. macOS results below belong
to the PR author, not this Windows session. Native Bash 3.2 was not available here.

- Removed `maps.mail.ru` from the default generator mirrors.
- Windows generators own a kill-on-close Job Object, including netconvert/duarouter
  descendants. A retained parent handle detects game exit; a per-run cancel file requests
  cleanup, with a five-second forced job termination fallback if Python is blocked.
- Picker cancellation waits for process exit; concurrent runs have distinct event/log files.
- Closed urllib HTTPError response streams before retry. PowerShell surface/drive wrappers
  prefer the console engine and explicitly wait for its exit.
- Already completed: 16 runtime/generator/lifecycle tests, two Windows HTTP/timeout tests,
  and a launcher test covering simulated Linux/macOS selection, paths containing spaces
  and no bridge arguments. These are not native macOS/Linux execution results.
- Initial full discovery: 315 tests, one skip, one failure and one error (408.429 s).
  The Godot asset subprocess timed out and the vehicle subprocess crashed in the sandbox.
  Repeating `tests.test_asset_dependencies tests.test_vehicle_availability -v` outside the
  sandbox passed all 13 tests. Full discovery was not repeated before merging, as requested.
- `pip check`, publication audit and elevated Godot `--headless --path game --import` passed.
  First import failed to create editor directories in the sandbox. First launcher fixture
  inherited AKADEM_MAP; fixed by isolating its environment. Sandbox Start-Process also failed
  with duplicate Path/PATH; surface/drive checks were restarted outside the sandbox.
- `start.ps1` on isolated port 8793: tiny (25 s, 1280x720), akadem (30 s, 1920x1080),
  both exit 0 with 100 cars. Baseline screenshots/metrics: `logs/qa-20260929/` (ignored).
  Median FPS: tiny 330, akadem 154.29; same-map comparison is still required after redesign.
- Traffic and priority validation ran; UI interaction, generation through the redesigned
  picker, full post-change suite and final runtime report remain for the next work unit.
- Windows Computer Use initialization failed on an unavailable dependency import root;
  no native UI input was sent during this integration work.

## 2026-09-29 — macOS: setup.sh downloads the macOS Godot build

Symptom: `./setup.sh` on macOS downloaded `Godot_v4.6-stable_linux.x86_64` and the import failed with "cannot execute binary file". Everything else in `setup.sh` already worked on macOS.

Fix:
- **`tools/godot.sh` (new):** sourced by `setup.sh`, `start.sh`, `tools/check_drive.sh` and `tools/check_surface.sh`; picks the binary and download URL by `uname -s`. Linux paths are unchanged. macOS uses `Godot_v4.6-stable_macos.universal.zip`, unpacked from `Godot.app` to `.tools/Godot_v4.6-stable_macos.app` (binary: `Contents/MacOS/Godot`).
- **`akadem_maps/runtime.py`:** `godot_names()` / `godot_url()` return the macOS bundle on `darwin`, so tests and CI find it.
- On macOS Godot ignores `XDG_*`; editor settings and `user://` go to `~/Library/Application Support/Godot`.

Checks (macOS 26, Apple Silicon):
- `./setup.sh`: exit 0; downloaded the universal build (arm64 + x86_64), Godot import created `game/.godot/global_script_class_cache.cfg`, and the `tiny` map was installed.
- `.venv/bin/python -m unittest discover -s tests`: 308 tests OK, 28 skipped (map data not generated); `test_vehicle_availability` ran against the macOS Godot.
- `AKADEM_MAP=tiny tools/check_drive.sh`: exit 0, all six drive scenarios `passed: true`.
- `./start.sh` then failed with `bridge_args[@]: unbound variable`: macOS `/bin/bash` is 3.2, which treats an empty array as unbound under `set -u`. `start.sh` now expands it as `${bridge_args[@]+"${bridge_args[@]}"}`; `"$@"` and the always non-empty `gen_args` are unaffected.
- `./start.sh --map tiny -- --seconds=25`: exit 0, Metal renderer on Apple M5, `WORLD_READY map=tiny`, bridge "ready" and "Client connected (map=tiny)", and no bridge process was left afterwards.
## 2026-09-29 — map picker: download feedback, and no orphaned curl after Ctrl+C

Symptoms (macOS, in-game "New map"): curl's progress and `HTTP 504` errors appeared in the terminal while the picker showed only "build · sources"; after Ctrl+C the game closed but curl kept running and writing to the terminal, and a second Ctrl+C did nothing.
- **504s:** Overpass was busy, and our query was the kind it turns away first (root cause under Fixes: the 1 GiB `maxsize`). No API key is involved. At 09:20 UTC even a one-node query to overpass-api.de returned 504 "The server is probably too busy"; kumi.systems returned 504 after 108 s and private.coffee timed out.
- **Orphan:** Godot's `OS.create_process` starts the generator with `setsid` (checked: child pgid = child pid, and grandchildren share it), so the terminal's SIGINT never reaches it. The orphaned curl had ppid 1 and no tty.
  - `OS.kill` in Cancel/`_exit_tree` SIGKILLed only Python.
  - On SIGINT Godot exits at once (status 130) without `_exit_tree`, so the generator and its curl were never stopped.

Fixes:
- **`prepare.download`:** curl runs with `-sS` and captured stderr; `curl_error()` turns failures into `HTTP 504` / `timed out after N s`.
- **`prepare.fetch`:** emits `download` (`url`, plus a browser-openable `query_url` = `?data=<query>`) per Overpass server and `warning` before each fallback. The final error lists each server with its reason. `BuildContext.notify` sends these events.
- **`location_picker.gd`:**
  - The status line shows the download and warnings.
  - The terminal gets the log path, stage changes, the URLs, warnings and errors.
  - Cancel/`_exit_tree` send SIGTERM to the generator's process group (`kill -TERM -<pid>`); Windows keeps `OS.kill`.
- **`generate_map.py`:**
  - SIGTERM → KeyboardInterrupt, so `subprocess.run` kills curl, the staging directory is cleaned and a `cancelled` error is written.
  - `--exit-with-parent` (passed by the game; POSIX only) cancels when `getppid()` changes, with a SIGKILL of the process group after 15 s as a fallback.
- README documents the `download` and `warning` events.
- **Root cause of the 504s: the query's `[maxsize:1073741824]`.** Overpass admits queries by the RAM they reserve.
  - Wrocław 1.5 km, same moment, both servers: 1 GiB → overpass-api.de 429 (partly from three parallel probes) and maps.mail.ru 504. The default (512 MiB) or 128 MiB → 200 and identical data (3.2 MB, 4495 ways).
  - A 5 km square of central Wrocław (the picker maximum) at 256 MiB → 200, 70 MB, 98k ways, no `remark`.
  - `prepare.fetch` now reads `overpass_maxsize`; the default is still 1 GiB, so existing configs are unchanged. `generate_map.py` sets 256 MiB.
- **Mirrors (`generate_map.OVERPASS`):**
  - Added VK Maps (`maps.mail.ru/osm/tools/overpass`), which is global and keyless per the OSM wiki.
  - kumi.systems is no longer listed on the wiki and timed out, so it moved to last.
  - Other listed instances need a key or payment, or cover one region only (CH, GB/IE, Virginia, Ethiopia).
  - overpass.openstreetmap.ru (connect timeout) and overpass.osm.jp (TLS error) did not work.
- Live check: `prepare.fetch` with the generator config for Wrocław 1.5 km → overpass-api.de answered in 1.6 s, 4495 ways.

Checks:
- Unit tests: 311 OK, 28 skipped. New: mirror failures and events, `curl_error`, `watch_parent`.
- Headless Godot driving the real picker (`scratchpad` harness, Wrocław 1.5 km):
  - Cancel during the download → "Cancelled; nothing was installed", with no curl or generator left.
  - SIGKILL of Godot → the watchdog cancelled within 3 s.
  - SIGINT with default disposition → Godot exited with 130 at once; the watchdog cancelled and nothing was left.
- Failed experiment: the first SIGINT test sent the signal to a background job of a non-interactive shell, where SIGINT is ignored, so Godot kept running until the harness timeout. It was repeated with SIGINT reset to default.
- Not checked: Windows (no curl there; the urllib path and `OS.kill` are unchanged).

## 2026-09-28 — traffic dropped mid-game: SUMO crash from road situations

Symptom: traffic worked, then the status turned to "NO TRAFFIC BRIDGE". Windows logged an APPCRASH of `python.exe` in `_libsumo.pyd` (0xc0000005) at 22:01:57; `bridge.log` had been overwritten by the next launch. Plain simulation (×16, 2 h simulated) and driving an ego car (8 min) did not crash.

A fuzz client sending every game message (incidents, lane closures, traffic lights, pause, spectator, density, reset) reproduced it in 42 s:
1. A stalled or accident car (`typeID='car'`, vClass passenger) on a lane that is or becomes closed by `setDisallowed(['passenger'])` → `FatalTraCIError: Invalid departlane definition` inside `simulationStep`. Minimal repro: the first stalled + lane_closed pair at the same point.
2. The handler died (1011). Any further step on that libsumo → `Windows fatal exception: access violation` in `simulationStep`, i.e. the observed crash.

Fixes:
- **Cause (`tools/situations.py`):** incident cars use vType `incident_car` with vClass `ignoring`, so lane permissions cannot reject them.
- **`tools/traffic.py`:**
  - A route cut by a closed lane (`TraCIException: no valid route`, found after the fix above) skips that trip instead of failing the tick.
  - Any exception in a tick rebuilds SUMO on the same map and keeps the client connected, with an error message to the game. Checked in-process: forced fatal → close → new Simulation → 3000 steps OK.
  - `faulthandler` is enabled, so a native crash leaves a Python stack in `bridge.err.log`.
- **`start.ps1`:**
  - Supervises the bridge while the game runs: up to 5 restarts, and the dead bridge's logs are kept as `logs/bridge.crash-<time>.*`.
  - `AKADEM_PORT` also moves the bridge and its logs (`bridge-<port>.*`), so a test session can run next to a live one.

Checks:
- Fuzz after the fixes: 480 s / 1227 actions on `khreshatyk` and 360 s / 996 actions on `akadem`; bridge alive, no SUMO errors.
- Supervisor: `start.ps1` on port 8790 with the bridge killed after the connection; it was restarted, the game reconnected, 100 cars at the end, crash logs kept.
- Unit tests for situations/traffic/scenario/generate_map/publication pass.
- Mistake during testing: a first supervisor attempt killed the user's own running bridge (port 8765). Test sessions now use `AKADEM_PORT`.


## 2026-09-28 — follow-up: bridge killed by start.ps1, frozen car, mouse look

After the entry below, the user ran `start.ps1`: still no traffic, and the car did not move (only the wheels steered).
- **Main cause, missed last time:** `start.ps1` ran the GUI build `Godot_v4.6-stable_win64.exe` with `&`. PowerShell does not wait for GUI-subsystem programs, so the script went straight to `finally` and ran `Stop-Process` on the bridge.
  - Evidence: `bridge.log` stopped at "ready", while Godot's log showed two maps loaded and no connection.
  - The earlier checks started the bridge and the console Godot directly, so they could not see this.
  - Fix: `Start-Process -NoNewWindow -PassThru` + `WaitForExit()` and the Godot exit code; `Find-Godot` prefers the console build.
- **Frozen car:** `player.enabled` required a traffic connection, and a disabled car has `body.freeze = true`. Driving no longer depends on the bridge. After 6 s without a socket, the status says "NO TRAFFIC BRIDGE · run start.ps1 · F5".
- **Mouse look (`player.gd`):** hold RMB to orbit the chase camera, or turn the head in the cockpit (±120°/±60°). The cursor is captured while dragging. The wheel sets the chase distance (4–25 m). The view eases back 1.5 s after release.

Checks (a game window was used, not only headless):
- `start.ps1 --map tiny '--' '--' '--seconds=25'`: "Client connected", 100 cars, exit 0, and the bridge stopped with the game.
- Same on `khreshatyk`: 100 cars, median 118 FPS.
- Without a bridge: throttle for 6 s reached 62 km/h and ~60 m.
- A synthetic RMB drag turned the orbit 90° (screenshot checked) and captured the cursor; it returned to 0° after release.
- `--` must be quoted when passing Godot user args through PowerShell (`'--'`); an unquoted one is eaten by PowerShell.


## 2026-09-28 — traffic connection, maps anywhere, English UI

Traffic never appeared after `start.ps1` ("connecting to traffic" banner). There were two causes, both reproduced; a third, the main one, is in the follow-up above:
- **Missing Godot class cache.** `game/.godot` is ignored, and no script created it. As a result, `class_name Vehicle/Wheel` (gevp) did not resolve, `main.gd`/`player.gd` failed to compile, and the player car never spawned.
  - Fix: `setup.ps1`/`setup.sh` run `godot --headless --path game --import`, and `start.ps1`/`start.sh` run it when `game/.godot/global_script_class_cache.cfg` is missing.
- **Silent handshake timeout.** `main.gd` opened the socket in `_ready`, but Godot sends the handshake only in `poll()`, after the world is built. websockets 15 drops a handshake that has not finished within 10 s, and logs nothing (`open_timeout`).
  - Reproduced: a raw client that waits 12 s is aborted by the old bridge (WinError 10053) and gets `101 Switching Protocols` from the new one.
  - Fix: `serve(open_timeout=None, ping_interval=None)`; client connect/switch/disconnect lines in `bridge.log`. The game connects from `_process` and reconnects on its own every 2 s; F5 still forces it.
  - The status shows "LOADING TRAFFIC FOR THIS MAP…" while the bridge rebuilds SUMO.

New features:
- **Maps anywhere.** `tools/generate_map.py` wraps build `--bbox` → export → install `--activate`, and writes JSONL progress. `game/scripts/location_picker.gd` opens from the map menu (M → "New map…").
  - Picker: OSM tile map, Nominatim search, and lat/lon paste. It runs the generator as a process and loads the map when it finishes.
  - CLI: `start.ps1 --generate LAT LON [--size KM] [--name NAME]`.
  - Downloads now send a User-Agent: overpass-api.de answered HTTP 406 without one. `overpass_mirrors` in a config is tried in order after `overpass`, since the main server returned 504.
- **English by default.** UI strings are English `tr()` keys; Ukrainian lives in `game/scripts/i18n.gd`, a runtime `Translation`, because the project runs without import. L or the menu button toggles it, saved in `user://settings.cfg`. Bridge errors and incident labels are English.
  - Map names are data and stay as built. The menu now finds `name` in sorted-key exports (it used to show the id).

Checks:
- `unittest discover`: 308 run, OK (1 Unix-only skip), including 6 new `tests/test_generate_map.py` tests.
- Headless game with the bridge on `tiny`: 100 cars received (70 far / 30 near).
- Bridge map switch `tiny → akadem` in 3.6 s with a client that stalled for 25 s; reconnect was immediate.
- `generate_map.py` at 49.8419, 24.0316, 0.6 km: built, exported and installed `lviv_rynok` in 36 s. The game on `lviv_rynok` with the bridge started on `akadem`: switched, 91 cars.
- Rendered the map menu, picker (live and cached tiles) and Ukrainian menu at 1920×1080 and checked them by eye. HUD screenshot is in English.
- Not run: interactive play through `start.ps1` (needs a person at the window), picker search/Generate clicks, and cancelling a generation.
- `check_publication.py` flagged the absolute checkout path in the entry below; it was replaced with a neutral description.

## 2026-09-28 — relocated to the standalone checkout

- The install script copied and hash-verified 254 source files, then failed on `dist/`: the staging wheel/sdist were ACL-locked to the Codex sandbox user. Wheel and sdist were rebuilt here from the same sources (setuptools, `--no-isolation`); the remaining steps then completed unchanged.
- The initial `git diff --cached --check` failed. Fixed an extra blank line at EOF in `akadem_maps/adapters/godot/demand.py`. Vendored `game/addons/gevp` keeps its upstream trailing whitespace (marked `-whitespace` in `.gitattributes`). The working copy of `setup.sh` was normalized to LF.
- Passed: pip check, `terra-drive doctor`, `akadem-maps --version`, `tools/check_publication.py`, `git diff --cached --check`, `tests.test_publication` + `tests.test_demand`. `.sh` files have mode 100755. No remote, no commit. The full suite was not rerun because the changes were whitespace-only.

## 2026-09-28 — standalone extraction

- Extracted the generator, Godot game, SUMO bridge, BeamNG adapter, configuration and tests.
- Preserved `akadem_maps` imports, `akadem-maps` alias, map IDs and original copyright notices.
- Added standalone branding, complete runtime pins, clean-checkout instructions and full CI.
- Excluded downloaded assets/maps, personal notes, historical QA logs and local tools from Git.
- Completed validation: 301 passed, one Unix-only skip; package/export/runtime/security results are in VALIDATION.md and VALIDATION.json.
- Initial discovery was interrupted by the agent server restart after the reproducibility test;
  it has no completed result and must not be reported as passing.

- Completed initial wheel/sdist build and installed-wheel offline build/validation, both exporters and explicit Godot installation.
- Dependency audit identified Pillow 12.1.1 advisories (35 database entries, including duplicate advisory IDs). Pin changed to Pillow 12.3.0; official release notes: https://pillow.readthedocs.io/en/stable/releasenotes/12.3.0.html. Revalidation pending.
- Initial audit/build harness accidentally resolved a relative executable against the parent process directory on Windows. Corrected it to an absolute executable under this checkout and reran; those failed attempts are not product defects.
- pip-audit required access to its AppData cache outside the sandbox. Godot headless import completed without script errors, with a sandbox certificate-store warning.
- Copied existing installed maps, SUMO inputs and licensed assets locally into ignored folders for runtime checks; no map was regenerated.

- Final tests use Pillow 12.3.0 and include local Akademmistechko data, downloaded assets and optional building-cache fixtures. All 302 tests were discovered (301 pass, one Unix-only skip).
- Godot main/import, surface (2,690 probes), six drive scenarios and Rivne three-route driving passed. SUMO 30 simulated minutes/100 cars: zero collisions/teleports; all incidents and priority passed.
- Installed-wheel build, both adapters, validation and Godot installation passed from outside the checkout. pip check and advisory audit (16 runtime packages, zero findings) passed.
- BeamNG 0.39.4.0 synthetic ZIP smoke completed, exit 0: 53 exact surface samples, 11 nav nodes/14 links, vehicle and traffic creation. Screenshot visually inspected. No signals exist in this fixture.
- Reproduction and known non-fatal Godot shutdown/certificate warnings are documented in VALIDATION.md. Large historical maps are preserved local runtime data, not new certified releases.
- Final destination is a fresh standalone directory with its own Git main branch, staged reviewed source, no remote and no initial commit. The environment is recreated there and all copied source hashes are checked.
