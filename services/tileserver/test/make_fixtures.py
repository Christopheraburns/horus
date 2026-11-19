#!/usr/bin/env python3
"""Small stand-ins for the delivered tile files, for test/run_e2e.sh.

Writes into the folder given (the test's tile store):
  * the 7 imagery files as tiny WebP MBTiles (z0-2) with the metadata the real
    ones carry (imagery/scripts/finish_mbtiles.py), the global one converted to
    PMTiles so that path is exercised too;
  * three bad files: corrupt.pmtiles (not PMTiles), wrong-format.mbtiles
    (metadata says webp, tiles are PNG) and unlisted.mbtiles (valid, but no
    [tileset] table in tilesets.toml).
Needs Pillow and pmtiles: uv run --no-project --with pillow --with pmtiles python make_fixtures.py DIR
"""
import io
import os
import sqlite3
import sys

from PIL import Image
from pmtiles.convert import mbtiles_to_pmtiles

WORLDCOVER = ("ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) "
              "processed by ESA WorldCover consortium")
REGIONS = {"hormuz": (52, 24, 58, 28), "taiwan-strait": (118, 22, 122, 26), "bosporus": (28, 40, 30, 42),
           "crimea": (32, 44, 37, 46), "channel": (-2, 49, 2, 52), "hampton-roads": (-77.5, 36, -75.5, 38)}
out = sys.argv[1]
os.makedirs(out, exist_ok=True)


def tile(fmt: str, colour) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (256, 256), colour).save(buf, format=fmt)
    return buf.getvalue()


def mbtiles(path: str, meta: dict, data: bytes, maxzoom: int = 2) -> None:
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    db.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
    db.executemany("INSERT INTO metadata VALUES (?, ?)", list(meta.items()))
    for z in range(maxzoom + 1):
        for x in range(2 ** z):
            for y in range(2 ** z):
                db.execute("INSERT INTO tiles VALUES (?, ?, ?, ?)", (z, x, y, data))
    db.commit()
    db.close()


webp = tile("WEBP", (40, 90, 60))
for name, b in REGIONS.items():
    mbtiles(os.path.join(out, f"horus-imagery-{name}.mbtiles"),
            {"name": f"horus-imagery-{name}", "format": "webp", "minzoom": "0", "maxzoom": "2",
             "bounds": ",".join(map(str, b)), "attribution": WORLDCOVER,
             "description": f"Horus offline imagery: {name}"}, webp)
glob_mb = os.path.join(out, "global.tmp.mbtiles")
mbtiles(glob_mb, {"name": "horus-imagery-global", "format": "webp", "minzoom": "0", "maxzoom": "2",
                  "bounds": "-180,-85.0511,180,85.0511", "attribution": WORLDCOVER,
                  "description": "Horus offline imagery: global"}, webp)
pm = os.path.join(out, "horus-imagery-global.pmtiles")
mbtiles_to_pmtiles(glob_mb, pm, maxzoom=2)
os.remove(glob_mb)
# The Python converter writes header maxzoom 0 although the tiles go to z2 (the Go
# `pmtiles convert` used for real files gets it right): set byte 101, the header's maxzoom.
with open(pm, "r+b") as f:
    f.seek(101)
    f.write(bytes([2]))

with open(os.path.join(out, "corrupt.pmtiles"), "wb") as f:
    f.write(b"this is not a PMTiles archive" * 10)
mbtiles(os.path.join(out, "wrong-format.mbtiles"),
        {"name": "wrong", "format": "webp", "minzoom": "0", "maxzoom": "1", "bounds": "0,0,10,10",
         "attribution": "x"}, tile("PNG", (200, 0, 0)), maxzoom=1)
mbtiles(os.path.join(out, "unlisted.mbtiles"),
        {"name": "unlisted", "format": "webp", "minzoom": "0", "maxzoom": "1", "bounds": "0,0,10,10",
         "attribution": "x"}, webp, maxzoom=1)
print("fixtures:", ", ".join(sorted(os.listdir(out))))
