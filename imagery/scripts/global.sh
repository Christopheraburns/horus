#!/usr/bin/env bash
# C1: build the global base layer from the source files' built-in overviews,
# read in place over /vsis3/ -- the 9 TB of full-resolution data is never
# downloaded.
#
# Usage: global.sh [WEST SOUTH EAST NORTH]     (default: the whole world)
#   A box builds a sample: e.g. NAME=global-sample global.sh 50 20 60 30
#
# Env:
#   LEVEL=2     source overview: 2 = 1500 px per 1-degree cell (~74 m),
#               3 = 750 px (~148 m)
#   MAXZOOM=10  top zoom of the output (z10 ~153 m/px, z9 ~306 m/px)
#   NAME=global output is out/horus-imagery-NAME.mbtiles
#   JOBS=16     cells fetched at once
#
# Layout under $HORUS_IMAGERY (default ~/horus-imagery):
#   global/files.txt     listing of the whole source bucket (made once)
#   global/L<LEVEL>/     cached 8-bit RGBA cells, stretched (kept between runs)
#   global/build-NAME/   VRTs and the MBTiles being built (removed at the end)
set -euo pipefail

W="${1:--180}"; S="${2:--90}"; E="${3:-180}"; N="${4:-90}"
LEVEL="${LEVEL:-2}"; MAXZOOM="${MAXZOOM:-10}"; NAME="${NAME:-global}"
JOBS="${JOBS:-16}"; QUALITY="${QUALITY:-85}"
[[ "$NAME" =~ ^[a-z0-9-]+$ ]] || { echo "NAME must be lower-case letters, digits, '-'"; exit 2; }

ROOT="${HORUS_IMAGERY:-$HOME/horus-imagery}"
G="$ROOT/global"
CACHE="$G/L$LEVEL"
BUILD="$G/build-$NAME"
OUTDIR="$ROOT/out"
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
GDAL_IMAGE="ghcr.io/osgeo/gdal:ubuntu-full-3.9.3"
AWS_IMAGE="amazon/aws-cli"
OUTNAME="horus-imagery-$NAME"
mkdir -p "$CACHE" "$BUILD" "$OUTDIR"

gdal() {
  docker run --rm -i -u "$(id -u):$(id -g)" \
    -v "$BUILD:/build" -v "$CACHE:/cache" -v "$G:/g:ro" -v "$OUTDIR:/out" \
    -v "$SCRIPTS:/scripts:ro" -w /build \
    -e GDAL_CACHEMAX=4096 -e GDAL_NUM_THREADS=ALL_CPUS -e CPL_TMPDIR=/tmp \
    -e AWS_NO_SIGN_REQUEST=YES -e AWS_REGION=eu-central-1 \
    -e GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR \
    -e CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif \
    -e GDAL_HTTP_MULTIRANGE=YES -e GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES \
    -e GDAL_HTTP_MAX_RETRY=6 -e GDAL_HTTP_RETRY_DELAY=3 \
    "$GDAL_IMAGE" "$@"
}

START=$(date +%s)
echo "== global $NAME: box W=$W S=$S E=$E N=$N, LEVEL=$LEVEL, MAXZOOM=$MAXZOOM"

# --- 1. the bucket listing (once) ------------------------------------------
if [[ ! -s "$G/files.txt" ]]; then
  echo "== listing the source bucket"
  docker run --rm "$AWS_IMAGE" s3 ls --recursive --no-sign-request \
    --region eu-central-1 s3://esa-worldcover-s2/rgbnir/2021/ </dev/null \
    | awk '$4 ~ /\.tif$/ {print $3, $4}' > "$G/files.txt.part"
  mv -f "$G/files.txt.part" "$G/files.txt"
fi
echo "   $(wc -l < "$G/files.txt") source cells in the bucket"

# --- 2. the cells that overlap the box -------------------------------------
gdal python3 - "$W" "$S" "$E" "$N" < /dev/null > "$BUILD/keys.txt" <<'PY'
import re, sys
w, s, e, n = map(float, sys.argv[1:])
for line in open("/g/files.txt"):
    key = line.split()[1]
    m = re.search(r"_([NS])(\d\d)([EW])(\d\d\d)_", key)
    lat = int(m[2]) * (1 if m[1] == "N" else -1)
    lon = int(m[4]) * (1 if m[3] == "E" else -1)
    if lon < e and lon + 1 > w and lat < n and lat + 1 > s:
        print(key)
PY
echo "   $(wc -l < "$BUILD/keys.txt") cells overlap the box"

# --- 3. fetch + stretch each cell's overview (cached) -----------------------
: > "$BUILD/todo.txt"
while read -r key; do
  [[ -s "$CACHE/$(basename "$key")" ]] || echo "$key" >> "$BUILD/todo.txt"
