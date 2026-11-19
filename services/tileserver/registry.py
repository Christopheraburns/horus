"""The Horus tile-set registry (burndown 8.2): one list of every map layer source.

Format and rules: docs/TILESETS.md. This module only merges and validates; it
reads no files except tilesets.toml. The tile server (8.3) reads each tile
file's own metadata (MBTiles ``metadata`` table, PMTiles header and metadata)
into a plain dict and calls :func:`build`; the UI (8.4) gets :func:`public`.

Standard library only (Python 3.11+ for tomllib), so the tile server's runtime
needs nothing extra.
"""
from __future__ import annotations

import re
import tomllib
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

VERSION = 1
ROLES = ("basemap", "imagery", "overlay")
SCHEMES = ("xyz", "tms", "wmts")
RASTER_FORMATS = ("png", "jpg", "webp")
VECTOR_FORMATS = ("pbf",)
# Stacking: higher draws on top. Within a role, more detailed sets (higher maxzoom)
# go above coarser ones, so a regional layer covers the global one where both exist.
ROLE_ORDER = {"basemap": 0, "imagery": 100, "overlay": 200}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
PLACEHOLDERS = {"xyz": ("{z}", "{x}", "{y}"), "tms": ("{z}", "{x}", "{y}"),
                "wmts": ("{TileMatrix}", "{TileRow}", "{TileCol}")}
MERCATOR_LAT = 85.0511287798


