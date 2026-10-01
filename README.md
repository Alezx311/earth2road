# TerraDrive — map generator (public beta, in progress)

[Українська версія](README.uk.md)

Turns an OpenStreetMap area into a reproducible, engine-neutral **world package** and exports
it to **BeamNG.drive** (a level ZIP) and to the bundled **Godot** driving game.

> **Status:** experimental public beta. This repository contains the generator, Godot game,
> tests and a synthetic offline example. Real-world maps and downloaded assets are generated
> separately and are not part of Git. Map-specific runtime acceptance is separate from the
> automated source checks; see [validation](docs/VALIDATION.md).

Road layout and buildings come from OSM. Heights, signal timings, traffic demand and street
dressing are derived or synthetic, never measured data — every record says which.

## Play in two commands

You need Python 3.11+ (3.14 is validated), `curl` and internet for the first setup.

**Windows, no terminal:** download the repository (Code → Download ZIP), unpack it and
double-click **`TerraDrive.cmd`**. The first run installs everything (it offers to install
Python with winget if it is missing); later runs start the game straight away.

Or from a terminal:

```powershell
.\setup.ps1      # Linux/macOS: ./setup.sh
.\start.ps1      # Linux/macOS: ./start.sh
```

`setup` downloads Godot 4.6, the Python dependencies and the car models, and installs a small
offline example map. `start` launches the game with traffic.

To drive your own place, press **M → New map from any place on Earth…** in the game: find a
place on the map or paste `lat, lon`, pick the area size (0.3–5 km) and press **Generate**.
The game downloads OpenStreetMap data, builds the map and loads it. Controls and details:
[docs/GAME.md](docs/GAME.md).

To export a map to BeamNG.drive, open **Maps (M)** and click **Export to BeamNG…** beside
the map. Choose a folder and click **Export ZIP**. The window shows the current stage and
supports cancellation; when done, use **Open folder** or **Copy ZIP path**. Each export
gets a new subfolder, preserving earlier ZIPs. Install the ZIP manually in BeamNG's mods
folder. Pick an **Optimization** mode (each has a note in the window; **A+B+C** is meant for
maps of several kilometres, **Original** is the reference). The game remembers your output
folder and mode; BeamNG does not need to be installed to export.

Everything below is for the command line: scripted builds, exports and development.

## Install (generator)

Use Python 3.14 for the pinned setup below. The generator supports Python 3.11+ with
unpinned compatible dependencies. Windows is locally validated; Linux has a CI job.

```bash
python -m pip install -c requirements.lock ".[generator]"               # from a checkout; not published on PyPI yet
terra-drive doctor                        # checks numpy, shapely, pyproj, osmium, SUMO netconvert
```

`setup.ps1` / `setup.sh` (and `TerraDrive.cmd`) install the CLI into the local `.venv`, not onto
`PATH`, so a plain `terra-drive` is "not found" there. Use `.\.venv\Scripts\terra-drive`
(Linux/macOS: `.venv/bin/terra-drive`), activate the venv first (`.\.venv\Scripts\Activate.ps1`,
`source .venv/bin/activate`), or run `python -m akadem_maps` with the venv's Python.

Players of an exported BeamNG map need only BeamNG.drive — no Python.

## Quick start — fully offline example

```bash
terra-drive build  --config examples/tiny/config.json --inputs examples/tiny/inputs --offline --output out/world
terra-drive validate --target world  --input out/world
terra-drive export --target beamng --world out/world --output out/beamng
terra-drive validate --target beamng --input out/beamng
terra-drive export --target godot  --world out/world --output out/godot --offline
```

`examples/tiny` is a synthetic 3×3 street grid with a flat DEM (MIT); it is not OSM data.

## Your own area (bbox)

```bash
terra-drive build --bbox WEST SOUTH EAST NORTH --id my_area --name "My area" --output out/my_area
```

