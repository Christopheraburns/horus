#!/usr/bin/env python3
"""Check nifi/test/out/*.jsonl (written by run.sh) against envelope v2.

Every envelope must meet the contract in docs/LAKE-SCHEMA.md; each sample also
has its own expected values. Exits 1 on any failure.
"""
import json
import os
import re
import sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
failures = []


def fail(case, msg):
    failures.append(f"{case}: {msg}")


def num_or_none(v):
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool))


def contract(case, env):
    e = env.get("entity") or {}
    src = e.get("source") or {}
    if env.get("schema_version") != 2:
        fail(case, f"schema_version {env.get('schema_version')}")
    for path, v in (("entity.id", e.get("id")), ("entity.entityType", e.get("entityType")),
                    ("source.provider", src.get("provider")), ("source.originalId", src.get("originalId")),
                    ("source.idScheme", src.get("idScheme"))):
        if not v:
            fail(case, f"{path} missing")
    if not ISO_Z.match(str(e.get("timestamp"))):
        fail(case, f"timestamp not UTC ISO-8601 with Z: {e.get('timestamp')}")
    if not ISO_Z.match(str(env.get("captured_at"))):
        fail(case, f"captured_at not UTC ISO-8601 with Z: {env.get('captured_at')}")
    pos = e.get("position") or {}
    if not all(isinstance(pos.get(k), (int, float)) for k in ("lat", "lng")):
        fail(case, f"position lat/lng not numbers: {pos}")
    if not num_or_none(pos.get("alt")):
        fail(case, f"position.alt not a number or null: {pos.get('alt')}")
    if "releasability" not in e:
        fail(case, "releasability missing")
    if e.get("subtype") is not None and not isinstance(e.get("subtype"), str):
        fail(case, f"subtype not a string: {e.get('subtype')}")
    m = e.get("motion")
    if m is not None:
        if set(m) - {"speedMps", "courseDeg", "headingDeg"}:
            fail(case, f"unexpected motion keys {sorted(m)}")
        if not all(num_or_none(m.get(k)) for k in m):
            fail(case, f"motion values not numbers or null: {m}")
        for k in ("courseDeg", "headingDeg"):
            if m.get(k) is not None and not 0 <= m[k] < 360:
                fail(case, f"motion.{k} out of range: {m[k]}")
        if m.get("speedMps") is not None and m["speedMps"] < 0:
            fail(case, f"motion.speedMps negative: {m['speedMps']}")
    if e.get("geometry") is not None:
        b = e.get("bbox")
        if not (isinstance(b, list) and len(b) == 4 and b[0] <= b[2] and b[1] <= b[3]):
            fail(case, f"geometry without a valid bbox: {b}")
        if not re.match(r"^(MULTI)?POLYGON \(", e["geometry"]):
            fail(case, f"geometry not polygon WKT: {e['geometry'][:40]}")


def expect(case, envs, n, checks):
    if len(envs) != n:
        fail(case, f"{len(envs)} envelopes, expected {n}")
        return
    for i, (path, want) in checks:
        got = envs[i]
        for k in path.split("."):
            got = got.get(k) if isinstance(got, dict) else None
        ok = abs(got - want) < 0.01 if isinstance(want, float) and isinstance(got, (int, float)) else got == want
        if not ok:
            fail(case, f"[{i}] {path} = {got!r}, expected {want!r}")


def load(name):
    path = os.path.join(OUT, f"{name}.jsonl")
    if not os.path.exists(path):
        fail(name, "no output")
        return []
    envs = [json.loads(line) for line in open(path) if line.strip()]
    for env in envs:
        contract(name, env)
    return envs


