#!/usr/bin/env bash
# A2 spike: one ESA WorldCover 1-degree tile -> z0-14 raster MBTiles (WebP).
#
# Usage: spike-tile.sh [TILE]     e.g. spike-tile.sh N25E055
# Run from WSL2. Work files go to $WORK (default ~/horus-imagery/spike).
#
# The colour stretch lives in stretch.py (A3) and is shared by every file.
set -euo pipefail

TILE="${1:-N25E055}"
WORK="${WORK:-$HOME/horus-imagery/spike}"
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
GDAL_IMAGE="ghcr.io/osgeo/gdal:ubuntu-full-3.9.3"
AWS_IMAGE="amazon/aws-cli"
BUCKET="s3://esa-worldcover-s2/rgbnir/2021"
QUALITY="${QUALITY:-85}"

ATTRIBUTION="ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium"

LAT_DIR="${TILE:0:3}"
SRC_NAME="ESA_WorldCover_10m_2021_v200_${TILE}_S2RGBNIR.tif"

mkdir -p "$WORK/src" "$WORK/out"

gdal() {
  docker run --rm -i -u "$(id -u):$(id -g)" -v "$WORK:/work" -w /work \
    -v "$SCRIPTS:/scripts:ro" \
    -e GDAL_CACHEMAX=2048 -e GDAL_NUM_THREADS=ALL_CPUS \
    "$GDAL_IMAGE" "$@"
}

# 1. Download the source tile (skip if already present).
if [[ ! -s "$WORK/src/$SRC_NAME" ]]; then
  echo "== download $SRC_NAME"
  docker run --rm -u "$(id -u):$(id -g)" -v "$WORK/src:/aws" "$AWS_IMAGE" \
    s3 cp --no-sign-request --region eu-central-1 \
    "$BUCKET/$LAT_DIR/$SRC_NAME" "/aws/$SRC_NAME"
fi

# 2. 8-bit RGBA VRT: bands 1-3 stretched, alpha from the NoData mask.
echo "== 8-bit VRT"
gdal python3 /scripts/stretch.py "/work/src/$SRC_NAME" "out/$TILE-8bit.vrt"

# 3. Reproject to Web Mercator and write z14 (the driver warps automatically).
#    UPPER: source is ~10.3 m in Mercator units at 25N, between z13 (19.1) and
#    z14 (9.55); LOWER would round down to z13. UPPER gives z14 below ~61N/S.
OUT="out/horus-imagery-spike-$TILE.mbtiles"
rm -f "$WORK/$OUT"
echo "== MBTiles z14"
time gdal gdal_translate -of MBTiles \
  -co TILE_FORMAT=WEBP -co QUALITY="$QUALITY" \
  -co ZOOM_LEVEL_STRATEGY=UPPER -co RESAMPLING=BILINEAR \
  -co NAME="horus-imagery-spike-$TILE" \
  "out/$TILE-8bit.vrt" "$OUT"

# 4. Lower zooms down to z0.
echo "== overviews"
time gdal gdaladdo -r average "$OUT" 2 4 8 16 32 64 128 256 512 1024 2048 4096 8192 16384

# 5. Attribution and a summary.
gdal python3 - "$OUT" "$ATTRIBUTION" <<'PY'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute("INSERT OR REPLACE INTO metadata(name, value) VALUES ('attribution', ?)", (sys.argv[2],))
db.commit()
for k, v in db.execute("SELECT name, value FROM metadata ORDER BY name"):
    print(f"  {k} = {v}")
for z, n in db.execute("SELECT zoom_level, COUNT(*) FROM tiles GROUP BY zoom_level ORDER BY zoom_level"):
    print(f"  z{z}: {n} tiles")
PY
ls -lh "$WORK/$OUT"
