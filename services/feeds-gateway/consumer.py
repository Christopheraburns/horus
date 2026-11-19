"""Kafka -> in-memory feed store.

A single ``aiokafka`` consumer (run as one uvicorn worker, started from the
FastAPI lifespan) subscribes to the canonical ``horus-events`` topic, reshapes
each record into feed items via the registry, and keeps a TTL keyed snapshot per
feed. The HTTP layer reads the latest snapshot; it never touches Kafka directly.

A coherent in-memory snapshot requires exactly one consumer instance, hence one
uvicorn worker. Scaling out would require a shared store (Redis) -- out of scope.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import ssl
from typing import Any

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError

import db
from registry import ENTITY_TYPE_TO_FEED, FEEDS, RESPONSE_KEY_TO_FEED

log = logging.getLogger("feeds-gateway.consumer")

# Connection is entirely environment-driven -- nothing cluster-specific or secret
# lives in source. On a CDP Public Cloud Streams Messaging Data Hub the brokers
# listen on 9093 with SASL_SSL/PLAIN and the workload user + workload password.
KAFKA_BROKERS = os.environ.get("KAFKA_BROKERS") or os.environ.get("KAFKA_BOOTSTRAP", "")
KAFKA_SECURITY_PROTOCOL = os.environ.get("KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
KAFKA_SASL_MECHANISM = os.environ.get("KAFKA_SASL_MECHANISM", "PLAIN")
KAFKA_USER = os.environ.get("KAFKA_USER")
KAFKA_PASSWORD = os.environ.get("KAFKA_PASSWORD")
KAFKA_CA_FILE = os.environ.get("KAFKA_CA_FILE")  # optional PEM bundle for private CAs
ENTITIES_TOPIC = (
    os.environ.get("KAFKA_TOPIC")
    or "horus-events"
)
# How long an entity stays on the live map after Horus last heard from it.
# Measured from when the gateway received the update (not the report's own
# time), so lakehouse replay ages the same way as live data.
FEED_TTL_SECONDS = float(os.environ.get("FEED_TTL_SECONDS", "3600"))          # default, every feed
# Aircraft move fast: about two adsb.lol cycles (12 min) before one is dropped.
FLIGHT_TTL_SECONDS = float(os.environ.get("FLIGHT_TTL_SECONDS", "1500"))
# Vessels: a moving ship that has gone quiet (usually out of shore-based AIS
# range) is dropped sooner than one at anchor or moored, which barely moves.
VESSEL_TTL_MOVING_SECONDS = float(os.environ.get("VESSEL_TTL_MOVING_SECONDS", "1200"))
VESSEL_TTL_STATIONARY_SECONDS = float(os.environ.get("VESSEL_TTL_STATIONARY_SECONDS", "3600"))
VESSEL_MOVING_KNOTS = float(os.environ.get("VESSEL_MOVING_KNOTS", "1.0"))
GROUP_ID = os.environ.get("KAFKA_GROUP_ID", "horus-feeds-gateway")


def _consumer_kwargs() -> dict:
    """aiokafka connection settings for the configured security protocol."""
    kw: dict[str, Any] = {"security_protocol": KAFKA_SECURITY_PROTOCOL}
    if KAFKA_SECURITY_PROTOCOL in ("SSL", "SASL_SSL"):
        kw["ssl_context"] = ssl.create_default_context(cafile=KAFKA_CA_FILE or None)
    if KAFKA_SECURITY_PROTOCOL.startswith("SASL"):
        if not (KAFKA_USER and KAFKA_PASSWORD):
            raise RuntimeError("KAFKA_USER / KAFKA_PASSWORD must be set for SASL")
        kw.update(
            sasl_mechanism=KAFKA_SASL_MECHANISM,
            sasl_plain_username=KAFKA_USER,
            sasl_plain_password=KAFKA_PASSWORD,
        )
    return kw


class FeedStore:
    """TTL keyed snapshot: feed -> { entity_id: (item, monotonic_ts) }."""

    LOG_THROTTLE_SECONDS = 20.0

    def __init__(self, ttl_seconds: float = FEED_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, dict[str, tuple[dict, float]]] = {
            name: {} for name in FEEDS
        }
        self._lock = asyncio.Lock()
        self._messages = 0
        self._last_message_at: float | None = None
        # Provenance + throttled-logging state (per feed).
        self._provenance: dict[str, dict] = {}
        self._batch_count: dict[str, int] = {}
        self._last_log_at: dict[str, float] = {}

    async def put(self, feed: str, entity_id: str, item: dict) -> None:
        async with self._lock:
            bucket = self._store.setdefault(feed, {})
            if feed == "vessels" and entity_id in bucket:
                item = self._merge_vessel(bucket[entity_id][0], item)
            bucket[entity_id] = (item, time.monotonic())

    # Descriptors only some reports carry; kept until a report replaces them.
    _VESSEL_STATIC_FIELDS = ("imo", "destination", "type", "flag")

    @staticmethod
    def _merge_vessel(prev: dict, new: dict) -> dict:
        """Merge a vessel report into the one already held for its MMSI.

        Vessels are MMSI-keyed and can come from several feeds (aisstream.io,
        hormuz.now). Two rules:

        - Static descriptors (IMO, destination, type, flag) ride only some
          reports -- aisstream sends IMO and destination in ShipStaticData,
          not in the far more frequent PositionReports -- so they are carried
          forward when the incoming report omits them. IMO is the graph join
          key; without this, vessel Deep-Dive intel never resolves.
        - A report older than the one already held (another feed's delayed
          copy) changes nothing it already has: it only fills missing fields and
          adds its feed to ``sources``. Otherwise the newest report wins.
        """
        mmsi = str(new.get("mmsi") or "")
        new_ts, prev_ts = new.get("timestamp"), prev.get("timestamp")
        if isinstance(new_ts, (int, float)) and isinstance(prev_ts, (int, float)) and new_ts < prev_ts:
            merged = dict(prev)
            for key, value in new.items():
                if merged.get(key) in (None, "") and value not in (None, ""):
                    merged[key] = value
        else:
            merged = dict(new)
        for key in FeedStore._VESSEL_STATIC_FIELDS:
            if merged.get(key) in (None, "") and prev.get(key) not in (None, ""):
                merged[key] = prev[key]
        # Don't let a PositionReport's MMSI-fallback name clobber a real name.
        if merged.get("name") in (None, "", mmsi) and prev.get("name") not in (None, "", mmsi):
            merged["name"] = prev["name"]
        sources = dict(prev.get("sources") or {})
        for provider, ts in (new.get("sources") or {}).items():
            sources[provider] = max(ts, sources.get(provider, ts))
        if sources:
            merged["sources"] = sources
        return merged

    async def clear(self) -> None:
        """Drop every snapshot -- used when the source mode switches."""
        async with self._lock:
            for bucket in self._store.values():
                bucket.clear()
            self._provenance.clear()

    async def set_provenance(self, feed: str, prov: dict) -> None:
        async with self._lock:
            self._provenance[feed] = prov

    async def get_provenance(self, feed: str) -> dict:
        async with self._lock:
            return dict(self._provenance.get(feed, {}))

    async def note_ingest(self, feed: str) -> tuple[bool, int]:
        """Increment the per-feed ingest counter; return (should_log, count)."""
        async with self._lock:
            self._batch_count[feed] = self._batch_count.get(feed, 0) + 1
            now = time.monotonic()
            last = self._last_log_at.get(feed, 0.0)
            if now - last >= self.LOG_THROTTLE_SECONDS:
                count = self._batch_count[feed]
                self._batch_count[feed] = 0
                self._last_log_at[feed] = now
                return True, count
            return False, self._batch_count[feed]

    def _ttl_for(self, feed: str, item: dict) -> float:
        """Seconds an entity stays live after its last update (see the *_TTL_* settings)."""
        if feed == "flights":
            return FLIGHT_TTL_SECONDS
        if feed == "vessels":
            speed = item.get("speed")
            moving = isinstance(speed, (int, float)) and speed >= VESSEL_MOVING_KNOTS
            return VESSEL_TTL_MOVING_SECONDS if moving else VESSEL_TTL_STATIONARY_SECONDS
        return self._ttl

    async def items(self, feed: str) -> list[dict]:
        """Live items for a feed, each with ``age_s``: seconds since its last update."""
        now = time.monotonic()
        async with self._lock:
            bucket = self._store.get(feed, {})
            fresh = {k: v for k, v in bucket.items() if now - v[1] <= self._ttl_for(feed, v[0])}
            self._store[feed] = fresh  # opportunistic eviction
            return [{**item, "age_s": int(now - ts)} for item, ts in fresh.values()]

    async def mark_message(self) -> None:
        async with self._lock:
            self._messages += 1
            self._last_message_at = time.time()

    async def stats(self) -> dict:
        async with self._lock:
            return {
                "messages": self._messages,
                "last_message_at": self._last_message_at,
                "counts": {feed: len(bucket) for feed, bucket in self._store.items()},
            }


def _records_from_value(value: Any) -> list[dict]:
    """Flatten a Kafka message value into a list of candidate records."""
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _provenance_of(rec: dict) -> dict:
    """Extract provenance from the canonical envelope (or nested entity.source)."""
    entity = rec.get("entity") if isinstance(rec.get("entity"), dict) else {}
    inner = entity.get("source") if isinstance(entity.get("source"), dict) else {}
    return {
        "ingest_run_id": rec.get("ingest_run_id"),
        "source": rec.get("source") if isinstance(rec.get("source"), str) else inner.get("feed"),
        "captured_at": rec.get("captured_at"),
    }


async def _record_provenance(store: "FeedStore", feed: str, rec: dict) -> None:
    """Save provenance and emit a throttled, durable ingest log row."""
    prov = _provenance_of(rec)
    await store.set_provenance(feed, prov)
    should_log, count = await store.note_ingest(feed)
    if should_log:
        db.log_row(
            "info",
            feed,
            f"ingested {count} {feed} entities from streaming lakehouse",
            ingest_run_id=prov.get("ingest_run_id"),
            data={"feed": feed, "count": count, "source": prov.get("source"),
                  "captured_at": prov.get("captured_at")},
        )


def _feed_for(rec: dict) -> str | None:
    """Resolve which migrated feed a record belongs to.

    Handles the canonical NiFi envelope ({"source", "entity": {...}}), a bare
    entity, and routes by entityType or the source/feed name.
    """
    entity = rec.get("entity") if isinstance(rec.get("entity"), dict) else rec
    entity_type = entity.get("entityType") or entity.get("entity_type")
    feed = ENTITY_TYPE_TO_FEED.get(entity_type) if entity_type else None
    if feed:
        return feed
    # Fall back to the source/feed name on the envelope or entity.source.feed.
    source = rec.get("source")
    if isinstance(source, str) and source in FEEDS:
        return source
    inner = entity.get("source") if isinstance(entity.get("source"), dict) else {}
    feed_name = inner.get("feed")
    if isinstance(feed_name, str) and feed_name in FEEDS:
        return feed_name
    return None


def _entity_id(feed: str, item: dict, counter: list[int]) -> str:
    """Stable store key: id field, or icao24 for flights, else a one-off counter."""
    if item.get("id"):
        return str(item["id"])
    if feed == "flights" and item.get("icao24"):
        return str(item["icao24"])
    cid = counter[0]
    counter[0] += 1
    return str(cid)


async def _ingest_record(store: FeedStore, rec: dict, counter: list[int]) -> None:
    """Route one record to the right feed and store its reshaped item(s)."""
    # Case 1: canonical entity/envelope routed by entityType or source.
    feed_name = _feed_for(rec)
    if feed_name:
        spec = FEEDS[feed_name]
        item = spec.reshape(rec)
        entity_id = _entity_id(feed_name, item, counter)
        await store.put(feed_name, entity_id, item)
        await _record_provenance(store, feed_name, rec)
        return

    # Case 2: feed-shaped envelope, e.g. {"earthquakes": [ {...}, ... ]}.
    for key, fname in RESPONSE_KEY_TO_FEED.items():
        bucket = rec.get(key)
        if isinstance(bucket, list):
            spec = FEEDS[fname]
            for raw in bucket:
                if not isinstance(raw, dict):
                    continue
                item = spec.reshape(raw)
                entity_id = _entity_id(fname, item, counter)
                await store.put(fname, entity_id, item)
            await _record_provenance(store, fname, rec)
            return


async def consume_loop(store: FeedStore, stop: asyncio.Event, mode: Any = None) -> None:
    """Connect (with retry) and consume until ``stop`` is set.

    ``mode`` is the shared SourceMode. Records are only written to the store while
    the gateway is in LIVE mode; in LAKEHOUSE mode the replayer owns the store and
    Kafka records are read and dropped (so the consumer stays warm for the switch
    back, and auto_offset_reset=latest means it resumes at the live edge).
    """
    if not KAFKA_BROKERS:
        log.warning("KAFKA_BROKERS not set -- live mode disabled (lakehouse replay still works)")
        await stop.wait()
        return
    while not stop.is_set():
        try:
            consumer = AIOKafkaConsumer(
                ENTITIES_TOPIC,
                bootstrap_servers=KAFKA_BROKERS,
                group_id=GROUP_ID,
                enable_auto_commit=True,
                auto_offset_reset="latest",
                value_deserializer=lambda b: _safe_json(b),
                **_consumer_kwargs(),
            )
        except Exception as exc:  # noqa: BLE001  bad config -- don't spin
            log.error("kafka consumer misconfigured (%s); retrying in 30s", exc)
            await _wait(stop, 30.0)
            continue
        try:
            await consumer.start()
            log.info("consumer connected brokers=%s topic=%s", KAFKA_BROKERS, ENTITIES_TOPIC)
        except (KafkaConnectionError, OSError) as exc:
            log.warning("kafka unavailable (%s); retrying in 5s", exc)
            await consumer.stop()
            await _wait(stop, 5.0)
            continue

        counter = [0]
        try:
            async for msg in consumer:
                if stop.is_set():
                    break
                if msg.value is None:
                    continue
                if mode is not None and not mode.is_live():
                    continue
                await store.mark_message()
                for rec in _records_from_value(msg.value):
                    try:
                        await _ingest_record(store, rec, counter)
                    except Exception as exc:  # noqa: BLE001
                        log.exception("reshape error: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("consume loop error (%s); reconnecting", exc)
        finally:
            await consumer.stop()
            if not stop.is_set():
                await _wait(stop, 2.0)


def _safe_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
