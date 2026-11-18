#!/usr/bin/env python3
"""Horus UI (Next.js): Workbench Application entry point.

Runtime: Horus Node 22 (runtimes/node). Runs `next start` on CDSW_APP_PORT,
bound to 127.0.0.1. It uses `next start`, not standalone output, because
standalone breaks static chunk serving (ChunkLoadError).

The basemap style URL is compiled into the browser bundle at build time, so this
launcher builds the app itself:
  - `npm ci` on first start, and again whenever package-lock.json changes
    (about 1-2 minutes)
  - `npm run build` on first start, and again whenever the style URL or the
    ui/ code (its last git commit) changes (about 3-5 minutes)
Later starts reuse the build and come up in seconds.

Application env vars:
    FEEDS_GATEWAY_URL      https://<gateway>.<domain>   (no trailing slash)
    INTEL_URL              https://<intel>.<domain>     (no trailing slash)
    TILESERVER_PUBLIC_URL  https://<tiles>.<domain>/    (the style URL is derived from it)
    NEXT_PUBLIC_BASEMAP_STYLE_URL  optional; overrides the derived style URL
    HORUS_UI_REBUILD=1     optional; force a rebuild on this start
"""
import hashlib
import json
import os
import subprocess
import sys


def log(*a):
    print("[horus-ui]", *a, flush=True)


try:
    here = os.path.dirname(os.path.abspath(__file__))
except NameError:  # Workbench runs the script inside a Jupyter kernel
    here = "/home/cdsw/horus/ui"
os.chdir(here)

style = os.environ.get("NEXT_PUBLIC_BASEMAP_STYLE_URL", "").strip()
if not style:
    tiles = os.environ.get("TILESERVER_PUBLIC_URL", "").strip()
    if not tiles:
        raise SystemExit("set TILESERVER_PUBLIC_URL (https://<tiles>.<domain>/) "
                         "or NEXT_PUBLIC_BASEMAP_STYLE_URL on this Application")
    style = tiles.rstrip("/") + "/styles/dark/style.json"
for var in ("FEEDS_GATEWAY_URL", "INTEL_URL"):
    val = os.environ.get(var, "")
    if not val:
        log(f"WARNING: {var} is not set; the UI will not reach that service")
    elif val.endswith("/"):
        log(f"WARNING: {var} ends with '/'; remove the trailing slash")

build_env = {**os.environ,
             "NEXT_PUBLIC_BASEMAP_STYLE_URL": style,
             # The CARTO tile-cache proxy is a Docker-only nginx; not used here.
             "NEXT_PUBLIC_TILE_CACHE_URL": "disabled",
             "NEXT_TELEMETRY_DISABLED": "1"}

# Reinstall when node_modules is missing or package-lock.json has changed since
# the last install (for example after a git pull that adds a dependency).
lock_path = "package-lock.json"
lock_stamp = os.path.join("node_modules", ".horus-lock.sha256")
with open(lock_path, "rb") as f:
    lock_hash = hashlib.sha256(f.read()).hexdigest()
try:
    with open(lock_stamp) as f:
        installed_hash = f.read().strip()
except OSError:
    installed_hash = None
if not os.path.isdir("node_modules") or installed_hash != lock_hash:
    log("installing dependencies (npm ci); package-lock.json is new or changed")
    subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], check=True, env=build_env)
    with open(lock_stamp, "w") as f:
        f.write(lock_hash)

stamp_path = os.path.join(".next", "horus-build.json")
try:  # last commit touching ui/, so a git pull that changes the UI rebuilds it
    rev = subprocess.run(["git", "log", "-1", "--format=%H", "--", "."], capture_output=True,
                         text=True, timeout=30).stdout.strip() or None
except (OSError, subprocess.SubprocessError):
    rev = None
want = {"basemap_style_url": style, "ui_commit": rev}
try:
    with open(stamp_path) as f:
        have = json.load(f)
except (OSError, ValueError):
    have = None
if have != want or os.environ.get("HORUS_UI_REBUILD") == "1":
    log(f"building (basemap style {style}); this takes a few minutes")
    subprocess.run(["npm", "run", "build"], check=True, env=build_env)
    with open(stamp_path, "w") as f:
        json.dump(want, f)
else:
    log("reusing existing build")

port = os.environ.get("CDSW_APP_PORT", "3000")
args = [os.path.join("node_modules", ".bin", "next"), "start",
        "--port", port, "--hostname", "127.0.0.1"]
log("launching:", " ".join(args))
proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1, env=build_env)
for line in proc.stdout:
    print(line, end="", flush=True)
rc = proc.wait()
log("next start exited with code", rc)
sys.exit(rc)
