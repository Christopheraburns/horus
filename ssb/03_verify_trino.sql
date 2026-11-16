-- Run in Hue against the Trino virtual warehouse once the SSB job has completed
-- a checkpoint or two. Trino reads Iceberg metadata on every query, so no
-- REFRESH / INVALIDATE METADATA is needed. Replace horus_<id> with your database.
SELECT source_feed, COUNT(*) AS n, MIN(event_time) AS first_event, MAX(event_time) AS last_event
FROM iceberg.horus_<id>.events_iceberg GROUP BY source_feed ORDER BY n DESC;
-- name must resolve from the full payload (TimeTravel labels depend on it):
SELECT asset_id, json_extract_scalar(payload, '$.entity.name') AS name, event_time
FROM iceberg.horus_<id>.events_iceberg ORDER BY event_time DESC LIMIT 10;
