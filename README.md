# Earth2Road — drive your own city (public beta)

[Українська версія](README.uk.md)

Pick any place on the map, and Earth2Road turns its OpenStreetMap data into a drivable
map: roads, junctions, markings, sidewalks, buildings, signs, traffic lights and traffic.
Drive it in the bundled **Godot** game or export it as a mod ZIP for **BeamNG.drive**.

> **Status:** experimental public beta. Road layout and buildings come from OSM; heights,
> signal timings, traffic and street dressing are derived or synthetic, not measured.
> See [known limitations](#limitations) and [validation results](docs/VALIDATION.md).

Formerly TerraDrive: existing maps, settings and `TerraDrive.cmd` keep working.

## Start (Windows)

1. Download the repository: **Code → Download ZIP**, and unpack it.
2. Double-click **`Earth2Road.cmd`**.

The first run installs everything into the folder itself: Godot 4.6, Python packages,
car models and a small example map (several hundred MB download, about 1.2 GB on disk,
a few minutes). If Python 3.11+ is missing, it offers to install it with winget.
Later runs open the game straight away.

Linux/macOS (not tested platforms for this beta): `./setup.sh` once, then `./start.sh`.

## Make a map of your place

1. In the game press **M** (or the **Maps · M** button).
2. Click **+ New map from any place on Earth…**.
3. Find the place by search or drag the map, or paste `lat, lon`; choose the area size
   (0.3–5 km).
4. Click **Generate**. The game downloads OpenStreetMap data and terrain, builds the map
   and loads it. A 1 km area takes a few minutes; you can cancel at any time.

Your maps stay in the **Maps** menu; switch between them there. **L** switches the
interface between English and Ukrainian.

Controls: WASD/arrows drive, Space handbrake, C camera, R reset, P/Esc pause, F spectator,
F1 help. More in [docs/GAME.md](docs/GAME.md).

## Export to BeamNG.drive

1. Open **Maps (M)** and click **Export to BeamNG…** next to the map.
2. Choose the folder (**Browse…**) and an **Optimization** mode. Each mode has a note in
   the window; **A+B+C** is for maps of several kilometres, **Original** is the reference.
3. Click **Export ZIP**. The window shows progress and can cancel; at the end use
   **Open folder** or **Copy ZIP path**. Every export gets a new subfolder, so earlier
   ZIPs are kept.

BeamNG does not have to be installed to export, and players of an exported map need only
BeamNG.drive.

**Install in BeamNG:** copy the ZIP, without unpacking, into the `mods` folder of your
BeamNG user folder (launcher → Manage User Folder → Open in Explorer; by default
`%LOCALAPPDATA%\BeamNG\BeamNG.drive\current\mods`). Start the game and pick the map in
Freeroam. To update a map, replace the ZIP with the same name; if the game still shows the
old one, delete `current\temp\levels\<level_id>`. Do not keep two versions of the same
map enabled. The ZIP contains no BeamNG game files: stock trees, props and textures are
referenced from your copy of the game.

## Update

Download the new version and run `Earth2Road.cmd` again. If you update an existing folder
in place (for example with `git pull`), run `setup.ps1` once (right-click → Run with
PowerShell) so the packages are refreshed.

## Limitations

- Map quality follows OSM: missing or wrong tags give missing or wrong roads and buildings.
- Heights are approximate (coarse terrain, assumed bridge and ramp heights).
- Signal timings are generator defaults; traffic is synthetic (SUMO in the Godot game,
  BeamNG's own AI in BeamNG).
- The Ukrainian region profile is the verified one; other countries build as
  *experimental* (no posted road signs, generic licence plates).
- Large areas need a lot of RAM and video memory, especially in BeamNG.
- Windows is the validated platform.

## Reporting a bug

Open an issue with the city, the place (coordinates or a screenshot), what you expected,
your OS and BeamNG version and PC specs. Logs are in the `logs` folder. Please do not attach
large downloaded map data.

## Licenses

Code and generated artwork: MIT ([LICENSE](LICENSE)). Map data keeps its own terms:
© OpenStreetMap contributors, ODbL 1.0 — MIT does not apply to it. Details:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [docs/SOURCES.md](docs/SOURCES.md),
world format: [docs/WORLD_FORMAT.md](docs/WORLD_FORMAT.md).

## Development

The distribution and CLI are `earth2road`; `terra-drive` and `akadem-maps` aliases, the `akadem_maps` Python API,
`AKADEM_*` environment variables and existing map IDs remain compatible.
Command line: [docs/CLI.md](docs/CLI.md). See [CONTRIBUTING](CONTRIBUTING.md), [game details](docs/GAME.md),
[validation results](docs/VALIDATION.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
