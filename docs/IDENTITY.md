# Entity identity rules (burndown O0a)

How Horus recognises the same vessel, aircraft or event across reports and feeds,
written as the ontology plan's declared identity keys
([ONTOLOGY_PLAN.md, Identity keys](ONTOLOGY_PLAN.md#identity-keys)) so that
Helios's resolution code needs no maritime or aviation logic. Consumers: entity
tables (burndown 4.5), the detections job's keys, the entity index (O5) and entity
resolution (O12).

## Principles

1. **An entity's primary key is its own.** `vesselId` and `aircraftId` are ids Horus
   mints (a ULID), never an MMSI, IMO or ICAO address. Every outside identifier can
   be missing, wrong, reused or changed; an entity outlives all of them.
2. **Reports carry claims, not entities.** A position report says "MMSI 636019825
   was here at 10:02". The lake keeps that claim as reported (`asset_id`,
   `id_scheme`) and never rewrites it. Which entity it belongs to is resolved
   *through* the identity keys, at the report's time, and can be re-resolved when
   the rules or the evidence change. This is why `events` holds no entity ids.
3. **Identifiers are valid for a time.** The entity index keeps one identifier row
   per (entity, scheme, value) with `valid_from` and `valid_to`. An MMSI that moved
   from one ship to another resolves differently before and after the move.
4. **A value is checked before it is trusted.** Each scheme has a value type with
   its own check (format, check digit, reserved ranges, known junk values). A value
   that fails is not an identifier; the report is resolved by its provider's own id,
   or not at all.
5. **The source caps the strength.** A strong key reported by a source that can't
   vouch for it behaves as weak. AIS static data is typed in by the crew, so an IMO
   from AIS proposes; an IMO from a register links.
6. **Conflicts are flagged, never resolved silently.** Two entities claiming the
   same exclusive value at the same time, or one entity with two different values of
   a permanent key, become a review item (a SameAsAssertion or an identity conflict),
   not a merge.

## The fields

The plan's four fields, plus one this document proposes:

| Field | Values | Meaning |
|---|---|---|
| `scheme` | e.g. `mmsi` | The kind of identifier; a value is unique within its scheme and scope |
| `strength` | `strong`, `weak` | A strong match links on its own; a weak match only proposes |
| `scope` | `global`, or a qualifier (`provider`, `manufacturer`) | Where a value is unique |
| `validity` | `permanent`, `reassignable` | Whether a value can move to another instance over time |
| `exclusive` (**proposed**) | `true` (default), `false` | Whether a value names at most one instance *at any moment*. `reassignable` says a value can move between instances over time; it doesn't say what to do when two instances use it at once. AIS shows this happens (shared and spoofed MMSIs), and a factory sees it too (one serial printed on two parts) |

`exclusive` needs a small change to the plan's identity keys (O2, S1). Until then
the rules below treat every strong key as exclusive.

## Vessel

Primary key `vesselId`. Title: the current name.

| Scheme | Strength | Scope | Validity | Exclusive | Value check | Notes |
|---|---|---|---|---|---|---|
| `imo` | strong | global | permanent | yes | 7 digits; check digit: digits 1–6 weighted 7, 6, 5, 4, 3, 2, sum mod 10 = digit 7 | The hull's number for life, through every sale, rename and reflag. Ships of 100 GT and over have one, and fishing vessels of 12 m and over can; small craft and most yachts don't. **From AIS it is crew-entered, so it proposes (principle 5)**; from a register it links |
| `mmsi` | strong | global | reassignable | yes | 9 digits; first digits a maritime identification digit, 201–775, for ships. Not a ship: `00…` coast stations, `111…` SAR aircraft, `970`/`972`/`974` SART, MOB and EPIRB devices, `98…` craft of a parent ship, `99…` aids to navigation. Junk: `000000000`, `111111111`, `123456789`, `999999999` and the like | The radio's number. Changes when a ship is reflagged or sold, is reissued to another ship later, and is often shared or spoofed. The key the live feeds have |
| `callSign` | weak | global | reassignable | no | 3–7 letters and digits | Changes with the flag |
| `vesselName` | weak | global | reassignable | no | non-empty after trimming | Not unique and changes; a tie-breaker and a search key only |
| `hormuz.now` | strong | provider | reassignable | yes | hormuz.now's own vessel id | Links reports *within* hormuz.now; says nothing about other feeds. Used when a hormuz.now vessel has no valid MMSI, and to tell apart the vessels behind a shared MMSI (below) |

**Anchors.** A vessel with a register-backed IMO is anchored by it: an MMSI that
moves away from it ends its MMSI row, the vessel stays. A vessel with no IMO is
anchored by its MMSI for as long as the MMSI isn't reassigned or contested; when it
is, the vessel keeps its id and the MMSI row ends.

**The real case: one MMSI, two vessels.** On 2026-11-19 hormuz.now showed 4 MMSIs
each used by two different hormuz.now vessels at once: different hormuz.now ids,
reporting positions too far apart for one hull. Today they merge into one asset (the
lake and the map key on MMSI), so one "vessel" jumps between two places and the
detections job sees impossible speeds. Under these rules:

- each hormuz.now id is its own entity, linked by the strong, provider-scoped key;
- the MMSI is exclusive, so both can't hold it: the identifier row is marked
  **contested** for the overlap, and an identity conflict goes to review with both
  tracks as evidence;
- while it is contested, an MMSI-only report (aisstream, which has no other id)
  resolves to neither and proposes; the analyst's decision (which vessel is the real
  holder, or a spoofer) is an action that ends the contest.

