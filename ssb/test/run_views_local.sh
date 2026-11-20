#!/bin/bash
# The typed views (burndown O0b) on a local Trino, then Helios's harvest and profile
# over them, set up by provision/semantic.py. HELIOS_REPO: the Helios checkout
# (default ../../../helios).
#   ssb/test/run_views_local.sh
set -euo pipefail
cd "$(dirname "$0")"
HELIOS_REPO="${HELIOS_REPO:-$(cd ../../.. && pwd)/helios}"
../../nifi/test/run.sh > out/nifi.log            # the envelopes the views are filled from
rm -rf out/helios
name=horus-trino-views
docker rm -f $name >/dev/null 2>&1 || true
docker run -d --name $name -p 18481:8080 -v "$PWD/trino/catalog:/etc/trino/catalog:ro" trinodb/trino:460 >/dev/null
trap 'docker rm -f $name >/dev/null' EXIT
for i in $(seq 1 60); do
  docker logs $name 2>&1 | grep -q "SERVER STARTED" && break
  sleep 2
done
docker exec $name mkdir -p /tmp/warehouse
uv run -q --no-project --python 3.12 --with trino \
  --with "$HELIOS_REPO/packages/helios-cortex[trino]" --with "$HELIOS_REPO/packages/helios-model" \
  python check_views.py
