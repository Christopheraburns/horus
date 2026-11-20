# Horus internet access inventory

This lists every place Horus reaches the public internet, so a demo can state
exactly what an air-gapped deployment needs. It was audited from the code on
2026-11-18.

**Goal for the air-gapped story.** In **SOURCE: PIPELINE** mode:
- The browser talks only to Horus.
- Horus talks only to the CDP environment, plus two configurable edges:
  - the NiFi ingest sources
  - the LLM endpoint

Section 8 lists what is still needed to make that true.

Legend: **Always** means it happens in both modes. **PUBLIC** means it happens
only when SOURCE is set to PUBLIC. **On use** means it happens only when a user
takes that action.

## 1. Ingest edge (by design)

These are the data sources. In an air-gapped site they point at on-prem
sources, or at a data diode. Alternatively, the gateway can replay captured
history from the lake (`GATEWAY_SOURCE_MODE=lakehouse`), which needs no live
feed at all.

| NiFi flow | Endpoint |
|---|---|
| Earthquakes | `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson` |
| Fires | `https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_24h.csv` |
| Flights | `https://api.adsb.lol/v2/point/…` |
| Vessels | `wss://stream.aisstream.io/v0/stream` (needs `HORUS_AISSTREAM_API_KEY`) |
| Vessels (hormuz.now) | `https://hormuz.now/api/snapshot`, every 30 s; Strait of Hormuz and Gulf of Oman only (24–28.5°N, 54–59°E); no key; CC BY 4.0 |
| Weather (EONET) | `https://eonet.gsfc.nasa.gov/api/v3/events` |
| Weather (NWS) | `https://api.weather.gov/alerts/active` |

## 2. LLM endpoint (configurable)

| Where | Endpoint | When | Air-gapped |
|---|---|---|---|
| feeds-gateway [llm.py](../services/feeds-gateway/llm.py) | `LLM_BASE_URL`, default `https://api.mistral.ai/v1` | On use: `/llm` page, Ask Horus, pattern-of-life | Point `LLM_BASE_URL` at on-prem Mistral or Cloudera AI Inference |

## 3. Install and start-up time

| What | Endpoint | When | Air-gapped |
|---|---|---|---|
| Runtime images | Docker Hub (`docker.io/christopheraburns/horus-*-runtime`) | Registering a runtime, and on first use on each node | Mirror the images to an internal registry (`HORUS_REGISTRY=… runtimes/build.sh --push`) |
| Runtime image build | nodesource, the Memgraph `.deb`, Cloudera's registry | Building the images only | Build where there is internet access, then mirror |
| Workbench project | GitHub (git clone, git pull) | Project creation and updates | Internal git server |
| UI, intel resolver, tile server | `registry.npmjs.org` (`npm ci`) | First start of each Application | Bake `node_modules` into the image, or use an internal npm mirror |
| feeds-gateway | PyPI (`pip install -r requirements.txt`) | Cold start, when modules are missing | Bake the packages into the image, or use an internal PyPI mirror |
| Provisioner | CDP control plane API; PyPI for `cdpcli` | Provisioning only | CDP Private Cloud control plane |
| `rebuild-from-raw` | Maven Central (`groovy-4.0.24.jar`, `groovy-json-4.0.24.jar`) | First rebuild in a session only | Copy the two jars into the project and set `GROOVY_JARS_DIR` |

Next.js telemetry is already disabled (`NEXT_TELEMETRY_DISABLED=1` in [launch_ui.py](../ui/launch_ui.py)).

## 4. Browser: always, or on use

