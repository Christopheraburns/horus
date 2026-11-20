# Entity identity rules (burndown O0a)

How Horus recognises the same vessel, aircraft or event across reports and feeds,
written as the ontology plan's declared identity keys
([ONTOLOGY_PLAN.md, Identity keys](ONTOLOGY_PLAN.md#identity-keys)).

The rules are in three parts, one per home, following the plan's layering (core,
packs, extensions; [ONTOLOGY_PLAN.md, Layering](ONTOLOGY_PLAN.md)). The test for
where a rule goes: **would a car manufacturer need it?** If yes, it is a Helios
mechanism. If only someone tracking ships or aircraft would, it belongs in a pack.
If only this deployment would (its feeds, its sources, its jobs), it belongs in the
Horus extension.

| Part | Home | Built in | Holds |
|---|---|---|---|
| [A. Mechanism](#a-the-mechanism-helios-core) | Helios core | O2 (S1, identity keys), O5 (S4, entity index), O12 (S11, resolution) | What identity keys are, how identifiers are stored over time, how resolution decides. Names no domain |
| [B. Domain packs](#b-the-domain-packs-packsmaritime-packsaviation) | `packs/maritime`, `packs/aviation` (in Horus first; may move to Helios as shared packs) | O14 (S13) | The Vessel and Aircraft types, their schemes, value checks and limits. True for anyone tracking ships or aircraft |
| [C. Horus extension](#c-the-horus-extension) | Horus | O13, O14, 4.5 | This deployment's feeds and their schemes, which sources are trusted, the event types, the lake and the detections job |

Consumers: entity tables (4.5), the detections job, the entity index (O5) and entity
resolution (O12).

---

## A. The mechanism (Helios core)

Nothing here names a domain. Each rule has a Horus and a car plant example, and
must work for both.

### Principles

1. **An entity's primary key is its own.** The entity index mints it (a ULID). No
   outside identifier is ever a primary key: every one can be missing, wrong,
   reused or changed, and the entity outlives all of them. *Horus:* a vessel's id
   is not its MMSI. *Car plant:* a vehicle's id is not its VIN, which is assigned
   after the body is built.
2. **Observations carry claims, not entities.** An observation says which
   identifier the source reported; it never stores an entity id. Which entity a
   claim belongs to is resolved through the identity keys at the observation's
   time, and can be resolved again when the rules or the evidence change. *Horus:*
   "MMSI 636019825 was here at 10:02". *Car plant:* "serial S-123 passed station 4
   at 10:02".
3. **Identifiers are valid for a time.** The entity index keeps one identifier row
   per entity, scheme and value, with `valid_from` and `valid_to`, so a value that
   moved between entities resolves differently before and after the move.
4. **A value is checked before it is trusted.** A scheme names a value type, and a
   value type can name a check, supplied by the pack (a format, a check digit,
   reserved ranges, known junk values). A value that fails is not an identifier.
5. **The source caps the strength.** A deployment declares which sources can vouch
   for which schemes. A strong key from a source that can't vouch for it behaves as
   weak: it proposes and never links on its own.
6. **Conflicts are flagged, never resolved silently.** Two entities claiming the
   same exclusive value at the same time, or one entity with two values of a
   permanent key, become a review item. Nothing merges without a link rule or a
   decision.

### Identity key fields

The plan's four fields, plus `exclusive`, proposed here:

| Field | Values | Meaning | Horus | Car plant |
|---|---|---|---|---|
| `scheme` | a name | The kind of identifier; a value is unique within its scheme and scope | `mmsi` | `vin` |
| `strength` | `strong`, `weak` | A strong match links on its own; a weak match only proposes | MMSI strong, name weak | VIN strong, supplier name weak |
| `scope` | `global`, or the property that qualifies it | Where a value is unique | global | a lot number per supplier |
| `validity` | `permanent`, `reassignable` | Whether a value can move to another instance over time | an MMSI is reissued | a serial never moves |
| `exclusive` (**proposed**) | `true` (default), `false` | Whether a value names at most one instance *at any moment*. `reassignable` covers a value moving over time, not two instances using it at once | an MMSI shared by two ships | one serial printed on two parts |
| `concurrencyWindow` (**proposed**, with `exclusive`) | a duration | How close in time two claims of an exclusive value must be to count as "at once" | set by the pack | set by the pack |

"At once" also needs a plausibility test: could one instance have made both
observations? For types that implement `Located`, the core compares the implied
speed with the type's declared `maxSpeed` (a pack value). Types without a location
use the window alone.

### Identifier rows

The entity index stores identity as rows, with no domain columns:

| Column | Meaning |
|---|---|
| `entity` | The entity's primary key |
| `scheme`, `value` | The identifier |
| `valid_from`, `valid_to` | When it applied (`valid_to` empty: current) |
| `source`, `confidence` | Who said so, and how sure |
| `status` | `active`, `contested` (claimed by more than one entity at once), or `ended` |

### Resolution

Entity resolution (O12) reads only the declarations above:

| Evidence | Result |
|---|---|
| A strong key that passes its check, from a source that can vouch for it, held by one entity at that time | link |
| A strong key that no entity holds | a provisional entity with that key |
| A strong key from a source that can't vouch for it | a proposal |
| A weak key | a proposal |
| An exclusive key claimed by two entities within its window, implausibly for one | both identifier rows `contested`; a conflict to review; claims of that value link to neither while it lasts |
| One entity with two values of a permanent key | a conflict to review |
| A value that fails its check | not an identifier; resolve by another key on the same observation, or not at all |

A decision on a conflict (which entity really holds the value, or that one is
false) is an action, recorded with who decided and the evidence, and it ends the
contest.

### Open questions for the plan

1. Accept `exclusive` and `concurrencyWindow` as identity key fields (O2), or
   express "at once" some other way?
2. Where source trust is declared: on the source in the extension (proposed:
   `vouchesFor: [scheme, ...]`), or as a policy?

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
| `imo` | strong | global | permanent | yes | 7 digits; digits 1 to 6 weighted 7, 6, 5, 4, 3, 2, and the sum's last digit is digit 7 | The hull's number for life |
| `mmsi` | strong | global | reassignable | yes, window 10 minutes | 9 digits starting with a ship's maritime identification digits, 201 to 775. Not a ship: `00…` coast stations, `111…` SAR aircraft, `970`, `972`, `974` (SART, MOB, EPIRB devices), `98…` craft of a parent ship, `99…` aids to navigation. Junk: `000000000`, `111111111`, `123456789`, `999999999` and the like | Changes when a ship is reflagged or sold, is reissued later, and is often shared or spoofed |
| `callSign` | weak | global | reassignable | no | 3 to 7 letters and digits | Changes with the flag |
| `vesselName` | weak | global | reassignable | no | not empty after trimming | Not unique, and changes; a tie-breaker and search key |

**Anchors.** A vessel whose IMO came from a source that vouches for it is anchored
by the IMO: an MMSI that moves away ends its MMSI row, and the vessel stays. A vessel
with no such IMO is anchored by its MMSI until the MMSI is reassigned or contested;
then the vessel keeps its id and the MMSI row ends.

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

3. Check the windows and limits (10 minutes and 50 knots for vessels, 5 minutes and
   Mach 3 for aircraft) against real cases (evidence query 3) before fixing them.

---

## C. The Horus extension

This deployment's feeds, sources and jobs.

### Provider schemes

Schemes that only mean something inside one feed:

| Scheme | Strength | Scope | Validity | Exclusive | For | Notes |
|---|---|---|---|---|---|---|
| `hormuz.now` | strong | provider | reassignable | yes | Vessel | hormuz.now's own vessel id. Links reports within hormuz.now only. Used when a vessel has no valid MMSI, and to tell apart the vessels behind a shared MMSI |
| `adsb.lol` | weak | provider | reassignable | no | Aircraft | adsb.lol addresses starting `~` (non-ICAO, such as TIS-B): never linked to an aircraft |

### Source trust (principle 5)

| Source | Vouches for | Why |
|---|---|---|
| aisstream.io, hormuz.now | `mmsi` | The radio sends its own MMSI |
| aisstream.io, hormuz.now | **not** `imo`, `callSign` | AIS static data is typed in by the crew, so an IMO from AIS only proposes |
| adsb.lol, OpenSky | `icao24` | The transponder sends its own address |
| adsb.lol | **not** `registration` | adsb.lol looks the registration up in its own database; it proposes |
| Offline reference data (12.x) | `imo`, `msn`, `registration` | Register data. Until it is loaded, every IMO and registration only proposes |

### The real case: one MMSI, two vessels

On 2026-11-19 hormuz.now showed 4 MMSIs each used by two different hormuz.now
vessels at once: different hormuz.now ids, positions too far apart for one hull.
Today they merge into one asset, because the lake and the map key on MMSI, so one
"vessel" jumps between two places and the detections job sees impossible speeds.
Under these rules:

- each hormuz.now id is its own vessel, linked by the `hormuz.now` key;
- the MMSI is exclusive, and two vessels claim it within 10 minutes at more than 50
  knots apart, so both MMSI rows are `contested` and a conflict goes to review with
  both tracks as evidence;
- while it lasts, an aisstream report with only that MMSI links to neither vessel and
  proposes; the analyst's decision ends it.

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
claims, not entities. Two changes follow from these rules:

- key on (`id_scheme`, `asset_id`), not `asset_id` alone, so a provider id can never
  collide with an MMSI;
- key on the most specific claim a report carries: for hormuz.now, its own vessel id
  ahead of the MMSI. That alone stops the false speed-jump alerts from shared MMSIs.

An alert becomes an Alert entity through an action by a machine actor (O7), which
resolves its claim to an entity at the alert's time; an alert on a contested
identifier says so.

### Evidence to gather from the lake

The rules rest on these. Run them in Hue over a few days and record the answers
here; they are the first use of the lake as evidence for the ontology (O0b).

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
