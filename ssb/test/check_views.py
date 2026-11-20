#!/usr/bin/env python3
"""The typed views (burndown O0b) on the local Trino started by run_views_local.sh.

Fills events with every v2 envelope the NiFi scripts produce from their samples
(nifi/test/out), through the migration's backfill SQL (as the Flink job writes
them), creates the views with lake.ensure_views, and checks that each view has its
rows and that its typed columns are filled from the payload. Then, if Helios is
importable, runs Helios's harvest and profile over the views schema.
"""
import glob
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "provision"))
import lake  # noqa: E402
import migrate_lake  # noqa: E402
import rebuild  # noqa: E402
import trino  # noqa: E402

CAT, DB, TABLE = "iceberg", "horus_vw", "events_iceberg"
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


lake._cursor = lambda *a: cur
run(f"CREATE SCHEMA IF NOT EXISTS {CAT}.{DB}")
run(f"CREATE TABLE {CAT}.{DB}.{TABLE} ({lake.COLUMNS}) WITH ({lake.TABLE_PROPERTIES})")
stage = f"{CAT}.{DB}.stage"
run(f"CREATE TABLE {stage} (payload VARCHAR)")
payloads = [l.strip() for f in sorted(glob.glob(os.path.join(ROOT, "nifi", "test", "out", "*.jsonl")))
            for l in open(f) if l.strip()]
rebuild._stage_insert(run, stage, payloads)
run(f"INSERT INTO {CAT}.{DB}.{TABLE} ({', '.join(migrate_lake.COLUMN_NAMES)}) "
    f"{migrate_lake.backfill_select(rebuild._stage_rows(stage), 'asset_id IS NOT NULL AND lat IS NOT NULL')}")
n_events = run(f"SELECT COUNT(*) FROM {CAT}.{DB}.{TABLE}")[0][0]

names = lake.ensure_views("h", 0, "u", "p", CAT, DB, TABLE, log=print)
names2 = lake.ensure_views("h", 0, "u", "p", CAT, DB, TABLE, log=lambda *a: None)   # re-run: replace
vdb = lake.views_database(DB)
# Every view has rows, and these columns are filled for at least one row.
filled = {"vessel_positions": ["mmsi", "speed_kn", "course_deg", "vessel_name"],
          "vessel_static_reports": ["mmsi", "imo", "call_sign", "length_m"],
          "aircraft_positions": ["icao24", "callsign", "registration", "aircraft_model", "alt_m", "speed_kn"],
          "earthquakes": ["magnitude", "depth_km", "place"],
          "weather_events": ["title", "severity", "weather_category"],
          "fire_detections": ["brightness_k", "radiative_power_mw", "confidence"]}
total = 0
for v in names:
    n = run(f"SELECT COUNT(*) FROM {CAT}.{vdb}.{v}")[0][0]
    total += n
    got = {c: run(f"SELECT COUNT({c}) FROM {CAT}.{vdb}.{v}")[0][0] for c in filled[v]}
    print(f"  {v}: {n} rows; " + ", ".join(f"{c} {k}" for c, k in got.items()))
    if not n:
        failures.append(f"{v} is empty")
    failures += [f"{v}.{c} is never filled" for c, k in got.items() if not k]
hormuz = run(f"SELECT COUNT(provider_vessel_id) FROM {CAT}.{vdb}.vessel_positions WHERE source_provider = 'hormuz.now'")[0][0]
if not hormuz:
    failures.append("vessel_positions has no hormuz.now vessel id")
if total != n_events:
    failures.append(f"the views hold {total} rows but events has {n_events}: every event should be in exactly one")

# Helios over the views schema, set up by provision/semantic.py as on the platform:
# harvest and profile (propose needs the LLM, so it runs on the platform only).
try:
    import semantic
    from helios_cortex.registry import SqlRegistry
    from helios_cortex.settings import load_settings
    from helios_model import Catalog, Profiler
except ImportError as e:
    failures.append(f"Helios not importable ({e})")
else:
    out = os.path.join(HERE, "out", "helios")
    os.makedirs(out, exist_ok=True)
    config = os.path.join(out, "helios.toml")
    with open(config, "w") as f:
        f.write(semantic.settings_toml(os.path.join(out, "data"), "localhost", 18481, CAT, vdb, "t",
                                       http_scheme="http"))
    semantic.register(config, {}, vdb)
    semantic.register(config, {}, vdb, log=lambda *a: None)    # again: already registered is fine
    settings = load_settings(config=config)
    source = SqlRegistry.from_settings(settings).data_source(semantic.SOURCE_ID)
    harvest = Catalog(settings).harvest(source, None, databases=[vdb], model_id=semantic.MODEL_ID)
    print(f"  helios harvest {harvest.run_id}: {sorted(harvest.tables)}")
    if sorted(t.split(".")[-1] for t in harvest.tables) != sorted(names):
        failures.append(f"Helios harvested {sorted(harvest.tables)}, expected exactly the views {sorted(names)}")
    profile = Profiler(settings).profile(harvest.run_id, None)
    print(f"  helios profile: {len(profile.relationships)} relationships verified, "
          f"{len(profile.suggested_relationships)} suggested")

print("\n".join(f"FAIL {f}" for f in failures) or
      f"ok: {len(names)} views over {n_events} events, every event in one view, typed columns filled; "
      "Helios (set up by semantic.py) harvested exactly the views and profiled them")
sys.exit(1 if failures else 0)
