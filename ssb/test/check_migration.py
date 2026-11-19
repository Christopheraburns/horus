#!/usr/bin/env python3
"""provision/migrate_lake.py on the local Trino started by run_migration_local.sh.

Builds a v1 table the way the v1 lake job filled it (its own column rules,
including reading NWS local times as UTC) from v1 and v2 envelopes of the same
samples, migrates it, and checks:
  * rows from v2 payloads equal the v2 Flink job's rows, every column but ingest_time;
  * rows from v1 payloads equal their v2 counterparts where the backfill rules
    say they can (LAKE-SCHEMA.md), and differ only where they say they must;
  * re-running skips copied days, a partly copied day is redone, nothing is lost,
    and the swap leaves a v2 table under the original name and the v1 table kept.
"""
import glob
import json
import math
import os
import sys
import time
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, os.path.join(HERE, "..", "..", "provision"))
os.environ.update({"LAKE_ENGINE": "trino", "HIVE_HOST": "localhost", "HIVE_PORT": "18481",
                   "HIVE_USE_SSL": "false", "HIVE_USER": "test", "HIVE_DATABASE": "horus_m",
                   "LAKE_CATALOG": "iceberg", "HISTORY_BOUNDS_TTL": "0"})
sys.path.insert(0, os.path.join(HERE, "..", "..", "services", "feeds-gateway"))
import history  # noqa: E402  the gateway's lake reader, pointed at this Trino
import lake  # noqa: E402
import migrate_lake  # noqa: E402
import trino  # noqa: E402

CAT, DB, TABLE = "iceberg", "horus_m", "events_iceberg"
FQ = f"{CAT}.{DB}.{TABLE}"
cur = trino.dbapi.connect(host="localhost", port=18481, user="test", catalog=CAT).cursor()
lake._cursor = lambda *a: trino.dbapi.connect(host="localhost", port=18481, user="test", catalog=CAT).cursor()


def run(sql):
    cur.execute(sql)
    return cur.fetchall()


for _ in range(60):   # wait for a worker, not just the coordinator ("No nodes available")
    try:
        if run("SELECT count(*) FROM system.runtime.nodes WHERE state = 'active'")[0][0] >= 1:
            run("SHOW SCHEMAS FROM iceberg")
            break
    except Exception:  # noqa: BLE001
        pass
    time.sleep(2)

failures = []


def fail(msg):
    failures.append(msg)