def load_config(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _format(value: Any) -> Optional[str]:
    v = str(value or "").strip().lower()
    return {"jpeg": "jpg", "mvt": "pbf"}.get(v, v) or None


def _bounds(value: Any) -> Optional[list]:
    """MBTiles gives "w,s,e,n" as text; PMTiles readers and TOML give a list."""
    if value is None or value == "":
        return None
    parts = value.split(",") if isinstance(value, str) else list(value)
    try:
        return [float(p) for p in parts]
    except (TypeError, ValueError):
        return parts   # left as is; validation reports it


def _int(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _captured(value: Any) -> Any:
    """ "2021-01-01/2021-12-31" or "2026-03-14" -> {"start", "end"} (end = start for one day)."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        value = value.isoformat()
    text = str(value)
    start, _, end = text.partition("/")
    try:
        s, e = date.fromisoformat(start.strip()), date.fromisoformat((end or start).strip())
    except ValueError:
        return {"invalid": text}
    return {"start": s.isoformat(), "end": e.isoformat()}


def _settings(cfg: dict, table: dict) -> dict:
    """A [tileset]/[url] table over its [defaults.<name>] table, if it names one."""
    merged = dict(cfg.get("defaults", {}).get(table.get("defaults", ""), {}))
    merged.update({k: v for k, v in table.items() if k != "defaults"})
    return merged


def _entry(id_: str, kind: str, meta: dict, s: dict) -> dict:
    """One registry entry: settings (``s``) over the file's own metadata (``meta``)."""
    fmt = _format(s.get("format", meta.get("format")))
    role = s.get("role")
    minzoom = _int(s.get("minzoom", meta.get("minzoom")))
    maxzoom = _int(s.get("maxzoom", meta.get("maxzoom")))
    licence = s.get("licence") or {}
    marking = s.get("marking") or {}
    order = s.get("order")
    if order is None and role in ROLE_ORDER and isinstance(maxzoom, int):
        order = ROLE_ORDER[role] + maxzoom
    return {
        "id": id_,
        "kind": kind,
        "role": role,
        "title": s.get("title") or meta.get("name") or id_,
        "format": fmt,
        "type": "vector" if fmt in VECTOR_FORMATS else "raster" if fmt in RASTER_FORMATS else None,
        "attribution": (s.get("attribution") or meta.get("attribution") or "").strip(),
        "licence": {"id": licence.get("id"), "url": licence.get("url")},
        "marking": {"classification": marking.get("classification"),
                    "releasability": marking.get("releasability")},
        "captured": _captured(s.get("captured")),
        "bounds": _bounds(s.get("bounds", meta.get("bounds"))),
        "minzoom": minzoom,
        "maxzoom": maxzoom,
        "order": order,
    }


def _area(b: list) -> float:
    return (b[2] - b[0]) * (b[3] - b[1])


def validate(e: dict) -> tuple[list, list]:
    """(errors, warnings). An entry with errors is left out of the registry."""
    errors, warnings = [], []
    if not ID_RE.match(e["id"]):
        errors.append("id must be lower case letters, digits, '.', '_' or '-' (at most 64)")
    if e["role"] not in ROLES:
        errors.append(f"role {e['role']!r} is not one of {', '.join(ROLES)}")
    if e["type"] is None:
        errors.append(f"format {e['format']!r} is not one of {', '.join(RASTER_FORMATS + VECTOR_FORMATS)}")
    elif e["role"] == "imagery" and e["type"] != "raster":
        errors.append("imagery must be a raster format")
    if not e["attribution"]:
        errors.append("attribution is required (licences require it on the map)")
    if not e["licence"]["id"]:
        errors.append("licence.id is required")
    if not e["marking"]["classification"]:
        errors.append("marking.classification is required (section 13)")
    b = e["bounds"]
    if not (isinstance(b, list) and len(b) == 4 and all(isinstance(v, float) for v in b)):
        errors.append(f"bounds must be [west, south, east, north], got {b!r}")
    elif not (-180 <= b[0] < b[2] <= 180 and -90 <= b[1] < b[3] <= 90):
        errors.append(f"bounds {b} are not west < east within ±180 and south < north within ±90")
    lo, hi = e["minzoom"], e["maxzoom"]
    if not (isinstance(lo, int) and isinstance(hi, int) and 0 <= lo <= hi <= 24):
        errors.append(f"zooms must be 0 <= minzoom <= maxzoom <= 24, got {lo!r} to {hi!r}")
    if not isinstance(e["order"], int):
        errors.append(f"order must be an integer, got {e['order']!r}")
    cap = e["captured"]
    if cap and "invalid" in cap:
        errors.append(f"captured {cap['invalid']!r} is not YYYY-MM-DD or YYYY-MM-DD/YYYY-MM-DD")
    elif cap and cap["start"] > cap["end"]:
        errors.append("captured starts after it ends")
    elif not cap and e["role"] == "imagery":
        warnings.append("imagery without a capture date can't take part in Time Travel (8.8)")
    src = e.get("source", {})
    if e["kind"] == "url":
        scheme, template = src.get("scheme"), src.get("template") or ""
        if scheme not in SCHEMES:
            errors.append(f"scheme {scheme!r} is not one of {', '.join(SCHEMES)}")
        else:
            missing = [p for p in PLACEHOLDERS[scheme] if p not in template]
            if missing:
                errors.append(f"template lacks {', '.join(missing)} for scheme {scheme}")
        if not template.startswith(("https://", "http://")):
            errors.append("template must be an http(s) URL")
    return errors, warnings


def build(files: Iterable[tuple[str, str, dict]], cfg: dict, now: Optional[datetime] = None) -> dict:
    """The registry from the tile files found and tilesets.toml.

    ``files``: (id, path, metadata) for each tile file in the store, where id is the
    file name without its extension and metadata holds whatever the file says
    (name, format, minzoom, maxzoom, bounds, attribution). Returns
    ``{"version", "generated", "tilesets", "skipped", "warnings"}``; ``skipped`` and
    ``warnings`` are (id, reason) pairs for the log, never for the UI.
    """
    tilesets, skipped, warnings = [], [], []
    configured = cfg.get("tileset", {})
    seen = set()
    for id_, path, meta in files:
        if id_ in seen:
            skipped.append((id_, f"a second file with the same id ({path})"))
            continue
        seen.add(id_)
        if id_ not in configured:
            skipped.append((id_, "no [tileset] table in tilesets.toml (marking and licence unknown)"))
            continue
        e = _entry(id_, "file", meta, _settings(cfg, configured[id_]))
        e["source"] = {"path": path}
        tilesets.append(e)
    for id_ in configured:
        if id_ not in seen:
            warnings.append((id_, "listed in tilesets.toml but no tile file was found"))
    for id_, table in cfg.get("url", {}).items():
        s = _settings(cfg, table)
        if id_ in seen:
            skipped.append((id_, "a [url] entry has the same id as a tile file"))
            continue
        seen.add(id_)
        e = _entry(id_, "url", {}, s)
        e["source"] = {"scheme": s.get("scheme"), "template": s.get("template"),
                       "credentials": s.get("credentials")}
        tilesets.append(e)
    kept = []
    for e in tilesets:
        errors, warns = validate(e)
        if errors:
            skipped.append((e["id"], "; ".join(errors)))
            continue
        warnings += [(e["id"], w) for w in warns]
        kept.append(e)
    # Ties (same role and maxzoom): the larger area goes underneath, so a regional layer
    # still draws over a world layer of the same detail.
    kept.sort(key=lambda e: (e["order"], -_area(e["bounds"]), e["id"]))
    return {"version": VERSION,
            "generated": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tilesets": kept, "skipped": skipped, "warnings": warnings}


def public(registry: dict) -> dict:
    """What the browser gets: no file paths, no credential names, no skip reasons."""
    out = []
    for e in registry["tilesets"]:
        e = {k: v for k, v in e.items() if k != "source"}
        out.append(e)
    return {"version": registry["version"], "generated": registry["generated"], "tilesets": out}
