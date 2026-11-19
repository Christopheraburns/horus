#!/bin/bash
# Check provision/lake_maintenance.py (16.6) and bbox file skipping (16.7) on a local Trino.
# Compaction of finished days in tile order, today left alone, snapshot and orphan clean-up.
#
#   ssb/test/run_maintenance_local.sh
set -euo pipefail
cd "$(dirname "$0")"
name=horus-trino-maint
docker rm -f $name >/dev/null 2>&1 || true
docker run -d --name $name -p 18481:8080 -v "$PWD/trino/catalog:/etc/trino/catalog:ro" \
  trinodb/trino:460 >/dev/null
trap 'docker rm -f $name >/dev/null' EXIT
for i in $(seq 1 60); do
  docker logs $name 2>&1 | grep -q "SERVER STARTED" && break
  sleep 2
done
docker exec $name mkdir -p /tmp/warehouse
rc=0
../../.venv/bin/python check_maintenance.py || rc=$?
# Keep the table files for a direct look (row order and row-group ranges), outside Trino.
rm -rf out/maint_files && mkdir -p out/maint_files
docker cp $name:/tmp/warehouse/horus_mt out/maint_files/ >/dev/null
[ $rc -eq 0 ] || exit $rc
uv run -q --no-project --with pyarrow python check_sorted_files.py 2026-11-16
