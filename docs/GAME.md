# Earth2Road Godot game

Godot 4.6 with Jolt provides the vehicle physics. Python/SUMO supplies synthetic traffic.
Windows is the locally validated platform; Linux has a CI job but was not run locally.

## Fresh checkout (Windows PowerShell)

```powershell
.\setup.ps1
.\start.ps1 --map tiny
```

Requirements: Python 3.11+ on PATH (3.14 is pinned and validated), `curl`, and internet for
the first setup. Setup downloads Godot 4.6, Python dependencies and licensed assets. When no
map is installed yet, it also builds and activates the offline example map `tiny` (a synthetic
grid from `examples/tiny`). The same steps by hand:

```powershell
.\.venv\Scripts\earth2road.exe build --config examples/tiny/config.json --inputs examples/tiny/inputs --offline --output out/tiny-world
.\.venv\Scripts\earth2road.exe export --target godot --world out/tiny-world --output out/tiny-godot --offline
.\.venv\Scripts\earth2road.exe install --target godot --export out/tiny-godot --root . --activate
```

`out/` destinations must not already exist; use a new name for another build.
Linux: `./setup.sh`, `.venv/bin/earth2road` and `./start.sh --map tiny`.

For a real area, use a config from `config/` or `earth2road build --bbox ...` as in [CLI.md](CLI.md),
or generate one around any point on Earth:

- In the game: M → **New map from any place on Earth…**. Drag or zoom the OpenStreetMap view,
  search for a place, or paste `lat, lon`. Then pick the area size (0.3–5 km) and press
  **Generate**. The game shows progress and loads the map when it is ready.
- From the shell: `.\start.ps1 --generate 49.8419 24.0316 --size 1.5 --name "Lviv centre"`
  (Linux: `./start.sh --generate ...`), or `tools/generate_map.py` directly.

The **Map data** controls offer Auto/Offline modes, saved territories, local PBF
selection, separate OSM/terrain readiness and **Prepare area offline**. Preparation
does not install a map. **Find regional package** shows a Geofabrik package and its
size; downloading is a separate button press. **Import local PBF…** asks for the
coverage guaranteed by its provider. Refresh preserves the previous snapshot.
Offline mode disables online search and background-tile requests; coordinates and
saved areas remain usable. See [CLI](CLI.md) for equivalent commands and cache rules.

Generation reuses verified snapshots and local packages before Overpass, and caches terrain tiles. A 0.6 km
square took about 40 s; larger areas take minutes. Areas outside Ukraine build as
`experimental`, without posted road signs. The progress log is `logs/generate.log`.
Generation may require network access, several GB of memory and tens of minutes.
Install maps one at a time; use `--replace` only when deliberately replacing a map.
`--activate` selects the initial map, and M opens the map menu in-game.

## Controls

WASD/arrows drive; Space handbrake; C camera; V vehicle; R reset; P/Esc pause;
F1 help; F spectator; F5 traffic reconnect; F12 screenshot; M map menu; L language.
Hold the right mouse button and move the mouse to look around the car; in the cockpit (C)
this turns the head. The mouse wheel sets the chase camera distance. The view returns
behind the car shortly after the button is released.

The UI is in English by default. L, or the language button in the map menu, switches to
Ukrainian, and the choice is remembered. The game connects to the traffic bridge by itself
and reconnects if the bridge restarts. The car drives with or without traffic. On first launch `start.ps1`/`start.sh` import the
Godot project once; this builds `game/.godot`, which the vehicle addon's classes need.
Spectator: WASD moves, Q/E or wheel changes height, right mouse looks, Shift accelerates.
Density and time controls are available in the panel. High densities may reduce simulation speed.

Vehicle models are downloaded from Kenney (a procedural stand-in is used until they are
fetched); optional ambientCG textures and Poly Haven props have procedural fallbacks. See THIRD_PARTY_NOTICES and config manifests for attribution.
For a missing car pack, run `.venv/Scripts/python.exe tools/fetch_assets.py` before playing.

## Runtime checks

```powershell
$env:AKADEM_MAP = 'akadem'  # a built and installed real map
.\tools\check_surface.ps1
.\tools\check_drive.ps1
.\.venv\Scripts\python.exe tools/validate_traffic.py
.\.venv\Scripts\python.exe tools/validate_traffic.py --incidents
.\.venv\Scripts\python.exe tools/validate_priority.py
```

These map acceptance checks have real-network expectations; they are not interchangeable
with the tiny fixture. Generated reports live in ignored `logs/`.

## Build-up timelapse (presentation video)

`--timelapse` records how a map is assembled: terrain, land cover, the SUMO lane network,
road surfaces, markings, sidewalks, buildings, dressing, signals and traffic appear as a wave
from the centre, then the camera drops to a junction, flies down a street and climbs out.
Frames go to a fresh directory per run under `logs/timelapse/` (15 fps). Existing
captures are never deleted. Start the traffic bridge first:

```powershell
$env:AKADEM_MAP = 'manhattan'
.\.venv\Scripts\python.exe tools\traffic.py            # separate window
.\.tools\Godot_v4.6-stable_win64_console.exe --path game --resolution 1280x720 -- --timelapse --density=2500 `
    --timelapse-near=-100,-250 --timelapse-fly=-306,-31,-19,-557 --timelapse-output=res://../logs/timelapse/my-take
ffmpeg -framerate 15 -i logs/timelapse/my-take/frame_%04d.jpg -c:v libx264 -pix_fmt yuv420p -crf 20 timelapse.mp4
```

Options (local map metres): `--timelapse-near=X,Z` centre, `--timelapse-fly=X1,Z1,X2,Z2[,…]`
street-level flight path (keep it on the street axis; more points follow a curved street),
`--timelapse-cars=N` cars in the simulation before recording starts (large maps fill slowly),
`--timelapse-title=TEXT`, `--timelapse-outro=TEXT`, `--timelapse-output=PATH` (fresh directory),
`--timelapse-overlay=false` (clean frames for editing). Use an absolute output path or
`res://../logs/timelapse/my-take` for a path relative to the project.
This is an animated reveal of an already generated map, not a recording of generator
execution time. The game itself is unchanged without `--timelapse`.
