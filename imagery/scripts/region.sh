#!/usr/bin/env bash
# B2: build one region of interest as a standalone z0-14 raster MBTiles.
#
# Usage: region.sh NAME WEST SOUTH EAST NORTH      (degrees; may be fractional)
#   e.g. region.sh hormuz 52 24 58 28
#
# Run from WSL2. Layout under $HORUS_IMAGERY (default ~/horus-imagery):
#   work/NAME/   source tiles and VRTs for the region being built (temporary)
#   out/         finished horus-imagery-NAME.mbtiles and NAME.sources.txt
#
# Disk rule: only one region's work files exist at a time. Starting a region
# deletes every other region's work directory; a finished region deletes its
# own (set KEEP_WORK=1 to keep it). Re-running the same region reuses its
# downloads.
set -euo pipefail

if [[ $# -ne 5 ]]; then sed -n '2,15p' "$0"; exit 2; fi
NAME="$1"; W="$2"; S="$3"; E="$4"; N="$5"
[[ "$NAME" =~ ^[a-z0-9-]+$ ]] || { echo "NAME must be lower-case letters, digits, '-'"; exit 2; }

ROOT="${HORUS_IMAGERY:-$HOME/horus-imagery}"
WORK="$ROOT/work/$NAME"
OUTDIR="$ROOT/out"
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
GDAL_IMAGE="ghcr.io/osgeo/gdal:ubuntu-full-3.9.3"
AWS_IMAGE="amazon/aws-cli"
BUCKET="s3://esa-worldcover-s2/rgbnir/2021"
QUALITY="${QUALITY:-85}"
OUTNAME="horus-imagery-$NAME"

# --- disk rule: clear other regions' work files first ----------------------
mkdir -p "$ROOT/work"
for d in "$ROOT"/work/*/; do
  [[ -d "$d" && "${d%/}" != "$WORK" ]] || continue
  echo "== removing previous region work dir $d ($(du -sh "$d" | cut -f1))"
  rm -rf "$d"
done
mkdir -p "$WORK/src" "$OUTDIR"

gdal() {
  docker run --rm -i -u "$(id -u):$(id -g)" \
    -v "$WORK:/work" -v "$OUTDIR:/out" -v "$SCRIPTS:/scripts:ro" -w /work \
    -e GDAL_CACHEMAX=4096 -e GDAL_NUM_THREADS=ALL_CPUS \
    -e CPL_TMPDIR=/tmp \
    "$GDAL_IMAGE" "$@"
}
aws_s3() {
  docker run --rm -u "$(id -u):$(id -g)" -v "$WORK/src:/aws" "$AWS_IMAGE" \
    s3 "$@" --no-sign-request --region eu-central-1
}

START=$(date +%s)
echo "== region $NAME: W=$W S=$S E=$E N=$N"

# --- 1. which 1-degree cells, and which of them exist ----------------------
# Cells are named after their south-west corner: N25E055, S01W077, ...
gdal python3 - "$W" "$S" "$E" "$N" > "$WORK/cells.txt" <<'PY'
import math, sys
w, s, e, n = map(float, sys.argv[1:])
assert w < e and s < n, "need WEST < EAST and SOUTH < NORTH"
for lat in range(math.floor(s), math.ceil(n)):
    for lon in range(math.floor(w), math.ceil(e)):
        la = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
        lo = f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
        print(la, f"ESA_WorldCover_10m_2021_v200_{la}{lo}_S2RGBNIR.tif")
PY
echo "   $(wc -l < "$WORK/cells.txt") cells in the box"

: > "$WORK/needed.txt"
for latdir in $(cut -d' ' -f1 "$WORK/cells.txt" | sort -u); do
  # A latitude with no land at all has no prefix; ls then fails, which is fine.
  { aws_s3 ls "$BUCKET/$latdir/" || true; } | awk '{print $4}' > "$WORK/ls-$latdir.txt"
  grep "^$latdir " "$WORK/cells.txt" | cut -d' ' -f2 | while read -r f; do
    if grep -qxF "$f" "$WORK/ls-$latdir.txt"; then echo "$latdir $f" >> "$WORK/needed.txt"; fi
  done
done
NEEDED=$(wc -l < "$WORK/needed.txt")
echo "   $NEEDED cells have data (the rest are open sea)"
[[ "$NEEDED" -gt 0 ]] || { echo "nothing to do"; exit 1; }

# --- 2. download (aws runs ~10 concurrent requests per call) ---------------
for latdir in $(cut -d' ' -f1 "$WORK/needed.txt" | sort -u); do
  args=()
  while read -r f; do
    [[ -s "$WORK/src/$f" ]] || args+=(--include "$f")
  done < <(grep "^$latdir " "$WORK/needed.txt" | cut -d' ' -f2)
  [[ ${#args[@]} -gt 0 ]] || continue
  echo "== download $latdir: $(( ${#args[@]} / 2 )) files"
  aws_s3 cp "$BUCKET/$latdir/" /aws/ --recursive --exclude '*' "${args[@]}" --only-show-errors
done
mapfile -t FILES < <(cut -d' ' -f2 "$WORK/needed.txt")
for f in "${FILES[@]}"; do
  [[ -s "$WORK/src/$f" ]] || { echo "missing after download: $f"; exit 1; }
done
echo "   source tiles: $(du -sh "$WORK/src" | cut -f1)"

# --- 3. fill small NoData holes per cell (see fill_holes.py) ---------------
# Output: 4-band UInt16 (R, G, B, alpha). Runs $JOBS cells at a time.
JOBS="${JOBS:-4}"
echo "== fill holes ($JOBS in parallel)"
mkdir -p "$WORK/fill"
fill_one() {
  # </dev/null: `docker run -i` would otherwise read (and swallow) stdin.
  gdal python3 /scripts/fill_holes.py "/work/src/$1" "/work/fill/$1.part.tif" </dev/null \
    && mv -f "$WORK/fill/$1.part.tif" "$WORK/fill/$1"
}
running=0
for f in "${FILES[@]}"; do
  [[ -s "$WORK/fill/$f" ]] && continue
  fill_one "$f" &
  if (( ++running >= JOBS )); then wait -n; running=$((running - 1)); fi
done
while (( running > 0 )); do wait -n; running=$((running - 1)); done
for f in "${FILES[@]}"; do
  [[ -s "$WORK/fill/$f" ]] || { echo "fill failed: $f"; exit 1; }
done

# --- 4. mosaic VRT clipped to the box, then the A3 stretch ------------------
echo "== VRTs"
cut -d' ' -f2 "$WORK/needed.txt" | sed 's|^|/work/fill/|' > "$WORK/srclist.txt"
gdal gdalbuildvrt -q -te "$W" "$S" "$E" "$N" \
  -input_file_list /work/srclist.txt /work/mosaic.vrt
gdal python3 /scripts/stretch.py /work/mosaic.vrt /work/rgba.vrt --alpha-band 4

# --- 5. MBTiles at z14, overviews, low zooms, metadata --------------------
# ZOOM_LEVEL_STRATEGY=UPPER: see A2 results (LOWER gives z13).
echo "== MBTiles z14"
rm -f "$WORK/$OUTNAME.mbtiles"
gdal gdal_translate -q -of MBTiles \
  -co TILE_FORMAT=WEBP -co QUALITY="$QUALITY" \
  -co ZOOM_LEVEL_STRATEGY=UPPER -co RESAMPLING=BILINEAR \
  -co NAME="$OUTNAME" \
  /work/rgba.vrt "/work/$OUTNAME.mbtiles"
echo "== overviews"
gdal gdaladdo -q -r average "/work/$OUTNAME.mbtiles" \
  2 4 8 16 32 64 128 256 512 1024 2048 4096 8192 16384
echo "== low zooms and metadata"
gdal python3 /scripts/finish_mbtiles.py "/work/$OUTNAME.mbtiles" "$OUTNAME" --quality "$QUALITY"

# --- 6. deliver, record sources, clean up -----------------------------------
mv -f "$WORK/$OUTNAME.mbtiles" "$OUTDIR/$OUTNAME.mbtiles"
{
  echo "# $OUTNAME  box W=$W S=$S E=$E N=$N  built $(date -u +%Y-%m-%dT%H:%MZ)"
  sed "s|^\([^ ]*\) |$BUCKET/\1/|" "$WORK/needed.txt"
} > "$OUTDIR/$OUTNAME.sources.txt"
ls -lh "$OUTDIR/$OUTNAME.mbtiles"
if [[ "${KEEP_WORK:-0}" != 1 ]]; then
  rm -rf "$WORK"
  echo "== removed work dir $WORK"
fi
echo "== done in $(( $(date +%s) - START )) s"
