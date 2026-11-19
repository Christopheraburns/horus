#!/bin/bash
# End-to-end test of the tile service (burndown 8.3): serve-tiles.py in the node:22
# image over a tile store of stand-in files (make_fixtures.py) plus the real basemap.
#   services/tileserver/test/run_e2e.sh
# Needs Docker, uv, and services/tileserver/horus-basemap.mbtiles.
set -euo pipefail
cd "$(dirname "$0")"
uv run -q --no-project --with pillow --with pmtiles python make_fixtures.py out/store
ln -f ../horus-basemap.mbtiles out/store/horus-basemap.mbtiles     # hard link: no copy
name=horus-tiles-e2e
docker rm -f $name >/dev/null 2>&1 || true
docker run -d --name $name -p 18491:8090 \
  -v "$PWD/..:/app" -v /app/node_modules -v "$PWD/out/store:/store:ro" \
  -e CDSW_APP_PORT=8090 -e TILESERVER_BIND=0.0.0.0 -e TILESET_DIR=/store \
  -e TILESERVER_PUBLIC_URL=http://localhost:18491/ \
  -w /app node:22 python3 serve-tiles.py >/dev/null
trap 'docker logs $name > out/e2e.log 2>&1; docker rm -f $name >/dev/null' EXIT
for i in $(seq 1 120); do
  docker logs $name 2>&1 | grep -q "Startup complete" && break
  docker ps -q --filter name=$name | grep -q . || { docker logs $name 2>&1 | tail -20; exit 1; }
  sleep 2
done
docker logs $name > out/e2e.log 2>&1
python3 check_e2e.py out/e2e.log
