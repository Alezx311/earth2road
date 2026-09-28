# Contributing to TerraDrive

Use Python 3.14 for the pinned validation environment. The generator metadata allows
Python 3.11+, but the complete lock file and runtime acceptance were tested with 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock ".[generator,traffic]" build
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe -m pip check
```

Run the README offline example to exercise both exporters. Test the wheel from a directory
outside the checkout to catch accidental source-tree imports. The CI performs this check.

Full discovery includes unit, geometry and offline contract tests. Tests requiring installed
real maps, downloaded enrichment caches or Godot explicitly skip when unavailable; report the
skip count. Use `AKADEM_MAP` to select an installed map, then repeat discovery and the runtime
checks in [GAME](docs/GAME.md). Fresh fixture builds do not certify historical maps.

For Godot checks, install 4.6 under `.tools/` (or run setup), then import once:
`.tools/Godot_v4.6-stable_win64.exe --headless --editor --path game --quit`.
Unit discovery then includes the asset and vehicle availability subprocess tests.

Before publication, run `python tools/check_publication.py` against Git's candidate files and
`python -m pip_audit -r requirements.lock --no-deps --disable-pip --cache-dir .cache/advisories` (requires `pip install pip-audit` and advisory access).
Do not commit `.venv`, `.tools`, `data`, `game/data`, assets, logs, credentials or real-map ZIPs.
Generated map releases need their own provenance and runtime acceptance records.

Describe the trigger, resulting behavior and checks in pull requests. Bug reports should include
the command, OS, engine version, doctor output, JSONL events and relevant map coordinates.
Do not post tokens, credentials, personal filesystem paths or large downloaded datasets.

The lock file includes transitive runtime dependencies. Advisory checks skip dependency resolution
because every version is already pinned; `pip check` separately verifies installed compatibility.
