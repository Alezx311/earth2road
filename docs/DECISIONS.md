# Decisions

- Local Visual DNA v0 is opt-in and engine-neutral. Manual district profiles are
  hypotheses, with per-property provenance and OSM taking precedence. Blend profile
  distributions in metric space; seed choices by map seed, OSM ID and property.
  Landmark importance and visual influence are separate. Keep world v2 and legacy
  paths compatible; new geometry remains spatially batched. The first experiment
  covers Podil buildings/greenery and landmark spawns, without imagery/CV or 3D
  reconstruction. See LOCAL_VISUAL_DNA.md for the interface and limitations.

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
