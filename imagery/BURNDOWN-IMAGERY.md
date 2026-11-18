# Burn-down: offline satellite imagery for Horus

This is a self-contained work package. It produces satellite imagery tiles that
Horus serves from its own tile server, with no internet access at view time. It
is meant to run on a separate machine (a Windows workstation) while the rest of
Horus development continues elsewhere. Everything needed to start is in this
file.

Status values: Todo / Doing / Done / Blocked / Cut. Estimates are hours.

## Why

Horus demonstrates an air-gap-capable system. Its map has a satellite view,
but today that view loads Esri World Imagery from the internet, so it is hidden
in PIPELINE mode. This package replaces it with imagery Horus hosts itself.

## Decisions already made (don't revisit)

- **Source: ESA WorldCover 2021 Sentinel-2 composites.** Ten-metre, cloud-free
  yearly median, global, CC BY 4.0. Not EOX Sentinel-2 cloudless: the 2016
  edition is too old, and later editions are non-commercial only. Not a custom
  Copernicus mosaic: too much work for now.
- **Renderer stays MapLibre GL** (already in the Horus UI). No CesiumJS.
- **Serving stays tileserver-gl-light** (already a Horus Application). Imagery
  is delivered as **raster MBTiles** and added to its `config.json`. No new
  service.
- **Depth: global base at low zoom, plus full depth (zoom 14) for selected
  regions of interest.** Not global zoom 14 (about 2.5 TB).
- Ten metres per pixel is the ceiling: ports, runways, road networks and city
  blocks are visible; individual buildings, vehicles and ships are not.
  Sub-metre imagery would come later from a customer-licensed source.

## Source data (verified 2026-11-18)

| | |
|---|---|
| Bucket | `s3://esa-worldcover-s2`, AWS region `eu-central-1`, anonymous read (`--no-sign-request`) |
| Imagery prefix | `rgbnir/2021/` (`rgbnir/2020/` also exists) |
| Files | 19,359 tiles of 1° × 1°, average 474 MB, 9.18 TB in total |
| Path pattern | `rgbnir/2021/N25/ESA_WorldCover_10m_2021_v200_N25E055_S2RGBNIR.tif`, named after the tile's south-west corner (`N25E055` covers 25–26°N, 55–56°E) |
| HTTPS form | `https://esa-worldcover-s2.s3.eu-central-1.amazonaws.com/rgbnir/2021/N25/…tif` (supports range requests, so GDAL can read it in place with `/vsicurl/`) |
| Format | Cloud-Optimized GeoTIFF, 12000 × 12000 pixels, EPSG:4326, 0.0000833° pixel |
| Bands | 1 = B04 red, 2 = B03 green, 3 = B02 blue, 4 = B08 near-infrared; UInt16; scale 0.0001 (reflectance = value / 10000); NoData 0 |
| Overviews | 6000, 3000, 1500, 750 pixels (each a factor of 2) |
| Compression | DEFLATE, predictor 2, 1024 × 1024 blocks |
| Tile index | `https://esa-worldcover.s3.eu-central-1.amazonaws.com/esa_worldcover_grid_composites.fgb` |
| Licence | CC BY 4.0 |
| Attribution (must be shown on the map) | `ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium` |
| Preview | https://viewer.esa-worldcover.org/worldcover/ |

## Output contract (what Horus expects)

Deliver files, nothing else; Horus integration happens on the other machine.

| Item | Requirement |
|---|---|
| Files | `horus-imagery-global.mbtiles` (the global base), and one `horus-imagery-<region>.mbtiles` per region, for example `horus-imagery-hormuz.mbtiles` |
| Tile format | Raster MBTiles, **JPEG** (quality about 85) or **WebP**; 256 × 256 tiles; standard XYZ in Web Mercator (EPSG:3857), as GDAL's MBTiles driver writes |
| Zooms | global: 0 to 9 or 10; regions: 0 to 14 (lower zooms are included so each file stands alone) |
| Colour | 8-bit RGB from bands 1-2-3; one stretch shared by every file, so the global and regional layers match where they meet |
| Metadata | MBTiles `metadata` table: `name`, `format` (`jpg` or `webp`), `minzoom`, `maxzoom`, `bounds`, and `attribution` set to the attribution string above |
| Checks | A `SHA256SUMS` file covering every delivered file; a `MANIFEST.md` listing each file's bounds, zooms, size and the source tiles used |
| Size target | Global base a few GB; each region (about 4° × 4°) roughly 1–3 GB; total under about 25 GB |

## Machine setup (Windows)

Use Docker Desktop with the official GDAL image, so no GDAL install is needed
on Windows itself. Run commands from a WSL2 shell (Ubuntu) if possible, since
the scripts are bash.

