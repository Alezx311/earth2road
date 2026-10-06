# Earth2Road handoff

## 2026-10-07 — road builder switch, time estimates, BeamNG mods folder in the map menu (Claude)

- Owner: 4×4 km with export takes about an hour; wants a switch with options and expected
  time at generation and export, and the BeamNG mods folder in the game's map manager.
  Owner chose: picker offers only Fast (legacy) and Roadgen v2 (Local Visual DNA stays in
  config); "Remove from BeamNG" separate from "Delete map"; deletion is permanent.
- Measured (existing logs): Bilychi 4×4 km legacy 14.6 min vs v2 68 min (network 24 min,
  roads 25 min, roadgen alone 15.5 min); Khreshchatyk 2 km legacy 5.6 min vs v2 44 min;
  BeamNG compact export 64 tiles 2.6 min, 111 tiles 7 min, 112 tiles with DNA 18 min.
- `tools/generate_map.py --road-geometry legacy|v2` (default legacy) → `cfg.road_geometry`.
  Picker: "Road builder" menu with note, remembered in `settings.cfg [generator]`; build
  time estimate replaces the old fixed "10–30 minutes" text; elapsed/expected while running.
- `akadem_maps/estimates.py`: minutes = overhead + rate × (km² | tiles) as a range; base
  rates from the runs above; after ≥2 runs of a mode, `logs/timings.jsonl` (written by
  generate_map and export_beamng_gui) replaces them. `tools/estimate.py` prints the table
  for Godot (`game/scripts/estimates.gd`, with the same fallback constants).
- Export dialog: export time per optimization mode, "Install into the BeamNG mods folder"
  (copies `earth2road_<id>.zip` flat into mods via `.part` + rename; a ZIP locked by a
  running BeamNG reports "Close BeamNG and retry" and offers Retry install).
- Map menu: mods folder line (auto: `%LOCALAPPDATA%/BeamNG/BeamNG.drive/current/mods`, or
  `userFolder` from BeamNG.drive.ini; Change…/Open folder), "· in BeamNG" mark, Add to
  BeamNG (newest validated export, else export dialog preset to install), Remove from
  BeamNG, Delete… (confirmation; disabled for the loaded map) → `tools/maps.py delete`:
  game/data, data/build, out/generated/<id>[-stamp][_godot][.logs], legacy `<id>.osm`,
  exports whose artifact.json names the id, both ZIP names in mods; junctions unlinked,
  OSM snapshots kept. Continues past locked files and lists them.
- Checks: full suite 467 OK, 1 skipped (`logs/modes-ui/unittest-01.log`);
  `validate_ui.gd --offline` (tiny) passed with new checks (`validate_ui-07`);
  `validate_beamng_export.gd --runtime` PASS (`validate_export-01`), install box forced
  off so the real mods folder was not touched (verified: no tiny ZIP there). The QA tiny
  timing line was removed from `logs/timings.jsonl`.
- Failed experiments: Godot launched from Git Bash segfaults before any output (also on
  `--quit`); from PowerShell it works. Relative `--log-file` crashed too (use absolute).
  `Estimates.reload()` collided with the built-in `GDScript.reload`; renamed `load_table`.
- Not verified: Add/Remove/Delete clicked by hand; estimate accuracy for v2 outside Kyiv.

## 2026-10-07 — local Reddit devlog and BeamNG assembly captures (Codex)

- Added ignored `/posts/` for drafts, style notes, archived copies and media. The
  Ukrainian devlog covers the agreed 2026-09-27–10-06 interval (first recorded work
  is 09-28). Existing drafts remain in place; copies and source provenance are local.
- Added `tools/beamng_assembly.py` / `.lua` and `docs/BEAMNG_ASSEMBLY.md`: fresh
  isolated BeamNG profiles, COLLADA partition without changing source exports,
  staged placement of road pieces, camera capture and captioned silent MP4 encoding.
  Generated surface corners retain their original position/normal/UV/material;
  presentation chunks have no collision and are not playable release artifacts.
  Normal exporter and existing uncommitted generator/game work were preserved.
- Source: `out/road-fairing/after-04` + its compact BeamNG export, ZIP SHA-256
  `31b6a7558c1c697ea949b613d8888b467a6a95a71b852749effcd5dc18b4e3c8`.
  Junction `cluster_3229797051_436619362` (v2 X, Efremova/Osinnia).
  Two full BeamNG 0.39.4 captures completed, exit 0: junction 624 animated objects,
  street 1,565; each 750 frames, 25 s, 1920×1080/30 fps. Ukrainian captions explicitly
  identify assembly visualization, not generation time. Files under
  `posts/2026-10-06-devlog/video/`; raw evidence under `captures/`.
- Geometry verification: all 58,187 triangles in the 14 partitioned junction
  objects compared as expanded multisets: exact position/normal/UV/material and
  multiplicity, recorded in `captures/junction-01/geometry-verification.json`.
  New tests also verify compact/balanced files and rejection of incompatible indices.
- Tests: full discovery 456 run, 2 failures, 1 skip, 427.846 s
  (`captures/unittest.log`). Both failures were Godot subprocess 0xC0000005 under
  the sandbox (asset props and vehicle availability); isolated unrestricted rerun
  passed both, 0.932 s (`captures/godot-retest.log`). Effective result: 455 passed,
  1 skipped. New partition tests: 2 passed again after final Python edits.
- First probe completed six shots but rising from below terrain hid the motion;
  final takes descend visibly from above. Probe retained as `captures/probe-01`.
  An initial ad-hoc mesh comparison script failed on a blank JSONL line; corrected
  and rerun successfully. No source geometry changed in either experiment.
- No Reddit publication, Git commit, map installation or release acceptance implied.
  Static control capture completed (2 frames, exit 0); restored scene visually
  matches the original export at the same camera pose. Street mesh verification:
  87,679 triangles in 19 source objects match exactly. Both MP4 files fully decode
  to 750 frames with no black intervals; inspected one frame per second and full-size titles.
- Optional Khreshchatyk capture stalled after texture import. Owner explicitly
  stopped further capture/debug work to prioritize writing; owned PID 25784 was
  terminated. No new Kyiv shots are claimed or linked. Final bundle has four
  verified images, two videos, polished Ukrainian text, source evidence and local
  `REVIEW.html`. The original draft is retained in `drafts/01-initial.uk.md`.
- Empty manual-group JSONL initially acquired a newline and logged an empty-document
  error; preparation now preserves empty files. Existing completed media is unaffected.
  Other concurrent UI/estimate work appeared during this task and was untouched;
  the full-suite result above applies to the 456 tests discovered at its start.

## 2026-10-06 — playtest fixes (10 notes) + Khreshchatyk DNA test map (Claude)

- New F9 defect marker in Godot (`game/scripts/defect_marker.gd`): frame, camera, car and the
  point under the screen centre → ignored `logs/defects/<map>/`; `tools/defects.py` resolves
  lon/lat, nearest SUMO edge/junction. Owner marked 10 notes on `bilychy_roadgen_v2`; summary,
  findings and generator changes per note: [PLAYTEST_2026-10-06.md](PLAYTEST_2026-10-06.md).
- Generator: `core/osm_buildings.py` (building multipolygons → hole-free pieces; S3DB outlines
  hidden when parts cover ≥50 %, parts share style key/colours; OSM `building:colour`/`roof:colour`
  in every mode; pyramidal/hipped/dome/onion roof solids, `roof:height`, `min_height`; one-storey
  kiosks; footprints over the at-grade carriageway clipped, or dropped when >60 % (small <60 m²: >30 %) on it, → `audit.json`
  `buildings_on_carriageway`). `core/landcover.py` (relation lakes/forests in every mode, `pitch`,
  `track`, priority overlap resolution). `core/roundabouts.py` (one lane count per ring before
  netconvert → `roundabout_lanes`). `road_profiles.lane_suspects` (report only →
  `lane_count_suspects`). `road_elevation`: carriageway pairing by name/ref/main class, median
  polylines for motorway/trunk pairs (derived barrier fences, open where carriageway reaches the
  line), junction-mouth plateau for minor roads (half major width + 4 m, ≤4 % added grade).
  `roadgen.clear_sidewalks`: sidewalks never over same-level carriageway, runs <4 m and walking
  slivers dropped. `rural.dress` also runs for the urban private sector (no roof changes) and
  reads jersey barriers/guard rails.
- Godot: roof colour materials, raised parts closed underneath, water/pitch/track materials with
  collision (water had none: the car fell through lakes), `--shots-file=` QA poses
  (`tools/shots_file.py`). BeamNG: water/pitch/track surfaces (water was grass with trees on it),
  no vegetation on non-green covers, fences exported, shared roof-colour materials, raised parts
  closed underneath.
