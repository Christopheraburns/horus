"""Helios over the Horus lake (burndown O0b, and the start of O0c).

The Horus semantic model, ``horus_lake``, is Horus product content: built once by
harvesting, profiling and proposing over the typed views (lake.VIEWS, in
``horus_<instance>_views``), reviewed by a person, and committed under
``semantic/horus_lake/``. Customers get the reviewed model; they don't harvest it.

This module writes an instance's Helios settings from the Horus configuration (the
same Trino the gateway uses, the same Mistral endpoint) and runs the stages through
Helios's own library:

    python provision/horus.py model-propose      # harvest, profile, propose; writes the proposal for review
    python provision/horus.py model-publish      # apply semantic/horus_lake/review.json, publish, export

Secrets are never written to the settings file: the Trino password and the Mistral
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
HELIOS_REPO = "https://github.com/christopheraburns/helios"
HELIOS_COMMIT = "0243ef0"
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


def summarize(proposals, run_id: str) -> str:
    """A proposal as Markdown, for review: one row per element, by section."""
    lines = [f"# Proposed `{MODEL_ID}` (run {run_id})", "",
             "Every element Helios proposed, with its confidence and the LLM's rationale. Decide each in "
             "`review.json` (accept, edit, reject), then `python provision/horus.py model-publish`.", ""]
    by_section: dict = {}
    for p in proposals:
        by_section.setdefault(p.section, []).append(p)
    for section, items in by_section.items():
        lines += [f"## {section.replace('_', ' ').capitalize()} ({len(items)})", "",
                  "| id | confidence | what | rationale |", "|---|---|---|---|"]
        for p in items:
            what = (getattr(p, "description", "") or getattr(p, "expression", "") or getattr(p, "definition", "")
                    or getattr(p, "role", "") or "")
            cell = lambda s, n: str(s or "").replace("\n", " ").replace("|", "\\|")[:n]
            lines.append(f"| `{p.id}` | {p.confidence:.2f} | {cell(what, 180)} | {cell(p.rationale, 220)} |")
        lines.append("")
    return "\n".join(lines)


def propose(config: str, extra_env: Dict[str, str], views_db: str, log=print) -> str:
    """Harvest, profile and propose over the typed views; write the proposal for review.
    Returns the run id."""
    os.environ.update(extra_env)
    from helios_cortex.registry import SqlRegistry
    from helios_cortex.settings import load_settings
    from helios_model import Catalog, Profiler, Proposer

    register(config, extra_env, views_db, log)
    settings = load_settings(config=config)
    source = SqlRegistry.from_settings(settings).data_source(SOURCE_ID)
    harvest = Catalog(settings).harvest(source, None, databases=[views_db], model_id=MODEL_ID)
    log(f"helios: harvested {len(harvest.tables)} views (run {harvest.run_id})")
    profile = Profiler(settings).profile(harvest.run_id, None)
    log(f"helios: profiled: {len(profile.relationships)} relationships verified, "
        f"{len(profile.suggested_relationships)} for the LLM to decide")
    proposals = Proposer(settings).propose(profile)
    log(f"helios: proposed {len(proposals)} elements")
    run_dir = os.path.join(str(settings.runs_dir or os.path.join(settings.data_dir, "runs")), harvest.run_id)
    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(os.path.join(MODEL_DIR, "PROPOSAL.md"), "w") as f:
        f.write(summarize(proposals, harvest.run_id))
    src = os.path.join(run_dir, "propose.json")
    if os.path.exists(src):
        with open(os.path.join(MODEL_DIR, "proposal.json"), "w") as f:
            json.dump(json.load(open(src)), f, indent=1, sort_keys=True)
    with open(os.path.join(MODEL_DIR, "RUN"), "w") as f:
        f.write(harvest.run_id + "\n")
    log("helios: proposal written to semantic/horus_lake/ (PROPOSAL.md, proposal.json, RUN)")
    return harvest.run_id


def publish(config: str, extra_env: Dict[str, str], publisher: str, log=print) -> str:
    """Publish the run in semantic/horus_lake/RUN with the decisions in review.json, and
    export the published model to model.json. Returns the revision id."""
    os.environ.update(extra_env)
    from helios_cortex import Caller
    from helios_cortex.settings import load_settings
    from helios_model import Proposer, Publisher

    run_id = open(os.path.join(MODEL_DIR, "RUN")).read().strip()
    review = os.path.join(MODEL_DIR, "review.json")
    if not os.path.exists(review):
        raise RuntimeError("semantic/horus_lake/review.json is missing: review the proposal first")
    settings = load_settings(config=config)
    run_dir = os.path.join(str(settings.runs_dir), run_id)
    if not os.path.isdir(run_dir):
        raise RuntimeError(f"run {run_id} is not in {settings.runs_dir}: publish where it was proposed")
    with open(os.path.join(run_dir, "review.json"), "w") as f:
        f.write(open(review).read())
    proposals = Proposer(settings).load(run_id)
    pending = [p for p in proposals if p.decision == "pending"]
    if pending:
        log(f"helios: {len(pending)} element(s) still pending are left out: "
            + ", ".join(f"{p.section}:{p.id}" for p in pending[:10]) + (" ..." if len(pending) > 10 else ""))
    publication = Publisher(settings).publish(proposals, Caller(publisher))
    with open(os.path.join(MODEL_DIR, "model.json"), "w") as f:
        json.dump(publication.document, f, indent=1, sort_keys=True)
    log(f"helios: published {MODEL_ID} revision {publication.revision.id}; exported to semantic/horus_lake/model.json")
    return publication.revision.id


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
