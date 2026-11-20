#!/bin/bash
# The bronze table (burndown 17.4, 17.5) on a local Trino: schema and maintenance.
# Retention, compaction of finished days, today left alone.
#
#   ssb/test/run_raw_local.sh
set -euo pipefail
cd "$(dirname "$0")"
name=horus-trino-raw
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
../../.venv/bin/python check_raw.py || rc=$?
[ $rc -eq 0 ] || exit $rc
