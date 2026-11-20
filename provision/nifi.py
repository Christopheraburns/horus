"""NiFi REST client for deploying the Horus flows into a Flow Management Data Hub.

Talks to the Data Hub's Knox ``cdp-proxy-api`` NiFi endpoint with the workload
user's basic-auth credentials. Every operation is idempotent: the parameter
context is created or updated in place, and a flow whose process group already
exists is left alone (re-running only refreshes parameters and run state).
"""
from __future__ import annotations

import copy
import glob
import json
import os
import time
import uuid
from typing import Dict, List, Optional

import requests

FLOW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nifi")


class NiFiError(RuntimeError):
    pass


class NiFi:
    def __init__(self, api_url: str, user: str, password: str, verify: object = True, timeout: int = 60):
        self.base = api_url.rstrip("/")
        self.s = requests.Session()
        self.s.auth = (user, password)
        self.s.verify = verify
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())

    # -- plumbing -----------------------------------------------------------
    def _req(self, method: str, path: str, **kw) -> dict:
        r = self.s.request(method, self.base + path, timeout=self.timeout, **kw)
        if r.status_code >= 400:
            hint = ""
            if r.status_code in (401, 403):
                hint = (" -- check the workload password, and that this user has NiFi Ranger "
                        "policies on the Flow Management Data Hub")
            raise NiFiError(f"{method} {path}: HTTP {r.status_code} {r.text[:300]}{hint}")
        return r.json() if r.content and "json" in r.headers.get("Content-Type", "") else {}

    def get(self, path: str) -> dict:
        return self._req("GET", path)

    def _rev(self, version: int = 0) -> dict:
        return {"clientId": self.client_id, "version": version}

    # -- discovery ----------------------------------------------------------
    def whoami(self) -> str:
        return self.get("/flow/current-user").get("identity", "?")

    def root_id(self) -> str:
        return self.get("/flow/process-groups/root")["processGroupFlow"]["id"]

    def child_groups(self, parent: str) -> List[dict]:
        return self.get(f"/process-groups/{parent}/process-groups").get("processGroups", [])

    def parameter_contexts(self) -> List[dict]:
        return self.get("/flow/parameter-contexts").get("parameterContexts", [])

    # -- parameter context ---------------------------------------------------
    def ensure_parameter_context(self, name: str, params: Dict[str, tuple]) -> str:
        """params: {name: (value, sensitive, description)}. Returns the context id."""
        wanted = [{"parameter": {"name": k, "value": v, "sensitive": s, "description": d}}
                  for k, (v, s, d) in params.items()]
        existing = next((c for c in self.parameter_contexts() if c["component"]["name"] == name), None)
        if existing is None:
            body = {"revision": self._rev(0),
                    "component": {"name": name, "description": "Horus feed flows", "parameters": wanted}}
            return self._req("POST", "/parameter-contexts", json=body)["id"]

        ctx_id = existing["id"]
        cur = {p["parameter"]["name"]: p["parameter"] for p in existing["component"].get("parameters", [])}
        changed = [w for w in wanted
                   if w["parameter"]["name"] not in cur
                   or w["parameter"]["sensitive"]                      # can't read back; always resend
                   or cur[w["parameter"]["name"]].get("value") != w["parameter"]["value"]]
        if not changed:
            return ctx_id
        body = {"revision": existing["revision"],
                "id": ctx_id,
                "component": {"id": ctx_id, "name": name, "parameters": changed}}
        req = self._req("POST", f"/parameter-contexts/{ctx_id}/update-requests", json=body)["request"]
        deadline = time.time() + 300
        while not req.get("complete") and time.time() < deadline:
            time.sleep(2)
            req = self.get(f"/parameter-contexts/{ctx_id}/update-requests/{req['requestId']}")["request"]
        self._req("DELETE", f"/parameter-contexts/{ctx_id}/update-requests/{req['requestId']}")
        if req.get("failureReason"):
            raise NiFiError(f"parameter context update failed: {req['failureReason']}")
        if not req.get("complete"):
            raise NiFiError("parameter context update did not complete within 5 minutes")
        return ctx_id

    # -- flows ---------------------------------------------------------------
    def upload_flow(self, parent: str, group_name: str, flow: dict, x: float, y: float) -> dict:
        files = {"file": ("flow.json", json.dumps(flow), "application/json")}
        data = {"groupName": group_name, "positionX": str(x), "positionY": str(y),
                "clientId": self.client_id, "disconnectedNodeAcknowledged": "false"}
        return self._req("POST", f"/process-groups/{parent}/process-groups/upload", files=files, data=data)

    def bind_context(self, group: dict, ctx_id: str) -> None:
        body = {"revision": group["revision"],
                "component": {"id": group["id"], "parameterContext": {"id": ctx_id}}}
        self._req("PUT", f"/process-groups/{group['id']}", json=body)

    def delete_context_if_unused(self, ctx_id: str) -> bool:
        ctx = self.get(f"/parameter-contexts/{ctx_id}")
        if ctx["component"].get("boundProcessGroups"):
            return False
        self._req("DELETE", f"/parameter-contexts/{ctx_id}?version={ctx['revision']['version']}"
                            f"&clientId={self.client_id}")
        return True

    def enable_services(self, group_id: str) -> None:
        self._req("PUT", f"/flow/process-groups/{group_id}/controller-services",
                  json={"id": group_id, "state": "ENABLED", "disconnectedNodeAcknowledged": False})

    def set_run_state(self, group_id: str, state: str) -> None:
        self._req("PUT", f"/flow/process-groups/{group_id}",
                  json={"id": group_id, "state": state, "disconnectedNodeAcknowledged": False})

    # -- processors -----------------------------------------------------------
    def processors(self, group_id: str) -> List[dict]:
        """Every processor in a group and its sub-groups."""
        out = list(self.get(f"/process-groups/{group_id}/processors").get("processors", []))
        for g in self.child_groups(group_id):
            out += self.processors(g["id"])
        return out

    def set_processor_state(self, proc: dict, state: str, timeout_s: int = 60) -> dict:
        """RUNNING or STOPPED; waits for a stop to finish (no active threads)."""
        self._req("PUT", f"/processors/{proc['id']}/run-status",
                  json={"revision": proc["revision"], "state": state, "disconnectedNodeAcknowledged": False})
        deadline = time.time() + timeout_s
        while True:
            p = self.get(f"/processors/{proc['id']}")
            stopped = p["component"]["state"] != "RUNNING" and not p.get("status", {}).get(
                "aggregateSnapshot", {}).get("activeThreadCount", 0)
            if state != "STOPPED" or stopped:
                return p
            if time.time() > deadline:
                raise NiFiError(f"processor {p['component']['name']} did not stop within {timeout_s}s")
            time.sleep(2)

    def set_property(self, proc: dict, name: str, value: str) -> dict:
        body = {"revision": proc["revision"], "disconnectedNodeAcknowledged": False,
                "component": {"id": proc["id"], "config": {"properties": {name: value}}}}
        return self._req("PUT", f"/processors/{proc['id']}", json=body)


