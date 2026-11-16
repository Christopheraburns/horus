-- Horus -- continuous Kafka -> Iceberg job. Run in SQL Stream Builder.
--
-- BEFORE YOU RUN
--   1. Job settings: ENABLE CHECKPOINTING (Iceberg commits only on checkpoint;
--      without it the job runs and the table stays empty).
--   2. Replace the <...> placeholders below. Paste the workload password in the
--      SSB editor only -- never commit a filled-in copy of this file.
--   3. The jaas class must be the NON-shaded
--      org.apache.kafka.common.security.plain.PlainLoginModule.
--   4. Ranger: `ssb` user can consume topic horus-events and publish ATLAS_HOOK.

SET 'table.local-time-zone' = 'UTC';

-- The whole Kafka value as one JSON string: one source definition serves every
-- feed and the lake keeps the exact message NiFi produced.
CREATE TEMPORARY TABLE IF NOT EXISTS horus_events_raw (
    payload STRING
) WITH (
    'connector' = 'kafka',
    'topic' = 'horus-events',
    'scan.startup.mode' = 'earliest-offset',
    'format' = 'raw',
    'properties.group.id' = 'horus-flink-lakehouse',
    'properties.bootstrap.servers' = '<broker0>:9093,<broker1>:9093,<broker2>:9093',
    'properties.security.protocol' = 'SASL_SSL',
    'properties.sasl.mechanism' = 'PLAIN',
    'properties.sasl.jaas.config' = 'org.apache.kafka.common.security.plain.PlainLoginModule required username="<workload-user>" password="<workload-password>";'
);

INSERT INTO events_iceberg
SELECT
    COALESCE(JSON_VALUE(payload, '$.entity.source.originalId'),
             JSON_VALUE(payload, '$.entity.id'))                        AS event_id,
    JSON_VALUE(payload, '$.entity.id')                                  AS asset_id,
    JSON_VALUE(payload, '$.entity.entityType')                          AS asset_type,
    CAST(JSON_VALUE(payload, '$.entity.position.lat') AS DOUBLE)        AS lat,
    CAST(JSON_VALUE(payload, '$.entity.position.lng') AS DOUBLE)        AS lon,
    CAST(TO_TIMESTAMP(SUBSTRING(REPLACE(REPLACE(
         JSON_VALUE(payload, '$.entity.timestamp'), 'T', ' '), 'Z', '')
         FROM 1 FOR 19)) AS TIMESTAMP(6))                               AS event_time,
    CAST(LOCALTIMESTAMP AS TIMESTAMP(6))                                AS ingest_time,
    JSON_VALUE(payload, '$.trace_id')                                   AS trace_id,
    JSON_VALUE(payload, '$.ingest_run_id')                              AS ingest_run_id,
    JSON_VALUE(payload, '$.entity.source.provider')                     AS source_provider,
    JSON_VALUE(payload, '$.entity.source.feed')                         AS source_feed,
    JSON_VALUE(payload, '$.captured_at')                                AS captured_at,
    CAST(JSON_VALUE(payload, '$.schema_version') AS BIGINT)             AS schema_version,
    CAST(JSON_VALUE(payload, '$.entity.source.confidence') AS DOUBLE)   AS source_confidence,
    payload                                                             AS payload
FROM horus_events_raw
WHERE JSON_VALUE(payload, '$.entity.id') IS NOT NULL;
