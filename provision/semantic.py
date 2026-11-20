"""Helios over the Horus lake (burndown O0b, and the start of O0c).

The Horus semantic model, ``horus_lake``, is Horus product content: built once by
harvesting, profiling and proposing over the typed views (lake.VIEWS, in
``horus_<instance>_views``), reviewed by a person, and committed under
``semantic/horus_lake/``. Customers get the reviewed model; they don't harvest it.

This module writes an instance's Helios settings from the Horus configuration (the
same Trino the gateway uses, the same Mistral endpoint) and runs the stages through
Helios's own library:

    python provision/horus.py model-propose      # harvest, profile, propose; writes the proposal for review
    python provision/horus.py model-publish      # publish with semantic/horus_lake/review.json, export model.yaml

Everything goes through the ``helios`` command, exactly as any Helios user would run
it; what Horus adds is only its configuration. Secrets are never written to the settings file: the Trino password and the Mistral
key reach Helios as HELIOS_* and MISTRAL_* environment variables of the process.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "semantic", "horus_lake")
MODEL_ID = "horus_lake"
SOURCE_ID = "lake"
CONNECTION = "lake"
# Helios pinned to a commit, installed from git into the session (O0c bakes it into the runtime).
HELIOS_REPO = "https://github.com/Christopheraburns/helios"
HELIOS_COMMIT = "6c3ad39"   # Track H to H.10 (Mistral reasoning models)
HELIOS_PACKAGES = (("helios-cortex", "[trino,llm]"), ("helios-model", ""))


def pip_requirements(commit: str = HELIOS_COMMIT) -> list:
    return [f"{name}{extras} @ git+{HELIOS_REPO}@{commit}#subdirectory=packages/{name}"
            for name, extras in HELIOS_PACKAGES]


def settings_toml(data_dir: str, host: str, port: int, catalog: str, schema: str, user: str,
                  http_scheme: str = "https", llm_model: Optional[str] = None) -> str:
    """helios.toml for one instance. No secrets: see env()."""
    llm = f'\n[llm]\nprovider = "mistral"\nmodel = "{llm_model}"\ntimeout_seconds = 180\n' if llm_model else ""
    return f'''# Written by provision/semantic.py for this Horus instance; regenerated on each run.
data_dir = "{data_dir}"

[connections.{CONNECTION}]
engine = "trino"
identity = "service"
host = "{host}"
port = {port}
catalog = "{catalog}"
schema = "{schema}"
user = "{user}"
http_scheme = "{http_scheme}"
{llm}'''


def env(password: Optional[str], llm_key: Optional[str], llm_base_url: Optional[str]) -> Dict[str, str]:
    """The secrets, as the environment of the Helios process."""
    out = {}
    if password:
        out[f"HELIOS_CONNECTIONS__{CONNECTION.upper()}__PASSWORD"] = password
    if llm_key:
        out["MISTRAL_API_KEY"] = llm_key
        out["LLM_PROVIDER"] = "mistral"
        if llm_base_url:
            out["MISTRAL_BASE_URL"] = llm_base_url.rstrip("/")
    return out


def helios(config: str, *args: str, extra_env: Optional[Dict[str, str]] = None, check: bool = True):
    """Run the helios CLI (installed in this Python) with ``config``."""
    cmd = [sys.executable, "-m", "helios_cortex.cli", "--config", config, *args]
    return subprocess.run(cmd, env={**os.environ, **(extra_env or {})}, check=check,
                          capture_output=True, text=True)


def register(config: str, extra_env: Dict[str, str], views_db: str, log=print) -> None:
    """The registry, the data source and the model (each only once)."""
    for args in (("registry", "upgrade"),
                 ("source", "add", SOURCE_ID, "--connection", CONNECTION, "--name", "Horus lake (typed views)"),
                 ("model", "add", MODEL_ID, "--name", "Horus lake", "--source", SOURCE_ID,
                  "--description", f"Horus's observations, typed per kind of thing ({views_db})")):
        r = helios(config, *args, extra_env=extra_env, check=False)
        out = (r.stdout + r.stderr).strip()
        if r.returncode and "already" not in out.lower() and "exists" not in out.lower():
            raise RuntimeError(f"helios {' '.join(args[:2])}: {out[-400:]}")
        log(f"helios: {' '.join(args[:2])}: {'ok' if not r.returncode else 'already there'}")


def _stage(config: str, extra_env: Dict[str, str], log, *args: str) -> list:
    """One helios command; returns its stdout lines (the run id first, for the stages)."""
    r = helios(config, *args, extra_env=extra_env, check=False)
    for line in r.stderr.splitlines():
        if line.strip() and not line.startswith("WARNING"):
            log(f"  {line}")
    if r.returncode:
        raise RuntimeError(f"helios {args[0]} failed: {(r.stderr or r.stdout).strip()[-600:]}")
    return r.stdout.splitlines()


def propose(config: str, extra_env: Dict[str, str], views_db: str, log=print) -> str:
    """Harvest, profile and propose over the typed views with the helios commands, as any
    Helios user would, and write the proposal for review. Returns the run id."""
    register(config, extra_env, views_db, log)
    out = _stage(config, extra_env, log, "harvest", "--source", SOURCE_ID, "--database", views_db, "--model", MODEL_ID)
    run_id = out[0].strip()
    log(f"helios: {out[-1]} (run {run_id})")
    log(f"helios: {_stage(config, extra_env, log, 'profile', '--run', run_id)[-1]}")
    log(f"helios: {_stage(config, extra_env, log, 'propose', '--run', run_id)[-1]}")
    os.makedirs(MODEL_DIR, exist_ok=True)
    _stage(config, extra_env, log, "proposal", "show", "--run", run_id, "--out", os.path.join(MODEL_DIR, "PROPOSAL.md"))
    _stage(config, extra_env, log, "proposal", "show", "--run", run_id, "--format", "json",
           "--out", os.path.join(MODEL_DIR, "proposal.json"))
    with open(os.path.join(MODEL_DIR, "RUN"), "w") as f:
        f.write(run_id + "\n")
    log("helios: proposal written to semantic/horus_lake/ (PROPOSAL.md, proposal.json, RUN)")
    return run_id


def publish(config: str, extra_env: Dict[str, str], publisher: str, log=print) -> None:
    """Publish the run in semantic/horus_lake/RUN with the decisions in review.json, and
    export the published model to model.yaml."""
    run_id = open(os.path.join(MODEL_DIR, "RUN")).read().strip()
    review = os.path.join(MODEL_DIR, "review.json")
    if not os.path.exists(review):
        raise RuntimeError("semantic/horus_lake/review.json is missing: review the proposal first")
    for line in _stage(config, extra_env, log, "publish", "--run", run_id, "--review", review, "--as", publisher):
        log(f"helios: {line}")
    _stage(config, extra_env, log, "model", "export", MODEL_ID, "--out", os.path.join(MODEL_DIR, "model.yaml"))
    log("helios: exported to semantic/horus_lake/model.yaml")


def instance_config(instance: str, host: str, port: int, catalog: str, database: str, user: str,
                    llm_model: Optional[str]) -> str:
    """Write this instance's helios.toml (in ~/helios-data/<instance>; O0c moves the store
    to the bucket) and return its path."""
    import lake
    data_dir = os.path.join(os.path.expanduser("~"), "helios-data", instance)
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "helios.toml")
    with open(path, "w") as f:
        f.write(settings_toml(data_dir, host, port, catalog, lake.views_database(database), user,
                              llm_model=llm_model))
    return path
