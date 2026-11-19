#!/usr/bin/env bash
# E1: convert the delivered MBTiles to PMTiles for object storage, and check them.
#
# Usage: scripts/to_pmtiles.sh            (from the imagery folder of the horus repo)
#   reads  ~/horus-imagery/out/horus-imagery-*.mbtiles   (HORUS_IMAGERY to change the root)
#   writes ~/horus-imagery/out/pmtiles/horus-imagery-*.pmtiles and SHA256SUMS
#
# For each file: `pmtiles convert` (Docker image, pinned), `pmtiles verify`, then the
# Horus tile service's own checks (services/tileserver/tilestore.py), and a comparison
# with the MBTiles it came from (format, zooms, bounds, attribution must match).
# Needs Docker, python3, and about as much free disk as the MBTiles (16 GB).
# Safe to re-run: a file already converted and checked is skipped.
set -euo pipefail
ROOT="${HORUS_IMAGERY:-$HOME/horus-imagery}"
OUT="$ROOT/out"
DEST="$OUT/pmtiles"
IMAGE="${PMTILES_IMAGE:-protomaps/go-pmtiles:v1.31.2}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
CHECK="$REPO/services/tileserver/tilestore.py"
mkdir -p "$DEST"
pm() { docker run --rm -v "$OUT:/data" "$IMAGE" "$@"; }

shopt -s nullglob
files=("$OUT"/horus-imagery-*.mbtiles)
[[ ${#files[@]} -gt 0 ]] || { echo "no horus-imagery-*.mbtiles in $OUT"; exit 1; }
failed=0
for mb in "${files[@]}"; do
  name="$(basename "$mb" .mbtiles)"
  pmt="$DEST/$name.pmtiles"
  if [[ -s "$pmt" && -f "$pmt.ok" ]]; then echo "skip $name (already converted and checked)"; continue; fi
  echo "== $name: $(date +%H:%M)"
  rm -f "$pmt" "$pmt.ok"
  pm -q convert "/data/$name.mbtiles" "/data/pmtiles/$name.pmtiles"
  if ! pm verify "/data/pmtiles/$name.pmtiles" >/dev/null 2>&1; then
    echo "FAIL $name: pmtiles verify"; pm verify "/data/pmtiles/$name.pmtiles" 2>&1 | tail -2; failed=1; continue
  fi
  if ! python3 "$CHECK" "$pmt"; then failed=1; continue; fi
  # The PMTiles must say what the MBTiles said.
  if ! python3 - "$mb" "$pmt" "$CHECK" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("tilestore", sys.argv[3])
ts = importlib.util.module_from_spec(spec); spec.loader.exec_module(ts)
a, _ = ts.read_metadata(sys.argv[1]); b, _ = ts.read_metadata(sys.argv[2])
diff = [k for k in ("format", "minzoom", "maxzoom", "attribution")
        if a.get(k) != b.get(k)]
if any(abs(x - y) > 1e-6 for x, y in zip(a["bounds"], b["bounds"])):
    diff.append("bounds")
if diff:
    print("FAIL differs from the MBTiles in: " + ", ".join(f"{k} ({a.get(k)!r} -> {b.get(k)!r})" for k in diff))
    sys.exit(1)
PY
  then failed=1; continue; fi
  touch "$pmt.ok"
done
[[ $failed -eq 0 ]] || { echo "Some files failed; see FAIL above. Don't upload; send the output."; exit 1; }
( cd "$DEST" && sha256sum horus-imagery-*.pmtiles > SHA256SUMS )
echo "All $(ls "$DEST"/horus-imagery-*.pmtiles | wc -l) files converted and checked."
echo "Hand-off set: $DEST (the .pmtiles files and SHA256SUMS; $(du -sh "$DEST" | cut -f1))"
