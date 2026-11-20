#!/usr/bin/env python3
"""Workbench Application entry point for the Horus tile service (burndown 8.3).

Runtime: Horus Node 22 (runtimes/node). On start it:

1. finds the tile files in the tile stores (TILESET_DIR: local folders and
   object storage prefixes such as s3a://<bucket>/data/horus/<instance>/tiles/,
   separated by commas; default this folder) and reads each one's own metadata, skipping
   any file that can't be served, with a log line saying why;
2. builds the tile-set registry from those files and tilesets.toml
   (docs/TILESETS.md), skipping entries that fail validation;
3. writes config.generated.json for tileserver-gl-light (ignored by git, so a
   `git pull` never conflicts with it) and runs tileserver as a child process on
   an internal port, streaming its output into this Application's log;
4. serves the Application's port itself (front_proxy.py): /registry.json for
   the UI, everything else passed to tileserver.

Tile files in object storage reach tileserver through the signing proxy
(bucket_proxy.py, 127.0.0.1:TILESERVER_BUCKET_PORT only): tileserver reads
http://127.0.0.1:<port>/<id>.pmtiles, and the proxy reads each byte range from
the bucket with the Application's own credentials (RAZ on CDP in AWS:
bucket.py), keeping TILE_CACHE_MB of ranges in memory. The browser never
reaches the bucket.

Adding a tile file means restarting the Application: tileserver-gl-light
doesn't reload its config.

Workbench rules this follows: bind 127.0.0.1 (0.0.0.0 hangs in "Starting") and
use CDSW_APP_PORT.

CORS: the UI is another Application, so every response needs
Access-Control-Allow-Origin. tileserver-gl sends it (and the front proxy passes
it on); the Workbench ingress doesn't add it (verified 2026-11-18). Set
TILESERVER_NO_CORS=1 only behind a proxy that adds its own.

TILESERVER_PUBLIC_URL must be this Application's own URL with a trailing slash
(https://horus-tileserver.<domain>/): served styles and TileJSON use it for
every glyph, sprite and tile URL.
"""
import json
import os
import subprocess
import sys
import threading
import time


def log(*a):
    print("[serve-tiles]", *a, flush=True)


try:
    here = os.path.dirname(os.path.abspath(__file__))
except NameError:  # Workbench runs the script inside a Jupyter kernel
    here = os.path.join(os.environ.get("HOME", "/home/cdsw"), "horus", "services", "tileserver")
os.chdir(here)
sys.path.insert(0, here)

import front_proxy  # noqa: E402
import registry  # noqa: E402
import tilestore  # noqa: E402

BASEMAP_ID = "horus-basemap"       # the vector basemap the dark style draws
port = int(os.environ.get("CDSW_APP_PORT", "8090"))
internal_port = int(os.environ.get("TILESERVER_INTERNAL_PORT", str(port + 1)))
public_url = os.environ.get("TILESERVER_PUBLIC_URL", "")
stores = [s.strip() for s in os.environ.get("TILESET_DIR", here).split(",") if s.strip()]
bucket_port = int(os.environ.get("TILESERVER_BUCKET_PORT", str(internal_port + 1)))
cache_mb = int(os.environ.get("TILE_CACHE_MB", "256"))

# 1. Tile files and what they say about themselves. A store is a local folder or an
#    object storage prefix (s3a://bucket/prefix/); several are separated by commas.
files = []
bucket_sources = {}      # id -> bucket_proxy.Source, for the tile files in object storage
for store in stores:
    if store.startswith(("s3://", "s3a://")):
        import bucket as bucketlib   # boto3 (and raz_client on CDP) only when a bucket is used
        import bucket_proxy
        try:
            b = bucketlib.Bucket(store)
            objects = b.list()
        except Exception as e:   # noqa: BLE001 -- a store that can't be read is skipped, not fatal
            log(f"SKIP store {store}: {type(e).__name__}: {e}")
            continue
        log(f"store {store}: {len(objects)} object(s)" + (" through RAZ" if b.raz else ""))
        for key, size in objects:
            name = key.rsplit("/", 1)[-1]
            id_, ext = os.path.splitext(name)
            if ext.lower() == ".mbtiles":
                log(f"SKIP {id_} ({name}): MBTiles can't be read from object storage; "
                    "convert it to PMTiles (imagery/scripts/to_pmtiles.sh)")
                continue
            if ext.lower() != ".pmtiles":
                continue
            try:
                meta, problems = tilestore.read_pmtiles(b.reader(key))
            except Exception as e:   # noqa: BLE001
                meta, problems = {}, [f"unreadable ({type(e).__name__}: {e})"]
            if problems:
                log(f"SKIP {id_} ({name}): {'; '.join(problems)}")
                continue
            if id_ in bucket_sources:
                log(f"SKIP {id_} ({store}{name}): a second file with the same id")
                continue
            bucket_sources[id_] = bucket_proxy.Source(size, lambda s, e, b=b, k=key: b.get_range(k, s, e))
            files.append((id_, f"s3://{b.bucket}/{key}", meta))
    else:
        for id_, path in tilestore.discover(store):
            meta, problems = tilestore.read_metadata(path)
            if problems:
                log(f"SKIP {id_} ({os.path.basename(path)}): {'; '.join(problems)}")
                continue
            files.append((id_, path, meta))
