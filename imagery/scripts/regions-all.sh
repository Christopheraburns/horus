#!/usr/bin/env bash
# B3: build every agreed region in turn (one at a time, per the disk rule).
# Regions already in out/ are skipped; delete the file to rebuild it.
#
# Usage: regions-all.sh [NAME...]     (default: all regions below)
# Logs: ~/horus-imagery/logs/NAME.log
set -uo pipefail
ROOT="${HORUS_IMAGERY:-$HOME/horus-imagery}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$ROOT/logs"

# name west south east north  -- keep in sync with BURNDOWN-IMAGERY.md, B1
REGIONS="
hormuz         52   24   58   28
taiwan-strait  118  22   122  26
bosporus       28   40   30   42
crimea         32   44   37   46
channel        -2   49   2    52
hampton-roads  -77.5 36  -75.5 38
"

want=" $* "
while read -r name w s e n; do
  [[ -n "$name" ]] || continue
  [[ $# -eq 0 || "$want" == *" $name "* ]] || continue
  if [[ -s "$ROOT/out/horus-imagery-$name.mbtiles" ]]; then
    echo "skip $name (already built)"; continue
  fi
  echo "== $name: $(date +%H:%M)"
  # </dev/null: docker run -i inside region.sh would swallow this loop's input.
  if bash "$HERE/region.sh" "$name" "$w" "$s" "$e" "$n" \
      < /dev/null > "$ROOT/logs/$name.log" 2>&1; then
    echo "   ok: $(tail -1 "$ROOT/logs/$name.log"); $(ls -lh "$ROOT/out/horus-imagery-$name.mbtiles" | awk '{print $5}')"
  else
    echo "   FAILED (see logs/$name.log):"; tail -5 "$ROOT/logs/$name.log" | sed 's/^/   /'
  fi
done <<< "$REGIONS"
