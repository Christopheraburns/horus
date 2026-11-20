"""Find the tile files in the tile store and read what each says about itself (burndown 8.3).

For each MBTiles or PMTiles file: its metadata (name, format, zooms, bounds,
attribution) in the plain form registry.build() takes, and the problems that
make it unservable. A file with problems is skipped with a log line; it never
stops the tile server.

Checks: the metadata is there; the first tile's bytes are the declared format
(so raster and vector can't be mixed up); bounds and zooms are valid Web
Mercator values; PMTiles is version 3 with readable metadata.

PMTiles is read through ``read(offset, length)`` only, so the same code reads a
local file now and S3 range requests through the signing proxy later (8.9).
Standard library only.
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
import struct
from typing import Callable, Optional

EXTENSIONS = (".pmtiles", ".mbtiles")
MERCATOR_LAT = 85.0511287798
# PMTiles v3 header fields (https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md).
PMTILES_HEADER = 127
PMTILES_TILE_TYPES = {1: "pbf", 2: "png", 3: "jpg", 4: "webp", 5: "avif"}
PMTILES_COMPRESSION = {0: "unknown", 1: "none", 2: "gzip", 3: "brotli", 4: "zstd"}


def discover(folder: str) -> list[tuple[str, str]]:
    """(id, path) for each tile file in a folder; the id is the file name without its extension."""
    out = []
    for name in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(name)
        if ext.lower() in EXTENSIONS and os.path.isfile(os.path.join(folder, name)):
            out.append((stem, os.path.join(folder, name)))
    return out


def sniff(data: bytes) -> Optional[str]:
    """The format of one tile from its first bytes."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:2] == b"\x1f\x8b":
        return "pbf"          # vector tiles are stored gzipped
    if data[:1] == b"\x1a":
        return "pbf"          # an uncompressed vector tile starts with a layer (field 3)
    return None


def _check_common(meta: dict, problems: list) -> None:
    for key in ("format", "minzoom", "maxzoom", "bounds"):
        if meta.get(key) in (None, ""):
            problems.append(f"metadata has no {key}")
    b = meta.get("bounds")
    if isinstance(b, list) and len(b) == 4:
        w, s, e, n = b
        if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
            problems.append(f"bounds {b} are not west < east within ±180 and south < north within ±90")
        else:
            # Many tools write ±90 for a world layer; Web Mercator tiles stop at ±85.05.
            meta["bounds"] = [w, max(s, -MERCATOR_LAT), e, min(n, MERCATOR_LAT)]
    lo, hi = meta.get("minzoom"), meta.get("maxzoom")
    if isinstance(lo, int) and isinstance(hi, int) and not 0 <= lo <= hi <= 24:
        problems.append(f"zooms {lo} to {hi} are not 0 <= min <= max <= 24")


def read_mbtiles(path: str) -> tuple[dict, list]:
    problems: list = []
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return {}, [f"not readable as SQLite ({e})"]
    try:
        try:
            raw = dict(db.execute("SELECT name, value FROM metadata"))
        except sqlite3.DatabaseError as e:
            return {}, [f"no MBTiles metadata table ({e})"]
        meta: dict = {"name": raw.get("name"), "attribution": raw.get("attribution"),
                      "description": raw.get("description")}
        # MBTiles tiles are Web Mercator by definition; refuse a file that says otherwise.
        crs = (raw.get("crs") or raw.get("srs") or "").upper()
        if crs and not any(c in crs for c in ("3857", "900913", "MERCATOR")):
            problems.append(f"metadata says its projection is {crs}; the map needs Web Mercator (EPSG:3857)")
        fmt = (raw.get("format") or "").lower()
        meta["format"] = {"jpeg": "jpg", "mvt": "pbf"}.get(fmt, fmt) or None
        try:
            meta["bounds"] = [float(v) for v in raw["bounds"].split(",")] if raw.get("bounds") else None
        except ValueError:
            problems.append(f"bounds {raw.get('bounds')!r} are not four numbers")
        try:
            row = db.execute("SELECT MIN(zoom_level), MAX(zoom_level) FROM tiles").fetchone()
            tile = db.execute("SELECT tile_data FROM tiles LIMIT 1").fetchone()
        except sqlite3.DatabaseError as e:
            return meta, [f"no MBTiles tiles table ({e})"]
        if tile is None:
            return meta, ["contains no tiles"]
        # The tiles say which zooms really exist; metadata only fills in when they agree.
        for key, have in (("minzoom", row[0]), ("maxzoom", row[1])):
            stated = raw.get(key)
            meta[key] = int(stated) if str(stated or "").lstrip("-").isdigit() else have
            if meta[key] != have:
                problems.append(f"metadata {key} {meta[key]} but the tiles' {key} is {have}")
        found = sniff(bytes(tile[0]))
        if meta["format"] and found and found != meta["format"]:
            problems.append(f"metadata format is {meta['format']} but the tiles are {found}")
        elif found is None:
            problems.append("the first tile is not PNG, JPEG, WebP or a vector tile")
        _check_common(meta, problems)
        return meta, problems
    finally:
        db.close()


