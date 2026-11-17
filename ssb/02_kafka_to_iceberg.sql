-- Horus -- continuous Kafka -> Iceberg job for SQL Stream Builder.
--
-- `python provision/horus.py create --yes` fills the {{...}} tokens and submits
-- this as the job {{JOB_NAME}} in SSB project {{PROJECT}}, with checkpointing on
-- (Iceberg only commits data files on a checkpoint). To run it by hand instead,
-- replace the tokens in the SSB editor -- never commit a filled-in copy, it holds
-- the workload password.
--
-- Prerequisites (the provisioner checks or creates the first three):
--   * the Iceberg table {{DATABASE}}.events_iceberg (created through Trino)
--   * the SSB Hive catalog {{HIVE_CATALOG}} (used to check the table is visible)
--   * Ranger, Hadoop SQL: user `ssb` -- all on database {{DATABASE}}, table *
--   * Ranger, S3 (RAZ): users `ssb` and the workload user -- read/write on
--     path /data/warehouse/tablespace/external/hive/{{DATABASE}}.db (recursive)
--   * the jaas class must be the NON-shaded PlainLoginModule below

SET 'table.local-time-zone' = 'UTC';

-- The whole Kafka value as one JSON string: one source definition serves every
-- feed and the lake keeps the exact message NiFi produced.
CREATE TEMPORARY TABLE horus_events_raw (
    payload STRING
) WITH (
    'connector' = 'kafka',
    'topic' = '{{TOPIC}}',
    'scan.startup.mode' = 'group-offsets',
    'properties.auto.offset.reset' = 'earliest',
    'format' = 'raw',
    'properties.group.id' = '{{GROUP_ID}}',
    'properties.bootstrap.servers' = '{{BROKERS}}',
    'properties.security.protocol' = 'SASL_SSL',
    'properties.sasl.mechanism' = 'PLAIN',
    'properties.sasl.jaas.config' = 'org.apache.kafka.common.security.plain.PlainLoginModule required username="{{KAFKA_USER}}" password="{{KAFKA_PASSWORD}}";'
);

-- The Data Lake metastore as an Iceberg catalog, from the hub's Hive client
-- config. The table already exists (created through Trino); Flink only appends.
CREATE CATALOG horus_ice WITH (
    'type' = 'iceberg',
    'catalog-type' = 'hive',
    'hive-conf-dir' = '/etc/hive/conf'
);

INSERT INTO horus_ice.{{DATABASE}}.events_iceberg
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