- Coordinates in degrees; `west < east`, `south < north`. The antimeridian is not supported.
- Downloads OSM (Overpass) and Mapzen terrain tiles; `--cache DIR` reuses raw inputs.
- `--region-profile ukraine` is the verified profile; any other area builds as
  `experimental` (no posted road signs, stock licence plates, "experimental region" in the title).
- Keep areas modest: a few km² builds in minutes; an ~80 km² area took about 36 minutes.
- For the Godot game, `tools/generate_map.py --lat LAT --lon LON --size-km 1.5` (or M → New map
  in the game) runs build, export and install in one step; see [docs/GAME.md](docs/GAME.md).
- Clear errors for an invalid bbox, an empty road network, no usable spawn road, a failed
  download and missing or tampered offline inputs.

Every build writes to a **new** directory, which appears only when the build succeeded
(cancel = Ctrl+C or SIGTERM, exit code 130, nothing published). Build again from the
recorded inputs with `--inputs <world>/inputs --offline` for identical network and tiles.

## BeamNG export

```bash
terra-drive export --target beamng --world out/my_area --output out/my_area_beamng [--level-id my_level]
```

`--world` is a world folder: the `--output` of `terra-drive build`, or `out/generated/<id>` for a
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
terra-drive capture --target beamng --level "%LOCALAPPDATA%\BeamNG\BeamNG.drive\current\levels\<level_id>" \
                    --export out/my_area_beamng --output my_edits.json
terra-drive export --target beamng --world out/my_area_v2 --output out/my_area_beamng_v2 --overrides my_edits.json
```

Only scene objects are captured (not edited meshes, terrain or signals). If an edited object
changed in the new build, the export stops and names the conflicts instead of guessing.

## Godot export

```bash
terra-drive export  --target godot --world out/my_area --output out/my_area_godot
terra-drive install --target godot --export out/my_area_godot --root . [--replace] [--activate]
```

Install never overwrites an installed map unless `--replace` (the old copy goes to
`.cache/replaced/`) and changes the active map only with `--activate`. Traffic uses SUMO
(`pip install ".[traffic]"`). Game controls and legacy commands: [docs/GAME.md](docs/GAME.md).

## Events for GUIs and scripts

Add `--events FILE` (or `--events -` for stdout) to any command: one JSON object per line —
`stage` (with monotonic `progress` 0…1), `error` (`code`, `message`) and a final `result`.
Informational records may appear in between: `download` (`url`, and for Overpass a
browser-openable `query_url`) and `warning` (`message`, e.g. a busy server and the next mirror).
Human-readable log goes to stderr.

## Limitations

- Heights are approximate (coarse DEM, assumed bridge and ramp heights).
- Signal timings are netconvert defaults; traffic demand is synthetic.
- Building enrichment (Overture/Microsoft) is optional and off for the Kyiv maps.
- Linux and macOS are not tested platforms for this beta (macOS: `setup.sh`, `start.sh`, unit
  tests and the headless drive check were run once on Apple Silicon).

## Reporting a bug

Open an issue with: the command line, the `--events` JSONL file, `terra-drive doctor` output,
OS and BeamNG version, and for map problems the level ID, coordinates or screenshot. Do not
attach downloaded OSM extracts larger than a few MB — the world's `inputs/manifest.json` hashes
are enough to identify them.

## Licenses

Code and generated artwork: MIT ([LICENSE](LICENSE)). Map data keeps its own terms:
© OpenStreetMap contributors, ODbL 1.0 — MIT does not apply to it. Details:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [docs/SOURCES.md](docs/SOURCES.md),
world format: [docs/WORLD_FORMAT.md](docs/WORLD_FORMAT.md).

## Development

The distribution and CLI are `terra-drive`; `akadem-maps`, the `akadem_maps` Python API,
`AKADEM_*` environment variables and existing map IDs remain compatible.
See [CONTRIBUTING](CONTRIBUTING.md), [game setup](docs/GAME.md),
[validation results](docs/VALIDATION.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
