#!/usr/bin/env python3
"""Checks for run_bucket_e2e.sh: tile files from the bucket served through the signing
proxy, the basemap from a local folder, bad and unservable objects skipped with reasons."""
import gzip
import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:18501"
PROXY = "http://127.0.0.1:18503"      # CDSW_APP_PORT + 2
failures = []


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":   # tileserver compresses tiles
                body = gzip.decompress(body)
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


log = open(sys.argv[1]).read()
status, _, body = get(BASE + "/registry.json")
ids = [t["id"] for t in json.loads(body)["tilesets"]] if status == 200 else []
if ids != ["horus-basemap", "horus-imagery-global", "horus-imagery-hormuz"]:
    failures.append(f"registry ids {ids}: expected the local basemap, then global and hormuz from the bucket")

for id_, z in (("horus-imagery-global", 1), ("horus-imagery-hormuz", 2)):
    status, _, body = get(f"{BASE}/data/{id_}.json")
    tj = json.loads(body) if status == 200 else {}
    if status != 200 or tj.get("format") != "webp":
        failures.append(f"/data/{id_}.json: HTTP {status}, format {tj.get('format')}")
    if id_ == "horus-imagery-global":
        path = "/data/horus-imagery-global/1/1/0.webp"
    else:   # a tile inside the region at z2
        path = "/data/horus-imagery-hormuz/2/2/1.webp"
    for attempt in (1, 2):   # the second comes from the range cache
        status, headers, body = get(BASE + path)
        if status != 200 or body[:4] != b"RIFF":
            failures.append(f"{path} (attempt {attempt}): HTTP {status}, {len(body)} bytes, not WebP")

# The signing proxy itself: byte ranges only, a stable ETag, 404 and 416.
status, h1, body = get(PROXY + "/horus-imagery-global.pmtiles", {"Range": "bytes=0-126"})
if status != 206 or body[:7] != b"PMTiles" or not h1.get("Content-Range", "").startswith("bytes 0-126/"):
    failures.append(f"proxy header range: HTTP {status}, Content-Range {h1.get('Content-Range')}")
_, h2, _ = get(PROXY + "/horus-imagery-global.pmtiles", {"Range": "bytes=0-126"})
if not h1.get("ETag") or h1.get("ETag") != h2.get("ETag"):
    failures.append(f"proxy ETag missing or unstable: {h1.get('ETag')} vs {h2.get('ETag')}")
size = int(h1["Content-Range"].rsplit("/", 1)[1]) if status == 206 else 0
status, h, body = get(PROXY + "/horus-imagery-global.pmtiles", {"Range": f"bytes={size - 10}-{size + 1000}"})
if status != 206 or len(body) != 10:
    failures.append(f"proxy range past the end: HTTP {status}, {len(body)} bytes (expected the last 10)")
status, h, _ = get(PROXY + "/horus-imagery-global.pmtiles", {"Range": f"bytes={size}-"})
if status != 416 or h.get("Content-Range") != f"bytes */{size}":
    failures.append(f"proxy range after the end: HTTP {status}, Content-Range {h.get('Content-Range')}")
status, _, _ = get(PROXY + "/horus-imagery-global.pmtiles")
if status != 416:
    failures.append(f"proxy without a Range header: HTTP {status} (expected 416: whole files are never served)")
for name in ("corrupt", "nothing-here"):
    status, _, _ = get(PROXY + f"/{name}.pmtiles", {"Range": "bytes=0-10"})
    if status != 404:
        failures.append(f"proxy /{name}.pmtiles: HTTP {status} (expected 404: not a served tile set)")

for expected in ("store s3a://horus-test/data/horus/test/tiles/: 6 object(s)",
                 "SKIP corrupt (corrupt.pmtiles)",
                 "SKIP horus-imagery-channel (horus-imagery-channel.pmtiles): truncated:",
                 "SKIP horus-imagery-crimea (horus-imagery-crimea.mbtiles): MBTiles can't be read from object storage",
                 "signing proxy on 127.0.0.1:18503: 2 tile file(s)"):
    if expected not in log:
        failures.append(f"log lacks: {expected}")
if "horus-imagery-bosporus (" in log or "SKIP horus-imagery-bosporus" in log:
    failures.append("a file in a subfolder of the prefix was picked up")
if "ERROR" in log or "DENIED" in log:
    failures.append("errors in the log: " + "; ".join(l for l in log.splitlines() if "ERROR" in l or "DENIED" in l))

print("\n".join(f"FAIL {f}" for f in failures) or "ok: bucket store served through the signing proxy")
sys.exit(1 if failures else 0)
