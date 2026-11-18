# Horus tile server

This is the self-hosted vector basemap for the Horus UI. It serves OpenMapTiles
vector tiles, a dark style, glyphs and sprites through
[tileserver-gl-light](https://github.com/maptiler/tileserver-gl). There is no
third-party map provider at runtime.

| | |
|---|---|
| Workbench Application script | `horus/services/tileserver/serve-tiles.py` (repo cloned at `/home/cdsw/horus`) |
| Runtime | Horus Node 22 (`horus-node-runtime`) |
| Env var | `TILESERVER_PUBLIC_URL=https://<subdomain>.<workbench-domain>/` (keep the trailing slash) |
| Basemap | `horus-basemap.mbtiles`: planet, zoom 0–7, OpenMapTiles 3.16, about 214 MB |

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
CDSW_APP_PORT=8090 python3 serve-tiles.py
# http://localhost:8090/ , http://localhost:8090/styles/dark/style.json
```
