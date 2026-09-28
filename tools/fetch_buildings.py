#!/usr/bin/env python3
"""Fetch + normalise enrichment building sources for one map (cached).

Usual runs (map configs stay enrichment-OFF until integration; --enable is the
explicit opt-in for standalone use):

    .venv/bin/python tools/fetch_buildings.py --map focus_metro_mcd --enable
    .venv/bin/python tools/fetch_buildings.py --map focus_metro_mcd --enable --offline
    .venv/bin/python tools/fetch_buildings.py --map focus_metro_mcd --enable \
        --overture-local /path/to/ukraine-buildings.geojson --dump out.geojson

Exit code: 0 = ok or disabled, 2 = any source failed / offline cache miss
(integration must gate on the audit status, not the exit code).
"""
import argparse
import json
import sys
from pathlib import Path

import building_sources as bs

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", required=True, help="config id under config/<id>.json")
    ap.add_argument("--enable", action="store_true",
                    help="force building_enrichment.enabled for this run only")
    ap.add_argument("--offline", action="store_true",
                    help="never touch the network; reuse caches only")
    ap.add_argument("--overture-local", metavar="PATH",
                    help="genuine local Overture GeoJSON/GeoJSONSeq input")
    ap.add_argument("--duckdb", action="store_true",
                    help="attempt the optional duckdb CLI bbox query instead")
    ap.add_argument("--cache-dir", default=None, help="cache root (default .cache/buildings)")
    ap.add_argument("--sources-config", default=None,
                    help="source pins file (default config/building_sources.json)")
    ap.add_argument("--dump", metavar="OUT.geojson",
                    help="write the normalised FeatureCollection to this file")
    a = ap.parse_args(argv)

    cfg_path = ROOT / "config" / f"{a.map}.json"
    if not cfg_path.is_file():
        print(f"error: no map config {cfg_path}", file=sys.stderr)
        return 2
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    en = dict(cfg.get("building_enrichment") or {})
    if a.enable:
        en["enabled"] = True
    # microsoft is the default source; overture is activated only by an explicit
    # input (--overture-local / --duckdb) or by the map config itself, so a plain
    # run never implies Overture data was acquired.
    sources = {"microsoft": {}}
    sources.update(en.get("sources") or {})
    if a.overture_local or a.duckdb:
        overture = dict(sources.get("overture") or {})
        if a.overture_local:
            p = Path(a.overture_local)
            if not p.is_absolute():
                p = ROOT / p
            if not p.is_file():
                print(f"error: local Overture input not found: {p}", file=sys.stderr)
                return 2
            overture["local_geojson"] = str(p)
        if a.duckdb:
            overture["duckdb"] = True
        sources["overture"] = overture
    if a.cache_dir:
        en["cache_dir"] = a.cache_dir
    if a.sources_config:
        en["sources_config"] = a.sources_config
    en["sources"] = sources
    cfg["building_enrichment"] = en

    try:
        features, audit = bs.load_candidates(cfg, offline=a.offline)
    except (ValueError, bs.SourceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(audit, ensure_ascii=False, indent=1))

    if a.dump:
        out = Path(a.dump)
        out.write_text(json.dumps(
            {"type": "FeatureCollection", "features": features}, ensure_ascii=False),
            encoding="utf-8")
        print(f"wrote {len(features)} normalised features to {out}")

    return 0 if audit["status"] in ("ok", "disabled") else 2


if __name__ == "__main__":
    sys.exit(main())