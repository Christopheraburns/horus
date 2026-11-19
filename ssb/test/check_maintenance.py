#!/usr/bin/env python3
"""provision/lake_maintenance.py on the local Trino started by run_maintenance_local.sh.

Writes three finished days and today as many small unsorted files (positions
spread over the world), then checks that maintenance compacts the finished
days, leaves today alone, writes the files in tile order so a bounding-box
query overlaps far fewer files (burndown 16.7), keeps every row, runs the
snapshot and orphan clean-up, and finds nothing to do the second time.
"""
import os
import random
import sys
import time
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "provision"))
import lake  # noqa: E402
import lake_maintenance as lm  # noqa: E402
import trino  # noqa: E402

CAT, DB, TABLE = "iceberg", "horus_mt", "events_iceberg"
FQ = f"{CAT}.{DB}.{TABLE}"
TODAY = "2026-11-19"
FINISHED = ["2026-11-16", "2026-11-17", "2026-11-18"]
# Small files so a compacted day still makes several files and the order inside them shows.
TARGET = 1024 * 1024


class RetryCursor:
    """A cursor that retries "No nodes available": single-node Trino needs a few seconds
    after start-up before it schedules queries on a catalog."""

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql):
        for attempt in range(10):
            try:
                return self._cur.execute(sql)
            except trino.exceptions.TrinoQueryError as e:
                if "NO_NODES_AVAILABLE" not in str(e) or attempt == 9:
                    raise
                time.sleep(3)

    def __getattr__(self, name):
        return getattr(self._cur, name)


def connect():
    return RetryCursor(trino.dbapi.connect(host="localhost", port=18481, user="t", catalog=CAT,
                               session_properties={"iceberg.target_max_file_size": "1MB",
                                                   # files can only end between row groups
                                                   "iceberg.parquet_writer_block_size": "256kB"}).cursor())


lake._cursor = lambda *a: connect()
cur = connect()


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
lake.ensure_table("", 0, "", "", CAT, DB, TABLE, log=lambda m: None)

# Hormuz: the bounding box used for the file-skipping check.
BOX = (24.0, 54.0, 28.5, 59.0)   # min lat, min lon, max lat, max lon
random.seed(7)
for day in FINISHED + [TODAY]:
    for batch in range(15):                     # 15 inserts = 15+ small files per day
        rows = []
        for j in range(1000):
            if j % 100 == 0:                     # a few positions inside the box
                lat, lon = random.uniform(BOX[0], BOX[2]), random.uniform(BOX[1], BOX[3])
            else:
                lat, lon = random.uniform(-60, 70), random.uniform(-180, 180)
            rows.append(f"('e-{day}-{batch}-{j}', {lat}, {lon}, TIMESTAMP '{day} {j % 24:02d}:{batch:02d}:00')")
        # Payload: ~640 hex characters from hashes, generated in Trino (incompressible like real
        # payloads, without sending megabytes of SQL).
        payload = " || ".join(f"to_hex(sha256(to_utf8(id || '{k}')))" for k in range(10))
        tile = lake.TILE_Z8_SQL.format(lat="la", lon="lo")
        run(f"INSERT INTO {FQ} (event_id, lat, lon, tile_z8, bbox_min_lat, bbox_min_lon, bbox_max_lat, "
            f"bbox_max_lon, event_time, payload) "
            f"SELECT id, la, lo, {tile}, la, lo, la, lo, t, {payload} "
            f"FROM (VALUES {', '.join(rows)}) AS v(id, la, lo, t)")


# Iceberg field ids follow the table's column order (1-based), as lake.COLUMNS lists it.
FIELD_ID = {line.split()[0]: i + 1 for i, line in enumerate(lake.COLUMNS.strip().splitlines())}


def files_touching_box(day):
    """Files of one day whose lat/lon bounds overlap the box: what a bbox query must read."""
    rows = run(f'SELECT file_path, lower_bounds, upper_bounds FROM {CAT}.{DB}."{TABLE}$files"')
    total = hit = 0
    for path, lo, hi in rows:
        if f"event_time_day={day}/" not in path:
            continue
        lat_lo, lat_hi = float(lo[FIELD_ID["lat"]]), float(hi[FIELD_ID["lat"]])
        lon_lo, lon_hi = float(lo[FIELD_ID["lon"]]), float(hi[FIELD_ID["lon"]])
        total += 1
        if not (lat_hi < BOX[0] or lat_lo > BOX[2] or lon_hi < BOX[1] or lon_lo > BOX[3]):
            hit += 1
    return hit, total


def in_box():
    return run(f"SELECT COUNT(*) FROM {FQ} WHERE lat BETWEEN {BOX[0]} AND {BOX[2]} "
               f"AND lon BETWEEN {BOX[1]} AND {BOX[3]}")[0][0]


rows_before = run(f"SELECT COUNT(*) FROM {FQ}")[0][0]
box_rows_before = in_box()
skip_before = files_touching_box(FINISHED[0])
today_files_before = next(p[1] for p in lm.partitions(run, FQ) if p[0] == TODAY)

logs = []
planned = lm.maintain(run, FQ, apply=False, log=logs.append, today=TODAY, target=TARGET)
if planned["days"] != FINISHED:
    failures.append(f"plan {planned['days']}, expected {FINISHED}")
result = lm.maintain(run, FQ, apply=True, log=logs.append, today=TODAY, target=TARGET)
again = lm.maintain(run, FQ, apply=False, log=logs.append, today=TODAY, target=TARGET)
print("\n".join(f"  {l}" for l in logs))

parts = {p[0]: p for p in lm.partitions(run, FQ)}
for day in FINISHED:
    files, size = parts[day][1], parts[day][2]
    if files > lm.SLACK * lm.files_needed(size, TARGET):
        failures.append(f"{day} still has {files} files for {size} bytes")
if parts[TODAY][1] != today_files_before:
    failures.append(f"today went from {today_files_before} to {parts[TODAY][1]} files; it should be left alone")
if run(f"SELECT COUNT(*) FROM {FQ}")[0][0] != rows_before:
    failures.append("row count changed")
if in_box() != box_rows_before:
    failures.append("rows in the box changed")
if again["days"]:
    failures.append(f"a second pass still wants to compact {again['days']}")

skip_after = files_touching_box(FINISHED[0])
print(f"  bbox {BOX}: {skip_before[0]} of {skip_before[1]} files overlap before, "
      f"{skip_after[0]} of {skip_after[1]} after")
# Order inside the compacted files and row-group skipping: check_sorted_files.py reads the
# files directly (Trino reads row groups in parallel, so it can't show file order).

if failures:
    print("\n".join(f"FAIL {f}" for f in failures))
    sys.exit(1)
print(f"maintenance: {result['files_before']} -> {result['files_after']} files, today untouched, rows kept, "
      f"second pass idle; {skip_before[1]} files per finished day became {skip_after[1]}")
