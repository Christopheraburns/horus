-- Horus -- continuous Kafka -> Iceberg job for SQL Stream Builder.
--
-- `python provision/horus.py create --yes` fills the {{...}} tokens and submits
-- this as the job {{JOB_NAME}} in SSB project {{PROJECT}}, with checkpointing on
-- (Iceberg only commits data files on a checkpoint). To run it by hand instead,
-- replace the tokens in the SSB editor -- never commit a filled-in copy, it holds
-- the workload password.
--
-- Prerequisites (the provisioner creates the first; it reports the Ranger ones):
--   * the Iceberg table {{DATABASE}}.events_iceberg (created through Trino)
--   * Ranger, Hadoop SQL: user `ssb` -- all on database {{DATABASE}}, table *
--   * Ranger, S3 (RAZ): users `ssb` and the workload user -- read/write on
--     path /data/warehouse/tablespace/external/hive/{{DATABASE}}.db (recursive)
--   * the jaas class must be the NON-shaded PlainLoginModule below

SET 'table.local-time-zone' = 'UTC';
-- Dedupe memory: a key seen within the last 36 h is dropped. Covers the 24 h
-- windows the USGS and FIRMS feeds re-send on every poll. RocksDB keeps that
-- state on disk rather than in the TaskManager heap.
SET 'table.exec.state.ttl' = '36 h';
SET 'state.backend.type' = 'rocksdb';
SET 'state.backend.incremental' = 'true';

