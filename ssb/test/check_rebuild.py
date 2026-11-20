#!/usr/bin/env python3
"""provision/rebuild.py (burndown 17.6) on the local Trino started by run_rebuild_local.sh.

A broken NWS script (every alert named BROKEN, the NWS bug of 2026-11-19 in
spirit) first writes its rows through the rebuild path itself; then the real
script rebuilds them from the same raw responses. Checks: the rows are replaced
with the real script's values; captured_at is each response's received time, not
the rebuild's; NWS rows captured before raw capture began and other providers'
rows are untouched; a repeated alert across responses is one row; a dry run
changes nothing; a second run gives the same rows; today is refused.
"""
import json
import os
import subprocess
import sys
import time
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "provision"))
import lake  # noqa: E402
import rebuild  # noqa: E402
import trino  # noqa: E402

CAT, DB, TABLE = "iceberg", "horus_rb", "events_iceberg"
EV, RAW = f"{CAT}.{DB}.{TABLE}", f"{CAT}.{DB}.{lake.RAW_TABLE}"
TODAY = "2026-11-20"
JARS = sys.argv[1]
WORK = os.path.join(HERE, "out", "rebuild")
os.makedirs(WORK, exist_ok=True)
failures = []


class RetryCursor:
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


cur = RetryCursor(trino.dbapi.connect(host="localhost", port=18481, user="t", catalog=CAT).cursor())


def run(sql):
    cur.execute(sql)
    return cur.fetchall()


def docker_runner(args):
    """Replay.groovy on Java 8 with only the Groovy jars, as in a Workbench session."""
    r = subprocess.run(["docker", "run", "--rm", "-v", f"{ROOT}:{ROOT}:ro", "-v", f"{WORK}:{WORK}",
                        "-v", f"{JARS}:/j:ro", "eclipse-temurin:8-jre", "java", "-cp",
                        "/j/groovy-4.0.24.jar:/j/groovy-json-4.0.24.jar", "groovy.ui.GroovyMain", *args],
                       capture_output=True, text=True)
    print("  " + (r.stdout + r.stderr).strip().splitlines()[-1])
    if r.returncode:
        raise RuntimeError(r.stdout + r.stderr)


# rebuild.FLOWS must name every provider each script writes, or a rebuild would
# leave that provider's old rows beside the new ones.
OUTS = {"usgs": ["usgs"], "firms": ["firms"], "opensky": ["opensky"], "adsblol": ["adsblol"],
        "aisstream": ["aisstream_position", "aisstream_static", "aisstream_unavailable"],
        "hormuznow": ["hormuz"], "eonet": ["eonet"], "nws": ["nws"]}
for flow, outs in OUTS.items():
    seen = {json.loads(l)["entity"]["source"]["provider"] for o in outs
            for l in open(os.path.join(ROOT, "nifi", "test", "out", f"{o}.jsonl")) if l.strip()}
    if not seen <= set(rebuild.FLOWS[flow]["providers"]):
        failures.append(f"rebuild.FLOWS[{flow!r}] lacks providers {sorted(seen - set(rebuild.FLOWS[flow]['providers']))}")
if set(OUTS) != set(rebuild.FLOWS):
    failures.append("rebuild.FLOWS and the flows tested here differ")

run(f"CREATE SCHEMA IF NOT EXISTS {CAT}.{DB}")
run(f"CREATE TABLE {EV} ({lake.COLUMNS}) WITH ({lake.TABLE_PROPERTIES})")
lake._cursor = lambda *a: cur
lake.ensure_raw_table("h", 0, "u", "p", CAT, DB, log=lambda *a: None)

# Raw: three NWS responses on 2026-11-18 (the second identical to the first, as
# re-polls are; the dedupe in the raw job would usually drop it) and one on 11-19.
nws = open(os.path.join(ROOT, "nifi", "test", "samples", "nws.json")).read()
for ts in ("2026-11-18 10:00:00", "2026-11-18 10:10:00", "2026-11-19 09:00:00"):
    run(f"INSERT INTO {RAW} VALUES ('nws', 'https://api.weather.gov/alerts/active', 200, 'application/geo+json', "
        f"TIMESTAMP '{ts}', TIMESTAMP '{ts}', 'h{ts}', {len(nws)}, {rebuild._q(nws)}, 0, 0)")

# Rows the rebuild must not touch: NWS before raw capture began, and another provider.
untouched = [("NOAA/NWS:early", "2026-11-17 12:00:00"), ("USGS:quake1", "2026-11-18 11:00:00")]
for eid, ts in untouched:
    prov = eid.split(":")[0]
    run(f"INSERT INTO {EV} (event_id, obs_hash, asset_id, lat, lon, event_time, captured_at, source_provider, "
        f"display_name, payload) VALUES ('{eid}', '{eid}-h', '{eid}', 1, 1, TIMESTAMP '{ts}', TIMESTAMP '{ts}', "
        f"'{prov}', 'keep me', '{{}}')")

