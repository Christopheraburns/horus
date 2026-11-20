"""Create the Horus lakehouse schema and Iceberg table through a CDW Trino VW.

The table lands in the environment's shared metastore, so the Flink job in SQL
Stream Builder writes to it through a Flink Iceberg catalog and Trino/Impala read it.
Schema v2: docs/LAKE-SCHEMA.md. ssb/01_events_iceberg_ddl.sql is the same DDL for by-hand use.
"""
from __future__ import annotations

from typing import Optional

# Schema v2 (docs/LAKE-SCHEMA.md). Order matches the INSERT in
# ssb/02_kafka_to_iceberg.sql and the reference DDL in ssb/01_events_iceberg_ddl.sql.
COLUMNS = """
    event_id          VARCHAR,
    obs_hash          VARCHAR,
    asset_id          VARCHAR,
    id_scheme         VARCHAR,
    asset_type        VARCHAR,
    asset_subtype     VARCHAR,
    display_name      VARCHAR,
    lat               DOUBLE,
    lon               DOUBLE,
    alt_m             DOUBLE,
    tile_z8           INTEGER,
    geom_wkt          VARCHAR,
    bbox_min_lon      DOUBLE,
    bbox_min_lat      DOUBLE,
    bbox_max_lon      DOUBLE,
    bbox_max_lat      DOUBLE,
    speed_mps         DOUBLE,
    course_deg        DOUBLE,
    heading_deg       DOUBLE,
    event_time        TIMESTAMP(6),
    captured_at       TIMESTAMP(6),
    ingest_time       TIMESTAMP(6),
    source_provider   VARCHAR,
    source_feed       VARCHAR,
    source_confidence DOUBLE,
    classification    VARCHAR,
    releasability     VARCHAR,
    trace_id          VARCHAR,
    ingest_run_id     VARCHAR,
    schema_version    BIGINT,
    payload           VARCHAR
"""

TABLE_PROPERTIES = ("format = 'PARQUET', format_version = 2, "
                    "partitioning = ARRAY['day(event_time)'], "
                    "sorted_by = ARRAY['tile_z8', 'event_time']")
# Iceberg's own property, read by the Flink writer and by compaction.
ZSTD = "MAP(ARRAY['write.parquet.compression-codec'], ARRAY['zstd'])"

# The derived columns in Trino SQL, the same formulas as the Flink job
# (ssb/02_kafka_to_iceberg.sql); ssb/test/run_trino_local.sh checks they agree.
# Format with lat, lon, event_id and event_time as column expressions.
TILE_Z8_SQL = """(LEAST(GREATEST(CAST(FLOOR((CAST({lon} AS DOUBLE) + 180) / 360 * 256) AS INTEGER), 0), 255) * 256
  + LEAST(GREATEST(CAST(FLOOR((1 - LN(TAN(RADIANS(GREATEST(LEAST(CAST({lat} AS DOUBLE), 85.0511287798), -85.0511287798)))
      + 1 / COS(RADIANS(GREATEST(LEAST(CAST({lat} AS DOUBLE), 85.0511287798), -85.0511287798)))) / PI()) / 2 * 256)
    AS INTEGER), 0), 255))"""
OBS_HASH_SQL = ("lower(to_hex(sha256(to_utf8({event_id} || '|' || CAST(CAST("
                "to_unixtime(with_timezone({event_time}, 'UTC')) * 1000 AS BIGINT) AS VARCHAR)))))")


# The bronze table (burndown 17, docs/LAKE-SCHEMA.md "Raw capture"): every upstream
# response as NiFi received it. Order matches the INSERT in ssb/05_raw_to_iceberg.sql.
RAW_TABLE = "raw_responses"
RAW_COLUMNS = """
    flow            VARCHAR,
    source_url      VARCHAR,
    http_status     INTEGER,
    content_type    VARCHAR,
    received_at     TIMESTAMP(6),
    ingest_time     TIMESTAMP(6),
    body_sha256     VARCHAR,
    body_chars      BIGINT,
    body            VARCHAR,
    kafka_partition INTEGER,
    kafka_offset    BIGINT
"""
RAW_TABLE_PROPERTIES = ("format = 'PARQUET', format_version = 2, "
                        "partitioning = ARRAY['day(received_at)', 'flow'], "
                        "sorted_by = ARRAY['received_at']")


