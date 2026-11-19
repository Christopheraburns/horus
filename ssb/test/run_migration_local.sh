#!/bin/bash
# Test the v1 -> v2 migration (provision/migrate_lake.py) on a local Trino.
# The v1 table holds what the v1 lake job wrote from both the v1 NiFi scripts
# (git 7f1c2dd, before envelope v2) and the v2 scripts, run on the same samples.
#   ssb/test/run_migration_local.sh
set -euo pipefail
cd "$(dirname "$0")"
V1_COMMIT=7f1c2dd
./run_lake_local.sh > out/lake.log 2>&1 || { cat out/lake.log; exit 1; }   # v2 envelopes + Flink rows

# The v1 transforms, as they were before envelope v2.
mkdir -p out/v1scripts out/v1
python3 - "$V1_COMMIT" <<'PY'
import json, subprocess, sys
commit = sys.argv[1]
embedded = {"earthquakes-usgs": "HORUS_Earthquakes_USGS.json", "fires-firms": "HORUS_Fires_NASA_FIRMS.json",
            "flights-adsblol": "HORUS_Flights_adsb.lol.json", "vessels-aisstream": "HORUS_Vessels_aisstream.io.json",
            "weather-eonet": "HORUS_Weather_EONET.json", "weather-nws": "HORUS_Weather_NWS.json"}
def show(path): return subprocess.run(["git", "show", f"{commit}:{path}"], capture_output=True, text=True, check=True).stdout
for name, flow in embedded.items():
    found = []
    def walk(n):
        if isinstance(n, dict):
            if isinstance(n.get("Script Body"), str): found.append(n["Script Body"])
            for v in n.values(): walk(v)
        elif isinstance(n, list):
            for v in n: walk(v)
    walk(json.loads(show(f"nifi/{flow}")))
    open(f"out/v1scripts/{name}.groovy", "w").write(found[0])
for name in ("flights-opensky", "vessels-hormuz"):
    open(f"out/v1scripts/{name}.groovy", "w").write(show(f"nifi/scripts/{name}.groovy"))
PY
N=../../nifi/test
cmds=""
while read -r script input attrs; do
  cmds+="groovy /n/Run.groovy /o/v1scripts/$script.groovy /n/samples/$input /o/v1/${input%.*}.jsonl $attrs >/dev/null && "
done <<'CASES'
earthquakes-usgs usgs.json
fires-firms firms.csv invokehttp.request.url=https://firms.modaps.eosdis.nasa.gov/x/VIIRS_SNPP_NRT
flights-opensky opensky.json
flights-adsblol adsblol.json
vessels-aisstream aisstream_position.json
vessels-aisstream aisstream_unavailable.json
vessels-aisstream aisstream_static.json
vessels-hormuz hormuz.json
weather-eonet eonet.json
weather-nws nws.json
CASES
docker run --rm -v "$PWD/$N:/n:ro" -v "$PWD/out:/o" groovy:4.0-jdk17 bash -c "${cmds} true" 2>&1 | grep -v "incubator modules" || true

name=horus-trino-migrate
docker rm -f $name >/dev/null 2>&1 || true
docker run -d --name $name -p 18481:8080 -v "$PWD/trino/catalog:/etc/trino/catalog:ro" trinodb/trino:460 >/dev/null
trap 'docker rm -f $name >/dev/null' EXIT
for i in $(seq 1 60); do docker logs $name 2>&1 | grep -q "SERVER STARTED" && break; sleep 2; done
docker exec $name mkdir -p /tmp/warehouse
../../.venv/bin/python check_migration.py
