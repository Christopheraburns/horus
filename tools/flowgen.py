"""Shared helpers for generating NiFi flow definitions from an existing export.

Polling flows (OpenSky, hormuz.now) reuse the adsb.lol export's Kafka
publishing and replace its front end with one timer, one InvokeHTTP call and a
Groovy transform. ``derive_poll_flow`` does that rewiring; each builder then
adds what is specific to its source (controller services, parameters).
"""
import copy
import json
import os
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NIFI = os.path.join(ROOT, "nifi")
ADSB_FLOW = os.path.join(NIFI, "HORUS_Flights_adsb.lol.json")


def id_maker(ns: uuid.UUID):
    """Stable ids across rebuilds: uuid5 of a component name in the flow's namespace."""
    return lambda name: str(uuid.uuid5(ns, name))


def descriptor(name, display, sensitive=False, service=False):
    return {"name": name, "displayName": display, "identifiesControllerService": service,
            "sensitive": sensitive, "dynamic": False}


def derive_poll_flow(sid, group_name, trigger_name, poll, invoke_name, invoke_props,
                     transform_name, groovy_path, trigger_key="proc:trigger"):
    """The adsb.lol flow rewired as timer -> InvokeHTTP -> transform -> PublishKafka.

    Returns ``(flow, parts)``; ``parts`` holds the processors and the Kafka
    service by role so the caller can add to them. ``trigger_key`` names the
    trigger's id: the other ids come from the source processors' names, but the
    adsb.lol trigger is renamed whenever its schedule changes.
    """
    flow = copy.deepcopy(json.load(open(ADSB_FLOW)))
    fc = flow["flowContents"]
    gid = sid("group")
    fc["identifier"] = gid
    fc["instanceIdentifier"] = sid("group-instance")
    fc["name"] = group_name

    def by_type(suffix):
        return next(p for p in fc["processors"] if p["type"].endswith(suffix))
    gen = by_type(".GenerateFlowFile")
    invoke = by_type(".InvokeHTTP")
    transform = by_type(".ExecuteScript")
    publish = by_type(".PublishKafka")
    keep = [gen, invoke, transform, publish]

    # New ids for every component, scoped to this group.
    old_to_new = {}
    for p in keep:
        key = trigger_key if p is gen else "proc:" + p["name"]
        new = sid(key)
        old_to_new[p["identifier"]] = new
        p["identifier"] = new
        p["instanceIdentifier"] = sid(key.replace("proc:", "proc-instance:", 1))
        p["groupIdentifier"] = gid
    for f in fc.get("funnels", []):
        new = sid("funnel")
        old_to_new[f["identifier"]] = new
        f["identifier"], f["instanceIdentifier"], f["groupIdentifier"] = new, sid("funnel-instance"), gid
    kafka_cs = fc["controllerServices"][0]
    kafka_new = sid("cs:kafka")
    old_to_new[kafka_cs["identifier"]] = kafka_new
    kafka_cs["identifier"], kafka_cs["instanceIdentifier"], kafka_cs["groupIdentifier"] = \
        kafka_new, sid("cs-instance:kafka"), gid
    publish["properties"]["Kafka Connection Service"] = kafka_new
    fc["controllerServices"] = [kafka_cs]

    # Trigger: a plain timer on the primary node (no coordinates).
    gen["name"] = trigger_name
    gen["schedulingStrategy"] = "TIMER_DRIVEN"   # the adsb.lol trigger is CRON
    gen["schedulingPeriod"] = poll
    gen["properties"]["generate-ff-custom-text"] = ""
    gen["position"] = {"x": -600.0, "y": -200.0}

    invoke["name"] = invoke_name
    invoke["properties"].update(invoke_props)
    invoke["position"] = {"x": -184.0, "y": -200.0}

    transform["name"] = transform_name
    transform["properties"]["Script Body"] = open(groovy_path).read()

    fc["processors"] = keep

    # Connections: trigger -> invoke -> transform -> publish; failures to the funnel.
    funnel = fc["funnels"][0]["identifier"] if fc.get("funnels") else None
    by_id = {p["identifier"]: p for p in keep}
    conns = []
    for c in fc["connections"]:
        src_new, dst_new = old_to_new.get(c["source"]["id"]), old_to_new.get(c["destination"]["id"])
        if src_new is None or dst_new is None:
            continue   # touched Split Coords / EvaluateJsonPath
        conns.append((c, src_new, dst_new))
    conns.append((copy.deepcopy(fc["connections"][0]), gen["identifier"], invoke["identifier"]))
    conns[-1][0]["selectedRelationships"] = ["success"]

    out = []
    for c, s, d in conns:
        c = copy.deepcopy(c)
        key = f"conn:{s}:{d}:{','.join(sorted(c['selectedRelationships']))}"
        c["identifier"], c["instanceIdentifier"], c["groupIdentifier"] = sid(key), sid(key + ":i"), gid
        for end, new in (("source", s), ("destination", d)):
            c[end]["id"] = new
            c[end]["groupId"] = gid
            if new in by_id:
                c[end]["name"] = by_id[new]["name"]
                c[end]["type"] = "PROCESSOR"
                c[end]["instanceIdentifier"] = by_id[new]["instanceIdentifier"]
            elif new == funnel:
                c[end]["type"] = "FUNNEL"
        out.append(c)
    fc["connections"] = out

    parts = {"gen": gen, "invoke": invoke, "transform": transform, "publish": publish,
             "kafka_cs": kafka_cs, "group_id": gid}
    return flow, parts


def add_parameters(flow, params):
    """Add (name, description, sensitive) parameters the flow needs, if missing."""
    ctx = next(iter(flow["parameterContexts"].values()))
    names = {p["name"] for p in ctx["parameters"]}
    for name, desc, sensitive in params:
        if name not in names:
            p = {"name": name, "description": desc, "sensitive": sensitive, "provided": False}
            if not sensitive:
                p["value"] = ""
            ctx["parameters"].append(p)