| # | What | Endpoint | When | Code |
|---|---|---|---|---|
| B1 | Web fonts (Inter, JetBrains Mono) | `fonts.googleapis.com`, `fonts.gstatic.com` | **Always**, every page load | [globals.css:1](../ui/src/app/globals.css#L1), [layout.tsx](../ui/src/app/layout.tsx) — **Fixed (7.1):** fonts are self-hosted with `@fontsource` and bundled into the build. |
| B2 | Place name under the cursor (reverse geocode) | `nominatim.openstreetmap.org/reverse` | **Always**, as the mouse moves (throttled and cached) | [page.tsx:277](../ui/src/app/page.tsx#L277) — **Fixed (7.2):** off in PIPELINE mode; the LOC readout is hidden and COORD remains. |
| B3 | Search bar | `nominatim.openstreetmap.org/search` | On use | [SearchBar.tsx:170](../ui/src/components/SearchBar.tsx#L170) |
| B4 | Satellite basemap | `server.arcgisonline.com` (Esri World Imagery) | On use: satellite map style | [page.tsx:638](../ui/src/app/page.tsx#L638), [HorusMap.tsx:1484](../ui/src/components/HorusMap.tsx#L1484) — **Fixed (7.4):** the toggle is hidden in PIPELINE mode, and switching to PIPELINE turns it off. |
| B5 | 3D buildings | `tiles.openfreemap.org/planet` | On use: 3D terrain toggle | [HorusMap.tsx:1417](../ui/src/components/HorusMap.tsx#L1417) — **Fixed (7.4):** the layer is hidden in PIPELINE mode, and switching to PIPELINE turns it off. |
| B6 | Fallback basemap | `tiles.openfreemap.org/styles/dark` | Only if the Horus tile server fails | [tileProxy.ts](../ui/src/lib/tileProxy.ts), [HorusMap.tsx:162](../ui/src/components/HorusMap.tsx#L162) — **Fixed (7.4):** there is no fallback in PIPELINE mode; the map stays on the Horus tile server. |
| B7 | Camera images and video | each camera operator's host (about 60 sources) | PUBLIC: CCTV layer | [CameraViewer.tsx](../ui/src/components/CameraViewer.tsx) |
| B8 | Embedded video | `youtube.com`, `youtube-nocookie.com`, `rumble.com` | PUBLIC: live news and alerts | [LiveAlerts.tsx](../ui/src/components/LiveAlerts.tsx) |
| B9 | Links in popups and the Share panel | FlightAware, MarineTraffic, Google Maps, X, Reddit, LinkedIn and others | Only when clicked; these are navigations, not background calls | **Fixed (2026-11-18):** all external links removed from the map popups and the Share panel. Camera and news-feed source links remain (PUBLIC-mode features). |

## 5. UI server: always, or on use

| # | What | Endpoint | When | Code |
|---|---|---|---|---|
| S1 | Global stats | runs `/api/satellites`, `/api/cctv`, `/api/infrastructure` and `/api/gdelt` on the server, each calling its public source (flights and weather use the gateway) | **Always**, on page load | [page.tsx:230](../ui/src/app/page.tsx#L230), [api/stats](../ui/src/app/api/stats/route.ts) — **Fixed (7.3):** PIPELINE mode counts only flights and weather from the gateway; the other four are skipped. |
| S2 | Region dossier | `nominatim.openstreetmap.org`, `restcountries.com`, `en.wikipedia.org`, `query.wikidata.org` | On use: right-click on the map | [api/region-dossier](../ui/src/app/api/region-dossier/route.ts) |
| S3 | Fly to your city | `ip-api.com`, `ipapi.co`, `freeipapi.com` | **Disabled** (`FLY_TO_VISITOR_CITY = false`) | [api/geo](../ui/src/app/api/geo/route.ts) |
| S4 | Entity intel | the Horus intel resolver (see section 6) | On use: opening an entity | [api/entity/expand](../ui/src/app/api/entity/expand/route.ts) |

## 6. Intel resolver

| # | What | Endpoint | When |
|---|---|---|---|
| I1 | OFAC SDN sanctions list | `data.opensanctions.org` (CSV) | **Always**, at start-up and every 24 h |
| I2 | Country lookups | `query.wikidata.org`, `www.wikidata.org` | On use; there is no Memgraph path |
| I3 | IP lookups | `ip-api.com` (plain HTTP), `stat.ripe.net` | On use; there is no Memgraph path |
| I4 | Aircraft, vessel, company, person | Wikidata | Only without `secure=1`. With `secure=1` they resolve from Memgraph. |

The UI sends `secure=1` based on the browser's copy of the SOURCE flag, which
isn't synced with the server toggle. Since the pipeline-mode default, it is
always `secure=1`. That's fine for the air-gapped demo, but it is a bug (8.9).

## 7. UI server: PUBLIC mode only

When SOURCE is PUBLIC, these API routes fetch their public sources directly.
PIPELINE mode suppresses them in the browser, but S1 still calls some of them.

| Route | Endpoint |
|---|---|
| `/api/flights` | `opensky-network.org`, `api.airplanes.live`, `api.adsb.lol` |
| `/api/maritime` | `aisstream.io` (WebSocket). Opens on the first PUBLIC request and closes when SOURCE is PIPELINE; verified 0 connections in PIPELINE mode. Key: `AIS_API_KEY`, or the project's `HORUS_AISSTREAM_API_KEY` |
| `/api/earthquakes`, `/api/infrastructure`, `/api/scm-suppliers`, `/api/country-risk` | `earthquake.usgs.gov` |
| `/api/fires` | `firms.modaps.eosdis.nasa.gov`, `eonet.gsfc.nasa.gov` |
| `/api/weather` | `api.weather.gov`, `eonet.gsfc.nasa.gov` |
| `/api/satellites` | `celestrak.org`, `db.satnogs.org` |
| `/api/cctv` (and `/stream-status`) | about 60 camera operators |
| `/api/gdelt` | `api.gdeltproject.org` |
| `/api/news` | Telegram (`t.me`), BBC, Al Jazeera, GDACS, Bulgarian news sites |
| `/api/live-news` | YouTube, Rumble |
| `/api/malware` | `feodotracker.abuse.ch`, `urlhaus.abuse.ch`, `ip-api.com` |
| `/api/cyber-threats` | `cisa.gov`, `dashboard.shadowserver.org` |
| `/api/radar` | IODA (`api.ioda.inetintel.cc.gatech.edu`) |
| `/api/air-quality` | `api.openaq.org` |
| `/api/sentinel` | Copernicus, Element 84 (AWS) |
| `/api/crypto` | `api.coingecko.com` (only used by an unmounted component) |
| `/api/proxy-tiles` | CARTO (a legacy fallback, unused with the Horus tile server) |

These make no internet calls: the Memgraph Application, the tile server at
runtime (local mbtiles, fonts and sprites), and the feeds-gateway apart from
the LLM. The gateway talks only to Kafka, Trino and Memgraph inside the CDP
environment.

## 8. Making PIPELINE mode internet-free

| # | Fix | Closes | Size |
|---|---|---|---|
| 8.1 | Self-host the two fonts — **done** | B1 | S |
| 8.2 | In PIPELINE mode, show coordinates only, with no reverse geocode — **done** | B2 | S |
| 8.3 | In PIPELINE mode, compute global stats from the gateway feeds only — **done** | S1 | S |
| 8.4 | In PIPELINE mode, hide the satellite style and 3D buildings toggles, and show an error instead of the OpenFreeMap fallback — **done** | B4, B5, B6 | S |
| 8.5 | Region dossier and search in PIPELINE mode from Memgraph (Country and Place nodes) and coordinate entry; otherwise disabled | S2, B3 | M |
| 8.6 | Intel resolver: load the OFAC list from a bundled file (`INTEL_SDN_FILE`); in secure mode, resolve countries from Memgraph and turn IP lookups off | I1, I2, I3 | S |
| 8.7 | Bake npm and pip dependencies into the runtime images, or document internal mirrors | section 3 | M |
| 8.8 | Prove it: load the UI in a headless browser in PIPELINE mode, record every network request, and fail on any host outside Horus | all | S |
| 8.9 | Sync the browser's SOURCE flag with the server for intel `secure=1` | I4 | S |