done < "$BUILD/keys.txt"
TODO=$(wc -l < "$BUILD/todo.txt")
echo "== fetch $TODO cells ($JOBS at a time)"
if [[ "$TODO" -gt 0 ]]; then
  t0=$(date +%s)
  # A cell that fails is reported and left out of the cache; re-run to retry.
  gdal bash -c "xargs -a /build/todo.txt -P $JOBS -I{} \
      sh -c 'bash /scripts/global_cell.sh $LEVEL {} /cache || echo FAILED {}'" \
    < /dev/null | tee -a "$BUILD/fetch.log"
  echo "   fetched in $(( $(date +%s) - t0 )) s"
fi
missing=0
while read -r key; do
  [[ -s "$CACHE/$(basename "$key")" ]] || { echo "   missing: $key"; missing=$((missing + 1)); }
done < "$BUILD/keys.txt"
[[ "$missing" -eq 0 ]] || { echo "$missing cells missing; re-run to retry"; exit 1; }
echo "   cache: $(du -sh "$CACHE" | cut -f1) for $(ls "$CACHE" | grep -c '\.tif$') cells"

# --- 4. mosaic, then warp to the z$MAXZOOM Web Mercator grid ---------------
echo "== VRTs"
sed 's|.*/|/cache/|' "$BUILD/keys.txt" > "$BUILD/srclist.txt"
gdal gdalbuildvrt -q -input_file_list /build/srclist.txt /build/mosaic.vrt < /dev/null
# Snap the box outward to whole z$MAXZOOM tiles; clamp to the Mercator limit.
read -r RES XMIN YMIN XMAX YMAX < <(gdal python3 - "$W" "$S" "$E" "$N" "$MAXZOOM" < /dev/null <<'PY'
import math, sys
w, s, e, n = map(float, sys.argv[1:5]); z = int(sys.argv[5])
R = 6378137.0; HALF = math.pi * R
res = 2 * HALF / (256 * 2 ** z); tile = 256 * res
lim = 85.0511287798
s, n = max(s, -lim), min(n, lim)
x = lambda lon: math.radians(lon) * R
y = lambda lat: R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
snap_lo = lambda v: -HALF + math.floor((v + HALF) / tile + 1e-9) * tile
snap_hi = lambda v: -HALF + math.ceil((v + HALF) / tile - 1e-9) * tile
print(repr(res), snap_lo(x(w)), snap_lo(y(s)), snap_hi(x(e)), snap_hi(y(n)))
PY
)
# Averaging when the source is finer than the output, else bilinear.
RS=bilinear; [[ "$LEVEL" -le 2 && "$MAXZOOM" -le 10 ]] && RS=average
gdal gdalwarp -q -of VRT -overwrite -t_srs EPSG:3857 -r "$RS" \
  -tr "$RES" "$RES" -te "$XMIN" "$YMIN" "$XMAX" "$YMAX" \
  -srcalpha -dstalpha -wo NUM_THREADS=ALL_CPUS \
  /build/mosaic.vrt /build/merc.vrt < /dev/null

# --- 5. MBTiles at z$MAXZOOM, overviews, low zooms, metadata ---------------
echo "== MBTiles z$MAXZOOM"
rm -f "$BUILD/$OUTNAME.mbtiles"
t0=$(date +%s)
gdal gdal_translate -q -of MBTiles \
  -co TILE_FORMAT=WEBP -co QUALITY="$QUALITY" -co NAME="$OUTNAME" \
  /build/merc.vrt "/build/$OUTNAME.mbtiles" < /dev/null
echo "   z$MAXZOOM in $(( $(date +%s) - t0 )) s"
echo "== overviews"
levels=(); f=2
for ((i = 0; i < MAXZOOM; i++)); do levels+=("$f"); f=$((f * 2)); done
gdal gdaladdo -q -r average "/build/$OUTNAME.mbtiles" "${levels[@]}" < /dev/null
echo "== low zooms and metadata"
gdal python3 /scripts/finish_mbtiles.py "/build/$OUTNAME.mbtiles" "$OUTNAME" \
  --quality "$QUALITY" < /dev/null

# --- 6. deliver, record sources, clean up -----------------------------------
mv -f "$BUILD/$OUTNAME.mbtiles" "$OUTDIR/$OUTNAME.mbtiles"
{
  echo "# $OUTNAME  box W=$W S=$S E=$E N=$N  overview level $LEVEL  built $(date -u +%Y-%m-%dT%H:%MZ)"
  sed 's|^|s3://esa-worldcover-s2/|' "$BUILD/keys.txt"
} > "$OUTDIR/$OUTNAME.sources.txt"
ls -lh "$OUTDIR/$OUTNAME.mbtiles"
[[ "${KEEP_WORK:-0}" == 1 ]] || rm -rf "$BUILD"
echo "== done in $(( $(date +%s) - START )) s"
