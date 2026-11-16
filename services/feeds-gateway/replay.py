"""Lakehouse replay: feed the gateway's store from Iceberg instead of Kafka.

While the gateway is in LAKEHOUSE mode this task reads a recorded window of
``events_iceberg`` through Impala in small time-ordered chunks and pushes each
stored canonical message through the same reshape/route path the Kafka consumer
uses. Events are released at their original cadence (times REPLAY_SPEED) and the
window loops, so an air-gapped demo shows a moving picture with no NiFi, no Kafka
traffic and no internet.

Environment:
    REPLAY_HOURS          how much of the lake to replay, counted back from the
                          newest event (default 3)
    REPLAY_SPEED          playback multiplier (default 1.0)
    REPLAY_CHUNK_SECONDS  event-time span fetched per Impala query (default 60)
    REPLAY_CHUNK_LIMIT    max rows per query (default 50000)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import history
from consumer import FeedStore, _ingest_record
from mode import SourceMode

log = logging.getLogger("feeds-gateway.replay")

REPLAY_HOURS = float(os.environ.get("REPLAY_HOURS", "3"))
REPLAY_SPEED = max(0.01, float(os.environ.get("REPLAY_SPEED", "1.0")))
CHUNK_MS = int(float(os.environ.get("REPLAY_CHUNK_SECONDS", "60")) * 1000)
CHUNK_LIMIT = int(os.environ.get("REPLAY_CHUNK_LIMIT", "50000"))

status: dict[str, Any] = {
    "state": "idle",        # idle | loading | playing | error
    "window_start": None,   # epoch ms
    "window_end": None,
    "position": None,       # epoch ms of the event time currently being replayed
    "loops": 0,
    "rows": 0,
    "skipped": 0,
    "error": None,
}


def _record_from_row(row: dict) -> dict | None:
    """Stored payload -> canonical record; rebuild from columns if it isn't one."""
    rec: Any = None
    raw = row.get("payload")
    if raw:
        try:
            rec = json.loads(raw)
        except (ValueError, TypeError):
            rec = None
    if isinstance(rec, dict) and isinstance(rec.get("entity"), dict):
        return rec
    if row.get("lat") is None or row.get("lng") is None:
        return None
    flat = rec if isinstance(rec, dict) else {}
    t = row.get("t")
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t / 1000)) if t else None
    return {
        "source": row.get("source_feed"),
        "entity": {
            "id": row.get("asset_id"),
            "name": flat.get("name") or row.get("asset_id"),
            "entityType": row.get("asset_type"),
            "position": {"lat": row.get("lat"), "lng": row.get("lng")},
            "timestamp": ts,
            "source": {"feed": row.get("source_feed"), "originalId": row.get("asset_id")},
            "properties": {k: v for k, v in flat.items() if k != "name"},
        },
    }


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def _play_window(store: FeedStore, mode: SourceMode, stop: asyncio.Event) -> None:
    status.update(state="loading", error=None)
    b = await asyncio.to_thread(history.bounds, True)
    end = b.get("max_time")
    if not end:
        raise RuntimeError("the lake is empty -- nothing to replay")
    start = max(int(b.get("min_time") or 0), int(end) - int(REPLAY_HOURS * 3_600_000))
    end = int(end) + 1  # half-open upper bound must include the newest event
    status.update(window_start=start, window_end=end, position=start)

    await store.clear()
    counter = [0]
    wall0 = time.monotonic()
    cursor = start
    status["state"] = "playing"
    while cursor < end and not stop.is_set() and not mode.is_live():
        chunk_end = min(cursor + CHUNK_MS, end)
        rows = await asyncio.to_thread(history.payload_window, cursor, chunk_end, CHUNK_LIMIT)
        for row in rows:
            if stop.is_set() or mode.is_live():
                return
            t = row.get("t") or cursor
            # Release each event when its offset into the window comes due.
            delay = (t - start) / 1000.0 / REPLAY_SPEED - (time.monotonic() - wall0)
            if delay > 0:
                await _sleep(stop, delay)
                if stop.is_set() or mode.is_live():  # switched while waiting
                    return
            rec = _record_from_row(row)
            if rec is None:
                status["skipped"] += 1
                continue
            try:
                await _ingest_record(store, rec, counter)
                await store.mark_message()
                status["rows"] += 1
            except Exception as exc:  # noqa: BLE001
                status["skipped"] += 1
                log.debug("replay reshape error: %s", exc)
            status["position"] = t
        if len(rows) >= CHUNK_LIMIT and rows[-1].get("t") and rows[-1]["t"] > cursor:
            cursor = rows[-1]["t"]  # chunk was truncated -- resume from its last event
        else:
            cursor = chunk_end
    # Hold until wall-clock reaches the end of the window before looping.
    remaining = (end - start) / 1000.0 / REPLAY_SPEED - (time.monotonic() - wall0)
    if remaining > 0 and not mode.is_live():
        await _sleep(stop, min(remaining, 5.0))


async def replay_loop(store: FeedStore, mode: SourceMode, stop: asyncio.Event) -> None:
    """Run for the life of the app; only active while mode is LAKEHOUSE."""
    while not stop.is_set():
        if mode.is_live():
            if status["state"] != "idle":
                status.update(state="idle", position=None)
            await _sleep(stop, 0.25)
            continue
        if not history.configured():
            status.update(state="error", error="history not configured (set HIVE_* env vars)")
            await _sleep(stop, 10.0)
            continue
        try:
            await _play_window(store, mode, stop)
            if not mode.is_live():
                status["loops"] += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("lakehouse replay failed: %s", exc)
            status.update(state="error", error=str(exc))
            await _sleep(stop, 10.0)
