# Offline data catalog

This is a running list of every dataset Horus can download once, keep inside
the environment, and use with no internet access. Add a row whenever a feature
needs reference data. Live feeds (aircraft, vessels, earthquakes, fires,
weather) are not listed here; they are the NiFi ingest flows in
[INSTALL.md](INSTALL.md). For runtime internet calls that still exist, see
[AIRGAP.md](AIRGAP.md).

## How refresh works

Each refreshable dataset gets its own NiFi flow, `HORUS - Ref (<dataset>)`, all
built from the same pattern:

1. **Schedule:** a CRON trigger, nightly by default. Datasets that change
   faster can run more often; static datasets don't need a flow.
2. **Fetch:** InvokeHTTP from `#{refdata.<dataset>.url}`. In a connected
   deployment this is the public source. In an air-gapped one it points to an
   internal mirror, which the customer's cross-domain transfer process fills.
   The flow is the same; only the parameter changes.
3. **Skip if unchanged:** compare the ETag, Last-Modified or content hash with
   the last run's, and stop if nothing changed.
4. **Unpack and normalise:** unzip, then convert CSV, XML or JSON into records
   with a fixed schema.
5. **Land:** write to an Iceberg table `horus_<instance>.ref_<dataset>`,
   replacing the previous snapshot. Iceberg keeps older snapshots, so Time
   Travel can show what a list said on a given day. That matters for
   sanctions. Large binary datasets (tiles, imagery, DEM) go to object storage
   instead.
6. **Record:** one row in `ref_refresh_log`: dataset, source, version or
   hash, row count, status and time. The UI and `status` can then show how
   old each dataset is.

Consumers (NiFi enrichment, the gateway, the intel resolver, Flink) read only
the internal copy, never the source.

## Catalog

**Status values:**
- **In use:** shipped and used today.
- **Planned:** has a burndown item.
- **Candidate:** worth adding.

Every licence marked "confirm" must be checked before customer use (12.9).

### Already in Horus

| Dataset | Gives Horus | Source | Licence | Size | Upstream updates | Refresh | Lands in | Status |
|---|---|---|---|---|---|---|---|---|
| Vector basemap tiles | Borders, coastlines, roads and labels on the globe | OpenStreetMap, built into MBTiles (`horus-basemap.mbtiles`) | ODbL (attribution) | ~GB | Continuously | Quarterly rebuild; no NiFi flow needed | Tile server | In use |
| Satellite imagery | Satellite basemap without public tile servers | ESA WorldCover 2021 Sentinel-2 composite | CC BY 4.0 | 9 TB source; MBTiles much smaller | Static (2021) | None (one-off build; [imagery/BURNDOWN-IMAGERY.md](../imagery/BURNDOWN-IMAGERY.md)) | Tile server | Building |
| Knowledge graph base | Companies, places, countries, ownership and location links for Ask Horus and Deep Dive | Wikidata items (`nohumans.ndjson.gz`), loaded into Memgraph (`osiris-graph-base-20260705.tgz`) | CC0 | 0.5 GB dump, 0.1 GB snapshot | Weekly dumps | Monthly or quarterly rebuild, scripted rather than a NiFi flow | Memgraph | In use (rebuild unscripted) |
| UI fonts | Inter and JetBrains Mono | @fontsource packages | OFL | Small | Rarely | With the UI image | UI bundle | In use |

### Flights (9.4)

| Dataset | Gives Horus | Source | Licence | Size | Upstream updates | Refresh | Lands in | Status |
|---|---|---|---|---|---|---|---|---|
| FAA aircraft registry | Registration, owner, type and engine for US aircraft by ICAO hex (Mode S code) | FAA "Releasable Aircraft Database" ZIP | Public domain (US government) | ~60 MB | Daily | Nightly flow | `ref_aircraft_faa` | Planned |
| OpenSky aircraft database | Worldwide registration, type code, operator and owner by ICAO hex | OpenSky metadata CSV | Confirm | ~100 MB | Monthly | Weekly flow | `ref_aircraft` | Planned |
| tar1090-db (Mictronics) | Worldwide hex to registration, type and military flag; the same data adsb.lol uses | GitHub `wiedehopf/tar1090-db` | Confirm | ~30 MB | Weekly | Weekly flow | `ref_aircraft` | Candidate |
| Airline designators | Callsign prefix to airline name and country (`UAL` → United Airlines) | VRS standing data, or OpenFlights `airlines.dat` | Confirm / ODbL | Small | Monthly | Weekly flow | `ref_airlines` | Planned |
| Callsign routes | Callsign to likely origin and destination: most of what the removed FlightAware link gave | VRS standing data (GitHub `vradarserver/standing-data`) | Confirm | ~10 MB | Several times a week | Nightly flow | `ref_routes` | Planned |
| Airports | Airport names, codes, locations and runways, so routes and positions can say "near KORD" | OurAirports CSVs | Public domain | ~15 MB | Nightly | Nightly flow | `ref_airports` | Planned |

