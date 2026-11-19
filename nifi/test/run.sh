#!/bin/bash
# Run every NiFi transform in nifi/scripts/ on the samples in nifi/test/samples/,
# outside NiFi (groovy:4.0 in Docker, with a mocked session), then check the
# output against envelope v2 (docs/LAKE-SCHEMA.md).
#   nifi/test/run.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p out
# A JSON key named "properties" must be read with .get('properties'): on the platform's
# NiFi, x.properties and x['properties'] returned bean properties (NWS lost every field).
if grep -nE "\[['\"]properties['\"]\]|[a-zA-Z_]\.properties\b" ../scripts/*.groovy | grep -vE '^[^:]+:[0-9]+:\s*(//|\*)'; then
  echo "FAIL: read 'properties' with .get('properties') (see above)"; exit 1
fi
cases=(
  "earthquakes-usgs usgs.json"
  "fires-firms firms.csv invokehttp.request.url=https://firms.modaps.eosdis.nasa.gov/x/VIIRS_SNPP_NRT"
  "flights-opensky opensky.json"
  "flights-adsblol adsblol.json"
  "vessels-aisstream aisstream_position.json"
  "vessels-aisstream aisstream_unavailable.json"
  "vessels-aisstream aisstream_static.json"
  "vessels-hormuz hormuz.json"
  "weather-eonet eonet.json"
  "weather-nws nws.json"
)
cmds=""
for c in "${cases[@]}"; do
  set -- $c
  script=$1; input=$2; shift 2
  cmds+="echo '== $script < $input'; groovy /t/Run.groovy /s/$script.groovy /t/samples/$input /t/out/${input%.*}.jsonl $* && "
done
docker run --rm -v "$PWD:/t" -v "$PWD/../scripts:/s:ro" groovy:4.0-jdk17 bash -c "${cmds} true"
python3 check.py