Detecting "at once" is a generic rule: two claims of an exclusive value, by two
entities, within a time window (declared per scheme; for MMSI, the same 10 minutes),
whose positions imply an impossible speed for the type (declared on the object type;
for a vessel, 50 knots).

## Aircraft

Primary key `aircraftId`. Title: the registration.

| Scheme | Strength | Scope | Validity | Exclusive | Value check | Notes |
|---|---|---|---|---|---|---|
| `msn` | strong | manufacturer and type | permanent | yes | as the register gives it | The airframe's serial number for life. Not in any live feed: from the offline aircraft database (burndown 12.3) |
| `icao24` | strong | global | reassignable | yes | 6 hex digits; not `000000` or `ffffff` | The transponder address, assigned with the registration. Changes on re-registration to another state, and is reissued. US privacy addresses (PIA) are temporary by design |
| `registration` | strong | global | reassignable | yes | the register's format, e.g. `N123AB`, `G-ABCD` | Changes on re-registration; US N-numbers are reissued |
| `adsb.lol` | weak | provider | reassignable | no | adsb.lol addresses starting `~` | Non-ICAO addresses (TIS-B and others): links reports within a short window at most, never to an aircraft |

**Not an aircraft key: the callsign.** `UAL123` names a flight, and the same
aircraft flies under many callsigns in a day. It belongs to a future Flight
occurrence. Reports today keyed only by callsign (`id_scheme = callsign`, adsb.lol
with no address) can't be linked to an aircraft.

**Anchors.** `msn` when the offline database has the airframe; else `icao24` until
it's reassigned.

## Events from the other feeds

Earthquakes, weather alerts, EONET events and fires are occurrences, not
long-lived assets, and each feed names them its own way:

| Type | Scheme | Strength, scope, validity | Notes |
|---|---|---|---|
| Earthquake | `usgs` | strong, provider, permanent | USGS can merge two network ids into one event and change the preferred id; the event's `ids` list is the set of keys, all strong |
| Weather alert | `nws` | strong, provider, permanent | An update is a new alert that references the earlier one: a link (supersedes), not a shared key |
| EONET event | `eonet` | strong, provider, permanent | One EONET event can be both a weather event and a fire; one entity, two observation types |
| Fire detection | none | | A FIRMS detection has no id and no identity beyond its place and time: an observation, not an entity |

## How this is used

**The lake.** `asset_id` and `id_scheme` stay as reported (principle 2). Entity
tables (4.5) hold one row per entity plus the identifier rows: (entity, scheme,
value, valid from, valid to, source, confidence, status `active`, `contested` or
`ended`). A report finds its entity by (`id_scheme`, `asset_id`) at `event_time`.

**Detections** (`ssb/04_detections.sql`). Detections run on the live stream, before
resolution, so they key on the claim, not the entity. Two changes follow:

- key on (`id_scheme`, `asset_id`), not `asset_id` alone, so a provider id can never
  collide with an MMSI;
- key on the most specific claim a report carries: for hormuz.now, its own vessel
  id ahead of the MMSI. That alone removes the impossible-speed alerts from shared
  MMSIs.