- Docker Desktop (WSL2 backend), image `ghcr.io/osgeo/gdal:ubuntu-full-3.9.3`.
  Use `ubuntu-full`, which includes the MBTiles and WebP drivers;
  `ubuntu-small` may not.
- AWS CLI v2 (only for listing and copying; no credentials needed).
- Free disk: about 50 GB working space per region during conversion, plus the
  outputs. Put the working directory on the WSL2 filesystem
  (`~/horus-imagery`), not `/mnt/c`, because file I/O across the boundary is
  slow.
- A clone of the Horus repo; scripts go in `imagery/scripts/`.

## Work items

### A. Set-up and spike

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| A1 | Install Docker Desktop (WSL2), AWS CLI; pull the GDAL image; `gdalinfo /vsicurl/<one tile URL>` works inside the container | Output matches the source table above | 1 | Todo |
| A2 | Spike one 1° tile end to end: read bands 1–3, scale to 8-bit, reproject to EPSG:3857, write a z0–14 MBTiles (`gdal_translate -of MBTiles` then `gdaladdo`), open it in QGIS or a MapLibre test page | One tile viewable at zoom 14 | 2 | Todo |
| A3 | Colour tuning on three contrasting tiles (desert, vegetation, coast or city): choose one stretch (for example reflectance 0–0.3 mapped to 0–255 with gamma about 1.2–1.4); record the final values in this file | Natural-looking and consistent across all three | 3 | Todo |

### B. Regions of interest (z0–14)

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| B1 | Region list agreed (bounding boxes in degrees). Proposed starters: Strait of Hormuz and Gulf, Taiwan Strait, Black Sea (Bosporus to Crimea), English Channel, a US port complex. **Waiting on the owner.** | List written here | – | Blocked |
| B2 | `scripts/region.sh <name> <west> <south> <east> <north>`: works out which 1° tiles it needs, downloads them (`aws s3 cp --no-sign-request`), builds a VRT, applies the A3 stretch, writes `horus-imagery-<name>.mbtiles` to z14 with overviews and metadata | One region file produced by a single command | 3 | Todo |
| B3 | Run B2 for every region; spot-check each at z8, z12 and z14 | All region files pass the checks | 4 | Todo |

### C. Global base (z0–9 or 10)

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| C1 | `scripts/global.sh`: build the global layer **from the files' built-in overviews read in place** (`/vsicurl/`, `OVERVIEW_LEVEL`), so the 9 TB is never downloaded. A VRT over all 19,359 tiles at the 750- or 1500-pixel overview, then the A3 stretch, reproject and MBTiles. Oceans have no tiles: leave them transparent (WebP) or set them to one flat colour (JPEG) | Global file produced | 4 | Todo |
| C2 | Decide z9 or z10 from C1's size and time (z10 is about 150 m per pixel, z9 about 300 m) | Recorded here | 0.5 | Todo |
| C3 | Check the seams where the global layer meets each region (same stretch, so colours match at the boundary) | No visible colour jump | 1 | Todo |

### D. Delivery

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| D1 | `SHA256SUMS` and `MANIFEST.md` as in the output contract | Both written | 0.5 | Todo |
| D2 | Hand-off: copy the files to where the Horus tile server can read them (decided with the owner; for now, upload into `horus/services/tileserver/` in the Workbench project, or object storage), and send the manifest | Files at the destination, checksums verified there | 1 | Todo |
| D3 | Commit the scripts (`imagery/scripts/`) and the final stretch values to the repo; never commit the imagery itself (`.gitignore` already covers `*.mbtiles`) | Scripts in git | 0.5 | Todo |

## Not in this package (done on the Horus side)

Tracked in [BURNDOWN.md](../BURNDOWN.md), section 8:
- adding the MBTiles to the tile server's `config.json`
- the UI imagery layer (satellite button back in PIPELINE mode), attribution
  on the map, and a setting to point at a customer's own imagery server

## Notes and pitfalls

- Read only bands 1, 2 and 3 (`-b 1 -b 2 -b 3`); band 4 is near-infrared.
- Apply the scale yourself: GDAL reads the raw integers. Reflectance is
  value / 10000, and NoData is 0. Keep 0 as transparent or masked, so ocean
  and no-data edges don't turn black.
- Reproject with a smooth resampler (`-r bilinear` or `cubic`) for imagery.
  Use `average` for overviews (`gdaladdo -r average`).
- MBTiles written by GDAL use EPSG:3857 automatically; don't pre-warp to
  another projection.
- The files are a yearly median, so moving objects (ships, vehicles) are
  averaged out and clouds are absent. That's expected.
- Sentinel-2 has little coverage poleward of about 84°N and 56°S; expect gaps
  there.
- Download from the AWS open-data bucket is free; be polite with parallelism
  (8–16 concurrent requests is plenty).
