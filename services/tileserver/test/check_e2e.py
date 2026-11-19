#!/usr/bin/env python3
"""Checks for run_e2e.sh: the registry, TileJSON and tiles through the front proxy, and the
bad files reported and skipped in the log."""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:18491"
EXPECTED = ["horus-basemap", "horus-imagery-global", "horus-imagery-bosporus", "horus-imagery-channel",
            "horus-imagery-crimea", "horus-imagery-hampton-roads", "horus-imagery-hormuz",
            "horus-imagery-taiwan-strait"]
failures = []


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


status, headers, body = get("/registry.json")
reg = json.loads(body) if status == 200 else {}
ids = [t["id"] for t in reg.get("tilesets", [])]
# Bottom to top: basemap, then the world imagery, then the regions (they don't overlap, so
# their order among themselves doesn't matter).
if ids[:2] != EXPECTED[:2] or set(ids[2:]) != set(EXPECTED[2:]):
    failures.append(f"registry ids {ids}: expected the basemap, the global layer, then the six regions")
if headers.get("Access-Control-Allow-Origin") != "*":
    failures.append("registry.json has no CORS header")
if "source" in json.dumps(reg):
    failures.append("registry.json exposes source paths")

for id_ in EXPECTED:
    status, _, body = get(f"/data/{id_}.json")
    tj = json.loads(body) if status == 200 else {}
    if status != 200 or not tj.get("tiles"):
        failures.append(f"/data/{id_}.json: HTTP {status}, tiles {tj.get('tiles')}")

for path, ctype in (("/data/horus-imagery-hormuz/0/0/0.webp", "image/webp"),         # MBTiles
                    ("/data/horus-imagery-global/1/1/1.webp", "image/webp"),         # PMTiles
                    ("/data/horus-basemap/0/0/0.pbf", "application/x-protobuf")):    # the real basemap
    status, headers, body = get(path)
    if status != 200 or not headers.get("Content-Type", "").startswith(ctype) or not body:
        failures.append(f"{path}: HTTP {status}, {headers.get('Content-Type')}, {len(body)} bytes")
    if headers.get("Access-Control-Allow-Origin") is None:
        failures.append(f"{path}: no CORS header through the front proxy")

status, _, body = get("/styles/dark/style.json")
style = json.loads(body) if status == 200 else {}
src = json.dumps(style.get("sources", {}))
if status != 200 or "/data/horus-basemap.json" not in src:
    failures.append(f"dark style: HTTP {status}, sources {src[:120]}")

for id_ in ("unlisted", "wrong-format", "corrupt"):
    if get(f"/data/{id_}.json")[0] != 404:
        failures.append(f"/data/{id_}.json is served; it should be skipped")

log = open(sys.argv[1]).read()
for needle in ("SKIP corrupt", "not a PMTiles file", "SKIP wrong-format", "tiles are png",
               "SKIP unlisted", "no [tileset] table"):
    if needle not in log:
        failures.append(f"log lacks {needle!r}")

if failures:
    print("\n".join(f"FAIL {f}" for f in failures))
    sys.exit(1)
print(f"tile service: registry of {len(ids)} served through the front proxy; TileJSON for all {len(EXPECTED)}; "
      "MBTiles, PMTiles and the real basemap tiles served with CORS; dark style on horus-basemap; "
      "corrupt, wrong-format and unlisted files reported and skipped")
