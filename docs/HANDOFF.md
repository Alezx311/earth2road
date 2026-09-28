# TerraDrive handoff

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
