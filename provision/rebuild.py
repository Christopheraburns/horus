"""Rebuild a flow's rows in the events table from the bronze table (burndown 17.6).

After a NiFi script bug is fixed (in nifi/scripts/ and pushed to NiFi with
``update-scripts``), the rows it wrote are wrong for good, unless the responses
they came from are still in ``raw_responses``. This reruns the flow's current
script over those responses and replaces that flow's rows:

1. **Read** the flow's raw responses for the days asked for, oldest first.
2. **Replay** them through the script (nifi/replay/Replay.groovy, plain Java and
   Groovy): each response's received time stands in for the clock, and state
   carries from one response to the next, as in NiFi.
3. **Stage** the envelopes in ``<db>.events_rebuild`` and derive every column with
   the backfill SQL the v2 migration uses (migrate_lake.backfill_select, tested to
   match the Flink job), keeping the first row per ``obs_hash``, as Flink does,
   and dropping any whose ``obs_hash`` is already in ``events`` outside the window.
4. **Replace**: delete the flow's rows captured inside the window, insert the new.

The window is never earlier than the flow's first raw response (rows from before
raw capture began have nothing to rebuild from and are left alone) and never
reaches today (the live job is still writing it). Rows are matched to a flow by
``source_provider`` and to the window by ``captured_at``, which NiFi sets as the
response arrives. Rebuilt rows carry ``ingest_run_id`` ``rebuild-<flow>-<time>``.

Every step is safe to re-run: the raw rows don't change, the stage is rebuilt,
and the delete covers anything a failed run inserted. Dry run by default.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

import lake
import migrate_lake

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPLAY = os.path.join(ROOT, "nifi", "replay", "Replay.groovy")
SCRIPTS = os.path.join(ROOT, "nifi", "scripts")

# Flow (the raw Kafka key, raw_capture.FLOW_KEYS) -> its script and the
# source_provider values its rows carry (check: nifi/test/run.sh output).
FLOWS: Dict[str, dict] = {
    "usgs": {"script": "earthquakes-usgs", "providers": ["USGS"]},
    "firms": {"script": "fires-firms", "providers": ["NASA-FIRMS"]},
    "opensky": {"script": "flights-opensky", "providers": ["opensky"]},
    "adsblol": {"script": "flights-adsblol", "providers": ["adsb.lol"]},
    "aisstream": {"script": "vessels-aisstream", "providers": ["aisstream.io"]},
    "hormuznow": {"script": "vessels-hormuz", "providers": ["hormuz.now"]},
    "eonet": {"script": "weather-eonet", "providers": ["NASA EONET", "NASA-EONET"]},
    "nws": {"script": "weather-nws", "providers": ["NOAA/NWS"]},
}
STAGE = "events_rebuild"
GROOVY_VERSION = "4.0.24"
GROOVY_JARS = ("groovy", "groovy-json")
# Trino's default query.max-length is 1,000,000 characters; stay well under it.
MAX_INSERT_CHARS = 600_000


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def groovy_classpath(log=print) -> str:
    """The Groovy jars: GROOVY_JARS_DIR if set (an air-gapped mirror), else a cached
    download from Maven Central."""
    d = os.environ.get("GROOVY_JARS_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "horus", "groovy")
    os.makedirs(d, exist_ok=True)
    paths = []
    for a in GROOVY_JARS:
        p = os.path.join(d, f"{a}-{GROOVY_VERSION}.jar")
        if not os.path.exists(p):
            if os.environ.get("GROOVY_JARS_DIR"):
                raise RuntimeError(f"rebuild: {p} missing (GROOVY_JARS_DIR)")
            url = (f"https://repo1.maven.org/maven2/org/apache/groovy/{a}/{GROOVY_VERSION}/"
                   f"{a}-{GROOVY_VERSION}.jar")
            log(f"rebuild: downloading {a} {GROOVY_VERSION} to {d}")
            with urllib.request.urlopen(url, timeout=120) as r, open(p + ".part", "wb") as f:
                shutil.copyfileobj(r, f)
            os.replace(p + ".part", p)
        paths.append(p)
    return os.pathsep.join(paths)


def replay(script: str, in_path: str, out_path: str, run_id: str, log=print,
           runner: Optional[Callable[[List[str]], None]] = None) -> None:
    """Run Replay.groovy. ``runner`` replaces ``java`` (the tests run it in Docker)."""
    path = script if os.path.isabs(script) else os.path.join(SCRIPTS, f"{script}.groovy")
    args = [REPLAY, path, in_path, out_path, run_id]
    if runner:
        runner(args)
        return
    java = shutil.which("java")
    if not java:
        raise RuntimeError("rebuild: no java on PATH (the Workbench runtimes have one)")
    r = subprocess.run([java, "-cp", groovy_classpath(log), "groovy.ui.GroovyMain", *args],
                       capture_output=True, text=True)
    for line in (r.stdout + r.stderr).splitlines():
        if line.strip() and not line.startswith("WARNING"):
            log(f"  {line}")
    if r.returncode:
        raise RuntimeError(f"rebuild: the replay failed (exit {r.returncode})")


def window(run, raw: str, flow: str, first: str, last: str, today: str) -> Optional[tuple]:
    """[start, end) as 'YYYY-MM-DD HH:MM:SS.ffffff' strings, or None if there is no raw
    data for the flow in the days asked for."""
    if last >= today:
        raise ValueError(f"rebuild: {last} is not a finished day (today is {today} UTC; "
                         "the live job is still writing it)")
    if first > last:
        raise ValueError(f"rebuild: --from {first} is after --to {last}")
    end = (date.fromisoformat(last) + timedelta(days=1)).isoformat() + " 00:00:00.000000"
    lo = run(f"SELECT CAST(MIN(received_at) AS VARCHAR) FROM {raw} WHERE flow = {_q(flow)} "
             f"AND received_at < TIMESTAMP '{end}'")[0][0]
    if lo is None:
        return None
    start = max(first + " 00:00:00.000000", lo)
    return (start, end) if start < end else None


def _stage_insert(run, stage: str, payloads) -> int:
    """Insert envelopes (any iterable, read lazily) in statements under MAX_INSERT_CHARS."""
    batch, size, n = [], 0, 0
    for p in payloads:
        n += 1
        v = f"({_q(p)})"
        if batch and size + len(v) > MAX_INSERT_CHARS:
            run(f"INSERT INTO {stage} (payload) VALUES {','.join(batch)}")
            batch, size = [], 0
        batch.append(v)
        size += len(v) + 1
    if batch:
        run(f"INSERT INTO {stage} (payload) VALUES {','.join(batch)}")
    return n


def _hours(start: str, end: str):
    """[start, end) in steps of at most an hour, so one read never holds a whole day
    of aisstream (about 4 M messages) in memory."""
    t = datetime.strptime(start[:19], "%Y-%m-%d %H:%M:%S")
    stop = datetime.strptime(end[:19], "%Y-%m-%d %H:%M:%S")
    while t < stop:
        nxt = min(t.replace(minute=0, second=0) + timedelta(hours=1), stop)
        yield (t.strftime("%Y-%m-%d %H:%M:%S") + start[19:] if t.strftime("%Y-%m-%d %H:%M:%S") == start[:19]
               else t.strftime("%Y-%m-%d %H:%M:%S.000000"), nxt.strftime("%Y-%m-%d %H:%M:%S.000000"))
        t = nxt


def _stage_rows(stage: str) -> str:
    """The stage's envelopes as the v1-shaped rows backfill_select reads."""
    p = migrate_lake._p
    return f"""(SELECT payload,
    CAST(NULL AS VARCHAR) AS event_id,
    CAST(NULL AS VARCHAR) AS source_provider,
    CAST(NULL AS BIGINT) AS schema_version,
    {p('$.entity.id')} AS asset_id,
    {p('$.entity.entityType')} AS asset_type,
    TRY_CAST({p('$.entity.position.lat')} AS DOUBLE) AS lat,
    TRY_CAST({p('$.entity.position.lng')} AS DOUBLE) AS lon,
    CAST(NULL AS TIMESTAMP(6)) AS event_time,
    {p('$.captured_at')} AS captured_at,
    CAST(localtimestamp AS TIMESTAMP(6)) AS ingest_time,
    {p('$.entity.source.feed')} AS source_feed,
    TRY_CAST({p('$.entity.source.confidence')} AS DOUBLE) AS source_confidence,
    {p('$.trace_id')} AS trace_id,
    {p('$.ingest_run_id')} AS ingest_run_id
  FROM {stage})"""


