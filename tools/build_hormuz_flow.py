#!/usr/bin/env python3
"""Generate nifi/HORUS_Vessels_hormuz.now.json from the adsb.lol flow export.

A second vessel source, for the Strait of Hormuz and the Gulf of Oman, where
aisstream.io has almost no receivers. hormuz.now publishes a live snapshot of
every vessel in 24-28.5N, 54-59E, refreshed about every 20 seconds, free and
without a key, under CC BY 4.0 (credit hormuz.now with a link).

The flow polls the full snapshot every 30 seconds. InvokeHTTP's response cache
sends the ETag back, so an unchanged snapshot costs hormuz.now a 304. The
transform (nifi/scripts/vessels-hormuz.groovy) keys vessels on MMSI, like the
aisstream.io flow, and only emits vessels that moved. Run it again after editing
the Groovy:

    python3 tools/build_hormuz_flow.py
"""
import json
import os
import uuid

from flowgen import NIFI, ROOT, derive_poll_flow, id_maker

DST = os.path.join(NIFI, "HORUS_Vessels_hormuz.now.json")
GROOVY = os.path.join(NIFI, "scripts", "vessels-hormuz.groovy")

NS = uuid.UUID("b7e2d9c4-1f6a-4c3e-8d21-6a9f0e5b7c33")   # stable ids across rebuilds
SNAPSHOT_URL = "https://hormuz.now/api/snapshot"
POLL = "30 sec"   # hormuz.now asks for no more than one poll every 20 seconds

sid = id_maker(NS)


def build() -> dict:
    flow, parts = derive_poll_flow(
        sid, "HORUS - Vessels (hormuz.now)", f"Trigger hormuz.now ({POLL})", POLL,
        "Get hormuz.now snapshot", {
            "HTTP URL": SNAPSHOT_URL,
            # ETag / If-None-Match handled by the cache; a 304 replays the cached
            # body, which the transform's state then finds unchanged.
            "Response Cache Enabled": "true",
            "Response Cache Size": "10MB",
            "Socket Read Timeout": "30 secs",
            "Connection Timeout": "20 secs",
            "Request User-Agent": "HORUS-Vessel-Layer (#{http.contact})",
        },
        "Transform hormuz.now to Horus events", GROOVY)
    parts["transform"]["comments"] = (
        "Keeps the last emitted position per vessel in local state. "
        "Clear the state to re-send every vessel.")
    return flow


if __name__ == "__main__":
    flow = build()
    json.dump(flow, open(DST, "w"), indent=2)
    print(f"wrote {os.path.relpath(DST, ROOT)}")
