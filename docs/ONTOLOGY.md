# Horus on the Helios ontology

Horus depends on an ontology: the vessels, aircraft, organizations, ports and alerts
it reasons about, their links, and the actions analysts and detections take on them.
The ontology itself, the engine that lets any user create ontologies and semantic
models of their data, is **Helios**. Its plan, identity mechanism and burndown are in
the Helios repo:

- [ontology-plan.md](https://github.com/Christopheraburns/helios/blob/main/docs/ontology-plan.md): the design (object types over Ossie, entities
  and observations, links, interfaces, actions, governance, streams, serving)
- [ontology-identity.md](https://github.com/Christopheraburns/helios/blob/main/docs/ontology-identity.md): how identity keys and resolution work
- [ontology-burndown.md](https://github.com/Christopheraburns/helios/blob/main/docs/ontology-burndown.md): sprints S0 to S15

This page is Horus's part: its extension (the seed), its integration as a host, and
what in Horus waits on which Helios sprint. The plan lived here until 2026-11-20
(`docs/ONTOLOGY_PLAN.md`, in git history).

**Where a change goes** (decided 2026-11-20): if a different Helios user would have to
take the same action to run Helios on their own data, the change is Helios's (its Track
H, [helios-decomposition-burndown.md](https://github.com/Christopheraburns/helios/blob/main/docs/helios-decomposition-burndown.md)). Horus keeps
its domain (packs, the extension), its pipeline (NiFi, Kafka, Flink) and its deployment.

## Built so far

| What | Where |
|---|---|
| The semantic model of the lake, `horus_lake`: six typed views, 120 fields, 24 metrics, reviewed | [semantic/horus_lake/](../semantic/horus_lake/) (burndown O0b) |
| Identity rules for Horus's domain: the maritime and aviation packs' schemes, checks and limits; this deployment's sources and their trust; the evidence from the lake | [IDENTITY.md](IDENTITY.md) parts B and C (O0a) |

## The Horus extension (maritime and aviation)

Built on the Horus lake and the `ref_*` tables ([OFFLINE-DATA.md](OFFLINE-DATA.md)).

| Object type | Kind | Backed by |
|---|---|---|
| Vessel | Entity | Vessel identities from AIS static data, with MMSI, IMO, name, flag |
| Aircraft | Entity | ICAO hex, registration and type from the offline aircraft database |
| Organization | Entity (implements Actor) | Operators and owners, sanctions lists, the Wikidata graph |
| Port | Entity (implements Located) | World Port Index |
| SanctionListing | Entity | `ref_sanctions` |
| Alert | Entity | The alerts topic and its lake table; analysts triage it |
| Encounter | Entity | Ship-to-ship detections; object-backed between two vessels |
| PositionReport | Observation | The events table, vessel and flight positions |

Metrics: dark hours, port calls per month, encounters per vessel, alerts per area.

Actions: triage alert (status, assignee, note), flag vessel or aircraft, add to watchlist, confirm or reject an identity match, and create Alert (machine actor, from Flink).

Consumers once it lands: Ask Horus tiers (burndown 11.4 to 11.7) read object sets instead of raw tables; the Prime Agent (section 5) works through the ontology tools; map popups open object views.

Its identity keys follow [IDENTITY.md](IDENTITY.md): MMSI (strong, reassignable,
exclusive), IMO (strong, permanent; proposes when from AIS), hormuz.now's own id, ICAO
address, registration, airframe serial.

## Horus as a host (Helios S12)

Horus's integration, after the Helios components (S14) and the side effects and Kafka adapter (S9):

| Points | Work |
|---:|---|
| 3 | Reference server deployed as a Workbench Application; Postgres hosted; Horus sign-in plugged in (needs BURNDOWN-DEPLOY C1, C2) |
| 1 | Helios Kafka adapter wired to Horus topics and mappings |
| 2 | Flink alerts and encounters submitted as machine-actor actions |
| 2 | Function runner process |
| 2 | Helios components (S14) embedded in the Horus UI with Horus theme tokens; a map renderer for `Located`; map popups open the object view |

## Seeds Horus builds (Helios S13)

| Points | Work |
|---:|---|
| 6 | The Horus extension over the lake (the typed views and `horus_lake`) and the `ref_*` tables, with its metrics and actions |
| 2 | Ask Horus tier 1 reads an object set (burndown 11.4) |

## What waits on which Helios sprint

| Horus work | Waits on |
|---|---|
| Entity tables for vessels and aircraft, keyed by the identity rules (burndown 4.5) | S1 identity keys, S4 entity index (or built ahead in Iceberg and loaded later) |
| Analyst writeback: flag, annotate (4.4) | S6 actions |
| Flink alerts as Alert entities (4.6 onward) | S6 actions, S9 Kafka adapter |
| Ask Horus tiers 11.4 to 11.7, the Prime Agent (section 5) | S5 object sets, S10 tools |
| Object views from map popups | S14 components |
| Security markings on objects (13.5) | S8 governance |
