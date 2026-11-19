#!/usr/bin/env bash
# C1 worker, run inside the GDAL container by global.sh (one call per cell).
#
# Usage: global_cell.sh LEVEL KEY OUTDIR
#   LEVEL   overview index in the source COG (2 = 1500 px per cell, 3 = 750 px)
#   KEY     object key under s3://esa-worldcover-s2/, e.g.
#           rgbnir/2021/N25/ESA_WorldCover_10m_2021_v200_N25E055_S2RGBNIR.tif
#   OUTDIR  where the 8-bit RGBA cell goes (same basename as the source)
#
# Reads only that overview over /vsis3/ (no full download), applies the A3
# stretch (stretch.py) and writes a small 8-bit RGBA GeoTIFF. Prints one line:
#   NAME SECONDS BYTES
set -euo pipefail
L="$1"; KEY="$2"; OUT="$3"
NAME="$(basename "$KEY")"
[[ -s "$OUT/$NAME" ]] && exit 0
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
t0=$(date +%s.%N)
gdal_translate -q -oo OVERVIEW_LEVEL="$L" -b 1 -b 2 -b 3 \
  "/vsis3/esa-worldcover-s2/$KEY" "$T/raw.tif"
python3 /scripts/stretch.py "$T/raw.tif" "$T/rgba.vrt"
gdal_translate -q "$T/rgba.vrt" "$OUT/$NAME.part.tif" \
  -co TILED=YES -co COMPRESS="${CELL_COMPRESS:-ZSTD}" -co PREDICTOR=2
mv -f "$OUT/$NAME.part.tif" "$OUT/$NAME"
t1=$(date +%s.%N)
awk -v n="$NAME" -v a="$t0" -v b="$t1" -v s="$(stat -c %s "$OUT/$NAME")" 'BEGIN{printf "%s %.1f %s\n", n, b-a, s}'