# Flows that are imported and started only when asked for (HORUS_ENABLE_OPENSKY=1).
# OpenSky blocks cloud-provider addresses, so from AWS its flow can only time out.
OPTIONAL_FLOWS = {"HORUS_Flights_OpenSky.json": "opensky"}


def load_flows(instance: str, ctx_name: str, optional: frozenset = frozenset()) -> List[tuple]:
    """(group_name, flow_json) for every flow, re-pointed at this instance's context.
    Optional flows are included only if their key is in ``optional``."""
    out = []
    for path in sorted(glob.glob(os.path.join(FLOW_DIR, "HORUS_*.json"))):
        key = OPTIONAL_FLOWS.get(os.path.basename(path))
        if key and key not in optional:
            continue
        flow = json.load(open(path))
        flow = copy.deepcopy(flow)
        name = flow["flowContents"]["name"].replace("HORUS - ", f"HORUS-{instance} - ", 1)
        flow["flowContents"]["name"] = name

        def walk(g):
            g["parameterContextName"] = ctx_name
            for sub in g.get("processGroups", []):
                walk(sub)
        walk(flow["flowContents"])
        ctx = next(iter(flow.get("parameterContexts", {}).values()), {"parameters": []})
        ctx = dict(ctx, name=ctx_name)
        # Never ship values in the upload; the live context already holds them.
        ctx["parameters"] = [{k: v for k, v in p.items() if k != "value"} for p in ctx["parameters"]]
        flow["parameterContexts"] = {ctx_name: ctx}
        out.append((name, flow))
    return out


def inspect(nifi: NiFi, instance: str, ctx_name: str, optional: frozenset = frozenset()) -> dict:
    """Read-only: does our context exist, and the run state of each enabled Horus group
    (an optional flow left disabled in NiFi is not counted)."""
    ctx = any(c["component"]["name"] == ctx_name for c in nifi.parameter_contexts())
    prefix = f"HORUS-{instance} - "
    wanted = {name for name, _ in load_flows(instance, ctx_name, optional)}
    groups = {}
    for g in nifi.child_groups(nifi.root_id()):
        name = g["component"]["name"]
        if name in wanted:
            groups[name[len(prefix):]] = {k: g.get(k, 0) for k in
                                          ("runningCount", "stoppedCount", "invalidCount", "disabledCount")}
    return {"context": ctx, "groups": groups, "expected": len(wanted)}


SCRIPT_PROCESSOR = "org.apache.nifi.processors.script.ExecuteScript"


def _script_bodies(flow: dict) -> List[str]:
    found = []

    def walk(g):
        for p in g.get("processors", []):
            if p.get("type") == SCRIPT_PROCESSOR and "Script Body" in p.get("properties", {}):
                found.append(p["properties"]["Script Body"])
        for sub in g.get("processGroups", []):
            walk(sub)
    walk(flow["flowContents"])
    return found