def lit(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


# ── 1. The v1 table, filled with the v1 job's rules ─────────────────────────
V1_COLUMNS = ("event_id VARCHAR, asset_id VARCHAR, asset_type VARCHAR, lat DOUBLE, lon DOUBLE, "
              "event_time TIMESTAMP(6), ingest_time TIMESTAMP(6), trace_id VARCHAR, ingest_run_id VARCHAR, "
              "source_provider VARCHAR, source_feed VARCHAR, captured_at VARCHAR, schema_version BIGINT, "
              "source_confidence DOUBLE, payload VARCHAR")
run(f"CREATE SCHEMA IF NOT EXISTS {CAT}.{DB}")
run(f"CREATE TABLE {FQ} ({V1_COLUMNS})")

samples = sorted(os.path.basename(p)[:-6] for p in glob.glob(os.path.join(OUT, "v1", "*.jsonl")))
v1_env, v2_env = {}, {}           # trace_id -> (sample, index)
payloads = []
for s in samples:
    for kind, store in (("v1", v1_env), ("v2", v2_env)):
        path = os.path.join(OUT, "v1", f"{s}.jsonl") if kind == "v1" else \
            os.path.join(HERE, "..", "..", "nifi", "test", "out", f"{s}.jsonl")
        for i, line in enumerate(l for l in open(path) if l.strip()):
            env = json.loads(line)
            store[env["trace_id"]] = (s, i)
            payloads.append(line.strip())
payloads.append(payloads[0])     # a duplicate: kept, not lost

V1_JOB = """
SELECT COALESCE(json_extract_scalar(p, '$.entity.source.originalId'), json_extract_scalar(p, '$.entity.id')),
  json_extract_scalar(p, '$.entity.id'), json_extract_scalar(p, '$.entity.entityType'),
  CAST(json_extract_scalar(p, '$.entity.position.lat') AS DOUBLE),
  CAST(json_extract_scalar(p, '$.entity.position.lng') AS DOUBLE),
  CAST(date_parse(substr(replace(replace(json_extract_scalar(p, '$.entity.timestamp'), 'T', ' '), 'Z', ''), 1, 19),
                  '%Y-%m-%d %H:%i:%s') AS TIMESTAMP(6)),
  CAST(current_timestamp AS TIMESTAMP(6)), json_extract_scalar(p, '$.trace_id'),
  json_extract_scalar(p, '$.ingest_run_id'), json_extract_scalar(p, '$.entity.source.provider'),
  json_extract_scalar(p, '$.entity.source.feed'), json_extract_scalar(p, '$.captured_at'),
  CAST(json_extract_scalar(p, '$.schema_version') AS BIGINT),
  CAST(json_extract_scalar(p, '$.entity.source.confidence') AS DOUBLE), p
FROM (VALUES {values}) AS t(p)"""
run(f"INSERT INTO {FQ} " + V1_JOB.format(values=", ".join(f"({lit(p)})" for p in payloads)))
# A row from before the full-payload change: a flat summary payload, columns only.
run(f"INSERT INTO {FQ} VALUES ('old-1', 'old-1', 'VESSEL', 10.0, 20.0, TIMESTAMP '2025-11-17 08:00:00', "
    f"TIMESTAMP '2025-11-17 08:00:01', 'trace-old', 'run-old', 'aisstream.io', 'vessels', "
    f"'2025-11-17T08:00:01Z', 1, 0.9, '{{\"name\": \"OLD SHIP\"}}')")
n_v1 = run(f"SELECT COUNT(*) FROM {FQ}")[0][0]

# The gateway's Time Travel query on the v1 table: names from payload.
WINDOW = (0, 4102444800000)   # 1970 .. 2100
before = sorted((e["asset_id"], e["t"], e["name"]) for e in history._query_window(*WINDOW))
if history._schema_v2():
    fail("gateway took the v1 table for v2")

# ── 2. Migrate: copy, re-run, redo a partial day, swap ──────────────────────
logs = []
if lake.ensure_table("", 0, "", "", CAT, DB, f"{TABLE}_v2", log=logs.append) != 2:
    fail("ensure_table did not create a v2 table")
migrate_lake.copy(run, CAT, DB, TABLE, log=logs.append)
logs.append("-- re-run")
migrate_lake.copy(run, CAT, DB, TABLE, log=logs.append)
if any("copied" in l and "already" not in l for l in logs[logs.index("-- re-run"):]):
    fail("re-run copied a day again")
run(f"DELETE FROM {FQ}_v2 WHERE source_provider = 'USGS'")       # a partly copied day
logs.append("-- after partial delete")
migrate_lake.copy(run, CAT, DB, TABLE, log=logs.append)
if not any("partial" in l for l in logs[logs.index("-- after partial delete"):]):
    fail("a partly copied day was not detected")
migrate_lake.swap(run, CAT, DB, TABLE, log=logs.append)
print("\n".join(f"  {l}" for l in logs))

if lake.schema_version(cur, CAT, DB, TABLE) != 2:
    fail("after the swap the table is not v2")
if lake.schema_version(cur, CAT, DB, f"{TABLE}_v1") != 1:
    fail("after the swap the v1 table is not kept")
n_v2 = run(f"SELECT COUNT(*) FROM {FQ}")[0][0]
if n_v2 != n_v1:
    fail(f"{n_v1} v1 rows, {n_v2} v2 rows")

# The same query after the swap: v2 detected without a restart, display_name used,
# same assets and names (times differ only where the backfill corrected them: NWS).
history._reset_conn()
after = history._query_window(*WINDOW)
if not history._schema_v2():
    fail("gateway did not detect the v2 table after the swap")
names_before = sorted((a, n) for a, _, n in before)
names_after = sorted((e["asset_id"], e["name"]) for e in after)
if names_before != names_after:
    fail(f"Time Travel names changed across the swap:\n  before {names_before}\n  after  {names_after}")

# ── 3. Compare rows ──────────────────────────────────────────────────────────
cols = migrate_lake.COLUMN_NAMES
rows = [dict(zip(cols, r)) for r in run(f"SELECT {', '.join(cols)} FROM {FQ}")]
flink = {}
for line in open(os.path.join(OUT, "lake_rows.txt")):
    if line.startswith("+I["):
        r = json.loads(line.strip()[3:-1])
        flink[r["obs_hash"]] = r
flink_by_trace = {r["trace_id"]: r for r in flink.values()}


def norm(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, str) and len(v) >= 19 and v[4] == "-" and v[10] in "T ":
        return v.replace("T", " ")[:19]
    return v


def same(a, b):
    a, b = norm(a), norm(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)
    return a == b


# v2 payloads: identical to the Flink job, column for column.
checked_v2 = 0
for r in rows:
    if r["trace_id"] in v2_env:
        f = flink.get(r["obs_hash"])
        if f is None:
            fail(f"v2 row {r['event_id']}: no Flink row with obs_hash {r['obs_hash'][:12]}")
            continue
        for c in cols:
            if c not in ("ingest_time", "payload") and not same(r[c], f.get(c)):
                fail(f"v2 row {r['event_id']}: {c} = {r[c]!r}, Flink {f.get(c)!r}")
        checked_v2 += 1

# v1 payloads: equal to the v2 row of the same sample input, except where the
# backfill rules say a v1 row can't know (LAKE-SCHEMA.md).
v2_rows_by_pos = {v2_env[r["trace_id"]]: r for r in rows if r["trace_id"] in v2_env}
EXPECTED_DIFF = {
    "event_time": {"aisstream", "adsblol"},       # v1 stamped NiFi's receive time
    "obs_hash": {"aisstream", "adsblol"},
    "asset_subtype": {"usgs"},                     # v1 USGS has no type
    "heading_deg": {"hormuz"},                     # v1 hormuz heading fell back to course
    "geom_wkt": {"nws"}, "bbox_min_lon": {"nws"}, "bbox_min_lat": {"nws"},
    "bbox_max_lon": {"nws"}, "bbox_max_lat": {"nws"},
}
# v1 flights stored the track rounded to whole degrees (a missing track as 0) and
# speed rounded to 0.1 knot, and no true heading: equal within that precision.
FLIGHT_TOLERANCE = {"course_deg": 0.5, "speed_mps": 0.05 * 0.514444 + 1e-9}
EXPECTED_DIFF["heading_deg"] |= {"adsblol", "opensky"}
SKIP = {"trace_id", "ingest_run_id", "ingest_time", "captured_at", "payload", "schema_version", "releasability"}
checked_v1 = 0
for r in rows:
    if r["trace_id"] not in v1_env:
        continue
    pos = v1_env[r["trace_id"]]
    twin = v2_rows_by_pos.get(pos)
    if twin is None:
        fail(f"v1 row {r['event_id']} ({pos}): no v2 row for the same input")
        continue
    checked_v1 += 1
    for c in cols:
        if c in SKIP:
            continue
        expected_to_differ = any(pos[0].startswith(p) for p in EXPECTED_DIFF.get(c, ()))
        if r["asset_type"] == "FLIGHT" and c in FLIGHT_TOLERANCE:
            if c == "course_deg" and r[c] == 0 and twin[c] is None:
                continue   # v1 stored a missing track as 0
            if r[c] is not None and twin[c] is not None and abs(r[c] - twin[c]) <= FLIGHT_TOLERANCE[c]:
                continue
        if not expected_to_differ and not same(r[c], twin[c]):
            fail(f"v1 row {r['event_id']} ({pos[0]}): {c} = {r[c]!r}, v2 {twin[c]!r}")

old = next((r for r in rows if r["trace_id"] == "trace-old"), None)
if old is None or old["display_name"] != "OLD SHIP" or old["event_id"] != "aisstream.io:old-1" \
        or old["bbox_min_lat"] != 10.0 or old["id_scheme"] != "mmsi":
    fail(f"flat-payload row not migrated as expected: {old}")

if failures:
    print("\n".join(f"FAIL {f}" for f in failures))
    sys.exit(1)
print(f"gateway: Time Travel gives the same {len(after)} assets and names before and after the swap, "
      f"from payload on v1 and display_name on v2")
print(f"migration: {n_v1} rows kept; {checked_v2} v2-payload rows equal the Flink job's, "
      f"{checked_v1} v1-payload rows match their v2 twins; re-run, partial-day redo and swap work")
