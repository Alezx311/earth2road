# Validation — 2026-09-28

The standalone **source repository is ready for publication as an experimental beta**.
This is not a release certificate for every historical map. Machine-readable results:
[VALIDATION.json](VALIDATION.json). Full local logs are retained in ignored `logs/publication/`.

Environment: Windows 11 x64 (26200), Python 3.14.0, Godot 4.6 stable,
SUMO 1.27.1, Pillow 12.3.0, BeamNG.drive 0.39.4.0.

| Check | Result |
|---|---|
| Full unittest discovery with installed maps, assets and enrichment fixtures | **301 passed, 1 skipped**, 302 discovered; 388.203 s; no failures/errors |
| Initial clean-checkout discovery | 302 discovered, 29 skipped for absent local maps/caches and Unix-only fixture; no failures/errors |
| Wheel and source distribution | Both built successfully; wheel installed into a separate environment |
| Installed wheel from outside the checkout | Doctor, offline world, validation, BeamNG export/validation, Godot export/install all passed |
| Dependency consistency | `pip check` passed |
| Dependency advisory audit | 16 pinned runtime packages; zero known vulnerabilities reported |
| Godot project | Headless import and main-scene startup passed; WORLD_READY reached |
| Akademmistechko surface | 2,690 probes across four routes; zero missing surfaces |
| Akademmistechko vehicle physics | Six scenarios passed: hold, reverse, long drive, stop-line traversal, kerb, traffic contact |
| Rivne vehicle physics | Three 350 m routes passed, zero off-road frames or contacts; hold and reverse passed |
| SUMO traffic | Leader braking, ego proxy and red signal passed; 1,800 simulated seconds with 100 cars, zero collisions/teleports |
| Road situations | Speed limit, lane closure, accident, expiry and traffic-light changes passed |
| Priority integration | Minor road yielded; zero collisions |
| BeamNG synthetic ZIP runtime | Complete, exit 0; 53/53 surface samples exact; 11 navigation nodes / 14 links; 8 vehicles, 7 traffic entries |
| Scripts | Python compileall, PowerShell AST and Bash syntax checks passed |
| Source publication audit | Candidate file audit passed: no matching credentials/private paths, oversized binaries or broken local Markdown links |

The single skip is `test_duckdb_audit_metrics_are_honest`: its fake DuckDB CLI
is a Unix shebang fixture and is intentionally skipped on Windows. The Linux CI job runs it.
The CI matrix covers Windows and Linux with complete discovery, Godot import, SUMO priority,
wheel/sdist, installation outside the checkout, source hygiene and advisory auditing.
Hosted CI has not yet run because this repository has not been uploaded.

## Reproduction

Install with `python -m pip install -c requirements.lock ".[generator,traffic]" build`.
Use a fresh output directory for every build/export. See [CONTRIBUTING](../CONTRIBUTING.md)
and [GAME](GAME.md) for engine setup and optional map-dependent checks.

```powershell
python -m unittest discover -s tests -v
python -m build
python tools/ci_offline.py
python -m pip check
python -m pip_audit -r requirements.lock --no-deps --disable-pip --cache-dir .cache/advisories --timeout 15
python tools/check_publication.py
```

`ci_offline.py` requires the built non-editable wheel to be installed first, as done in CI.
`setup.ps1`/`setup.sh` install the checkout editable (a copy frozen at setup time made the
CLI build maps with stale code), so run `ci_offline.py` locally from a separate venv.
Map-dependent tests require installed data and `AKADEM_MAP=akadem`; a fresh public clone
will skip them until maps are built. The tiny synthetic example needs no downloaded map data.

## Fixes and limitations

- Pillow was updated from 12.1.1 to 12.3.0 after the first advisory scan. All final source
  tests, exports and package checks use the corrected pin. See the upstream
  [Pillow 12.3.0 security changes](https://pillow.readthedocs.io/en/stable/releasenotes/12.3.0.html).
- CLI/distribution branding is `earth2road` (renamed on 2026-10-02); the `akadem_maps`
  module, existing IDs and formats remain compatible. Local environments are recreated on relocation.
- CI previously ran only `test_beta.py`; it now discovers the entire suite. Generated worlds,
  packaging outputs, assets, caches, binaries and secrets are excluded from Git.
- An interrupted preflight run has no valid result. A relative-executable path error in the
  local validation harness was fixed before completed checks. A slow redundant audit with
  dependency resolution was cancelled; the completed pinned-package advisory scan is the result above.
- Godot under the sandbox printed a root-certificate-store access warning. Some standalone
  physics validators also print resource/ObjectDB cleanup warnings at process exit; they complete
  their assertions with exit 0. No GDScript parse/runtime errors were observed in the completed checks.
- The BeamNG fixture has **zero signals** and a small flat synthetic network. Its smoke test
  checks loading, navigation, surface contact, vehicle/traffic creation and screenshots; it does
  not certify real-map signals, prolonged AI driving, road seams or frame-rate targets.
- Existing real-map data was preserved for local use. No large historical map was regenerated.
  Publish real map ZIPs only with their own provenance and map-specific acceptance results.
- Secret-pattern checks and an advisory scan are bounded checks, not guarantees against every
  possible secret or vulnerability. Runtime data has separate attribution from the MIT source.