- Corrections: first roundabout reading ("netconvert adds a lane") was wrong — the extra lane was
  the guessed sidewalk. First full Khreshchatyk build (`world-01`) failed after 40 min with
  `KeyError: '_tags'` (a visible outline lost its markers before its parts read them); fixed and
  checked first on a 0.8×0.7 km cut (`smoke-02`, 1.5 min, both exports OK, Godot shots).
- Not done: typical models for churches/fuel stations/shops; lane counts are not raised from
  suspicion; BeamNG water is a surface, not a water volume.
- Tests: new `test_osm_buildings`, `test_landcover`, `test_roundabouts`, `test_playtest_roads`.
  Full suite before the Khreshchatyk build: 453 OK, 1 skipped (`logs/khreshchatyk-dna/unittest-01.log`);
  final code: 454 OK, 1 skipped (`logs/khreshchatyk-dna/unittest-02.log`).
- Khreshchatyk: `config/khreshchatyk_dna.json` (bbox of the old `khreshatyk` map, v2, DNA,
  10 quick-travel anchors), profile `config/visuals/khreshchatyk_dna.json` (5 manual profiles,
  42 anchors by a fixed rule, `logs/khreshchatyk-dna/make_profile.py`). Sources prepared offline
  from the registered Ukraine PBF into `out/khreshchatyk-dna/inputs`.
- Khreshchatyk builds: `world-01` failed (`KeyError: '_tags'`, above); `world-02` failed after
  40 min with a GEOS `TopologyException` (no traceback captured; not reproduced on two cuts).
  New geometry operations now retry on repaired, 1 mm-snapped geometry
  (`osm_buildings.robust`); builds run with `AKADEM_MAPS_TRACEBACK=1`. `world-03` completed
  (~45 min); review showed whole 5-storey buildings dropped next to over-wide yard roads and the
  Dnipro draped up the slope → drop only when >60 % on the carriageway (small <60 m²: >30 %), and
  flat water at the 10th DEM percentile inside each water polygon with the shore anchoring the
  ground (`landcover.water_level/shore`). Trial BeamNG export of `world-03` was copied to the
  normal BeamNG mods folder on owner request.
- Final `out/khreshchatyk-dna/world-04` (34 tiles, 7,809 lanes): 2,351 buildings, 38 building
  relations, 33 S3DB outlines hidden / 659 parts, shaped roofs 25 dome, 11 onion, 55 pyramidal,
  72 hipped, 89 fallbacks; 670 footprints clipped and 92 dropped (all <60 m²) at the
  carriageway; 23 landcover relations, 20 flat water levels (Dnipro 22.5 ha one level; shore
  ground within 0.25 m of water level); 149 sidewalk runs cut, 227 walking slivers dropped;
  470 urban fences; 69 paired carriageway ways, 0 medians (no motorway/trunk); lane suspects:
  Bohdana Khmelnytskoho (trolleybus, lanes=2). DNA: 2,690 styled, 10 landmarks, 14 spawns.
  Godot export installed as new map `khreshchatyk_dna` (not activated; replaced only the
  `world-03` install of the same new ID, backup in `.cache/replaced/`). Shots with
  `--shots-file` (`logs/khreshchatyk-dna/shots-04/`): St Michael's, St Sophia (white walls,
  green roofs, gold domes), Maidan column and fountains, Dynamo track and pitches recognisable.
  `tools/shots_file.py` takes the camera height from the nearest lane: two river poses ended
  inside the hill (camera below terrain); not fixed.
- Final BeamNG compact export `out/khreshchatyk-dna/beamng-02`: level `kyiv_khreshchatyk_dna`,
  ZIP 30.4 MB, SHA-256 51692375…, 3,679 objects, 342 signals, 19,961 forest instances; height
  audit nodes over 2 m: 19, max 7.33 m (not investigated). Copied over the trial ZIP in the
  BeamNG mods folder (`earth2road_khreshchatyk_dna.zip`; no other mod touched). Runtime not verified.
- Seen, not fixed: neighbouring footprints with different styles overlap on a facade
  (Bessarabka block); surface audit acceptance remains `pending`; not driven yet.

## 2026-10-06 — Local Visual DNA for Bilychi, 21 quick-travel points (Claude)

- Owner drove Podil DNA: "much better", quick-travel by points is convenient; some places
  have no textures (location not given). Static check of the Podil ZIP: all 227 materials
  defined, every level texture present, 157 DNA facade PNGs decode (RGB 256²). Cause not found.
- `config/bilychy_dna.json`: same 4 km square as `bilychy_roadgen_v2`, new level
  `kyiv_bilychy_dna`. Source re-extracted (selection v3) from the full Ukraine PBF (396 s,
  11,351 ways); terrain copied from Bilychi-11 inputs. Cache `out/bilychy-dna/inputs`.
- Profile `config/visuals/bilychy_dna.json`: 5 manual profiles (private, khrushchovka,
  panel_high, industrial, forest_edge); 96 anchors on a 400 m grid (650 m radius), profile
  per anchor by a fixed rule from OSM building type/levels and landuse within 300 m
  (`logs/bilychy-dna/make_profile.py`, grid stats `grid.json`; ignored).
- Points: `local_visual_dna.landmark_limit` (default 5, validated 0..50) set to 10;
  `pois` enabled (limit 6) with 16 manual anchors from OSM names (metro stations, malls,
  NAS institutes, parks, interchanges). `landmarks.merge_spawns` drops a landmark spawn
  within 150 m of an existing point. Result: 21 spawns (15 anchors, 4 landmarks, 5 fuel
  minus overlaps); unsnapped >150 m from a usable lane: Proliskok camp, Dacha Diakova,
  St Nicholas church, Agromat, 2 landmark nodes. 4 landmark spawns skipped as duplicates.
- World `out/bilychy-dna/world-01` (17,082 lanes, 112 tiles; build ~70 min): 4,414 styled
  buildings, 1,765 gabled, 172 roof fallbacks, 4,023 synthetic trees, 0 OSM trees.
  Export compact `out/bilychy-dna/beamng-01`: ZIP 65.8 MB, SHA-256 b902493a…, 9,748
  objects, 65,984 forest instances; height audit over 2 m: 20, max 6.51 m.
  Installed as `mods/earth2road_bilychy_dna.zip` (BeamNG was running; needs restart).
  `kyiv_bilychy_roadgen_v2.zip` untouched. Full suite 435 OK, 1 skipped
  (`logs/bilychy-dna/unittest-01.log`). Not driven yet.

## 2026-10-06 — Local Visual DNA, Podil pilot (Codex)

- User selected a 2×2 km Podil pilot, manually authored profiles, buildings + greenery,
  and OSM landmark spawns. Opt-in world v2 extension, shared by BeamNG and Godot;
  detailed configuration and reproduction: [LOCAL_VISUAL_DNA.md](LOCAL_VISUAL_DNA.md).
  Existing uncommitted road-generator work was preserved.
- Added 25 visual anchors / 4 profile distributions; deterministic per-property
  selection, coverage-edge fade, observed OSM priority, original procedural facade
  textures, exact-footprint gables with total height preserved and explicit fallbacks.
  Tree provenance separates OSM nodes from generated fill. Landmark ranking is a
  heuristic; profiles are manual hypotheses, not photo analysis.
- PBF/Overpass landmark selection v3 includes standalone landmarks and landmark
  relations. Pilot re-extracted from the original full dated Ukraine PBF (877,501,127
  bytes), not the older Kyiv cut. New snapshot: 5,357 ways, 106 relations, 35,668 nodes;
  extraction 404 s. Both A/B worlds use this one snapshot and cached z12 DEM.
- Completed unit/integration checks so far: `logs/local-dna/targeted-01.log` 37 OK;
  `integration-02.log` 16 OK, including a synthetic building through world + both
  exporters and a named landmark spawn. Empty tiny smoke alone had zero buildings;
  it was insufficient, so a building-bearing fixture was added.
- Failed experiments: first pilot config used the wrong config-root-relative path
  (fixed before extraction); first density test assumed no edge fade (fixture corrected
  to full overlapping coverage); first building export failed namespace validation
  (`dna_fac_*` renamed through the existing `kyiv_*` resource namespace contract).
  Sandboxed Godot editor settings failed and the headless rendering smoke crashed;
  unrestricted editor import and smoke reruns completed with exit 0.
- A/B worlds built: `out/local-dna/baseline-01`, `styled-01` (same spawn, 5,739 lanes;
  styled: 1,784 styled buildings, 788 gabled, 266 roof fallbacks, 1 OSM + 863 synthetic
  trees, 5 landmarks selected, 3 snapped spawns, 2 unsnapped). Codex's export script
  (`logs/local-dna/export_pilot.py`) and its full-suite run were killed with the session
  at 17:31 before finishing (no ZIP, no test summary).
