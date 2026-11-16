"""Thin wrapper over the CDP CLI.

The CLI picks up credentials the usual way: CDP_ACCESS_KEY_ID / CDP_PRIVATE_KEY
(Workbench project variables), or CDP_PROFILE / ~/.cdp on a workstation.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


class CdpError(RuntimeError):
    @property
    def not_found(self) -> bool:
        return "NOT_FOUND" in str(self)


def cdp(*args: str, timeout: int = 120) -> Any:
    exe = shutil.which("cdp")
    if not exe:
        raise CdpError("CDP CLI not found -- pip install cdpcli")
    proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise CdpError((proc.stderr or proc.stdout).strip())
    out = proc.stdout.strip()
    return json.loads(out) if out else {}
