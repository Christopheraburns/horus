#!/usr/bin/env python3
"""horus provision -- set up a Horus deployment in a CDP environment.

    python provision/horus.py status [--json] [--env-file .env]
    python provision/horus.py create [--yes] [--wait]

`status` is read-only: it calls only describe/list CDP APIs, never starts a
stopped Data Hub or wakes a suspended virtual warehouse, and prints the values
the Feeds-Gateway needs.

`create` builds whatever Horus owns and is missing (today: the Kafka and Flink
Data Hubs). Without --yes it only prints the plan. It is idempotent: re-running
it skips anything that already exists.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfgmod  # noqa: E402
from cdp import CdpError, cdp  # noqa: E402

OK, WARN, FAIL, TODO = "ok", "warn", "fail", "todo"


class Report:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.gateway_env: Dict[str, str] = {}
        self.planned_hubs: List[Dict[str, str]] = []
        self.hubs: Dict[str, Optional[dict]] = {}
        self.nifi_api: Optional[str] = None
        self.env_name = ""
        self.owner = ""

    def add(self, component: str, state: str, detail: str) -> None:
        self.rows.append({"component": component, "state": state, "detail": detail})

    @property
    def blocked(self) -> bool:
        return any(r["state"] == FAIL for r in self.rows)


def _endpoint(cluster: dict, service: str, api: bool = True) -> Optional[str]:
    for ep in (cluster.get("endpoints") or {}).get("endpoints", []):
        url = ep.get("serviceUrl", "")
        if ep.get("serviceName") == service and (("/cdp-proxy-api/" in url) == api):
            return url
    return None


def _hosts(cluster: dict, groups: tuple) -> List[str]:
    return [i["fqdn"] for g in cluster.get("instanceGroups", []) if g["name"] in groups
            for i in g.get("instances", []) if i.get("fqdn")]


def _datahub(rep: Report, label: str, name: str, env_crn: str) -> Optional[dict]:
    try:
        c = cdp("datahub", "describe-cluster", "--cluster-name", name)["cluster"]
    except CdpError as e:
        if e.not_found:
            return None
        rep.add(label, FAIL, f"{name}: {e}")
        return {}
    if c.get("environmentCrn") != env_crn:
        rep.add(label, FAIL, f"{name} exists but belongs to a different environment")
        return {}
    return c


def _dedicated_hub(rep: Report, label: str, name: str, override: Optional[str], template: str,
                   env: dict, runtime: Optional[str], definitions: set) -> Optional[dict]:
    """A Data Hub Horus owns: report it, or report what `create` would build."""
    hub = _datahub(rep, label, name, env["crn"])
    if hub is None:
        cloud = (env.get("cloudPlatform") or "AWS").upper()
        definition = override or (f"{runtime} - {template} for {cloud}" if runtime else None)
        if definition in definitions:
            rep.add(label, TODO, f"{name} does not exist; create will use '{definition}'")
            rep.planned_hubs.append({"name": name, "definition": definition, "cloud": cloud})
        else:
            rep.add(label, FAIL, f"{name} does not exist and cluster definition '{definition}' "
                                 "is not available; set the matching HORUS_*_DEFINITION")
    elif hub:
        rep.add(label, OK if hub.get("status") == "AVAILABLE" else WARN, f"{name} {hub.get('status')}")
    return hub


def status(cfg: cfgmod.Config) -> Report:
    rep = Report()
    for p in cfg.problems:
        rep.add("config", FAIL, p)
    if cfg.problems:
        return rep

    # Who are we?
    try:
        user = cdp("iam", "get-user")["user"]
        rep.add("cdp identity", OK, f"{user.get('workloadUsername')} (control plane {user.get('crn', '').split(':')[3]})")
    except CdpError as e:
        rep.add("cdp identity", FAIL, f"CDP credentials rejected: {e}")
        return rep
    rep.owner = user.get("workloadUsername") or ""
    if cfg.workload_user and cfg.workload_user != user.get("workloadUsername"):
        rep.add("workload user", WARN,
                f"HORUS_WORKLOAD_USER={cfg.workload_user} differs from the CDP key owner "
                f"{user.get('workloadUsername')}")
    if not (cfg.workload_user and cfg.workload_password):
        rep.add("workload creds", WARN,
                "HORUS_WORKLOAD_USER / HORUS_WORKLOAD_PASSWORD not set -- needed for Kafka, NiFi, SSB and the lakehouse")

    # Environment + Data Lake runtime
    try:
        env = cdp("environments", "describe-environment", "--environment-name", cfg.environment)["environment"]
    except CdpError as e:
        rep.add("environment", FAIL, f"{cfg.environment}: {e}")
        return rep
    env_crn = env["crn"]
    rep.env_name = cfg.environment
    rep.add("environment", OK if env.get("status") == "AVAILABLE" else WARN,
            f"{cfg.environment} {env.get('status')} {env.get('cloudPlatform')} {env.get('region')}")
    runtime = None
    try:
        dl = cdp("datalake", "list-datalakes", "--environment-name", cfg.environment)["datalakes"][0]
        dld = cdp("datalake", "describe-datalake", "--datalake-name", dl["datalakeName"])["datalake"]
        runtime = next((p["version"].split("-")[0] for p in dld.get("productVersions", [])
                        if p.get("name") == "CDH"), None)
        rep.add("data lake", OK if dld.get("status") == "RUNNING" else WARN,
                f"{dl['datalakeName']} {dld.get('status')} runtime {runtime}")
    except (CdpError, IndexError, KeyError) as e:
        rep.add("data lake", FAIL, f"could not read the Data Lake: {e}")

    # Dedicated Data Hubs: Kafka and Flink (SQL Stream Builder); created if missing.
    definitions = {d["clusterDefinitionName"] for d in
                   cdp("datahub", "list-cluster-definitions").get("clusterDefinitions", [])}
    kafka = _dedicated_hub(rep, "kafka datahub", cfg.kafka_datahub, cfg.kafka_definition,
                           "Streams Messaging Light Duty", env, runtime, definitions)
    rep.hubs["kafka"] = kafka
    if kafka:
        brokers = _hosts(kafka, ("core_broker", "broker"))
        rep.rows[-1]["detail"] += f" ({len(brokers)} brokers)"
        if brokers:
            rep.gateway_env["KAFKA_BROKERS"] = ",".join(f"{h}:9093" for h in brokers)
    flink = _dedicated_hub(rep, "flink datahub", cfg.flink_datahub, cfg.flink_definition,
                           "Streaming Analytics Light Duty", env, runtime, definitions)
    rep.hubs["flink"] = flink
    if flink:
        ssb = _endpoint(flink, "SSB_SSE_UI", api=False) or _endpoint(flink, "SSB_SSE_UI")
        rep.rows[-1]["detail"] += f"; SSB {ssb or 'endpoint not found'}"

    # NiFi Data Hub (re-used)
    nifi = _datahub(rep, "nifi datahub", cfg.nifi_datahub, env_crn)
    if nifi is None:
        rep.add("nifi datahub", FAIL, f"{cfg.nifi_datahub} not found (set HORUS_NIFI_DATAHUB)")
    rep.hubs["nifi"] = nifi
    if nifi:
        api = _endpoint(nifi, "NIFI_NODE")
        rep.nifi_api = api
        rep.add("nifi datahub", OK if nifi.get("status") == "AVAILABLE" else WARN,
                f"{cfg.nifi_datahub} {nifi.get('status')}; API {api or 'not exposed'}")
        if "NiFi 2" not in (nifi.get("workloadType") or ""):
            rep.add("nifi version", WARN, "the Horus flows target NiFi 2.x; this hub is not a NiFi 2 template")

    # Lakehouse virtual warehouse (re-used, CDW): Impala or Trino
    if not cfg.lake_vw:
        rep.add("lake vw", FAIL, "HORUS_LAKE_VW is not set")
    else:
        dw = next((c for c in cdp("dw", "list-clusters").get("clusters", [])
                   if c.get("environmentCrn") == env_crn), None)
        vw = None
        if dw:
            vw = next((v for v in cdp("dw", "list-vws", "--cluster-id", dw["id"]).get("vws", [])
                       if v.get("name") == cfg.lake_vw), None)
        if not vw:
            rep.add("lake vw", FAIL, f"{cfg.lake_vw} not found in {cfg.environment}'s Data Warehouse")
        elif vw.get("vwType") not in ("impala", "trino"):
            rep.add("lake vw", FAIL, f"{cfg.lake_vw} is a {vw.get('vwType')} warehouse; need Impala or Trino")
        else:
            d = cdp("dw", "describe-vw", "--cluster-id", dw["id"], "--vw-id", vw["id"])["vw"]
            ep = d.get("endpoints") or {}
            suspend = (d.get("autoscalingOptions") or {}).get("autoSuspendTimeoutSeconds")
            when = f"auto-suspends after {suspend}s" if suspend else "never auto-suspends"
            owner = (d.get("creator") or {}).get("workloadUsername")
            if vw["vwType"] == "trino":
                m = re.search(r"https://([^:'/]+):(\d+)", ep.get("trinoCli", ""))
                host, port = (m.group(1), m.group(2)) if m else ("", "443")
                rep.add("lake vw", OK if host else FAIL,
                        f"{cfg.lake_vw} (trino) {d.get('status')}, {when}, owner {owner}"
                        + ("" if host else " -- no Trino endpoint found"))
                rep.gateway_env.update({"LAKE_ENGINE": "trino", "LAKE_CATALOG": cfg.lake_catalog,
                                        "HIVE_HOST": host, "HIVE_PORT": port, "HIVE_USE_SSL": "true"})
            else:
                ldap = (d.get("supportedAuthMethods") or {}).get("ldap")
                rep.add("lake vw", OK if ldap else FAIL,
                        f"{cfg.lake_vw} (impala) {d.get('status')}, {when}, owner {owner}"
                        + ("" if ldap else " -- LDAP auth disabled, gateway cannot log in"))
                rep.gateway_env.update({"LAKE_ENGINE": "impala", "HIVE_HOST": ep.get("hostname", ""),
                                        "HIVE_PORT": str(ep.get("port", 443)),
                                        "HIVE_HTTP_PATH": "cliservice", "HIVE_USE_SSL": "true"})

    # Workbench (informational)
    try:
        ws = [w for w in cdp("ml", "list-workspaces").get("workspaces", [])
              if w.get("environmentName") == cfg.environment]
        names = [w["instanceName"] for w in ws]
        if cfg.workbench and cfg.workbench not in names:
            rep.add("workbench", FAIL, f"{cfg.workbench} not found in {cfg.environment}")
        elif cfg.workbench:
            rep.add("workbench", OK, cfg.workbench)
        else:
            rep.add("workbench", WARN, f"HORUS_WORKBENCH not set; available: {', '.join(names) or 'none'}")
    except CdpError as e:
        rep.add("workbench", WARN, f"could not list workbenches: {e}")

    # Not yet implemented -- reported so nobody mistakes silence for success.
    rep.add("data plane", TODO,
            f"topic {cfg.topic}, database {cfg.database}, NiFi context {cfg.parameter_context}: "
            "checks not implemented yet (need the hubs running)")

    rep.gateway_env.update({
        "KAFKA_TOPIC": cfg.topic,
        "KAFKA_GROUP_ID": cfg.gateway_group,
        "HIVE_DATABASE": cfg.database,
        "HIVE_TABLE": cfg.table,
    })
    if cfg.workload_user:
        rep.gateway_env.update({"KAFKA_USER": cfg.workload_user, "HIVE_USER": cfg.workload_user})
    return rep


CREATE_CMD = {"AWS": "create-aws-cluster", "AZURE": "create-azure-cluster", "GCP": "create-gcp-cluster"}
TERMINAL_BAD = ("CREATE_FAILED", "DELETE_COMPLETED", "DELETE_FAILED", "DELETED_ON_PROVIDER_SIDE")


def create_hubs(cfg: cfgmod.Config, rep: Report, wait: bool, timeout_s: int = 5400) -> int:
    for hub in rep.planned_hubs:
        request = {
            "clusterName": hub["name"],
            "clusterDefinitionName": hub["definition"],
            "environmentName": rep.env_name,
            "tags": [{"key": "project", "value": "horus"},
                     {"key": "horus-instance", "value": cfg.instance},
                     {"key": "horus-owner", "value": rep.owner}],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(request, fh)
        try:
            cdp("datahub", CREATE_CMD[hub["cloud"]], "--cli-input-json", f"file://{fh.name}")
            print(f"requested {hub['name']} ({hub['definition']})")
        except CdpError as e:
            print(f"FAILED to request {hub['name']}: {e}")
            return 1
        finally:
            os.unlink(fh.name)
    if not wait:
        print("Not waiting; run `status` to follow progress.")
        return 0

    pending = {h["name"] for h in rep.planned_hubs}
    deadline = time.time() + timeout_s
    while pending and time.time() < deadline:
        time.sleep(60)
        for name in sorted(pending):
            st = cdp("datahub", "describe-cluster", "--cluster-name", name)["cluster"].get("status")
            print(f"{time.strftime('%H:%M:%S')} {name}: {st}", flush=True)
            if st == "AVAILABLE":
                pending.discard(name)
            elif st in TERMINAL_BAD:
                print(f"{name} ended in {st}; see the Management Console event history")
                return 1
    if pending:
        print(f"timed out waiting for: {', '.join(sorted(pending))}")
        return 1
    print("All Horus Data Hubs are AVAILABLE.")
    return 0


def _ready(hub: Optional[dict]) -> bool:
    return bool(hub) and hub.get("status") == "AVAILABLE"


def _ca_bundle(env_name: str) -> str:
    """Public CAs (Knox / CDW endpoints) + the environment's FreeIPA root (brokers)."""
    import certifi

    root = cdp("environments", "get-root-certificate", "--environment-name", env_name)["contents"]
    fh = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
    fh.write(open(certifi.where()).read() + "\n" + root.strip() + "\n")
    fh.close()
    return fh.name


