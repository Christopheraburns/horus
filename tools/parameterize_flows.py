#!/usr/bin/env python3
"""Normalise the Horus NiFi flow definitions in nifi/ (idempotent, in place).

- names each flow "HORUS - <feed>"
- binds every process group to the one shared parameter context "Horus"
- keeps Kafka brokers / user / password / topic, the aisstream key and the
  HTTP contact as parameter references, so nothing environment-specific or
  secret is ever committed
- rewrites the embedded "Horus" parameter context so every flow declares the
  same parameter set (values left empty; fill them in NiFi)

Run it after exporting a flow from NiFi, before committing:

    tools/parameterize_flows.py nifi/
"""
import glob, json, os, re, sys

CTX = "Horus"
PARAMS = [
    ("kafka.bootstrap.servers", "Comma-separated broker list, port 9093", False, ""),
    ("kafka.sasl.username", "CDP workload user name", False, ""),
    ("kafka.sasl.password", "CDP workload password", True, None),
    ("kafka.topic", "Topic all feeds publish to", False, "horus-events"),
    # Not sensitive: NiFi only allows sensitive parameters in sensitive
    # properties, and the key is spliced into ReplaceText's Replacement Value.
    ("aisstream.api.key", "aisstream.io API key (vessels flow only)", False, ""),
    ("http.contact", "Contact (email or URL) sent in the User-Agent to adsb.lol and NWS", False, ""),
]
NAMES = {
    "Earthquakes": "HORUS - Earthquakes (USGS)",
    "Fires": "HORUS - Fires (NASA FIRMS)",
    "Flights": "HORUS - Flights (adsb.lol)",
    "Vessels": "HORUS - Vessels (aisstream.io)",
    "EONET": "HORUS - Weather (EONET)",
    "NWS": "HORUS - Weather (NWS)",
}
USER_AGENTS = {
    "Flights": "HORUS-Flight-Layer (#{http.contact})",
    "NWS": "HORUS SEVERE WEATHER LAYER (#{http.contact})",
}


def walk(group):
    yield group
    for sub in group.get("processGroups", []):
        yield from walk(sub)


def normalise(path):
    flow = json.load(open(path))
    fc = flow["flowContents"]
    feed = next(k for k in NAMES if k.lower() in os.path.basename(path).lower())
    fc["name"] = NAMES[feed]
    for g in walk(fc):
        g["parameterContextName"] = CTX
        for cs in g.get("controllerServices", []):
            p = cs["properties"]
            if cs["type"].endswith("Kafka3ConnectionService"):
                p["bootstrap.servers"] = "#{kafka.bootstrap.servers}"
                p["sasl.username"] = "#{kafka.sasl.username}"
                p["sasl.password"] = "#{kafka.sasl.password}"
        for pr in g.get("processors", []):
            p = pr["properties"]
            if pr["type"].endswith("PublishKafka"):
                p["Topic Name"] = "#{kafka.topic}"
            if pr["type"].endswith("ReplaceText") and "APIKey" in (p.get("Replacement Value") or ""):
                p["Replacement Value"] = re.sub(
                    r'("APIKey"\s*:\s*")[^"]*(")', r"\1#{aisstream.api.key}\2", p["Replacement Value"])
            if p.get("Request User-Agent") and feed in USER_AGENTS:
                p["Request User-Agent"] = USER_AGENTS[feed]
            if pr["type"].endswith("ConnectWebSocket") and p.get("websocket-client-id"):
                p["websocket-client-id"] = "Horus-AIS"
    flow["parameterContexts"] = {CTX: {
        "name": CTX,
        "description": "Shared settings for all Horus feed flows",
        "parameters": [
            {k: v for k, v in dict(name=n, description=d, sensitive=s, provided=False, value=val).items()
             if v is not None}
            for n, d, s, val in PARAMS],
        "inheritedParameterContexts": [],
        "componentType": "PARAMETER_CONTEXT",
    }}
    with open(path, "w") as fh:
        json.dump(flow, fh, indent=2)
    return path


if __name__ == "__main__":
    for f in sorted(glob.glob(os.path.join(sys.argv[1] if len(sys.argv) > 1 else "nifi", "HORUS_*.json"))):
        print(normalise(f))