def _cursor(host: str, port: int, user: str, password: str, catalog: str):
    import trino  # lazy

    conn = trino.dbapi.connect(host=host, port=port, user=user, catalog=catalog,
                               http_scheme="https",
                               auth=trino.auth.BasicAuthentication(user, password))
    return conn.cursor()


def table_rows(host: str, port: int, user: str, password: str, catalog: str,
               database: str, table: str) -> Optional[int]:
    """Row count, or None if the schema or table does not exist. Read-only."""
    cur = _cursor(host, port, user, password, catalog)
    cur.execute(f"SELECT count(*) FROM {catalog}.information_schema.tables "
                f"WHERE table_schema = '{database}' AND table_name = '{table}'")
    if not cur.fetchall()[0][0]:
        return None
    cur.execute(f"SELECT COUNT(*) FROM {catalog}.{database}.{table}")
    return cur.fetchall()[0][0]


def schema_version(cur, catalog: str, database: str, table: str) -> Optional[int]:
    """2 for a v2 table, 1 for the original one, None if the table doesn't exist."""
    cur.execute(f"SELECT column_name FROM {catalog}.information_schema.columns "
                f"WHERE table_schema = '{database}' AND table_name = '{table}'")
    cols = {r[0] for r in cur.fetchall()}
    if not cols:
        return None
    return 2 if "obs_hash" in cols else 1


def _ensure_zstd(run, fq: str, database: str, table: str, log) -> None:
    """Trino records its own codec (ZSTD by default) as the table's
    write.parquet.compression-codec, which the Flink writer also reads. Set it
    only if this Trino is configured otherwise."""
    props = dict(run(f'SELECT key, value FROM {fq.rsplit(".", 1)[0]}."{table}$properties"'))
    if props.get("write.parquet.compression-codec", "").lower() == "zstd":
        return
    try:
        run(f"ALTER TABLE {fq} SET PROPERTIES extra_properties = {ZSTD}")
        log("lake: set write.parquet.compression-codec=zstd")
    except Exception as e:  # noqa: BLE001 -- older Trino has no extra_properties
        log(f"lake: table codec is {props.get('write.parquet.compression-codec')!r} and Trino cannot change "
            f"it ({str(e).splitlines()[0][:120]}); run in Impala: ALTER TABLE {database}.{table} "
            "SET TBLPROPERTIES ('write.parquet.compression-codec'='zstd')")


def ensure_table(host: str, port: int, user: str, password: str, catalog: str,
                 database: str, table: str, log=print) -> int:
    """Create the v2 table if there is none. Returns the table's schema version.

    An existing v1 table is left as it is: moving it to v2 keeps its history and
    is a separate, deliberate step (burndown 16.5).
    """
    cur = _cursor(host, port, user, password, catalog)

    def run(sql: str) -> list:
        cur.execute(sql)
        return cur.fetchall()

    catalogs = {r[0] for r in run("SHOW CATALOGS")}
    if catalog not in catalogs:
        raise RuntimeError(f"lake: Trino has no catalog {catalog!r}; available: {sorted(catalogs)} "
                           "-- set LAKE_CATALOG")
    run(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{database}")
    fq = f"{catalog}.{database}.{table}"
    version = schema_version(cur, catalog, database, table)
    if version == 1:
        log(f"lake: {fq} is schema v1; leaving it for the v2 migration (burndown 16.5)")
        return 1
    if version is None:
        run(f"CREATE TABLE {fq} ({COLUMNS}) WITH ({TABLE_PROPERTIES})")
        log(f"lake: created {fq} (schema v2, partitioned by day, sorted by tile_z8)")
        _ensure_zstd(run, fq, database, table, log)
    n = run(f"SELECT COUNT(*) FROM {fq}")[0][0]
    log(f"lake: {fq} ready ({n} rows)")
    return 2


def ensure_raw_table(host: str, port: int, user: str, password: str, catalog: str,
                     database: str, log=print) -> None:
    """Create the bronze table beside events if there is none (burndown 17.4)."""
    cur = _cursor(host, port, user, password, catalog)

    def run(sql: str) -> list:
        cur.execute(sql)
        return cur.fetchall()

    run(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{database}")
    fq = f"{catalog}.{database}.{RAW_TABLE}"
    run(f"CREATE TABLE IF NOT EXISTS {fq} ({RAW_COLUMNS}) WITH ({RAW_TABLE_PROPERTIES})")
    _ensure_zstd(run, fq, database, RAW_TABLE, log)
    n = run(f"SELECT COUNT(*) FROM {fq}")[0][0]
    log(f"lake: {fq} ready ({n} rows)")