def deploy_data_plane(cfg: cfgmod.Config, rep: Report, start_flows: bool) -> int:
    """Topic, lakehouse table and NiFi flows -- each only once its hub is ready."""
    if not (cfg.workload_user and cfg.workload_password):
        print("data plane: HORUS_WORKLOAD_USER / HORUS_WORKLOAD_PASSWORD not set; skipping")
        return 1
    user, pw = cfg.workload_user, cfg.workload_password
    ca = _ca_bundle(rep.env_name)
    failures = 0
    kafka_ok = False
    try:
        brokers = [b for b in rep.gateway_env.get("KAFKA_BROKERS", "").split(",") if b]
        if _ready(rep.hubs.get("kafka")) and brokers:
            import kafka_admin
            try:
                kafka_admin.ensure_topic(brokers, user, pw, ca, cfg.topic)
                kafka_ok = True
            except Exception as e:  # noqa: BLE001
                print(f"kafka: FAILED: {e}")
                failures += 1
        else:
            print("kafka: hub not AVAILABLE yet; topic skipped")

        if rep.gateway_env.get("LAKE_ENGINE") == "trino":
            import lake
            try:
                lake.ensure_table(rep.gateway_env["HIVE_HOST"], int(rep.gateway_env["HIVE_PORT"]), user, pw,
                                  cfg.lake_catalog, cfg.database, cfg.table)
            except Exception as e:  # noqa: BLE001
                print(f"lake: FAILED: {e}")
                failures += 1
        else:
            print("lake: table creation is implemented for Trino warehouses only; skipped")

        if _ready(rep.hubs.get("nifi")) and rep.nifi_api:
            import nifi as nifimod
            params = {
                "kafka.bootstrap.servers": (",".join(brokers), False, "Comma-separated broker list, port 9093"),
                "kafka.sasl.username": (user, False, "CDP workload user name"),
                "kafka.sasl.password": (pw, True, "CDP workload password"),
                "kafka.topic": (cfg.topic, False, "Topic all feeds publish to"),
                "aisstream.api.key": (cfg.aisstream_api_key or "", False, "aisstream.io API key (vessels flow only)"),
                "http.contact": (cfg.http_contact or "", False, "Contact sent in the User-Agent to adsb.lol and NWS"),
            }
            try:
                n = nifimod.NiFi(rep.nifi_api, user, pw, verify=ca)
                nifimod.deploy(n, cfg.instance, cfg.parameter_context, params,
                               start=start_flows and kafka_ok)
            except Exception as e:  # noqa: BLE001
                print(f"nifi: FAILED: {e}")
                failures += 1
        else:
            print("nifi: hub not AVAILABLE; flows skipped")

        print("ssb: Flink job submission not implemented yet (needs the Flink hub up to read its API)")
    finally:
        os.unlink(ca)
    return 1 if failures else 0


