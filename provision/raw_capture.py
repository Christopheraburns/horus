"""Raw capture in the NiFi flows (burndown 17.3): publish every upstream response as received.

Each flow fetches with InvokeHTTP (relationship ``Response``) or ConnectWebSocket
(``binary message``, aisstream). A NiFi relationship can feed more than one
connection, each with its own copy of the FlowFile, so a second connection from
that relationship goes to a PublishKafka for the raw topic; the transform path
is untouched. (InvokeHTTP's ``Original`` is the empty trigger FlowFile, not the
response.)

A failed or stopped raw publisher must never hold up the events path: failures
are dropped (NiFi still shows a bulletin), and the raw connection expires
FlowFiles after a few minutes and has a high back-pressure limit, so it can't
fill and stop the fetching processor.

One definition, two uses: :func:`patch_flow` adds the branch to a flow
definition (tools/add_raw_capture.py keeps nifi/*.json up to date, so a fresh
import has it), and :func:`add_to_live` adds it to a flow already in NiFi through
the REST API, keeping the flow's state and queues (``horus.py add-raw-capture``).
"""
from __future__ import annotations

import copy
import uuid
from typing import List, Optional

PUBLISHER_NAME = "Publish raw response"
PUBLISH_KAFKA = "org.apache.nifi.kafka.processors.PublishKafka"
SOURCES = {   # the processor whose output is the upstream response, and that relationship
    "org.apache.nifi.processors.standard.InvokeHTTP": "Response",
    "org.apache.nifi.processors.websocket.ConnectWebSocket": "binary message",
}
# The Kafka key names the flow, so bronze rows say where they came from.
FLOW_KEYS = {
    "HORUS_Earthquakes_USGS.json": "usgs",
    "HORUS_Fires_NASA_FIRMS.json": "firms",
    "HORUS_Flights_OpenSky.json": "opensky",
    "HORUS_Flights_adsb.lol.json": "adsblol",
    "HORUS_Vessels_aisstream.io.json": "aisstream",
    "HORUS_Vessels_hormuz.now.json": "hormuznow",
    "HORUS_Weather_EONET.json": "eonet",
    "HORUS_Weather_NWS.json": "nws",
}
# The response's own facts, as Kafka headers (InvokeHTTP's attributes).
HEADER_PATTERN = r"invokehttp\.status\.code|invokehttp\.request\.url|mime\.type"
CONNECTION = {   # the raw branch: never back-pressures the fetching processor
    "flowFileExpiration": "3 min",
    "backPressureObjectThreshold": 100000,
    "backPressureDataSizeThreshold": "4 GB",
}


def publisher_properties(events_publisher: dict, flow_key: str) -> dict:
    """The raw publisher's properties: the events publisher's, re-pointed."""
    props = dict(events_publisher)
    props.update({
        "Topic Name": "#{kafka.raw.topic}",
        "Kafka Key": flow_key,
        # The producer checks the uncompressed size (FIRMS's CSV is 6 MB); the
        # broker checks the compressed one against the topic's max.message.bytes.
        "compression.type": "gzip",
        "max.request.size": "32 MB",
        "FlowFile Attribute Header Pattern": HEADER_PATTERN,
        "Failure Strategy": "Route to Failure",
        "Transactions Enabled": "false",
        "Publish Strategy": "USE_VALUE",
        "Record Reader": None,
        "Record Writer": None,
    })
    return props


def _find(group: dict, pred) -> List[dict]:
    return [p for p in group.get("processors", []) if pred(p)]


