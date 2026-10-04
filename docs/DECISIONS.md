# Decisions

- Public project/distribution/CLI/repository: Earth2Road / `earth2road`
  (github.com/Alezx311/earth2road). The only CLI is `earth2road`; `akadem_maps` (Python
  package) and `AKADEM_*` (environment) are internal technical names.
- One engine-neutral world feeds the Godot and BeamNG adapters. Exports do not mutate inputs.
- Roadgen-v2 elevation preserves broad terrain shape: uniform distance samples and robust
  local linear filtering are derived geometry. Absolute grade thresholds (6%, service 12%)
  diagnose steep surfaces; they do not flatten a natural hill. Legacy worlds remain readable
  and legacy builds keep the old profile. BeamNG navigation must respect node-radius spacing;
  residual height-chord errors and missing owning surfaces are reported, not silently hidden.
  The filter follows strokes (straightest continuation through a junction), and bend
  heights never extrapolate a fitted plane across the road width.
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
