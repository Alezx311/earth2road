# Earth2Road command line

Everything the game's menus do is also available from a terminal: scripted builds, exports
and development. Players do not need any of this; see the [README](../README.md).

## Install (generator)

Use Python 3.14 for the pinned setup below. The generator supports Python 3.11+ with
unpinned compatible dependencies. Windows is locally validated; Linux has a CI job.

```bash
python -m pip install -c requirements.lock ".[generator]"               # from a checkout; not published on PyPI yet
earth2road doctor                        # checks numpy, shapely, pyproj, osmium, SUMO netconvert
```

`setup.ps1` / `setup.sh` (and `Earth2Road.cmd`) install the CLI into the local `.venv`, not onto
`PATH`, so a plain `earth2road` is "not found" there. Use `.\.venv\Scripts\earth2road`
(Linux/macOS: `.venv/bin/earth2road`), activate the venv first (`.\.venv\Scripts\Activate.ps1`,
`source .venv/bin/activate`), or run `python -m akadem_maps` with the venv's Python.

Players of an exported BeamNG map need only BeamNG.drive — no Python.

## Quick start — fully offline example

```bash
earth2road build  --config examples/tiny/config.json --inputs examples/tiny/inputs --offline --output out/world
earth2road validate --target world  --input out/world
earth2road export --target beamng --world out/world --output out/beamng
earth2road validate --target beamng --input out/beamng
earth2road export --target godot  --world out/world --output out/godot --offline
```

`examples/tiny` is a synthetic 3×3 street grid with a flat DEM (MIT); it is not OSM data.

## Your own area (bbox)

```bash
earth2road build --bbox WEST SOUTH EAST NORTH --id my_area --name "My area" --output out/my_area
```

- Coordinates in degrees; `west < east`, `south < north`. The antimeridian is not supported.
- Downloads OSM (Overpass) and Mapzen terrain tiles; `--cache DIR` reuses raw inputs.
- `--region-profile ukraine` is the verified profile; any other area builds as
  `experimental` (no posted road signs, stock licence plates, "experimental region" in the title).
- Keep areas modest: a few km² builds in minutes; an ~80 km² area took about 36 minutes.
- For the Godot game, `tools/generate_map.py --lat LAT --lon LON --size-km 1.5` (or M → New map
  in the game) runs build, export and install in one step; see [GAME.md](GAME.md).
- Clear errors for an invalid bbox, an empty road network, no usable spawn road, a failed
  download and missing or tampered offline inputs.

Every build writes to a **new** directory, which appears only when the build succeeded
(cancel = Ctrl+C or SIGTERM, exit code 130, nothing published). Build again from the
recorded inputs with `--inputs <world>/inputs --offline` for identical network and tiles.

## BeamNG export

```bash
earth2road export --target beamng --world out/my_area --output out/my_area_beamng [--level-id my_level]
```

`--world` is a world folder: the `--output` of `earth2road build`, or `out/generated/<id>` for a
map made in the game (M → New map). `--output` must not exist yet. A level ID may contain only
lowercase letters, digits and `_`; by default it is `kyiv_<map id>`. `tools/export_beamng.py
--world <folder> --output <folder>` does the same for older scripts; its `--map` takes an
installed map ID such as `tiny`, not a path.

`--optimization balanced` (default) shares identical vertices in the DAE files, merges flat
ground (≤5 cm height error, tile edges kept exact) and gives sidewalks a simplified collision
mesh without the curb bevel. `--optimization legacy` writes the previous unoptimized geometry.
Further features join with `+`: `balanced+writer` (A: 1 mm coordinates and smoothed normals,
~70 % smaller DAE), `balanced+kerbs` (B: kerbs without the bevel, the visible mesh is the
collider), `balanced+terrain` (C: ground as a native TerrainBlock heightmap); `compact` is
all three. `tools/beamng_bench.py` compares ZIPs in the game (load time, memory, FPS,
side-by-side screenshots) in isolated BeamNG profiles.
Per-category measurements: `reports/performance.json` (`--map`: `<output>.performance.json`).

Output: the level ZIP, `artifact.json` (SHA-256, version), `acceptance.json` (status
`pending` — structural validation is not in-game acceptance) and technical `reports/`.

Install: copy the ZIP into `%LOCALAPPDATA%\BeamNG\BeamNG.drive\current\mods` (Windows) and
pick the level in Freeroam. To update, replace the ZIP with the same name and remove
`current\temp\levels\<level_id>` if the game shows the old version. Earlier builds were checked
in BeamNG.drive 0.39.x. This version's synthetic ZIP passed a runtime smoke check for loading,
surface contact and traffic; real-map acceptance remains separate. The ZIP contains no BeamNG game files; stock trees, props and textures are referenced
by path, and every own resource is prefixed with the level ID.

### Keeping World Editor changes

```bash
earth2road capture --target beamng --level "%LOCALAPPDATA%\BeamNG\BeamNG.drive\current\levels\<level_id>" \
                    --export out/my_area_beamng --output my_edits.json
earth2road export --target beamng --world out/my_area_v2 --output out/my_area_beamng_v2 --overrides my_edits.json
```

Only scene objects are captured (not edited meshes, terrain or signals). If an edited object
changed in the new build, the export stops and names the conflicts instead of guessing.

## Godot export

```bash
earth2road export  --target godot --world out/my_area --output out/my_area_godot
earth2road install --target godot --export out/my_area_godot --root . [--replace] [--activate]
```

Install never overwrites an installed map unless `--replace` (the old copy goes to
`.cache/replaced/`) and changes the active map only with `--activate`. Traffic uses SUMO
(`pip install ".[traffic]"`). Game controls and legacy commands: [GAME.md](GAME.md).

## Events for GUIs and scripts

Add `--events FILE` (or `--events -` for stdout) to any command: one JSON object per line —
`stage` (with monotonic `progress` 0…1), `error` (`code`, `message`) and a final `result`.
Informational records may appear in between: `download` (`url`, and for Overpass a
browser-openable `query_url`) and `warning` (`message`, e.g. a busy server and the next mirror).
Human-readable log goes to stderr.
