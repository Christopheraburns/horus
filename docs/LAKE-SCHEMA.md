# Lake schema v2

The events table is Horus's one generic observations table: every report from
every feed, one row each. This note defines version 2 of the table and of the
canonical envelope it is built from (burndown section 16).

Rules:

- **One generic table.** No resolved entity ids and no entity attributes: the
  ontology owns those (ONTOLOGY_PLAN.md). Typed views per asset type come later
  from the Helios semantic model (O0b).
- **Flink stays generic.** The lake job reads named envelope fields and nothing
  feed-specific. Anything that writes the envelope to the events topic can feed
  Horus (DEPLOYMENT-MODEL.md), so meaning has to be in the envelope, not in
  per-provider rules in the job. The per-feed rules below exist only to backfill
  old rows (16.5).
- **The payload stays loss-less.** The full message is kept as `payload` for
  replay and for fields that have no column.

## Envelope v2

Version 2 is additive: every v1 field keeps its name and meaning, except
`entity.position.alt`, which is corrected. The gateway's reshapers read
`entity.properties` and keep working unchanged.

```json
{
  "schema_version": 2,
  "ingest_run_id": "...",
  "trace_id": "...",
  "captured_at": "2026-11-19T18:02:11Z",
  "entity": {
    "id": "636019825",
    "name": "PACIFIC TRADER",
    "entityType": "VESSEL",
    "subtype": "tanker",
    "domain": "SEA",
    "timestamp": "2026-11-19T18:01:58Z",
    "position": {"lat": 26.41, "lng": 56.22, "alt": null},
    "motion": {"speedMps": 6.43, "courseDeg": 112.0, "headingDeg": 110.0},
    "geometry": null,
    "bbox": null,
    "classification": "UNCLASSIFIED",
    "releasability": null,
    "confidence": 0.9,
    "source": {
      "provider": "aisstream.io", "feed": "vessels",
      "originalId": "636019825", "idScheme": "mmsi", "confidence": 0.9
    },
    "properties": {"mmsi": 636019825, "sog": 12.5, "cog": 112.0, "heading": 110}
  }
}
```

