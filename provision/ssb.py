"""Deploy the Horus Flink jobs through SQL Stream Builder (REST v2).

Three jobs, one SQL template each: ssb/02_kafka_to_iceberg.sql (the lakehouse
writer), ssb/04_detections.sql (alerts to the alerts topic) and
ssb/05_raw_to_iceberg.sql (raw responses to the bronze table, burndown 17).

Talks to the Streaming Analytics Data Hub's Knox ``cdp-proxy-api`` SSB endpoint
with the workload user's basic-auth credentials. Idempotent: the project and
the job are each created only if missing, and a running job is
left alone.
"""
from __future__ import annotations

import os
import re
import time
from typing import Dict, Optional

import requests

SSB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ssb")
SQL_TEMPLATE = os.path.join(SSB_DIR, "02_kafka_to_iceberg.sql")
DETECTIONS_TEMPLATE = os.path.join(SSB_DIR, "04_detections.sql")
RAW_TEMPLATE = os.path.join(SSB_DIR, "05_raw_to_iceberg.sql")
HEALTHY = ("INITIALIZING", "CREATED", "RUNNING", "RESTARTING", "RECONCILING")


class SsbError(RuntimeError):
    pass


class SSB:
    def __init__(self, api_url: str, user: str, password: str, verify: object = True, timeout: int = 120):
        self.base = api_url.rstrip("/") + "/api/v2"
        self.s = requests.Session()
        self.s.auth = (user, password)
        self.s.verify = verify
        self.timeout = timeout

    def _req(self, method: str, path: str, **kw):
        r = self.s.request(method, self.base + path, timeout=self.timeout, **kw)
        body = r.json() if r.content and "json" in r.headers.get("Content-Type", "") else {}
        if r.status_code >= 400 or (isinstance(body, dict) and (body.get("error") or body.get("error_message"))):
            msg = body.get("error_message") or body.get("error") if isinstance(body, dict) else r.text[:300]
            hint = " -- check the workload password" if r.status_code in (401, 403) else ""
            raise SsbError(f"{method} {path}: HTTP {r.status_code} {msg}{hint}")
        return body

    # -- project -------------------------------------------------------------
    def ensure_project(self, name: str, description: str) -> str:
        for p in self._req("GET", "/projects"):
            if p["name"] == name:
                return p["id"]
        return self._req("POST", "/projects", json={"name": name, "description": description})["id"]

    def execute_sql(self, pid: str, sql: str) -> dict:
        return self._req("POST", f"/projects/{pid}/sql/execute",
                         json={"sql": sql, "add_to_history": False,
                               "job_config": {"job_name": "horus_probe",
                                              "runtime_config": {"execution_mode": "PER_JOB"}}})

    # -- jobs --------------------------------------------------------------------
    def jobs(self, pid: str) -> list:
        return self._req("GET", f"/projects/{pid}/jobs").get("jobs", [])

    def job(self, pid: str, name: str) -> Optional[dict]:
        return next((j for j in self.jobs(pid) if j.get("name") == name), None)

    def state(self, pid: str, job_id: int) -> str:
        return self._req("GET", f"/projects/{pid}/jobs/{job_id}/state").get("state", "?")

    def events(self, pid: str, job_id: int) -> list:
        try:
            return self._req("GET", f"/projects/{pid}/jobs/{job_id}/events") or []
        except SsbError:
            return []

    def submit(self, pid: str, name: str, sql: str, checkpoint_ms: int) -> dict:
        cfg = {"job_name": name,
               "runtime_config": {"execution_mode": "PER_JOB", "parallelism": 1},
               "checkpoint_config": {"enable_checkpointing": True,
                                     "checkpoint_interval_millis": checkpoint_ms,
                                     "checkpoint_mode": "EXACTLY_ONCE"}}
        body = {"sql": sql, "job_config": cfg, "add_to_history": False}
        existing = self.job(pid, name)
        if existing is None:      # create only saves the job; execute starts it
            jid = self._req("POST", f"/projects/{pid}/jobs", json=body)["job_id"]
        else:
            jid = existing["job_id"]
            self._req("PUT", f"/projects/{pid}/jobs/{jid}", json=body)
        self._req("POST", f"/projects/{pid}/jobs/{jid}/execute", json=body)
        return self.job(pid, name) or {"job_id": jid}

    def stop(self, pid: str, job_id: int, savepoint: bool = False, timeout_s: int = 180) -> str:
        self._req("POST", f"/projects/{pid}/jobs/{job_id}/stop", json={"savepoint": savepoint})
        deadline = time.time() + timeout_s
        st = self.state(pid, job_id)
        while st in HEALTHY + ("CANCELLING", "FAILING") and time.time() < deadline:
            time.sleep(5)
            st = self.state(pid, job_id)
        return st

    def unlock_keytab(self, principal: str, password: str) -> None:
        """SSB runs jobs as the user, from a keytab it derives from the workload password.
        A keytab made on an earlier run is kept (SSB answers HTTP 400 "Keytab already exists")."""
        try:
            self._req("POST", "/user/keytab/generate", json={"principal": principal, "password": password})
        except SsbError as e:
            if "already exists" not in str(e).lower():
                raise


