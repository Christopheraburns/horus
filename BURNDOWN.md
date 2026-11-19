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
| 3.1 | Port `osiris/mcp-server` to `services/mcp`: rename, point at the Horus Applications | Tools answer against the dev instance | 3 | Todo |
| 3.2 | Bearer token on `/mcp`: moved to BURNDOWN-DEPLOY C3 | – | – | Moved |
| 3.3 | New tools: lake history query (read-only), alerts, findings | Tools listed and tested | 3 | Todo |
| 3.4 | Register as a Mistral Studio connector and a Cloudera Agent Studio MCP server | An agent calls a tool from each | 1 | Todo |

## 4. Flink detections, alerts and findings

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 4.1 | SSB jobs: AIS gaps (dark vessels), loitering, ship-to-ship encounters, impossible speed jumps, squawk 7500/7600/7700 → `horus-<instance>-alerts` topic | Alerts flow on the dev instance | 8 | Built, awaiting dev run: `ssb/04_detections.sql`, job `horus_<instance>_detections`; passes `ssb/test/run_local.sh` (7/7 cases on Flink 1.19). Run `create --yes`, then `tools/tail_alerts.py` |
| 4.1a | Port and anchorage reference data (self-hosted) to suppress `STS_ENCOUNTER` and `LOITERING` in harbours; tune thresholds on a day of real alerts | False-positive rate acceptable for a demo | 3 | Todo |
| 4.2 | Iceberg tables `alerts_iceberg` and `findings_iceberg` created by the provisioner | `status` shows both | 2 | Todo |
| 4.3 | Gateway and UI: ALERTS and AGENT FINDINGS map layers, Time Travel aware | Layers render | 4 | Todo |
| 4.4 | Analyst writeback: flag and annotate an entity or alert, stored in Iceberg | Note survives restart and shows in Time Travel | 4 | Todo |

## 5. Prime Agent anomaly investigations

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 5.1 | Trino backend for the Optiness lakehouse skill (or an Impala VW over the same table) | Skill queries `events_iceberg` | 3 | Todo |
| 5.2 | Skills: graph (Memgraph read-only), intel resolver, live feeds (or reuse the MCP server) | Callable from the REPL | 3 | Todo |
| 5.3 | Investigation method for maritime and aviation anomalies, split by day, entity type and region | Method in AGENTS.md | 3 | Todo |
| 5.4 | Findings written to `findings_iceberg` with SQL and row counts; shown on the map | One investigation end to end | 4 | Todo |
| 5.5 | Read-only workload user, read-only Ranger policies, isolated project; validation pass on findings (agent guardrails, needed even for demos) | Policies in place | 2 | Todo |