- Finished by Claude: styled BeamNG compact export `out/local-dna/styled-beamng-02`
  (`logs/local-dna/export-styled-02.log`): level `kyiv_podil_dna`, ZIP 23.2 MB, SHA-256
  0f8c5fdd…, 4,421 objects, 152 signals, 5,515 forest instances; height audit nodes
  over 2 m: 33, max 11.28 m (not investigated). Full suite 433 OK, 1 skipped
  (`logs/local-dna/unittest-claude-01.log`). Installed on owner request as
  `mods/earth2road_podil_dna.zip` (new level; `earth2road_kyiv_podilskyi.zip` untouched).
  Baseline BeamNG export, `tools/local_dna_compare.py` A/B capture and Godot exports
  not run. Not driven yet; acceptance remains `pending`.

## 2026-10-06 — road profile fairing on the 1 km Bilychi cut (Codex)

- Owner feedback: junction appearance accepted, but longitudinal roads still wavy.
  Scope is the general generator, not map-specific edits. Existing uncommitted work
  was preserved; baseline copies of the two inspected modules are in ignored
  `logs/road-fairing/`. No source OSM, configuration, template-family algorithm or
  normal installed map was changed by this work.
- Reproduction: fresh offline `out/road-fairing/before`, using
  `config/bilychy_1km_v2.json` and `out/roadgen-v2/1km/elev-17/inputs`. Same network
  and inputs throughout the experiment. `tools/elevation_bench.py` replays elevation
  without a full world build, clips source profiles to the bbox and measures at 2 m
  spacing. Source way lengths are not lane-km; mesh audit is reported separately.
- Causes: the robust filter removed spikes but kept longer DEM undulations; an OSM
  way can change independently filtered strokes at an internal node, producing a
  jump within one sample interval; averaging a short driveway into a through road
  repeatedly perturbed it; restoring old node anchors undid reconciled profiles.
- Fix: a linear-time pentadiagonal curvature-penalty solve after robust filtering,
  using a 30 m characteristic length or 0.8 times the class radius, whichever is
  greater. Preserve linear grades, fair broad terrain, wrap closed strokes. Shared
  heights prefer higher class/longer strokes; reconcile whole strokes before way
  assembly, include source knots, and synchronize all resulting node heights.
  No new dependency; v2 only, legacy heights remain unchanged.
- Additional integration defect exposed by smoothing: when a neighbouring template
  absorbed a short approach, a fallback junction lost its source-way identity and
  failed to recognize overlapping pieces of the same street. Topology now comes
  from network approaches, independent of surviving meshes. Such same-level road
  overlaps are subtracted from fallback pavement, with their boundary heights used;
  pinning only vertices had left triangles spanning different-height surfaces.
- Profile comparison (`logs/road-fairing/comparison.json`, same 22,654 m sampled
  ground ways): total grade variation/km 1.0959 -> 0.5327 (-51.4%), ascent+descent
  635.36 -> 520.37 m (-18.1%), grade changes >2 percentage points 70 -> 56.
  Ways >200 m: variation/km 1.0763 -> 0.5749 (-46.6%), ascent+descent
  184.31 -> 154.25 m (-16.3%). Major roads: variation/km 0.7916 -> 0.5369.
  Broad elevation trends intentionally remain. Plot: `logs/road-fairing/profiles-before-after.png`.
- Failed/intermediate experiments retained locally: `fair-01` added fairing without
  stroke reconciliation and increased final grade variation (1.15 -> 1.78/km);
  `fair-02` reconciled strokes but old node anchors undid it (1.53/km);
  `fair-03` synchronized anchors; `fair-04` added through-road priority. These early
  metrics used original station spacing, so use `before-final`/`after-final` and
  `comparison.json` for the final uniform-spacing comparison. World `after-02`
  exposed a 1.439 m ambiguous fallback overlap at `254389925`; `after-03` restored
  identity but vertex pinning still left 0.580 m. Neither is the final candidate.
- Tests added: independent dense solve comparison, repeated waves, constant steep
  grades, broad hills, sampling-density invariance, invalid samples, small closed
  rings, stroke switching beside a 5 m source interval, driveway/through-road
  hierarchy, and absorbed-approach overlap without a duplicate pavement layer.
  Latest targeted run: 58 tests passed (`logs/road-fairing/targeted-04.log`). Earlier
  full-suite attempts hit two Godot sandbox crashes/timeouts; isolated unrestricted
  rerun passed both (`godot-retest.log`). Final full-suite and map checks below.
- Final world `out/road-fairing/after-04`: same network SHA-256 as `before`, same
  211 v2 / 86 fallback junctions and 1,949 lanes. Actual surface grade changes >5 pp
  105 -> 74; >2 pp 996 -> 739; absolute-grade warning samples 1,508 -> 883;
  crossfall >6% 198 -> 127. Connected steps >10 cm 1 -> 0, max 0.1651 -> 0.0895 m.
  Ambiguous overlap max 0.5523 -> 0.3367 m, >30 cm contacts 12 -> 2 (none >60 cm).
  Existing cross-section misses stay 263/29,930 and lane-centre errors stay 3;
  two remaining >30 cm ambiguous contacts need separate topology investigation.
  These are structural results, not an assertion that every road worldwide is fixed.
  Full evidence: `logs/road-fairing/world-comparison.json`.

## 2026-10-05 — roadgen-v2: smoother main roads, paired carriageways, bridge clearance (Claude)

- Owner's drive of Bilychi-10: Zhytomyr highway / Beresteiskyi avenue wavy, the two directions
  at different heights, the Beresteiskyi overpass over Kiltseva too low for a car. Measured:
  clearance 2.1 m (legacy 3.3 m: decks only satisfied clearance at OSM nodes, straight between
  nodes 150 m apart; the road beneath also humped up from DEM samples of the embankment).
- Test map `config/bilychy_beresteiskyi_v2.json` (1.5×1 km along Beresteiskyi with both
  overpasses, same offline inputs); builds `out/roadgen-v2/ber/` (`base` = start of this work).
- `road_elevation`: filter radius by road class (`CLASS_RADIUS`: trunk 90 m … others 24);
  samples within 14 m of a bridge deck untrusted for roads beneath (`smooth(trusted=)`);
  `pair_carriageways` averages the dense profiles of antiparallel one-way ways of one name within
  45 m (dominant partner per way, so a same-named slip road can't take over; Gaussian-spread
  difference); `deck_clearance` lifts decks densely as a 60 m crest curve at 6 % to
  BRIDGE_CLEARANCE above the final beneath profile. `prepare.road_node_heights(crest=True,
  dense_pairs=True)` in v2: node decks use the same crest, the node-level pair closing (partner
  read as a chord between sparse nodes, pushed junction nodes 1.3 m off) is skipped. Legacy unchanged.
- Beresteiskyi map (base → e05): carriageway gap median 0.36 → 0.02 m, p90 1.15 → 0.38, max
  4.75 → 1.44; overpass clearance 2.1 → 6.3–6.6 m (deck surface above road surface); major-road
  grade breaks >2 pts 108 → 89. 1 km (elev-16 → 17): major breaks >2 pts 17 → 0, gap p90
  1.53 → 0.21 m, crossfall >6 % 263 → 198, grade changes >5 pts 110 → 105.
- Bilychi-11 (10 → 11): gap median 0.26 → 0.01 m, p90 0.92 → 0.28, max 4.82 → 1.83; all four
  overpasses 6.3–6.6 m; connected steps >30 cm 8 → 2, >10 cm 11 → 10; crossfall >6 % 1100 →
  1040; absolute grade over limit 10630 → 9589; major breaks >2 pts 277 → 255 but >5 pts 45 → 63
  (new sites: west end of bridge `500943216` where node heights leave a 0.25 m deck shortfall that
  is faded over the last 10 m; v2 split `26131518`). ZIP 65.8 MB, build 66 min.
- Failed/changed during the work: a tent-shaped deck lift (sharp crest, 34 breaks on bridge
  lanes) → crest curve; crest curve without matching node decks left 1.9 m end shortfalls →
  shared `crest_drop`; per-station nearest partner jumped to a same-named slip road (0.3 m step).
- Installed (owner request): `mods/kyiv_bilychy_roadgen_v2.zip` = Bilychi-11, `mods/kyiv_bilychy_1km_v2.zip`
  = 1 km elev-17 (previous ZIPs remain in `out/`). Full suite 409 OK, 1 skipped
  (`logs/ber/unittest-full.log`); new tests: untrusted samples, class radius, carriageway pairing,
  deck clearance. Not driven yet.

## 2026-10-05 — project knowledge reconciliation

