-- Horus -- raw capture: the raw topic -> the bronze table (burndown 17.4).
--
-- `python provision/horus.py create --yes` fills the {{...}} tokens and submits
-- this as the job {{JOB_NAME}} in SSB project {{PROJECT}}. Never commit a
-- filled-in copy: it holds the workload password.
--
-- Each message is one upstream response exactly as NiFi received it (the flow's
-- second PublishKafka, provision/raw_capture.py): the key names the flow, the
-- value is the body, the headers carry InvokeHTTP's URL, status and content
-- type, and the Kafka timestamp is when NiFi published it, just after receipt.
--
-- Prerequisites: the table {{DATABASE}}.raw_responses (created through Trino) and
-- the same Ranger policies as the events job, plus Consume on the raw topic.

SET 'table.local-time-zone' = 'UTC';
-- An identical body from the same flow within 36 h is stored once (an unchanged
-- hormuz.now snapshot, a re-sent USGS or FIRMS file). Keep-first deduplication
-- keeps only a flag per key in state, not the body.
SET 'table.exec.state.ttl' = '36 h';
SET 'state.backend.type' = 'rocksdb';
SET 'state.backend.incremental' = 'true';

CREATE TEMPORARY TABLE horus_raw_in (
    flow            STRING,
    body            STRING,
    headers         MAP<STRING, BYTES>      METADATA FROM 'headers'   VIRTUAL,
    kafka_ts        TIMESTAMP_LTZ(3)        METADATA FROM 'timestamp' VIRTUAL,
    kafka_partition INT                     METADATA FROM 'partition' VIRTUAL,
    kafka_offset    BIGINT                  METADATA FROM 'offset'    VIRTUAL,
    proc_time AS PROCTIME()
) WITH (
    'connector' = 'kafka',
    'topic' = '{{TOPIC}}',
    'scan.startup.mode' = 'group-offsets',
    'properties.auto.offset.reset' = 'earliest',
    'key.format' = 'raw',
    'key.fields' = 'flow',
    'value.format' = 'raw',
    'value.fields-include' = 'EXCEPT_KEY',
    -- Whole responses: FIRMS's CSV is about 6 MB (1.5 MB compressed).
    'properties.max.partition.fetch.bytes' = '33554432',
    'properties.group.id' = '{{GROUP_ID}}',
    'properties.bootstrap.servers' = '{{BROKERS}}',
    'properties.security.protocol' = 'SASL_SSL',
    'properties.sasl.mechanism' = 'PLAIN',
    'properties.sasl.jaas.config' = 'org.apache.kafka.common.security.plain.PlainLoginModule required username="{{KAFKA_USER}}" password="{{KAFKA_PASSWORD}}";'
);

CREATE CATALOG horus_ice WITH (
    'type' = 'iceberg',
    'catalog-type' = 'hive',
    'hive-conf-dir' = '/etc/hive/conf'
);

CREATE TEMPORARY VIEW horus_raw AS
SELECT
    COALESCE(flow, 'unknown')                                              AS flow,
    CAST(headers['invokehttp.request.url'] AS STRING)                      AS source_url,
    TRY_CAST(CAST(headers['invokehttp.status.code'] AS STRING) AS INT)     AS http_status,
    CAST(headers['mime.type'] AS STRING)                                   AS content_type,
    CAST(kafka_ts AS TIMESTAMP(6))                                         AS received_at,
    CAST(LOCALTIMESTAMP AS TIMESTAMP(6))                                   AS ingest_time,
    LOWER(SHA256(body))                                                    AS body_sha256,
    CAST(CHAR_LENGTH(body) AS BIGINT)                                      AS body_chars,
    body,
    kafka_partition,
    kafka_offset,
    proc_time
FROM horus_raw_in
WHERE body IS NOT NULL;

INSERT INTO horus_ice.{{DATABASE}}.raw_responses
SELECT flow, source_url, http_status, content_type, received_at, ingest_time,
       body_sha256, body_chars, body, kafka_partition, kafka_offset
FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY flow, body_sha256 ORDER BY proc_time ASC) AS rn
    FROM horus_raw
)
WHERE rn = 1;
