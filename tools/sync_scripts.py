#!/usr/bin/env python3
"""Copy each NiFi transform script from nifi/scripts/ into its flow definition.

nifi/scripts/*.groovy are the source of the ExecuteScript transforms; the flow
definitions in nifi/ embed a copy as the processor's Script Body, because that
is what the provisioner imports. Run this after editing a script:

    python3 tools/sync_scripts.py          # write the flows
    python3 tools/sync_scripts.py --check  # exit 1 if any flow is out of date

Only the Script Body changes; everything else in the flow file is left as it is.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NIFI = os.path.join(ROOT, "nifi")

FLOWS = {
    "HORUS_Earthquakes_USGS.json": "earthquakes-usgs.groovy",
    "HORUS_Fires_NASA_FIRMS.json": "fires-firms.groovy",
    "HORUS_Flights_OpenSky.json": "flights-opensky.groovy",
    "HORUS_Flights_adsb.lol.json": "flights-adsblol.groovy",
    "HORUS_Vessels_aisstream.io.json": "vessels-aisstream.groovy",
    "HORUS_Vessels_hormuz.now.json": "vessels-hormuz.groovy",
    "HORUS_Weather_EONET.json": "weather-eonet.groovy",
    "HORUS_Weather_NWS.json": "weather-nws.groovy",
}


def _bodies(node, found):
    """Every dict that holds a Script Body property, in document order."""
    if isinstance(node, dict):
        if isinstance(node.get("Script Body"), str):
            found.append(node)
        for v in node.values():
            _bodies(v, found)
    elif isinstance(node, list):
        for v in node:
            _bodies(v, found)
    return found


def sync(check: bool) -> int:
    stale = 0
    for flow_name, script_name in FLOWS.items():
        flow_path = os.path.join(NIFI, flow_name)
        script = open(os.path.join(NIFI, "scripts", script_name)).read()
        raw = open(flow_path).read()
        flow = json.loads(raw)
        holders = _bodies(flow, [])
        if len(holders) != 1:
            raise SystemExit(f"{flow_name}: expected one Script Body, found {len(holders)}")
        if holders[0]["Script Body"] == script:
            continue
        stale += 1
        if check:
            print(f"out of date: {flow_name} (from nifi/scripts/{script_name})")
            continue
        holders[0]["Script Body"] = script
        out = json.dumps(flow, indent=2) + ("\n" if raw.endswith("\n") else "")
        open(flow_path, "w").write(out)
        print(f"wrote nifi/{flow_name}")
    return 1 if (check and stale) else 0


if __name__ == "__main__":
    sys.exit(sync("--check" in sys.argv[1:]))
