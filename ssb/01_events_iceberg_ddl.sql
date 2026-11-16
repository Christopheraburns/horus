-- Horus -- Iceberg landing table. Run ONCE in SQL Stream Builder (Flink SQL)
-- before starting the INSERT job in 02_kafka_to_iceberg.sql.
--
-- Prerequisites
--   * Database `horus` exists in the Hive Metastore (create it in Hue/Impala:
--       CREATE DATABASE IF NOT EXISTS horus;)
--   * Ranger: the `ssb` service user AND your workload user have
--       - Hadoop SQL: all on database horus
--       - S3 (RAZ):   read/write on the warehouse path of database horus
--   * <registered-hive-catalog-name> is the Hive catalog registered in SSB
--     (Data Providers > Catalogs).

CREATE TABLE IF NOT EXISTS events_iceberg (
    event_id          STRING,        -- entity.source.originalId (falls back to entity.id)
    asset_id          STRING,        -- entity.id  (stable identity; TimeTravel / Pattern-of-Life key)
    asset_type        STRING,        -- entity.entityType
    lat               DOUBLE,        -- entity.position.lat
    lon               DOUBLE,        -- entity.position.lng
    event_time        TIMESTAMP(6),  -- source event time (UTC)
    ingest_time       TIMESTAMP(6),
    trace_id          STRING,        -- NiFi correlation UUID
    ingest_run_id     STRING,
    source_provider   STRING,        -- entity.source.provider
    source_feed       STRING,        -- entity.source.feed
    captured_at       STRING,
    schema_version    BIGINT,
    source_confidence DOUBLE,
    payload           STRING         -- the FULL canonical message, loss-less (replay source)
) WITH (
    'connector'           = 'iceberg',
    'catalog-type'        = 'hive',
    'catalog-name'        = 'horus_iceberg',
    'catalog-database'    = 'horus',
    'catalog-table'       = 'events_iceberg',
    'ssb-hive-catalog'    = '<registered-hive-catalog-name>',
    'engine.hive.enabled' = 'true'
);
