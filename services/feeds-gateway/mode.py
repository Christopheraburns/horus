"""Source mode for the feeds-gateway: where the live picture comes from.

  live       NiFi pulls the upstream APIs -> Kafka -> this gateway (needs egress
             from NiFi to the feed providers).
  lakehouse  Nothing external. The gateway replays what is already recorded in
             the Iceberg lake (via Impala) into the same in-memory feed store, so
             the UI, MCP tools and intel endpoints behave exactly as in live mode.

Either way the lake itself was populated by NiFi -> Kafka -> Flink. The mode is a
process-wide flag: set the default with GATEWAY_SOURCE_MODE and switch at runtime
with POST /mode.
"""
from __future__ import annotations

import os

LIVE = "live"
LAKEHOUSE = "lakehouse"
MODES = (LIVE, LAKEHOUSE)


class SourceMode:
    def __init__(self, initial: str | None = None) -> None:
        value = (initial or os.environ.get("GATEWAY_SOURCE_MODE") or LIVE).strip().lower()
        self.current = value if value in MODES else LIVE

    def is_live(self) -> bool:
        return self.current == LIVE

    def set(self, value: str) -> str:
        value = (value or "").strip().lower()
        if value not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.current = value
        return self.current
