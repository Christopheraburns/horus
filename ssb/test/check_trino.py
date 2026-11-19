#!/usr/bin/env python3
"""provision/lake.py against the local Trino started by run_trino_local.sh."""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "provision"))
import lake  # noqa: E402
import trino  # noqa: E402

CATALOG = "iceberg"


def local_cursor(host, port, user, password, catalog):
    return trino.dbapi.connect(host="localhost", port=18481, user="test", catalog=catalog).cursor()


lake._cursor = local_cursor   # the local Trino has no TLS or passwords
cur = local_cursor(None, None, None, None, CATALOG)


def q(sql):
    cur.execute(sql)
    return cur.fetchall()


import time  # noqa: E402
for _ in range(60):   # wait for a worker, not just the coordinator ("No nodes available")
    try:
        if q("SELECT count(*) FROM system.runtime.nodes WHERE state = 'active'")[0][0] >= 1:
            q("SHOW SCHEMAS FROM iceberg")
            break
    except Exception:  # noqa: BLE001
        pass
    time.sleep(2)


failures = []
logs = []

# 1. A fresh schema: ensure_table creates the v2 table, and again is a no-op.
v = lake.ensure_table("", 0, "", "", CATALOG, "horus_t", "events_iceberg", log=logs.append)
if v != 2:
    failures.append(f"fresh create returned {v}, expected 2")
v = lake.ensure_table("", 0, "", "", CATALOG, "horus_t", "events_iceberg", log=logs.append)
if v != 2:
    failures.append(f"second run returned {v}, expected 2")
ddl = q("SHOW CREATE TABLE iceberg.horus_t.events_iceberg")[0][0]
for want in ("format_version = 2", "partitioning = ARRAY['day(event_time)']",
             "sorted_by = ARRAY['tile_z8 ASC NULLS FIRST','event_time ASC NULLS FIRST']"):
    if want.replace(" ", "") not in ddl.replace(" ", ""):
        failures.append(f"table lacks {want}")
props = dict(q('SELECT key, value FROM iceberg.horus_t."events_iceberg$properties"'))
if props.get("write.parquet.compression-codec", "").lower() != "zstd":
    failures.append(f"compression codec {props.get('write.parquet.compression-codec')!r}, expected zstd")
cols = [r[0] for r in q("SELECT column_name FROM iceberg.information_schema.columns WHERE table_schema = "
                         "'horus_t' AND table_name = 'events_iceberg' ORDER BY ordinal_position")]
flink_cols = json.load(open(os.path.join(HERE, "out", "lake_columns.json")))
if cols != flink_cols:
    failures.append(f"table columns differ from the Flink INSERT:\n  table {cols}\n  flink {flink_cols}")

# 2. A v1 table is detected and left alone.
q("CREATE SCHEMA IF NOT EXISTS iceberg.horus_v1")
q("CREATE TABLE IF NOT EXISTS iceberg.horus_v1.events_iceberg (event_id VARCHAR, asset_id VARCHAR, "
  "event_time TIMESTAMP(6), payload VARCHAR)")
v = lake.ensure_table("", 0, "", "", CATALOG, "horus_v1", "events_iceberg", log=logs.append)
if v != 1:
    failures.append(f"v1 table returned {v}, expected 1")

# 3. Trino's formulas agree with the Flink job's values.
rows = [json.loads(l.strip()[3:-1]) for l in open(os.path.join(HERE, "out", "lake_rows.txt"))
        if l.startswith("+I[")]
values = ", ".join(
    f"('{r['event_id'].replace(chr(39), chr(39) * 2)}', TIMESTAMP '{r['event_time'].replace('T', ' ')[:19]}', "
    f"{r['lat']}, {r['lon']}, {r['tile_z8']}, '{r['obs_hash']}')" for r in rows)
tile = lake.TILE_Z8_SQL.format(lat="lat", lon="lon")
obs = lake.OBS_HASH_SQL.format(event_id="event_id", event_time="CAST(event_time AS TIMESTAMP(6))")
diff = q(f"SELECT event_id, tile, {tile}, hash, {obs} FROM (VALUES {values}) "
         f"AS t(event_id, event_time, lat, lon, tile, hash) "
         f"WHERE tile <> {tile} OR hash <> {obs}")
for d in diff:
    failures.append(f"{d[0]}: Flink tile {d[1]} hash {d[3][:12]}, Trino tile {d[2]} hash {d[4][:12]}")

print("\n".join(f"  {l}" for l in logs))
print(f"  table properties: { {k: v for k, v in props.items() if 'compression' in k or 'format' in k} }")
if failures:
    print("\n".join(f"FAIL {f}" for f in failures))
    sys.exit(1)
print(f"trino: v2 DDL accepted (day partitions, tile_z8 sort, zstd), v1 detected; "
      f"tile_z8 and obs_hash agree with Flink on {len(rows)} rows")
