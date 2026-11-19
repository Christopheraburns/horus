# Burn-down: Horus

Status values: Todo / Doing / Done / Blocked / Cut / Moved. Estimates are hours.
Work the sections in order; each builds on the one before.

Security and deployment work (dependency upgrades, per-service images, SSO,
credentials) is tracked separately in [BURNDOWN-DEPLOY.md](BURNDOWN-DEPLOY.md).

## 1. Mistral as the LLM (Large 4 where possible)

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 1.1 | Gateway `llm.py`: provider-neutral `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (old `OPENAI_*` still read), default model `mistral-large-4`, optional `LLM_REASONING_EFFORT` | `/llm/health` reports the Mistral model and `available: true` | 2 | Done |
| 1.2 | Handle Mistral streaming: text deltas, and reasoning ("thinking") chunks dropped from the answer | `/llm/chat` and Ask Horus stream clean text from Large 4 (mock-tested 2026-11-18; live check is 1.4) | 1 | Done |
| 1.3 | Remove the unused Gemini path from the UI (`AiAnalyst`, `/api/ai/*`, `ai-engine`, `@google/generative-ai`); no LLM keys in browsers | No `gemini` left in `ui/src`; build passes | 1 | Done |
| 1.4 | Verify against Mistral Studio: `/llm` page, Ask Horus (GraphRAG), pattern-of-life | Three features answer in Workbench (verified 2026-11-18: `/llm` and Pattern of Life on Large 4) | 1 | Done |
| 1.5 | Docs: INSTALL.md gateway variables; air-gapped option (same variables pointed at an on-prem Mistral or Cloudera AI Inference endpoint) | Section written | 0.5 | Done |
| 1.6 | Confirm with Mistral which models are licensed for on-prem / air-gapped use (Large 4 vs Medium) | Answer recorded here: yes. The demo premise is Mistral Studio deployed on-prem (2026-11-18) | – | Done |

## 2. Upstream OSIRIS fixes

The security fixes (Next.js upgrade, upstream security ports) moved to
BURNDOWN-DEPLOY A1 and A2.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 2.3 | Port #370 (derived or missing data not shown as observed), #469 (reload on chunk load failure), #289 (bound every fetch, type errors fail the build, stream-status host check); #385 (ArcGIS SSRF) does not apply, Horus has no `/api/arcgis` | Ported | 2 | Done 2026-11-18: country-risk basis and word-boundary quake matching, honest `/api/health`, news keyword labels and centroid precision, rightmost-proxy client IP, chunk reload, every server fetch bounded (safeFetch defaults to 30 s; LLM streams end with the browser), `ignoreBuildErrors: false` with 0 type errors; upstream's 28 tests for these pass against the port (not added to Horus: no test runner) |

## 3. Horus MCP server

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 3.1 | Port `osiris/mcp-server` to `services/mcp`: rename, point at the Horus Applications. Interim: the long-term tool layer is the ontology tools (O11), served by helios-mcp or Daedalus | Tools answer against the dev instance | 3 | Todo |
| 3.2 | Bearer token on `/mcp`: moved to BURNDOWN-DEPLOY C3 | – | – | Moved |
| 3.3 | New tools: lake history query (read-only), alerts, findings | Tools listed and tested | 3 | Cut: replaced by the ontology tools (O11: `search_objects`, `run_object_set`, `submit_action`); add one interim alerts tool only if a demo needs it first |
| 3.4 | Register as a Mistral Studio connector and a Cloudera Agent Studio MCP server. Registers whichever MCP server exists at the time (3.1 now, the ontology tools later) | An agent calls a tool from each | 1 | Todo |

## 4. Flink detections, alerts and findings

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 4.1 | SSB jobs: AIS gaps (dark vessels), loitering, ship-to-ship encounters, impossible speed jumps, squawk 7500/7600/7700 → `horus-<instance>-alerts` topic | Alerts flow on the dev instance | 8 | Built, awaiting dev run: `ssb/04_detections.sql`, job `horus_<instance>_detections`; passes `ssb/test/run_local.sh` (7/7 cases on Flink 1.19). Run `create --yes`, then `tools/tail_alerts.py` |
| 4.1a | Port and anchorage reference data (self-hosted) to suppress `STS_ENCOUNTER` and `LOITERING` in harbours; tune thresholds on a day of real alerts | False-positive rate acceptable for a demo | 3 | Todo |
| 4.2 | Iceberg tables `alerts_iceberg` and `findings_iceberg` created by the provisioner. These become the datasets behind the Alert type and the findings proposals (section 14): `alert_id` stays deterministic as the primary key, and triage state comes from the ontology edit log, so no status column | `status` shows both | 2 | Todo |
| 4.3 | Gateway and UI: ALERTS and AGENT FINDINGS map layers, Time Travel aware. Later reads the Alert object set so the map shows triage state (O14) | Layers render | 4 | Todo |
| 4.4 | Analyst writeback: flag and annotate an entity or alert, stored in Iceberg | Note survives restart and shows in Time Travel | 4 | Moved to section 14: analyst writeback is the ontology write path (actions, edit log, Iceberg copy); first Horus actions are "triage alert" and "flag vessel" (O7, O14). A separate gateway write path would break the plan's rule 1 |
| 4.5 | Entity tables: a job (SSB or Spark) keeping one row per vessel (from AIS static messages) and per aircraft (from positions plus the 12.3 aircraft data) in Iceberg, keyed by the O0a identity rules; detections' `asset_id` uses the same key | `vessels` and `aircraft` tables populated and current | 5 | Todo |

## 5. Prime Agent anomaly investigations

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 5.1 | Trino access for the Optiness lakehouse skill through Helios's Trino engine (`helios-cortex`, runs as the caller) rather than a new backend; or an Impala VW over the same table | Skill queries `events_iceberg` | 3 | Todo |
| 5.2 | Skills: graph (Memgraph read-only), intel resolver, live feeds (or reuse the MCP server). Switch to the ontology tools when O11 lands | Callable from the REPL | 3 | Todo |
| 5.3 | Investigation method for maritime and aviation anomalies, split by day, entity type and region | Method in AGENTS.md | 3 | Todo |
| 5.4 | Findings submitted as proposals by the agent as a machine actor (design rule 11): SQL and row counts as evidence, stored in `findings_iceberg`, accepted or rejected by an analyst; shown on the map. Interim before the ontology: write the same record to `findings_iceberg` with status `proposed` | One investigation end to end | 4 | Todo |
| 5.5 | Read-only workload user, read-only Ranger policies, isolated project; validation pass on findings (agent guardrails, needed even for demos). Helios's "grants nothing" rule (queries run as the caller) covers part of this once 5.1 uses it | Policies in place | 2 | Todo |

## 6. Upstream camera, flight and map features

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 6.1 | Camera sources and catalogue cache, preview tiles, close-up viewer, HLS/YouTube playback (check each source's terms) | Cameras render in PUBLIC mode | 8 | Todo |
| 6.2 | Camera catalogue as a NiFi feed so cameras work in PIPELINE mode | Cameras render in PIPELINE mode | 4 | Todo |
| 6.5 | Public camera video through NiFi ([DEPLOYMENT-MODEL.md](docs/DEPLOYMENT-MODEL.md#video)): NiFi fetches HLS segments or snapshots for a watchlist of cameras (ffmpeg on the NiFi host for RTSP), writes them to object storage and indexes them in `camera_frames` / `camera_segments`; an internal media server re-serves stored segments as HLS; the UI never contacts a camera | A watched camera plays in PIPELINE mode with no UI or media-server internet traffic | 8 | Todo |
| 6.6 | Private-sensor path: media server (MediaMTX) takes an internal camera or a test RTSP/MPEG-TS source directly, LL-HLS to the UI (not WebRTC on Workbench), recordings indexed in `camera_segments` | Internal test stream plays live and its recording is findable by time | 5 | Todo |
| 6.7 | Playback and clips: from an alert or a track point, open the nearest camera's recording at that time | An alert opens a clip from the right time | 3 | Todo |
| 6.3 | AI Analyze (YOLOX-nano in the browser, model file self-hosted); Identify routed to Mistral through the gateway | Works with no browser key | 4 | Todo |
| 6.4 | Flights: airframe identity, flown tracks (from the lake), multi-aircraft watch. Watch list: simple store now, moved to an ontology object changed by an action in O14 | Ported | 6 | Todo |

## 7. Air-gap readiness (PIPELINE mode with no internet calls)

Inventory and details: [docs/AIRGAP.md](docs/AIRGAP.md). Image and install-time items are in [BURNDOWN-DEPLOY.md](BURNDOWN-DEPLOY.md).

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 7.1 | Self-host the web fonts | No `fonts.googleapis.com` request | 0.5 | Done |
| 7.2 | PIPELINE mode: no reverse geocode under the cursor | No `nominatim` request while panning | 0.5 | Done |
| 7.3 | PIPELINE mode: global stats from gateway feeds only | `/api/stats` makes no public calls | 1 | Done |
| 7.4 | PIPELINE mode: hide satellite imagery and 3D buildings; no OpenFreeMap fallback | No Esri or OpenFreeMap request | 1 | Done |
| 7.5 | PIPELINE mode: region dossier and search from Memgraph, plus coordinate entry. Later, search runs over object sets (section 14) | No Nominatim, Wikipedia, Wikidata or restcountries request | 4 | Todo |
| 7.6 | Intel resolver: bundled OFAC file; countries from Memgraph; IP lookups off in secure mode | Resolver starts and answers with egress blocked | 3 | Todo |
| 7.7 | Dependencies baked into images: moved to BURNDOWN-DEPLOY section B | – | – | Moved |
| 7.8 | Egress test: headless browser in PIPELINE mode records every request; fails on non-Horus hosts | Test passes | 2 | Todo |
| 7.9 | Sync the browser's SOURCE flag with the server (intel `secure=1`) | Toggle changes intel source | 1 | Todo |
| 7.10 | Splash screen removed; fly-to-city disabled (code kept) | Done 2026-11-18 | 0.5 | Done |

## 8. Imagery and tile sets (Horus side)

The imagery package ([imagery/BURNDOWN-IMAGERY.md](imagery/BURNDOWN-IMAGERY.md))
has produced its delivery set: 7 raster MBTiles, 16.05 GB, with `MANIFEST.md`
and `SHA256SUMS`. The global base (`horus-imagery-global`, z0–10, 12.46 GB) and
six regions to z14 (`hormuz`, `taiwan-strait`, `bosporus`, `crimea`,
`channel`, `hampton-roads`) are ESA WorldCover 2021, WebP with transparent
ocean, and carry their attribution in the file metadata.

This section connects them to Horus, and does it as a **tile-set registry**
rather than one hard-coded basemap. The registry is one list of tile sets; each is either a file
served by the Horus tile server or a customer's own tile server URL. Each entry
carries its licence and attribution, security marking and capture date, and the
UI builds its map layers from the list. That is how a customer brings their own
imagery: licensed sub-metre imagery, drone orthomosaics, post-event imagery.

**The demo runs the production architecture.** Stand-in *data* is fine: "the
vessels come from aisstream.io; the same NiFi flow points at your own
source". Stand-in *architecture* is not: the demo never serves imagery from
files inside a Workbench Application with a promise of something better later.
Tile sets live in the environment's object storage (S3 on CDP in AWS, Ozone
on-prem: the same S3 API, governed the same way), as PMTiles, read by the
Horus tile service. Workbench-local MBTiles are for development only.

Design notes:
- Most serious customers have a tile *server* (GeoServer, ArcGIS
  Enterprise, a national imagery service) more often than files, so URLs are first-class
  entries, not an afterthought.
- Fresh imagery usually arrives as GeoTIFF/COG, NITF or GeoPackage, not
  MBTiles. The real import is a conversion step (8.7).
- MBTiles is SQLite and needs a normal filesystem, which is why object
  storage uses PMTiles instead: one file per tile set, each tile a single HTTP
  range request. `pmtiles convert` turns the delivered MBTiles into PMTiles
  without rebuilding them.
- Adding a file means restarting the tile server, which takes seconds
  (tileserver-gl-light does not reload its config).

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 8.1 | Storage per deployment, with object storage as the standard: the demo and production use the environment's object store (S3 data-lake bucket on CDP in AWS, Ozone on CDP Private Cloud; MinIO or similar elsewhere) under a per-instance prefix the provisioner creates, with read access for the tile service's identity (IDBroker/RAZ on AWS, Ranger on Ozone). Local disk or Workbench project storage only for development. Hand-off (imagery D2): convert the 7 files to PMTiles, copy them to the bucket from the imagery workstation, and verify checksums there; never through the browser upload | Decided and documented in INSTALL.md; the 7 PMTiles verified in the bucket | 3 | Todo |
| 8.2 | Registry format: one list of tile sets with id, kind (`file` or `url`), role (imagery, vector basemap or overlay), title, attribution and licence, marking, capture date or date range, bounds, zoom range and stacking order. File entries are filled from the MBTiles `metadata` table; a small override file holds what the metadata lacks (marking, capture date) | Format written down, with the 7 delivered files as the example | 2 | Todo |
| 8.3 | Tile server builds its config from the registry: on start, `serve-tiles.py` lists the tile sets (the bucket prefix, or a local folder in development), reads each one's metadata, validates it (raster or vector as declared, Web Mercator, metadata present) and writes `config.json`. A bad file is skipped with a clear log line, not a failed start | The 7 files served with TileJSON at `/data/<id>.json`; a deliberately broken file is reported and skipped | 4 | Todo |
| 8.4 | UI layers from the registry at run time: imagery as MapLibre raster sources, global under regional, each limited to its bounds so tiles outside are never requested. The satellite button returns in PIPELINE mode and uses it (PUBLIC mode can still use Esri) | Satellite view works with egress blocked; a new file appears after a tile-server restart, with no UI rebuild | 4 | Todo |
| 8.5 | Attribution and marking on the map for every visible tile set (ESA WorldCover / Copernicus, CC BY 4.0, for the delivered set); markings follow section 13 | Attribution and marking visible whenever the layer is | 1 | Todo |
| 8.6 | Customer tile servers as registry entries of kind `url` (XYZ, TMS, WMTS), replacing the single `IMAGERY_TILE_URL` setting planned before; servers that need credentials go through a Horus proxy so the browser never holds them. In an air-gapped site these are enclave servers only (DEPLOYMENT-MODEL.md) | One registry entry adds a customer server's imagery to the map | 3 | Todo |
| 8.7 | Import fresh imagery: a Workbench job that turns a GeoTIFF or COG (later NITF and GeoPackage) into a tile file using the imagery package's recipe (`region.sh`, `finish_mbtiles.py`; the stretch only for raw reflectance, not for imagery that is already 8-bit RGB), then registers it with its capture date | A customer-style GeoTIFF becomes a registered tile set with one command | 8 | Todo |
| 8.8 | Dated imagery: the layer list shows each tile set's capture date, and Time Travel picks the tile set nearest the replay time where several cover the same place | Replaying a past date shows the imagery from that date | 4 | Todo |
| 8.9 | Serve PMTiles from object storage: the tile service reads tile sets from the bucket by range requests with its own credentials (the browser never reaches the bucket), with caching and long cache headers since tiles never change. First check whether tileserver-gl reads PMTiles from an authenticated S3 or Ozone bucket; if not, add a small range-reading service in front of it. This is also where per-tile-set access checks (markings, section 13) are enforced. Needed by 8.3 and 8.4 | The 7 tile sets served from the bucket in the demo environment, with no tile files in Workbench | 6 | Todo |
| 8.10 | Self-service upload page in the UI | – | – | Cut: multi-gigabyte uploads through the Workbench ingress are fragile, and adding imagery is an admin action with markings; use 8.1's transfer route and 8.7 instead |

## 9. Flight sources

adsb.lol now limits anonymous use to 500 requests a day per IP (seen 2026-11-18),
so flights also come from OpenSky. Both flows publish to the same topic.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 9.1 | OpenSky flow: OAuth2 client credentials, one global `/states/all` call every 90 s, Groovy transform (position time as event time, stale and on-ground dropped, callsign-based classification); generated by `tools/build_opensky_flow.py` | Transform tested on a live snapshot: 9,710 aircraft emitted | 4 | Done |
| 9.2 | adsb.lol flow on a CRON schedule: every 12 min, 7 AM–10 PM US Central (450 requests per UTC day; adsb.lol resets at 00:00 UTC) | In the repo flow | 0.2 | Done |
| 9.3 | Deploy (blocked 2026-11-18: NiFi's connection to auth.opensky-network.org times out, OpenSky blocks AWS addresses; flow disabled in NiFi and now opt-in: the provisioner skips it unless `HORUS_ENABLE_OPENSKY=1`. Also seen: the OAuth2 service did not pick up `#{opensky.client.secret}`, so it was hardcoded in the service; check the sensitive-parameter update if the flow is ever re-enabled): OpenSky API client created; `HORUS_OPENSKY_CLIENT_ID` / `_SECRET` set; `tools/nifi_props.py` confirms the OAuth2 property keys; `create --yes` imports the flow; the running adsb.lol flow's schedule changed to 20 min by hand | Aircraft on the map from `source_provider = opensky` | 1 | Blocked |
| 9.4 | Offline flight reference data, downloaded once and shipped with Horus (no runtime calls): aircraft database by ICAO hex (OpenSky aircraft DB or tar1090-db; FAA registry for US), airline ICAO codes, OurAirports, and callsign-to-route data (VRS standing data); NiFi enrichment adds registration, type, operator and likely origin/destination. Replaces the removed FlightAware / ADS-B Exchange / RadarBox popup links. Check each dataset's licence | Popups show type, operator and route with the internet off | 5 | Todo |
| 9.5 | Licence: OpenSky standard accounts are non-commercial; confirm the licensed tier (or another source) before customer use | Decision recorded | – | Todo |
| 9.6 | Coverage grid for adsb.lol (40–60 points) | – | – | Cut (500 requests a day makes it impractical) |
| 9.7 | Licensing options to revisit: OpenSky licensed tier (live and Trino, quote only); adsb.lol feeder (receiver about $150; feeder key allows a whole-world snapshot twice a minute; ask whether usable from AWS; ODbL) | Option chosen | – | Todo |

## 10. Freshness of live positions

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 10.1 | Popups show LAST UPDATE for aircraft and vessels; positions older than 15 min are drawn faded and marked STALE | Visible in both SOURCE modes | 2 | Done |
| 10.2 | Gateway cutoffs per feed: aircraft 25 min, moving ships 20 min, ships at anchor 60 min, others 60 min (settings in INSTALL.md); every item carries `age_s` | Tested with a fake clock | 2 | Done |
| 10.3 | Dead reckoning: estimate a moving ship's (or aircraft's) current position from its last speed and heading, drawn as an estimate (for example a dashed line from the last fix) | Estimated positions shown and labelled | 4 | Todo |
| 10.4 | Commercial aircraft are thinned 10x before drawing (upstream OSIRIS performance shortcut in `HorusMap` `toFeatures(..., 10)`); review now that counts are lower | Decision made; thinning removed or zoom-dependent | 1 | Todo |

## 11. AI answers (Ask Horus, Pattern of Life)

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 11.1 | Selecting another entity clears the previous Ask Horus and Pattern-of-Life results and aborts streams still running (browser to gateway to LLM) | No text from a previous asset appears | 1 | Done |
| 11.2 | Short-lived gateway cache for Pattern of Life, keyed by entity, window and time bucket (about 10 min); the panel shows "generated N min ago" with a refresh button | A repeat request within the window returns instantly | 2 | Todo |
| 11.3 | Record every generated answer (question, entity, facts used, model, timestamp) in an Iceberg table: an audit trail and lineage for AI output. Fits the ontology action log's Iceberg copy; an answer can later be an object linked to its entity | Answers queryable in Trino | 3 | Todo |
| 11.4 | Ask Horus tier 1 (Attribution) with real facts: gateway graph on Memgraph (C7) plus the offline aircraft database (12.3) for operator, type and registration; vessels too (MMSI country code, ShipStaticData, Memgraph by IMO). Facts gathered through one `facts_for(entity, tier)` function, so O14 swaps it to object sets without touching the tier | Tier 1 answers with an operator and type for a typical airliner and a typical vessel | 3 | Todo |
| 11.5 | Ask Horus tier 5 (Anomaly): the entity's alerts from the alerts topic (4.1, read by the gateway in 4.3) given to the LLM as facts. Facts gathered through one `facts_for(entity, tier)` function, so O14 swaps it to object sets without touching the tier | An entity with an alert gets an explanation of it | 2 | Todo |
| 11.6 | Ask Horus tier 3 (Spatial): what is within N km now, from the gateway's live snapshot (aircraft, vessels, events, alerts), plus nearest port and maritime zone (12.4). Facts gathered through one `facts_for(entity, tier)` function, so O14 swaps it to object sets without touching the tier | Answer names nearby entities with distances | 3 | Todo |
| 11.7 | Ask Horus tier 2 (Operator): the operator's other assets from Memgraph, sanctions from `ref_sanctions` (12.5), registration-country context. Facts gathered through one `facts_for(entity, tier)` function, so O14 swaps it to object sets without touching the tier | Answer lists the fleet and any sanctions hit | 3 | Todo |
| 11.8 | Tier 4 (Pattern): reuse Pattern of Life rather than build a second history answer; one panel, tiers relabelled to match what is built. Tiers 2–5 are hidden in the UI until each one is built (re-add to `INTEL_TIERS` as it lands) | No disabled placeholder buttons; every visible tier works | 1 | Todo |

## 12. Offline reference data

Catalog and refresh pattern: [docs/OFFLINE-DATA.md](docs/OFFLINE-DATA.md). Each refreshable dataset gets a NiFi flow (nightly by default) whose source URL is a parameter: the public source when connected, an internal mirror when air-gapped. It lands in an Iceberg `ref_*` table.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 12.1 | Catalog of offline datasets, kept as a running list | `docs/OFFLINE-DATA.md` | 1 | Done |
| 12.2 | Refresh pattern: a template NiFi flow (CRON, InvokeHTTP from `#{refdata.<dataset>.url}`, skip if unchanged, normalise, write Iceberg, log row to `ref_refresh_log`); the provisioner creates the `ref_*` tables and parameters, and `status` shows each dataset's age | First dataset refreshes nightly and shows in `status`; primary keys are stable across refreshes (the `ref_*` tables back ontology entity types, and edits must not detach) | 5 | Todo |
| 12.3 | Flight reference flows: FAA registry, OpenSky aircraft DB or tar1090-db, airline designators, routes, OurAirports (feeds 9.4) | Tables populated nightly | 4 | Todo |
| 12.4 | Maritime reference flows: World Port Index, anchorages, MMSI country codes (feeds 4.1a) | Tables populated; detections can join them | 3 | Todo |
| 12.5 | Sanctions flows: OFAC SDN first, then UN, EU and UK; the intel resolver reads `ref_sanctions` instead of downloading at start-up (closes AIRGAP I1) | Resolver works with no internet; Time Travel shows past list versions | 4 | Todo |
| 12.6 | Places: GeoNames and Natural Earth, for an offline reverse geocode that restores the LOC readout in PIPELINE mode (AIRGAP B2) | LOC readout works with the internet off | 3 | Todo |
| 12.7 | Satellite orbits: CelesTrak GP every 6 h, satellite layer enabled in PIPELINE mode | Satellites render in PIPELINE mode | 3 | Todo |
| 12.8 | Knowledge graph rebuild from a fresh Wikidata dump, scripted (it is now a one-off snapshot): land the extract in Iceberg first, then project it into Memgraph, so Organization has a dataset behind it and Memgraph becomes a generated view (section 14) | Rebuild runs end to end | 4 | Todo |
| 12.9 | Licence review for every "confirm" row in the catalog, before customer use | Each row has a confirmed licence | 1 | Todo |

## 13. Deployment model and security markings

Design: [docs/DEPLOYMENT-MODEL.md](docs/DEPLOYMENT-MODEL.md). Boundary rule: no high-side service opens a connection to the public internet; public data arrives only through NiFi; private sensors on the enclave network may connect directly.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 13.1 | Deployment model note: low side, CDS, high side, where each component sits, the boundary rule, video paths, markings | `docs/DEPLOYMENT-MODEL.md` | 1 | Done |
| 13.2 | Two-tier NiFi demo: a low-side process group collects a public feed and writes packaged files to a drop folder; a simulated one-way hand-off moves them; high-side NiFi picks them up and publishes to Kafka. Start with one feed (adsb.lol) | The feed reaches the map only through the hand-off | 5 | Todo |
| 13.3 | Boundary check: a `status` or test step that lists outbound connections from the high-side services (gateway, resolver, tile server, UI, media server) and flags any to the public internet | Check passes in PIPELINE mode; failures name the service and host | 3 | Todo |
| 13.4 | Markings in the lake: the lake job lands `classification` and a new `releasability` field as columns (today `classification` is only inside the raw payload); NiFi flows set both from parameters | Columns populated for every source | 2 | Todo |
| 13.5 | Atlas classifications on the Horus tables and columns, with Ranger tag-based policies; Ranger row-level filter on events by marking versus user attributes; demo with two users who see different rows in Trino | Two users, same query, different rows | 4 | Todo |
| 13.6 | Markings in the UI: the gateway queries as the signed-in user (needs SSO, BURNDOWN-DEPLOY), and popups show each record's marking. Use Helios's caller identity modes (`token` or `impersonate`), the same mechanism the ontology uses (O13) | A restricted record is absent for one user and marked for the other | 4 | Todo |
| 13.7 | MISB/KLV video: parse KLV from a sample MPEG-TS file (sensor position, frame footprint, time) into `camera_segments`, and draw the footprint on the map | A sample FMV clip shows its ground footprint moving on the map | 6 | Todo |

## 14. Ontology (Helios semantic models plus an operational ontology)

Plan: [docs/ONTOLOGY_PLAN.md](docs/ONTOLOGY_PLAN.md). One stack: object types bound to Helios (Ossie) datasets and metrics; entities indexed and editable, observations read in place from Iceberg; actions as the only write path; policies that only narrow what Ranger allows; Flink results as machine-actor actions. Most work happens in the Helios repo, with Horus as the first host; the split is still being settled (the plan's "Helios or Horus" section). Estimates here are the plan's **points** (220 total), not hours, except O0a and O0b, which are hours. Recommended start: O0b, then O0a, then 4.5 (entity tables): all three help Horus before any ontology code exists. The plan moves to the Helios repo when work starts.

| ID | Item | Owner | Pts | Status |
|---|---|---|---|---|
| O0 | Settle the Helios/Horus split: the six open boundaries in the plan (reusable server, stream adapter, Postgres requirement, applications, domain packs, timing against Helios phases 9 and 10) | Both | – | Todo |
| O0a | Entity identity rules: primary keys for Vessel (MMSI changes, IMO missing on small craft, names change) and Aircraft (ICAO hex can be reassigned); how detections' `asset_id` and entity resolution use them. Needed before 4.5. Real case: hormuz.now has 4 MMSIs shared by two different vessels (seen 2026-11-19), which merge into one entity today | Both | 1 h | Todo |
| O0b | Helios semantic model of the Horus lake: run harvest, profile, propose and review against Horus's Trino and publish `horus_lake` (datasets, verified joins, first metrics such as dark hours). Can start now; every object type binds to it | Both | 4 h | Todo |
| O1 | S0 Foundations: ids, branches and revisions in the Helios registry, schema, layering, audit, base types | Helios | 13 | Todo |
| O2 | S1 Object types over Ossie: kinds, properties bound to fields, value types, metrics on types | Helios | 21 | Todo |
| O3 | S2 Links and interfaces, plus `OntologyGraph`/LinkML generated for compatibility | Helios | 21 | Todo |
| O4 | S3 Proposals and review for object types and links | Helios | 13 | Todo |
| O5 | S4 Entity storage: indexer, upserts, edit log, merge, logs copied to Iceberg | Helios | 21 | Todo |
| O6 | S5 Object sets, observations compiled through Helios as the caller | Helios | 21 | Todo |
| O7 | S6 Actions, including machine actors and proposal-only actions; absorbs 4.4 (analyst writeback) | Helios | 21 | Todo |
| O8 | S7 Functions (runner process in Horus) | Both | 13 | Todo |
| O9 | S8 Governance, including policies compiled to Ranger | Helios | 16 | Todo |
| O10 | S9 Side effects and commit stream (Kafka adapter in Horus) | Both | 8 | Todo |
| O11 | S10 Ontology tools (Helios) and HTTP API (Horus) | Both | 13 | Todo |
| O12 | S11 Instance proposals and entity resolution (crawler records, SameAsAssertion, merge, MMSI/IMO/ICAO identity) | Helios | 13 | Todo |
| O13 | S12 Horus host: service, Postgres, sign-in caller (BURNDOWN-DEPLOY C1, C2), Kafka adapter, Flink alerts as actions, object view and map popups | Horus | 13 | Todo |
| O14 | S13 Seeds: OSINT pack and the Horus maritime/aviation extension; first Horus actions (triage alert, flag vessel, watch list from 6.4); Ask Horus `facts_for` (11.4–11.7) and the alerts layer (4.3) switched to object sets | Both | 13 | Todo |

## 15. Multi-source feeds

Several feeds of the same asset type, linked by identity and kept apart as
observations: each feed's report is its own lake row (`event_id` is the feed's
own id), and reports of the same vessel or aircraft share `asset_id` (MMSI, ICAO
hex). The first pair is aisstream.io plus hormuz.now for vessels. Per-source
display, a fused view and geofences are discussed but not yet planned.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 15.1 | hormuz.now vessel flow (`tools/build_hormuz_flow.py`, `nifi/scripts/vessels-hormuz.groovy`): full snapshot every 30 s with ETag caching, Strait of Hormuz and Gulf of Oman; keyed on MMSI like aisstream (no MMSI: `hormuz.now:<id>`); per-vessel local state so only moved vessels are sent, plus a 10-minute heartbeat (hormuz.now's `posAt` shifts every poll, so Flink's dedupe can't catch repeats); navigation aids and reports over 60 min dropped; CC BY 4.0 credit in the popup | Flow imported by `create --yes` and running (2026-11-19); transform tested on a 1,364-vessel snapshot | 4 | Done |
| 15.2 | Gateway vessel merge across feeds: items carry `source`, `sources` (feed to last report time) and `flag`; an older report from another feed only fills missing fields and never moves a vessel back. Also fixed aisstream ship types (`shipType` was never read, so every vessel was "cargo") | Tested with a four-report aisstream/hormuz.now sequence | 2 | Done |
| 15.3 | `tools/flowgen.py`: poll-flow rewiring shared by the OpenSky and hormuz.now builders; trigger set to TIMER_DRIVEN (rebuilding OpenSky from the now-CRON adsb.lol trigger gave an invalid schedule) | OpenSky flow regenerates byte-identical | 1 | Done |
| 15.4 | Generated triggers start invalid: `flowgen` sets the GenerateFlowFile custom text to an empty string, which NiFi imports as "Set empty string" with unique FlowFiles on. Leave the property unset instead; regenerate the OpenSky and hormuz.now flows. Already-imported flows were fixed by hand (seen 2026-11-19) | A fresh import starts with no invalid processors | 0.5 | Todo |
| 15.5 | Verify two-source vessels in the lake: vessels with both `aisstream.io` and `hormuz.now` rows under one `asset_id` (needs aisstream's Dubai-area receiver, silent since 2026-11-18); check the transform's state survives a NiFi restart without re-sending everything as moved | The query finds two-source vessels | 0.5 | Todo |
| 15.6 | Popup LAST UPDATE from the report's own time, not when the gateway received it (a 50-minute-old hormuz.now report shows as fresh). Keep the gateway's TTL on receipt time so lakehouse replay ages as before (10.2) | A delayed report shows its true age | 2 | Todo |
| 15.7 | Licence: hormuz.now's own data is CC BY 4.0, but its positions come from an unnamed tracker's public map tiles; confirm the upstream rights before customer use (as 9.5 for OpenSky) | Decision recorded | – | Todo |

## Carried over

| ID | Item | Status |
|---|---|---|
| C1 | Test the provisioner on a fresh instance; update path for already-imported NiFi flows | Todo |
| C2 | Verify the NWS weather flow contributes rows | Todo |
| C3 | `.project-metadata.yaml` (AMP) | Todo |
| C4 | Fold RUNBOOK.md into INSTALL.md | Todo |
| C7 | Captured-graph gap: the gateway's `graph.py` expects a Neo4j that Horus doesn't run (blocks Ask Horus tier 1, 11.4). Still needed soon; long term the graph is generated from the ontology (O3) | Todo |
| C8 | Optional: delete the unused `horus_hive` SSB catalog and old `osiris-*` Docker Hub images | Todo |
| C9 | UI status bar: `V.4.1` label and the `NEO4J` button that points at localhost | Done: both removed. The graph explorer is O13 |
