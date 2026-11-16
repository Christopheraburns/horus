-- Run in Hue / Impala once the SSB job has completed a checkpoint or two.
INVALIDATE METADATA horus.events_iceberg;
SELECT source_feed, COUNT(*) AS n, MIN(event_time) AS first_event, MAX(event_time) AS last_event
FROM horus.events_iceberg GROUP BY source_feed ORDER BY n DESC;
-- name must resolve from the full payload (TimeTravel labels depend on it):
SELECT asset_id, get_json_object(payload, '$.entity.name') AS name, event_time
FROM horus.events_iceberg ORDER BY event_time DESC LIMIT 10;
