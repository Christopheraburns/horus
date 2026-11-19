#!/usr/bin/env python3
"""Generate nifi/HORUS_Flights_OpenSky.json from the adsb.lol flow export.

The OpenSky flow reuses the adsb.lol flow's Kafka publishing, then replaces the
front end: one timer, one InvokeHTTP call to OpenSky's global /states/all with
an OAuth2 client-credentials token, and the transform in
nifi/scripts/flights-opensky.groovy. Run it again after editing the Groovy:

    python3 tools/build_opensky_flow.py

It also keeps the adsb.lol flow under adsb.lol's anonymous limit
(500 requests a day): 6 points every 20 minutes is 432 a day.
"""
import json
import os
import uuid

from flowgen import add_parameters, derive_poll_flow, descriptor, id_maker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NIFI = os.path.join(ROOT, "nifi")
SRC = os.path.join(NIFI, "HORUS_Flights_adsb.lol.json")
DST = os.path.join(NIFI, "HORUS_Flights_OpenSky.json")
GROOVY = os.path.join(NIFI, "scripts", "flights-opensky.groovy")

NS = uuid.UUID("5f0c8a52-3c1e-4a8e-9a57-0f6a1c2b9d11")   # stable ids across rebuilds
NIFI_VERSION = "2.6.0.4.12.0.0-914"          # version in the adsb.lol export
OAUTH_NAR_VERSION = "2.6.0.4.12.0.100-95"    # installed on the Horus NiFi (tools/nifi_props.py)
OPENSKY_URL = "https://opensky-network.org/api/states/all?extended=1"
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
POLL = "90 sec"   # 4 credits per global call: 960 calls/day = 3,840 of a standard account's 4,000

# adsb.lol allows 500 requests per UTC day (window resets 00:00 UTC). Spend it in
# working hours only: every 12 min, 13:00-03:48 UTC (7:00 AM-9:48 PM US Central
# standard time) = 15 h x 5 cycles x 6 points = 450 requests. Quartz syntax;
# NiFi evaluates it in the server's time zone (UTC on Data Hub nodes).
ADSB_CRON = "0 0/12 0-3,13-23 * * ?"
ADSB_LABEL = "7AM-10PM CT, every 12 min"


sid = id_maker(NS)


def build() -> dict:
    flow, parts = derive_poll_flow(
        sid, "HORUS - Flights (OpenSky)", f"Trigger OpenSky ({POLL})", POLL,
        "Get OpenSky states", {}, "Transform OpenSky to Horus events", GROOVY,
        # The trigger's id dates from when the adsb.lol trigger had this name.
        trigger_key="proc:Generate Coordinates for ADSB.lol (20 min)")
    gid, invoke = parts["group_id"], parts["invoke"]

    # OAuth2 client-credentials token provider (built into NiFi).
    oauth_id = sid("cs:oauth2")
    oauth = {
        "identifier": oauth_id,
        "instanceIdentifier": sid("cs-instance:oauth2"),
        "name": "OpenSky OAuth2 Token",
        "comments": "Client credentials from the OpenSky account page (API client).",
        "type": "org.apache.nifi.oauth2.StandardOauth2AccessTokenProvider",
        "bundle": {"group": "org.apache.nifi", "artifact": "nifi-oauth2-provider-nar", "version": OAUTH_NAR_VERSION},
        # Property keys as NiFi 2.6 defines them (verified with tools/nifi_props.py).
        "properties": {
            "Authorization Server URL": TOKEN_URL,
            "Client Authentication Strategy": "REQUEST_BODY",
            "Grant Type": "client_credentials",
            "Client ID": "#{opensky.client.id}",
            "Client secret": "#{opensky.client.secret}",
            "Refresh Window": "60 s",   # renew a minute before the 30-minute token expires
        },
        "propertyDescriptors": {
            "Authorization Server URL": descriptor("Authorization Server URL", "Authorization Server URL"),
            "Client Authentication Strategy": descriptor("Client Authentication Strategy", "Client Authentication Strategy"),
            "Grant Type": descriptor("Grant Type", "Grant Type"),
            "Client ID": descriptor("Client ID", "Client ID"),
            "Client secret": descriptor("Client secret", "Client secret", sensitive=True),
            "Refresh Window": descriptor("Refresh Window", "Refresh Window"),
        },
        "controllerServiceApis": [{
            "type": "org.apache.nifi.oauth2.OAuth2AccessTokenProvider",
            "bundle": {"group": "org.apache.nifi", "artifact": "nifi-standard-services-api-nar",
                       "version": OAUTH_NAR_VERSION},
        }],
        "scheduledState": "DISABLED",
        "bulletinLevel": "WARN",
        "componentType": "CONTROLLER_SERVICE",
        "groupIdentifier": gid,
    }
    flow["flowContents"]["controllerServices"].append(oauth)

    # InvokeHTTP: one global request with the token.
    invoke["properties"].update({
        "HTTP URL": OPENSKY_URL,
        "Request OAuth2 Access Token Provider": oauth_id,
        "OAuth2 Access Token Refresh Strategy": "ON_TOKEN_EXPIRATION",
        "Socket Read Timeout": "60 secs",
        "Connection Timeout": "30 secs",
        "Request User-Agent": "HORUS-Flight-Layer (#{http.contact})",
    })
    invoke["propertyDescriptors"]["Request OAuth2 Access Token Provider"] = descriptor(
        "Request OAuth2 Access Token Provider", "Request OAuth2 Access Token Provider", service=True)

    # Parameters: the OpenSky client credentials (values are set by the provisioner).
    add_parameters(flow, (
        ("opensky.client.id", "OpenSky API client ID (Flights OpenSky flow)", False),
        ("opensky.client.secret", "OpenSky API client secret (Flights OpenSky flow)", True),
    ))
    return flow


def slow_adsb() -> None:
    """Keep the adsb.lol flow under 500 requests per UTC day (see ADSB_CRON)."""
    flow = json.load(open(SRC))
    name = f"Generate Coordinates for ADSB.lol ({ADSB_LABEL})"
    changed = False
    for p in flow["flowContents"]["processors"]:
        if p["type"].endswith("GenerateFlowFile") and (
                p["schedulingStrategy"] != "CRON_DRIVEN" or p["schedulingPeriod"] != ADSB_CRON):
            p["schedulingStrategy"] = "CRON_DRIVEN"
            p["schedulingPeriod"] = ADSB_CRON
            p["name"] = name
            changed = True
    for c in flow["flowContents"]["connections"]:
        for end in ("source", "destination"):
            if c[end]["name"].startswith("Generate Coordinates for ADSB.lol"):
                c[end]["name"] = name
    if changed:
        json.dump(flow, open(SRC, "w"), indent=2)
        print(f"updated {os.path.relpath(SRC, ROOT)}: CRON {ADSB_CRON}")


if __name__ == "__main__":
    flow = build()
    json.dump(flow, open(DST, "w"), indent=2)
    print(f"wrote {os.path.relpath(DST, ROOT)}")
    slow_adsb()
