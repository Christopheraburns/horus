# Entity identity rules (burndown O0a)

How Horus recognises the same vessel, aircraft or event across reports and feeds,
written as the ontology plan's declared identity keys
([Helios's ontology plan, Identity keys](https://github.com/Christopheraburns/helios/blob/main/docs/ontology-plan.md#identity-keys)).

The rules are in three parts, one per home, following the plan's layering (core,
packs, extensions; [Helios's ontology plan, Layers and packs](https://github.com/Christopheraburns/helios/blob/main/docs/ontology-plan.md#layers-and-packs)). The test for
where a rule goes: **would a car manufacturer need it?** If yes, it is a Helios
mechanism. If only someone tracking ships or aircraft would, it belongs in a pack.
If only this deployment would (its feeds, its sources, its jobs), it belongs in the
Horus extension.

| Part | Home | Built in | Holds |
|---|---|---|---|
| [A. Mechanism](https://github.com/Christopheraburns/helios/blob/main/docs/ontology-identity.md) (in the Helios repo) | Helios core | O2 (S1, identity keys), O5 (S4, entity index), O12 (S11, resolution) | What identity keys are, how identifiers are stored over time, how resolution decides. Names no domain |
| [B. Domain packs](#b-the-domain-packs-packsmaritime-packsaviation) | `packs/maritime`, `packs/aviation` (in Horus first; may move to Helios as shared packs) | O14 (S13) | The Vessel and Aircraft types, their schemes, value checks and limits. True for anyone tracking ships or aircraft |
| [C. Horus extension](#c-the-horus-extension) | Horus | O13, O14, 4.5 | This deployment's feeds and their schemes, which sources are trusted, the event types, the lake and the detections job |

Consumers: entity tables (4.5), the detections job, the entity index (O5) and entity
resolution (O12).

---

## A. The mechanism (Helios core)

Moved to Helios on 2026-11-20: [ontology-identity.md](https://github.com/Christopheraburns/helios/blob/main/docs/ontology-identity.md). It holds the six
principles (an entity's own primary key; observations carry claims; identifiers
valid for a time; values checked before they are trusted; the source caps the
strength; conflicts flagged, never resolved silently), the identity key fields
(with `exclusive` and `concurrencyWindow`), identifier rows, the resolution rules,
and the decisions on both open questions (the two fields accepted; source trust
declared on each source with `vouchesFor`). Parts B and C below are what Horus
declares through it.

---

## B. The domain packs (`packs/maritime`, `packs/aviation`)

What anyone tracking ships or aircraft would share. Each scheme's value check is a
function the pack supplies to the core's check hook (principle 4).

### Vessel (`packs/maritime`)

An **IMO number** is the ship identification number of the International Maritime
Organization (the UN shipping agency): seven digits, issued to the hull, kept through
every sale, rename and reflag, and painted on the ship. Ships of 100 GT and over have
one, and fishing vessels of 12 m and over can; small craft and most yachts don't. An
**MMSI** is the number of a ship's radio, used by AIS.

Primary key `vesselId`. Title: the current name. Implements `Located`; `maxSpeed`
50 knots.

| Scheme | Strength | Scope | Validity | Exclusive | Value check | Notes |
|---|---|---|---|---|---|---|
| `imo` | strong | global | permanent | yes | 7 digits; digits 1 to 6 weighted 7, 6, 5, 4, 3, 2, and the sum's last digit is digit 7. Junk even though some pass the check: `1234567`, `1111111`, `9999999`; and AIS's "not available", `1073741823` (2³⁰−1) | The hull's number for life. In AIS only static messages carry it (17% of aisstream reports, none from hormuz.now: evidence 1), so it is learned per vessel, never read off a position |
| `mmsi` | strong | global | reassignable | yes, window 10 minutes | Exactly 9 digits starting with an assigned maritime identification digit, 201 to 775. Not a ship: `00…` coast stations, `111…` SAR aircraft, `970`, `972`, `974` (SART, MOB, EPIRB devices), `8…` handheld radios, `98…` craft of a parent ship, `99…` aids to navigation; anything else starting 1 or 9, or above 775, is invalid. Junk: a MID followed by zeros (`200000000`, `525000000`), repeated or sequential digits (`111111111`, `123456789`, `999999999`), `299999999` and the like (all seen: evidence 2, 5) | Changes when a ship is reflagged or sold, is reissued later, and is often shared or spoofed. Reflags show as one valid IMO with two MMSIs (evidence 4) |
| `callSign` | weak | global | reassignable | no | 3 to 7 letters and digits | Changes with the flag |
| `vesselName` | weak | global | reassignable | no | Trim trailing spaces and `@` (AIS padding). Not a name if it is then empty, still contains `@`, contains characters outside AIS's 6-bit text set, or equals the MMSI | Not unique, and changes; a tie-breaker and search key. Most "renames" in the lake are decode errors in the name text, not renames (evidence 2) |

**Anchors.** A vessel whose IMO came from a source that vouches for it is anchored
by the IMO: an MMSI that moves away ends its MMSI row, and the vessel stays. A vessel
with no such IMO is anchored by its MMSI until the MMSI is reassigned or contested;
then the vessel keeps its id and the MMSI row ends.

**Not every AIS transmitter is a vessel.** Besides the device MMSIs above, some
transmitters are fishing gear: net buoys whose name is a battery level, such as
`REVO-62%` (evidence 2). The pack classifies them as gear (their own object type,
later), not vessels.

**Organizations** (later): the IMO also numbers registered owners and ship managers
(IMO company numbers): a strong, permanent key for Organization in this pack.

### Aircraft (`packs/aviation`)

Primary key `aircraftId`. Title: the registration. Implements `Located`; `maxSpeed`
Mach 3 (about 3,700 km/h), well above any civil type.

| Scheme | Strength | Scope | Validity | Exclusive | Value check | Notes |
|---|---|---|---|---|---|---|
| `msn` | strong | manufacturer and type | permanent | yes | as the register gives it | The airframe's serial number for life |
| `icao24` | strong | global | reassignable | yes, window 5 minutes | 6 hex digits; not `000000` or `ffffff` | The transponder address, assigned with the registration; changes on re-registration to another state and is reissued. US privacy addresses (PIA) are temporary by design |
| `registration` | strong | global | reassignable | yes | the register's format (`N123AB`, `G-ABCD`) | Changes on re-registration; US N-numbers are reissued |

**Not an aircraft key: the callsign.** `UAL123` names a flight, and one aircraft
flies under many callsigns in a day. It belongs to a Flight occurrence in this pack,
later.

**Anchors.** `msn` when it's known; else `icao24` until it's reassigned.

### Open question for the packs

3. **Vessels settled** by evidence 7: 10 minutes and 50 knots. Aircraft (5 minutes,
   Mach 3) still to check, once there is an aircraft case.

---

## C. The Horus extension

This deployment's feeds, sources and jobs.

### Provider schemes

Schemes that only mean something inside one feed:

| Scheme | Strength | Scope | Validity | Exclusive | For | Notes |
|---|---|---|---|---|---|---|
| `hormuz.now` | strong | provider | reassignable | yes | Vessel | hormuz.now's own vessel id. Links reports within hormuz.now only. **Not one per vessel and not stable** (evidence 7): hormuz.now sometimes lists one vessel under two ids at once, and gives a vessel a new id over time. So a vessel can hold several of these at once, and the MMSI, not this id, carries a vessel across them. Used on its own only when a vessel has no valid MMSI |
| `adsb.lol` | weak | provider | reassignable | no | Aircraft | adsb.lol addresses starting `~` (non-ICAO, such as TIS-B): never linked to an aircraft |

### Source trust (principle 5)

Declared on each source (`vouchesFor`), as decided 2026-11-20:

| Source | Vouches for | Why |
|---|---|---|
| aisstream.io, hormuz.now | `mmsi` | The radio sends its own MMSI |
| aisstream.io, hormuz.now | **not** `imo`, `callSign` | AIS static data is typed in by the crew, so an IMO from AIS only proposes |
| adsb.lol, OpenSky | `icao24` | The transponder sends its own address |
| adsb.lol | **not** `registration` | adsb.lol looks the registration up in its own database; it proposes |
| Offline reference data (12.x) | `imo`, `msn`, `registration` | Register data. Until it is loaded, every IMO and registration only proposes |

### The real case: MMSIs with more than one hormuz.now vessel

12 MMSIs were seen with more than one hormuz.now vessel id (evidence 3). Comparing
ids reporting in the same 10 minutes (evidence 7) shows three different things, and
the rules handle each without anything special:

| What | MMSIs | Seen | Under these rules |
|---|---|---|---|
| Two ships on one MMSI | `470902000`, `470013000` | 20 and 41 windows together, about 110 km apart: 660 km/h for one ship | Implausible within the window, so both MMSI rows are `contested`, a conflict goes to review with both tracks, and an MMSI-only report (aisstream) links to neither until an analyst decides |
| One ship listed twice by hormuz.now | `470922000`, `457669000`, `620999368`, `470684000` | together, 0 to 1 km apart | Plausible, so the MMSI links both hormuz.now ids to one vessel |
| One ship renumbered by hormuz.now | the other six | never together | The MMSI carries the vessel from the old id to the new one |

Today all twelve merge into one asset per MMSI. For the ten that is right; for the
two shared MMSIs one "vessel" jumps 110 km and back.

The thresholds are settled for vessels: 50 knots is about 15 km in 10 minutes, far
from both the duplicates (0 to 1 km) and the sharing (110 km).

### The event feeds

Occurrences rather than long-lived assets; each feed names them its own way. These
are Horus's for now; a hazards pack could share them later.

| Type | Scheme | Strength, scope, validity | Notes |
|---|---|---|---|
| Earthquake | `usgs` | strong, provider, permanent | USGS can merge two network ids into one event and change its preferred id; every id in the event's `ids` list is a key |
| Weather alert | `nws` | strong, provider, permanent | An update is a new alert that references the earlier one: a link (supersedes), not a shared key |
| EONET event | `eonet` | strong, provider, permanent | One EONET event can be both a weather event and a fire: one entity, two observation types |
| Fire detection | none | | A FIRMS detection has no id beyond its place and time: an observation, not an entity |

### The lake

`asset_id` and `id_scheme` stay as reported (principle 2). The entity tables (4.5)
hold one row per entity plus its identifier rows (part A). A report finds its entity
by (`id_scheme`, `asset_id`) at `event_time`.

### The detections job

`ssb/04_detections.sql` runs on the live stream, before resolution, so it keys on
claims, not entities, and keeps the MMSI as its key (evidence 7: for ten of the
twelve MMSIs with several hormuz.now ids, the MMSI is the right key and the
hormuz.now id is not). Two changes:

- key on (`id_scheme`, `asset_id`), not `asset_id` alone, so a provider id can never
  collide with an MMSI;
- the speed-jump check compares consecutive reports only when they carry the same
  provider id, so two ships on one MMSI don't raise impossible-speed alerts. The gap
  and loitering checks stay on the MMSI.

The lasting fix is resolution: once an MMSI is `contested`, detections on it say so.
An alert becomes an Alert entity through an action by a machine actor (O7), which
resolves its claim to an entity at the alert's time.

### Evidence from the lake (2026-11-20)

The first use of the lake as evidence for the ontology (O0b). Run 2026-11-20 over
about 16 M vessel reports since the lake rework:

1. **IMO coverage.** aisstream.io: 2,695,581 of 16,000,957 reports (17%) carry an
   IMO, all from static messages. hormuz.now: none of 264,272.
2. **MMSIs with several names:** almost none are renames. Most are decode errors in
   AIS name text (`DARDA@!(7@@@@@@@X`); placeholder MMSIs shared by unrelated ships
   (`0` with 14 names, `200000000`, `525000000`, `111111111`, `299999999 TESTSHIP`);
   names equal to the MMSI; and fishing-gear buoys named by battery level
   (`REVO-62%` to `REVO-82%`). A few look like real renames or shared MMSIs
   (`368115220`: WESTPORT41M, TRU LUV, PRICELESS).
3. **MMSIs with more than one hormuz.now vessel:** 12 (4 seen on 2026-11-19), 11 with
   two vessels and `620999368` with three; mostly UAE (`470…`).
4. **IMOs with several MMSIs:** 42. 15 fail the check digit (`1073741823`, which is
   AIS's 2³⁰−1 "not available", with 62 MMSIs; `123456789`; `1`; `14`; ...).
   `1234567` passes it and is junk. The other 26 look like reflags (Marshall Islands
   `538…` with another flag) or MMSI typos (`241928000` and `241192800`).
5. **MMSIs that aren't ships:** about 200: SART, EPIRB and MOB devices (`970`, `974`,
   `972`), SAR aircraft (`111`), handheld radios (`8…`), `98x` and `99x`, MIDs above
   775, other `1…` and `9…`, and `0` and `1`. The aisstream script checks no MMSI, so
   these reach the lake as vessels; hormuz.now's checks for 9 digits.
6. **ICAO addresses with several registrations:** none. Weak evidence: adsb.lol looks
   the registration up from the address in its own database, so they can't disagree.
7. **The 12 MMSIs of 3, in the same 10 minutes:** `470902000` and `470013000` together 20 and
   41 times, about 110 km apart (two ships); `470922000`, `457669000`, `620999368`
   and `470684000` together 0 to 1 km apart (one ship listed twice); the other six
   never together (renumbered). See the real case above.

Rules changed by this: the IMO junk list and AIS's "not available" value; the MMSI
check (handheld radios, MID-and-zeros placeholders, invalid 1, 9 and 7xx ranges);
the name check; fishing gear is not a vessel; the hormuz.now id is neither one per
vessel nor stable; the detections change; the vessel window and limit confirmed.

### The queries

Run in Hue (`iceberg.horus_dev.events_iceberg`), all on 2026-11-20.

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

-- 7. For the MMSIs in 3: two hormuz.now vessels in the same 10 minutes, and how far
--    apart. Far apart at once is two ships on one MMSI; never at once is hormuz.now
--    renumbering one ship.
WITH r AS (
  SELECT asset_id, json_extract_scalar(payload, '$.entity.properties.hormuz_id') AS hid,
         from_unixtime(floor(to_unixtime(event_time) / 600) * 600) AS t, lat, lon
  FROM iceberg.horus_dev.events_iceberg
  WHERE source_provider = 'hormuz.now' AND id_scheme = 'mmsi'
    AND asset_id IN ('470613000', '457669000', '470902000', '470144000', '470922000', '470684000',
                     '470676000', '470013000', '515232000', '470084000', '620999368', '470921000')),
b AS (SELECT asset_id, hid, t, avg(lat) AS lat, avg(lon) AS lon FROM r GROUP BY 1, 2, 3)
SELECT x.asset_id, COUNT(*) AS windows_together,
       round(max(great_circle_distance(x.lat, x.lon, y.lat, y.lon))) AS max_km,
       round(approx_percentile(great_circle_distance(x.lat, x.lon, y.lat, y.lon), 0.5)) AS median_km
FROM b x JOIN b y ON x.asset_id = y.asset_id AND x.t = y.t AND x.hid < y.hid
GROUP BY 1 ORDER BY max_km DESC;
```