# The broken script writes the bad rows.
broken = os.path.join(WORK, "weather-nws-broken.groovy")
text = open(os.path.join(ROOT, "nifi", "scripts", "weather-nws.groovy")).read()
assert "name          : title.toString()," in text
open(broken, "w").write(text.replace("name          : title.toString(),", "name          : 'BROKEN',"))
real = rebuild.FLOWS["nws"]["script"]
rebuild.FLOWS["nws"]["script"] = broken
rebuild.rebuild(run, CAT, DB, TABLE, "nws", "2026-11-18", "2026-11-19", apply=True, today=TODAY,
                runner=docker_runner, workdir=WORK)
bad = run(f"SELECT display_name, COUNT(*) FROM {EV} WHERE source_provider = 'NOAA/NWS' "
          f"AND captured_at >= TIMESTAMP '2026-11-18 00:00:00' GROUP BY 1")
if [r[0] for r in bad] != ["BROKEN"]:
    failures.append(f"setup: the broken script's rows are {bad}")
n_bad = sum(r[1] for r in bad)

# Fixed: dry run, then the rebuild, then again.
rebuild.FLOWS["nws"]["script"] = real
before = run(f"SELECT COUNT(*) FROM {EV}")[0][0]
plan = rebuild.rebuild(run, CAT, DB, TABLE, "nws", "2026-11-18", "2026-11-19", apply=False, today=TODAY,
                       runner=docker_runner, workdir=WORK)
if run(f"SELECT COUNT(*) FROM {EV} WHERE display_name = 'BROKEN'")[0][0] != n_bad or \
        run(f"SELECT COUNT(*) FROM {EV}")[0][0] != before:
    failures.append("the dry run changed the table")
res = rebuild.rebuild(run, CAT, DB, TABLE, "nws", "2026-11-18", "2026-11-19", apply=True, today=TODAY,
                      runner=docker_runner, workdir=WORK)
rows = run(f"SELECT event_id, obs_hash, display_name, CAST(captured_at AS VARCHAR), ingest_run_id, asset_type "
           f"FROM {EV} WHERE source_provider = 'NOAA/NWS' AND captured_at >= TIMESTAMP '2026-11-18 00:00:00' "
           f"ORDER BY event_id")
expected = [json.loads(l) for l in open(os.path.join(ROOT, "nifi", "test", "out", "nws.jsonl")) if l.strip()]
want_names = sorted(e["entity"]["name"] for e in expected)
if sorted(r[2] for r in rows) != want_names:
    failures.append(f"rebuilt names {sorted(r[2] for r in rows)}, expected the real script's {want_names}")
if len({r[1] for r in rows}) != len(rows):
    failures.append("duplicate obs_hash after the rebuild")
if any(not r[3].startswith("2026-11-18 10:00:00") for r in rows):
    failures.append(f"captured_at should be the first response's received time: {[r[3] for r in rows]}")
if any(not (r[4] or "").startswith("rebuild-nws-") for r in rows):
    failures.append("rebuilt rows lack the rebuild ingest_run_id")
for eid, ts in untouched:
    got = run(f"SELECT display_name FROM {EV} WHERE event_id = '{eid}'")
    if got != [["keep me"]]:
        failures.append(f"{eid} was touched: {got}")
if plan["new"] != res["new"] or res["after"] != len(want_names):
    failures.append(f"counts: plan {plan['new']}, applied {res['new']}, after {res.get('after')}, "
                    f"expected {len(want_names)}")
first = sorted((r[0], r[1], r[2], r[3]) for r in rows)
rebuild.rebuild(run, CAT, DB, TABLE, "nws", "2026-11-18", "2026-11-19", apply=True, today=TODAY,
                runner=docker_runner, workdir=WORK)
again = sorted(tuple(r[:4]) for r in run(
    f"SELECT event_id, obs_hash, display_name, CAST(captured_at AS VARCHAR) FROM {EV} "
    f"WHERE source_provider = 'NOAA/NWS' AND captured_at >= TIMESTAMP '2026-11-18 00:00:00'"))
if again != first:
    failures.append("a second rebuild gave different rows")
try:
    rebuild.rebuild(run, CAT, DB, TABLE, "nws", "2026-11-19", TODAY, apply=False, today=TODAY,
                    runner=docker_runner, workdir=WORK)
    failures.append("a window reaching today was accepted")
except ValueError:
    pass

print("\n".join(f"FAIL {f}" for f in failures) or
      f"ok: {n_bad} broken NWS rows rebuilt from 3 raw responses into the real script's {len(want_names)}; "
      "providers match the scripts; captured_at from the responses; earlier and other rows untouched; dry run and re-run safe; today refused")
sys.exit(1 if failures else 0)
