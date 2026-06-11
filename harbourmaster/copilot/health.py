"""Preflight health checks for Governance Copilot."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

import httpx

from harbourmaster import config
from harbourmaster.copilot.tools_mcp import mcp_status
from harbourmaster.elastic_store import enabled as elastic_enabled
from harbourmaster.phoenix_audit import _phoenix_headers, phoenix_console_url
from harbourmaster.settings import get_snapshot, validate


def check_phoenix() -> dict[str, Any]:
    snapshot = get_snapshot()
    base = snapshot.phoenix.api_base_url.rstrip("/")
    try:
        response = httpx.get(f"{base}/healthz", headers=_phoenix_headers(), timeout=5)
        ok = response.status_code == 200
        return {
            "ok": ok,
            "detail": f"{base} -> {response.status_code}",
            "mode": snapshot.phoenix.mode,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc), "mode": snapshot.phoenix.mode}


def check_elastic() -> dict[str, Any]:
    snapshot = get_snapshot()
    if not elastic_enabled():
        return {
            "ok": False,
            "detail": "Elastic disabled or ELASTIC_URL unset",
            "mode": snapshot.elastic.mode,
        }
    try:
        from harbourmaster.elastic_store import client

        health = client().cluster.health()
        status = str(health.get("status", "unknown"))
        return {
            "ok": status in {"green", "yellow"},
            "detail": f"cluster status: {status}",
            "mode": snapshot.elastic.mode,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc), "mode": snapshot.elastic.mode}


def check_node() -> dict[str, Any]:
    npx = shutil.which("npx")
    if not npx:
        return {"ok": False, "detail": "npx not found on PATH"}
    try:
        proc = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        version = (proc.stdout or proc.stderr or "").strip()
        return {"ok": proc.returncode == 0, "detail": version or "node unavailable"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)}


def check_gemini() -> dict[str, Any]:
    ok = bool((config.GEMINI_API_KEY or "").strip())
    return {"ok": ok, "detail": "GEMINI_API_KEY set" if ok else "GEMINI_API_KEY missing"}


def run_health_checks() -> dict[str, Any]:
    """Aggregate copilot dependency health."""
    snapshot = get_snapshot()
    errors, warnings = validate(snapshot)
    return {
        "phoenix": check_phoenix(),
        "elastic": check_elastic(),
        "node": check_node(),
        "gemini": check_gemini(),
        "mcp": mcp_status(),
        "phoenix_mode": snapshot.phoenix.mode,
        "elastic_mode": snapshot.elastic.mode,
        "validation_errors": errors,
        "validation_warnings": warnings,
        "console_url": phoenix_console_url(),
    }
