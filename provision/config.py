"""Horus deployment settings, read from the environment (and an optional .env).

Real environment variables win over .env, so Workbench project variables always
take precedence over a file someone left in the project.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

INSTANCE_RE = re.compile(r"^[a-z][a-z0-9]{1,11}$")


def load_dotenv(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name, "").strip()
    return val or default


@dataclass
class Config:
    instance: str
    environment: str
    kafka_datahub: str
    kafka_definition: Optional[str]      # None -> pick to match the Data Lake runtime
    flink_datahub: str
    flink_definition: Optional[str]
    nifi_datahub: str
    lake_vw: Optional[str]               # CDW virtual warehouse (Impala or Trino)
    workbench: Optional[str]
    workload_user: Optional[str]
    workload_password: Optional[str] = field(repr=False, default=None)
    aisstream_api_key: Optional[str] = field(repr=False, default=None)
    http_contact: Optional[str] = None
    opensky_client_id: Optional[str] = None
    opensky_client_secret: Optional[str] = field(repr=False, default=None)
    enable_opensky: bool = False
    lake_catalog: str = "iceberg"
    problems: List[str] = field(default_factory=list)

    # Names derived from the instance -- one place, so teams never collide.
    @property
    def topic(self) -> str:
        return f"horus-{self.instance}-events"

    @property
    def database(self) -> str:
        return f"horus_{self.instance}"

    @property
    def table(self) -> str:
        return "events_iceberg"

    @property
    def parameter_context(self) -> str:
        return f"Horus-{self.instance}"

    @property
    def ssb_project(self) -> str:
        return f"horus_{self.instance}"

    @property
    def flink_job(self) -> str:
        return f"horus_{self.instance}_kafka_to_iceberg"

    @property
    def optional_flows(self) -> frozenset:
        return frozenset(["opensky"] if self.enable_opensky else [])

    @property
    def alerts_topic(self) -> str:
        return f"horus-{self.instance}-alerts"

    @property
    def detections_job(self) -> str:
        return f"horus_{self.instance}_detections"

    @property
    def detections_group(self) -> str:
        return f"horus-{self.instance}-detections"

    @property
    def gateway_group(self) -> str:
        return f"horus-{self.instance}-feeds-gateway"

    @property
    def raw_topic(self) -> str:
        """Every upstream response as received (burndown 17)."""
        return f"horus-{self.instance}-raw"

    @property
    def raw_job(self) -> str:
        return f"horus_{self.instance}_raw_to_iceberg"

    @property
    def raw_group(self) -> str:
        return f"horus-{self.instance}-raw"

    @property
    def maintenance_job(self) -> str:
        return f"horus-{self.instance}-lake-maintenance"

    @property
    def lakehouse_group(self) -> str:
        # "-2": the lake was rebuilt (2026-11-17) by replaying the topic through the
        # deduplicating job under a fresh consumer group. Bump again to re-replay.
        return f"horus-{self.instance}-lakehouse-2"


def load(dotenv_path: str = ".env") -> Config:
    load_dotenv(dotenv_path)
    problems: List[str] = []

    instance = (_env("HORUS_INSTANCE") or "").lower()
    if not INSTANCE_RE.match(instance):
        problems.append(
            "HORUS_INSTANCE must be 2-12 chars, lowercase letters/digits, starting with a letter "
            f"(got {instance!r})")
    environment = _env("HORUS_ENVIRONMENT")
    if not environment:
        problems.append("HORUS_ENVIRONMENT is not set (the CDP environment name)")

    return Config(
        instance=instance,
        environment=environment or "",
        kafka_datahub=_env("HORUS_KAFKA_DATAHUB", f"horus-{instance}-kafka"),
        kafka_definition=_env("HORUS_KAFKA_DEFINITION"),
        flink_datahub=_env("HORUS_FLINK_DATAHUB", f"horus-{instance}-flink"),
        flink_definition=_env("HORUS_FLINK_DEFINITION"),
        nifi_datahub=_env("HORUS_NIFI_DATAHUB", f"horus-{instance}-nifi"),
        lake_vw=_env("HORUS_LAKE_VW") or _env("HORUS_IMPALA_VW"),
        workbench=_env("HORUS_WORKBENCH"),
        workload_user=_env("HORUS_WORKLOAD_USER"),
        workload_password=_env("HORUS_WORKLOAD_PASSWORD"),
        aisstream_api_key=_env("HORUS_AISSTREAM_API_KEY"),
        http_contact=_env("HORUS_HTTP_CONTACT"),
        opensky_client_id=_env("HORUS_OPENSKY_CLIENT_ID"),
        opensky_client_secret=_env("HORUS_OPENSKY_CLIENT_SECRET"),
        enable_opensky=(_env("HORUS_ENABLE_OPENSKY", "0") or "0").lower() in ("1", "true", "yes"),
        lake_catalog=_env("LAKE_CATALOG", "iceberg"),
        problems=problems,
    )
