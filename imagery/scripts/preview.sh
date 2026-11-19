#!/usr/bin/env bash
# Render PNG previews from an MBTiles file at a given zoom.
#
# Usage: preview.sh FILE.mbtiles OUT.png ZOOM [WEST NORTH EAST SOUTH]
#   Without a bounding box, renders the whole file at that zoom.
#   FILE and OUT are paths relative to the current directory.
set -euo pipefail
IN="$1"; OUT="$2"; Z="$3"; shift 3
WIN=()
if [[ $# -eq 4 ]]; then WIN=(-projwin_srs EPSG:4326 -projwin "$@"); fi
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/work" -w /work -e GDAL_PAM_ENABLED=NO \
  ghcr.io/osgeo/gdal:ubuntu-full-3.9.3 \
  gdal_translate -q -oo ZOOM_LEVEL="$Z" "${WIN[@]}" -of PNG "$IN" "$OUT"
