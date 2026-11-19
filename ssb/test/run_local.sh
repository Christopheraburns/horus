#!/bin/bash
# Run ssb/04_detections.sql on a local Flink (Docker) against synthetic events:
# the Kafka source and sink are swapped for a file and the print connector.
#   ssb/test/run_local.sh        -> prints the alerts the job emits
set -euo pipefail
cd "$(dirname "$0")"
python3 gen_events.py
python3 - <<'PY'
import re
sql = open("../04_detections.sql").read()
src = "WITH (\n    'connector' = 'filesystem',\n    'path' = '/data/events.jsonl',\n    'format' = 'raw'\n);"
out = []
for b in re.split(r"(?=CREATE TEMPORARY TABLE)", sql):
    if b.startswith("CREATE TEMPORARY TABLE horus_events_src"):
        b = re.sub(r"WITH \((?s:.*?)\);", src, b, count=1)
    elif b.startswith("CREATE TEMPORARY TABLE horus_alerts"):
        b = re.sub(r"WITH \((?s:.*?)\);", "WITH ('connector' = 'print');", b, count=1)
    out.append(b)
sql = re.sub(r"SET 'state\.backend\.[a-z.]+' = '[a-z]+';\n", "", "".join(out))
open("out/test.sql", "w").write("SET 'table.dml-sync' = 'true';\n" + sql)
PY
docker run --rm -v "$PWD/out:/data" flink:1.19.1-scala_2.12-java11 bash -c '
/opt/flink/bin/start-cluster.sh >/dev/null 2>&1; sleep 8
/opt/flink/bin/sql-client.sh -f /data/test.sql > /tmp/client.log 2>&1 || true
sleep 3
grep -A8 "ERROR" /tmp/client.log | sed "s/\x1b\[[0-9;]*m//g" | grep -v "^\s*at " | head -30 || true
grep -h "^+I" /opt/flink/log/*taskexecutor*.out || echo "no alerts"'
