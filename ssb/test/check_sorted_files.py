#!/usr/bin/env python3
"""Read the compacted files from run_maintenance_local.sh directly (pyarrow), not through
Trino, which reads row groups in parallel and so can't show the order inside a file.

Checks that each compacted file is one run sorted by tile_z8, and counts how many of
its row groups a Strait of Hormuz bounding box overlaps: Trino skips the others by their
min/max statistics (burndown 16.7).
"""
import glob
import sys

import pyarrow.parquet as pq

DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-11-16"
BOX = (24.0, 54.0, 28.5, 59.0)   # min lat, min lon, max lat, max lon (as check_maintenance.py)

files = glob.glob(f"out/maint_files/**/event_time_day={DAY}/*.parquet", recursive=True)
# Files replaced by compaction stay until snapshot expiry (7 days); keep the newest snapshot's
# file: the one holding the whole day.
compacted = max(files, key=lambda p: pq.ParquetFile(p).metadata.num_rows)
pf = pq.ParquetFile(compacted)
col = {name: pf.schema_arrow.get_field_index(name) for name in ("tile_z8", "lat", "lon")}
tiles = pf.read(columns=["tile_z8"]).column(0).to_pylist()
drops = sum(b < a for a, b in zip(tiles, tiles[1:]))

groups = pf.metadata.num_row_groups
hit = 0
for g in range(groups):
    rg = pf.metadata.row_group(g)
    lat, lon = rg.column(col["lat"]).statistics, rg.column(col["lon"]).statistics
    if not (lat.max < BOX[0] or lat.min > BOX[2] or lon.max < BOX[1] or lon.min > BOX[3]):
        hit += 1

print(f"sorted files: {DAY}: {len(tiles)} rows in one file, {drops} tile_z8 decreases; "
      f"a Hormuz bbox overlaps {hit} of {groups} row groups")
failures = []
if drops:
    failures.append(f"the compacted file is not one sorted run ({drops} decreases)")
if hit > max(2, groups // 10):
    failures.append(f"the bbox overlaps {hit} of {groups} row groups; rows aren't clustered by area")
for f in failures:
    print(f"FAIL {f}")
sys.exit(1 if failures else 0)
