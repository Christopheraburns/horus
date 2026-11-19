#!/usr/bin/env python3
"""Compare the lake job's rows (run_lake_local.sh) with a Python reference.

The reference implements docs/LAKE-SCHEMA.md directly: event_id, obs_hash and
tile_z8 by their formulas, every other column from its envelope path. Exits 1 on
any difference, a missing row, or a duplicate that wasn't dropped.
"""
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def get(d, path):
    for k in path.split("."):
        if isinstance(d, list):
            d = d[int(k)] if int(k) < len(d) else None
        elif isinstance(d, dict):
            d = d.get(k)
        else:
            return None
    return d


def tile_z8(lat, lon):
    lat_c = max(min(lat, 85.0511287798), -85.0511287798)
    x = min(max(math.floor((lon + 180) / 360 * 256), 0), 255)
    r = math.radians(lat_c)
    y = min(max(math.floor((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 256), 0), 255)
    return x * 256 + y


def ts(s):
    return s[:19].replace("T", " ").replace("Z", "") if s else None


def reference(env):
    e = env["entity"]
    provider = get(e, "source.provider") or "unknown"
    event_id = f"{provider}:{get(e, 'source.originalId') or e['id']}"
    t = ts(e["timestamp"])
    ms = int(datetime.strptime(t, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()) * 1000
    lat, lon = get(e, "position.lat"), get(e, "position.lng")
    bbox = e.get("bbox") or [lon, lat, lon, lat]
    f = lambda v: None if v is None else float(v)
    return {
        "event_id": event_id,
        "obs_hash": hashlib.sha256(f"{event_id}|{ms}".encode()).hexdigest(),
        "asset_id": e["id"], "id_scheme": get(e, "source.idScheme"), "asset_type": e.get("entityType"),
        "asset_subtype": e.get("subtype"), "display_name": e.get("name"),
        "lat": f(lat), "lon": f(lon), "alt_m": f(get(e, "position.alt")), "tile_z8": tile_z8(lat, lon),
        "geom_wkt": e.get("geometry"),
        "bbox_min_lon": f(bbox[0]), "bbox_min_lat": f(bbox[1]), "bbox_max_lon": f(bbox[2]), "bbox_max_lat": f(bbox[3]),
        "speed_mps": f(get(e, "motion.speedMps")), "course_deg": f(get(e, "motion.courseDeg")),
        "heading_deg": f(get(e, "motion.headingDeg")),
        "event_time": t, "captured_at": ts(env.get("captured_at")),
        "source_provider": provider, "source_feed": get(e, "source.feed"),
        "source_confidence": f(get(e, "source.confidence")),
        "classification": e.get("classification"), "releasability": e.get("releasability"),
        "trace_id": env.get("trace_id"), "ingest_run_id": env.get("ingest_run_id"),
        "schema_version": env.get("schema_version"),
    }


def same(col, want, got):
    if col in ("event_time", "captured_at") and isinstance(got, str):
        got = got.replace("T", " ")[:19]
    if isinstance(want, float) and isinstance(got, (int, float)):
        return math.isclose(want, got, rel_tol=1e-12, abs_tol=1e-9)
    return want == got


expected = {}
for line in open(os.path.join(OUT, "lake_input.jsonl")):
    row = reference(json.loads(line))
    expected.setdefault(row["obs_hash"], row)

got = {}
duplicates = 0
for line in open(os.path.join(OUT, "lake_rows.txt")):
    line = line.strip()
    if not line.startswith("+I["):
        print(line)
        continue
    row = json.loads(line[3:-1])
    duplicates += row["obs_hash"] in got
    got[row["obs_hash"]] = row

failures = []
if not got:
    failures.append("no rows from Flink (see the output above)")
if duplicates:
    failures.append(f"{duplicates} duplicate rows were not dropped")
for h, want in expected.items():
    row = got.get(h)
    if row is None:
        failures.append(f"missing row {want['event_id']} at {want['event_time']}")
        continue
    for col, v in want.items():
        if col == "ingest_time":
            continue
        if not same(col, v, row.get(col)):
            failures.append(f"{want['event_id']}: {col} = {row.get(col)!r}, expected {v!r}")
for h in set(got) - set(expected):
    failures.append(f"unexpected row {got[h]['event_id']}")
missing_cols = set(json.load(open(os.path.join(OUT, "lake_columns.json")))) - {"payload", "ingest_time"} - set(
    next(iter(expected.values())))
if missing_cols:
    failures.append(f"job columns the reference doesn't check: {sorted(missing_cols)}")

if failures:
    print("\n".join(f"FAIL {f}" for f in failures))
    sys.exit(1)
print(f"lake job: {len(got)} rows match the reference ({len(expected)} expected, duplicate dropped)")
