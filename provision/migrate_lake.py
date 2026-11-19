"""Move an instance's events table from lake schema v1 to v2, keeping its history.

Burndown 16.5; the rules are in docs/LAKE-SCHEMA.md ("Backfill from v1 payloads").
Run through ``python provision/horus.py migrate-lake`` (a dry run; ``--yes`` to
apply). The steps, each safe to re-run if one fails:

1. Stop the v1 lake job in SSB, so no row arrives after its day is copied.
   Iceberg commits only on a checkpoint, so nothing written is lost, and the
   v2 job later resumes from the same consumer group's committed offsets.
2. Create ``<table>_v2`` (provision/lake.py) and fill it from the v1 table one
   day at a time. A day whose row count already matches is skipped; a partly
   copied day is deleted and copied again.
3. Check the totals match, then rename: ``<table>`` -> ``<table>_v1`` and
   ``<table>_v2`` -> ``<table>``.
4. Start the v2 job (ssb/02_kafka_to_iceberg.sql).

The v1 table is kept as ``<table>_v1``; drop it after a week.
"""
from __future__ import annotations

from typing import Callable, List, Optional

import lake

COLUMN_NAMES = [line.split()[0] for line in lake.COLUMNS.strip().splitlines()]


def _p(path: str) -> str:
    return f"json_extract_scalar(payload, '{path}')"


def _num(path: str) -> str:
    return f"TRY_CAST({_p(path)} AS DOUBLE)"


def _ts(expr: str) -> str:
    """An envelope time string (ISO-8601, to the second) as TIMESTAMP(6)."""
    return (f"TRY(CAST(date_parse(substr(replace(replace({expr}, 'T', ' '), 'Z', ''), 1, 19), "
            f"'%Y-%m-%d %H:%i:%s') AS TIMESTAMP(6)))")


KNOTS = "0.514444"

# Per-row: rows whose payload is envelope v2 (NiFi after update-scripts) take the
# v2 fields exactly as the Flink job does; v1 rows take the backfill rules.
V1_ID_SCHEME = """CASE prov
    WHEN 'aisstream.io' THEN 'mmsi'
    WHEN 'hormuz.now' THEN CASE WHEN asset_id LIKE 'hormuz.now:%' THEN 'hormuz.now' ELSE 'mmsi' END
    WHEN 'opensky' THEN 'icao24'
    WHEN 'adsb.lol' THEN CASE WHEN regexp_like(asset_id, '^[0-9a-f]{6}$') THEN 'icao24'
                              WHEN asset_id LIKE '~%' THEN 'adsb.lol' ELSE 'callsign' END
    WHEN 'USGS' THEN 'usgs'
    WHEN 'NASA-FIRMS' THEN 'firms'
    WHEN 'NASA EONET' THEN 'eonet'
    WHEN 'NASA-EONET' THEN 'eonet'
    WHEN 'NOAA/NWS' THEN 'nws'
  END"""

V1_SUBTYPE = f"""CASE asset_type
    WHEN 'VESSEL' THEN COALESCE({_p('$.entity.properties.type')},
      CASE WHEN {_num('$.entity.properties.shipType')} BETWEEN 80 AND 89 THEN 'tanker'
           WHEN {_num('$.entity.properties.shipType')} = 35 THEN 'military'
           WHEN {_num('$.entity.properties.shipType')} > 0 THEN 'cargo' END)
    WHEN 'FLIGHT' THEN {_p('$.entity.properties.category')}
    WHEN 'WEATHER' THEN {_p('$.entity.properties.category')}
    WHEN 'FIRE' THEN {_p('$.entity.properties.firetype')}
  END"""

V1_SPEED = f"""CASE asset_type
    WHEN 'FLIGHT' THEN {_num('$.entity.properties.speed_knots')} * {KNOTS}
    WHEN 'VESSEL' THEN CASE WHEN {_num('$.entity.properties.sog')} < 102.3
                            THEN {_num('$.entity.properties.sog')} * {KNOTS} END
  END"""