def rebuilt_select(stage: str, events: str, providers: List[str], start: str, end: str) -> str:
    """The rows to insert: derived as the Flink job would, first per obs_hash, none whose
    obs_hash is in events outside the window being replaced."""
    keep = (f"source_provider IN ({', '.join(_q(p) for p in providers)}) "
            f"AND captured_at >= TIMESTAMP '{start}' AND captured_at < TIMESTAMP '{end}'")
    where = "asset_id IS NOT NULL AND lat IS NOT NULL AND lon IS NOT NULL"
    cols = ", ".join(migrate_lake.COLUMN_NAMES)
    return f"""SELECT {cols} FROM (
  SELECT d.*, ROW_NUMBER() OVER (PARTITION BY obs_hash ORDER BY captured_at, ingest_time) AS rn
  FROM ({migrate_lake.backfill_select(_stage_rows(stage), where)}) d
  WHERE event_time IS NOT NULL
) x
WHERE rn = 1
  AND obs_hash NOT IN (SELECT obs_hash FROM {events}
                       WHERE obs_hash IS NOT NULL AND NOT COALESCE({keep}, false))"""


def rebuild(run: Callable[[str], list], catalog: str, database: str, table: str, flow: str,
            first: str, last: str, apply: bool, log=print, today: Optional[str] = None,
            runner: Optional[Callable[[List[str]], None]] = None, workdir: Optional[str] = None) -> dict:
    if flow not in FLOWS:
        raise ValueError(f"rebuild: unknown flow {flow!r}; one of {', '.join(FLOWS)}")
    spec = FLOWS[flow]
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fq = f"{catalog}.{database}"
    raw, events, stage = f"{fq}.{lake.RAW_TABLE}", f"{fq}.{table}", f"{fq}.{STAGE}"
    w = window(run, raw, flow, first, last, today)
    if w is None:
        log(f"rebuild: no raw responses for {flow} from {first} to {last}; nothing to do")
        return {"window": None}
    start, end = w
    providers = spec["providers"]
    in_window = (f"source_provider IN ({', '.join(_q(p) for p in providers)}) "
                 f"AND captured_at >= TIMESTAMP '{start}' AND captured_at < TIMESTAMP '{end}'")
    n_raw = run(f"SELECT COUNT(*) FROM {raw} WHERE flow = {_q(flow)} AND received_at >= TIMESTAMP '{start}' "
                f"AND received_at < TIMESTAMP '{end}'")[0][0]
    n_old = run(f"SELECT COUNT(*) FROM {events} WHERE {in_window}")[0][0]
    log(f"rebuild: {flow} ({', '.join(providers)}), captured {start[:19]} to {end[:19]} UTC: "
        f"{n_raw} raw responses; {n_old} rows in {table} now")

    # 1-2. Read and replay.
    tmp = workdir or tempfile.mkdtemp(prefix="horus-rebuild-")
    in_path, out_path = os.path.join(tmp, "raw.jsonl"), os.path.join(tmp, "envelopes.jsonl")
    with open(in_path, "w", encoding="utf-8") as f:
        for h0, h1 in _hours(start, end):
            for ms, url, status, ctype, body in run(
                    f"SELECT CAST(to_unixtime(with_timezone(received_at, 'UTC')) * 1000 AS BIGINT), source_url, "
                    f"http_status, content_type, body FROM {raw} WHERE flow = {_q(flow)} "
                    f"AND received_at >= TIMESTAMP '{h0}' AND received_at < TIMESTAMP '{h1}' "
                    f"ORDER BY received_at, kafka_partition, kafka_offset"):
                if status is not None and not 200 <= status < 300:
                    continue   # a failed fetch: NiFi routed it to failure, not to the script
                f.write(json.dumps({"received_ms": ms, "attrs": {"invokehttp.request.url": url,
                                                                 "mime.type": ctype}, "body": body}) + "\n")
    run_id = f"rebuild-{flow}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    replay(spec["script"], in_path, out_path, run_id, log, runner)

    # 3. Stage and derive.
    run(f"DROP TABLE IF EXISTS {stage}")
    run(f"CREATE TABLE {stage} (payload VARCHAR) WITH (format = 'PARQUET', format_version = 2)")
    with open(out_path, encoding="utf-8") as f:
        n_env = _stage_insert(run, stage, (l.rstrip("\n") for l in f if l.strip()))
    select = rebuilt_select(stage, events, providers, start, end)
    n_new = run(f"SELECT COUNT(*) FROM ({select})")[0][0]
    log(f"rebuild: {n_env} envelopes -> {n_new} rows (first per obs_hash, none already outside the window)")
    result = {"window": (start, end), "raw": n_raw, "old": n_old, "new": n_new, "run_id": run_id}
    if not apply:
        run(f"DROP TABLE IF EXISTS {stage}")
        log(f"rebuild: would replace {n_old} rows with {n_new}")
        return result

    # 4. Replace.
    run(f"DELETE FROM {events} WHERE {in_window}")
    run(f"INSERT INTO {events} ({', '.join(migrate_lake.COLUMN_NAMES)}) {select}")
    run(f"DROP TABLE IF EXISTS {stage}")
    n_after = run(f"SELECT COUNT(*) FROM {events} WHERE {in_window}")[0][0]
    log(f"rebuild: replaced {n_old} rows with {n_after} (ingest_run_id {run_id})")
    result["after"] = n_after
    if not workdir:
        shutil.rmtree(tmp, ignore_errors=True)
    return result