def patch_flow(flow: dict, flow_key: str) -> bool:
    """Add the raw branch to a flow definition. Returns False if it is already there."""
    g = flow["flowContents"]
    if _find(g, lambda p: p["name"] == PUBLISHER_NAME):
        return False
    src = _find(g, lambda p: p["type"] in SOURCES)
    events = _find(g, lambda p: p["type"] == PUBLISH_KAFKA)
    if len(src) != 1 or len(events) != 1:
        raise ValueError(f"expected one fetching processor and one PublishKafka, "
                         f"found {len(src)} and {len(events)}")
    src, events = src[0], events[0]
    pub = copy.deepcopy(events)
    pub["identifier"] = str(uuid.uuid4())
    pub["instanceIdentifier"] = str(uuid.uuid4())
    pub["name"] = PUBLISHER_NAME
    pub["comments"] = ("Burndown 17: the upstream response as received, to the raw topic and "
                       "the bronze table. Failures are dropped so they never hold up the events path.")
    pub["position"] = {"x": src["position"]["x"] + 450.0, "y": src["position"]["y"]}
    pub["properties"] = publisher_properties(events["properties"], flow_key)
    pub["autoTerminatedRelationships"] = ["success", "failure"]
    g["processors"].append(pub)

    rel = SOURCES[src["type"]]
    template = next(c for c in g["connections"] if c["source"]["id"] == src["identifier"])

    def end(p: dict) -> dict:
        return {"id": p["identifier"], "type": "PROCESSOR", "groupId": g["identifier"],
                "name": p["name"], "comments": "", "instanceIdentifier": p["instanceIdentifier"]}
    conn = copy.deepcopy(template)
    conn.update({"identifier": str(uuid.uuid4()), "instanceIdentifier": str(uuid.uuid4()), "name": "raw",
                 "source": end(src), "destination": end(pub), "selectedRelationships": [rel],
                 "bends": [], "prioritizers": []})
    conn.update(CONNECTION)
    g["connections"].append(conn)

    ctx = next(iter(flow.get("parameterContexts", {}).values()), None)
    if ctx is not None and not any(p["name"] == "kafka.raw.topic" for p in ctx["parameters"]):
        ctx["parameters"].append({"name": "kafka.raw.topic", "description": "Topic for raw upstream responses",
                                  "sensitive": False, "provided": False, "value": "horus-raw"})
    return True


def add_to_live(nifi, group_id: str, flow_key: str, log=print, name: str = "") -> Optional[str]:
    """Add the raw branch to a flow already in NiFi. Returns what was done, or None
    if the branch is already there. Starts the new publisher if the flow's events
    publisher is running."""
    procs = nifi.processors(group_id)
    if any(p["component"]["name"] == PUBLISHER_NAME for p in procs):
        return None
    src = [p for p in procs if p["component"]["type"] in SOURCES]
    events = [p for p in procs if p["component"]["type"] == PUBLISH_KAFKA]
    if len(src) != 1 or len(events) != 1:
        raise RuntimeError(f"{name}: expected one fetching processor and one PublishKafka, "
                           f"found {len(src)} and {len(events)}; add the raw branch by hand")
    src, events = src[0], events[0]
    ec = events["component"]
    pos = src["component"]["position"]
    body = {"revision": nifi._rev(0), "disconnectedNodeAcknowledged": False, "component": {
        "type": PUBLISH_KAFKA, "bundle": ec["bundle"], "name": PUBLISHER_NAME,
        "position": {"x": pos["x"] + 450.0, "y": pos["y"]},
        "config": {"properties": publisher_properties(ec["config"]["properties"], flow_key),
                   "autoTerminatedRelationships": ["success", "failure"],
                   "schedulingPeriod": "0 sec", "concurrentlySchedulableTaskCount": 1,
                   "comments": "Burndown 17: the upstream response as received, to the raw topic."}}}
    pub = nifi._req("POST", f"/process-groups/{group_id}/processors", json=body)
    conn = {"revision": nifi._rev(0), "disconnectedNodeAcknowledged": False, "component": dict(
        name="raw",
        source={"id": src["id"], "groupId": group_id, "type": "PROCESSOR"},
        destination={"id": pub["id"], "groupId": group_id, "type": "PROCESSOR"},
        selectedRelationships=[SOURCES[src["component"]["type"]]], **CONNECTION)}
    nifi._req("POST", f"/process-groups/{group_id}/connections", json=conn)
    if ec["state"] == "RUNNING":
        nifi.set_processor_state(nifi.get(f"/processors/{pub['id']}"), "RUNNING")
        return "added and started"
    return "added (left stopped, like the flow)"
