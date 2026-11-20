#!/usr/bin/env python3
"""Add the raw-capture branch (burndown 17.3) to every flow definition in nifi/.

    python3 tools/add_raw_capture.py          # idempotent: a flow that has it is left alone

A fresh `horus.py create --yes` then imports flows that already publish raw
responses; flows already in NiFi get the branch from `horus.py add-raw-capture`.
The branch itself is defined once, in provision/raw_capture.py.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "provision"))
import raw_capture  # noqa: E402

changed = 0
for name, key in sorted(raw_capture.FLOW_KEYS.items()):
    path = os.path.join(ROOT, "nifi", name)
    flow = json.load(open(path))
    if raw_capture.patch_flow(flow, key):
        with open(path, "w") as f:
            json.dump(flow, f, indent=2)
        changed += 1
        print(f"added raw capture to {name} (key {key})")
    else:
        print(f"{name}: already has raw capture")
print(f"{changed} flow(s) changed")