| Field | New in v2 | Meaning |
|---|---|---|
| `entity.timestamp` | | When the source observed it, not when NiFi received it (16.3). UTC, ISO-8601 with `Z`, to the second, like `captured_at` |
| `entity.position.alt` | Corrected | Metres above sea level as the source reports it (barometric for aircraft). `null` when not measured: vessels, fires, weather. USGS depth moves out of `alt` and stays in `properties.depth` |
| `entity.subtype` | Yes | The feed's own category: flight category (`commercial`, `private`, `jet`, `military`), vessel type (`cargo`, `tanker`, `military`, ...), weather category, fire type. Optional |
| `entity.motion.speedMps` | Yes | Speed over ground, metres per second |
| `entity.motion.courseDeg` | Yes | Course (track) over ground, degrees true |
| `entity.motion.headingDeg` | Yes | Where the bow or nose points, degrees true; `null` when not reported (AIS 511) |
| `entity.geometry` | Yes | WKT for a shape (a weather alert's polygon); `null` for a point |
| `entity.bbox` | Yes | `[minLon, minLat, maxLon, maxLat]` of `geometry`; required when `geometry` is set |
| `entity.releasability` | Yes | Who the record may be shared with (section 13); beside the existing `classification` |
| `entity.source.idScheme` | Yes | What kind of identifier `entity.id` is: `mmsi`, `icao24`, `callsign`, or a provider namespace (`usgs`, `firms`, `eonet`, `nws`, `hormuz.now`) |

Each NiFi script (`nifi/scripts/`, embedded into the flows by
`tools/sync_scripts.py`) maps its feed's fields into these, and
`nifi/test/run.sh` checks every script's output against this contract. For example, aisstream maps
`Sog` (knots) to `speedMps` and its ship type code to `subtype`, and adsb.lol
maps `track` to `courseDeg` (aircraft feeds report no heading).

## Table v2

`events_iceberg`, Iceberg format v2, Parquet with zstd.

| Column | Type | From | Notes |
|---|---|---|---|
| `event_id` | string | `source.provider` + `:` + `source.originalId` (else `entity.id`) | The feed's id for what it reported, prefixed so two feeds can't collide. With `event_time`, identifies a report |
| `obs_hash` | string | see below | Stable row id; the dedupe key |
| `asset_id` | string | `entity.id` | Shared across feeds for the same vessel or aircraft (MMSI, ICAO hex) |
| `id_scheme` | string | `source.idScheme` | |
| `asset_type` | string | `entity.entityType` | `FLIGHT`, `VESSEL`, `SEISMIC`, `FIRE`, `WEATHER` |
| `asset_subtype` | string | `entity.subtype` | |
| `display_name` | string | `entity.name` | As reported for this observation (names change) |
| `lat`, `lon` | double | `entity.position` | Representative point, always set |
| `alt_m` | double | `entity.position.alt` | |
| `tile_z8` | int | lat, lon | Web Mercator tile at zoom 8, see below |
| `geom_wkt` | string | `entity.geometry` | |
| `bbox_min_lon`, `bbox_min_lat`, `bbox_max_lon`, `bbox_max_lat` | double | `entity.bbox`, else the point | Set on every row, so one predicate finds points and shapes |
| `speed_mps`, `course_deg`, `heading_deg` | double | `entity.motion` | |
| `event_time` | timestamp(6) | `entity.timestamp` | UTC |
| `captured_at` | timestamp(6) | `captured_at` | When NiFi fetched it (was a string) |
| `ingest_time` | timestamp(6) | Flink's clock | When the lake job wrote it |
| `source_provider`, `source_feed` | string | `entity.source` | |
| `source_confidence` | double | `entity.source.confidence` | |
| `classification`, `releasability` | string | `entity` | Ranger row filters read these (13.5) |
| `trace_id`, `ingest_run_id` | string | envelope | |
| `schema_version` | bigint | envelope | 1 for backfilled rows, 2 after |
| `payload` | string | the whole message | |

**Partitioning and order.** Partitioned by `day(event_time)`; sort order
`tile_z8, event_time`. Flink appends unsorted; the maintenance job (16.6)
rewrites each day's files in sort order. Sorted files cover narrow ranges of
`lat`, `lon` and the bounding box, so Trino skips files on those predicates
directly. Queries filter on coordinates, not on `tile_z8`; the tile only clusters
nearby rows into the same files.

**`tile_z8`.** The tile column `x` times 256 plus the tile row `y`, both 0 to 255.
Flink SQL and Trino have the same functions, so the expression is the same in
both (16.7 checks they agree):

```sql
-- lat_c = GREATEST(LEAST(lat, 85.0511287798), -85.0511287798)
x = LEAST(GREATEST(CAST(FLOOR((lon + 180) / 360 * 256) AS INT), 0), 255)
y = LEAST(GREATEST(CAST(FLOOR(
      (1 - LN(TAN(RADIANS(lat_c)) + 1 / COS(RADIANS(lat_c))) / PI()) / 2 * 256
    ) AS INT), 0), 255)
tile_z8 = x * 256 + y
```

**`obs_hash`.** Lowercase hex SHA-256 of `event_id || '|' || epoch milliseconds
of event_time`. Only a string and an integer go in, because engines format
doubles differently. It replaces Flink's current dedupe key
(`event_id, event_time`) with the same meaning, and gives the migration (16.5)
and the ontology's observation references a single stable row id.

**Sketch of the Trino DDL** (16.2 makes it exact):

```sql
CREATE TABLE iceberg.horus.events_iceberg (... columns above ...)
WITH (format = 'PARQUET', format_version = 2,
      partitioning = ARRAY['day(event_time)'],
      sorted_by = ARRAY['tile_z8', 'event_time']);
-- plus write.parquet.compression-codec = zstd (see open checks)
```

## Backfill from v1 payloads (16.5 only)

Old rows have no v2 fields. The migration (`provision/migrate_lake.py`) derives
them from `payload` with these rules, read from the NiFi scripts as of
2026-11-19. Flink never uses them. Rows whose payload is already envelope v2
(written after `update-scripts`, before the migration) take the v2 fields exactly
as the Flink job does; rows from before the full-payload change (a flat
`{"name": ...}` payload) keep their columns and get the point as their bounding
box.

| Column | Rule |
|---|---|
| `alt_m` | `FLIGHT`: `position.alt`. Everything else: null (USGS `alt` is depth in km; vessels carry a placeholder 0) |
| `speed_mps` | `FLIGHT`: `properties.speed_knots` × 0.514444. `VESSEL`: `properties.sog` × 0.514444 |
| `course_deg` | `FLIGHT`: `properties.heading` (it is the track). `VESSEL`: `properties.cog` |
| `heading_deg` | `VESSEL`: `properties.heading`, null when 511. `FLIGHT`: null |
| `asset_subtype` | `VESSEL`: `properties.type`, else the AIS `shipType` code (80–89 tanker, 35 military, other non-zero cargo). `FLIGHT`, `WEATHER`: `properties.category`. `FIRE`: `properties.firetype`. `SEISMIC`: null |
| `id_scheme` | aisstream.io: `mmsi`. hormuz.now: `mmsi`, or `hormuz.now` when `asset_id` starts `hormuz.now:`. opensky: `icao24`. adsb.lol: `icao24` when `asset_id` is a six-digit hex address, `adsb.lol` when it starts with `~` (a non-ICAO address), else `callsign`. USGS `usgs`, NASA-FIRMS `firms`, NASA EONET and NASA-EONET `eonet`, NOAA/NWS `nws` |
| `releasability` | null |
| precision | v1 flights kept the track rounded to whole degrees (a missing track as 0, which the backfill can't tell from north), speed to 0.1 knot, and no true heading; v1 hormuz.now headings fell back to the course when not reported. These stay as v1 recorded them |
| `event_time` | NOAA/NWS: `properties.date` converted to UTC (see below). Everything else: as v1 |
| everything else | the same paths as v2, all present in v1 |

## Found while writing this

Each is fixed by v2 or by its backfill rule:

- **USGS depth in `position.alt`.** As v1 stores it, an earthquake 10 km down
  has an altitude of 10.
- **Flight "heading" is the track.** adsb.lol `track` and OpenSky `true_track`
  are stored as `properties.heading`.
- **EONET volcanoes lose a row.** EONET sends each volcano twice, as a weather
  event and as a fire, with the same `originalId` and time, so today's dedupe key
  keeps only one. The provider prefix in `event_id` (`NASA EONET` and
  `NASA-EONET`) keeps both. Seen in the code, not yet confirmed in the data.
- **Receive time as event time.** aisstream (16.3) and also adsb.lol (whose
  `seen_pos` gives the position's age) stamp `entity.timestamp` with the time NiFi
  received the report.
- **NWS times off by the local offset.** NWS sends `effective` with a local
  offset (`2025-11-19T17:00:00-06:00`); the lake job cuts it to 19 characters and
  reads it as UTC, so an alert lands 4 to 10 hours early. The NWS script now
  converts to UTC; backfilled NWS rows are corrected from `properties.date`.

## Tests

Run locally with Docker, no platform needed:

| Test | Checks |
|---|---|
| `nifi/test/run.sh` | Every NiFi script, on sample input for its feed, meets envelope v2 and gives the expected values |
| `ssb/test/run_lake_local.sh` | The lake job's views and dedupe (Flink 1.19) turn those envelopes, a duplicate and a v1 message into rows that match a Python reference column by column |
| `ssb/test/run_migration_local.sh` | The migration on Trino 460: a v1 table filled from the v1 scripts (git `7f1c2dd`) and the v2 scripts, as the v1 job wrote it; every row kept; v2-payload rows equal the Flink job's; v1-payload rows equal their v2 twins within the precision v1 kept; re-run, partial-day redo and swap; the gateway's Time Travel query before and after |
| `ssb/test/run_trino_local.sh` | `provision/lake.py` on Trino 460: the v2 DDL is accepted, a v1 table is detected and left alone, and Trino's `tile_z8` and `obs_hash` (`lake.TILE_Z8_SQL`, `lake.OBS_HASH_SQL`, used by the backfill) agree with Flink's on every row |

## Open checks

- **zstd, settled 2026-11-19:** Trino writes its own codec (ZSTD by default) into
  the table property `write.parquet.compression-codec` on `CREATE TABLE`, and
  the Flink writer reads that property. Trino 460 has no `extra_properties`, so
  `lake.py` only falls back to printing an Impala statement if the CDW Trino is
  configured with another codec.
- **The SSB Flink Iceberg sink on a partitioned format-v2 table:** first seen
  on the platform when the migration (16.5) starts the v2 job.
- **Compaction applying `sorted_by`** (16.6): whether CDW Trino's
  `ALTER TABLE ... EXECUTE optimize` applies the sort order. If it doesn't, the
  maintenance job uses Spark's `rewrite_data_files` with the sort strategy.
