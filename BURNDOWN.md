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
| 8.1 | Storage per deployment, with object storage as the standard: the demo and production use the environment's object store (S3 data-lake bucket on CDP in AWS, Ozone on CDP Private Cloud; MinIO or similar elsewhere) under a per-instance prefix the provisioner creates, with read access for the tile service's identity (IDBroker/RAZ on AWS, Ranger on Ozone). Local disk or Workbench project storage only for development. Hand-off (imagery D2): convert the 7 files to PMTiles, copy them to the bucket from the imagery workstation, and verify checksums there; never through the browser upload | Decided and documented in INSTALL.md; the 7 PMTiles verified in the bucket | 3 | Done 2026-11-20: the 7 PMTiles in `s3a://applied-ai-buk-d5eff1ab/data/horus/dev/tiles/` with `SHA256SUMS` (imagery E1, E2), all 7 matching their checksums and their headers' sizes (the global file was first put one 2000 MiB part short and put again); Ranger read policy Horus-TileServer; INSTALL.md steps 7 and 9 |
| 8.2 | Registry format: one list of tile sets with id, kind (`file` or `url`), role (imagery, vector basemap or overlay), title, attribution and licence, marking, capture date or date range, bounds, zoom range and stacking order. File entries are filled from the MBTiles `metadata` table; a small override file holds what the metadata lacks (marking, capture date) | Format written down, with the 7 delivered files as the example | 2 | Done (2026-11-19): [docs/TILESETS.md](docs/TILESETS.md); `services/tileserver/tilesets.toml` (the 7 files and the basemap; a customer server example) and `registry.py` (merge, validation, stacking, public view; `test_registry.py`) |
| 8.3 | Tile server builds its config from the registry: on start, `serve-tiles.py` lists the tile sets (the bucket prefix, or a local folder in development), reads each one's metadata, validates it (raster or vector as declared, Web Mercator, metadata present) and writes `config.json`. A bad file is skipped with a clear log line, not a failed start | The 7 files served with TileJSON at `/data/<id>.json`; a deliberately broken file is reported and skipped | 4 | Doing: built 2026-11-19 for a local folder (`TILESET_DIR`): `tilestore.py` checks each file, `serve-tiles.py` builds the registry and `config.generated.json`, a front proxy serves `/registry.json`. Tested end to end with stand-ins for the 7 files plus the real basemap and three bad files (`services/tileserver/test/run_e2e.sh`). The real 7 after 8.1; reading from the bucket with 8.9 |
| 8.4 | UI layers from the registry at run time: imagery as MapLibre raster sources, global under regional, each limited to its bounds so tiles outside are never requested. The satellite button returns in PIPELINE mode and uses it (PUBLIC mode can still use Esri) | Satellite view works with egress blocked; a new file appears after a tile-server restart, with no UI rebuild | 4 | Doing: built 2026-11-20: the UI reads `/registry.json` on load (`ui/src/lib/tileRegistry.ts`); the satellite button shows Horus's imagery in both modes when the tile server has some (Esri only in PUBLIC mode without it), one raster source per file from its TileJSON, in registry order, under the basemap's roads, borders and labels, added only when the view is first turned on. Type-checked and built; not yet seen in a browser |
| 8.5 | Attribution and marking on the map for every visible tile set (ESA WorldCover / Copernicus, CC BY 4.0, for the delivered set); markings follow section 13 | Attribution and marking visible whenever the layer is | 1 | Todo |
| 8.6 | Customer tile servers as registry entries of kind `url` (XYZ, TMS, WMTS), replacing the single `IMAGERY_TILE_URL` setting planned before; servers that need credentials go through a Horus proxy so the browser never holds them. In an air-gapped site these are enclave servers only (DEPLOYMENT-MODEL.md) | One registry entry adds a customer server's imagery to the map | 3 | Todo |
| 8.7 | Import fresh imagery: a Workbench job that turns a GeoTIFF or COG (later NITF and GeoPackage) into a tile file using the imagery package's recipe (`region.sh`, `finish_mbtiles.py`; the stretch only for raw reflectance, not for imagery that is already 8-bit RGB), then registers it with its capture date | A customer-style GeoTIFF becomes a registered tile set with one command | 8 | Todo |
| 8.8 | Dated imagery: the layer list shows each tile set's capture date, and Time Travel picks the tile set nearest the replay time where several cover the same place | Replaying a past date shows the imagery from that date | 4 | Todo |
| 8.9 | Serve PMTiles from object storage: the tile service reads tile sets from the bucket by range requests with its own credentials (the browser never reaches the bucket), with caching and long cache headers since tiles never change. Checked 2026-11-19: tileserver-gl-light 4.13.3 reads PMTiles from a local file or an unauthenticated HTTP(S) URL only, so it needs a small signing proxy beside it in the same Application (listens on localhost, signs the S3 range requests with the service's credentials). On CDP in AWS the bucket is behind RAZ: settled 2026-11-20, the proxy signs through Cloudera's `raz_client` (boto3 plugin, already in the PBJ runtimes), as the Application's Kerberos user, with a Ranger S3 read policy on the tiles prefix; no AWS keys. `services/tileserver/bucket.py` (list and range reads, with a probe) read all 7 files from the bucket through RAZ; a 16 KB range read takes about 70 ms (delegation token 71 ms median, Kerberos per request 77 ms), so the proxy needs an in-memory cache of tiles and PMTiles directories. On Ozone it uses an S3 access key. This is also where per-tile-set access checks (markings, section 13) are enforced. Needed by 8.3 and 8.4 | The 7 tile sets served from the bucket in the demo environment, with no tile files in Workbench | 6 | Done 2026-11-20: the tile service on the platform reads all 7 from the bucket through RAZ at start (`TILESET_DIR`), and `bucket_proxy.py` serves them to tileserver on localhost with a range cache; a PMTiles shorter than its header says is now skipped as truncated; tested locally against a local S3 server (`test/run_bucket_e2e.sh`). The imagery itself not yet looked at in a viewer: that comes with 8.4 |
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

Design: [docs/DEPLOYMENT-MODEL.md](docs/DEPLOYMENT-MODEL.md). Boundary rule: no high-side service opens a connection to the public internet; public data arrives through one controlled ingest gateway (NiFi in Horus); private sensors on the enclave network may connect directly; anything that writes the canonical envelope to Kafka can feed Horus.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 13.1 | Deployment model note: low side, CDS, high side, where each component sits, the boundary rule, video paths, markings | `docs/DEPLOYMENT-MODEL.md` | 1 | Done |
| 13.2 | Two-tier NiFi demo: a low-side process group collects a public feed and writes packaged files to a drop folder; a simulated one-way hand-off moves them; high-side NiFi picks them up and publishes to Kafka. Start with one feed (adsb.lol) | The feed reaches the map only through the hand-off | 5 | Todo |
| 13.3 | Boundary check: a `status` or test step that lists outbound connections from the high-side services (gateway, resolver, tile server, UI, media server) and flags any to the public internet | Check passes in PIPELINE mode; failures name the service and host | 3 | Todo |
| 13.4 | Markings in the lake: the lake job lands `classification` and a new `releasability` field as columns (today `classification` is only inside the raw payload); NiFi flows set both from parameters. The columns and envelope fields come with lake schema v2 (16.2); what remains here is the NiFi parameters | Columns populated for every source | 1 | Todo |
| 13.5 | Atlas classifications on the Horus tables and columns, with Ranger tag-based policies; Ranger row-level filter on events by marking versus user attributes; demo with two users who see different rows in Trino | Two users, same query, different rows | 4 | Todo |
| 13.6 | Markings in the UI: the gateway queries as the signed-in user (needs SSO, BURNDOWN-DEPLOY), and popups show each record's marking. Use Helios's caller identity modes (`token` or `impersonate`), the same mechanism the ontology uses (O13) | A restricted record is absent for one user and marked for the other | 4 | Todo |
| 13.7 | MISB/KLV video: parse KLV from a sample MPEG-TS file (sensor position, frame footprint, time) into `camera_segments`, and draw the footprint on the map | A sample FMV clip shows its ground footprint moving on the map | 6 | Todo |

## 14. Ontology (Helios semantic models plus an operational ontology)

Plan: [docs/ONTOLOGY_PLAN.md](docs/ONTOLOGY_PLAN.md). One stack: object types bound to Helios (Ossie) datasets and metrics; entities indexed and editable, observations read in place from Iceberg; actions as the only write path; policies that only narrow what Ranger allows; Flink results as machine-actor actions. The design is domain-neutral (any Helios host, for example a car manufacturer; a manufacturing test pack checks it). Most work happens in the Helios repo, with Horus as the first host; the split is still being settled (the plan's "Helios or Horus" section). **UI split (decided 2026-11-19):** a screen built only from the ontology definition and what the caller may see and do ships from Helios as React components (`@helios/ontology-ui`, O15); layout, domain views (the map), navigation and sign-in stay with the host. The components are still a library (no server, state or identity), so "libraries, not a platform" holds. Estimates here are **points**, not hours, except O0a and O0b, which are hours: 270 in total, as in the plan (245 before the UI split added O15, O16 and took 1 from O13). Recommended start: O0b, then O0a, then 4.5 (entity tables): all three help Horus before any ontology code exists. The plan moves to the Helios repo when work starts.

| ID | Item | Owner | Pts | Status |
|---|---|---|---|---|
| O0 | Settle the Helios/Horus split: the four open boundaries in the plan (Postgres requirement, applications, domain packs, timing against Helios phases 9 and 10). Decided 2026-11-19: a reusable reference server and the Kafka adapter both go in Helios; generic ontology screens go in Helios as components (O15), which answers the plan's applications boundary | Both | – | Todo |
| O0a | Entity identity rules, written as the plan's declared identity keys (scheme, strength, scope, validity) so no domain logic is hard-coded: primary keys for Vessel (MMSI changes, IMO missing on small craft, names change) and Aircraft (ICAO hex can be reassigned); how detections' `asset_id` and entity resolution use them. Needed before 4.5. Real case: hormuz.now has 4 MMSIs shared by two different vessels (seen 2026-11-19), which merge into one entity today | Both | 1 h | Todo |
| O0b | Helios semantic model of the Horus lake: run harvest, profile, propose and review against Horus's Trino and publish `horus_lake` (datasets, verified joins, first metrics such as dark hours). Can start now; every object type binds to it | Both | 4 h | Todo |
| O1 | S0 Foundations: ids, branches and revisions in the Helios registry, schema, layering, audit, base types | Helios | 13 | Todo |
| O2 | S1 Object types over Ossie: kinds, properties bound to fields, value types, metrics on types, identity keys, time-series observation types | Helios | 26 | Todo |
| O3 | S2 Links and interfaces (core `Actor`, `Located` with containment, `Occurrence`), plus `OntologyGraph`/LinkML generated for compatibility | Helios | 23 | Todo |
| O4 | S3 Proposals and review for object types and links | Helios | 13 | Todo |
| O5 | S4 Entity storage: indexer, upserts, edit log, merge, logs copied to Iceberg | Helios | 21 | Todo |
| O6 | S5 Object sets, observations compiled through Helios as the caller; deep `traverse` and `within` | Helios | 25 | Todo |
| O7 | S6 Actions, including machine actors, proposal-only actions and state machines; absorbs 4.4 (analyst writeback) | Helios | 24 | Todo |
| O8 | S7 Functions (runner process in Horus) | Both | 13 | Todo |
| O9 | S8 Governance, including policies compiled to Ranger | Helios | 16 | Todo |
| O10 | S9 Side effects, commit stream and the Kafka adapter (now in Helios) | Helios | 11 | Todo |
| O11 | S10 Ontology tools and the `helios-ontology-server` reference server; each host plugs in sign-in. The typed client is a TypeScript package (`@helios/ontology-client`) generated from the OpenAPI, which O15 builds on | Helios | 16 | Todo |
| O12 | S11 Instance proposals and entity resolution (crawler records, SameAsAssertion, merge, resolution driven by declared identity keys) | Helios | 15 | Todo |
| O13 | S12 Horus host: reference server deployed, Postgres, sign-in caller (BURNDOWN-DEPLOY C1, C2), Helios Kafka adapter wired to Horus topics, Flink alerts as actions; Helios components (O15) embedded in the Horus UI with a Horus map renderer for `Located`, and map popups that open the object view | Horus | 10 | Todo |
| O14 | S13 Seeds: OSINT pack, the Horus maritime/aviation extension, and the manufacturing test pack (Helios, proves the core is domain-neutral); first Horus actions (triage alert, flag vessel, watch list from 6.4); Ask Horus `facts_for` (11.4–11.7) and the alerts layer (4.3) switched to object sets | Both | 18 | Todo |
| O15 | S14 `@helios/ontology-ui`, React components rendered from the definition: ObjectView, ObjectSetTable and Explorer (search, filter, search-around), ActionForm (parameters, criteria messages, proposal or commit), ProposalReview queue, ObjectHistory/Explain (edits, sources, lineage), read-only Definition browser. Unstyled with theme tokens; hosts register renderers for property types and link views; take a client and a caller, never sign anyone in. React 18 and 19 as peer dependencies; work as Next.js client components (Horus is Next 16, React 19). Done when the S0–S11 fixtures render with no domain code; O14 then checks the manufacturing test pack and the Horus extension render with no component change. Needs O11 and O12 | Helios | 21 | Todo |
| O16 | S15 Reference console bundled with `helios-ontology-server`: a thin shell composing O15 into a working admin and steward UI, so a new host has a usable UI on day one. After O13, so the components are proven in a real host before a generic shell is built around them | Helios | 5 | Todo |

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

## 16. Lake schema v2 (do before section 8)

The events table today has no partitioning, no maintenance (about 1,300 small
files a day), and keeps altitude, speed, name, category and marking only inside
`payload`. Measured 2026-11-19: 11.2 M rows, 2.7 GB, 2,559 files, about 670 bytes
per row, almost all of it `payload`. Rebuild it now, while it is small and before
the ontology binds to it. The table stays one generic observations table: no
resolved entity ids and no entity attributes (the ontology owns those); typed
views per asset type come later from the Helios semantic model (O0b).

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 16.1 | Schema v2, written down: `tile_z8` (Web Mercator tile at zoom 8, same formula in Flink and Trino); optional `geom_wkt` plus a bounding box for shapes; `alt_m`, `speed_mps`, `course_deg`, `heading_deg`; `display_name`, `asset_subtype`; `id_scheme`; `event_id` as `provider:originalId`; `obs_hash`; `classification`, `releasability`; `captured_at` as a timestamp. Table: partition by day of `event_time`, sort by `tile_z8` then time, zstd, Iceberg format v2. Drafted 2026-11-19 in [docs/LAKE-SCHEMA.md](docs/LAKE-SCHEMA.md), with envelope v2 (the new fields go in the envelope so the Flink job stays generic) and the per-feed backfill rules | Schema agreed and documented | 1 | Done (2026-11-19) |
| 16.2 | Apply it: `ssb/01_events_iceberg_ddl.sql`, `provision/lake.py` and the Flink job `ssb/02_kafka_to_iceberg.sql`; envelope v2 in all eight NiFi scripts (`subtype`, `motion`, `idScheme`, `releasability`, corrected `alt`) and the flows regenerated; resolve LAKE-SCHEMA.md's open checks (zstd property, Flink sink on a partitioned v2 table) | A fresh `create --yes` builds the v2 table and the job fills every column; the live map looks the same in the UI | 5 | Done (2026-11-19): the migration built the v2 table with `lake.ensure_table`; Trino shows every column filled on every feed; live map unchanged. A fresh `create --yes` was tested locally only (fresh instance: C1) |
| 16.3 | Report times, not NiFi's receive time: aisstream from `MetaData.time_utc`; adsb.lol from the response time minus each aircraft's `seen_pos` | aisstream and adsb.lol rows carry report times | 0.5 | Done for aisstream and adsb.lol (2026-11-19, all aisstream rows reported before received). NWS rows had no `effective` time at all (C2), fixed |
| 16.4 | Gateway queries over the lake (history, replay, pattern of life) use the new columns instead of reading `payload` | Time Travel and Pattern of Life work on v2 | 1.5 | Done (2026-11-19): Pattern of Life and Time Travel run on v2 (Strait of Hormuz replay); display problems tracked in C13 |
| 16.5 | Migrate with history, in this order: NiFi scripts to envelope v2 first (`update-scripts --yes`; the v1 job ignores the new fields); stop the v1 lake job in SSB; create v2 (`lake.ensure_table` under a new name), fill it from the old table in Trino using the backfill rules (LAKE-SCHEMA.md; `lake.TILE_Z8_SQL`, `lake.OBS_HASH_SQL`), swap names, start the v2 job from the v1 job's Kafka offsets so every message it reads is v2; keep the old table a week, then drop it | No rows lost; old table dropped | 1 | Doing: migrated 2026-11-19 with `migrate-lake --yes` (job stopped, copied, swapped, v2 job running). Drop `events_iceberg_v1` on or after 2026-11-26 |
| 16.6 | Table maintenance job on a schedule: compact small files applying the sort, expire snapshots, remove orphan files | File count stays flat day to day | 2 | Doing: `maintain-lake --yes` ran on the platform (2026-11-19); the daily Workbench Job could not be created (C14), so it runs by hand until then. Done when the file count stays flat day to day |
| 16.7 | Checks: the Flink and Trino tile formulas agree; a bounding-box query skips most files | Both shown in a test | 1 | Done (2026-11-19): Flink and Trino formulas agree; a compacted day is one run sorted by tile and a Hormuz bbox overlaps 2 of 38 row groups (local Trino); compaction ran on the platform |

## 17. Raw capture (bronze layer; do before the ontology)

Today NiFi turns each upstream response into envelopes before Kafka, and the
upstream response is discarded; `payload` holds the envelope, not the source.
So a bug in a NiFi script loses data for good (the NWS flow wrote empty
properties for weeks: C2). Keep every response as received for a while, so the
silver table can be rebuilt with fixed scripts, and so agent findings can cite
their raw sources. Agreed 2026-11-20.

The branch: every flow fetches with InvokeHTTP (its **Response** relationship)
or ConnectWebSocket (**binary message**; aisstream). A NiFi relationship can feed
more than one connection, and each gets its own copy of the FlowFile, so Response
connects to both the transform script and a second PublishKafka. InvokeHTTP's
**Original** relationship is the empty trigger FlowFile, not the response, so it
isn't the branch.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 17.1 | Measure first: response sizes and rates per flow for a day (InvokeHTTP's `fileSize` in NiFi's provenance, or a counter in each flow). OpenSky's all-states, NWS alerts with their polygons and FIRMS's CSV can each be several MB, and hormuz.now sends a whole snapshot every 30 s, unchanged much of the time | Sizes and daily volume per flow in LAKE-SCHEMA.md | 1 | Todo |
| 17.2 | The raw topic, created by the provisioner per instance: `horus.<instance>.raw`, 7 days retention, `max.message.bytes` above the largest compressed response from 17.1 (Kafka's default is 1 MB); its Ranger Kafka policy printed like the events topic's | `create` makes it; the policy is in INSTALL.md step 7 | 2 | Todo |
| 17.3 | Each flow publishes the response as received: a second PublishKafka on the Response (or binary message) relationship, zstd compression, `max.request.size` to match, NiFi attributes as Kafka headers (flow, source URL, HTTP status, content type, received time). Ships as an update to the 8 flow definitions; already-imported flows need their process group replaced (INSTALL.md step 6) | Every flow writes to both topics; a failed raw publish never blocks the events path | 3 | Todo |
| 17.4 | The bronze table `raw_responses` (Iceberg v2, zstd, partitioned by day and flow): flow, source URL, HTTP status, content type, received time, body, body bytes and SHA-256. Written by a second Flink job from the raw topic. Identical consecutive bodies from the same flow (an unchanged hormuz.now snapshot) are stored once, keyed on the SHA-256 | Rows for every flow in the demo environment | 3 | Todo |
| 17.5 | Retention: `maintain-lake` deletes `raw_responses` days older than `RAW_RETENTION_DAYS` (default 90; bronze is for recovery and provenance, not history) and compacts it like `events` | A day older than the setting is gone after the nightly run | 1 | Todo |
| 17.6 | `horus.py rebuild-from-raw --flow <flow> --from <day> --to <day>`: runs the flow's current NiFi script over its raw rows (the nifi/test harness already runs the scripts outside NiFi), then replaces that flow's rows in `events` for those days, with `obs_hash` dedupe so a re-run is safe. Dry run by default, like `migrate-lake` | A deliberately broken script's days are rebuilt correctly after the fix, in a test | 4 | Todo |
| 17.7 | Access: bronze is source data with no marking columns, so its Ranger policies are admin and service users only; agents and the UI read silver and the ontology, never bronze, except to cite a source record by id | Policies in INSTALL.md step 7 | 1 | Todo |

## Carried over

| ID | Item | Status |
|---|---|---|
| C1 | Test the provisioner on a fresh instance; update path for already-imported NiFi flows. Scripts: `horus.py update-scripts` (2026-11-19, not yet run on the platform); other flow changes still need a delete and re-import | Todo |
| C2 | Verify the NWS weather flow contributes rows. It did, but empty (2026-11-19): every alert had a generic title, no times and no area, because the script read `f['properties']`, which in the platform's NiFi returned bean properties (USGS uses `.get('properties')` and works). Fixed with `.get('properties')`; `nifi/test/run.sh` now fails on the old pattern | Doing: fix pushed; run `update-scripts --yes`, then NWS rows should have headlines and `effective` times |
| C3 | `.project-metadata.yaml` (AMP) | Todo |
| C4 | Fold RUNBOOK.md into INSTALL.md | Todo |
| C7 | Captured-graph gap: the gateway's `graph.py` expects a Neo4j that Horus doesn't run (blocks Ask Horus tier 1, 11.4). Still needed soon; long term the graph is generated from the ontology (O3) | Todo |
| C8 | Optional: delete the unused `horus_hive` SSB catalog and old `osiris-*` Docker Hub images | Todo |
| C9 | UI status bar: `V.4.1` label and the `NEO4J` button that points at localhost | Done: both removed. The graph explorer is O13 |
| C10 | Fires: the gateway stored every re-sent FIRMS detection as a new point (the fire item had no `id`, so each got a one-off key; 35K on the map, 2026-11-19), now keyed on the entity id; flame icon instead of an orange dot (vessels are orange dots too); popup says "thermal anomaly" with confidence, fire power and detection time | Done (2026-11-19); check fire count and icon on the platform |
| C12 | Pattern of Life feels slow (2026-11-19): per-stage timings (graph resolve, lake bounds, asset track, LLM first token and total) in the gateway log line, the `done` event and the log row, with a trace id also sent to the resolver as `X-Trace-Id`. Measured: everything before the LLM about 1 s; Mistral Large 4's silent reasoning 22–56 s before the first word, then the answer in about 1 s. Fixed: Pattern of Life asks for `low` reasoning (`POL_REASONING_EFFORT`; Large 4 rejects `none`). Also fixed, found in the same answers: the UI sent the MMSI as the IMO when there was none; popups stripped ':' and spaces from ids and names (`hormuz.now:9571704` lost its colon, so its track lookup found nothing); the gateway put non-MMSI ids in `mmsi`; an empty track was worded so the model called it a dropout | Doing: fixes in; check the timing with `low` on the platform |
| C13 | Time Travel display (seen 2026-11-19): assets blink because the replay shows a report for a fixed 2 min (`TRAIL_MS`) but feeds report less often: adsb.lol flights every 12 min, hormuz.now stationary vessels every 10 min (heartbeat). Keep each asset until about one feed interval after its last report (per source), so ships at anchor and polled flights stay put; then reduce the clutter of dense areas (the Strait at 60x). Later: interpolate between reports, and one position per vessel when two feeds report it | Todo |
| C15 | Lake growth: about 5 M rows and 1 GB a day (2026-11-18/19, almost all aisstream), about 365 GB a year with nothing deleted. Decide a retention rule or thinning of old vessel positions (for example keep one position per vessel per minute after 30 days) before a long-running demo; maintenance would apply it | Todo |
| C14 | The daily lake-maintenance Workbench Job: `maintain-lake --yes` reported it could not be created through the Workbench API (2026-11-19). Read the printed reason, fix `ensure_maintenance_job` (or create the Job by hand with the printed settings) | Todo |
| C11 | Fires at sea: FIRMS near-real-time data can't tell gas flares from fires (only the later standard product has the offshore type). Mark detections over water as likely gas flares using an offline land outline (section 12), in the popup and with a different icon | Todo |
| C16 | Conflict zones (2026-11-20): the UI drew 13 hard-coded markers from the upstream OSIRIS code, labelled "Live reporting", always on with no toggle. If conflict data comes back it is a real feed through NiFi into the lake (ACLED is the candidate; GDELT is already a feed), shown from the lake or from agents working over it | Done: removed. Revisit with the source decision |
