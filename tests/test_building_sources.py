"""DATA package tests: Microsoft GlobalMLBuildingFootprints + Overture ingestion.

Fixture-only: nothing here touches the network. The Microsoft index/quadkey
files are synthesized in memory; the Overture path uses a genuine local
GeoJSON fixture; duckdb is only tested for its missing-CLI failure mode.
"""
import gzip
import io
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import building_sources as bs

TEST_BBOX = [30.3, 50.4, 30.5, 50.5]  # western Kyiv-ish, ~15 km

MS_RELEASE = "2026-08-13"
OVT_RELEASE = "2026-08-19.0"

INDEX_HOST = "bfppub.blob.core.windows.net"
DATA_HOST = "bfppub.z5.web.core.windows.net"
DATA_PREFIX = f"/{MS_RELEASE}/global-buildings.geojsonl/"


def mspoly(coords):
    return {"type": "Polygon", "coordinates": [coords]}


def ms_feature(sid, coords, height: float = -1.0, extra=None):
    f = {"type": "Feature",
         "properties": {"id": sid, "areaInMeters": 100.0, "height": height},
         "geometry": mspoly(coords)}
    if extra:
        f["properties"].update(extra)
    return f


def gz_lines(lines):
    return gzip.compress(("\n".join(json.dumps(l) for l in lines)).encode("utf-8"))


