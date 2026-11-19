#!/usr/bin/env bash
# D1: write MANIFEST.md and SHA256SUMS for everything in out/.
#
# Usage: delivery.sh         (run from WSL2 once every file is built)
# The delivery set is out/: each horus-imagery-*.mbtiles, its .sources.txt,
# MANIFEST.md, and SHA256SUMS. Check it with `sha256sum -c SHA256SUMS` there.
set -euo pipefail
ROOT="${HORUS_IMAGERY:-$HOME/horus-imagery}"
OUTDIR="$ROOT/out"
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"

echo "== MANIFEST.md (with SQLite quick_check of every file)"
docker run --rm -u "$(id -u):$(id -g)" -v "$OUTDIR:/out" -v "$SCRIPTS:/scripts:ro" \
  ghcr.io/osgeo/gdal:ubuntu-full-3.9.3 python3 /scripts/manifest.py /out </dev/null

echo "== SHA256SUMS"
cd "$OUTDIR"
# Anything else in out/ (previews, stray files) is not part of the delivery.
ls horus-imagery-*.mbtiles horus-imagery-*.sources.txt MANIFEST.md \
  | xargs -P 8 -n 1 sha256sum | sort -k 2 > SHA256SUMS.part
mv -f SHA256SUMS.part SHA256SUMS
cat SHA256SUMS
sha256sum -c --quiet SHA256SUMS && echo "== verified"
