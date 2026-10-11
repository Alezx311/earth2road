# World format v2 and adapter API

A **world** is an engine-neutral, self-verifying folder produced by `earth2road build`.
Adapters (`export --target godot|beamng`) only read it; they never modify it.

## Layout

| Path | Content |
|---|---|
| `world.json` | Manifest: `format: "akadem-world"`, `version: 2`, `id`, `generator`, `seed`, `coordinates`, `licenses`, `tools` (Python, platform, package and netconvert versions) and `files` — SHA-256 of every file except `netconvert.log`. |
| `config.json` | The normalised config the world was built from. |
| `index.json` | Map header: `version`, `id`, `name`, `bbox`, `offset`, `base_height`, `tile_size`, `tiles`, `lanes`, `signals`, `tls`, `spawn`, `shots`, `region_profile`, `attribution`, `network_sha256`. |
| `tiles/<i>_<j>.json` | Geometry per tile: `road_strips`, `markings`, `sidewalks`, `walkingareas`, `junctions`, `buildings`, `greens`, `parking`, `paths`, `trees`, `ground`, `signs`, `fences`, `visual_props`. |
| `network.net.xml` | SUMO network (comments stripped so equal inputs give equal bytes). |
| `corrected.osm`, `sources.json`, `audit.json` | OSM after tag corrections, source provenance, build report and assumptions. |
| `inputs/` | Everything needed to rebuild offline: `config.json`, `raw/` (OSM, DEM tiles, optional corridor), `resources/`, `config_root/` files used, and `manifest.json` with SHA-256 and tool versions. |

`validate --target world` re-hashes every file, checks the network hash, that the spawn
lane exists and that every tile parses. Any mismatch is an error, not a warning.

Buildings may carry `typical` = `{kind, provenance: "derived:typical_model", version,
role?, fallback?}` (`akadem_maps/core/building_types.py`). Kinds: `church_orthodox`,
`church_western`, `mosque`, `fuel_canopy`, `mall`, `retail`. A record with a `role`
(`dome`, `bell_tower`, `minaret`, `post`) is a derived part sharing the main building's
`id` and `style_key`; it has the same fields as an S3DB part (`base`, `roof_triangles`,
`local_style`, `roof_color`). `audit.json` → `typical_models` lists every typed building,
including those kept as mapped because OSM has parts or `roof:shape`.

`visual_props` (`akadem_maps/core/yards.py`) are synthetic courtyard items: `{kind, position,
yaw, radius, provenance: "synthetic:yard", rule, source}`; `parked_car` adds `model` (a
passenger entry of `config/vehicles.json`) and `size` [w, h, l]. `yaw` turns the item's local
+Z (car length, bench backrest) in Godot's Y rotation. Kinds: `parked_car`, `bench`, `bin`,
`shrub`, `swing`, `slide`, `sandbox`, `climber`, `carousel`. Godot only; the BeamNG adapter
ignores the field. Counts: `audit.json` → `yard_*`.

## Coordinates

Metres; **X east, Y up, Z south** (Godot compatible). Horizontal origin is the SUMO
projection minus `index.offset`; heights are relative to `index.base_height`. BeamNG
position = `[x, -z, y + vertical_offset]`.

Heights come from a coarse DEM smoothed along the road graph; bridge, tunnel and ramp
heights are assumptions, not surveyed values (`audit.json` → `assumptions`).

Road strips may carry canonical `triangles`, in the same world coordinates. Both
adapters render these verbatim; `points` remains the lane/profile path. Old worlds
without triangles retain their existing ribbon rendering. Generated profile points
and internal turn curves do not mutate the archived OSM or SUMO network.

`surface_audit.json` reports exact triangle overlaps and touching edges, including
junctions; contacts are classified using topology, layer, bridge and tunnel tags.
Height alone never declares a connection. Counts are per surface pair / 2 m cell,
not interchangeable with the earlier lane-sample overlap metric. `road_seams.json`
records generated corrections and reference carriageways. Grade changes are sampled
at 2 m, including internal lanes. BeamNG coordinates in this audit are before the
optional export vertical offset. Structural validation does not imply acceptance.

Corridors accept optional `include_bboxes: [[west,south,east,north], ...]` inside
`config.corridor`. Areas must connect to the corridor. They are unioned with its
polygon, included in the area digest and archived config, and invalidate an old
OSM extract. The union's bounding rectangle is only an envelope, not the map area.

## Provenance rules

- Observed OSM data and generated defaults stay distinguishable: signs carry
  `provenance: osm | derived`, buildings `height_source`, `visual_source`.
- Signal timings are netconvert defaults. Traffic demand is synthetic and produced by the
  Godot adapter, not by the world.
- `config.source_kind: synthetic` (e.g. `examples/tiny`) removes OSM/terrain attribution
  and licenses from the world and its exports.
- `config.region_profile`: `ukraine` enables Ukrainian road signs and licence plates;
  `experimental` (default for a bare `--bbox`) exports no posted signs.

## Writing a new adapter

1. Call `akadem_maps.world.validate_world(world)` first and refuse on any error.
2. Read `index.json` and `tiles/*.json`; convert coordinates from the axes above.
3. Write into a fresh directory through `akadem_maps.context.atomic_directory(output)`:
   the output appears only when the export finished; an existing output is an error.
4. Never write into the world, `game/data` or an active-map pointer. Installation is a
   separate, explicit step (see `adapters/godot/install.py`).
5. Carry attribution: keep `index.attribution` and the `world.json` `licenses` in the
   exported package.

Reference adapters: `akadem_maps/adapters/godot/export.py` (tiles + routes + synthetic
demand) and `akadem_maps/adapters/beamng/export.py` (level ZIP, `artifact.json`,
`acceptance.json` with status `pending`, technical `reports/`).