def _print(rep: Report) -> None:
    marks = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL", TODO: "TODO"}
    width = max(len(r["component"]) for r in rep.rows)
    for r in rep.rows:
        print(f"[{marks[r['state']]}] {r['component']:<{width}}  {r['detail']}")
    if rep.gateway_env:
        print("\nFeeds-Gateway variables (passwords not shown):")
        for k, v in rep.gateway_env.items():
            print(f"  {k}={v}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="horus provision")
    ap.add_argument("command", choices=["status", "create"])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--yes", action="store_true", help="create: actually create (billable) resources")
    ap.add_argument("--wait", action="store_true", help="create: wait until the Data Hubs are AVAILABLE")
    ap.add_argument("--no-start", action="store_true", help="create: import NiFi flows but leave them stopped")
    args = ap.parse_args(argv)

    cfg = cfgmod.load(args.env_file)
    rep = status(cfg)
    if args.command == "create":
        _print(rep)
        if rep.blocked:
            print("\nNot creating anything: fix the FAIL rows first.")
            return 1
        print("\nPlan:")
        for h in rep.planned_hubs:
            print(f"  create Data Hub {h['name']}  <- '{h['definition']}'  (billable)")
        print(f"  ensure topic {cfg.topic}, table {cfg.lake_catalog}.{cfg.database}.{cfg.table}, "
              f"NiFi context {cfg.parameter_context} + 6 flows"
              + ("" if args.no_start else " (started once Kafka is up)"))
        if not args.yes:
            print("\nDry run. Re-run with --yes to apply.")
            return 0
        print()
        rc = create_hubs(cfg, rep, args.wait) if rep.planned_hubs else 0
        if rc:
            return rc
        if rep.planned_hubs:
            rep = status(cfg)          # refresh: hubs we just waited for are now AVAILABLE
        return deploy_data_plane(cfg, rep, start_flows=not args.no_start)
    if args.json:
        print(json.dumps({"rows": rep.rows, "gateway_env": rep.gateway_env}, indent=2))
    else:
        _print(rep)
    return 1 if rep.blocked else 0


if __name__ == "__main__":
    sys.exit(main())