## 6. Upstream camera, flight and map features

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 6.1 | Camera sources and catalogue cache, preview tiles, close-up viewer, HLS/YouTube playback (check each source's terms) | Cameras render in PUBLIC mode | 8 | Todo |
| 6.2 | Camera catalogue as a NiFi feed so cameras work in PIPELINE mode | Cameras render in PIPELINE mode | 4 | Todo |
| 6.3 | AI Analyze (YOLOX-nano in the browser, model file self-hosted); Identify routed to Mistral through the gateway | Works with no browser key | 4 | Todo |
| 6.4 | Flights: airframe identity, flown tracks (from the lake), multi-aircraft watch | Ported | 6 | Todo |

## 7. Air-gap readiness (PIPELINE mode with no internet calls)

Inventory and details: [docs/AIRGAP.md](docs/AIRGAP.md). Image and install-time items are in [BURNDOWN-DEPLOY.md](BURNDOWN-DEPLOY.md).

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 7.1 | Self-host the web fonts | No `fonts.googleapis.com` request | 0.5 | Done |
| 7.2 | PIPELINE mode: no reverse geocode under the cursor | No `nominatim` request while panning | 0.5 | Done |
| 7.3 | PIPELINE mode: global stats from gateway feeds only | `/api/stats` makes no public calls | 1 | Done |
| 7.4 | PIPELINE mode: hide satellite imagery and 3D buildings; no OpenFreeMap fallback | No Esri or OpenFreeMap request | 1 | Done |
| 7.5 | PIPELINE mode: region dossier and search from Memgraph, plus coordinate entry | No Nominatim, Wikipedia, Wikidata or restcountries request | 4 | Todo |
| 7.6 | Intel resolver: bundled OFAC file; countries from Memgraph; IP lookups off in secure mode | Resolver starts and answers with egress blocked | 3 | Todo |
| 7.7 | Dependencies baked into images: moved to BURNDOWN-DEPLOY section B | – | – | Moved |
| 7.8 | Egress test: headless browser in PIPELINE mode records every request; fails on non-Horus hosts | Test passes | 2 | Todo |
| 7.9 | Sync the browser's SOURCE flag with the server (intel `secure=1`) | Toggle changes intel source | 1 | Todo |
| 7.10 | Splash screen removed; fly-to-city disabled (code kept) | Done 2026-11-18 | 0.5 | Done |

## 8. Offline satellite imagery (Horus side)

The imagery tiles are built separately, on another machine:
[imagery/BURNDOWN-IMAGERY.md](imagery/BURNDOWN-IMAGERY.md) (ESA WorldCover 2021,
10 m; global base plus regions of interest to zoom 14, delivered as raster
MBTiles). These items connect them to Horus.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 8.1 | Tile server `config.json`: add each imagery MBTiles as a data source; check the served TileJSON | `/data/horus-imagery-*.json` served | 1 | Todo |
| 8.2 | UI: imagery as a MapLibre raster layer from the Horus tile server; the satellite button returns in PIPELINE mode and uses it (PUBLIC mode can still use Esri) | Satellite view works with egress blocked | 3 | Todo |
| 8.3 | Map attribution for ESA WorldCover / Copernicus (CC BY 4.0) shown whenever the imagery is visible | Attribution visible | 0.5 | Todo |
| 8.4 | Setting for a customer's own imagery server (`IMAGERY_TILE_URL`), read at run time | One setting switches the source | 1 | Todo |
| 8.5 | Where the imagery files live in Workbench (project storage, a volume, or object storage) and how they get there | Decided and documented in INSTALL.md | 1 | Todo |

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
| 11.3 | Record every generated answer (question, entity, facts used, model, timestamp) in an Iceberg table: an audit trail and lineage for AI output | Answers queryable in Trino | 3 | Todo |
| 11.4 | Ask Horus tier 1 (Attribution) with real facts: gateway graph on Memgraph (C7) plus the offline aircraft database (12.3) for operator, type and registration; vessels too (MMSI country code, ShipStaticData, Memgraph by IMO) | Tier 1 answers with an operator and type for a typical airliner and a typical vessel | 3 | Todo |
| 11.5 | Ask Horus tier 5 (Anomaly): the entity's alerts from the alerts topic (4.1, read by the gateway in 4.3) given to the LLM as facts | An entity with an alert gets an explanation of it | 2 | Todo |
| 11.6 | Ask Horus tier 3 (Spatial): what is within N km now, from the gateway's live snapshot (aircraft, vessels, events, alerts), plus nearest port and maritime zone (12.4) | Answer names nearby entities with distances | 3 | Todo |
| 11.7 | Ask Horus tier 2 (Operator): the operator's other assets from Memgraph, sanctions from `ref_sanctions` (12.5), registration-country context | Answer lists the fleet and any sanctions hit | 3 | Todo |
| 11.8 | Tier 4 (Pattern): reuse Pattern of Life rather than build a second history answer; one panel, tiers relabelled to match what is built. Tiers 2–5 are hidden in the UI until each one is built (re-add to `INTEL_TIERS` as it lands) | No disabled placeholder buttons; every visible tier works | 1 | Todo |

## 12. Offline reference data

Catalog and refresh pattern: [docs/OFFLINE-DATA.md](docs/OFFLINE-DATA.md). Each refreshable dataset gets a NiFi flow (nightly by default) whose source URL is a parameter: the public source when connected, an internal mirror when air-gapped. It lands in an Iceberg `ref_*` table.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 12.1 | Catalog of offline datasets, kept as a running list | `docs/OFFLINE-DATA.md` | 1 | Done |
| 12.2 | Refresh pattern: a template NiFi flow (CRON, InvokeHTTP from `#{refdata.<dataset>.url}`, skip if unchanged, normalise, write Iceberg, log row to `ref_refresh_log`); the provisioner creates the `ref_*` tables and parameters, and `status` shows each dataset's age | First dataset refreshes nightly and shows in `status` | 5 | Todo |
| 12.3 | Flight reference flows: FAA registry, OpenSky aircraft DB or tar1090-db, airline designators, routes, OurAirports (feeds 9.4) | Tables populated nightly | 4 | Todo |
| 12.4 | Maritime reference flows: World Port Index, anchorages, MMSI country codes (feeds 4.1a) | Tables populated; detections can join them | 3 | Todo |
| 12.5 | Sanctions flows: OFAC SDN first, then UN, EU and UK; the intel resolver reads `ref_sanctions` instead of downloading at start-up (closes AIRGAP I1) | Resolver works with no internet; Time Travel shows past list versions | 4 | Todo |
| 12.6 | Places: GeoNames and Natural Earth, for an offline reverse geocode that restores the LOC readout in PIPELINE mode (AIRGAP B2) | LOC readout works with the internet off | 3 | Todo |
| 12.7 | Satellite orbits: CelesTrak GP every 6 h, satellite layer enabled in PIPELINE mode | Satellites render in PIPELINE mode | 3 | Todo |
| 12.8 | Knowledge graph rebuild from a fresh Wikidata dump, scripted (it is now a one-off snapshot) | Rebuild runs end to end | 4 | Todo |
| 12.9 | Licence review for every "confirm" row in the catalog, before customer use | Each row has a confirmed licence | 1 | Todo |

## Carried over

| ID | Item | Status |
|---|---|---|
| C1 | Test the provisioner on a fresh instance; update path for already-imported NiFi flows | Todo |
| C2 | Verify the NWS weather flow contributes rows | Todo |
| C3 | `.project-metadata.yaml` (AMP) | Todo |
| C4 | Fold RUNBOOK.md into INSTALL.md | Todo |
| C7 | Captured-graph gap: the gateway's `graph.py` expects a Neo4j that Horus doesn't run (blocks Ask Horus tier 1, 11.4) | Todo |
| C8 | Optional: delete the unused `horus_hive` SSB catalog and old `osiris-*` Docker Hub images | Todo |
| C9 | UI status bar: `V.4.1` label and the `NEO4J` button that points at localhost | Todo |