- Reconciled the repository documentation, current working-tree implementation/configs,
  existing JSON reports and historical notes into an external linked knowledge base:
  16 Markdown files (11 new, 5 updated). Personal notes and backups remain outside Git.
- Distinguished implementation, completed builds, structural audits, installed versions
  and runtime evidence. Preserved historical observations and explicitly marked stale
  plan items, mixed map versions and results that lack a corresponding primary report.
- Checks: pre-write hashes and regular-file/link checks; post-write content verification
  for all 16 files; 79 new wiki links and 75 local source links resolved successfully.
  Existing notes were backed up before replacement. No generator tests, map builds,
  exports or engine checks were started for this documentation-only work unit.

## 2026-10-05 — roadgen-v2: endcap/cluster templates, profiled cores, 1 km test map (Claude)

- Fast iteration map: `config/bilychy_1km_v2.json`, a 1×1 km cut of Bilychi (world x −750…250,
  z −500…500 of Bilychi-08) from the same verified OSM snapshot and z12 DEM; build offline with
  `--cache out/elevation-v2/bilychy-08/inputs/raw` (~4.5 min, replay `tools/roadgen_lab.py
  --prepared` ~1.5 min). Builds: `out/roadgen-v2/1km/` (`base` = code at session start).
- Owner decision (DECISIONS): keep longitudinal DEM grades, smooth crossfall and local humps.
- Templates (`roadgen`): **endcap** (dead end: last section + half circle, profile levels out
  over the cap radius so turnarounds don't flip grade), **cluster** (junctions joined by lanes
  < 9 m become one template: absorbed lanes and SUMO junction areas are core; up to 4 members,
  6 arms, `complex` shapes allowed), **shared lanes** (two templates overlapping on one lane are
  rebuilt to their half of it; shorter sockets: margin ≥1.5 m, transition ≥4 m), slit closing
  between opposite lanes (≤30 cm), sections/stubs keep only the piece at the socket when a road
  curves back. Families now 8 (T, X, Y, merge, split, transition, endcap, cluster) — still
  parametric, not a prefab library.
- Core heights: was one lstsq plane through all sockets (one road's grade = the other's
  crossfall). Now the flattest pair of opposite arms (≤45°) keeps its profile across the core
  (mean across lanes, cubic across the junction), other arms ramp to their own profile; the
  transition then blends only the residual. Clusters/pairless cores: harmonic surface through
  the outer sockets. Overlapping lanes at different heights: the band takes the lane whose
  centreline is nearest. Fallback junctions (`junction_surface(free_boundary=True)`, v2 only):
  only road mouths fixed (CG solve), plus connected lanes overlapping the junction as anchors.
- Elevation: shared-node corrections fade over |Δ|/3% (12–60 m, `correction_field`), exact only
  at shared/corrected nodes (they stopped at the next OSM node: 2 m tents).
- Sidewalk collars only where an arm has a SUMO sidewalk (service dead ends had collars;
  sidewalks 118 k → 55 k tris on 1 km). BeamNG navigation looks junction surfaces up by every
  member of a cluster (unmatched nodes 774 → 95).
- 1 km (base → elev-16): v2/fallback 47/250 → 211/86; connected steps >10 cm 1 → 1 (same legacy
  overlap at fallback `8814372535`, 0.165 m); grade changes >5 points 119 → 110; crossfall >6%
  624 → 263; lane-centre errors 4 → 3; cross-section misses 312 → 263; ZIP 7.83 → 7.95 MB;
  build 3:17 → 4:22 (+~30 % roadgen). BeamNG nav: chord max 0.71 → 0.40 m, chords >5 cm
  141 → 191 (engine node spacing; more transitions).
- Bilychi 4×4 (08 → `out/elevation-v2/bilychy-10`): v2/fallback 532/1769 → 1669/632 (endcap 595,
  T 588, X 144, cluster 111); connected steps >10 cm 25 → 11, >30 cm 8 → 8 (all old fallback/legacy
  sites: roundabout `1200327578`, lane overlap `1224968999`/`556798997`, fallback Y/X pair
  `12997711925`/`13075480239`), max 0.424 → 0.368 m; crossfall >6% 3023 → 1100; grade changes
  >5 points 467 → 632; lane-centre errors 29 → 34 (2 new without surface, rest 5–11 cm);
  cross-section misses 2412 → 1902. Build 62 min (was ~32): `stitch_mesh` scales with patches.
- Trade-off seen only on 4×4: existing v2 X/T got +38/+29 internal grade breaks. A core levelled
  along the flatter road makes the steeper road catch up within its transition (grade overshoot
  ~(1+e/L)). Longer side transitions would help; not done.
- Failed experiments: profiles from lane centreline points (binned, then per-lane averaged) —
  worse than averaged rays (smooth >5: 176 vs 110 on 1 km), reverted; the useful part kept is
  the lateral weight by arm area. Lab `close_junctions` control now resolves as v2 (expected
  updated). A `git stash` of roadgen.py was run by mistake and popped back immediately.
- Pre-existing, not fixed: service roads crossing without a shared node get a 0.55 m lane spike
  from `align_strips` (`60252301#7_0`); a T at `1724206503` sits in a 1.5 m dip because an
  approach comes from a way joined by netconvert without a shared OSM node (heights unconstrained).
- Checks: lab `out/roadgen-v2/lab-claude-1` 24/24 expected (116 v2 / 16 fallback, was 52/80;
  steps max 25 mm, lane errors 0); full suite 405 OK, 1 skipped (`logs/1km/unittest-full-2.log`),
  new tests for endcap, through-road core, flattest pair, shared lane, clusters, correction field,
  free junction boundary. BeamNG compact export of Bilychi-10 (`out/elevation-v2/bilychy-10-beamng`,
  level `kyiv_bilychy_elevation_v2`): ZIP 66.3 MB (Bilychi-08 65.6 MB); nav chords max 3.39 → 1.02 m,
  >5 cm 750 → 987, unmatched 539 → 458. Installed (owner request): `mods/kyiv_bilychy_roadgen_v2.zip`
  = Bilychi-10 (replaced Bilychi-08, a copy stays in `out/elevation-v2/bilychy-08-beamng`) and
  `mods/kyiv_bilychy_1km_v2.zip` (1 km elev-15, level `kyiv_bilychy_1km_v2`). Not driven yet.

## 2026-10-05 — v2 template coverage regression, junction timelapses, Reddit draft (Claude)

- Bilychi-07 had only 264 v2 / 2037 fallback junctions (first v2 build: 522/1779): 536
  rejected as "transition is not a single ribbon". The dense elevation ribbons union with
  zero-area pinholes between triangles and between lanes. `roadgen._solid` fills holes
  < 1e-6 m² (`SPECK`) per lane and per arm union; real islands stay (12 remain, 0.2–1.4 m²).
  The lab had the same regression hidden: Codex's 50/82 "two supporting junctions differ"
  is back to 52/80 (lab-07). Test `test_lane_areas_fill_pinholes_but_keep_real_islands`.
- Bilychi-08 (`out/elevation-v2/bilychy-08`): 532 v2 / 1769 fallback (T 366, X 101,
  transition 25, Y 15, split 13, merge 12); connected steps >10 cm 25, max 0.424 m, none
  >60 cm; grade changes >5 points 467; crossfall >6% 3023 (Bilychi-07 1667) — more v2
  cores on slopes, where one road's grade is the other's crossfall; not investigated further.
  Full suite 398 OK, 1 skipped (`logs/elevation-unittest-claude-3.log`).
- Installed: Godot `game/data/bilychy_roadgen_v2` = Bilychi-08 (backups in
  `.cache/replaced/`); BeamNG `mods/kyiv_bilychy_roadgen_v2.zip` (level
  `kyiv_bilychy_elevation_v2`, SHA-256 b1e73bc8…). The owner had renamed the Bilychi-07 ZIP to
  that name and removed the older Bilychi ZIPs; the Bilychi-07 ZIP was moved to
  `out/elevation-v2/replaced-mods/` so only one ZIP holds the level.
- Timelapse: `--timelapse-close=D` (game/scripts/timelapse.gd) orbits `--timelapse-near` at
  about D m, shrinks the reveal wave and the street flight to that scale. First take
  (close 110, Bilychi-07) crashed Godot (0xC0000005) at frame 506 during the street
  flight; the eight later takes (close 75/80) completed 630 frames each.
  Takes: `logs/timelapse/junctions-2026-10-05-c/` (Bilychi-08, both X junctions are v2).
- Reddit draft `docs/REDDIT_POST.uk.md` (roads/junctions); media in
  `out/reddit-ua/roadgen-v2/`: 72 s montage, four 42 s takes, eight before/after pairs
  (pairs are from the 2026-10-03 shots, i.e. pre-elevation v2). Not published.

