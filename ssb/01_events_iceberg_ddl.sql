-- Horus -- the events table, schema v2 (docs/LAKE-SCHEMA.md), in Trino.
--
-- `python provision/horus.py create --yes` runs this for you (provision/lake.py,
-- which holds the same columns and properties). Run it by hand only to create the
-- table without the provisioner: in a CDW Trino virtual warehouse, with
-- <catalog> and <database> filled in.
--
-- Trino creates the table, not Flink: a Flink DDL cannot declare the day()
-- partitioning or the sort order. The Flink job (02_kafka_to_iceberg.sql) only
-- appends to it.
--
-- Prerequisites
--   * Ranger: the `ssb` service user AND your workload user have
--       - Hadoop SQL: all on database <database>
--       - S3 (RAZ):   read/write on the warehouse path of database <database>

CREATE SCHEMA IF NOT EXISTS <catalog>.<database>;

CREATE TABLE <catalog>.<database>.events_iceberg (
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
) WITH (format = 'PARQUET', format_version = 2,
      partitioning = ARRAY['day(event_time)'],
      sorted_by = ARRAY['tile_z8', 'event_time']);

-- zstd: Trino writes its own codec (ZSTD by default) into the table property
-- write.parquet.compression-codec, which the Flink writer also reads. Check with
--   SELECT * FROM <catalog>.<database>."events_iceberg$properties";
-- and only if it is not zstd, run in Impala:
--   ALTER TABLE <database>.events_iceberg
--     SET TBLPROPERTIES ('write.parquet.compression-codec'='zstd');
