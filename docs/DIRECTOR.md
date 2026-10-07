# Earth2Road director

Portable instructions for any AI agent creating Earth2Road scenarios and footage.
Read this first; read [capture mechanics](BEAMNG_ASSEMBLY.md) only when producing
footage. Scripts require the local project environment and a licensed BeamNG
installation; instructions alone do not supply those capabilities.

## What the project means

Earth2Road turns real geographic data into explorable driving maps. A Python
generator creates one engine-neutral world, used by the project's Godot game and
its BeamNG.drive exporter. OpenStreetMap provides road layouts and mapped features;
terrain comes from DEM data. Facades, missing heights, road engineering, traffic
and default signals can be procedural assumptions. This is not photogrammetry.

The current visual strengths are **scale, recognizable geography and the variety
of places that can become a map**. Fine detail is limited. Sell the sweep of an
avenue, street network, coastline, relief and city blocks. A drive is an optional
way to establish size, not the obligatory subject of every clip. Use real captures;
do not invent landmarks, paint missing geometry into frames, or promise identical
facades. Other countries currently use the experimental region profile.

## Editorial rules

- Default to clean footage: no captions, labels, watermarks, logo cards, explanatory
  voiceover or added music. Explain only on explicit request. Keep attribution and
  necessary context in the accompanying post; choose sources compatible with this.
- Start with a recognizable composition or visible transformation. End on a larger
  view that earns its screen time. Keep the subject legible on a phone.
- Do not force every clip into one template. Useful formats include real photo →
  game, roads → blocks → district, a familiar junction → its wider network, and
  several places linked by one geographic idea.
- Write public copy in the target audience's language (US pilot: English). Keep
  scripts and operational notes in whichever language the operator requests.
- An assembly animation replays an already generated map. Call it an **assembly
  visualization**, not actual generation time or physical construction. Record real
  generation timing separately. Never infer gameplay quality from a capture.
- Do not claim "any place works" from one example. A new-location pilot must start
  from new geographic inputs; record what failed as well as what rendered.
- Scenario creation, rendering and publication are separate tasks. A script or a
  completed MP4 is not permission to publish, contact anyone or connect accounts.

## Deliver a shot recipe

Use [scenario template](DIRECTOR_SCENARIO.md). Each recipe must be executable:
identify the world and exact export; say what is visible, when it appears, where
the camera is, and what the viewer should recognize. Store scene JSON alongside
the human-readable script. Reuse existing CLI tools rather than writing one-off
engine automation for every city.

Drafts and generated media live in ignored `posts/<date>-<location>/`: script,
reference and provenance, build config/logs, scene JSON, probe screenshots, final
video, post copy, and QA record. Never commit downloaded photos, maps or credentials.
Fresh output folders preserve previous attempts. Only mark a step complete when
there is corresponding evidence.

## Find and match a photo

1. Find a high, broad, perspective view with at least four shared geographic
   anchors. Favor street intersections, waterfront turns and large building masses
   over facade details. Inspect the actual image and map coverage before choosing.
2. Save the original source page, creator, image date, usage terms, retrieval date,
   download URL and file hash. Do not confuse a page's metadata license with the
   photograph's license. Resolve reuse before including the photo in the video.
   A usable reference can remain reference-only if its publication rights differ.
3. Read EXIF where available. GPS may identify the subject rather than the camera;
   verify against the visible geometry. Record altitude datum uncertainty and
   whether a focal length is original or 35 mm equivalent. Crops change framing.
4. Convert lon/lat with the **world's network projection and offsets**, then use
   BeamNG X east, Y north, Z up including the export's vertical offset. Do not
   guess a universal metres-per-degree transform or reuse another map's offsets.
5. Store normalized anchor positions in the chosen photo crop and identify the
   corresponding map features. Estimate pose/FOV, capture a static probe, compare
   anchors, then correct. Limit to three rounds per reference; archive/reject a
   poor match rather than hiding it with image warping.
6. Judge the first game frame against the same photo crop. Approximate composition
   is acceptable; claim exact registration only if measured. Do not stretch,
   mirror, perspective-warp or synthesize either scene to manufacture similarity.
7. Keep the camera still during the matched section. Begin the reveal after the
   assembly resolves. Check the entire path for clipped roofs, terrain penetration,
   missing tiles, map edges and abrupt speed changes.

## Execute and review

- Typical pilot: 1080×1920, 30 fps, 20–25 seconds; 2 seconds of photo followed by
  assembly and a smooth retreat. Adapt timings to the subject, not the reverse.
- Build and export with the checkout's code: `.venv/Scripts/python.exe -m akadem_maps
  build|export` from the repository root. `earth2road.exe` runs whatever wheel is
  installed in the venv, which can predate current features (Detroit world-02 came
  from a 02.10 wheel without multipolygon water: the Detroit River rendered as dirt).
- Fit the pose instead of guessing it: with the EXIF position as a soft prior, solve
  yaw/pitch/vertical FOV/position from ≥4 anchors and drop an anchor only with a
  stated reason. BeamNG `fov` is vertical; a full-height portrait crop keeps the
  photo's vertical FOV and only turns yaw to the crop centre.
- Test generator/export changes on 1–2 km maps first and compare stage times between
  sizes (×4 area should cost ~×4); a full 4 km build is 35–60 min. Small maps do not
  exercise every path: `LocalCut` tiles only above 100k vertices, so keep
  `AKADEM_MAPS_TRACEBACK=1 AKADEM_MAPS_GEOS_DUMP=<dir>` on full builds; a geometry
  failure then leaves a traceback and WKB inputs instead of needing another run.
- Probe the engine on the small map too: frame size, FOV and water show up there.
- Run one GPU capture at a time in an isolated profile. Use `--static` and sample
  times for probes, then a fresh full take. For director footage always encode
  with `--clean`; the old encoder intentionally retains historical caption behavior.
- Inspect the first frame, assembly stages and final frame; fully decode the video
  to check count, duration, size and black intervals. Review playback or ordered
  full-length frame sampling for motion. State which form of review actually ran.
- Record matching limitations and omitted/mismatched landmarks. Keep source photo
  date separate from OSM snapshot date; a difference can be real urban change.
- Hand off the MP4 with post text and source credits. Update `docs/HANDOFF.md` with
  exact checks and failures, and improve this guide only from demonstrated lessons.

## Detroit pilot

The first new-area experiment targets a 4 km square of downtown Detroit around
42.337 N, 83.048 W. The hook is "Motor City, rebuilt from map data". Reference:
[Carol M. Highsmith, 2020-02-22, Library of Congress, highsm.63410](https://www.loc.gov/pictures/item/2020742291/).
The source says "No known restrictions on publication"; retain that wording, not
an invented CC license. Its photographed skyline predates the map snapshot.
Local evidence belongs in `posts/2026-10-07-detroit/`. Result (08.10.2026): world-09,
beamng-09, take-10 → a 24.6 s clean 1080×1920 candidate with an approximate (not
measured) photo match; checks and limitations in its `qa.md`. Not published.

Lessons from it: a 4 km city first exposed stage costs and GEOS failures that 1 km maps
did not (see above); a river tunnel drawn from a blurred DEM bed surfaced over the water;
and a wrong assembly stage (ground hidden as a prop) was only visible in mid-assembly
frames — sample the first seconds of a take, not just its first and last frame.