## 2026-10-05 — roadgen-v2 elevation: real-map regressions (Claude)

- Codex's Bilychi-03 ran pre-final code (started 22:10, last edits 22:18) and died with its
  session. Rebuilt as `out/elevation-v2/bilychy-04` (final Codex code, same verified inputs):
  against the earlier v2 world, re-audited with the same current audit, it regressed —
  connected steps >60 cm 0 → 5 (max 0.69 m, acceptance `blocked`), grade changes >5 points
  293 → 544, crossfall >6% 893 → 2868, absolute grade over limit 3023 → 10778. Lab-05
  (final Codex code) was clean, as lab-04: the lab has no rings, wide bends or real DEM.
- Elevation-only bench (OSM + z12 DEM, ~17 s, no netconvert) reproduced it: v2 tracked the
  DEM to 2 cm median, i.e. barely filtered. A larger radius made it worse (1498 breaks at
  R=96): 85/107 breaks sat within 3 m of branch nodes, where every chain ended and was
  filtered alone. Not kept: local quadratic / R=48–96 sweeps.
- Fixes in `road_elevation`: (1) chains continue through a junction on the straightest
  unused edge within 35° (`STROKE_TURN`), so a straight street is one filtered stroke and
  side roads join it; bench breaks >5 points 107 → 64 (legacy 13, mostly service/DEM
  cliff), >2 points 718 → 253 (legacy 303). (2) `BendField` no longer fits a plane: the
  plane carried terrain slope across wide roads as crossfall (3-lane roundabout
  `1200327578`, lanes 8 m apart, 0.64 m apart in height → the 0.69 m junction step).
  Near bends it now averages dense profile stations with a Gaussian whose width grows
  with centreline distance; bend weights are summed (closed rings included), never
  switched by nearest centre (the old switch stepped 0.25 m on a synthetic ring).
  Bilychi-05 (only the nearest-switch fix, still planes) did not move the step: 0.68 m.
- Bilychi-07 (all fixes): steps >60 cm 0 (max 0.424, acceptance `pending`), >10 cm 26
  (old v2 31), crossfall >6% 1667, lane-centre errors 29 (old v2 26 with the v2 audit),
  grade changes >5 points 517 / >2 points 4402. By lane: ordinary lanes are at parity
  (99/776 vs old 128/743), v2 template connectors 8/159 (old 4/125); fallback-junction
  connectors carry the rest, 410/2950 vs 161/1096 — IDW junction surfaces between the now
  steeper (DEM-preserving) approaches. Absolute grade over limit stays ~3.5× legacy by
  the DECISIONS choice not to flatten terrain; way `60545126` keeps a 9 m DEM drop over
  ~40 m (flagged in `road_elevation.json` spikes, max correction 3.54 m).
- Lab-06: 24/24 expected status, 50 v2 / 82 fallback, 0 lane errors, 0 changes >5 points
  (12 → 16 >2 points); max connected step 1 mm → 25 mm between opposite lanes of one curved
  edge (`10066`): the Gaussian field is not linear, so differently placed ribbon vertices
  interpolate it differently. Below the 10 cm threshold; noted, not fixed.
- Pre-existing, not elevation: service way `993483437` ends ~2 m above the road it joins at
  `11363616237` in the old world too; lab cross-section misses (107) are lane edges inside
  the 4→2 taper of `width_transition` (SUMO S-curves) plus ≤3 cm boundary samples.
- Checks: full suite 397 OK, 1 skipped (`logs/elevation-unittest-claude-2.log`); new tests
  for ring blending and through-junction strokes. BeamNG compact export of Bilychi-07
  (`out/elevation-v2/bilychy-07-beamng`, level `kyiv_bilychy_elevation_v2`) completed:
  ZIP 62.8 MB (old v2 51.2 MB), DecalRoad height audit over_2m 16 (old 20), max 3.59 m
  (old 16.46 m); navigation chords 146,607 samples, 793 >5 cm, max 3.39 m, 543 without an
  owning surface. Installed as `mods/earth2road_bilychy_elevation_v2.zip` (renamed so the
  old `earth2road_bilychy_roadgen_v2.zip` stays for comparison; SHA-256 f8a53f14…);
  not loaded in game yet.
- Open: (a) owner decision — keep DEM-preserving grades (3.5× more >6% samples) or filter
  harder; (b) fallback junction surfaces (IDW) are now the main roughness source;
  (c) Bilychi-07 installed but not driven in BeamNG/Godot yet.

## 2026-10-04 — roadgen-v2 elevation (implementation and acceptance in progress)

- V2 uses DEM stations <=2 m apart, robust local linear filtering over a 24 m radius,
  and degree-two graph chains across OSM way boundaries. Shared source nodes, paired
  carriageways, structure heights and ramp assumptions remain constrained by the existing
  elevation rules. Legacy keeps its original height path. Heights remain derived/synthetic.
- Dense road profiles feed the whole ribbon width, junction transitions, ground boundaries,
  lane positions and paint. Local planes around sharp ground-road bends avoid jumps between
  nearest source segments; bridges/tunnels are excluded from that additional fit.
- Added absolute surface grade (6% / service 12% warning thresholds), profile grade and
  cross-section diagnostics. BeamNG v2 navigation samples its own road/junction triangles,
  retains height stations subject to the existing navigation-radius spacing, and reports
  residual chord errors rather than violating the engine's node-spacing constraint.
- Completed intermediate lab `out/elevation-v2/lab-04`: all 24 primary cases retain their
  expected v2/fallback status; 50 v2 / 82 fallback effective junctions (two supporting
  junctions differ from the old 52/80). Zero contacts exceeding the audit's 1 cm reporting
  floor, zero lane-centre errors >5 cm, zero grade changes >5 percentage points / 2 m;
  12 changes >2 points remain. Cross-width audit: 15,375 sections, 107 sections missing at
  least one same-topology surface sample; this is not a claim of full-width acceptance.
  Both exporters completed. Latest small diagnostic/structure-protection fixes postdate
  this lab snapshot. Real-map and engine acceptance are still pending.
- Failed experiments: lab-01 densified walking-area outlines too and hit a GEOS overlay
  error; densification is now limited to passenger lanes. Lab-02 hit NumPy int64 JSON
  serialization in the smoothness counters; profile queries now return native floats.
  Lab-03 exposed nearest-segment height jumps inside sharp source bends; the shared bend
  field removed changes >5 points in lab-04. Bilychi attempts 01/02 were stopped while
  still preparing roads to restart with these fixes; neither is a completed map result.
- Initial full suite: 393 discovered, 2 errors (Godot subprocess timeouts in sandbox),
  1 skipped; no assertion failures (`logs/elevation-unittest-01.log`). An unsandboxed
  final discovery, Bilychi-03 build and isolated lab BeamNG drive check are running.

## 2026-10-03 — roadgen-v2 lab fixes (Claude)

- Found 3/10 roadgen tests failing: the "curved approach crosses template boundary" guard
  rejected straight X/width-transition cases, because the approach before its socket stuck out
  of the curb-return curve. The core now absorbs that stub (`candidate`); the guard stays.
- Lane-centre stations without pavement (`lane_surface_errors`, `10046_1` at `y_acute`):
  `scene.triangles` silently drops pieces < 0.01 m², so sockets cutting a strip near its own
  station lost slivers (and patch draping lost cell corners). `triangles`/`draped_triangles`
  take `min_area`; roadgen uses `MIN_PIECE = 1e-4` (= `prepare.MIN_TRIANGLE_AREA`). Default
  0.01 unchanged, so legacy output is unaffected.
  First (wrong) guess was the stitching of far knots; restricting knots to patch boundaries
  doubled sub-mm cracks (1324 vs 614 holes > 1e-4 m²; legacy 670) and was reverted.
- Fixture: merge/split connectors ran through the junction centre without a shared node
  (60 m² overlaps in v2 and legacy); now routed around. The roundabout ring had only one node
  per arm, so it rendered as a diamond in BeamNG (owner screenshot); now a node every 15°.
  The generator draws what OSM gives; coarse real rings would still be polygonal.
- Size: `roadgen.sidewalks` turned whole sidewalk strips near a collar into 2 m-draped walking
  areas and re-draped every area (walk triangles 520 → 65 601). Now strips are trimmed
  (`_runs_clear_of`), only the near remainder becomes an area, untouched areas are kept, and
  the collar's outer edge (never asphalt-facing) is `buffer(3, quad_segs=4).simplify(.05)`.
  Patch cores are triangulated whole (planar), transitions in ≤2 m cross-sections
  (`BAND_STEP`) instead of a 2 m world grid. `beamng_pavement.road_mesh` uses v2 strip
  triangles (the main surface export already did).
