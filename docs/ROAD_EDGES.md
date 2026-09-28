# Low kerbs and the Beresteiskyi branch

Implementation started 2026-09-25. Source geometry is OSM-derived; heights,
sidewalk profiles, lighting and traffic timing are synthetic.

## Interfaces

- `corridor.axes` accepts named axes with individual `lat_range` or `clip_bbox`.
  Each axis is clipped before its 500 m scenery buffer; buffers are unioned.
  Legacy `corridor.axis` retains its original behaviour.
- `config/ring_beresteiskyi.json` keeps the ring centre and uses the same BeamNG
  `level_id`, with a separate preparation ID so the old snapshot remains available.
  `tools/configure_beresteiskyi.py` reproduces the configuration from the ring.
  Avenue anchors record the dated OSM node IDs used for their coordinates.
- Pedestrian snapshot records carry `structure_level`; missing legacy flags are
  additionally separated by actual height where footprints overlap.
- `Pavement` indexes the exact road triangles and interpolates triangle heights.
  Envelope queries clip triangles to the requested vertical interval.
- `build_sidewalks` unions pedestrian footprints before spatial chunking, clips
  same-grade asphalt, and emits one continuous profile: 35 mm rise, 150 mm lip,
  8 mm bevel. Rounded inward offsets cannot protrude into asphalt. Zebra-marked
  crossings taper to zero; road openings are cut out of pedestrian footprints.
- The asphalt geometry is unchanged by the exporter. This is not a redesign of
  the road elevation generator or an assertion that every old road seam is fixed.

## Placement and user decision

Poles, signs, rails, vegetation and fuel canopies use the shared pavement index.
Failed synthetic placements are omitted and recorded. A mandatory signal post
that cannot fit either shoulder remains an unresolved acceptance issue, rather
than being placed on a lane without collision.

The user explicitly requested **unchanged building footprints** after the audit
found widespread conflicts. These are reported as `deferred` in
`building-conflicts.json`; they are not silently clipped or relocated.
`placement-corrections.json` records derived placements and reasons. Scene editor
overrides continue through the existing `--overrides` / `--capture-edits` flow.

`acceptance_ready` in the export manifest concerns unresolved placements in this
iteration. It does not mean runtime verification or zero deferred building
conflicts. Runtime results remain in the isolated QA profile.

## Reproduction

```powershell
.venv/Scripts/python.exe tools/prepare.py --config config/ring_beresteiskyi.json
.venv/Scripts/python.exe tools/export_beamng.py --map ring_beresteiskyi --output dist/kyiv_ring_beresteiskyi_01
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_beamng*.py'
.venv/Scripts/python.exe -m unittest discover -s tests -p test_ring_corridor.py
```

Preparation produces a separate world. Installation and activation require explicit
`--install` and `--activate` flags; use `--replace` deliberately for an existing map. Export never replaces an existing build folder
or a game-profile mod. Preserve the previous ZIP for rollback.

## Acceptance

Automated fixtures cover curves, tile seams, crossings, slopes, overlapping decks,
actual miter footprints, vertical obstacle envelopes and unchanged buildings.
Use isolated game profiles for screenshots, wheel contact, kerb crossings, spawn
checks, route driving and traffic. Compare identical routes/settings; report
failed or incomplete traffic runs separately from frame-time measurements.