store = ", ".join(stores)

# 2. The registry.
reg = registry.build(files, registry.load_config(os.path.join(here, "tilesets.toml")))
for id_, reason in reg["skipped"]:
    log(f"SKIP {id_}: {reason}")
for id_, warning in reg["warnings"]:
    log(f"WARN {id_}: {warning}")
for e in reg["tilesets"]:
    log(f"serve {e['id']}: {e['role']}, {e['format']}, z{e['minzoom']}-{e['maxzoom']}, "
        f"{e['marking']['classification']}, order {e['order']}")
log(f"{len(reg['tilesets'])} tile set(s) in the registry from {store}")

# 3. tileserver-gl-light's config: every file tile set; the dark style if its basemap is there.
data = {}
for e in reg["tilesets"]:
    if e["kind"] == "file":
        path = e["source"]["path"]
        if path.startswith("s3://"):   # through the signing proxy, on localhost
            data[e["id"]] = {"pmtiles": f"http://127.0.0.1:{bucket_port}/{e['id']}.pmtiles"}
        else:
            data[e["id"]] = {"pmtiles" if path.lower().endswith(".pmtiles") else "mbtiles": path}
styles = {}
if BASEMAP_ID in data:
    styles["dark"] = {"style": "dark/style.json"}
else:
    log(f"WARNING: no {BASEMAP_ID} tile set, so the dark style (the UI's basemap) is not served")
config = {"options": {"paths": {"root": here, "fonts": "fonts", "sprites": "sprites", "styles": "styles",
                                "mbtiles": here, "pmtiles": here}},
          "styles": styles, "data": data}
with open("config.generated.json", "w") as f:
    json.dump(config, f, indent=2)
with open("registry.generated.json", "w") as f:   # the full registry, for whoever debugs this
    json.dump(reg, f, indent=2, default=str)

main_js = os.path.join(here, "node_modules", "tileserver-gl-light", "src", "main.js")
if not os.path.exists(main_js):
    log("installing tileserver-gl-light (npm ci, first start only)")
    subprocess.run(["npm", "ci", "--omit=dev", "--no-audit", "--no-fund"], check=True)

args = ["node", main_js, "--verbose", "--port", str(internal_port), "--bind", "127.0.0.1",
        "-c", "config.generated.json"]
if os.environ.get("TILESERVER_NO_CORS") == "1":
    args.append("--no-cors")
if public_url:
    if not public_url.startswith("https://") or not public_url.endswith("/"):
        log(f"WARNING: TILESERVER_PUBLIC_URL={public_url!r} should be https://<this-app>.<domain>/ "
            "(https, trailing slash)")
    log(f"public URL: {public_url}  <- must be this Application's own URL")
    args += ["--public_url", public_url]
else:
    log("WARNING: TILESERVER_PUBLIC_URL not set; tile URLs will follow the request host")

# 4. The signing proxy first (tileserver reads each PMTiles header as it starts), then
#    tileserver, then the front proxy on the Application's port.
if bucket_sources:
    used = {e["id"] for e in reg["tilesets"]}
    sources = {k: v for k, v in bucket_sources.items() if k in used}
    signing, cache = bucket_proxy.serve(bucket_port, sources, cache_mb * 1024 * 1024, log)
    threading.Thread(target=signing.serve_forever, daemon=True).start()
    log(f"signing proxy on 127.0.0.1:{bucket_port}: {len(sources)} tile file(s) from object storage, "
        f"{cache_mb} MB range cache")

    def report_cache():
        while True:
            time.sleep(600)
            log(f"range cache: {cache.hits} hits, {cache.misses} misses, {cache.size / 1e6:.0f} MB")
    threading.Thread(target=report_cache, daemon=True).start()


log(f"launching tileserver on 127.0.0.1:{internal_port}:", " ".join(args))
proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
# 127.0.0.1 on Workbench (0.0.0.0 hangs in "Starting"); the Docker test sets 0.0.0.0.
front = front_proxy.serve(port, internal_port, registry.public(reg), os.environ.get("TILESERVER_BIND", "127.0.0.1"))
threading.Thread(target=front.serve_forever, daemon=True).start()
log(f"front proxy on port {port}: /registry.json, everything else to tileserver")
for line in proc.stdout:
    print(line, end="", flush=True)
rc = proc.wait()
front.shutdown()
log("tileserver exited with code", rc)
sys.exit(rc)
