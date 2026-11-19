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

### As set up on this workstation (A1, 2026-11-18)

- Docker Desktop 29.5.3 on WSL2; distro `Ubuntu-24.04`; 12 cores, 47 GB RAM.
- GDAL image `ghcr.io/osgeo/gdal:ubuntu-full-3.9.3` pulled; MBTiles (rw+),
  WEBP and JPEG drivers present. `gdalinfo /vsicurl/` on N25E055 matches the
  source table exactly (12000², EPSG:4326, 4 × UInt16, scale 0.0001, NoData 0,
  overviews 6000/3000/1500/750, COG, DEFLATE predictor 2).
- AWS CLI: run as the Docker image `amazon/aws-cli` (v2.41.0) rather than a
  local install, e.g.
  `docker run --rm amazon/aws-cli s3 ls --no-sign-request --region eu-central-1 s3://esa-worldcover-s2/rgbnir/2021/N25/`.
  (The Windows/WSL `aws` on PATH is a broken miniforge stub; ignore it.)
- Disk: about 500 GB usable. The WSL2 distro's virtual disk lives on `C:`
  (about 250 GB free); `E:` has about 500 GB free. Process regions one at a
  time and delete each region's downloaded source tiles once its MBTiles is
  written.

## Work items

### A. Set-up and spike

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| A1 | Install Docker Desktop (WSL2), AWS CLI; pull the GDAL image; `gdalinfo /vsicurl/<one tile URL>` works inside the container | Output matches the source table above | 1 | Done |
| A2 | Spike one 1° tile end to end: read bands 1–3, scale to 8-bit, reproject to EPSG:3857, write a z0–14 MBTiles (`gdal_translate -of MBTiles` then `gdaladdo`), open it in QGIS or a MapLibre test page | One tile viewable at zoom 14 | 2 | Done |
| A3 | Colour tuning on three contrasting tiles (desert, vegetation, coast or city): choose one stretch (for example reflectance 0–0.3 mapped to 0–255 with gamma about 1.2–1.4); record the final values in this file | Natural-looking and consistent across all three | 3 | Done |

#### A2 results (2026-11-18, tile N25E055, Dubai)

- Script: `imagery/scripts/spike-tile.sh [TILE]`; previews with
  `imagery/scripts/preview.sh`. The pipeline is: 8-bit RGBA VRT (bands 1–3
  stretched to 1–255 by `stretch.py`, see A3; alpha from the NoData mask), then
  `gdal_translate -of MBTiles` (WebP, quality 85, bilinear), then
  `gdaladdo -r average`. Download 13 s; MBTiles 12 s; overviews 4 s.
- **Use `ZOOM_LEVEL_STRATEGY=UPPER`.** In Mercator units the source pixel is
  about 10.3 m at 25°N, which falls between z13 (19.1 m) and z14 (9.55 m).
  `LOWER` gives z13. `UPPER` gives z14 at latitudes below about 61°.
- Size: 49 MB per 1° tile with WebP, so a 4° × 4° region is about 0.8 GB.
- z14 is checked visually (Palm Jumeirah fronds, DXB runways and taxiways, city
  blocks). tileserver-gl-light serves it as WebP, and the `attribution`
  appears in its TileJSON.
- Open sea is NoData in the source (only land and a stepped coastal strip are
  covered), and there are a few small NoData holes on land. Both come out
  transparent, which supports **WebP over JPEG**. The small holes are filled
  in B2 (`fill_holes.py`).
- **minzoom issue:** `gdaladdo` stops once the whole raster fits in one
  tile, so the 1° spike has z8–14 and a 4° region would stop at about z6.
  Resolved in B2: `finish_mbtiles.py` builds the remaining zooms down to z0.
- Highlights clip at the placeholder stretch (raw 3000): white roofs and sand
  read about 3900. A3 handles this.

#### A3 results: the Horus stretch (2026-11-18)

Final values, the same for every file and all three bands:

| Parameter | Value | Meaning |
|---|---|---|
| Black point | reflectance 0.010 (raw 100) | maps to output 1; removes residual haze |
| White point | reflectance 0.35 (raw 3500) | where the gamma part would reach 255 |
| Gamma | 1.4 | `out = x^(1/1.4)` after normalising black to white |
| Shoulder | above 80 % of output | exponential roll-off towards 255 instead of a hard clip |
| Output | 1–255; 0 reserved for NoData (alpha 0) | |

