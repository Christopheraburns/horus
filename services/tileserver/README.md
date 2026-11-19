# Horus tile service

The self-hosted map layers for the Horus UI: the OpenMapTiles vector basemap
with its dark style, glyphs and sprites, and the imagery tile sets, served by
[tileserver-gl-light](https://github.com/maptiler/tileserver-gl). There is no
third-party map provider at runtime.

| | |
|---|---|
| Workbench Application script | `horus/services/tileserver/serve-tiles.py` (repo cloned at `/home/cdsw/horus`) |
| Runtime | Horus Node 22 (`horus-node-runtime`) |
| Env var | `TILESERVER_PUBLIC_URL=https://<subdomain>.<workbench-domain>/` (keep the trailing slash) |
| Env var (optional) | `TILESET_DIR`: the folder holding the tile files; default this folder. Object storage comes with burndown 8.9 |
| Basemap | `horus-basemap.mbtiles`: planet, zoom 0–7, OpenMapTiles 3.16, about 214 MB |

## What happens on start

`serve-tiles.py` finds every `.pmtiles` and `.mbtiles` file in `TILESET_DIR`,
checks each one (`tilestore.py`: metadata present, tiles in the declared
format, valid zooms and bounds), and builds the tile-set registry from them and
`tilesets.toml` ([docs/TILESETS.md](../../docs/TILESETS.md)). A file that fails
a check, or has no table in `tilesets.toml`, is skipped with a `SKIP` line in
the log saying why; the rest are served. It then writes
`config.generated.json` (ignored by git) and runs tileserver-gl-light on an
internal port, behind a small front proxy (`front_proxy.py`) on the
Application's port, which also serves:

| Path | What |
|---|---|
| `/registry.json` | The registry the UI builds its layers from (no file paths or credential names) |
| `/data/<id>.json` | TileJSON for each tile set; tiles at `/data/<id>/{z}/{x}/{y}.<format>` |
| `/styles/dark/style.json` | The dark style, drawn from `horus-basemap` |

To add a tile file, put it in `TILESET_DIR`, add its table to `tilesets.toml`
and restart the Application (tileserver-gl-light doesn't reload its config).

## The basemap file

`horus-basemap.mbtiles` is too large for git and is ignored by `*.mbtiles`.
Upload it into this directory in the Workbench project, under **Files →
horus/services/tileserver/**, before starting the Application. The launcher stops
with a clear message if the file is missing.

## What's in git

The repo has `styles/dark/style.json`, `sprites/dark/*`, and only the six font
families the style uses (Metropolis Light, Light Italic, Medium Italic and
Regular; Noto Sans Regular and Italic). The launcher installs `tileserver-gl-light`
from `package-lock.json` on first start.

## Run locally

```bash
cd services/tileserver
ln -s ../../horus-basemap.mbtiles .     # or copy the file here
CDSW_APP_PORT=8090 python3 serve-tiles.py   # Python 3.11+ and Node 22
# http://localhost:8090/registry.json , http://localhost:8090/styles/dark/style.json
```

## Tests

- `python3 test_registry.py`: the registry rules on the delivered set.
- `test/run_e2e.sh`: the whole service in the `node:22` image, over stand-ins
  for the 7 imagery files (one as PMTiles), the real basemap and three bad
  files: registry, TileJSON and tiles through the front proxy, and the bad
  files skipped with their reasons. Needs Docker and `uv`.