- Lab (all 24 cases, BeamNG compact, `out/roadgen-v2/all-claude-ring`): 24/24 expected status
  (18 primary v2, 6 fallback controls); 52 v2 / 80 fallback effective junctions; connected
  steps max 12.5 mm (same site 12.9 mm in legacy), 0 uncovered lane stations, 0 patch/road
  overlaps > 1e-3 m²; DecalRoad height audit max 0.291 m (legacy 0.297). Export: surfaces
  35 252 tris (legacy 36 223), sidewalks 31 529 (18 480), ZIP 1.95 MB (1.62 MB); geometry
  ~15 s. The extra sidewalk triangles are kerbs along curved curb returns — not reduced further.
- Owner's second BeamNG test still showed the 4-node diamond after installing the fixed ZIP:
  `temp/levels/kyiv_roadgen_lab` held .cdae compiled at 15:00 under the same mesh names, and
  the ZIP entries carry the fixed `ZIP_STAMP` (2026-09-24), so the game kept the old meshes.
  `static_mesh` now appends a 10-hex SHA-256 of the .dae to its file name; a changed mesh is a
  new path and cannot hit a stale cache (signs/signal head keep fixed names). Export tests
  85 OK. Re-exported ZIP (`all-claude-ring/beamng2`) copied to the game's mods folder;
  not yet confirmed in game.
- First real v2 map: Bilychi 4×4 km (`out/roadgen-v2/real/bilychy_v2.json`, the verified
  offline inputs of `bilychy_offline_verified`), build 32 min, compact export 8.5 min.
  522 v2 / 1779 fallback (T 360, X 98, transition 23, Y 15, merge 13, split 13). Fallback
  reasons: endcap 722, approach too short 586, socket cross-section 141, approach tangent 112,
  overlapping group 112, single-ribbon 25, structure 24, roundabout 21, internal lane 18.
- The first Bilychi build had 32 lane stations > 5 cm off the pavement (legacy 8), all on v2
  patches: lanes got patch heights only at sparse SUMO vertices while transitions bend
  (smoothstep). `roadgen.lane_heights` adds a station every 1 m (`LANE_STEP`) inside a patch,
  incl. internal lanes. Rebuild: 8 (the same legacy sites; 7 uncovered, pre-existing).
  Shot snapping in `prepare` now indexes `road_z.shape` instead of the SUMO shape.
- The first export failed with MemoryError (109 MiB) with ~8.6 GB free commit and no other
  Python running (probably the game open); the second run, after rebuild, passed.
- Bilychi v2 vs the 2026-10-02 legacy export: connected steps > 10 cm 31 vs 32, max 0.372 m
  both; ZIP 51.2 vs 45.5 MB; surfaces 925 k vs 955 k tris; sidewalks 527 k vs 271 k;
  DecalRoad height audit over_5cm 4846 vs 3165, over_20cm 1674 vs 1458, over_2m 20 vs 20
  (max 16.46 m at the same pre-existing node). DecalRoad nodes come from SUMO edge shapes,
  so they still chord through transitions — follow-up. Installed as
  `earth2road_bilychy_roadgen_v2.zip` (level `kyiv_bilychy_roadgen_v2`); not loaded in game yet.
- Godot comparison (`out/roadgen-v2/compare/bilychy_compare_{1,2}.jpg`): 8 v2 junctions
  (2 X, 2 T, Y, transition, merge, split) shot with identical poses in the installed legacy
  `bilychy_offline_verified` and the new `bilychy_roadgen_v2` (poses injected into each
  `index.json`, originals restored). `main.gd --shots` produced the chase-camera view for every
  pose (the player camera re-took the viewport); the shot camera is now made current every
  wait frame and before capture, and the log prints `camera=true`.
  Seen in v2: curved curb returns and continuous sidewalks instead of jagged wedges; the
  transition case lost its asphalt step. Defects to check: at T `436619329` and the Y the
  sidewalk collar wraps across an adjacent paved strip (not in the carriageway cut?); at the
  merge the crosswalk on the left arm is gone (legacy had one).
- Checks: `test_roadgen` 13 OK (3 new); full suite 382 OK, 1 skipped
  (`logs/unittest-roadgen-claude-final.log`). Bilychi legacy/v2 real-map builds were started
  and cancelled at the owner's request; no real map has been built with v2 yet.

## 2026-10-03 — roadgen-v2 prototype (implementation in progress)

- Added opt-in `road_geometry.mode: v2` (default remains legacy), OSM source graph,
  SUMO binding, T/X/Y/merge/split/transition templates and generated shared pavement,
  sidewalk collars and paint clipping. `tools/roadgen_lab.py` builds synthetic offline
  fixtures or replays prepared geometry, producing PNG/SVG and JSON diagnostics.
- First complete 24-case lab: 18 primary cases use v2; short/close/divided/roundabout/
  five-arm/structure controls use explicit fallback. Supporting streets are counted
  separately from primary cases. No engine acceptance yet.
- Checks so far: `python -m unittest discover -s tests -p test_roadgen.py -v`
  10 passed, including offline reproducibility. Existing surface seam suite: 12 passed.
- Failed fixture attempts: wrong example-resource path; then interleaved OSM nodes/ways
  made netconvert read only the first way, so spawn selection failed. Fixed ordering.
  Initial grade tests exposed a snapped-boundary tolerance error; corrected 1e-7 to 2e-6 m.
- Initial lab audit found up to 0.127 m steps and one sub-millimetre uncovered station.
  A shared-boundary station pass and height tolerance correction are being revalidated.
  Results under ignored `out/roadgen-v2/`; old attempts retained for comparison.

## 2026-10-03 — roadgen-v2 planning backlog

- Created and switched to `roadgen-v2` from `generator-local-cut`, preserving the existing
  uncommitted district configs/tool, Reddit draft and handoff additions.
- [PLAN.md](PLAN.md) now holds the user's 12-part backlog: road graph/junction families,
  elevation, BeamNG export v2, Building Grammar, hybrid geometry/textures, city props,
  generation/nightly pipelines, Ukrainian showcase maps, city packs, monetization and devlog.
- First priority is roads + shared junction/elevation transitions, then measured BeamNG export.
  The 4×4 km/~20 MB baseline and 22–35/30–50 MB estimates are planning references to verify,
  not new benchmark results. Existing functionality must be audited before implementation.
- Next work unit: choose a reproducible baseline, inspect existing road/elevation/export code
  and tests, then define the road graph and junction prototype. No implementation started here.
- Initial branch creation failed because the sandbox could not write `.git/refs/heads`;
  retry with approved elevated permissions succeeded. No generation/runtime experiments run.
- Checks passed: `git diff --check -- docs/PLAN.md docs/HANDOFF.md`; a `python -c` check
  calling `tools.check_publication.inspect_file` on those two files (UTF-8, local Markdown
  links and source hygiene), plus section-number assertions (1–12; 115 unchecked tasks).
  `git branch --show-current` reports `roadgen-v2`. Full unittest/runtime checks were not run
  for this documentation-only change; no previous map acceptance status was changed.

## 2026-10-03 — Kyiv district and suburb maps for BeamNG (overnight batch)

- `tools/configure_districts.py <admin.geojson>` writes `config/districts/<id>.json` and
  `config/districts/areas/<id>.geojson` from OSM administrative relations (Kyiv raions,
  admin_level 10; towns, admin_level 9), listed with relation IDs in `AREAS`. The outline is
  buffered 150 m (coarse arcs) and simplified 10 m in the tool; configs use `buffer_m: 0`.
  The admin GeoJSON came from a one-off pyosmium area scan of ukraine-260918 (not kept in Git).
- Failed: the first configs used `buffer_m: 150` from `boundary_area` (64 segments per quarter
  arc). The netconvert `--keep-edges.in-geo-boundary` argument reached 45–72 k characters;
  Windows CreateProcess failed with an empty netconvert.log ("SUMO netconvert failed",
  Podilskyi). Pecherskyi (12.6 k) passed; Solomianskyi, started with the long outline, also
  passed netconvert — not investigated why.
  Not fixed in core: `corridor.geo_boundary` has no length guard.
- Districts above 55 km² are split into equal-area parts along the longer axis (200 m overlap,
  ids `_w/_c/_e`, `_s/_cs/_cn/_n`); union of parts covers 100 % of each relation. Reasons:
  build memory (a 45 km² build peaks at ~13 GB private; the machine has 32 GB RAM + 8 GB
  pagefile, and three parallel builds dropped free commit to 1.1 GB) and the earlier
  8 × 8 km Shuliavka level that BeamNG could not load.
