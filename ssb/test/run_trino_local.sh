#!/bin/bash
# Check provision/lake.py against a local Trino (Docker, file-based Iceberg catalog):
# the v2 DDL is accepted, v1 and v2 tables are told apart, and Trino's tile_z8
# and obs_hash formulas agree with the Flink job's values row by row.
#   ssb/test/run_trino_local.sh     (after run_lake_local.sh, which writes out/lake_rows.txt)
set -euo pipefail
cd "$(dirname "$0")"
name=horus-trino-test
docker rm -f $name >/dev/null 2>&1 || true
docker run -d --name $name -p 18481:8080 -v "$PWD/trino/catalog:/etc/trino/catalog:ro" \
  trinodb/trino:460 >/dev/null
trap 'docker rm -f $name >/dev/null' EXIT
for i in $(seq 1 60); do
  docker logs $name 2>&1 | grep -q "SERVER STARTED" && break
  sleep 2
done
docker exec $name mkdir -p /tmp/warehouse
../../.venv/bin/python check_trino.py
