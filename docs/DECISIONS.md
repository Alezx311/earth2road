# Decisions

- Local Visual DNA v0 is opt-in and engine-neutral. Manual district profiles are
  hypotheses, with per-property provenance and OSM taking precedence. Blend profile
  distributions in metric space; seed choices by map seed, OSM ID and property.
  Landmark importance and visual influence are separate. Keep world v2 and legacy
  paths compatible; new geometry remains spatially batched. The first experiment
  covers Podil buildings/greenery and landmark spawns, without imagery/CV or 3D
  reconstruction. See LOCAL_VISUAL_DNA.md for the interface and limitations.

- Typical models by building type (2026-10-08) are derived geometry, used only where
  OSM has no detail: a church/mosque/fuel canopy/shop hall without `building:part`
  items or `roof:shape` gets a recognizable form (nave + drum/onion + bell tower,
  spire, dome + minaret, raised deck on posts, 4.5 m retail storeys). Tagged heights
  and colours always win; every derived record says `typical.provenance`. An untagged
  Christian church is Orthodox in the `ukraine` region profile and Western elsewhere.
  The form is extra building records (S3DB-like parts), so adapters need no new code.
- Courtyard dressing (2026-10-08, owner): parked cars, entrance benches/bins, shrubs along
  apartment walls and playground equipment are synthetic, each anchored to an observed OSM
  feature (surface parking, yard service road near an apartment block, entrance node, wall,
  playground). They live in `visual_props` and are drawn by Godot only. Parked cars are never
  exported to BeamNG (CPU/GPU load there); other yard props may follow later as a separate
  decision. S3DB `building:min_level` counts as 3 m storeys when `min_height` is absent.
- Texture styles (2026-10-08, owner): facade looks are switchable packs, not baked into the world.
  Godot switches them at run time (global shader uniform `facade_style`); BeamNG gets the chosen
  one baked at export (`--texture-style`, default `procedural`). In a photo style every facade
  family uses the pack (no procedural walls left among photo ones). Packs the owner downloads by
  hand live in ignored `texture_packs/`; import tools write ignored `game/assets/textures` with
  per-file SHA-256 and licence. Styles are visual only and must be named as such in posts.
  A photo style also covers the ground (2026-10-08, owner: "better ground and grass"): ambientCG
  CC0 `photo_*` sets (lawn, meadow, verge, worn turf, trodden soil) mixed as base cover +
  patches + worn spots; Godot blends them per pixel, BeamNG gets baked 24 m sheets for
  `kyiv_grass`/`kyiv_ground` (normals flipped to DirectX, assumed, not confirmed in BeamNG docs).
  `synthwave` (2026-10-08, owner): no CC0 retrowave texture pack exists (only wallpapers and
  backgrounds), so the 1980s neon look is fully procedural: shaders in Godot, baked emissive
  tiles and a dusk sky in BeamNG. A style may change sky, fog and glow, never geometry.
  `nes` (2026-10-10, owner: "8-bit, like old NES games"): procedural like synthwave. Godot draws
  world-space pixels in the 2C02 palette and adds a palette screen filter (the part that makes it
  read as a console); BeamNG gets the same sprites baked, without the filter.
- Public project/distribution/CLI/repository: Earth2Road / `earth2road`
  (github.com/Alezx311/earth2road). The only CLI is `earth2road`; `akadem_maps` (Python
  package) and `AKADEM_*` (environment) are internal technical names.
- One engine-neutral world feeds the Godot and BeamNG adapters. Exports do not mutate inputs.
- Roadgen-v2 road profiles (2026-10-06, owner feedback supersedes the earlier
  keep-all-longitudinal-DEM-detail compromise): roads may cut/fill local terrain.
  Robust outlier removal is followed by distance-scaled curvature fairing along
  complete strokes (30 m characteristic length, or 0.8 times the class filter
  radius if larger). These are synthetic engineering choices, not design standards.
  Constant grades and broad terrain trends remain; repeated shorter hills/dips are
  suppressed. Shared heights follow the higher-class, then longer stroke. Reconcile
  strokes before assembling OSM ways and synchronize the resulting node anchors, so
  neither stroke switches nor later source-node constraints put the waves back.
  Closed strokes use periodic padding. Legacy elevation remains unchanged.
  Junction topology comes from network approaches even if their meshes were absorbed
  by neighbouring templates; a missing short mesh must not erase a same-street seam.
  Connected same-level road footprints are subtracted from fallback junctions rather
  than covered by a second height-interpolated asphalt layer.
- Roadgen-v2 elevation preserves broad terrain shape: uniform distance samples and robust
  local linear filtering are derived geometry. Absolute grade thresholds (6%, service 12%)
  diagnose steep surfaces; they do not flatten a natural hill. Legacy worlds remain readable
  and legacy builds keep the old profile. BeamNG navigation must respect node-radius spacing;
  residual height-chord errors and missing owning surfaces are reported, not silently hidden.
  The filter follows strokes (straightest continuation through a junction), and bend
  heights never extrapolate a fitted plane across the road width.
- Roadgen-v2 junction heights (owner's compromise, 2026-10-05): longitudinal DEM grades stay;
  crossfall and local humps/dips are what gets smoothed. In a template core the flattest pair
  of roughly opposite arms keeps its own profile and the other roads ramp to it, so inside the
  core their crossfall equals the through road's grade (a steep street levels out across a
  flat one). Clusters and cores without such a pair use a harmonic surface through the outer
  sockets; fallback junction surfaces fix only the road mouths (natural kerb boundary).
  Shared-node height corrections fade over |correction|/3% (12–60 m), not at the next OSM node.
- Roadgen-v2 main roads (2026-10-05, owner feedback after driving): the DEM filter window grows
  with road class (trunk/motorway 90 m, primary 70, secondary 50, tertiary 36, others 24).
  The two one-way carriageways of a named divided road share one dense profile; the node-level
  pair closing (chords between sparse OSM nodes) is not used in v2. DEM samples within 14 m of a
  bridge deck are not trusted for roads beneath. Bridge decks are shaped densely as a crest curve
  (60 m) at the ramp grade so that the deck stands BRIDGE_CLEARANCE above the final profile of
  every road beneath, not only at OSM nodes. Legacy builds keep their old heights.
- New builds/exports require fresh output directories. Map replacement requires an explicit
  flag and preserves a backup. Activation is a separate explicit action.
- Original code retains its existing MIT copyright notice. OSM and other external data retain
  their own terms. Vendored GEVP retains its license. Proprietary engine assets are not shipped.
- Public Git contains source/configuration and the MIT synthetic fixture. Downloads, historical
  snapshots, personal notes, local QA profiles and binaries are excluded.
- Road layout may be observed; DEM smoothing, assumed structure heights, facade styles,
  demand and signal timings are derived/synthetic. They are not measured traffic or surveyed geometry.
- Source snapshots are immutable and keyed by spatial coverage plus selection rules,
  independently of map IDs. Only verified complete coverage may serve another area.
  Local PBF packages precede Overpass; country downloads require a separate explicit
  action with a displayed size. Imported coverage is a user's declaration, never
  inferred from a filename or object envelope. Snapshots have no automatic expiry.
- Offline preparation includes OSM and DEM. Prepared source availability is separate
  from online name search/map backgrounds and from successful road geometry/runtime
  acceptance. Antimeridian-crossing maps remain unsupported.
