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
| 1.4 | Verify against Mistral Studio: `/llm` page, Ask Horus (GraphRAG), pattern-of-life | Three features answer in Workbench | 1 | Todo |
| 1.5 | Docs: INSTALL.md gateway variables; air-gapped option (same variables pointed at an on-prem Mistral or Cloudera AI Inference endpoint) | Section written | 0.5 | Done |
| 1.6 | Confirm with Mistral which models are licensed for on-prem / air-gapped use (Large 4 vs Medium) | Answer recorded here | – | Todo |

## 2. Upstream OSIRIS fixes

The security fixes (Next.js upgrade, upstream security ports) moved to
BURNDOWN-DEPLOY A1 and A2.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 2.3 | Port #370 (derived or missing data not shown as observed) and #469 (reload on chunk load failure) | Ported | 2 | Todo |

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
| 4.1 | SSB jobs: AIS gaps (dark vessels), loitering, ship-to-ship encounters, impossible speed jumps, squawk 7500/7600/7700 → `horus-<instance>-alerts` topic | Alerts flow on the dev instance | 8 | Todo |
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
| 9.2 | adsb.lol flow slowed to every 20 minutes (432 requests a day) | In the repo flow | 0.2 | Done |
| 9.3 | Deploy: OpenSky API client created; `HORUS_OPENSKY_CLIENT_ID` / `_SECRET` set; `tools/nifi_props.py` confirms the OAuth2 property keys; `create --yes` imports the flow; the running adsb.lol flow's schedule changed to 20 min by hand | Aircraft on the map from `source_provider = opensky` | 1 | Todo |
| 9.4 | Enrich OpenSky aircraft with the OpenSky aircraft database (registration, type code, operator): restores model, registration, private-jet and better military classification | Popups show type and registration for OpenSky aircraft | 4 | Todo |
| 9.5 | Licence: OpenSky standard accounts are non-commercial; confirm the licensed tier (or another source) before customer use | Decision recorded | – | Todo |
| 9.6 | Coverage grid for adsb.lol (40–60 points) | – | – | Cut (500 requests a day makes it impractical) |

## Carried over

| ID | Item | Status |
|---|---|---|
| C1 | Test the provisioner on a fresh instance; update path for already-imported NiFi flows | Todo |
| C2 | Verify the NWS weather flow contributes rows | Todo |
| C3 | `.project-metadata.yaml` (AMP) | Todo |
| C4 | Fold RUNBOOK.md into INSTALL.md | Todo |
| C7 | Captured-graph gap: the gateway's `graph.py` expects a Neo4j that Horus doesn't run | Todo |
| C8 | Optional: delete the unused `horus_hive` SSB catalog and old `osiris-*` Docker Hub images | Todo |
| C9 | UI status bar: `V.4.1` label and the `NEO4J` button that points at localhost | Todo |
