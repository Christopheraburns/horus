#!/usr/bin/env python3
"""Workbench Application entry point for the Horus tile server (tileserver-gl-light).

Runtime: Horus Node 22 (runtimes/node). Serves the self-hosted OpenMapTiles
vector basemap (horus-basemap.mbtiles) and the dark style the UI uses.

Runs tileserver as a CHILD process and streams its output into this app's log,
so startup errors are visible instead of hidden by an exec. The kernel stays
alive as the supervisor; the child holds the port.

Workbench rules this follows: bind 127.0.0.1 (0.0.0.0 hangs in "Starting") and
use CDSW_APP_PORT.

CORS: the UI is a different Application (another subdomain), so the browser
needs Access-Control-Allow-Origin on every style, tile, font and sprite
response. tileserver-gl sends it by default, and the Workbench ingress does not
add it (verified 2026-11-18), so --no-cors is NOT used. Set TILESERVER_NO_CORS=1
only behind a proxy that adds its own CORS headers (two sets conflict).

TILESERVER_PUBLIC_URL must be this Application's own URL with a trailing slash,
for example https://horus-tileserver.<domain>/. The served style.json uses it
for every glyph, sprite and tile URL, so a wrong host breaks the whole map.
"""
import os
import subprocess
import sys


def log(*a):
    print("[serve-tiles]", *a, flush=True)


try:
    here = os.path.dirname(os.path.abspath(__file__))
except NameError:  # Workbench runs the script inside a Jupyter kernel
    # Workbench project root is /home/cdsw; the repo is cloned at /home/cdsw/horus.
    here = os.path.join(os.environ.get("HOME", "/home/cdsw"), "horus", "services", "tileserver")
os.chdir(here)

port = os.environ.get("CDSW_APP_PORT", "8090")
public_url = os.environ.get("TILESERVER_PUBLIC_URL", "")

# The basemap is too large for git (214 MB); it is uploaded into this directory.
if not os.path.exists("horus-basemap.mbtiles"):
    raise SystemExit(f"horus-basemap.mbtiles not found in {here} -- upload it there "
                     "(Workbench project Files -> horus/services/tileserver/)")

main_js = os.path.join(here, "node_modules", "tileserver-gl-light", "src", "main.js")
if not os.path.exists(main_js):
    log("installing tileserver-gl-light (npm ci, first start only)")
    subprocess.run(["npm", "ci", "--omit=dev", "--no-audit", "--no-fund"], check=True)

args = ["node", main_js, "--verbose", "--port", port, "--bind", "127.0.0.1", "-c", "config.json"]
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

log("launching:", " ".join(args))
proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
for line in proc.stdout:
    print(line, end="", flush=True)
rc = proc.wait()
log("tileserver exited with code", rc)
sys.exit(rc)
