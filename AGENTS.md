# Earth2Road — contributor and agent entry point

1. Inspect `git status --short`; preserve other work. Do not spawn agents unless requested.
2. Read `docs/HANDOFF.md`, `docs/PLAN.md`, `docs/DECISIONS.md` and `docs/VALIDATION.md`.
3. Inspect implementation and tests before editing. Plans and old map reports are not test results.
4. Update HANDOFF after completed work units; record exact checks and failed experiments.
5. Keep observed OSM information distinct from generated assumptions. Traffic demand and default signal timings are synthetic.
6. Keep downloads, engine binaries, generated maps, caches, credentials and personal notes out of Git.
7. Use `python -m unittest discover -s tests -v`; map/runtime checks are documented in CONTRIBUTING.
8. Preserve compatibility with `akadem_maps`, `akadem-maps`, existing world formats and map IDs.
