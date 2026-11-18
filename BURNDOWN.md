# Burn-down: Horus

Status values: Todo / Doing / Done / Blocked / Cut. Estimates are hours.
Work the sections in order; each builds on the one before.

## 1. Mistral as the LLM (Large 4 where possible)

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 1.1 | Gateway `llm.py`: provider-neutral `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (old `OPENAI_*` still read), default model `mistral-large-4`, optional `LLM_REASONING_EFFORT` | `/llm/health` reports the Mistral model and `available: true` | 2 | Done |
| 1.2 | Handle Mistral streaming: text deltas, and reasoning ("thinking") chunks dropped from the answer | `/llm/chat` and Ask Horus stream clean text from Large 4 (mock-tested 2026-11-18; live check is 1.4) | 1 | Done |
| 1.3 | Remove the unused Gemini path from the UI (`AiAnalyst`, `/api/ai/*`, `ai-engine`, `@google/generative-ai`); no LLM keys in browsers | No `gemini` left in `ui/src`; build passes | 1 | Done |
| 1.4 | Verify against Mistral Studio: `/llm` page, Ask Horus (GraphRAG), pattern-of-life | Three features answer in Workbench | 1 | Todo |
| 1.5 | Docs: INSTALL.md gateway variables; air-gapped option (same variables pointed at an on-prem Mistral or Cloudera AI Inference endpoint) | Section written | 0.5 | Done |
| 1.6 | Confirm with Mistral which models are licensed for on-prem / air-gapped use (Large 4 vs Medium) | Answer recorded here | – | Todo |

## 2. Upstream OSIRIS security fixes

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 2.1 | Next.js 16.2.6 → 16.4.3 (security advisories) | Build and smoke test pass | 1 | Todo |
| 2.2 | Port: image optimizer disabled, tile proxy narrowed, ArcGIS server-side request forgery fix, rate limits that bind | Each fix ported or confirmed not applicable | 3 | Todo |
| 2.3 | Port #370 (derived or missing data not shown as observed) and #469 (reload on chunk load failure) | Ported | 2 | Todo |

## 3. Horus MCP server

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 3.1 | Port `osiris/mcp-server` to `services/mcp`: rename, point at the Horus Applications | Tools answer against the dev instance | 3 | Todo |
| 3.2 | Bearer token required on `/mcp`; Memgraph shim token passed through | Unauthenticated call rejected | 1 | Todo |
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
| 5.5 | Read-only workload user, read-only Ranger policies, isolated project; validation pass on findings | Policies in place | 2 | Todo |

## 6. Upstream camera, flight and map features; real identity

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| 6.1 | Camera sources and catalogue cache, preview tiles, close-up viewer, HLS/YouTube playback (check each source's terms) | Cameras render in PUBLIC mode | 8 | Todo |
| 6.2 | Camera catalogue as a NiFi feed so cameras work in PIPELINE mode | Cameras render in PIPELINE mode | 4 | Todo |
| 6.3 | AI Analyze (YOLOX-nano in the browser, model file self-hosted); Identify routed to Mistral through the gateway | Works with no browser key | 4 | Todo |
| 6.4 | Flights: airframe identity, flown tracks (from the lake), multi-aircraft watch | Ported | 6 | Todo |
| 6.5 | SSO in front of every Application; per-user identity through to Trino and Ranger; drop unauthenticated access | No Application open without login | 8 | Todo |

## Carried over

| ID | Item | Status |
|---|---|---|
| C1 | Test the provisioner on a fresh instance; update path for already-imported NiFi flows | Todo |
| C2 | Verify the NWS weather flow contributes rows | Todo |
| C3 | `.project-metadata.yaml` (AMP) | Todo |
| C4 | Fold RUNBOOK.md into INSTALL.md | Todo |
| C5 | Remove the CDP access key from the Workbench project | Todo |
| C6 | Rotate the Kafka password committed in the OSIRIS repo | Todo |
| C7 | Captured-graph gap: the gateway's `graph.py` expects a Neo4j that Horus doesn't run | Todo |
| C8 | Optional: delete the unused `horus_hive` SSB catalog and old `osiris-*` Docker Hub images | Todo |
| C9 | UI status bar: `V.4.1` label and the `NEO4J` button that points at localhost | Todo |
