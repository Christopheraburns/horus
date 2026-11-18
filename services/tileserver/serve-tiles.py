#!/usr/bin/env python3
"""Workbench Application entry point for the Horus tile server (tileserver-gl-light).

Runtime: Horus Node 22 (runtimes/node). Serves the self-hosted OpenMapTiles
vector basemap (horus-basemap.mbtiles) and the dark style the UI uses.

Runs tileserver as a CHILD process and streams its output into this app's log,
so startup errors are visible instead of hidden by an exec. The kernel stays
alive as the supervisor; the child holds the port.

Workbench rules this follows: bind 127.0.0.1 (0.0.0.0 hangs in "Starting"),
use CDSW_APP_PORT, and run with --no-cors (the Workbench ingress adds the CORS
headers; a second set conflicts).
"""
import os
import subprocess
import sys


def log(*a):
    print("[serve-tiles]", *a, flush=True)


try:
    here = os.path.dirname(os.path.abspath(__file__))
except NameError:  # Workbench runs the script inside a Jupyter kernel
    here = os.path.join(os.environ.get("HOME", "/home/cdsw"), "services", "tileserver")
os.chdir(here)

port = os.environ.get("CDSW_APP_PORT", "8090")
public_url = os.environ.get("TILESERVER_PUBLIC_URL", "")

# The basemap is too large for git (214 MB); it is uploaded into this directory.
if not os.path.exists("horus-basemap.mbtiles"):
    raise SystemExit(f"horus-basemap.mbtiles not found in {here} -- upload it there "
                     "(Workbench project Files -> services/tileserver/)")

main_js = os.path.join(here, "node_modules", "tileserver-gl-light", "src", "main.js")
if not os.path.exists(main_js):
    log("installing tileserver-gl-light (npm ci, first start only)")
    subprocess.run(["npm", "ci", "--omit=dev", "--no-audit", "--no-fund"], check=True)

args = ["node", main_js, "--verbose", "--no-cors", "--port", port, "--bind", "127.0.0.1",
        "-c", "config.json"]
if public_url:
    args += ["--public_url", public_url]

log("launching:", " ".join(args))
proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
for line in proc.stdout:
    print(line, end="", flush=True)
rc = proc.wait()
log("tileserver exited with code", rc)
sys.exit(rc)