An alert then becomes an Alert entity through an action by a machine actor (O7);
that action resolves the claim to an entity at the alert's time, and an alert on a
contested identifier says so.

**Entity resolution** (O12), driven only by these declarations:

| Evidence | Result |
|---|---|
| A strong key, valid, from a source that can vouch for it, held by one entity at that time | link |
| A strong key no entity holds | a provisional entity with that key |
| A strong key from a source that can't vouch for it (an IMO from AIS) | proposal |
| A weak key (name, call sign) | proposal |
| An exclusive key claimed by two entities at once | contested; a conflict to review |
| One entity with two values of a permanent key | a conflict to review |
| A value that fails its check | not an identifier; resolve by the provider's id if there is one |

## Evidence to gather from the lake

The rules above rest on these; run them in Hue (`iceberg.horus_dev.events_iceberg`)
over a few days and record the answers here. They are the first use of the lake as
evidence for the ontology (O0b).

```sql
-- 1. How often a vessel report carries an IMO, per source.
SELECT source_provider, COUNT(*) AS reports,
       COUNT(json_extract_scalar(payload, '$.entity.properties.imo')) AS with_imo
FROM iceberg.horus_dev.events_iceberg WHERE asset_type = 'VESSEL' GROUP BY 1;

-- 2. MMSIs seen with more than one name (renames, or shared MMSIs).
SELECT asset_id, COUNT(DISTINCT display_name) AS names, array_agg(DISTINCT display_name) AS seen
FROM iceberg.horus_dev.events_iceberg
WHERE id_scheme = 'mmsi' AND display_name IS NOT NULL
GROUP BY 1 HAVING COUNT(DISTINCT display_name) > 1 ORDER BY names DESC LIMIT 50;

-- 3. MMSIs used by more than one hormuz.now vessel (the shared-MMSI case).
SELECT asset_id, COUNT(DISTINCT json_extract_scalar(payload, '$.entity.properties.hormuz_id')) AS vessels
FROM iceberg.horus_dev.events_iceberg
WHERE source_provider = 'hormuz.now' AND id_scheme = 'mmsi'
GROUP BY 1 HAVING COUNT(DISTINCT json_extract_scalar(payload, '$.entity.properties.hormuz_id')) > 1;

-- 4. IMOs seen with more than one MMSI (reflags, or a wrong IMO typed in).
SELECT json_extract_scalar(payload, '$.entity.properties.imo') AS imo, COUNT(DISTINCT asset_id) AS mmsis,
       array_agg(DISTINCT asset_id) AS seen
FROM iceberg.horus_dev.events_iceberg
WHERE json_extract_scalar(payload, '$.entity.properties.imo') IS NOT NULL
GROUP BY 1 HAVING COUNT(DISTINCT asset_id) > 1;

-- 5. MMSIs that aren't ships, or are junk (fail the value check).
SELECT substr(asset_id, 1, 3) AS prefix, COUNT(DISTINCT asset_id) AS mmsis
FROM iceberg.horus_dev.events_iceberg
WHERE id_scheme = 'mmsi' AND NOT COALESCE(TRY_CAST(substr(asset_id, 1, 3) AS INTEGER) BETWEEN 201 AND 775, false)
GROUP BY 1 ORDER BY mmsis DESC;

-- 6. ICAO addresses seen with more than one registration (adsb.lol carries both).
SELECT asset_id, array_agg(DISTINCT json_extract_scalar(payload, '$.entity.properties.registration')) AS regs
FROM iceberg.horus_dev.events_iceberg
WHERE source_provider = 'adsb.lol' AND id_scheme = 'icao24'
  AND json_extract_scalar(payload, '$.entity.properties.registration') NOT IN ('N/A', '')
GROUP BY 1 HAVING COUNT(DISTINCT json_extract_scalar(payload, '$.entity.properties.registration')) > 1;
```

## Open questions

1. **`exclusive` in the plan.** Accept the fifth field (O2), or express "at once"
   some other way?
2. **Who vouches for an IMO.** Which sources count as a register for principle 5:
   the offline reference data (12.x), a customer's vessel register, an analyst's
   confirmation? Until one exists, every IMO proposes.
3. **The "at once" window and speed limits** (10 minutes; 50 knots for a vessel, a
   value for aircraft) are declarations on the scheme and type. Check them against
   query 3's vessels before fixing them.
