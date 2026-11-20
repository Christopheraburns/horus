#!/usr/bin/env python3
"""Checks for run_raw_flink_local.sh: the rows the raw capture job would write."""
import hashlib
import sys

lines = [l for l in open(sys.argv[1]).read().splitlines() if "+I[" in l]
rows = [l.split("+I[", 1)[1].rstrip("]").split(", ") for l in lines]
failures = []
by_flow = {}
for r in rows:
    by_flow.setdefault(r[0], []).append(r)
if sorted(by_flow) != ["aisstream", "firms", "nws", "usgs"]:
    failures.append(f"flows {sorted(by_flow)}")
if len(by_flow.get("nws", [])) != 1:
    failures.append(f"the repeated NWS body was stored {len(by_flow.get('nws', []))} times, expected once")
u = by_flow.get("usgs", [[None] * 11])[0]
body = '{"type":"FeatureCollection","features":[]}'
want = {1: "https://earthquake.usgs.gov/x.geojson", 2: "200", 3: "application/json",
        6: hashlib.sha256(body.encode()).hexdigest(), 7: str(len(body))}
for i, v in want.items():
    if u[i] != v:
        failures.append(f"usgs column {i}: {u[i]!r}, expected {v!r}")
if not (u[4] or "").startswith("20"):
    failures.append(f"usgs received_at {u[4]!r} is not a timestamp")
f = by_flow.get("firms", [[None] * 11])[0]
if f[2] != "503":
    failures.append(f"firms http_status {f[2]!r}, expected 503 (failed fetches are kept too)")
a = by_flow.get("aisstream", [[None] * 11])[0]
if a[1] != "null" or a[2] != "null":
    failures.append(f"aisstream without headers: url {a[1]!r}, status {a[2]!r}, expected null")
if "é" not in ", ".join(a):
    failures.append("aisstream body lost its non-ASCII characters")
print("\n".join(f"FAIL {x}" for x in failures) or
      f"ok: raw job read key, headers, timestamp and body for {len(rows)} rows; the repeated body stored once")
sys.exit(1 if failures else 0)