V1_COURSE = f"""CASE asset_type
    WHEN 'FLIGHT' THEN {_num('$.entity.properties.heading')}
    WHEN 'VESSEL' THEN CASE WHEN {_num('$.entity.properties.cog')} < 360
                            THEN {_num('$.entity.properties.cog')} END
  END"""

V1_HEADING = f"""CASE WHEN asset_type = 'VESSEL' AND {_num('$.entity.properties.heading')} < 360
       THEN {_num('$.entity.properties.heading')} END"""

# NWS v1 rows: the job read a local-offset time as UTC; recompute from the source string.
V1_EVENT_TIME = f"""CASE WHEN prov = 'NOAA/NWS'
       THEN COALESCE(TRY(CAST(from_iso8601_timestamp({_p('$.entity.properties.date')}) AT TIME ZONE 'UTC'
                              AS TIMESTAMP(6))), event_time)
       ELSE event_time END"""


def backfill_select(source: str, where: str) -> str:
    """SELECT producing v2 rows (in lake.COLUMNS order) from v1 rows of ``source``."""
    v2 = "sv >= 2"
    base = f"""
SELECT r.*,
  CASE WHEN {v2} THEN {_ts(_p('$.entity.timestamp'))} ELSE {V1_EVENT_TIME} END AS et
FROM (
  SELECT t.*,
    COALESCE({_p('$.entity.source.provider')}, source_provider, 'unknown') AS prov,
    COALESCE({_p('$.entity.source.originalId')}, {_p('$.entity.id')}, event_id) AS orig,
    COALESCE(TRY_CAST({_p('$.schema_version')} AS BIGINT), schema_version, 1) AS sv
  FROM {source} t
  WHERE {where}
) r"""
    eid = "prov || ':' || orig"
    cols = {
        "event_id": eid,
        "obs_hash": lake.OBS_HASH_SQL.format(event_id=f"({eid})", event_time="et"),
        "asset_id": "asset_id",
        "id_scheme": f"CASE WHEN {v2} THEN {_p('$.entity.source.idScheme')} ELSE {V1_ID_SCHEME} END",
        "asset_type": "asset_type",
        "asset_subtype": f"CASE WHEN {v2} THEN {_p('$.entity.subtype')} ELSE {V1_SUBTYPE} END",
        "display_name": f"COALESCE({_p('$.entity.name')}, {_p('$.name')})",
        "lat": "lat",
        "lon": "lon",
        "alt_m": (f"CASE WHEN {v2} THEN {_num('$.entity.position.alt')} "
                  f"WHEN asset_type = 'FLIGHT' THEN {_num('$.entity.position.alt')} END"),
        "tile_z8": lake.TILE_Z8_SQL.format(lat="lat", lon="lon"),
        "geom_wkt": f"CASE WHEN {v2} THEN {_p('$.entity.geometry')} END",
        "bbox_min_lon": f"COALESCE(CASE WHEN {v2} THEN {_num('$.entity.bbox[0]')} END, lon)",
        "bbox_min_lat": f"COALESCE(CASE WHEN {v2} THEN {_num('$.entity.bbox[1]')} END, lat)",
        "bbox_max_lon": f"COALESCE(CASE WHEN {v2} THEN {_num('$.entity.bbox[2]')} END, lon)",
        "bbox_max_lat": f"COALESCE(CASE WHEN {v2} THEN {_num('$.entity.bbox[3]')} END, lat)",
        "speed_mps": f"CASE WHEN {v2} THEN {_num('$.entity.motion.speedMps')} ELSE {V1_SPEED} END",
        "course_deg": f"CASE WHEN {v2} THEN {_num('$.entity.motion.courseDeg')} ELSE {V1_COURSE} END",
        "heading_deg": f"CASE WHEN {v2} THEN {_num('$.entity.motion.headingDeg')} ELSE {V1_HEADING} END",
        "event_time": "et",
        "captured_at": _ts("captured_at"),
        "ingest_time": "ingest_time",
        "source_provider": "prov",
        "source_feed": "source_feed",
        "source_confidence": "source_confidence",
        "classification": _p("$.entity.classification"),
        "releasability": f"CASE WHEN {v2} THEN {_p('$.entity.releasability')} END",
        "trace_id": "trace_id",
        "ingest_run_id": "ingest_run_id",
        "schema_version": "sv",
        "payload": "payload",
    }
    missing = set(COLUMN_NAMES) ^ set(cols)
    if missing:
        raise AssertionError(f"backfill columns out of step with lake.COLUMNS: {sorted(missing)}")
    select = ",\n  ".join(f"{cols[c]} AS {c}" for c in COLUMN_NAMES)
    return f"SELECT\n  {select}\nFROM ({base}\n) b"