def update_scripts(nifi: NiFi, instance: str, ctx_name: str, apply: bool, log=print,
                   optional: frozenset = frozenset()) -> int:
    """Bring the transform scripts of already-imported flows up to date.

    `deploy` leaves existing flows alone, so a changed script in nifi/ never
    reaches a running instance on its own. For each Horus flow present in NiFi,
    compare its ExecuteScript body with the repository's; with ``apply``, stop
    the processor, set the new body and start it again if it was running. The
    processor's local state (hormuz.now's last positions) is kept. Returns the
    number of processors that differ (or were updated).
    """
    root = nifi.root_id()
    by_name = {g["component"]["name"]: g for g in nifi.child_groups(root)}
    changed = 0
    for name, flow in load_flows(instance, ctx_name, optional):
        g = by_name.get(name)
        if g is None:
            log(f"nifi: {name} not imported; `create --yes` imports it")
            continue
        bodies = _script_bodies(flow)
        procs = [p for p in nifi.processors(g["id"]) if p["component"]["type"] == SCRIPT_PROCESSOR]
        if len(bodies) != 1 or len(procs) != 1:
            log(f"nifi: {name}: expected one ExecuteScript, found {len(procs)} in NiFi and "
                f"{len(bodies)} in the flow file; update it by hand")
            continue
        proc, body = procs[0], bodies[0]
        if proc["component"]["config"]["properties"].get("Script Body") == body:
            log(f"nifi: {name}: script up to date")
            continue
        changed += 1
        if not apply:
            log(f"nifi: {name}: script differs (would update {proc['component']['name']})")
            continue
        was_running = proc["component"]["state"] == "RUNNING"
        proc = nifi.set_processor_state(proc, "STOPPED")
        proc = nifi.set_property(proc, "Script Body", body)
        if was_running:
            nifi.set_processor_state(proc, "RUNNING")
        log(f"nifi: {name}: script updated" + (" and restarted" if was_running else " (left stopped)"))
    return changed


def deploy(nifi: NiFi, instance: str, ctx_name: str, params: Dict[str, tuple],
           start: bool, log=print, optional: frozenset = frozenset()) -> Dict[str, str]:
    """Create/refresh the context, import missing flows, enable services, optionally start."""
    log(f"nifi: authenticated as {nifi.whoami()}")
    ctx_id = nifi.ensure_parameter_context(ctx_name, params)
    log(f"nifi: parameter context {ctx_name} ready ({ctx_id})")

    root = nifi.root_id()
    by_name = {g["component"]["name"]: g for g in nifi.child_groups(root)}
    groups: Dict[str, str] = {}
    for i, (name, flow) in enumerate(load_flows(instance, ctx_name, optional)):
        g = by_name.get(name)
        if g is None:
            g = nifi.upload_flow(root, name, flow, x=400.0 * (i % 3), y=300.0 * (i // 3) + 600.0)
            log(f"nifi: imported {name}")
        else:
            log(f"nifi: {name} already present")
        bound = ((g.get("component") or {}).get("parameterContext") or {}).get("id")
        if bound != ctx_id:
            # NiFi made its own copy of the context on import; re-bind ours and drop the copy.
            g = nifi.get(f"/process-groups/{g['id']}")
            nifi.bind_context(g, ctx_id)
            if bound and nifi.delete_context_if_unused(bound):
                log(f"nifi: removed duplicate parameter context created by the import")
        groups[name] = g["id"]

    # Services and processors only validate once Kafka exists (bootstrap.servers is
    # empty until then), so enable and start together.
    if start:
        for name, gid in groups.items():
            nifi.enable_services(gid)
        log("nifi: controller services enabling")
        time.sleep(5)  # let services reach ENABLED before processors validate
        for name, gid in groups.items():
            nifi.set_run_state(gid, "RUNNING")
        log("nifi: all Horus process groups started")
    else:
        log("nifi: flows left stopped (Kafka not ready, or --no-start)")
    return groups


def add_raw_capture(nifi: NiFi, instance: str, apply: bool, log=print,
                    optional: frozenset = frozenset()) -> int:
    """Add the raw-capture branch (burndown 17.3, raw_capture.py) to imported flows that
    lack it, through the API: the flow's state and queues are kept. Returns how many
    flows lack it (or got it)."""
    import raw_capture
    root = nifi.root_id()
    by_name = {g["component"]["name"]: g for g in nifi.child_groups(root)}
    prefix = f"HORUS-{instance} - "
    missing = 0
    for path in sorted(glob.glob(os.path.join(FLOW_DIR, "HORUS_*.json"))):
        base = os.path.basename(path)
        key = OPTIONAL_FLOWS.get(base)
        if key and key not in optional:
            continue
        name = json.load(open(path))["flowContents"]["name"].replace("HORUS - ", prefix, 1)
        g = by_name.get(name)
        if g is None:
            continue   # not imported; `deploy` imports it with the branch already in it
        procs = nifi.processors(g["id"])
        if any(p["component"]["name"] == raw_capture.PUBLISHER_NAME for p in procs):
            log(f"nifi: {name}: raw capture present")
            continue
        missing += 1
        if not apply:
            log(f"nifi: {name}: no raw capture (would add it)")
            continue
        done = raw_capture.add_to_live(nifi, g["id"], raw_capture.FLOW_KEYS[base], log, name)
        log(f"nifi: {name}: raw capture {done}")
    return missing
