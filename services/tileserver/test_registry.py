#!/usr/bin/env python3
"""Tests for registry.py against the real tilesets.toml (Python 3.11+, standard library).

    python3 services/tileserver/test_registry.py

The file metadata below is what the delivered files carry: the six regions'
bounds come from imagery/scripts/regions-all.sh, the global set covers the
Web Mercator world to z10, every imagery file is WebP with the WorldCover
attribution (imagery/scripts/finish_mbtiles.py), and the basemap is
OpenMapTiles vector tiles to z7. MBTiles stores bounds as "w,s,e,n" text.
"""
import copy
import os
import tomllib
import unittest
from datetime import datetime, timezone

import registry

HERE = os.path.dirname(os.path.abspath(__file__))
WORLDCOVER = ("ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) "
              "processed by ESA WorldCover consortium")
REGIONS = {"hormuz": (52, 24, 58, 28), "taiwan-strait": (118, 22, 122, 26), "bosporus": (28, 40, 30, 42),
           "crimea": (32, 44, 37, 46), "channel": (-2, 49, 2, 52), "hampton-roads": (-77.5, 36, -75.5, 38)}


def delivered():
    files = [("horus-imagery-global", "s3://bucket/horus/dev/tiles/horus-imagery-global.pmtiles",
              {"name": "horus-imagery-global", "format": "webp", "minzoom": "0", "maxzoom": "10",
               "bounds": "-180,-85.0511,180,85.0511", "attribution": WORLDCOVER})]
    for name, b in REGIONS.items():
        files.append((f"horus-imagery-{name}", f"s3://bucket/horus/dev/tiles/horus-imagery-{name}.pmtiles",
                      {"name": f"horus-imagery-{name}", "format": "webp", "minzoom": "0", "maxzoom": "14",
                       "bounds": ",".join(map(str, b)), "attribution": WORLDCOVER}))
    files.append(("horus-basemap", "s3://bucket/horus/dev/tiles/horus-basemap.pmtiles",
                  {"name": "OpenMapTiles", "format": "pbf", "minzoom": 0, "maxzoom": 7,
                   "bounds": [-180, -85.0511, 180, 85.0511], "attribution": ""}))
    return files


NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)


class Registry(unittest.TestCase):
    def setUp(self):
        self.cfg = registry.load_config(os.path.join(HERE, "tilesets.toml"))

    def test_delivered_set(self):
        reg = registry.build(delivered(), self.cfg, now=NOW)
        self.assertEqual(reg["skipped"], [])
        self.assertEqual(reg["warnings"], [])
        ids = [e["id"] for e in reg["tilesets"]]
        self.assertEqual(len(ids), 8)
        # Stacking: basemap at the bottom, the global layer under every region.
        self.assertEqual(ids[0], "horus-basemap")
        self.assertEqual(ids[1], "horus-imagery-global")
        self.assertEqual(set(ids[2:]), {f"horus-imagery-{r}" for r in REGIONS})
        hormuz = next(e for e in reg["tilesets"] if e["id"] == "horus-imagery-hormuz")
        self.assertEqual(hormuz, {
            "id": "horus-imagery-hormuz", "kind": "file", "role": "imagery",
            "title": "Strait of Hormuz imagery (ESA WorldCover 2021)",
            "format": "webp", "type": "raster", "attribution": WORLDCOVER,
            "licence": {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
            "marking": {"classification": "UNCLASSIFIED", "releasability": None},
            "captured": {"start": "2021-01-01", "end": "2021-12-31"},
            "bounds": [52.0, 24.0, 58.0, 28.0], "minzoom": 0, "maxzoom": 14, "order": 114,
            "source": {"path": "s3://bucket/horus/dev/tiles/horus-imagery-hormuz.pmtiles"}})
        basemap = reg["tilesets"][0]
        self.assertEqual((basemap["type"], basemap["order"], basemap["attribution"]),
                         ("vector", 7, "© OpenMapTiles © OpenStreetMap contributors"))

    def test_public_view_hides_paths(self):
        pub = registry.public(registry.build(delivered(), self.cfg, now=NOW))
        self.assertEqual(set(pub), {"version", "generated", "tilesets"})
        self.assertTrue(all("source" not in e for e in pub["tilesets"]))

    def test_file_without_table_is_skipped(self):
        files = delivered() + [("mystery", "s3://b/mystery.pmtiles",
                                {"format": "png", "minzoom": 0, "maxzoom": 5, "bounds": "0,0,1,1",
                                 "attribution": "x"})]
        reg = registry.build(files, self.cfg, now=NOW)
        self.assertIn("mystery", [s[0] for s in reg["skipped"]])
        self.assertNotIn("mystery", [e["id"] for e in reg["tilesets"]])

    def test_missing_file_is_a_warning(self):
        reg = registry.build([f for f in delivered() if f[0] != "horus-imagery-crimea"], self.cfg, now=NOW)
        self.assertIn(("horus-imagery-crimea", "listed in tilesets.toml but no tile file was found"),
                      reg["warnings"])
        self.assertEqual(len(reg["tilesets"]), 7)

    def test_bad_entries_are_skipped_with_reasons(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["tileset"]["horus-imagery-bosporus"]["marking"] = {}
        cfg["tileset"]["horus-imagery-crimea"]["captured"] = "2021-13-01"
        files = delivered()
        files[2] = (files[2][0], files[2][1], dict(files[2][2], bounds="30,40,28,42"))   # west > east
        reg = registry.build(files, cfg, now=NOW)
        reasons = dict(reg["skipped"])
        self.assertIn("marking.classification is required", reasons["horus-imagery-bosporus"])
        self.assertIn("is not YYYY-MM-DD", reasons["horus-imagery-crimea"])
        self.assertIn("are not west < east", reasons[files[2][0]])

    def test_url_entry(self):
        # The commented example in tilesets.toml, enabled.
        with open(os.path.join(HERE, "tilesets.toml")) as f:
            text = f.read()
        block = text[text.index("# [url.customer-ortho-2026]"):]
        enabled = "\n".join(line[2:] if line.startswith("# ") else line for line in block.splitlines())
        cfg = copy.deepcopy(self.cfg)
        cfg.update(tomllib.loads(enabled))
        reg = registry.build(delivered(), cfg, now=NOW)
        url = next(e for e in reg["tilesets"] if e["id"] == "customer-ortho-2026")
        self.assertEqual((url["kind"], url["order"], url["captured"]["start"], url["marking"]["releasability"]),
                         ("url", 119, "2026-03-14", "FVEY"))
        self.assertEqual(url["source"]["credentials"], "CUSTOMER_ORTHO_BASIC_AUTH")
        pub = registry.public(reg)
        self.assertNotIn("CUSTOMER_ORTHO_BASIC_AUTH", str(pub))
        bad = copy.deepcopy(cfg)
        bad["url"]["customer-ortho-2026"]["template"] = "https://x.example/tiles/{z}/{x}.png"
        reasons = dict(registry.build(delivered(), bad, now=NOW)["skipped"])
        self.assertIn("template lacks {y}", reasons["customer-ortho-2026"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
