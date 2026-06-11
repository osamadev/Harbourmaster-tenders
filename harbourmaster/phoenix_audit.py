"""Phoenix span loading shared by dashboard and copilot native tools."""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from harbourmaster import config

MAX_SPANS = 500
PAGE_SIZE = 100

_project_identifier_cache: dict[str, str] = {}


def clear_phoenix_project_cache() -> None:
    """Clear cached Phoenix project ID lookups (call after config reload)."""
    _project_identifier_cache.clear()


def _phoenix_headers() -> dict[str, str]:
    from harbourmaster.settings import get_snapshot

    return dict(get_snapshot().phoenix.auth_headers)


def _flatten(data: dict[str, Any], parent: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{parent}.{key}" if parent else str(key)
        if isinstance(value, dict):
            flat.update(_flatten(value, full_key))
        else:
            flat[full_key] = value
    return flat


def _status_to_action(status_code: str) -> str:
    code = str(status_code or "").upper()
    if code in {"OK", "STATUS_CODE_OK"}:
        return "ALLOW"
    if code in {"ERROR", "STATUS_CODE_ERROR"}:
        return "DENY"
    return "UNKNOWN"


def _extract_spans(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(payload, dict):
        spans = payload.get("data") or payload.get("spans") or []
        cursor = payload.get("next_cursor")
    elif isinstance(payload, list):
        spans = payload
        cursor = None
    else:
        spans = []
        cursor = None
    rows = [row for row in spans if isinstance(row, dict)]
    return rows, cursor if isinstance(cursor, str) and cursor.strip() else None


def resolve_phoenix_project_identifier(*, force_refresh: bool = False) -> str:
    """Return Phoenix project ID for console URLs (UI expects ID, not name)."""
    project_id = str(getattr(config, "PHOENIX_PROJECT_ID", "") or "").strip()
    if project_id:
        return project_id

    project_name = str(config.PHOENIX_PROJECT_NAME or "").strip() or "harbourmaster"
    base = config.PHOENIX_BASE_URL.rstrip("/")
    cache_key = f"{base}:{project_name}"
    if not force_refresh and cache_key in _project_identifier_cache:
        return _project_identifier_cache[cache_key]

    headers = _phoenix_headers()
    try:
        response = httpx.get(
            f"{base}/v1/projects/{project_name}",
            headers=headers,
            timeout=5,
        )
        if response.status_code == 200:
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict) and data.get("id"):
                resolved = str(data["id"])
                _project_identifier_cache[cache_key] = resolved
                return resolved
    except Exception:  # noqa: BLE001
        pass

    return project_name


def phoenix_console_url(*, project: bool = True) -> str:
    """Build a browser-openable Phoenix console URL from env-backed settings."""
    base = config.PHOENIX_CONSOLE_URL.rstrip("/")
    if not project:
        return base
    identifier = resolve_phoenix_project_identifier()
    return f"{base}/projects/{identifier}"


def _fetch_project_spans(base: str, project_name: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    endpoint = f"{base}/v1/projects/{project_name}/spans"
    entries: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(entries) < MAX_SPANS:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        response = httpx.get(endpoint, headers=headers, params=params, timeout=8)
        if response.status_code != 200:
            return []
        payload = response.json()
        page, next_cursor = _extract_spans(payload)
        if not page:
            break
        entries.extend(page)
        if not next_cursor:
            break
        cursor = next_cursor
    return entries[:MAX_SPANS]


def load_entries() -> list[dict]:
    """Read recent spans from Phoenix; return empty list if unavailable."""
    base = config.PHOENIX_BASE_URL.rstrip("/")
    headers = _phoenix_headers()
    project_candidates = [config.PHOENIX_PROJECT_NAME, "default"]
    seen: set[str] = set()

    for project_name in project_candidates:
        project = str(project_name or "").strip()
        if not project or project in seen:
            continue
        seen.add(project)
        try:
            entries = _fetch_project_spans(base, project, headers)
            if entries:
                return entries
        except Exception:  # noqa: BLE001
            continue
    return []


def load_dataframe() -> pd.DataFrame:
    """Load governance telemetry into a DataFrame."""
    entries = load_entries()
    if not entries:
        return pd.DataFrame()

    rows = []
    for entry in entries:
        attrs_raw = entry.get("attributes") or entry.get("metadata") or {}
        if not isinstance(attrs_raw, dict):
            attrs_raw = {}
        attrs = _flatten(attrs_raw)
        risk_raw = attrs.get("inspection.risk_score", attrs.get("risk_score"))
        try:
            risk_score = float(risk_raw or 0.0)
        except Exception:  # noqa: BLE001
            risk_score = 0.0
        has_explicit_risk = risk_raw is not None and risk_score > 0.0

        categories = attrs.get("inspection.categories") or attrs.get("categories") or []
        if isinstance(categories, str):
            category_list = [c.strip() for c in categories.split(",") if c.strip()]
        elif isinstance(categories, list):
            category_list = [str(c).strip() for c in categories if str(c).strip()]
        else:
            category_list = []

        verdict = (
            attrs.get("inspection.verdict")
            or attrs.get("verdict")
            or _status_to_action(entry.get("status_code") or entry.get("status"))
        )
        direction = (
            attrs.get("openinference.span.kind")
            or attrs.get("direction")
            or "model_call"
        )

        row = {
            "timestamp": entry.get("start_time") or entry.get("timestamp", ""),
            "request_id": entry.get("id") or entry.get("span_id") or entry.get("trace_id", ""),
            "direction": str(direction),
            "action": str(verdict or "UNKNOWN").upper(),
            "rule_name": attrs.get("inspection.reason", ""),
            "deny_message": attrs.get("inspection.reason", ""),
            "agent_id": attrs.get("agent_id") or attrs.get("openinference.user_id") or entry.get("name", ""),
            "prompt": attrs.get("input.value", ""),
            "token_count": int(attrs.get("llm.token_count.total", 0) or 0),
            "risk_score": risk_score,
            "has_explicit_risk": has_explicit_risk,
            "intent_category": ", ".join(category_list),
            "mismatches": [],
            "has_mismatches": False,
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if "timestamp" in df.columns and not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df