def render(values: Dict[str, str], template: str = SQL_TEMPLATE) -> str:
    sql = open(template).read()
    # Drop the comment header: it repeats the tokens and is noise in the SSB editor.
    sql = re.sub(r"\A(--[^\n]*\n|\n)+", "", sql)
    for k, v in values.items():
        sql = sql.replace("{{" + k + "}}", v)
    left = set(re.findall(r"\{\{([A-Z_]+)\}\}", sql))
    if left:
        raise SsbError(f"unfilled tokens in {template}: {sorted(left)}")
    return sql


def deploy(ssb: SSB, project: str, database: str, table: str, job_name: str,
           values: Dict[str, str], checkpoint_ms: int = 60000, log=print,
           template: str = SQL_TEMPLATE) -> Optional[str]:
    """Project, then the job. Returns the job state, or None if not submitted."""
    pid = ssb.ensure_project(project, f"Horus {database}: lakehouse and detection jobs")
    log(f"ssb: project {project} ready ({pid})")

    existing = ssb.job(pid, job_name)
    if existing and ssb.state(pid, existing["job_id"]) in HEALTHY:
        st = ssb.state(pid, existing["job_id"])
        log(f"ssb: job {job_name} already {st}")
        return st

    sql = render(dict(values, JOB_NAME=job_name, PROJECT=project, DATABASE=database), template)
    try:
        job = ssb.submit(pid, job_name, sql, checkpoint_ms)
    except SsbError as e:
        m = re.search(r"s3a://([^/]+)/(\S+?/" + re.escape(database) + r"\.db)/", str(e))
        lake_job = template == SQL_TEMPLATE
        if lake_job and ("Cannot find table" in str(e) or "AccessControl" in str(e)
                         or "Permission denied" in str(e)):
            raise SsbError(
                f"SSB cannot read {database}.{table} from the metastore -- add a Ranger Hadoop SQL policy "
                f"(Data Lake Ranger, service cm_hive): user ssb, all on database {database}, table *, column *") from e
        if "TOPIC_AUTHORIZATION" in str(e) or "TopicAuthorization" in str(e):
            topics = ", ".join(t for t in (values.get("TOPIC"), values.get("ALERTS_TOPIC")) if t)
            raise SsbError(
                f"Flink may not use a Horus topic -- add a Ranger Kafka policy (service cm_kafka): users "
                f"{values.get('KAFKA_USER')} and ssb, Consume/Publish/Describe on topics {topics}") from e
        if m and "Failed to open input stream" in str(e):
            raise SsbError(
                f"Flink cannot read the table files in S3 -- add a Ranger S3 (RAZ) policy: bucket {m.group(1)}, "
                f"path /{m.group(2)} (leading slash, no /*), recursive, users {values.get('KAFKA_USER')} "
                f"and ssb, read+write") from e
        raise
    jid = job.get("job_id")
    log(f"ssb: submitted {job_name} (job {jid})")
    st = "?"
    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(10)
        st = ssb.state(pid, jid)
        if st in ("RUNNING", "FAILED", "CANCELED", "FINISHED"):
            break
    log(f"ssb: job {job_name} {st}")
    if st != "RUNNING":
        for e in ssb.events(pid, jid)[-5:]:
            log(f"ssb:   {str(e)[:400]}")
    return st
