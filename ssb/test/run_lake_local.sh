#!/bin/bash
# Run the lake job's views (ssb/02_kafka_to_iceberg.sql) on a local Flink (Docker)
# over the envelopes the NiFi transforms produce (nifi/test/run.sh), then check
# every column against a Python reference (check_lake.py).
#   ssb/test/run_lake_local.sh
# The Kafka source becomes a file and the Iceberg sink a print table that
# receives each row as one JSON object; the views and the dedupe are the job's own.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p out
../../nifi/test/run.sh > out/nifi.log
python3 - <<'PY'
import glob, json, re
# Input: every v2 envelope, one repeated (must be deduped), and one v1 message.
lines = []
for f in sorted(glob.glob("../../nifi/test/out/*.jsonl")):
    lines += [l for l in open(f).read().splitlines() if l.strip()]
lines.append(lines[0])
lines.append(json.dumps({"schema_version": 1, "captured_at": "2025-11-19T18:00:00Z", "entity": {
    "id": "a0b0c0", "name": "V1TEST", "entityType": "FLIGHT", "timestamp": "2025-11-19T18:00:00Z",
    "position": {"lat": 10.0, "lng": 20.0, "alt": 1000.0},
    "source": {"provider": "adsb.lol", "feed": "flights", "originalId": "a0b0c0"},
    "properties": {"speed_knots": 300, "heading": 90}}}))
open("out/lake_input.jsonl", "w").write("\n".join(lines) + "\n")

sql = open("../02_kafka_to_iceberg.sql").read()
sql = re.sub(r"SET 'state\.backend\.[a-z.]+' = '[a-z]+';\n", "", sql)
sql = re.sub(r"(CREATE TEMPORARY TABLE horus_events_raw \((?s:.*?)\)) WITH \((?s:.*?)\);",
             r"\1 WITH ('connector' = 'filesystem', 'path' = '/data/lake_input.jsonl', 'format' = 'raw');",
             sql, count=1)
sql = re.sub(r"CREATE CATALOG horus_ice WITH \((?s:.*?)\);\n", "", sql, count=1)
head, insert = sql.split("INSERT INTO horus_ice.{{DATABASE}}.events_iceberg\n")
select_list, from_clause = re.match(r"SELECT (.*?)\nFROM \((.*)", insert, re.S).groups()
cols = [c.strip() for c in select_list.replace("\n", " ").split(",") if c.strip()]
obj = ", ".join(f"KEY '{c}' VALUE {c}" for c in cols if c != "payload")
test = ("SET 'table.dml-sync' = 'true';\n" + head
        + "CREATE TEMPORARY TABLE lake_out (j STRING) WITH ('connector' = 'print');\n"
        + f"INSERT INTO lake_out\nSELECT JSON_OBJECT({obj})\nFROM (" + from_clause)
open("out/lake_test.sql", "w").write(test)
json.dump(cols, open("out/lake_columns.json", "w"))
PY
docker run --rm -v "$PWD/out:/data" flink:1.19.1-scala_2.12-java11 bash -c '
/opt/flink/bin/start-cluster.sh >/dev/null 2>&1; sleep 8
/opt/flink/bin/sql-client.sh -f /data/lake_test.sql > /tmp/client.log 2>&1 || true
sleep 3
grep -A12 "ERROR" /tmp/client.log | sed "s/\x1b\[[0-9;]*m//g" | grep -v "^\s*at " | head -40 || true
grep -h "^+I" /opt/flink/log/*taskexecutor*.out' > out/lake_rows.txt || true
python3 check_lake.py