def ms_fixture(bbox=TEST_BBOX, data_host=DATA_HOST):
    """Index CSV + per-quadkey gz data files that cover `bbox`."""
    qk = bs.quadkey_for((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2, 9)
    data_url = (f"https://{data_host}{DATA_PREFIX}RegionName=Ukraine/"
                f"quadkey={qk}/part-00001-test.c000.csv.gz")
    index = ("Location,QuadKey,Url,Size,UploadDate\n"
             f"Ukraine,{qk},{data_url},1KB,2026-08-13\n"
             "Ukraine,0,https://{data_host}{prefix}RegionName=Ukraine/quadkey=0/part-x.c000.csv.gz,1KB,2026-08-13\n"
             "Ukraine,not-a-quadkey,https://{data_host}{prefix}RegionName=Ukraine/quadkey=x/part-x.c000.csv.gz,1KB,2026-08-13\n").format(
                 data_host=data_host, prefix=DATA_PREFIX)
    inside = [[30.40, 50.44], [30.41, 50.44], [30.41, 50.45], [30.40, 50.44]]
    lines = [
        ms_feature("ua-in-1", inside, height=-1),
        ms_feature("ua-in-2", inside, height=4.5),  # MS heights are always ML, even when set
        ms_feature("ua-in-multi", inside),
        {"type": "Feature", "properties": {"id": "ua-in-multi"},  # duplicate id -> dropped
         "geometry": ms_feature("dup", [[30.42, 50.46], [30.43, 50.46], [30.43, 50.47], [30.42, 50.46]])["geometry"]},
        ms_feature("ua-out", [[30.90, 50.90], [30.91, 50.90], [30.91, 50.91], [30.90, 50.90]]),
        ms_feature("ua-bad", [[30.40, 50.44], [30.41, 50.44], ["NaN", 50.45], [30.40, 50.44]]),
        {"type": "Feature", "properties": {"id": "ua-line"},
         "geometry": {"type": "LineString", "coordinates": inside}},
        ms_feature("ua-mp", inside, extra={"id": "ua-mp"}),
    ]
    lines[-1] = {"type": "Feature",
                 "properties": {"id": "ua-mp", "areaInMeters": 1.0, "height": -1},
                 "geometry": {"type": "MultiPolygon", "coordinates": [[inside]]}}
    files = {data_url: gz_lines(lines)}
    return index, files


def make_fetch(files):
    """Fake fetch: returns fixture bytes for known URLs, counts calls."""
    calls = []

    def fake(url, max_bytes, max_time):
        calls.append(url)
        if url not in files:
            raise bs.FetchError(f"unexpected URL in test fixture: {url}")
        return files[url]

    return fake, calls


def ms_fetch_files():
    """Full fetch map: Microsoft index URL -> CSV bytes, data URLs -> gz bytes."""
    index, files = ms_fixture()
    files = dict(files)
    files[ms_source_cfg()["index_url"]] = index.encode("utf-8")
    return files


def ms_source_cfg():
    return {
        "release": MS_RELEASE,
        "license": "CDLA-Permissive-2.0",
        "index_url": f"https://{INDEX_HOST}/$web/{MS_RELEASE}/dataset-links.csv",
        "index_sha256": None,
        "url_hosts": [INDEX_HOST, DATA_HOST],
        "data_path_prefix": DATA_PREFIX,
        "file_caps": {"max_bytes": 1 << 20, "max_time": 30},
        "index_caps": {"max_bytes": 1 << 20, "max_time": 30},
        "height_provenance": "ml_estimated",
        "geo_q": 0.002,
    }


def ovt_source_cfg():
    return {
        "release": OVT_RELEASE,
        "license": "ODbL-1.0",
        "height_provenance": "overture_assumed",
        "geo_q": 0.002,
        "local_max_bytes": 1 << 20,
    }


def ovt_fixture_body():
    inside = [[[30.40, 50.44], [30.41, 50.44], [30.41, 50.45], [30.40, 50.44]]]
    outside = [[[30.90, 50.90], [30.91, 50.90], [30.91, 50.91], [30.90, 50.90]]]
    feats = [
        {"type": "Feature", "properties": {"id": "ovt-1", "height": 22.5, "num_floors": 7},
         "geometry": {"type": "Polygon", "coordinates": inside}},
        {"type": "Feature", "properties": {"id": "ovt-2", "height": -5},
         "geometry": {"type": "Polygon", "coordinates": inside}},
        {"type": "Feature", "properties": {"id": "ovt-3", "height": 9.0},
         "geometry": {"type": "Polygon", "coordinates": outside}},
        {"type": "Feature", "properties": {"id": "ovt-4"},
         "geometry": {"type": "MultiPolygon", "coordinates": [inside]}},
        {"type": "Feature", "properties": {"id": "ovt-5", "height": None},
         "geometry": {"type": "Polygon", "coordinates": inside}},
        {"type": "Feature", "properties": {"id": "ovt-1", "height": 1.0},  # dup id
         "geometry": {"type": "Polygon", "coordinates": [[30.44, 50.46], [30.45, 50.46], [30.45, 50.47], [30.44, 50.46]]}},
    ]
    return "\n".join(json.dumps(f) for f in feats) + "\n"


class QuadKeyTests(unittest.TestCase):
    def test_reference_cells(self):
        w, n, e, s = bs.quadkey_bounds("0")
        self.assertAlmostEqual(w, -180.0)
        self.assertAlmostEqual(e, 0.0)
        self.assertAlmostEqual(s, 0.0)
        self.assertAlmostEqual(n, 85.0511287798066, places=6)

    def test_roundtrip(self):
        for lon, lat, z in [(30.35, 50.45, 9), (-73.98, 40.75, 10), (139.69, 35.69, 11)]:
            w, n, e, s = bs.quadkey_bounds(bs.quadkey_for(lon, lat, z))
            self.assertLessEqual(w, lon)
            self.assertGreaterEqual(e, lon)
            self.assertLessEqual(s, lat)
            self.assertGreaterEqual(n, lat)

    def test_bad_quadkey(self):
        with self.assertRaises(ValueError):
            bs.quadkey_bounds("abc")


class HeightTests(unittest.TestCase):
    def test_clean_height(self):
        self.assertIsNone(bs.clean_height(-1))
        self.assertIsNone(bs.clean_height(0))
        self.assertIsNone(bs.clean_height(float("inf")))
        self.assertIsNone(bs.clean_height(float("nan")))
        self.assertIsNone(bs.clean_height("abc"))
        self.assertIsNone(bs.clean_height(None))
        self.assertEqual(bs.clean_height(12.5), 12.5)
        self.assertEqual(bs.clean_height("3"), 3.0)


class NormalizeTests(unittest.TestCase):
    def test_normal_form_properties(self):
        in_geom = {"type": "Polygon", "coordinates": [[[30.40, 50.44], [30.41, 50.44], [30.41, 50.45], [30.40, 50.44]]]}
        f = bs.normalize_feature({"type": "Feature", "properties": {"id": "x1", "height": -1},
                                  "geometry": in_geom},
                                 source="microsoft", release=MS_RELEASE, license_="CDLA-Permissive-2.0",
                                 height_provenance="ml_estimated")
        self.assertEqual(f["properties"]["source"], "microsoft")
        self.assertEqual(f["properties"]["source_id"], "x1")
        self.assertEqual(f["properties"]["release"], MS_RELEASE)
        self.assertEqual(f["properties"]["license"], "CDLA-Permissive-2.0")
        self.assertIsNone(f["properties"]["height"])
        self.assertIsNone(f["properties"]["height_provenance"])
        self.assertEqual(set(f["properties"]), set(bs.NORMAL_PROPS))

    def test_ms_negative_height_becomes_none(self):
        in_geom = {"type": "Polygon", "coordinates": [[[30.40, 50.44], [30.41, 50.44], [30.41, 50.45], [30.40, 50.44]]]}
        f = bs.normalize_feature({"type": "Feature", "properties": {"id": "x1", "height": -1},
                                  "geometry": in_geom},
                                 source="microsoft", release=MS_RELEASE, license_="CDLA-Permissive-2.0",
                                 height_provenance="ml_estimated")
        self.assertIsNone(f["properties"]["height"])

    def test_drops_invalid(self):
        bad = [
            {"geometry": {"type": "LineString", "coordinates": [[30.4, 50.4], [30.5, 50.5]]}},
            {"geometry": {"type": "Polygon", "coordinates": [[[30.4, 50.4], [30.5, 50.4], [30.5, 50.5], [30.4, "NaN"]]]}},
            {"geometry": {"type": "Point", "coordinates": [30.4, 50.4]}},
            {"geometry": None},
        ]
        for b in bad:
            f = bs.normalize_feature({"type": "Feature", "properties": {"id": "z"}, **b},
                                     source="microsoft", release=MS_RELEASE, license_="x",
                                     height_provenance="ml_estimated")
            self.assertIsNone(f, b)

    def test_deterministic_fallback_id(self):
        geom = {"type": "Polygon", "coordinates": [[[30.40, 50.44], [30.41, 50.44], [30.41, 50.45], [30.40, 50.44]]]}
        a = bs.normalize_feature({"type": "Feature", "properties": {}, "geometry": geom},
                                 source="microsoft", release=MS_RELEASE, license_="x", height_provenance="ml_estimated")
        b = bs.normalize_feature({"type": "Feature", "properties": {}, "geometry": geom},
                                 source="microsoft", release=MS_RELEASE, license_="x", height_provenance="ml_estimated")
        self.assertIsNotNone(a)
        self.assertEqual(a["properties"]["source_id"], b["properties"]["source_id"])
        self.assertTrue(a["properties"]["source_id"].startswith("microsoft-auto-"))

    def test_bbox_intersect_not_containment(self):
        box_in = bs.shape({"type": "Polygon", "coordinates": [[[30.37, 50.43], [30.43, 50.43], [30.43, 50.48], [30.37, 50.43]]]})
        self.assertTrue(bs.intersects_bbox(box_in, TEST_BBOX))  # crosses the bbox
        self.assertTrue(bs.intersects_bbox(bs.box(30.4, 50.45, 30.49, 50.49), TEST_BBOX))  # contained
        self.assertTrue(bs.intersects_bbox(bs.box(30.48, 50.48, 30.6, 50.6), TEST_BBOX))  # touching corner
        self.assertFalse(bs.intersects_bbox(bs.box(30.9, 50.9, 31.0, 51.0), TEST_BBOX))   # disjoint


class SelectRowsTests(unittest.TestCase):
    def test_select_intersecting_rows(self):
        rows = [
            {"location": "Ukraine", "quadkey": bs.quadkey_for(30.4, 50.45, 9), "url": "https://a/1.csv.gz"},
            {"location": "Ukraine", "quadkey": "0", "url": "https://a/0.csv.gz"},  # Atlantic
            {"location": "Ukraine", "quadkey": "bad", "url": "https://a/bad.csv.gz"},
        ]
        sel = bs.select_quadkey_rows(rows, TEST_BBOX, location="Ukraine")
        self.assertEqual(len(sel), 1)
        self.assertEqual(sel[0]["quadkey"], bs.quadkey_for(30.4, 50.45, 9))

    def test_location_filter(self):
        rows = [{"location": "France", "quadkey": bs.quadkey_for(30.4, 50.45, 9), "url": "u"}]
        self.assertEqual(bs.select_quadkey_rows(rows, TEST_BBOX, location="Ukraine"), [])


class MicrosoftPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bs-ms-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_fetch_cache_offline_reuse(self):
        fetch, calls = make_fetch(ms_fetch_files())
        cfg = ms_source_cfg()

        feats1, audit1 = bs.ingest_microsoft(TEST_BBOX, cfg, self.tmp, fetch=fetch)
        self.assertEqual(audit1["status"], "ok")
        self.assertFalse(audit1["cached"])
        ids1 = [f["properties"]["source_id"] for f in feats1]
        # ua-in-1, ua-in-2, ua-in-multi (+ its dedup drop), ua-mp kept; ua-out/ua-bad/ua-line dropped
        self.assertEqual(set(ids1), {"ua-in-1", "ua-in-2", "ua-in-multi", "ua-mp"})
        self.assertEqual(len(set(ids1)), 4)
        for f in feats1:
            self.assertEqual(f["properties"]["source"], "microsoft")
            if f["properties"]["source_id"] == "ua-in-2":
                self.assertEqual(f["properties"]["height"], 4.5)
                self.assertEqual(f["properties"]["height_provenance"], "ml_estimated")
            else:
                self.assertIsNone(f["properties"]["height"])
                self.assertIsNone(f["properties"]["height_provenance"])
        # ua-in-multi appears once exactly
        self.assertEqual(ids1.count("ua-in-multi"), 1)
        # sorted deterministically
        self.assertEqual(ids1, sorted(ids1))
        self.assertEqual(len(calls), 2)  # index + 1 data file (disjoint quadkey never fetched)

        feats2, audit2 = bs.ingest_microsoft(TEST_BBOX, cfg, self.tmp, offline=True, fetch=fetch)
        self.assertEqual(audit2["status"], "ok")
        self.assertTrue(audit2["cached"])
        self.assertEqual([f["properties"]["source_id"] for f in feats2], ids1)
        self.assertEqual(len(calls), 2)  # offline reuse: no new network

        feats3, audit3 = bs.ingest_microsoft(TEST_BBOX, cfg, self.tmp, offline=True, fetch=fetch)
        self.assertEqual(feats3, feats1)

    def test_offline_cache_miss_reports_not_empty(self):
        cfg = ms_source_cfg()
        feats, audit = bs.ingest_microsoft(TEST_BBOX, cfg, self.tmp, offline=True)
        self.assertEqual(feats, [])
        self.assertEqual(audit["status"], "offline_cache_miss")
        self.assertTrue(audit.get("error"))

    def test_no_quadkeys_refuses_empty_cache(self):
        cfg = ms_source_cfg()
        ocean = [170.0, -20.0, 171.0, -19.0]
        with self.assertRaises(bs.SourceError):
            bs.ingest_microsoft(ocean, cfg, self.tmp, fetch=make_fetch({})[0])

    def test_failure_never_cached(self):
        index, files = ms_fixture()
        ok = index.splitlines(keepends=True)[0] + "\n"
        files = {u: files[u] for u in files}
        # force the data URL host off the allow-list -> SourceError before download
        fetch, calls = make_fetch(files)
        cfg = ms_source_cfg()
        cfg["url_hosts"] = [INDEX_HOST]
        with self.assertRaises(bs.SourceError):
            bs.ingest_microsoft(TEST_BBOX, cfg, self.tmp, fetch=fetch)
        self.assertEqual(list(self.tmp.rglob("features.geojson")), [])
        # a *network* failure instead: also nothing cached
        cfg = ms_source_cfg()
        fetch, calls = make_fetch({})

        def bad(url, mb, mt):
            raise bs.FetchError("connection refused (test)")

        with self.assertRaises(bs.SourceError):
            bs.ingest_microsoft(TEST_BBOX, cfg, self.tmp, fetch=bad)
        self.assertEqual(list(self.tmp.rglob("features.geojson")), [])


class OvertureLocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bs-ovt-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = self.tmp / "overture.geojson"
        self.src.write_text(ovt_fixture_body(), encoding="utf-8")

    def test_local_ingest_normal_forms(self):
        cfg = ovt_source_cfg()
        feats, audit = bs.ingest_overture_local(TEST_BBOX, cfg, self.tmp / "cache", self.src)
        self.assertEqual(audit["status"], "ok")
        by_id = {f["properties"]["source_id"]: f for f in feats}
        self.assertEqual(set(by_id), {"ovt-1", "ovt-2", "ovt-4", "ovt-5"})
        self.assertEqual(by_id["ovt-1"]["properties"]["height"], 22.5)
        self.assertEqual(by_id["ovt-1"]["properties"]["height_provenance"], "overture_assumed")
        self.assertIsNone(by_id["ovt-2"]["properties"]["height"])  # -5 -> None
        self.assertIsNone(by_id["ovt-2"]["properties"]["height_provenance"])
        self.assertIsNone(by_id["ovt-5"]["properties"]["height"])  # null -> None
        for f in feats:
            self.assertEqual(f["properties"]["source"], "overture")
            self.assertEqual(f["properties"]["release"], OVT_RELEASE)

        feats2, audit2 = bs.ingest_overture_local(TEST_BBOX, cfg, self.tmp / "cache", self.src, offline=True)
        self.assertTrue(audit2["cached"])
        self.assertEqual(feats2, feats)

        # changing the local input invalidates the cache (input sha tracked)
        self.src.write_text(ovt_fixture_body() + '{"type":"Feature","properties":{"id":"ovt-new","height":3.0},"geometry":{"type":"Polygon","coordinates":[[[30.40,50.44],[30.41,50.44],[30.41,50.45],[30.40,50.44]]]}}\n')
        feats3, audit3 = bs.ingest_overture_local(TEST_BBOX, cfg, self.tmp / "cache", self.src)
        self.assertFalse(audit3["cached"])
        self.assertIn("ovt-new", [f["properties"]["source_id"] for f in feats3])

    def test_missing_local_input_reported(self):
        cfg = ovt_source_cfg()
        with self.assertRaises(bs.SourceError):
            bs.ingest_overture_local(TEST_BBOX, cfg, self.tmp / "cache", self.tmp / "nope.geojson")

    def test_options_change_invalidates_cache(self):
        """Strict source identity: same local file but changed options (or engine)
        must NOT be served from the old cache."""
        cfg_a = ovt_source_cfg()
        cfg_b = dict(cfg_a)
        cfg_b["height_provenance"] = "user_checked"
        self.assertNotEqual(bs._options_digest(cfg_a, engine="local"),
                            bs._options_digest(cfg_b, engine="local"))
        self.assertNotEqual(bs._options_digest(cfg_a, engine="local"),
                            bs._options_digest(cfg_a, engine="duckdb"))
        cache = self.tmp / "cache"
        _, a1 = bs.ingest_overture_local(TEST_BBOX, cfg_a, cache, self.src)
        self.assertFalse(a1["cached"])
        self.assertEqual(a1["status"], "ok")
        _, a2 = bs.ingest_overture_local(TEST_BBOX, cfg_a, cache, self.src, offline=True)
        self.assertTrue(a2["cached"])
        # same input file, different options -> strict digest rejects the cache
        _, a3 = bs.ingest_overture_local(TEST_BBOX, cfg_b, cache, self.src, offline=True)
        self.assertEqual(a3["status"], "offline_cache_miss")
        _, a4 = bs.ingest_overture_local(TEST_BBOX, cfg_b, cache, self.src)
        self.assertFalse(a4["cached"])
        self.assertEqual(a4["status"], "ok")


class DuckdbTests(unittest.TestCase):
    def test_missing_cli_reports_error(self):
        cfg = ovt_source_cfg()
        cfg["release"] = OVT_RELEASE
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(bs.SourceError):
                bs.ingest_overture_duckdb(TEST_BBOX, cfg, Path(tmp), duckdb_cli="definitely-not-a-duckdb")

    def test_sql_validation_rejects_bad_release(self):
        cfg = ovt_source_cfg()
        cfg["release"] = "rm -rf /"
        cfg["parquet_s3_template"] = "s3://overturemaps-us-west-2/release/{release}/theme=buildings/type=building/*.parquet"
        with self.assertRaises(bs.SourceError):
            bs._duckdb_sql(cfg, TEST_BBOX, Path("/tmp/x.geojsonseq"))

    def test_sql_build_is_bounded_and_pinned(self):
        cfg = ovt_source_cfg()
        cfg["parquet_s3_template"] = "s3://overturemaps-us-west-2/release/{release}/theme=buildings/type=building/*.parquet"
        sql = bs._duckdb_sql(cfg, TEST_BBOX, Path("/tmp/opencode/out.geojsonseq"))
        self.assertIn(f"release/{OVT_RELEASE}/theme=buildings", sql)
        self.assertIn("bbox.xmin < 30.5", sql)
        self.assertIn("DRIVER 'GeoJSONSeq'", sql)

    @unittest.skipIf(os.name == 'nt', 'fake duckdb CLI is a Unix shebang script')
    def test_duckdb_audit_metrics_are_honest(self):
        """The duckdb engine cannot measure its own network transfer: audit must
        report downloaded_bytes=None and extracted_bytes = produced GeoJSON bytes,
        and both must survive a cache round-trip."""
        cfg = ovt_source_cfg()
        cfg["parquet_s3_template"] = "s3://overturemaps-us-west-2/release/{release}/theme=buildings/type=building/*.parquet"
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            line = ('{"type":"Feature","properties":{"id":"ovt-d1","height":18.5},'
                    '"geometry":{"type":"Polygon","coordinates":[[[30.40,50.44],[30.41,50.44],'
                    '[30.41,50.45],[30.40,50.44]]]}}')
            b64 = __import__("base64").b64encode((line + "\n").encode("utf-8")).decode("ascii")
            cli = Path(tmp) / "fake-duckdb"
            cli.write_text(
                "#!/usr/bin/env python3\n"
                "import re, sys, base64\n"
                "sql = sys.argv[2]\n"
                "m = re.search(r\"\\) TO '([^']*)' \\(\", sql)\n"
                "assert m, sql\n"
                f"open(m.group(1), 'wb').write(base64.b64decode('{b64}'))\n")
            cli.chmod(0o755)
            feats, audit = bs.ingest_overture_duckdb(TEST_BBOX, cfg, cache, duckdb_cli=str(cli))
            self.assertEqual(audit["status"], "ok")
            self.assertIsNone(audit["downloaded_bytes"])              # unmeasurable, never inferred from output size
            self.assertEqual(audit["extracted_bytes"], len(line) + 1)  # the GeoJSONSeq actually produced
            self.assertIsNone(audit["index_bytes"])
            self.assertIsNone(audit["shard_bytes"])
            self.assertEqual(audit["engine"], "duckdb")
            self.assertEqual(len(feats), 1)
            feats2, audit2 = bs.ingest_overture_duckdb(TEST_BBOX, cfg, cache,
                                                       duckdb_cli=str(cli), offline=True)
            self.assertTrue(audit2["cached"])
            self.assertIsNone(audit2["downloaded_bytes"])             # metrics preserved via cache meta
            self.assertEqual(audit2["extracted_bytes"], len(line) + 1)
            self.assertEqual(feats2, feats)


class UrlSafetyTests(unittest.TestCase):
    def test_rejects_unsafe(self):
        hosts = ["bfppub.z5.web.core.windows.net"]
        good = "https://bfppub.z5.web.core.windows.net/2026-08-13/global-buildings.geojsonl/x.csv.gz"
        self.assertEqual(bs.check_url(good, hosts, path_prefix="/2026-08-13/", suffix=".csv.gz"), good)
        for bad in [
            "http://bfppub.z5.web.core.windows.net/x",
            "https://evil.example/x",
            "https://bfppub.z5.web.core.windows.net/../etc/passwd",
            "https://user:pass@bfppub.z5.web.core.windows.net/x",
            "https://bfppub.z5.web.core.windows.net/other.csv.gz",
            "https://bfppub.z5.web.core.windows.net/x.csv",
        ]:
            with self.assertRaises(ValueError, msg=bad):
                bs.check_url(bad, hosts, path_prefix="/2026-08-13/", suffix=".csv.gz")


class LoadCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bs-lc-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ovt_file = self.tmp / "ovt.geojson"
        self.ovt_file.write_text(ovt_fixture_body(), encoding="utf-8")

    def base_cfg(self, enabled: "bool | None" = True, sources=None):
        cfg = {"id": "test_map", "bbox": list(TEST_BBOX), "center": [30.4, 50.45]}
        if enabled is not None:
            en = {"enabled": enabled, "cache_dir": str(self.tmp / "cache"),
                  "sources_config": str(self.tmp / "building_sources.json")}
            if sources is not None:
                en["sources"] = sources
            cfg["building_enrichment"] = en
        return cfg

    def write_sources_config(self):
        sc = {"version": 1, "sources": {"microsoft": ms_source_cfg(), "overture": ovt_source_cfg()}}
        (self.tmp / "building_sources.json").write_text(json.dumps(sc), encoding="utf-8")

    def test_disabled_by_default(self):
        self.write_sources_config()
        feats, audit = bs.load_candidates(self.base_cfg(enabled=None))
        self.assertEqual(feats, [])
        self.assertEqual(audit["status"], "disabled")

    def test_merged_enabled_sources(self):
        self.write_sources_config()
        fetch, calls = make_fetch(ms_fetch_files())
        cfg = self.base_cfg(enabled=True, sources={
            "microsoft": {},
            "overture": {"local_geojson": str(self.ovt_file)},
        })
        feats, audit = bs.load_candidates(cfg, fetch=fetch)
        self.assertEqual(audit["status"], "ok")
        self.assertEqual(audit["map_id"], "test_map")
        self.assertEqual(audit["bbox_requested"], list(TEST_BBOX))
        ids = [f["properties"]["source_id"] for f in feats]
        self.assertIn("ua-in-1", ids)
        self.assertIn("ovt-1", ids)
        # canonical deterministic order: source priority (overture, microsoft), then id
        self.assertEqual(ids, ["ovt-1", "ovt-2", "ovt-4", "ovt-5",
                               "ua-in-1", "ua-in-2", "ua-in-multi", "ua-mp"])
        ms_ids = [f["properties"]["source_id"] for f in feats if f["properties"]["source"] == "microsoft"]
        ovt_f = [f for f in feats if f["properties"]["source_id"] == "ovt-1"][0]
        self.assertEqual(ovt_f["properties"]["height"], 22.5)
        # per-source audits carry release/license
        self.assertEqual(audit["sources"]["microsoft"]["release"], MS_RELEASE)
        self.assertEqual(audit["sources"]["microsoft"]["license"], "CDLA-Permissive-2.0")
        self.assertEqual(audit["sources"]["overture"]["license"], "ODbL-1.0")
        self.assertEqual(audit["features"], len(feats))
        self.assertEqual(len(feats), 8)

    def test_offline_miss_propagates(self):
        self.write_sources_config()
        cfg = self.base_cfg(enabled=True, sources={"microsoft": {}})
        feats, audit = bs.load_candidates(cfg, offline=True)
        self.assertEqual(feats, [])
        self.assertEqual(audit["status"], "offline_cache_miss")
        self.assertIn("microsoft", audit["sources"])

    def test_error_recorded_not_cached(self):
        sc = {"version": 1, "sources": {"microsoft": ms_source_cfg(), "overture": ovt_source_cfg()}}
        sc["sources"]["microsoft"]["url_hosts"] = [DATA_HOST]  # index host now refused
        (self.tmp / "building_sources.json").write_text(json.dumps(sc), encoding="utf-8")
        cfg = self.base_cfg(enabled=True, sources={"microsoft": {}})
        feats, audit = bs.load_candidates(cfg, fetch=make_fetch({})[0])
        self.assertEqual(feats, [])
        self.assertEqual(audit["status"], "error")
        self.assertTrue(audit["sources"]["microsoft"]["error"])
        self.assertEqual(list((self.tmp / "cache").rglob("features.geojson")), [])

    def test_overture_no_input_reported(self):
        self.write_sources_config()
        cfg = self.base_cfg(enabled=True, sources={"overture": {}})  # no local, no duckdb
        feats, audit = bs.load_candidates(cfg)
        self.assertEqual(audit["status"], "no_source_data")
        self.assertEqual(audit["sources"]["overture"]["status"], "no_input")

    def test_overture_local_path_resolves_relative_to_root(self):
        self.write_sources_config()
        # relative path resolves against ROOT; "ovt.geojson" does not exist there
        cfg = self.base_cfg(enabled=True, sources={"overture": {"local_geojson": "ovt.geojson"}})
        feats, audit = bs.load_candidates(cfg, fetch=make_fetch({})[0])
        self.assertEqual(feats, [])
        self.assertEqual(audit["status"], "error")


class DedupTests(unittest.TestCase):
    def mk(self, sid, source, geom):
        return {"type": "Feature", "geometry": json.loads(json.dumps(geom)),
                "properties": {"source": source, "source_id": sid, "release": "r",
                               "license": "l", "height": None, "height_provenance": None}}

    def poly(self, dx=0.0, dy=0.0):
        return bs.mapping(bs.box(30.40 + dx, 50.44 + dy, 30.41 + dx, 50.45 + dy))

    def test_osm_priority_drops_overlap(self):
        a = self.mk("a", "microsoft", self.poly())
        b = self.mk("b", "microsoft", self.poly(0.5, 0.5))
        kept, dropped = bs.dedup_osm_priority([a, b], [bs.box(30.40, 50.44, 30.405, 50.445)])
        self.assertEqual([f["properties"]["source_id"] for f in kept], ["b"])
        self.assertEqual(dropped, ["a"])

    def test_duplicates_first_by_priority(self):
        geom = self.poly()
        ms = self.mk("same-geom", "microsoft", geom)
        ovt = self.mk("same-geom", "overture", geom)
        kept, dropped = bs.dedup_duplicates([ms, ovt])
        self.assertEqual([f["properties"]["source_id"] for f in kept], ["same-geom"])
        self.assertEqual(kept[0]["properties"]["source"], "overture")  # overture > microsoft
        self.assertEqual(dropped, ["same-geom"])

    def test_duplicates_exact_geometry(self):
        geom = self.poly()
        ms = self.mk("ms-x", "microsoft", geom)
        ovt = self.mk("ovt-y", "overture", geom)
        kept, dropped = bs.dedup_duplicates([ms, ovt])
        self.assertEqual([f["properties"]["source_id"] for f in kept], ["ovt-y"])
        self.assertEqual(dropped, ["ms-x"])

    def test_no_false_collapse_for_neighbours(self):
        a = self.mk("a", "microsoft", self.poly())
        b = self.mk("b", "microsoft", self.poly(0.001, 0.001))
        kept, dropped = bs.dedup_duplicates([a, b])
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, [])


if __name__ == "__main__":
    unittest.main()