# Local Visual DNA v0

An opt-in experiment in neighbourhood appearance. The Podil profiles are manually
authored hypotheses, not image analysis or verified reconstructions. OSM footprints,
tagged heights and levels remain unchanged. No photographs or third-party assets
are downloaded by this feature.

## Build the A/B pilot

```powershell
.venv/Scripts/python.exe -m akadem_maps build --config config/podil_dna_baseline.json --cache out/local-dna/inputs --output out/local-dna/baseline
.venv/Scripts/python.exe -m akadem_maps build --config config/podil_dna.json --cache out/local-dna/inputs --output out/local-dna/styled
.venv/Scripts/python.exe -m akadem_maps export --target beamng --world out/local-dna/baseline --output out/local-dna/baseline-beamng --optimization compact
.venv/Scripts/python.exe -m akadem_maps export --target beamng --world out/local-dna/styled --output out/local-dna/styled-beamng --optimization compact
.venv/Scripts/python.exe tools/local_dna_compare.py out/local-dna/baseline out/local-dna/styled --output out/local-dna/comparison --capture out/local-dna/baseline-beamng out/local-dna/styled-beamng
```

Use fresh output directories. Both configs share a 2000 m square around Kontraktova
Square and seed 311. Use the same verified source snapshot and DEM for both builds;
`--offline` works after those sources have been prepared. The optional `--capture`
starts BeamNG on Windows with separate disposable profiles; it does not install or
activate either map in the normal profile. Without it, the comparison is engine-free.

The comparison checks network, road geometry, spawn, signals, footprints and known
heights before producing `comparison.json`, eight shared cameras and `influence.png`.
The influence image shows relative profile weights; coverage strength fades toward
the default generator at the outer edge. Screenshots assess the hypothesis; passing
structural checks does not establish recognisability or certify road driveability.

## Configuration and world interface

Add `"local_visual_dna": {"file": "config/visuals/podil_dna.json"}` to a map config.
Paths use the existing config-root convention. The profile file is copied and hashed
in the world's input bundle, so offline replay does not depend on later edits.

Version 1 profile files contain `profiles` and `anchors`. Every profile has weighted
`architecture`, `materials`, `colors`, `floors`, `roofs` dictionaries, a
`vegetation_density` multiplier (0–3), and `provenance`. Weights need not sum to one.
Architecture families: `historic`, `brick`, `panel`, `modern`, `industrial`.
Roof choices: `flat`, `gabled`. Colours are six-digit hex or the named palette in
`core/local_dna.py`. Each anchor has `id`, `lon`, `lat`, `radius_m`, `profile`, and
`provenance`. The pilot contains 25 anchors on a 400 m grid with 750 m radii.

Influence uses the compact kernel `(1 - (distance/radius)^2)^2` inside each radius.
Distributions blend with normalized weights. Total kernel mass capped at one is the
coverage strength: it blends vegetation toward the legacy density and smoothly
changes the probability that a building receives DNA. SHA-256(seed, OSM ID, property)
makes choices independent of building order and tile size. Missing coverage keeps
the old building behavior. Rural mode and DNA are mutually exclusive in v0.

Buildings gain optional `local_style` with architecture, material, colour, requested
roof, per-property provenance and influencing anchor IDs/weights. Existing roof
triangle fields carry actual geometry. Unsupported roofs/outlines and raised
passages use a flat fallback with an explicit reason; gabled roofs use the original
footprint and keep total height. Unknown tagged colours remain recorded with an
unsupported marker and neutral render fallback. Ordinary floors are inferred only
when both OSM height and levels are absent. Height-only buildings derive a floor
count for rendering. Industrial OSM uses constrain the synthetic family.

World v2 remains version 2. The index gains `local_visual_dna` with profiles, anchors,
counts and landmark discovery. Tiles retain the existing `trees` position array
and optionally add `tree_records` with per-tree provenance. Old consumers can ignore
these additions. BeamNG uses shared procedural textures and existing spatial batches;
Godot uses shader materials and the same roof geometry. Detailed Godot window props
are suppressed for DNA buildings in this minimal grammar.

## Landmarks and sources

Landmarks come from selected OSM categories on nodes, ways and relations, with member
node means as representative points. Category, name and Wikipedia/Wikidata tags
produce a heuristic importance score, not a measured popularity score. Matching
Wikidata IDs and nearby equal names deduplicate representations. Up to `landmark_limit`
(in `local_visual_dna`, default 5) named landmarks separated by 200 m are selected;
a landmark spawn within 150 m of a config anchor or OSM POI is skipped. Road snapping uses existing POI rules;
unsnappable landmarks stay in the report. Visual anchors never become spawns, and
landmark importance does not imply a neighbourhood style.

PBF and Overpass share landmark tag selection. Snapshot selection is now v3, so old
v2 snapshots cannot claim complete landmark coverage. Existing explicit legacy
inputs remain readable; an explicitly selected stamped v2 snapshot is rejected for
DNA builds. Re-extract from an original PBF or fetch a new source for the pilot.

No CV, 3D landmark reconstruction, new street props, parked cars or road-graph
influence is included in v0. Building multipolygon rendering retains the generator's
existing closed-way limitation; landmark relation discovery does not fix that.
