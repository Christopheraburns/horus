"""Finish a GDAL-written raster MBTiles: build the missing low zooms and set
the metadata Horus expects.

  python3 finish_mbtiles.py FILE.mbtiles NAME [--quality 85]

gdaladdo stops once the whole raster fits in one tile, so a region file starts
at about z5-8. This builds every zoom below that, down to z0, by averaging
2 x 2 child tiles (premultiplied alpha, like gdaladdo -r average), so each
file stands alone. Then it sets name, description, minzoom, maxzoom and
attribution. Runs inside the GDAL container (PIL has WebP).
"""
import argparse
import io
import sqlite3

from PIL import Image

ATTRIBUTION = ("ESA WorldCover project 2021 / Contains modified Copernicus "
               "Sentinel data (2021) processed by ESA WorldCover consortium")


def decode(blob):
    return Image.open(io.BytesIO(blob)).convert("RGBA")


def encode(img, fmt, quality):
    buf = io.BytesIO()
    if fmt == "webp":
        img.save(buf, "WEBP", quality=quality, method=6)
    else:  # jpg: no alpha
        img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def build_level(db, z, fmt, quality):
    """Build zoom z from z + 1. Rows are TMS (row 0 at the south)."""
    children = db.execute(
        "SELECT tile_column, tile_row, tile_data FROM tiles WHERE zoom_level = ?",
        (z + 1,)).fetchall()
    parents = {}
    for col, row, data in children:
        parents.setdefault((col // 2, row // 2), []).append((col, row, data))
    for (pc, pr), kids in parents.items():
        canvas = Image.new("RGBa", (512, 512), (0, 0, 0, 0))
        for col, row, data in kids:
            dx = (col - 2 * pc) * 256
            dy = (1 - (row - 2 * pr)) * 256   # higher TMS row = north = top
            canvas.paste(decode(data).convert("RGBa"), (dx, dy))
        img = canvas.resize((256, 256), Image.BOX).convert("RGBA")
        if img.getchannel("A").getextrema()[1] == 0:
            continue  # fully transparent
        db.execute("INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?)",
                   (z, pc, pr, encode(img, fmt, quality)))
    return len(parents)


def set_meta(db, key, value):
    db.execute("DELETE FROM metadata WHERE name = ?", (key,))
    db.execute("INSERT INTO metadata (name, value) VALUES (?, ?)", (key, str(value)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("name")
    ap.add_argument("--quality", type=int, default=85)
    a = ap.parse_args()

    db = sqlite3.connect(a.file)
    meta = dict(db.execute("SELECT name, value FROM metadata"))
    fmt = meta.get("format", "webp")
    zmin, zmax = db.execute(
        "SELECT MIN(zoom_level), MAX(zoom_level) FROM tiles").fetchone()
    for z in range(zmin - 1, -1, -1):
        n = build_level(db, z, fmt, a.quality)
        print(f"  built z{z}: {n} tiles")
    db.commit()

    set_meta(db, "name", a.name)
    set_meta(db, "description", f"Horus offline imagery: {a.name}")
    set_meta(db, "minzoom", 0)
    set_meta(db, "maxzoom", zmax)
    set_meta(db, "attribution", ATTRIBUTION)
    db.commit()
    for k, v in db.execute("SELECT name, value FROM metadata ORDER BY name"):
        print(f"  {k} = {v}")
    for z, n in db.execute(
            "SELECT zoom_level, COUNT(*) FROM tiles GROUP BY zoom_level"):
        print(f"  z{z}: {n} tiles")
    db.execute("VACUUM")
    db.close()


if __name__ == "__main__":
    main()
