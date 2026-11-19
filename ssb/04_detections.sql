-- Horus -- continuous detection job for SQL Stream Builder (burndown 4.1).
--
-- `python provision/horus.py create --yes` fills the {{...}} tokens and submits
-- this as the job {{JOB_NAME}} in SSB project {{PROJECT}}. It reads the events
-- topic {{TOPIC}} and writes alerts to {{ALERTS_TOPIC}}. Never commit a filled-in
-- copy: it holds the workload password.
--
-- Detections (thresholds are in the views below; tune them there):
--   AIS_GAP          vessel underway (>= 3 kn) goes silent for >= 2 h and reappears
--                    near where it vanished (< 25% of the distance its speed would
--                    have covered): it stopped while dark, inside AIS coverage.
--   LOITERING        vessel reporting "under way" stays inside ~1.5 nm for >= 90 min
--                    at 0.3-2 kn average (anchored, moored and fishing are excluded).
--   STS_ENCOUNTER    two vessels, both < 2 kn and not moored, within 0.15 nm of each
--                    other over the same hour (ship-to-ship transfer pattern).
--   SPEED_JUMP       consecutive positions imply > 60 kn (vessel) or > 1000 kn
--                    (aircraft) over a real distance: spoofing or a shared identifier.
--   SQUAWK_EMERGENCY aircraft squawking 7500 (hijack), 7600 (radio failure) or
--                    7700 (emergency).
--
-- Time: detections use captured_at (when NiFi received the report). It is set
-- by every feed, it is close to real time, and odd feed timestamps (a weather
-- alert's future onset, a 24 h old earthquake) cannot move the watermark.
-- The job starts at the latest offset: it alerts on live traffic, not history.
--
-- Each alert has a stable alert_id; one alert per id is emitted (repeats of the
-- same condition within a 6 h bucket are dropped).

SET 'table.local-time-zone' = 'UTC';
SET 'table.exec.state.ttl' = '24 h';
SET 'table.exec.source.idle-timeout' = '60 s';
SET 'state.backend.type' = 'rocksdb';
SET 'state.backend.incremental' = 'true';

CREATE TEMPORARY TABLE horus_events_src (
    payload  STRING,
    event_ts AS COALESCE(
        TO_TIMESTAMP(SUBSTRING(REPLACE(REPLACE(JSON_VALUE(payload, '$.captured_at'), 'T', ' '), 'Z', '')
                     FROM 1 FOR 19)),
        TO_TIMESTAMP('1970-01-01 00:00:00')),
    WATERMARK FOR event_ts AS event_ts - INTERVAL '2' MINUTE
) WITH (
    'connector' = 'kafka',
    'topic' = '{{TOPIC}}',
    'scan.startup.mode' = 'group-offsets',
    'properties.auto.offset.reset' = 'latest',
    'format' = 'raw',
    'properties.group.id' = '{{GROUP_ID}}',
    'properties.bootstrap.servers' = '{{BROKERS}}',
    'properties.security.protocol' = 'SASL_SSL',
    'properties.sasl.mechanism' = 'PLAIN',
    'properties.sasl.jaas.config' = 'org.apache.kafka.common.security.plain.PlainLoginModule required username="{{KAFKA_USER}}" password="{{KAFKA_PASSWORD}}";'
);

CREATE TEMPORARY TABLE horus_alerts (
    alert_id           STRING,
    alert_type         STRING,
    severity           STRING,
    asset_type         STRING,
    asset_id           STRING,
    asset_name         STRING,
    related_asset_id   STRING,
    related_asset_name STRING,
    lat                DOUBLE,
    lon                DOUBLE,
    start_time         STRING,
    end_time           STRING,
    detected_at        STRING,
    metric             DOUBLE,
    metric_unit        STRING,
    summary            STRING,
    schema_version     INT
) WITH (
    'connector' = 'kafka',
    'topic' = '{{ALERTS_TOPIC}}',
    'key.format' = 'raw',
    'key.fields' = 'asset_id',
    'value.format' = 'json',
    'value.fields-include' = 'ALL',
    'sink.delivery-guarantee' = 'at-least-once',
    'properties.bootstrap.servers' = '{{BROKERS}}',
    'properties.security.protocol' = 'SASL_SSL',
    'properties.sasl.mechanism' = 'PLAIN',
    'properties.sasl.jaas.config' = 'org.apache.kafka.common.security.plain.PlainLoginModule required username="{{KAFKA_USER}}" password="{{KAFKA_PASSWORD}}";'
);

-- Position reports from moving things: vessels (aisstream PositionReport) and flights.
CREATE TEMPORARY VIEW track_points AS
SELECT
    JSON_VALUE(payload, '$.entity.entityType')                          AS asset_type,
    JSON_VALUE(payload, '$.entity.id')                                  AS asset_id,
    COALESCE(JSON_VALUE(payload, '$.entity.name'),
             JSON_VALUE(payload, '$.entity.id'))                        AS asset_name,
    CAST(JSON_VALUE(payload, '$.entity.position.lat') AS DOUBLE)        AS lat,
    CAST(JSON_VALUE(payload, '$.entity.position.lng') AS DOUBLE)        AS lon,
    CAST(COALESCE(JSON_VALUE(payload, '$.entity.properties.sog'),
                  JSON_VALUE(payload, '$.entity.properties.speed_knots')) AS DOUBLE) AS speed_kn,
    CAST(JSON_VALUE(payload, '$.entity.properties.navStatus') AS INT)   AS nav_status,
    JSON_VALUE(payload, '$.entity.properties.squawk')                   AS squawk,
    event_ts
FROM horus_events_src
WHERE JSON_VALUE(payload, '$.entity.id') IS NOT NULL
  AND JSON_VALUE(payload, '$.entity.position.lat') IS NOT NULL
  AND JSON_VALUE(payload, '$.entity.position.lng') IS NOT NULL
  AND (   (JSON_VALUE(payload, '$.entity.entityType') = 'VESSEL'
           AND JSON_VALUE(payload, '$.entity.properties.msgType') = 'PositionReport')
       OR JSON_VALUE(payload, '$.entity.entityType') = 'FLIGHT');

CREATE TEMPORARY VIEW vessel_points AS
SELECT * FROM track_points WHERE asset_type = 'VESSEL';

-- Every pair of consecutive reports for the same asset (A = previous, B = current).
CREATE TEMPORARY VIEW track_pairs AS
SELECT * FROM track_points
MATCH_RECOGNIZE (
    PARTITION BY asset_type, asset_id
    ORDER BY event_ts
    MEASURES
        B.asset_name AS asset_name,
        A.lat        AS lat1,
        A.lon        AS lon1,
        A.speed_kn   AS speed1,
        A.event_ts   AS t1,
        B.lat        AS lat2,
        B.lon        AS lon2,
        B.event_ts   AS t2
    ONE ROW PER MATCH
    AFTER MATCH SKIP TO LAST B
    PATTERN (A B)
    DEFINE B AS B.event_ts >= A.event_ts
);

-- Elapsed seconds and great-circle distance (nautical miles) between the two reports.
CREATE TEMPORARY VIEW track_steps AS
SELECT
    asset_type, asset_id, asset_name, lat1, lon1, speed1,
    CAST(t1 AS TIMESTAMP(3)) AS t1, lat2, lon2, CAST(t2 AS TIMESTAMP(3)) AS t2,
    CAST(TIMESTAMPDIFF(SECOND, t1, t2) AS DOUBLE) AS dt_s,
    3440.065 * 2 * ASIN(SQRT(LEAST(1.0,
        POWER(SIN(RADIANS(lat2 - lat1) / 2), 2)
        + COS(RADIANS(lat1)) * COS(RADIANS(lat2)) * POWER(SIN(RADIANS(lon2 - lon1) / 2), 2)))) AS dist_nm
FROM track_pairs;

-- AIS_GAP
CREATE TEMPORARY VIEW alert_ais_gap AS
SELECT
    'AIS_GAP' AS alert_type, 'MEDIUM' AS severity, asset_type, asset_id, asset_name,
    CAST(NULL AS STRING) AS related_asset_id, CAST(NULL AS STRING) AS related_asset_name,
    lat2 AS lat, lon2 AS lon, t1 AS start_ts, t2 AS end_ts,
    ROUND(dt_s / 60, 0) AS metric, 'minutes' AS metric_unit,
    CONCAT('AIS silent for ', CAST(CAST(ROUND(dt_s / 60, 0) AS INT) AS STRING), ' min while underway at ',
           CAST(ROUND(speed1, 1) AS STRING), ' kn; reappeared ', CAST(ROUND(dist_nm, 1) AS STRING),
           ' nm from where it went dark') AS summary,
    DATE_FORMAT(t2, 'yyyyMMddHHmmss') AS bucket
FROM track_steps
WHERE asset_type = 'VESSEL'
  AND dt_s >= 7200
  AND speed1 >= 3
  AND dist_nm < 0.25 * speed1 * dt_s / 3600;

-- SPEED_JUMP
CREATE TEMPORARY VIEW alert_speed_jump AS
SELECT
    'SPEED_JUMP' AS alert_type, 'MEDIUM' AS severity, asset_type, asset_id, asset_name,
    CAST(NULL AS STRING) AS related_asset_id, CAST(NULL AS STRING) AS related_asset_name,
    lat2 AS lat, lon2 AS lon, t1 AS start_ts, t2 AS end_ts,
    ROUND(dist_nm * 3600 / GREATEST(dt_s, 1.0), 0) AS metric, 'knots' AS metric_unit,
    CONCAT('Position jumped ', CAST(ROUND(dist_nm, 1) AS STRING), ' nm in ',
           CAST(CAST(dt_s AS INT) AS STRING), ' s (implied ',
           CAST(CAST(ROUND(dist_nm * 3600 / GREATEST(dt_s, 1.0), 0) AS INT) AS STRING),
           ' kn): spoofed position or shared identifier') AS summary,
    DATE_FORMAT(t2, 'yyyyMMddHH') AS bucket
FROM track_steps
WHERE (asset_type = 'VESSEL' AND dist_nm > 5    AND dist_nm * 3600 / GREATEST(dt_s, 1.0) > 60)
   OR (asset_type = 'FLIGHT' AND dist_nm > 20   AND dist_nm * 3600 / GREATEST(dt_s, 1.0) > 1000);

-- SQUAWK_EMERGENCY
CREATE TEMPORARY VIEW alert_squawk AS
SELECT
    'SQUAWK_EMERGENCY' AS alert_type,
    CASE WHEN squawk = '7600' THEN 'MEDIUM' ELSE 'HIGH' END AS severity,
    asset_type, asset_id, asset_name,
    CAST(NULL AS STRING) AS related_asset_id, CAST(NULL AS STRING) AS related_asset_name,
    lat, lon, CAST(event_ts AS TIMESTAMP(3)) AS start_ts, CAST(event_ts AS TIMESTAMP(3)) AS end_ts,
    CAST(squawk AS DOUBLE) AS metric, 'squawk' AS metric_unit,
    CONCAT('Squawk ', squawk, CASE squawk WHEN '7500' THEN ' (unlawful interference)'
                                          WHEN '7600' THEN ' (radio failure)'
                                          ELSE ' (general emergency)' END) AS summary,
    CONCAT(squawk, '-', DATE_FORMAT(event_ts, 'yyyyMMdd'),
           CAST(CAST(FLOOR(HOUR(event_ts) / 6.0) AS INT) AS STRING)) AS bucket
FROM track_points
WHERE asset_type = 'FLIGHT' AND squawk IN ('7500', '7600', '7700');

-- LOITERING: 2 h windows every 30 min.
CREATE TEMPORARY VIEW vessel_loiter_windows AS
SELECT
    asset_id,
    MAX(asset_name) AS asset_name,
    AVG(lat)                                         AS lat,
    AVG(lon)                                         AS lon,
    MIN(event_ts)                                    AS first_ts,
    MAX(event_ts)                                    AS last_ts,
    AVG(speed_kn)                                    AS avg_kn,
    window_end
FROM TABLE(HOP(TABLE vessel_points, DESCRIPTOR(event_ts), INTERVAL '30' MINUTES, INTERVAL '2' HOURS))
GROUP BY window_start, window_end, asset_id
HAVING COUNT(*) >= 10
   AND TIMESTAMPDIFF(MINUTE, MIN(event_ts), MAX(event_ts)) >= 90
   -- >= 0.3 kn: drifting or holding station; berthed ships whose AIS still says
   -- "under way" report 0.0 and are left out
   AND AVG(speed_kn) >= 0.3 AND AVG(speed_kn) < 2
   AND MAX(lat) - MIN(lat) < 0.025
   AND (MAX(lon) - MIN(lon)) * COS(RADIANS(AVG(lat))) < 0.025
   -- 0 under way, 8 sailing, 15 undefined; anything else (anchored, moored, fishing...) is excluded
   AND MAX(CASE WHEN nav_status IS NULL OR nav_status IN (0, 8, 15) THEN 0 ELSE 1 END) = 0;

CREATE TEMPORARY VIEW alert_loitering AS
SELECT
    'LOITERING' AS alert_type, 'LOW' AS severity, 'VESSEL' AS asset_type, asset_id, asset_name,
    CAST(NULL AS STRING) AS related_asset_id, CAST(NULL AS STRING) AS related_asset_name,
    lat, lon, first_ts AS start_ts, last_ts AS end_ts,
    CAST(TIMESTAMPDIFF(MINUTE, first_ts, last_ts) AS DOUBLE) AS metric, 'minutes' AS metric_unit,
    CONCAT('Reporting under way but stayed within ~1.5 nm for ',
           CAST(TIMESTAMPDIFF(MINUTE, first_ts, last_ts) AS STRING), ' min at ',
           CAST(ROUND(avg_kn, 1) AS STRING), ' kn average') AS summary,
    CONCAT(DATE_FORMAT(window_end, 'yyyyMMdd'),
           CAST(CAST(FLOOR(HOUR(window_end) / 6.0) AS INT) AS STRING)) AS bucket
FROM vessel_loiter_windows;

-- STS_ENCOUNTER: hourly summary per slow, not-moored vessel, matched on a
-- ~1.2 nm grid (each vessel is compared with its own and the 8 neighbouring cells).
CREATE TEMPORARY VIEW vessel_hours AS
SELECT
    window_start, window_end, asset_id,
    MAX(asset_name) AS asset_name,
    AVG(lat)               AS lat,
    AVG(lon)               AS lon,
    MIN(event_ts)          AS first_ts,
    MAX(event_ts)          AS last_ts,
    CAST(FLOOR(AVG(lat) / 0.02) AS BIGINT) AS cy,
    CAST(FLOOR(AVG(lon) / 0.02) AS BIGINT) AS cx
FROM TABLE(TUMBLE(TABLE vessel_points, DESCRIPTOR(event_ts), INTERVAL '1' HOUR))
GROUP BY window_start, window_end, asset_id
HAVING COUNT(*) >= 3
   AND MAX(speed_kn) < 2
   AND MAX(CASE WHEN nav_status = 5 THEN 1 ELSE 0 END) = 0;

CREATE TEMPORARY VIEW vessel_hours_near AS
SELECT v.*, y.ny, x.nx
FROM vessel_hours AS v
CROSS JOIN UNNEST(ARRAY[v.cy - 1, v.cy, v.cy + 1]) AS y (ny)
CROSS JOIN UNNEST(ARRAY[v.cx - 1, v.cx, v.cx + 1]) AS x (nx);

CREATE TEMPORARY VIEW vessel_encounters AS
SELECT
    a.asset_id, a.asset_name, b.asset_id AS other_id, b.asset_name AS other_name,
    (a.lat + b.lat) / 2 AS lat, (a.lon + b.lon) / 2 AS lon,
    GREATEST(a.first_ts, b.first_ts) AS start_ts, LEAST(a.last_ts, b.last_ts) AS end_ts,
    a.window_end,
    3440.065 * 2 * ASIN(SQRT(LEAST(1.0,
        POWER(SIN(RADIANS(b.lat - a.lat) / 2), 2)
        + COS(RADIANS(a.lat)) * COS(RADIANS(b.lat)) * POWER(SIN(RADIANS(b.lon - a.lon) / 2), 2)))) AS dist_nm
FROM vessel_hours_near AS a
JOIN vessel_hours AS b
  ON a.window_start = b.window_start AND a.ny = b.cy AND a.nx = b.cx AND a.asset_id < b.asset_id;

CREATE TEMPORARY VIEW alert_sts AS
SELECT
    'STS_ENCOUNTER' AS alert_type, 'MEDIUM' AS severity, 'VESSEL' AS asset_type, asset_id, asset_name,
    other_id AS related_asset_id, other_name AS related_asset_name,
    lat, lon, start_ts, end_ts,
    ROUND(dist_nm * 1852, 0) AS metric, 'meters' AS metric_unit,
    CONCAT('Alongside ', other_name, ' (', other_id, '), ', CAST(CAST(ROUND(dist_nm * 1852, 0) AS INT) AS STRING),
           ' m apart, both under 2 kn') AS summary,
    CONCAT(other_id, '-', DATE_FORMAT(window_end, 'yyyyMMdd'),
           CAST(CAST(FLOOR(HOUR(window_end) / 6.0) AS INT) AS STRING)) AS bucket
FROM vessel_encounters
WHERE dist_nm < 0.15;

CREATE TEMPORARY VIEW all_alerts AS
SELECT *, PROCTIME() AS proc_time,
       CONCAT(alert_type, ':', asset_type, ':', asset_id, ':', bucket) AS alert_id
FROM (
    SELECT * FROM alert_ais_gap
    UNION ALL SELECT * FROM alert_speed_jump
    UNION ALL SELECT * FROM alert_squawk
    UNION ALL SELECT * FROM alert_loitering
    UNION ALL SELECT * FROM alert_sts
);

INSERT INTO horus_alerts
SELECT
    alert_id, alert_type, severity, asset_type, asset_id, asset_name,
    related_asset_id, related_asset_name, lat, lon,
    DATE_FORMAT(start_ts, 'yyyy-MM-dd''T''HH:mm:ss''Z''') AS start_time,
    DATE_FORMAT(end_ts,   'yyyy-MM-dd''T''HH:mm:ss''Z''') AS end_time,
    DATE_FORMAT(proc_time, 'yyyy-MM-dd''T''HH:mm:ss''Z''') AS detected_at,
    CAST(metric AS DOUBLE) AS metric, metric_unit, summary, 1 AS schema_version
FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY alert_id ORDER BY proc_time ASC) AS rn
    FROM all_alerts
)
WHERE rn = 1;
