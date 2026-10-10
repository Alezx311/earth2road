# Godot streaming feasibility prototype

The target is full current nearby geometry, SUMO behaviour and control within 30 s
of selecting an uncached point. BeamNG remains an export of a selected area.
This prototype measures the three prerequisites. It does **not** add a Free Drive
menu, a moving world generator or claim a successful 20-minute streaming drive.

## Reproduce

Run from the repository root with the generator/traffic dependencies and Godot 4.6.
All output directories must be new. Installed maps and the active map are untouched.
The real suite contains manually selected city, suburb and rural points, each at
500, 1,000 and 2,000 m. These are representative experiments, not global coverage.

```powershell
.venv/Scripts/python.exe tools/streaming_probe.py benchmark --suite config/streaming_tiny.json --output out/streaming/tiny --modes source geometry --godot .tools/Godot_v4.6-stable_win64_console.exe
.venv/Scripts/python.exe tools/streaming_probe.py benchmark --suite config/streaming_matrix.json --output out/streaming/cold --modes cold --timeout 40 --godot .tools/Godot_v4.6-stable_win64_console.exe
.venv/Scripts/python.exe tools/streaming_probe.py benchmark --suite config/streaming_matrix.json --output out/streaming/source --modes source geometry --source-run out/streaming/cold --timeout 40 --godot .tools/Godot_v4.6-stable_win64_console.exe
.venv/Scripts/python.exe tools/streaming_surface_lab.py --output out/streaming/seams
.venv/Scripts/python.exe tools/streaming_traffic_lab.py --output logs/streaming/traffic
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Use `--only city_500` and a larger `--timeout` for a completed profile after the
30 s budget has failed. `--geometry-run out/streaming/source --modes geometry`
reuses a **completed** source run. `--source-cache PATH` uses an existing verified
source cache in offline mode. An unavailable source is a failed measurement,
not a warm-cache performance result. Do not repeatedly retry an HTTP 429.
`matrix --output NEW_FILE` reproduces the suite using geodesic metric extents.

A cold timeout can leave incomplete DEM coverage. Before a full source-only
profile, use the existing `earth2road data prepare --bbox W S E N --cache PATH`
command (or provide a complete input bundle). This preparation has its own log
and is not counted as uncached startup. A source-mode timeout does not establish
that later lazy DEM reads would have succeeded.

## What the reports measure

Each case has `job.json`, line-flushed `events.jsonl`, `worker.log`, `result.json`
and, when reached, `godot.log`. The suite report records revision, dirty checkout,
suite digest, platform, CPU, Python and the timeout. Exported worlds retain the
normal input hashes/tool versions/provenance. Files stay under ignored output roots.

- `cold`: a new empty source cache per point/size; OSM and DEM acquisition included.
- `source`: rebuild full v2 geometry offline using the same source snapshot/cache.
- `geometry`: validate the completed world and reuse its Godot export and demand.
  This is a ready-world load measurement, not fresh geometry production.
- Exclusive intervals distinguish source acquisition, terrain, netconvert network,
  road geometry, road meshes, ground, buildings, tiling, audit, provenance, Godot
  export/demand, SUMO process/warm-up and Godot process/start. DEM downloads are
  also timestamped events; DEM may be loaded on demand during later geometry stages.
- Godot builds the existing start radius with full meshes and collisions, waits
  for physics and probes the spawn surface. Its nested metrics separate mesh build
  and collision construction. No map installation or player input is required.
- SUMO loads the exported routes in a separate process, inserts up to 100 synthetic
  vehicles and warms for 3 simulated seconds. Counts, pending vehicles, collisions
  and teleports are recorded. This does not verify the live game bridge protocol,
  its demand catalogue or actual player control. Headless Godot does not measure FPS.

Timeouts are censored observations: `>40 s`, never “build time = 40 s”. Completed
stage intervals and the last stage are preserved. The supervisor terminates only
its worker process tree. A terminated atomic build may leave its ignored staging
directory; do not use that directory as a completed world.

`pipeline_within_30s` requires traffic, a supported spawn and total wall time
including the worker process. It is a necessary lower-level check, not acceptance
of the whole experience. Start-to-control, a 20-minute drive, memory/queue bounds,
production keeping up at 90 km/h and stopping at an offline boundary remain
`not_tested`. No report turns `streaming_release` on automatically.

## Surface experiment

The synthetic MIT lab builds a whole map and west/east windows with overlap, then
repeats in reverse order. It includes straight roads, intersections, an analytic
sloping DEM and a separately tagged bridge over a ground road. Same-window network,
index and tile hashes check order independence. Lane-centre and wheel-track probes
compare each window and their overlap against the whole map.

The standalone comparator also accepts existing engine-neutral world directories:

```powershell
.venv/Scripts/python.exe tools/streaming_probe.py seams --reference out/whole --candidate out/west --bbox 30.3545 50.449 30.3575 50.459 --output logs/streaming/seams.json
```

Queries convert through each SUMO projection/offset and add its `base_height`.
Topology and structure levels restrict matches; a ground road cannot stand in for
the bridge above it. Missing reference surfaces, missing candidate surfaces,
unmatched topology, differences over 5 cm and an empty sample set fail explicitly.
This is a geometric comparison, not a driven collision test. The 5 cm diagnostic
tolerance is an engineering test choice, not a surveyed accuracy claim.

## Traffic experiment

`akadem_maps.traffic_handoff.transfer` uses two explicit TraCI connections. The
target network has a different outside branch but identical overlap lanes. Tests
transfer a red-light queue (including its later restart), a vehicle on an internal
junction lane and a stopped player proxy with a braking follower. Both processes
continue for 10 simulated seconds; IDs, positions, lane/speed at handoff, signals,
collisions and teleports are checked.

Preflight requires equal clocks, an empty destination, matching vehicle types,
remaining routes, lane shapes/lengths and traffic-light controlled-link ordering.
Only fixed-time signal programs and vehicles without scheduled stops or lateral
manoeuvres are supported. The source is never mutated. If import or verification
fails, discard the shadow process and retain the source; never switch to a partial
destination. The lab's deterministic drivers have zero imperfection.

This is not a universal state serializer: hidden driver RNG, accumulated waiting
time, in-progress lane-change state, dynamic situations and bridge-side caches are
not transferred. Rebuilt OSM windows may change edge/junction IDs and TLS grouping;
these are rejected. A stable geographic identity/route-extension layer is still
required before integrating this with `tools/traffic.py` or its libsumo backend.
The prototype follows the installed TraCI API and the upstream
[vehicle-state](https://eclipse.dev/sumo/docs/TraCI/Change_Vehicle_State.html) and
[traffic-light](https://eclipse.dev/sumo/docs/TraCI/Traffic_Lights_Value_Retrieval.html)
contracts; documented setters alone do not establish seamless continuation.

## Decision gate

Keep the production generators, exporters and menu behaviour. If acquisition,
geometry or handoff fails the budget/continuity checks, record that bottleneck
before building the long-lived service, moving traffic window, bounded tile
residency, geographic origin rebasing and offline boundary guard. Do not reduce
quality or replace SUMO with simpler traffic to make this test pass. Antimeridian
crossing, unsupported latitudes and places without passenger roads are explicit
errors; no synthetic roads are substituted into real-map cases.

Measured results and exact verification commands are recorded in HANDOFF.