- The single source of truth is `imagery/scripts/stretch.py`. It writes the
  curve into the 8-bit RGBA VRT as a per-band `<LUT>`, within 1 DN of the
  exact curve. Alpha comes from the source NoData mask. The pipeline stays
  pure GDAL, with no Python pixel functions, so C1 can use it over
  `/vsicurl/`.
- Tested on N25E055 (Dubai: desert, city, bright coast), N24E121 (NE Taiwan:
  forest, Su'ao port) and N50E001 (Calais/Boulogne: farmland, port, Channel).
  Percentiles (reflectance × 10000, red band, median / p99): Dubai 2912 / 4163,
  Taiwan 301 / 1848, Calais 618 / 1649. The scenes differ about tenfold in
  brightness, which is why a plain 0–0.30 stretch fails (it blows out the
  desert) and a high gamma fails (it makes forest and farmland look hazy).
- Rejected: a saturation boost of 1.2–1.3 made fields slightly richer but
  pushed the desert orange, and it needs cross-band maths that a VRT LUT
  can't do.
- To compare stretches again: `imagery/scripts/stretch_lab.py`
  (`stats TILE...` and `sheet OUT.png TILE [W N E S]`). It renders candidate
  curves side by side, with NoData shown in magenta.

### B. Regions of interest (z0–14)

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| B1 | Region list agreed (bounding boxes in degrees). See the table below | List written here | – | Done |
| B2 | `scripts/region.sh <name> <west> <south> <east> <north>`: works out which 1° tiles it needs, downloads them (`aws s3 cp --no-sign-request`), builds a VRT, applies the A3 stretch, writes `horus-imagery-<name>.mbtiles` to z14 with overviews and metadata | One region file produced by a single command | 3 | Done |
| B3 | Run B2 for every region; spot-check each at z8, z12 and z14 | All region files pass the checks | 4 | Done |

Regions agreed 2026-11-18 (west, south, east, north, in degrees):

| Name | Box | Covers |
|---|---|---|
| `hormuz` | 52, 24, 58, 28 | Ruwais and Das Island, Abu Dhabi, Dubai, Sharjah, Musandam, the strait, Bandar Abbas |
| `taiwan-strait` | 118, 22, 122, 26 | Xiamen and the Fujian coast, western Taiwan, Penghu, Kinmen |
| `bosporus` | 28, 40, 30, 42 | Istanbul and the Bosporus |
| `crimea` | 32, 44, 37, 46 | Sevastopol, Crimea, the Kerch Strait |
| `channel` | -2, 49, 2, 52 | Dover/Calais, Portsmouth, Le Havre, Cherbourg |
| `hampton-roads` | -77.5, 36, -75.5, 38 | Norfolk Naval Station, Newport News shipyard, Langley, NAS Oceana, Yorktown, the Chesapeake Bay Bridge-Tunnel (chosen over `socal`, 2026-11-18) |

#### B2 results (2026-11-18)

Usage, from WSL2: `bash imagery/scripts/region.sh hormuz 52 24 58 28`.
Work files go to `~/horus-imagery/work/<name>/`, and the result goes to
`~/horus-imagery/out/horus-imagery-<name>.mbtiles` plus
`<name>.sources.txt`, which lists the source tiles used (for D1's
manifest). The steps:

1. List the 1° cells in the box and keep only those that exist in the bucket
   (cells that are entirely open sea have no file).
2. Download them with `aws s3 cp --recursive --include …` (about 10
   concurrent requests). Already-downloaded files are skipped, so a re-run
   resumes.
3. **Fill small NoData holes** with `fill_holes.py`, running `$JOBS` cells
   at a time (default 4). The 2021 composite has holes on land, about
   200–500 m across, mostly on bright new-build sand: Palm Jebel Ali,
   Atlantis, Jebel Ali port. The 2020 composite has the same holes (it fills
   3,463 of about 3.85 M NoData pixels), so it can't be used to fill them.
   Instead, a sieve on the valid mask finds enclosed NoData regions smaller
   than 2 km² (20,000 px), and GDAL `FillNodata` interpolates them. Open sea
   and the coastal NoData strip are much larger, so they stay transparent.
   The output is a 4-band file (R, G, B, alpha), about half the size of the
   source because it has no NIR band.
4. `gdalbuildvrt -te W S E N` mosaic, then `stretch.py --alpha-band 4`.
5. MBTiles z14 (WebP 85, `UPPER`), `gdaladdo -r average`, then
   `finish_mbtiles.py`. That step builds z0 up to gdaladdo's lowest level
   from 2 × 2 children (premultiplied alpha) and sets `name`, `description`,
   `minzoom` 0, `maxzoom` 14 and `attribution`.
6. Move the result to `out/` and delete the work directory (`KEEP_WORK=1`
   keeps it).

**Disk rule (owner's instruction):** only one region's files may exist at a
time. `region.sh` deletes every other region's work directory before it
starts and deletes its own when it finishes.

Test on a 2° × 2° box (54–56°E, 24–26°N, 4 cells): 236 s, 174 MB, z0–14.
Checked at z3, z5, z7, z12 and z14: no seam where the four cells meet at
Jebel Ali, the holes are filled, and the sea is transparent. Gotcha: GDAL
`FillNodata` writes scratch files with fixed names into the current
directory, so parallel containers sharing `/work` collide. `CPL_TMPDIR=/tmp`
fixes this.

#### B3 progress

Run all regions with `imagery/scripts/regions-all.sh [NAME...]`. It runs one
at a time, skips regions already in `out/`, and logs to
`~/horus-imagery/logs/`. Spot-check with
`imagery/scripts/spotcheck.sh NAME LON LAT TAG`; PNGs go to
`~/horus-imagery/checks/NAME/`.

| Region | Cells (land / box) | Download | Output | Build time | Spot-check |
|---|---|---|---|---|---|
| `hormuz` | 22 / 24 | 7.5 GB | 1.1 GB | about 20 min | Pass: z8 whole; z12 Bandar Abbas and Ruwais; z14 Khalifa Port. Hole fills are visible as soft smudges at Khalifa Port's terminal and breakwater; acceptable |
| `taiwan-strait` | 13 land cells filled | – | 594 MB | about 15 min | Pass: z8 whole; z12 Xiamen and Kinmen, Keelung; z14 Kaohsiung harbour. Known source limitation: the sea off Keelung (N25E121) has dark cloud-shadow blotches in the composite itself (only 91 px were filled there), not from the pipeline; land is unaffected |
| `bosporus` | – | – | 243 MB | about 6 min | Pass: z8 whole; z12 the full strait (both bridges, Golden Horn, Haydarpaşa) |
| `crimea` | – | – | 321 MB | about 10 min | Pass: z8 whole; z14 Sevastopol bays and naval quays; z12 Kerch Bridge. Source limitation: a rectangular NoData block and patchy water in the Kerch Strait south of the bridge |
| `channel` | – | – | 889 MB | about 16 min | Pass: z8 whole (London to the Isle of Wight, Cherbourg to Calais); z12 Dover and Folkestone; z14 Portsmouth naval base |
| `hampton-roads` | 6 / 6 | – | 301 MB | about 6 min | Pass: z8 whole (Chesapeake, Delmarva, Dismal Swamp); z14 Norfolk Naval Station (piers, Chambers Field); z12 Chesapeake Bay Bridge-Tunnel. Square NoData blocks over open bay water are in the source |

**B3 complete: 6 region files, 3.4 GB in total**, every one z0–14 with full
metadata. `~/horus-imagery/work/` is empty.

Bug found on the first Hormuz run and fixed: `docker run -i` inside a
`while read` loop swallowed the loop's input, so only the first 4 cells were
filled. Fill containers now get `</dev/null`, and the checks no longer run in
pipelines, so a failure stops the script.

### C. Global base (z0–9 or 10)

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| C1 | `scripts/global.sh`: build the global layer **from the files' built-in overviews read in place** (`/vsicurl/`, `OVERVIEW_LEVEL`), so the 9 TB is never downloaded. A VRT over all 19,359 tiles at the 750- or 1500-pixel overview, then the A3 stretch, reproject and MBTiles. Oceans have no tiles: leave them transparent (WebP) or set them to one flat colour (JPEG) | Global file produced | 4 | Done |
| C2 | Decide z9 or z10 from C1's size and time (z10 is about 150 m per pixel, z9 about 300 m) | Recorded here | 0.5 | Done: z10 |
| C3 | Check the seams where the global layer meets each region (same stretch, so colours match at the boundary) | No visible colour jump | 1 | Done |

#### C1 sample (2026-11-18)

`scripts/global.sh` (with the worker `scripts/global_cell.sh`). Each cell's
overview is read over `/vsis3/` and stretched straight to 8-bit RGBA. The
stretched cells are cached under `~/horus-imagery/global/L<level>/`, then
mosaicked and warped onto the exact z-max Web Mercator grid. Ocean is
transparent WebP. Test: `NAME=global-sample-l2 LEVEL=2 global.sh 50 20 60 30`.

- 96 cells were fetched in 58 s (16 at a time; about 0.6 s per cell overall).
  Each cached cell is about 3.4 MB. The whole build took 97 s, and z10 was
  30 MB.
- Over Dubai at z10, the result matched `horus-imagery-hormuz` in colour and
  was only slightly softer, so the shared stretch holds across the two
  products.
- Projected to all 19,359 cells, weighted by Mercator area:

  | Item | Estimate |
  |---|---|
  | Fetch time | about 3–4 h |
  | Cell cache on C: | about 66 GB |
  | z10 output | about 0.77 M tiles, up to about 21 GB |
  | z9 output | about 0.19 M tiles, up to about 5 GB |

  The sample is desert, so these sizes are upper bounds; ice and tundra
  compress better.

#### C1 results: the global base at z9 (2026-11-18)

`LEVEL=2 MAXZOOM=9 global.sh`, run over the whole world.

- **Fetch:** 19,359 cells in about 4 h (14,634 s).
  - 13 cells failed with transient `SSL_ERROR_SYSCALL`, including a burst of
    nine along S20 in Australia.
  - A re-run fetched only those 13, in 15 s.
  - The cache holds 75 GB at `~/horus-imagery/global/L2/`. Keep it until C2
    is decided, because z10 can be rebuilt from it without fetching again.
- **Build:** z9 took 78 min; the whole run, with overviews and low zooms,
  took 87 min.
- **Output:** `horus-imagery-global.mbtiles`, **3.1 GB, 86,508 tiles**.
  - z9 has 62,784 tiles; the projection's tile count was about 3× too high.
  - Bounds are the whole Mercator world. Metadata is complete.
- **Checks:** a z3 view of the whole world, plus z9 crops of the Alps and of
  western Norway (fjords, about 60°N), all look clean. Known source traits:
  - Coverage stops at 60°S, so there is no Antarctica.
  - Interior Greenland and the Alpine glaciers roll off to near-white.
  - Faint diagonal acquisition swaths show over the Amazon and Congo at
    low zoom.
  - Scattered few-pixel NoData specks remain, the same holes as in B2, which
    are not filled in the global layer.
- **Projected z10:** about 4× z9, so about 12 GB and about 5 h to build.
  With the regions, that is about 15.5 GB in total.

#### C2 decision: z10 (2026-11-19)

The delivered global base is built at z10, the top of the contract's range.
`LEVEL=2 MAXZOOM=10 global.sh` built it from the cache, with no re-fetch.

- **Build:** 3.2 h, of which 2.7 h was the z10 tiles.
- **Output:** `horus-imagery-global.mbtiles`, **12.46 GB, 326,192 tiles**
  (239,684 of them at z10). It replaces the z9 file.
- **Delivery total:** 16.05 GB with the six regions (decimal GB; see D1).
- **z11 was considered and rejected.** It would be about 50 GB. It would add
  little detail, because the 1500-px overview (about 74 m) is about z11's
  own resolution, and beyond about 55° latitude z11 would only enlarge
  pixels.

#### C3 results: seams (2026-11-19)

Each region was compared with the global layer at z10 over the region's own
box, on pixels valid in both:

| Region | Mean difference R/G/B (region − global) | Mean \|difference\| |
|---|---|---|
| hormuz | +0.1 / +0.2 / +0.1 | 5.5 |
| taiwan-strait | +0.3 / +0.2 / +0.3 | 8.2 |
| bosporus | +0.1 / +0.0 / +0.0 | 8.7 |
| crimea | +0.2 / +0.3 / +0.2 | 5.3 |
| channel | +0.0 / +0.0 / +0.0 | 6.6 |
| hampton-roads | +0.2 / +0.1 / +0.1 | 7.4 |

- **No colour shift.** The bias is at most 0.3 DN in every band and every
  region.
- **The absolute difference is fine texture.** The region file is averaged
  down from 10 m pixels, while the global layer uses ESA's overview.
- **No visible seam.** Composites of each region over the global layer show
  no step across the box edge: the Bosporus at 30°E, and Hormuz at 58°E over
  the Iranian desert.
- **Above z10** the client overzooms the global layer, so it looks softer
  beside the sharp region. That is expected, and it is not a colour seam.
- **The cell cache is still on C:** 75 GB at `~/horus-imagery/global/L2/`.
  It is only needed to rebuild the global layer. Delete it after delivery.

### D. Delivery

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| D1 | `SHA256SUMS` and `MANIFEST.md` as in the output contract | Both written | 0.5 | Done |
| D2 | Hand-off: copy the files to where the Horus tile server can read them | – | – | Moved: replaced by E1 (convert to PMTiles) and E2 (copy to object storage); never into the Workbench project |
| D3 | Commit the scripts (`imagery/scripts/`) and the final stretch values to the repo; never commit the imagery itself (`.gitignore` already covers `*.mbtiles`) | Scripts in git | 0.5 | Todo |

#### D1 results (2026-11-19)

`scripts/delivery.sh` writes the delivery set into `~/horus-imagery/out/`.
It runs `scripts/manifest.py` to write `MANIFEST.md`, then writes
`SHA256SUMS`.

- **`manifest.py`** reads each file's metadata, tile counts and
  `.sources.txt`, and runs SQLite `quick_check`. It fails if any of these is
  missing or bad.
- **`SHA256SUMS`** covers the 7 `.mbtiles`, their 7 `.sources.txt` and
  `MANIFEST.md`, in standard `sha256sum` format.

Results:

- **Delivery set:** 16 files, 16.05 GB (decimal).
- **Checks:** every file passed `quick_check` and has complete metadata, and
  `sha256sum -c` verifies.
- **If any file changes,** re-run `delivery.sh`.
- **The set to hand off is exactly the contents of `out/`.**

### E. Hand-off to Horus object storage

Decided 2026-11-19 (Horus burndown section 8): Horus serves imagery from the
environment's object storage as **PMTiles**, one file per tile set, read by
HTTP range requests. MBTiles is SQLite and needs a normal filesystem, so it
stays on this workstation. The files go from here straight to the bucket,
never through a browser upload or the Workbench project.

| ID | Item | Done when | Est | Status |
|---|---|---|---|---|
| E1 | Convert the 7 MBTiles to PMTiles and check them: `scripts/to_pmtiles.sh` | The script ends with "All 7 files converted and checked" | 1 | Todo |
| E2 | Copy the 7 PMTiles and their `SHA256SUMS` to the instance's bucket prefix and verify the checksums there | Checksums verified in the bucket | 1 | Blocked: waiting for the bucket path and how this workstation authenticates to it (Horus 8.1 and 8.9) |

#### E1: how to run it

From a WSL2 shell, in the `imagery` folder of the horus repo (pull first):

```bash
git pull
df -h ~                      # needs about 16 GB free (the PMTiles are about the size of the MBTiles)
scripts/to_pmtiles.sh
```

For each `~/horus-imagery/out/horus-imagery-*.mbtiles` it:

1. converts it with `pmtiles convert`, run from the Docker image
   `protomaps/go-pmtiles:v1.31.2`, so nothing is installed;
2. runs `pmtiles verify` on the result;
3. runs the Horus tile service's own checks on it
   (`services/tileserver/tilestore.py`: metadata present, tiles in the declared
   format, valid zooms and bounds), so a file that passes here will be served;
4. checks the PMTiles says what the MBTiles said: format, zooms, bounds,
   attribution.

Output goes to `~/horus-imagery/out/pmtiles/`: the 7 `.pmtiles` files and a
`SHA256SUMS` covering them. That folder is the hand-off set for E2. The global
file is the long one (12.5 GB; expect tens of minutes); a re-run skips files
already converted and checked.

**If a file fails, don't fix it by hand and don't upload it**: send the
output. One failure to know about: if the tile service's check says the
PMTiles header's maxzoom differs from its metadata, the map would stop at the
lower zoom. A long run of identical tiles (empty ocean, for example) can cause
this in the converter, and `pmtiles edit` can't fix it cleanly.

To check any single file the way the tile service will:
`python3 ../services/tileserver/tilestore.py FILE`.

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