expect("usgs", load("usgs"), 2, [
    (0, ("entity.position.alt", None)), (0, ("entity.properties.depth", 10.2)),
    (0, ("entity.subtype", "earthquake")), (1, ("entity.subtype", "quarry blast")),
    (0, ("entity.source.idScheme", "usgs")), (0, ("entity.timestamp", "2025-11-19T17:52:00Z")),
])
expect("firms", load("firms"), 2, [
    (0, ("entity.timestamp", "2025-11-19T04:12:00Z")), (0, ("entity.source.idScheme", "firms")),
    (0, ("entity.subtype", "satellite-detection")),
])
expect("opensky", load("opensky"), 2, [
    (0, ("entity.motion.speedMps", 231.5)), (0, ("entity.motion.courseDeg", 92.3)),
    (0, ("entity.motion.headingDeg", None)), (0, ("entity.subtype", "commercial")),
    (1, ("entity.subtype", "military")), (0, ("entity.source.idScheme", "icao24")),
    (0, ("entity.timestamp", "2025-11-19T18:01:55Z")),
])
expect("adsblol", load("adsblol"), 2, [
    (0, ("entity.timestamp", "2025-11-19T18:01:57Z")), (0, ("entity.motion.speedMps", 231.6)),
    (0, ("entity.motion.courseDeg", 95.5)), (0, ("entity.motion.headingDeg", 97.0)),
    (0, ("entity.source.idScheme", "icao24")), (1, ("entity.source.idScheme", "adsb.lol")),
    (1, ("entity.timestamp", "2025-11-19T18:01:50Z")), (1, ("entity.motion.courseDeg", None)),
    (0, ("entity.properties.heading", 96)),
])
expect("aisstream_position", load("aisstream_position"), 1, [
    (0, ("entity.timestamp", "2025-11-19T18:01:58Z")), (0, ("entity.motion.speedMps", 6.43)),
    (0, ("entity.motion.courseDeg", 112.0)), (0, ("entity.motion.headingDeg", 110.0)),
    (0, ("entity.position.alt", None)), (0, ("entity.source.idScheme", "mmsi")),
    (0, ("entity.properties.sog", 12.5)),
])
expect("aisstream_unavailable", load("aisstream_unavailable"), 1, [
    (0, ("entity.motion.speedMps", None)), (0, ("entity.motion.courseDeg", None)),
    (0, ("entity.motion.headingDeg", None)),
])
expect("aisstream_static", load("aisstream_static"), 1, [
    (0, ("entity.subtype", "tanker")), (0, ("entity.motion", None)),
    (0, ("entity.timestamp", "2025-11-19T18:00:10Z")),
])
expect("hormuz", load("hormuz"), 2, [
    (0, ("entity.source.idScheme", "mmsi")), (0, ("entity.motion.headingDeg", None)),
    (0, ("entity.motion.courseDeg", 45.0)), (0, ("entity.properties.heading", 45.0)),
    (0, ("entity.motion.speedMps", 4.63)), (0, ("entity.subtype", "tanker")),
    (1, ("entity.id", "hormuz.now:h-2002")), (1, ("entity.source.idScheme", "hormuz.now")),
    (1, ("entity.motion.headingDeg", 200.0)), (1, ("entity.motion.courseDeg", None)),
])
eonet = load("eonet")
expect("eonet", eonet, 3, [
    (0, ("entity.subtype", "volcanoes")), (1, ("entity.subtype", "volcano")),
    (1, ("entity.entityType", "FIRE")), (2, ("entity.subtype", "severeStorms")),
    (0, ("entity.source.idScheme", "eonet")), (1, ("entity.source.idScheme", "eonet")),
])
if len(eonet) == 3:
    ids = {f"{e['entity']['source']['provider']}:{e['entity']['source']['originalId']}" for e in eonet[:2]}
    if len(ids) != 2:
        fail("eonet", f"volcano weather and fire rows share an event_id: {ids}")
expect("nws", load("nws"), 2, [
    (0, ("entity.timestamp", "2025-11-19T23:00:00Z")), (0, ("entity.bbox", [-97.0, 35.0, -96.0, 36.0])),
    (0, ("entity.source.idScheme", "nws")), (1, ("entity.geometry", None)), (1, ("entity.bbox", None)),
    (1, ("entity.timestamp", "2025-11-19T17:00:00Z")),
])

if failures:
    print("\n".join(f"FAIL {f}" for f in failures))
    sys.exit(1)
print("envelope v2: all checks passed")
