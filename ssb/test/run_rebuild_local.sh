#!/bin/bash
# provision/rebuild.py (burndown 17.6) on a local Trino, with the replay on Java 8 and
# only the Groovy jars (eclipse-temurin:8-jre), as in a Workbench session.
#   ssb/test/run_rebuild_local.sh
set -euo pipefail
cd "$(dirname "$0")"
../../nifi/test/run.sh > out/nifi.log            # the real scripts' expected output
JARS="$PWD/out/groovy-jars"
mkdir -p "$JARS"
for a in groovy groovy-json; do
  [ -f "$JARS/$a-4.0.24.jar" ] || curl -sfL -o "$JARS/$a-4.0.24.jar" \
    "https://repo1.maven.org/maven2/org/apache/groovy/$a/4.0.24/$a-4.0.24.jar"
done
name=horus-trino-rebuild
docker rm -f $name >/dev/null 2>&1 || true
docker run -d --name $name -p 18481:8080 -v "$PWD/trino/catalog:/etc/trino/catalog:ro" trinodb/trino:460 >/dev/null
trap 'docker rm -f $name >/dev/null' EXIT
for i in $(seq 1 60); do
  docker logs $name 2>&1 | grep -q "SERVER STARTED" && break
  sleep 2
done
docker exec $name mkdir -p /tmp/warehouse
../../.venv/bin/python check_rebuild.py "$JARS"
