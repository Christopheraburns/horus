#!/bin/bash
# The raw capture job (ssb/05_raw_to_iceberg.sql, burndown 17.4) on a local Flink and
# Kafka (Docker): messages written the way NiFi's raw publisher writes them (key =
# flow, value = body, InvokeHTTP attributes as headers), read by the job's own source
# table and views; the Iceberg sink becomes a print table. check_raw_flink.py checks
# every column, and that a repeated body from the same flow is stored once.
#   ssb/test/run_raw_flink_local.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p out/rawflink
net=horus-rawtest
KAFKA=apache/kafka:3.8.0
FLINK=flink:1.19.1-scala_2.12-java11
JAR=flink-sql-connector-kafka-3.2.0-1.19.jar
[ -f out/rawflink/$JAR ] || curl -sfL -o out/rawflink/$JAR \
  https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.2.0-1.19/$JAR
cleanup() { docker rm -f horus-rawtest-kafka horus-rawtest-flink >/dev/null 2>&1 || true; docker network rm $net >/dev/null 2>&1 || true; }
cleanup; trap cleanup EXIT
docker network create $net >/dev/null
docker run -d --name horus-rawtest-kafka --network $net -e KAFKA_NODE_ID=1 \
  -e KAFKA_PROCESS_ROLES=broker,controller -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@horus-rawtest-kafka:9093 \
  -e KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093 -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://horus-rawtest-kafka:9092 \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 $KAFKA >/dev/null
for i in $(seq 1 40); do docker exec horus-rawtest-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list >/dev/null 2>&1 && break; sleep 2; done
docker exec horus-rawtest-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --topic raw --partitions 1 >/dev/null
# headers, key, value (the console producer's order); the NWS body twice (must be stored once), one without headers (aisstream).
printf '%s\n' \
  'invokehttp.status.code:200,invokehttp.request.url:https://earthquake.usgs.gov/x.geojson,mime.type:application/json	usgs	{"type":"FeatureCollection","features":[]}' \
  'invokehttp.status.code:200,invokehttp.request.url:https://api.weather.gov/alerts/active,mime.type:application/geo+json	nws	{"features":[{"id":"a"}]}' \
  'invokehttp.status.code:200,invokehttp.request.url:https://api.weather.gov/alerts/active,mime.type:application/geo+json	nws	{"features":[{"id":"a"}]}' \
  'invokehttp.status.code:503,invokehttp.request.url:https://firms.example/c.csv,mime.type:text/csv	firms	latitude,longitude' \
  'NO_HEADERS	aisstream	{"MessageType":"PositionReport","Ünïcode":"é"}' \
| docker exec -i horus-rawtest-kafka /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic raw \
    --property parse.key=true --property key.separator=$'\t' --property parse.headers=true \
    --property headers.delimiter=$'\t' --property headers.separator=, --property headers.key.separator=: \
    --property null.marker=NO_HEADERS
python3 - <<'PY'
import re
sql = open("../05_raw_to_iceberg.sql").read()
sql = re.sub(r"\A(--[^\n]*\n|\n)+", "", sql)
sql = re.sub(r"SET 'state\.backend\.[a-z.]+' = '[a-z]+';\n", "", sql)
for k in ("properties.security.protocol", "properties.sasl.mechanism", "properties.sasl.jaas.config"):
    sql = re.sub(rf"\s*'{re.escape(k)}' = '[^\n]*',?", "", sql)
sql = sql.replace("'scan.startup.mode' = 'group-offsets'", "'scan.startup.mode' = 'earliest-offset', 'scan.bounded.mode' = 'latest-offset'")
sql = sql.replace("{{TOPIC}}", "raw").replace("{{GROUP_ID}}", "t").replace("{{BROKERS}}", "horus-rawtest-kafka:9092")
sql = sql.replace(",\n);", "\n);")
sql = re.sub(r"CREATE CATALOG horus_ice WITH \((?s:.*?)\);\n", "", sql)
cols = re.search(r"INSERT INTO \S+\s+SELECT (.*?)\s+FROM \(", sql, re.S).group(1)
names = [c.strip() for c in cols.replace("\n", " ").split(",")]
types = {"http_status": "INT", "received_at": "TIMESTAMP(6)", "ingest_time": "TIMESTAMP(6)", "body_chars": "BIGINT",
         "kafka_partition": "INT", "kafka_offset": "BIGINT"}
sink = "CREATE TEMPORARY TABLE raw_sink (\n" + ",\n".join(f"  {n} {types.get(n, 'STRING')}" for n in names) + \
       "\n) WITH ('connector' = 'print', 'print-identifier' = 'RAW');\n"
sql = re.sub(r"INSERT INTO horus_ice\.\{\{DATABASE\}\}\.raw_responses", sink + "INSERT INTO raw_sink", sql)
open("out/rawflink/test.sql", "w").write("SET 'table.dml-sync' = 'true';\n" + sql)
PY
docker run -d --name horus-rawtest-flink --network $net -v "$PWD/out/rawflink:/data" $FLINK sleep 600 >/dev/null
docker exec horus-rawtest-flink bash -c "cp /data/$JAR /opt/flink/lib/ && /opt/flink/bin/start-cluster.sh >/dev/null 2>&1"
sleep 8
docker exec horus-rawtest-flink bash -c '/opt/flink/bin/sql-client.sh -f /data/test.sql > /tmp/client.log 2>&1 || true; sleep 3
  grep -A8 "ERROR" /tmp/client.log | sed "s/\x1b\[[0-9;]*m//g" | grep -v "^\s*at " | head -30 || true
  cat /opt/flink/log/*taskexecutor*.out' > out/rawflink/result.txt
cat out/rawflink/result.txt | head -40
python3 check_raw_flink.py out/rawflink/result.txt
