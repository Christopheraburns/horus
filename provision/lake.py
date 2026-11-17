"""Create the Horus lakehouse schema and Iceberg table through a CDW Trino VW.

The table lands in the environment's shared metastore, so the Flink job in SQL
Stream Builder writes to it through a Flink Iceberg catalog and Trino/Impala read it.
Column types mirror ssb/01_events_iceberg_ddl.sql exactly.
"""
from __future__ import annotations

from typing import Optional

COLUMNS = """
    event_id          VARCHAR,
    asset_id          VARCHAR,
    asset_type        VARCHAR,
    lat               DOUBLE,
    lon               DOUBLE,
    event_time        TIMESTAMP(6),
    ingest_time       TIMESTAMP(6),
    trace_id          VARCHAR,
    ingest_run_id     VARCHAR,
    source_provider   VARCHAR,
    source_feed       VARCHAR,
    captured_at       VARCHAR,
    schema_version    BIGINT,
    source_confidence DOUBLE,
    payload           VARCHAR
"""


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


def ensure_table(host: str, port: int, user: str, password: str, catalog: str,
                 database: str, table: str, log=print) -> None:
    cur = _cursor(host, port, user, password, catalog)

    def run(sql: str) -> list:
        cur.execute(sql)
        return cur.fetchall()

    catalogs = {r[0] for r in run("SHOW CATALOGS")}
    if catalog not in catalogs:
        raise RuntimeError(f"lake: Trino has no catalog {catalog!r}; available: {sorted(catalogs)} "
                           "-- set LAKE_CATALOG")
    run(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{database}")
    run(f"CREATE TABLE IF NOT EXISTS {catalog}.{database}.{table} ({COLUMNS}) "
        "WITH (format = 'PARQUET')")
    n = run(f"SELECT COUNT(*) FROM {catalog}.{database}.{table}")[0][0]
    log(f"lake: {catalog}.{database}.{table} ready ({n} rows)")