- Per-map extraction from the full 877 MB PBF took ~400 s. A Kyiv-area cut
  `ukraine-260918-kyiv.osm.pbf` (36 MB, md5 41a03808…, bbox 30.10 50.16 31.06 50.68) was
  made with the same selection as `core/osm_extract.py` (PBF output instead of XML) and is
  referenced from the district configs as `local/ukraine-260918-kyiv.osm.pbf` (cache-only;
  nothing is downloaded from that "url"). `ring_beresteiskyi` still uses the full PBF.
- Batch runner (ignored, `out/districts/`): `run.py` = build → `export --optimization compact`
  → copy ZIP to `%LOCALAPPDATA%/BeamNG/BeamNG.drive/current/mods`; `worker.sh` takes items
  from `todo.txt` when ≥14 GB commit is free and 15 min after the previous start. Results:
  `out/districts/status.jsonl`; logs `logs/districts/`. The runner's `peak_gb` is always 0
  (it reads the venv launcher process, not the real interpreter) — ignore it.
- Ring + Beresteiskyi regenerated from `config/ring_beresteiskyi.json` with the same level ID
  `kyiv_ring_teremky_berkovets`, compact: ZIP 92 MB (old legacy ZIP 258 MB). The old
  `akadem_drive_ring_beresteiskyi.zip` and the game's 1.9 GB `temp/levels/` cache for that
  level were moved to `out/districts/replaced-mods/` (not deleted) to avoid two ZIPs with one level.
- Timings (one map, two in parallel): Pecherskyi 22 km² build 38 min (incl. full-PBF extract)
  + export 18 min, ZIP 65 MB; Shevchenkivskyi 31 km² 75 + 25 min, 95 MB; Solomianskyi 45 km²
  109 + 37 min, 116 MB; Podilskyi 41 km² 56 + 26 min, 84 MB; ring 72 + 27 min, 92 MB.
- Fixed (core, `scene.py`/`prepare.py`): large maps stalled in the "trees" stage for hours
  (py-spy: Dniprovskyi west 3.5 h, CPU-bound, flat memory). Three map-wide polygon operations
  repeated per small feature: `paths` (`line.difference(covered)` per footway), green areas
  (`difference(cover_cut)` per area) and `draped_triangles` (whole ground polygon ∩ every
  20 m cell). `LocalCut` splits a polygon above `LOCAL_CUT_COORDS` (100 k vertices) into
  quadtree tiles once and subtracts only the tiles near each feature; `draped_triangles`
  halves along the same cell grid when vertices × cells > `DRAPE_SPLIT_WORK` (50 M). Below
  the thresholds the original operations run unchanged. Synthetic benchmark: 300 path
  differences 2.7 s → 0.1 s. After the fix Dniprovskyi west reached "signs" in 24 min.
  Tests `tests/test_local_cut.py` (equivalence vs direct difference/drape); full suite
  369 OK, 1 skipped (`logs/districts/unittest-drape.log`). Maps built before this change
  used the old code; geometry differs only by floating-point noding at tile seams.
- Follow-ups found during the batch: `get_num_coordinates` returns int32 and the
  vertices × cells product overflowed (RuntimeWarning in every large build; a wrapped value
  only selects the slower, equivalent path) — now cast to int. Holosiivskyi north failed with
  GEOS "Invalid number of points in LinearRing found 3" in the trees stage (no traceback; the
  CLI prints one only with `AKADEM_MAPS_TRACEBACK=1`, now set by the batch runner). Most likely
  `clip_by_rect` in `LocalCut`; it now falls back to `intersection(box)` on GEOSException,
  and the retry passed. Not proven to be the source. Final full suite after these: 369 OK,
  1 skipped (`logs/districts/unittest-final.log`).
- Result (2026-10-03 11:5x): 31 ZIPs in BeamNG mods, 1.61 GB — 22 Kyiv district maps
  (Pecherskyi, Shevchenkivskyi, Podilskyi, Solomianskyi whole; Dniprovskyi 2, Sviatoshynskyi 3,
  Obolonskyi 3, Darnytskyi 3, Desnianskyi 3, Holosiivskyi 4 parts), ring, and 8 towns (Irpin,
  Bucha, Brovary, Vyshneve + Kriukivshchyna, Boryspil, Vyshhorod, Boiarka, Sofiivska +
  Petropavlivska Borshchahivka). ZIPs 17–116 MB; forest/floodplain parts are the small ones
  (Darnytskyi east: 197 motor-road ways, 420 lanes). Hostomel was not included (no
  settlement-level boundary in this extract; the hromada is 67 km² with the airfield).
- Not done: no map from this batch was loaded in BeamNG (runtime_verified false; acceptance
  pending). Whether 45–55 km² compact levels load is untested.

## 2026-10-02 — local sources and offline preparation

- SUMO resolves native eclipse-sumo binaries before pip wrappers; `doctor` exercises
  netconvert and duarouter. Both report 1.27.1 after checkout relocation.
- Added verified area/selection-keyed OSM snapshots, recursive relation validation,
  local PBF registry, Geofabrik coverage catalog/explicit size-confirmed downloads,
  and OSM + DEM preparation/readiness. Picker and CLI share source actions.
- PBF scan initially passed an unsupported bare SimpleHandler to osmium.apply; now uses
  a native filter. Invalid PBF header rejection avoids a native Windows handle leak.
  Old tests expected three per-host retries and a way without nodes; fixtures corrected.
- Godot editor import and the graphical picker harness (`DATA_PICKER_OK`) passed outside
  the sandbox; the sandbox could not create Godot AppData directories.
- Existing Ukraine PBF checked against its recorded Geofabrik MD5 and registered with the
  catalog polygon (SHA-256 1340de17a955…, 878444553 bytes). Fetching the dated remote MD5
  timed out twice; no replacement PBF downloaded.
