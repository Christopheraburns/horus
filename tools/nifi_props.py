"""Read-only: ask the Horus NiFi for component property definitions.

Run from a Workbench session (the NiFi gateway is not reachable from outside):
    python tools/nifi_props.py


Prints the property names (keys), allowable values and defaults for the
OAuth2 access token provider and InvokeHTTP, so a hand-built flow JSON uses the
exact keys this NiFi version expects. No secrets are printed.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "provision"))
os.chdir(REPO)
import config as cfgmod  # noqa: E402
import horus  # noqa: E402
import nifi as nifimod  # noqa: E402

cfg = cfgmod.load()
rep = horus.status(cfg)
ca = horus._ca_bundle(rep.env_name)
n = nifimod.NiFi(rep.nifi_api, cfg.workload_user, cfg.workload_password, verify=ca)
print("nifi:", rep.nifi_api, "| user:", n.whoami())

types = n.get("/flow/controller-service-types").get("controllerServiceTypes", [])
oauth = [t for t in types if "Oauth2AccessTokenProvider" in t["type"] or "OAuth2AccessTokenProvider" in t["type"]]
for t in oauth:
    b = t["bundle"]
    print("\nTYPE", t["type"], b["group"], b["artifact"], b["version"])
    d = n.get(f"/flow/controller-service-definition/{b['group']}/{b['artifact']}/{b['version']}/{t['type']}")
    for name, p in (d.get("propertyDescriptors") or {}).items():
        allow = [a.get("value") for a in (p.get("allowableValues") or [])]
        print(f"  key={name!r} display={p.get('displayName')!r} default={p.get('defaultValue')!r} "
              f"required={p.get('required')} sensitive={p.get('sensitive')} allow={allow}")

ptypes = n.get("/flow/processor-types").get("processorTypes", [])
inv = next(t for t in ptypes if t["type"] == "org.apache.nifi.processors.standard.InvokeHTTP")
b = inv["bundle"]
d = n.get(f"/flow/processor-definition/{b['group']}/{b['artifact']}/{b['version']}/{inv['type']}")
for name, p in (d.get("propertyDescriptors") or {}).items():
    if "oauth" in name.lower() or "OAuth" in (p.get("displayName") or ""):
        print(f"\nInvokeHTTP key={name!r} display={p.get('displayName')!r} default={p.get('defaultValue')!r}")

# Compare with the keys the generated OpenSky flow uses.
import json  # noqa: E402
flow = json.load(open(os.path.join(REPO, "nifi", "HORUS_Flights_OpenSky.json")))
oauth_cs = next(c for c in flow["flowContents"]["controllerServices"] if "Oauth2" in c["type"])
known = set()
for t in oauth:
    b = t["bundle"]
    d = n.get(f"/flow/controller-service-definition/{b['group']}/{b['artifact']}/{b['version']}/{t['type']}")
    known |= set((d.get("propertyDescriptors") or {}).keys())
missing = [k for k in oauth_cs["properties"] if k not in known]
print("\nOpenSky flow OAuth2 keys:", list(oauth_cs["properties"]))
print("OK: all keys known to this NiFi" if not missing else f"MISMATCH: {missing} not in this NiFi's definition")