def _days(run, source: str) -> List[Optional[str]]:
    """Each day in the source table (YYYY-MM-DD), oldest first; None for rows with no event_time."""
    rows = run(f"SELECT DISTINCT CAST(CAST(event_time AS DATE) AS VARCHAR) FROM {source}")
    days = sorted(r[0] for r in rows if r[0] is not None)
    return days + ([None] if any(r[0] is None for r in rows) else [])


def _day_where(day: Optional[str]) -> str:
    if day is None:
        return "event_time IS NULL"
    return (f"event_time >= TIMESTAMP '{day} 00:00:00' "
            f"AND event_time < TIMESTAMP '{day} 00:00:00' + INTERVAL '1' DAY")


def copy(run: Callable[[str], list], catalog: str, database: str, table: str,
         log=print) -> int:
    """Steps 2 and 3 up to the check: fill <table>_v2 from <table>. Returns the row count.

    v1 rows keep their own event_time partition, except NWS rows whose time is
    corrected; those are matched by the v1 day they came from (``v1_day``).
    """
    src = f"{catalog}.{database}.{table}"
    dst = f"{catalog}.{database}.{table}_v2"
    total = 0
    for day in _days(run, src):
        where = _day_where(day)
        n_src = run(f"SELECT COUNT(*) FROM {src} WHERE {where}")[0][0]
        # Rows copied from this source day: match on the hash of their v1 identity, so
        # rows whose event_time moved (NWS) are still counted against their source day.
        n_dst = run(f"SELECT COUNT(*) FROM {dst} WHERE obs_hash IN "
                    f"(SELECT obs_hash FROM ({backfill_select(src, where)}))")[0][0]
        label = day or "no event_time"
        if n_dst == n_src:
            log(f"migrate: {label}: {n_src} rows already copied")
            total += n_src
            continue
        if n_dst:
            run(f"DELETE FROM {dst} WHERE obs_hash IN "
                f"(SELECT obs_hash FROM ({backfill_select(src, where)}))")
            log(f"migrate: {label}: removed a partial copy ({n_dst} rows)")
        run(f"INSERT INTO {dst} ({', '.join(COLUMN_NAMES)}) {backfill_select(src, where)}")
        log(f"migrate: {label}: copied {n_src} rows")
        total += n_src
    n_src = run(f"SELECT COUNT(*) FROM {src}")[0][0]
    n_dst = run(f"SELECT COUNT(*) FROM {dst}")[0][0]
    if n_src != n_dst:
        raise RuntimeError(f"migrate: {src} has {n_src} rows but {dst} has {n_dst}; not swapping")
    log(f"migrate: {dst} has all {n_dst} rows")
    return n_dst


def swap(run: Callable[[str], list], catalog: str, database: str, table: str, log=print) -> None:
    """Step 3: <table> -> <table>_v1, <table>_v2 -> <table>."""
    fq = f"{catalog}.{database}"
    run(f"ALTER TABLE {fq}.{table} RENAME TO {fq}.{table}_v1")
    run(f"ALTER TABLE {fq}.{table}_v2 RENAME TO {fq}.{table}")
    log(f"migrate: {fq}.{table} is now schema v2; the v1 table is {fq}.{table}_v1 (drop it after a week)")