- Fixed: files moved out of `tempfile.TemporaryDirectory` kept its owner-only ACL
  (Python 3.13+ maps mkdtemp's 0o700 to an ACL on Windows). Ten DEM tiles prepared by the
  Codex sandbox user in `out/generated/.akadem-inputs/terrain/12/239[1-4]/` are unreadable
  and undeletable for the normal account; status reported them missing. Cache staging now
  uses `context.scratch_directory` (plain mkdir, inherited ACL); regression test
  `CacheAclTests`. The owner removed those ten files as administrator.
- Fixed: a snapshot/package with `coverage: null` raised AttributeError from shapely
  instead of being skipped. Restored the corrupted `©` in sources.json license text.
- Acceptance (fresh cache `out/generated/.akadem-inputs-acceptance`, verified Bilychi
  snapshot copied in): `prepare` online fetched 17 DEM tiles, no Overpass/PBF use;
  `status --offline` ready, 0 missing; `generate --offline` build/export/install exit 0,
  111 tiles, 17082 lanes, 135 verified files, zero download events; `validate world` OK.
- Runtime on Bilychi: drive 5/6 — `stop_line` failed (car left the spawn lane onto
  pavement at the junction, min speed 3.4 km/h). Surface 11 missing of 5957 probes.
  Control on previously accepted `kyiv_shuliavka` with the same tools: drive 6/6, surface
  9 missing of 11608 — the surface gap predates this work; Bilychi's spawn junction is a
  map geometry issue, not a source issue. Neither is certified.
- Full suite: 363 tests OK, 1 skipped. Logs: `logs/source-claude-unittest-final.log`,
  `logs/bilychy-*-claude.*`, `logs/bilychy-check-*.log`, `logs/shuliavka-check-*-control.log`.

## 2026-10-02 — Earth2Road branding and presentation

- Brand/distribution/CLI/launcher: Earth2Road / `earth2road` / `Earth2Road.cmd` only; the
  former names, CLI aliases and launcher were removed. `akadem_maps`, map IDs, world formats
  and `AKADEM_*` remain as internal technical names. BeamNG ZIPs are `earth2road_<map>.zip`;
  mod metadata, LICENSE and the example fixture credit "Earth2Road contributors" (the tiny
  example's `inputs/manifest.json` config hash was updated). Terrain `persistentId` seeds
  changed, so a re-export is not byte-identical to an older ZIP.
- Godot uses its default user directory for the project name (`app_userdata/Earth2Road`);
  settings from the previous directory (language, export folder, mode) are not migrated.
  Timelapse takes now use fresh directories; an existing explicit output is rejected,
  never cleared. Clean-overlay capture is optional.
- Full unittest discovery: 339 run in 554.412 s, 336 passed, 1 skipped, 2 errors.
  Both errors were Godot subprocess timeouts inside the sandbox (asset props and
  vehicle availability). Both passed outside the sandbox: 2 tests, 1.046 s.
  Logs: `logs/earth2road-unittest.log`, `logs/earth2road-godot-retest.log`.
- Built wheel/sdist; installed new non-editable package; `tools/ci_offline.py` passed
  from a temporary directory, including new CLI and both aliases, world build,
  validation, both adapters and Godot install. `pip check` and publication audit pass.
  Headless Godot editor import completed without script errors.
- Failed setup experiment: `pip install --no-build-isolation` lacked setuptools.
  Installed build tools locally and retried successfully. No runtime pin changed.
- Kyiv Maidan, Lviv centre and Odesa compact ZIPs exported and run in BeamNG 0.39.4
  from separate profiles (`out/earth2road-launch/beamng/*/result.json`): load 14–15 s,
  one route of 226–317 m each, 4 wheels in contact, no damage, 303 surface samples
  with max error < 1 mm, all signals bound, 5–6 moving AI entries. Download folder
  `out/earth2road-launch/downloads/` (ZIPs, README.uk.md, SHA256SUMS, runtime-results).
  This is one route per map, not whole-map acceptance.
- Video `out/earth2road-launch/video/Earth2Road-ukraine-dev-60s.mp4` (60 s, 1080p30, silent).
  The first Godot take stalled: GEVP squares the action strength, so throttle 0.38 gave
  0.14 and the car stayed at 1 km/h in N; the HUD also still read "TERRA / DRIVE".
  Fixed (`hud.gd` → EARTH2ROAD, throttle 0.8, export shot shows the compact mode) and
  recaptured; the stalled take is kept as `godot-promo-v1-stalled`. `edit_promo.py`
  keeps badges off the top edge on the gameplay shot, where the game HUD is.
- Godot UI in the picker/export shots is English although the locale is set to `uk`.
- GitHub repository renamed to `Alezx311/earth2road` (origin updated); docs, the Reddit
  draft and the download README point there. Not done: public posting and release
  publication; the Reddit draft still needs the release URL.
- Reddit draft now has per-map stats for the ten Ukrainian 4 km squares and points at
  `out/reddit-ua/<id>/shots/ua-oblique.png`. Counts come from each map's `sources.json`,
  `audit.json` and non-internal SUMO lane lengths. Copy with images:
  `out/reddit-ua/POST.uk.md`. Not posted.

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
  `akadem_maps`, so `.venv/Scripts/earth2road` runs stale code (it still rejects licence plates).
- Now the largest category is road surfaces (120 k tris, 46 % of DAE) — path C.
- **Not checked in BeamNG**: kerb look without bevel, kerb/wheel collision, load time/RAM.

### Separate variants: `--optimization balanced+writer|kerbs|terrain`

`--optimization` now composes features with `+` (`optimization_mode`/`features` in
`beamng_geometry.py`): `writer` (A), `kerbs` (B), `terrain` (C); `compact` = all three.
`balanced` (default) and `legacy` are unchanged. Accepted by `earth2road export`,
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

### In-game benchmark of the variants (BeamNG.drive 0.39, RTX 2070 SUPER, 1920×1080 Normal)

`tools/beamng_bench.py` + `tools/beamng_bench.lua`: each ZIP in an isolated profile under
`out/bench/<run>/` (never the user's BeamNG profile), launched cold (fresh `.cdae` cache) then
warm; load time is the game's own `Level loaded in …` line; memory = private bytes of the game
process; per view: 4 s streaming, screenshot, 4 s frame times. Same six cameras for every variant
(spawn, signal, street, kerb close-up on an at-grade sidewalk, low overview at +160 m, overview).
Final sheets and table: `out/bench/livo-final/` (`compare-<view>.jpg`, `results.md`).

| variant | level load cold s | level load warm s | private MB at load (warm) | best FPS (6 views) |
|---|---|---|---|---|
| 0 balanced | 13.1 / 11.0 | 6.9 / 5.7 | 3033–3277 | 177–212 |
| A writer | 11.6 / 9.6 / 9.8 | 7.0 / 5.7 / 5.8 | 2891–3085 | 179–210 |
| B kerbs | 11.1 / 13.3 | 6.7 / 5.9 | 3091–3152 | 163–198 |
| C terrain | 12.2 / 11.1 | 5.8 / 6.3 | 3138–3324 | 163–200 |
| A+B+C | 9.1 / 9.1 | 5.9 / 5.8 | 3163–3238 | 166–206 |

- At 1 km² the map is too small to separate the variants: the game's own ~3 GB dominates
  memory, warm loads are 5.7–7.0 s for all, FPS is GPU-bound at 160–210 everywhere. Only the
  cold load (DAE → .cdae conversion) shows a consistent gain: A+B+C 9.1 s in both runs vs
  11–13 s. The real test is 8 × 8 (balanced vs compact).
- FPS noise: in several runs FPS fell to 2–15 for 3–4 minutes spanning consecutive game
  processes and any variant (e.g. end of A cold → all of A warm → start of B cold), then
  recovered mid-run. Not caused by a variant (A alone re-measured at 173–210 fps). Hence
  "best per view over all runs"; GPU utilisation log `logs/bench-livo2-gpu.csv` (≈100 % throughout,
  so it does not identify the other load).
- One game crash: balanced warm in run 2, C++ crash 0.3 s after the level loaded
  (`out/bench/livo2/livo_0_balanced/warm/beamng.log`); the same run passed in run 1.
- Fixed during the benchmark: the terrain material was the old `diffuseMap` form and rendered
  flat grey/beige in 0.39 — now PBR (shared `t_grass_01` detail, `t_macro_grass` macro, own 256²
  flat base maps; base maps must equal the texture set's `baseTexSize`, otherwise the game logs
  "dont have required size" and drops them → near-black ground). Cameras: the old low
  overview sat 8 m above an 83 m roof; the kerb view now targets an at-grade sidewalk.
- Visible in C/A+B+C: the terrain continues past the map as a flat plain to the 2048 m grid
  edge, and the source-data spike near (−420, 118) shows as a thin vertical needle.
 (`--optimization balanced|legacy`)

Started by Codex (ran out of quota mid-benchmark), finished by Claude.

- `balanced` is the default for `earth2road export`, `tools/export_beamng.py` and the GUI tool;
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

Report: "`earth2road` doesn't exist" and `tools/export_beamng.py` "says the map ID/level ID
is invalid".

- `earth2road` exists, but `setup.ps1`/`setup.sh`/`Earth2Road.cmd` install it into `.venv`,
  not onto `PATH`; README only showed the bare command. README (en/uk) now names
  `.venv\Scripts\earth2road`, venv activation and `python -m akadem_maps`; setup prints the
  BeamNG export command with the venv path.
- `tools/export_beamng.py --map` takes an installed map ID; a world folder path
  (`out/generated/<id>`) failed with a bare `Invalid map id`. The tool now has `--world`, and a
  `--map` value that is a folder with `config.json` goes the same way; both call
  `adapters.beamng.export.export_world` (the CLI's path). Map/level ID errors now show the value
  and the `[a-z0-9_]` rule.
- Checks: tiny world built from `examples/tiny`; `tools/export_beamng.py --map <world>` ZIP
  SHA-256 equals `earth2road export --target beamng` on the same world (d15c36ea…) and
  `earth2road validate --target beamng` passes; `--level-id My-Level` gives the new message.
  `python -m unittest discover -s tests`: 321 passed, 1 skipped (2 new tests in
  `test_beamng_export`). Not checked in BeamNG.drive itself.

## 2026-09-29 — double-click Windows launcher

- `Earth2Road.cmd` at the root: first run calls `setup.ps1`, later runs `start.ps1`
  (both with `-ExecutionPolicy Bypass`, so a downloaded ZIP works). Missing Python 3.11+ →
  offers `winget install Python.Python.3.14 --scope user`, otherwise points to python.org.
  Arguments go to start.ps1; `-File` keeps `--`, so `Earth2Road.cmd --map tiny -- -- --seconds=5`.
- A real `.exe` in Git was not added: binaries are excluded by DECISIONS and `.gitignore`.
- Fixed `setup.ps1`: the committed file held a BEL byte instead of `\a` in
  `game\data\active_map`; Test-Path threw, so setup failed at its last step on every run.
- Checks: fresh clone in a temp folder, first `Earth2Road.cmd` run from zero 176 s
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
`akadem_maps`, map IDs, hotkeys, English/Українська and OSM attribution kept.

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
- Passed: pip check, `earth2road doctor`, `earth2road --version`, `tools/check_publication.py`, `git diff --cached --check`, `tests.test_publication` + `tests.test_demand`. `.sh` files have mode 100755. No remote, no commit. The full suite was not rerun because the changes were whitespace-only.

## 2026-09-28 — standalone extraction

- Extracted the generator, Godot game, SUMO bridge, BeamNG adapter, configuration and tests.
- Preserved `akadem_maps` imports, map IDs and original copyright notices.
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
