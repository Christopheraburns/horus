#!/usr/bin/env bash
# B3 spot-check: render a region file at z8 (whole), z12 and z14 (around a point).
#
# Usage: spotcheck.sh NAME LON LAT [TAG]
#   e.g. spotcheck.sh hormuz 56.25 27.15 bandar-abbas
# Writes PNGs to ~/horus-imagery/checks/NAME/ (transparent = no data).
set -euo pipefail
NAME="$1"; LON="$2"; LAT="$3"; TAG="${4:-pt}"
ROOT="${HORUS_IMAGERY:-$HOME/horus-imagery}"
P="$(cd "$(dirname "$0")" && pwd)/preview.sh"
FILE="out/horus-imagery-$NAME.mbtiles"
CHK="checks/$NAME"
cd "$ROOT"
mkdir -p "$CHK"
[[ -s "$CHK/z8-whole.png" ]] || bash "$P" "$FILE" "$CHK/z8-whole.png" 8
box() {  # half-width in degrees -> W N E S
  awk -v x="$LON" -v y="$LAT" -v h="$1" 'BEGIN{printf "%.5f %.5f %.5f %.5f", x-h, y+h*0.8, x+h, y-h*0.8}'
}
# shellcheck disable=SC2046
bash "$P" "$FILE" "$CHK/z12-$TAG.png" 12 $(box 0.15)
# shellcheck disable=SC2046
bash "$P" "$FILE" "$CHK/z14-$TAG.png" 14 $(box 0.03)
ls -1 "$CHK"/*.png
