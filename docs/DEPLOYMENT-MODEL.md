# Deployment model: connected, air-gapped and cross-domain

This note says where Horus sits in a classified or air-gapped deployment. It
covers what "air-gapped" means in practice, where NiFi and the media server go,
and how records carry security markings. The rule that the rest of the design
follows is in [The boundary rule](#the-boundary-rule).

Related: [AIRGAP.md](AIRGAP.md) (the runtime internet calls still to remove),
[OFFLINE-DATA.md](OFFLINE-DATA.md) (reference data kept inside), and
[BURNDOWN.md](../BURNDOWN.md) section 13.

## What "air-gapped" means

An air-gapped enclave has no network path to the public internet. It still
takes in plenty of data, but only by approved routes:

```
 LOW SIDE (internet-connected)   │ CROSS-DOMAIN │  HIGH SIDE (the enclave)
                                 │   SOLUTION   │
 Public sources: AIS, ADS-B,     │              │  Private sensors on the enclave network:
 news, weather, public cameras,  │              │   - drone and aircraft video (MISB/KLV)
 reference data (OFFLINE-DATA)   │              │   - imagery ground stations
            │                    │              │   - radar, signals, partner feeds
            ▼                    │              │   - site cameras, access control
   Low-side NiFi ────────────────┼─► diode or ──┼─► High-side NiFi ◄──┘
   collect, filter, scan,        │   guard      │        │
   package                       │   one way    │        ▼
                                 │              │  Kafka → Flink → Iceberg → gateway → UI
                                 │ ◄─ release ──┼─ rare, manual, human-reviewed
```

- **Low side and high side** are separate networks. The high side never opens
  a connection outward.
- **A cross-domain solution (CDS)** moves data from low to high. It is often a
  hardware data diode, which can only send one way, or a guard that inspects
  and filters content. The customer owns and accredits it. Horus doesn't
  provide one; it hands files to one and picks them up on the other side.
- **Private sensors connect directly** on the enclave network. They don't
  cross a boundary, so nothing needs to buffer them from the internet.
- **High to low** ("release") is rare, manual and reviewed by a person. Horus
  has no automated path in that direction.
- **Software** crosses the same way as data: scanned images brought in through
  an approved transfer. For Horus that is the per-service images scanned in
  JFrog ([BURNDOWN-DEPLOY.md](../BURNDOWN-DEPLOY.md)).

## The boundary rule

> **No high-side Horus service opens a connection to the public internet.**
> Public data arrives through one controlled ingest gateway; Horus includes
> NiFi for this. Services may connect to approved sensors and systems on the
> enclave's own network.

The buffer is the internet boundary, not "everything outside Horus". A
customer's own cameras feeding the media server directly is fine. The same
media server pulling a public traffic camera is not; that goes through the
ingest gateway.

The same rule in a connected deployment: Horus's public feeds still come in
through its NiFi flows, so moving to an air-gapped site only means changing NiFi
parameters (a public URL becomes an internal mirror or a diode drop folder).
No service code changes.

## What feeds Horus

Horus's contract with its sources is **a Kafka topic and the canonical event
envelope**, not NiFi. Flink, the lake and the gateway only ever read events
from Kafka, so anything that writes valid events to the topic is a first-class
source: Kafka Connect, a customer's existing Kafka pipelines, a sensor that
publishes to Kafka natively, or a bridge from another message bus.

NiFi is the ingest toolkit Horus includes: hundreds of connectors, provenance
on every record, back-pressure, and the two-tier hand-off across a
cross-domain solution described above. Every Horus feed ships as a NiFi flow.
A customer can keep those, replace any of them, or add their own producers
beside them. The boundary rule applies to whichever component fetches from the
internet.

## Where each component sits

| Component | Side | Talks to | Notes |
|---|---|---|---|
| Low-side NiFi | Low | Public APIs and sites | Collects, filters, scans and packages. Only needed in a cross-domain deployment; in a connected one, the single NiFi does both jobs. |
| CDS (diode or guard) | Between | Low-side drop folder to high-side pickup folder | Customer's equipment. In the demo, a simulated hand-off (13.2). |
| High-side NiFi | High | CDS pickup folder, internal mirrors, private sensors | The ingest toolkit Horus includes; every Horus feed is a NiFi flow, and every flow's source URL is a parameter. |
| Other producers | High | Kafka | Optional. Anything that writes the canonical envelope to the events topic, such as Kafka Connect or a customer's existing pipeline. |
| Kafka, Flink, Iceberg, Trino | High | Internal only | Unchanged. |
| Gateway, intel resolver, Memgraph, tile server, UI | High | Internal only | AIRGAP.md lists the internet calls that remain. |
| LLM (Mistral on-prem) | High | Internal only | The demo premise. |
| Media server | High | Private cameras directly; public video only as NiFi-stored segments | See [Video](#video). |

## Video

Two paths, depending on where the camera is:

- **Public cameras (OSINT).** NiFi fetches HLS segments, or snapshots from
  cameras that only offer stills, and writes them to object storage. RTSP-only
  public cameras go through ffmpeg on the NiFi host. An internal media server
  re-serves the stored segments to the UI as HLS. The UI never contacts the
  camera. (In the earlier design discussion this was "Option A".)
- **Private cameras and sensors.** They feed the media server directly on the
  enclave network: live LL-HLS to the UI, with recording. On Workbench, use
  LL-HLS rather than WebRTC, because WebRTC needs ports Workbench's single
  HTTPS port can't provide.

Both paths write an index to the lake (`camera_frames` for snapshots,
`camera_segments` for recorded video), so a video can be found by camera,
place and time and joined to tracks and alerts.

The format target is **MPEG-TS with MISB/KLV metadata**, the standard for
military full-motion video. The KLV gives sensor position, look angle and the
ground footprint of each frame. With it, video joins the rest of the lake by
position and time, not just by camera ID. Public traffic cameras stand in for
this in the demo.

## Security markings

Intelligence systems mark every record with its classification and
releasability (who it may be shared with) and enforce access per record and
per user. Horus can do the same with Cloudera's governance stack:

- **On the record.** Every NiFi flow already stamps `classification` on its
  events (all `UNCLASSIFIED` today). It is only inside the raw payload; the
  lake job should land it, and a `releasability` field, as columns.
- **On the table.** Atlas classifications (tags) on tables and columns, with
  Ranger tag-based policies deciding who may read them.
- **On the row.** Ranger row-level filters on the events table, comparing a
  record's marking with the user's clearance attributes, enforced in Trino,
  Hive and Spark alike.
- **In the UI.** The gateway should query as the signed-in user, not a
  shared service account, so the map only shows what that user may see. Each
  popup shows the record's marking.

This is the answer to "Palantir marks every object": the same control, built
from standard Cloudera parts the customer already accredits.

## How Palantir fits the same picture

From public material: Gotham and Foundry are deployed inside the enclave and
ingest from internal systems; the customer's CDS brings public data across.
Apollo delivers and updates Palantir's software into disconnected networks.
Every object carries security markings. Horus's equivalents are high-side NiFi
for ingest, two-tier NiFi for the cross-domain story (which Palantir doesn't
own), scanned per-service images for delivery, and Atlas and Ranger for
markings.
