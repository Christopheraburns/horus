#!/usr/bin/env python3
"""The bronze table (burndown 17.4, 17.5) on the local Trino started by run_raw_local.sh.

Checks: lake.ensure_raw_table creates raw_responses (and is safe to re-run); its
columns are exactly what ssb/05_raw_to_iceberg.sql inserts, in order; maintenance
deletes whole days older than the retention, compacts finished days, leaves today
alone and keeps every other row; a second pass has nothing to do.
"""
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "provision"))
sys.path.insert(0, HERE)
import lake  # noqa: E402
import lake_maintenance as lm  # noqa: E402
import time  # noqa: E402

import trino  # noqa: E402


class RetryCursor:
    """Retries "No nodes available" while single-node Trino finishes starting."""

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


def _connect():
    return RetryCursor(trino.dbapi.connect(host="localhost", port=18481, user="t", catalog=CAT).cursor())

CAT, DB = "iceberg", "horus_raw"
FQ = f"{CAT}.{DB}.{lake.RAW_TABLE}"
TODAY = "2026-11-20"
KEEP = 30
# Old enough to delete (before 2026-10-21), finished and kept, and today.
OLD = ["2026-10-01", "2026-10-20"]
KEPT = ["2026-10-21", "2026-11-18", "2026-11-19"]
FLOWS = ["usgs", "nws", "hormuznow"]
failures = []

lake._cursor = lambda *a: _connect()
cur = _connect()


def run(sql):
    cur.execute(sql)
    return cur.fetchall()


# 1. The table, twice (idempotent).
lake.ensure_raw_table("h", 0, "u", "p", CAT, DB, log=lambda *a: None)
lake.ensure_raw_table("h", 0, "u", "p", CAT, DB, log=lambda *a: None)
cols = [r[0] for r in run(f"SELECT column_name FROM {CAT}.information_schema.columns "
                          f"WHERE table_schema = '{DB}' AND table_name = '{lake.RAW_TABLE}' ORDER BY ordinal_position")]
sql = open(os.path.join(HERE, "..", "05_raw_to_iceberg.sql")).read()
insert = re.search(r"INSERT INTO \S+raw_responses\s+SELECT (.*?)\s+FROM \(", sql, re.S).group(1)
inserted = [c.strip() for c in insert.replace("\n", " ").split(",")]
if cols != inserted:
    failures.append(f"table columns {cols} != the Flink INSERT's {inserted}")

# 2. Rows: each day x flow written as several small inserts (several files per partition).
for day in OLD + KEPT + [TODAY]:
    for flow in FLOWS:
        for i in range(4):
            run(f"INSERT INTO {FQ} VALUES ('{flow}', 'https://x.example/{flow}', 200, 'application/json', "
                f"TIMESTAMP '{day} {10 + i:02d}:00:00', TIMESTAMP '{day} {10 + i:02d}:00:05', "
                f"'{flow}{day}{i}', 10, '{{\"i\": {i}}}', 0, {i})")
before = {d: f for d, f, *_ in lm.partitions(run, FQ, "received_at")}

# 3. A dry run changes nothing; then the real pass.
plan = lm.maintain(run, FQ, apply=False, log=lambda *a: None, today=TODAY, time_col="received_at", retain_days=KEEP)
if plan["dropped"] != OLD:
    failures.append(f"dry run would drop {plan['dropped']}, expected {OLD}")
if run(f"SELECT COUNT(*) FROM {FQ}")[0][0] != 6 * 3 * 4:
    failures.append("the dry run changed the table")
res = lm.maintain(run, FQ, apply=True, log=print, today=TODAY, time_col="received_at", retain_days=KEEP)
after = {d: f for d, f, *_ in lm.partitions(run, FQ, "received_at")}
if any(d in after for d in OLD):
    failures.append(f"days past retention still there: {[d for d in OLD if d in after]}")
for d in KEPT:
    if after.get(d, 0) >= before[d]:
        failures.append(f"{d} not compacted: {before[d]} -> {after.get(d)} files")
if after.get(TODAY) != before[TODAY]:
    failures.append(f"today was touched: {before[TODAY]} -> {after.get(TODAY)} files")
n = run(f"SELECT COUNT(*) FROM {FQ}")[0][0]
if n != (len(KEPT) + 1) * len(FLOWS) * 4:
    failures.append(f"{n} rows after maintenance, expected {(len(KEPT) + 1) * len(FLOWS) * 4}")
again = lm.maintain(run, FQ, apply=True, log=lambda *a: None, today=TODAY, time_col="received_at", retain_days=KEEP)
if again["days"] or again["dropped"]:
    failures.append(f"second pass still had work: {again['days']}, {again['dropped']}")

print("\n".join(f"FAIL {f}" for f in failures) or
      f"ok: bronze table matches the Flink job; {len(OLD)} days past {KEEP}-day retention deleted, "
      f"{len(KEPT)} finished days compacted, today untouched, every kept row there")
sys.exit(1 if failures else 0)