### Maritime (4.1a and the vessel ontology)

| Dataset | Gives Horus | Source | Licence | Size | Upstream updates | Refresh | Lands in | Status |
|---|---|---|---|---|---|---|---|---|
| World Port Index | ~3,800 ports with locations, so detections can suppress `STS_ENCOUNTER` and `LOITERING` in harbours | NGA Pub. 150 | Public domain (US government) | ~5 MB | A few times a year | Monthly flow | `ref_ports` | Planned (4.1a) |
| Anchorages | Named anchorage areas, which separate "waiting at anchorage" from suspicious loitering | Global Fishing Watch anchorages | Confirm (may be non-commercial) | ~20 MB | Yearly | Monthly flow | `ref_anchorages` | Planned (4.1a) |
| MMSI country codes (MID) | Flag state from the first three digits of an MMSI | ITU Maritime Identification Digits table | Free to use; confirm | Tiny | Rarely | Static; ships with Horus | `ref_mid` | Candidate |
| Maritime boundaries (EEZ) | Whose waters a vessel is in, which feeds detections ("dark inside an EEZ") and the ontology | Marine Regions EEZ shapefiles | CC BY 4.0 | ~100 MB | Every few years | Static | Object storage, plus a Flink lookup | Candidate |

### Sanctions and watchlists (vessel and company ontology)

| Dataset | Gives Horus | Source | Licence | Size | Upstream updates | Refresh | Lands in | Status |
|---|---|---|---|---|---|---|---|---|
| OFAC SDN list | Sanctioned people, companies and **vessels by IMO number** | US Treasury (XML/CSV); today the intel resolver downloads it from OpenSanctions at start-up (AIRGAP I1) | Public domain (US government) | ~20 MB | Several times a week | Nightly flow; the resolver reads the table instead of downloading | `ref_sanctions` | Planned |
| UN Security Council consolidated list | UN-sanctioned people and entities | UN XML | Free to use | Small | As changed | Nightly flow | `ref_sanctions` | Candidate |
| EU consolidated list | EU financial sanctions | EU Financial Sanctions Files (XML) | Free to use | Small | As changed | Nightly flow | `ref_sanctions` | Candidate |
| UK sanctions list | UK (OFSI) designations, including ships | UK government | Open Government Licence | Small | As changed | Nightly flow | `ref_sanctions` | Candidate |
| OpenSanctions (aggregate) | All of the above de-duplicated, plus many more lists and entity links | OpenSanctions | CC BY-NC (non-commercial); a commercial licence is needed for customers | ~1 GB | Daily | Nightly flow | `ref_sanctions` | Candidate (licence) |

### Places and terrain (7.x: features currently off in PIPELINE mode)

| Dataset | Gives Horus | Source | Licence | Size | Upstream updates | Refresh | Lands in | Status |
|---|---|---|---|---|---|---|---|---|
| GeoNames cities | Offline reverse geocode: brings back the LOC readout in PIPELINE mode, and gives place names for alerts | GeoNames `cities15000` | CC BY 4.0 | ~10 MB | Daily | Weekly flow | `ref_places` | Candidate |
| Natural Earth | Country and admin boundaries, so a position can be given a country | Natural Earth 1:10m | Public domain | ~50 MB | Rarely | Static | `ref_admin` / object storage | Candidate |
| Copernicus DEM (GLO-90) | 3D terrain toggle without public terrain tiles | ESA Copernicus | Free with attribution; confirm | ~TB (global); a region only, for a demo | Static | None (one-off build) | Tile server | Candidate |
| Satellite orbits (TLE/GP) | Satellite layer in PIPELINE mode; positions computed locally from orbits | CelesTrak GP data | Free to use; confirm | ~5 MB | Several times a day | Every 6 h flow | `ref_satellites` | Candidate |

## Adding a dataset

1. Add a row here, with the licence as you found it.
2. Add a burndown item under section 12.
3. Build the flow from the refresh pattern, with the URL as a parameter, and
   add the parameter to the provisioner.
4. Add the table to the provisioner, so `create --yes` makes it and `status`
   checks it.