-- The whole Kafka value as one JSON string: one source definition serves every
-- feed and the lake keeps the exact message NiFi produced.
CREATE TEMPORARY TABLE horus_events_raw (
    payload   STRING,
    proc_time AS PROCTIME()
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

-- Envelope v2 (docs/LAKE-SCHEMA.md) parsed into lake columns. Only named
-- envelope fields are read: nothing here knows about a particular feed.
CREATE TEMPORARY VIEW horus_envelopes AS
SELECT
    COALESCE(JSON_VALUE(payload, '$.entity.source.provider'), 'unknown')  AS source_provider,
    COALESCE(JSON_VALUE(payload, '$.entity.source.originalId'),
             JSON_VALUE(payload, '$.entity.id'))                          AS original_id,
    JSON_VALUE(payload, '$.entity.id')                                    AS asset_id,
    JSON_VALUE(payload, '$.entity.source.idScheme')                       AS id_scheme,
    JSON_VALUE(payload, '$.entity.entityType')                            AS asset_type,
    JSON_VALUE(payload, '$.entity.subtype')                               AS asset_subtype,
    JSON_VALUE(payload, '$.entity.name')                                  AS display_name,
    CAST(JSON_VALUE(payload, '$.entity.position.lat') AS DOUBLE)          AS lat,
    CAST(JSON_VALUE(payload, '$.entity.position.lng') AS DOUBLE)          AS lon,
    CAST(JSON_VALUE(payload, '$.entity.position.alt') AS DOUBLE)          AS alt_m,
    JSON_VALUE(payload, '$.entity.geometry')                              AS geom_wkt,
    CAST(JSON_VALUE(payload, '$.entity.bbox[0]') AS DOUBLE)               AS shape_min_lon,
    CAST(JSON_VALUE(payload, '$.entity.bbox[1]') AS DOUBLE)               AS shape_min_lat,
    CAST(JSON_VALUE(payload, '$.entity.bbox[2]') AS DOUBLE)               AS shape_max_lon,
    CAST(JSON_VALUE(payload, '$.entity.bbox[3]') AS DOUBLE)               AS shape_max_lat,
    CAST(JSON_VALUE(payload, '$.entity.motion.speedMps') AS DOUBLE)       AS speed_mps,
    CAST(JSON_VALUE(payload, '$.entity.motion.courseDeg') AS DOUBLE)      AS course_deg,
    CAST(JSON_VALUE(payload, '$.entity.motion.headingDeg') AS DOUBLE)     AS heading_deg,
    -- Envelope times are UTC ISO-8601 with Z, to the second.
    SUBSTRING(REPLACE(REPLACE(JSON_VALUE(payload, '$.entity.timestamp'), 'T', ' '), 'Z', '')
              FROM 1 FOR 19)                                              AS event_time_s,
    SUBSTRING(REPLACE(REPLACE(JSON_VALUE(payload, '$.captured_at'), 'T', ' '), 'Z', '')
              FROM 1 FOR 19)                                              AS captured_at_s,
    JSON_VALUE(payload, '$.entity.source.feed')                           AS source_feed,
    CAST(JSON_VALUE(payload, '$.entity.source.confidence') AS DOUBLE)     AS source_confidence,
    JSON_VALUE(payload, '$.entity.classification')                        AS classification,
    JSON_VALUE(payload, '$.entity.releasability')                         AS releasability,
    JSON_VALUE(payload, '$.trace_id')                                     AS trace_id,
    JSON_VALUE(payload, '$.ingest_run_id')                                AS ingest_run_id,
    CAST(JSON_VALUE(payload, '$.schema_version') AS BIGINT)               AS schema_version,
    payload,
    proc_time
FROM horus_events_raw
WHERE JSON_VALUE(payload, '$.entity.id') IS NOT NULL
  AND JSON_VALUE(payload, '$.entity.position.lat') IS NOT NULL
  AND JSON_VALUE(payload, '$.entity.position.lng') IS NOT NULL;

-- Derived columns. tile_z8 and obs_hash use the same formulas as the Trino
-- backfill (docs/LAKE-SCHEMA.md); ssb/test checks they agree.
CREATE TEMPORARY VIEW horus_events AS
SELECT
    CONCAT(source_provider, ':', original_id)                             AS event_id,
    LOWER(SHA256(CONCAT(source_provider, ':', original_id, '|',
          CAST(UNIX_TIMESTAMP(event_time_s, 'yyyy-MM-dd HH:mm:ss') * 1000 AS STRING))))
                                                                          AS obs_hash,
    asset_id, id_scheme, asset_type, asset_subtype, display_name,
    lat, lon, alt_m,
    LEAST(GREATEST(CAST(FLOOR((lon + 180) / 360 * 256) AS INT), 0), 255) * 256
      + LEAST(GREATEST(CAST(FLOOR(
          (1 - LN(TAN(RADIANS(lat_c)) + 1 / COS(RADIANS(lat_c))) / PI()) / 2 * 256
        ) AS INT), 0), 255)                                               AS tile_z8,
    geom_wkt,
    COALESCE(shape_min_lon, lon)                                          AS bbox_min_lon,
    COALESCE(shape_min_lat, lat)                                          AS bbox_min_lat,
    COALESCE(shape_max_lon, lon)                                          AS bbox_max_lon,
    COALESCE(shape_max_lat, lat)                                          AS bbox_max_lat,
    speed_mps, course_deg, heading_deg,
    CAST(TO_TIMESTAMP(event_time_s) AS TIMESTAMP(6))                      AS event_time,
    CAST(TO_TIMESTAMP(captured_at_s) AS TIMESTAMP(6))                     AS captured_at,
    CAST(LOCALTIMESTAMP AS TIMESTAMP(6))                                  AS ingest_time,
    source_provider, source_feed, source_confidence,
    classification, releasability,
    trace_id, ingest_run_id, schema_version,
    payload,
    proc_time
FROM (
    SELECT *, GREATEST(LEAST(lat, 85.0511287798), -85.0511287798) AS lat_c
    FROM horus_envelopes
    WHERE event_time_s IS NOT NULL
);

-- One row per observation (obs_hash: event_id and event time): re-polled
-- earthquakes, fires and weather alerts, and repeated AIS reports, are dropped; a
-- moving asset's new positions are new keys and are kept. Keeping the FIRST row
-- on processing time makes the output append-only, so Iceberg needs no upserts.
INSERT INTO horus_ice.{{DATABASE}}.events_iceberg
SELECT event_id, obs_hash, asset_id, id_scheme, asset_type, asset_subtype, display_name,
       lat, lon, alt_m, tile_z8, geom_wkt,
       bbox_min_lon, bbox_min_lat, bbox_max_lon, bbox_max_lat,
       speed_mps, course_deg, heading_deg,
       event_time, captured_at, ingest_time,
       source_provider, source_feed, source_confidence,
       classification, releasability,
       trace_id, ingest_run_id, schema_version,
       payload
FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY obs_hash ORDER BY proc_time ASC) AS rn
    FROM horus_events
)
WHERE rn = 1;
