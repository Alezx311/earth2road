# Decisions

- Public project/distribution/CLI/repository: Earth2Road / `earth2road`
  (github.com/Alezx311/earth2road; the GitHub repository was renamed from `terra-drive`).
  Keep `terra-drive` and `akadem-maps` as CLI aliases, `akadem_maps` imports and `AKADEM_*`
  settings for compatibility with existing workflows.
- One engine-neutral world feeds the Godot and BeamNG adapters. Exports do not mutate inputs.
- New builds/exports require fresh output directories. Map replacement requires an explicit
  flag and preserves a backup. Activation is a separate explicit action.
- Original code retains its existing MIT copyright notice. OSM and other external data retain
  their own terms. Vendored GEVP retains its license. Proprietary engine assets are not shipped.
- Public Git contains source/configuration and the MIT synthetic fixture. Downloads, historical
  snapshots, personal notes, local QA profiles and binaries are excluded.
- Road layout may be observed; DEM smoothing, assumed structure heights, facade styles,
  demand and signal timings are derived/synthetic. They are not measured traffic or surveyed geometry.
