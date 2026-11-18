"""Horus intel resolver (horus-intel): Workbench Application entry point.

Runtime: Horus Node 22 (runtimes/node). This Python script runs under the
Workbench PBJ kernel and starts the Node service, the live enrichment layer:
GET /resolve over OpenSanctions/OFAC, Wikidata, ip-api and RIPE, plus Memgraph
when MEMGRAPH_URL is set. It is bound to CDSW_APP_PORT on 127.0.0.1.
proc.wait() keeps the Application alive.

Application env vars (all optional):
    MEMGRAPH_URL        https://<memgraph-subdomain>.<domain>/cypher (no trailing slash)
    HORUS_HTTP_CONTACT  contact sent in the Wikidata User-Agent (inherited from
                        the project variables)
    INTEL_RESOLVER_DIR  source path (default: this script's directory, or
                        /home/cdsw/horus/services/intel)

Egress: at startup the service downloads the OFAC SDN list from
data.opensanctions.org. Per request it queries query.wikidata.org,
www.wikidata.org, ip-api.com and stat.ripe.net. Enable "Unauthenticated Access":
the UI's proxy sends no Authorization header.
"""
import os
import subprocess
import sys

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:  # Workbench runs the script inside a Jupyter kernel
    _here = "/home/cdsw/horus/services/intel"
INTEL_DIR = os.environ.get("INTEL_RESOLVER_DIR", _here)
if not os.path.isdir(INTEL_DIR):
    raise RuntimeError(f"horus-intel source not found at {INTEL_DIR} -- "
                       "git pull the repo into the project or set INTEL_RESOLVER_DIR")
os.chdir(INTEL_DIR)

if not os.path.isdir(os.path.join(INTEL_DIR, "node_modules")):
    print("[launcher] installing horus-intel dependencies (npm ci, first start only)", flush=True)
    subprocess.check_call(["npm", "ci", "--omit=dev", "--no-audit", "--no-fund"])

port = os.environ["CDSW_APP_PORT"]
# server.js reads INTEL_PORT (not PORT) and binds 127.0.0.1.
child_env = {**os.environ, "INTEL_PORT": port}
print(f"[launcher] starting horus-intel on 127.0.0.1:{port}", flush=True)
proc = subprocess.Popen(["node", "server.js"], env=child_env)
sys.exit(proc.wait())
