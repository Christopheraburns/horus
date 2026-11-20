#!/bin/bash
# End-to-end test of tile files in object storage (burndown 8.9): serve-tiles.py with a
# store in a local S3 server (moto) and the basemap in a local folder, on this machine.
#   services/tileserver/test/run_bucket_e2e.sh
# Needs uv, node 22+, services/tileserver/horus-basemap.mbtiles, and run_e2e.sh's fixtures
# (run that once first). RAZ itself can only be tested on the platform: bucket.py's probe.
set -euo pipefail
cd "$(dirname "$0")"
OUT=out/bucket
rm -rf "$OUT" && mkdir -p "$OUT/local"
ln -sf "$(cd .. && pwd -P)/horus-basemap.mbtiles" "$OUT/local/horus-basemap.mbtiles"
S3=18505
PY="uv run -q --no-project --python 3.12 --with boto3 --with moto[server]"
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_REGION=us-east-1 S3_ENDPOINT_URL=http://127.0.0.1:$S3
$PY moto_server -p $S3 > "$OUT/moto.log" 2>&1 &
# uv starts children, so stop by what they run, not by the shell's job ids.
cleanup() { pkill -f "moto_server -p $S3" || true; pkill -f "serve-tiles.py" || true
            pkill -f "main.js --verbose --port 18502" || true; }
trap cleanup EXIT
for i in $(seq 1 30); do curl -s -o /dev/null http://127.0.0.1:$S3 && break; sleep 1; done
$PY python - <<'PY'
import boto3, os
c = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT_URL"])
c.create_bucket(Bucket="horus-test")
p = "data/horus/test/tiles/"
c.put_object(Bucket="horus-test", Key=p, Body=b"")                      # folder marker (hdfs dfs -mkdir)
for src, name in [("out/store/horus-imagery-global.pmtiles", "horus-imagery-global.pmtiles"),
                  ("out/conv/horus-imagery-hormuz.pmtiles", "horus-imagery-hormuz.pmtiles"),
                  ("out/store/corrupt.pmtiles", "corrupt.pmtiles"),
                  ("out/store/horus-imagery-crimea.mbtiles", "horus-imagery-crimea.mbtiles")]:
    c.upload_file(src, "horus-test", p + name)
c.put_object(Bucket="horus-test", Key=p + "SHA256SUMS", Body=b"x")
whole = open("out/store/horus-imagery-global.pmtiles", "rb").read()        # a part missing, as on 2026-11-20
c.put_object(Bucket="horus-test", Key=p + "horus-imagery-channel.pmtiles", Body=whole[:-1000])
c.put_object(Bucket="horus-test", Key=p + "old/horus-imagery-bosporus.pmtiles", Body=b"x")   # not listed
PY
(cd .. && CDSW_APP_PORT=18501 TILESERVER_PUBLIC_URL=http://localhost:18501/ \
   TILESET_DIR="s3a://horus-test/data/horus/test/tiles/,test/$OUT/local" TILE_CACHE_MB=16 \
   $PY python serve-tiles.py) > "$OUT/serve.log" 2>&1 &
APP=$!
for i in $(seq 1 120); do
  grep -q "Startup complete" "$OUT/serve.log" && break
  kill -0 $APP 2>/dev/null || { tail -30 "$OUT/serve.log"; exit 1; }
  sleep 1
done
$PY python check_bucket_e2e.py "$OUT/serve.log"
