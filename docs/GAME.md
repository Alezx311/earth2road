# TerraDrive Godot game

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
.\.venv\Scripts\terra-drive.exe build --config examples/tiny/config.json --inputs examples/tiny/inputs --offline --output out/tiny-world
.\.venv\Scripts\terra-drive.exe export --target godot --world out/tiny-world --output out/tiny-godot --offline
.\.venv\Scripts\terra-drive.exe install --target godot --export out/tiny-godot --root . --activate
```

`out/` destinations must not already exist; use a new name for another build.
Linux: `./setup.sh`, `.venv/bin/terra-drive` and `./start.sh --map tiny`.

For a real area, use a config from `config/` or `terra-drive build --bbox ...` as in the README,
or generate one around any point on Earth:

- In the game: M → **New map from any place on Earth…**. Drag or zoom the OpenStreetMap view,
  search for a place, or paste `lat, lon`. Then pick the area size (0.3–5 km) and press
  **Generate**. The game shows progress and loads the map when it is ready.
- From the shell: `.\start.ps1 --generate 49.8419 24.0316 --size 1.5 --name "Lviv centre"`
  (Linux: `./start.sh --generate ...`), or `tools/generate_map.py` directly.

Generation downloads OSM data (Overpass, with mirror fallback) and terrain tiles. A 0.6 km
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

Vehicle models are downloaded from Kenney; optional ambientCG textures and Poly Haven props
have procedural fallbacks. See THIRD_PARTY_NOTICES and config manifests for attribution.
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
