# Third-party notices

The MIT license in `LICENSE` covers only the original code and procedurally
generated artwork of this repository. Everything below keeps its own terms.
Per-source details, pinned versions and checksums: `docs/SOURCES.md`.

## Map data (never relicensed as MIT)

| Source | License | Notes |
|---|---|---|
| OpenStreetMap | ODbL 1.0 — © OpenStreetMap contributors, https://www.openstreetmap.org/copyright | Road network, buildings, POIs. Worlds and exported maps derived from OSM are Produced Works / Derivative Databases under ODbL; world packages keep the OSM snapshot and SHA-256 in `inputs/`. |
| Mapzen Terrain Tiles | Source-specific attribution: https://github.com/tilezen/joerd/blob/master/docs/attribution.md | DEM; approximate, not survey-grade. |
| Overture Maps buildings (optional) | ODbL 1.0 | Only when `building_enrichment.enabled`. Both beta maps have it disabled. |
| Microsoft Building Footprints (optional) | CDLA-Permissive-2.0 | Only when `building_enrichment.enabled`. |
| Kyiv road works (optional, Godot traffic only) | Not stated by the publisher | Not redistributed in public data packages until the license is confirmed. |
| `examples/tiny` | MIT | Synthetic streets and flat terrain; no OSM or measured data. |

## Generator dependencies (installed by pip, not vendored)

| Package | Version | License |
|---|---|---|
| eclipse-sumo, sumolib, libsumo, traci | 1.27.1 | EPL-2.0 OR GPL-2.0-or-later |
| numpy | 2.x | BSD-3-Clause (bundled parts: 0BSD, MIT, Zlib, CC0-1.0) |
| shapely | 2.1.2 | BSD-3-Clause |
| pyproj | 3.7.2 | MIT |
| Pillow | 12.3.0 | MIT-CMU |
| osmium (pyosmium) | 4.3.1 | BSD-2-Clause |
| requests | 2.x | Apache-2.0 |
| websockets | 15.0.1 | BSD-3-Clause |

## Godot game

| Component | License |
|---|---|
| Godot 4.6 (installed separately) | MIT |
| Godot Easy Vehicle Physics, vendored in `game/addons/gevp/` | MIT (see its LICENSE) |
| Kenney Car Kit 3.1 (downloaded by `tools/fetch_assets.py`, not committed) | CC0 1.0 |
| ambientCG textures (downloaded by `tools/fetch_textures.py`, not committed) | CC0 1.0 |
| Poly Haven props (downloaded by `tools/fetch_visual_assets.py`, not committed) | CC0 1.0; pinned files in `config/visuals/downloads.json` |

## BeamNG.drive

The BeamNG export references stock BeamNG.drive meshes and textures by path.
No BeamNG file is copied into the generated ZIP. BeamNG.drive is required to
play the exported maps and is subject to its own EULA.
