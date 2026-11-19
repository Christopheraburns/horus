# Tile-set registry

The registry is one list of every source of map layers Horus can show: tile
files it serves itself, and tile servers it doesn't host (a customer's
GeoServer, ArcGIS Enterprise or national imagery service). The tile server
builds it on start; the UI builds its map layers from it (burndown section 8).

It is built from two inputs:

1. **The tile files in the tile store**: PMTiles in the instance's object
   storage prefix (MBTiles in a local folder during development). Each file
   describes itself: name, format, zoom range, bounds and attribution.
2. **`services/tileserver/tilesets.toml`**, edited by hand: what a file's
   metadata can't say (licence, security marking, capture date, title,
   stacking) and the tile servers Horus doesn't host.

A tile file appears only if `tilesets.toml` has a table for it: Horus never
shows imagery whose marking and licence nobody has stated. An entry that fails
validation is left out with a log line naming the reason; it never stops the
tile server.

The rules are implemented, and tested, in `services/tileserver/registry.py`
(`test_registry.py` runs the delivered set through them).

## tilesets.toml

```toml
[defaults.imagery]                 # shared settings; a table picks them with defaults = "imagery"
role = "imagery"
licence = { id = "CC-BY-4.0", url = "https://creativecommons.org/licenses/by/4.0/" }
captured = "2021-01-01/2021-12-31"
marking = { classification = "UNCLASSIFIED" }

[tileset.horus-imagery-hormuz]     # a tile file: the id is the file name without .pmtiles/.mbtiles
defaults = "imagery"
title = "Strait of Hormuz imagery (ESA WorldCover 2021)"

[url.customer-ortho-2026]          # a tile server Horus doesn't host
role = "imagery"
scheme = "xyz"
template = "https://geoserver.example.mil/.../{z}/{x}/{y}.png"
format = "png"
bounds = [-76.4, 36.8, -76.2, 37.0]
minzoom = 10
maxzoom = 19
attribution = "Example Imagery Agency"
licence = { id = "proprietary", url = "https://example.mil/terms" }
captured = "2026-03-14"
marking = { classification = "UNCLASSIFIED", releasability = "FVEY" }
credentials = "CUSTOMER_ORTHO_BASIC_AUTH"
```

A table's own keys override its defaults, and both override the file's
metadata.

## Fields

| Field | Required | From | Meaning |
|---|---|---|---|
| `id` | yes | file name, or the table name for `[url]` | Lower case letters, digits, `.`, `_`, `-`; at most 64. Unique |
| `kind` | yes | | `file` (served by Horus) or `url` (another server) |
| `role` | yes | toml | `basemap`, `imagery` or `overlay` |
| `title` | | toml, else metadata `name`, else the id | Shown in the layer list |
| `format` | yes | metadata, or toml | `webp`, `jpg`, `png` (raster) or `pbf` (vector). Imagery must be raster |
| `attribution` | yes | metadata, or toml | Shown on the map whenever the layer is (8.5); licences require it |
| `licence.id`, `licence.url` | id yes | toml | SPDX-style id (`CC-BY-4.0`, `ODbL-1.0`, `proprietary`) and the terms |
| `marking.classification`, `marking.releasability` | classification yes | toml | Section 13 markings; the tile service enforces them per tile set (8.9) |
| `captured` | warned if missing on imagery | toml | `YYYY-MM-DD` or `YYYY-MM-DD/YYYY-MM-DD`; Time Travel picks the imagery nearest the replay time (8.8) |
| `bounds` | yes | metadata, or toml | `[west, south, east, north]` in degrees; the UI never requests tiles outside |
| `minzoom`, `maxzoom` | yes | metadata, or toml | 0 to 24 |
| `order` | | toml, else role and detail | Stacking, higher on top. Default: basemap 0, imagery 100, overlay 200, plus `maxzoom`, so a z14 region draws over the z10 world |
| `scheme`, `template` | `[url]` only | toml | `xyz` or `tms` with `{z}`, `{x}`, `{y}`; `wmts` with `{TileMatrix}`, `{TileRow}`, `{TileCol}` |
| `credentials` | | toml | The name of an environment variable on the tile service holding the server's credentials. Such servers are reached through the tile service, so the browser never sees them (8.6) |

## The registry document

The tile server keeps the full registry, including file paths and credential
names. The browser gets the public view: the same entries without `source`.

```json
{
  "version": 1,
  "generated": "2026-11-19T00:00:00Z",
  "tilesets": [
    {
      "id": "horus-imagery-hormuz", "kind": "file", "role": "imagery",
      "title": "Strait of Hormuz imagery (ESA WorldCover 2021)",
      "format": "webp", "type": "raster",
      "attribution": "ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium",
      "licence": {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
      "marking": {"classification": "UNCLASSIFIED", "releasability": null},
      "captured": {"start": "2021-01-01", "end": "2021-12-31"},
      "bounds": [52.0, 24.0, 58.0, 28.0], "minzoom": 0, "maxzoom": 14, "order": 114
    }
  ]
}
```

## The delivered set

Seven ESA WorldCover 2021 imagery files (WebP, 16.05 GB with checksums, from
`imagery/`) and the OpenMapTiles vector basemap, as the registry lists them,
bottom to top:

| id | role | zooms | bounds (W, S, E, N) | order |
|---|---|---|---|---|
| `horus-basemap` | basemap (vector) | 0–7 | world | 7 |
| `horus-imagery-global` | imagery | 0–10 | world (to ±85.05°) | 110 |
| `horus-imagery-bosporus` | imagery | 0–14 | 28, 40, 30, 42 | 114 |
| `horus-imagery-channel` | imagery | 0–14 | −2, 49, 2, 52 | 114 |
| `horus-imagery-crimea` | imagery | 0–14 | 32, 44, 37, 46 | 114 |
| `horus-imagery-hampton-roads` | imagery | 0–14 | −77.5, 36, −75.5, 38 | 114 |
| `horus-imagery-hormuz` | imagery | 0–14 | 52, 24, 58, 28 | 114 |
| `horus-imagery-taiwan-strait` | imagery | 0–14 | 118, 22, 122, 26 | 114 |

All seven imagery files share one licence (CC BY 4.0), attribution, capture
period (2021, annual composite) and marking (UNCLASSIFIED), set once in
`[defaults.imagery]`. The regions don't overlap each other, so equal orders are
fine; a region always draws above the global layer. Bounds and zooms here come
from the build scripts; the registry reads the real values from each file.

## Adding imagery

1. Put the tile file in the tile store (8.1: copy to the bucket prefix from the
   machine that has it, never through the browser; 8.7 converts a GeoTIFF).
2. Add its `[tileset.<id>]` table to `tilesets.toml` with at least `role`,
   `licence`, `marking` and, for imagery, `captured`.
3. Restart the tile server (tileserver-gl-light doesn't reload its config).
   Its log lists every tile set it serves and every one it skipped, with why.