def file_reader(path: str) -> Callable[[int, int], bytes]:
    def read(offset: int, length: int) -> bytes:
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read(length)
    return read


def read_pmtiles(read: Callable[[int, int], bytes], size: Optional[int] = None) -> tuple[dict, list]:
    """``size``: the file's length, when known; a file shorter than its header says is
    truncated (an incomplete upload) and its tiles would be served from the wrong bytes."""
    head = read(0, PMTILES_HEADER)
    if len(head) < PMTILES_HEADER or head[:7] != b"PMTiles":
        return {}, ["not a PMTiles file (no PMTiles header)"]
    if head[7] != 3:
        return {}, [f"PMTiles version {head[7]}; only version 3 is supported"]
    meta_offset, meta_length = struct.unpack_from("<QQ", head, 24)
    internal, tile_type = head[97], head[99]
    minzoom, maxzoom = head[100], head[101]
    w, s, e, n = (v / 1e7 for v in struct.unpack_from("<iiii", head, 102))
    problems: list = []
    # Header sections: root directory, metadata, leaf directories, tile data (offset, length).
    end = max(o + n for o, n in (struct.unpack_from("<QQ", head, at) for at in (8, 24, 40, 56)))
    if size is not None and size < end:
        return {}, [f"truncated: the file is {size:,} bytes but its header says {end:,} "
                    f"({end - size:,} missing; an incomplete upload?)"]
    meta: dict = {"format": PMTILES_TILE_TYPES.get(tile_type), "minzoom": minzoom, "maxzoom": maxzoom,
                  "bounds": [w, s, e, n]}
    if meta["format"] is None:
        problems.append(f"PMTiles tile type {tile_type} is unknown")
    elif meta["format"] == "avif":
        problems.append("AVIF tiles are not supported by the map")
    body = read(meta_offset, meta_length) if meta_length else b""
    try:
        if internal == 2:
            body = gzip.decompress(body)
        elif internal not in (0, 1):
            raise ValueError(f"metadata is {PMTILES_COMPRESSION.get(internal, internal)}-compressed; "
                             "write PMTiles with gzip metadata (pmtiles convert does)")
        extra = json.loads(body or b"{}")
    except (OSError, ValueError) as err:
        problems.append(f"PMTiles metadata unreadable ({err})")
        extra = {}
    meta.update({"name": extra.get("name"), "attribution": extra.get("attribution"),
                 "description": extra.get("description")})
    # A converted MBTiles keeps its zooms in the metadata; a header that disagrees means a
    # bad conversion (seen with the Python pmtiles converter: header maxzoom 0, tiles to z2).
    for key, have in (("minzoom", minzoom), ("maxzoom", maxzoom)):
        stated = str(extra.get(key, "")).strip()
        if stated.isdigit() and int(stated) != have:
            problems.append(f"PMTiles header {key} is {have} but its metadata says {stated}, so the map "
                            f"would use z{have}; long runs of identical tiles can cause this in conversion")
    _check_common(meta, problems)
    return meta, problems


def read_metadata(path: str) -> tuple[dict, list]:
    """(metadata, problems) for one local tile file."""
    try:
        if os.path.getsize(path) == 0:
            return {}, ["empty file"]
        if path.lower().endswith(".pmtiles"):
            return read_pmtiles(file_reader(path), os.path.getsize(path))
        return read_mbtiles(path)
    except OSError as e:
        return {}, [f"unreadable ({e})"]


def main(argv: list) -> int:
    """Check tile files as the tile service will: python3 tilestore.py FILE [FILE ...]."""
    bad = 0
    for path in argv:
        meta, problems = read_metadata(path)
        name = os.path.basename(path)
        if problems:
            bad += 1
            print(f"FAIL {name}: {'; '.join(problems)}")
        else:
            print(f"ok   {name}: {meta['format']}, z{meta['minzoom']}-{meta['maxzoom']}, bounds {meta['bounds']}")
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
