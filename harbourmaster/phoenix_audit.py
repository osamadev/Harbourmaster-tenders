"""Phoenix span loading shared by dashboard and copilot native tools."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pandas as pd

from harbourmaster import config
from harbourmaster.pricing import estimate_cost

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

    # MCP-first: resolve the project id via the Phoenix MCP server.
    try:
        from harbourmaster.mcp_client import mcp_resolve_project_id

        pid = mcp_resolve_project_id(project_name)
        if pid:
            _project_identifier_cache[cache_key] = pid
            return pid
    except Exception:  # noqa: BLE001
        pass

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


_last_source = "none"


def last_source() -> str:
    """Where the most recent span fetch came from: 'mcp', 'rest', or 'none'."""
    return _last_source


def load_entries() -> list[dict]:
    """Read recent spans from Phoenix (MCP-first, REST fallback); empty if unavailable."""
    global _last_source
    base = config.PHOENIX_BASE_URL.rstrip("/")
    headers = _phoenix_headers()
    project_candidates = [config.PHOENIX_PROJECT_NAME, "default"]
    seen: set[str] = set()

    for project_name in project_candidates:
        project = str(project_name or "").strip()
        if not project or project in seen:
            continue
        seen.add(project)

        # MCP-first: pull spans through the Phoenix MCP server.
        try:
            from harbourmaster.mcp_client import mcp_get_spans

            spans = mcp_get_spans(project=project, limit=MAX_SPANS)
            if spans:
                _last_source = "mcp"
                return spans
        except Exception:  # noqa: BLE001
            pass

        # Native fallback: Phoenix REST.
        try:
            entries = _fetch_project_spans(base, project, headers)
            if entries:
                _last_source = "rest"
                return entries
        except Exception:  # noqa: BLE001
            continue

    _last_source = "none"
    return []


_SPECIALIST_HINTS = ("legal", "financial", "delivery", "ip_data", "compliance")
_WORKFLOW_HINTS = ("segment", "verifier", "negotiator", "drafter")


def _classify_component(attrs: dict[str, Any], agent_id: str, direction: str, span_type: str) -> str:
    """Tag each span as copilot / guard / specialist / workflow / other."""
    meta = str(attrs.get("metadata") or "")
    if "hm_component" in meta and "copilot" in meta:
        return "copilot"
    aid = str(agent_id or "").lower()
    if direction == "guard" or "guard" in aid:
        return "guard"
    if any(hint in aid for hint in _SPECIALIST_HINTS):
        return "specialist"
    if span_type == "inspection" or any(hint in aid for hint in _WORKFLOW_HINTS):
        return "workflow"
    # Copilot spans are already excluded, so any remaining model-call span is the
    # workflow's own LLM traffic (raw "ChatCompletion" spans carry tokens/cost).
    if span_type == "llm":
        return "workflow"
    return "other"


def _build_dataframe() -> pd.DataFrame:
    """Read spans from Phoenix into an enriched governance DataFrame."""
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
        # Prefer the explicit governance `direction` (guard/model_call/workflow_risk)
        # over the OpenInference span kind: inspection spans now carry a CHAIN kind
        # for clean rendering, but their `direction` is what drives classification.
        # Raw ChatCompletion spans have no `direction`, so they still resolve to LLM.
        direction = str(
            attrs.get("direction") or attrs.get("openinference.span.kind") or "model_call"
        )
        agent_id = attrs.get("agent_id") or attrs.get("openinference.user_id") or entry.get("name", "")

        prompt_tokens = int(attrs.get("llm.token_count.prompt", 0) or 0)
        completion_tokens = int(attrs.get("llm.token_count.completion", 0) or 0)
        total_tokens = int(
            attrs.get("llm.token_count.total", prompt_tokens + completion_tokens) or 0
        )
        model = str(attrs.get("llm.model_name") or "")
        cost_usd = (
            estimate_cost(model, prompt_tokens, completion_tokens)
            if (prompt_tokens or completion_tokens)
            else 0.0
        )

        has_inspection = "inspection.verdict" in attrs or "inspection.risk_score" in attrs
        span_type = "inspection" if has_inspection else ("llm" if (model or total_tokens) else "other")
        component = _classify_component(attrs, agent_id, direction, span_type)

        rows.append(
            {
                "timestamp": entry.get("start_time") or entry.get("timestamp", ""),
                "end_time": entry.get("end_time", ""),
                "request_id": entry.get("id") or entry.get("span_id") or entry.get("trace_id", ""),
                "trace_id": entry.get("trace_id", ""),
                "session_id": str(attrs.get("session.id") or ""),
                "direction": direction,
                "action": str(verdict or "UNKNOWN").upper(),
                "rule_name": attrs.get("inspection.reason", ""),
                "deny_message": attrs.get("inspection.reason", ""),
                "agent_id": agent_id,
                "component": component,
                "span_type": span_type,
                "model": model,
                "prompt": attrs.get("input.value", ""),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "token_count": total_tokens,  # legacy alias for the dashboard
                "cost_usd": cost_usd,
                "risk_score": risk_score,
                "has_explicit_risk": has_explicit_risk,
                "intent_category": ", ".join(category_list),
                "mismatches": [],
                "has_mismatches": False,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    start = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    end = pd.to_datetime(df["end_time"], errors="coerce", utc=True)
    df["timestamp"] = start
    df["latency_ms"] = (end - start).dt.total_seconds() * 1000.0
    return df


_CACHE: dict[str, Any] = {"df": None, "ts": 0.0}
_CACHE_TTL = 5.0


def clear_dataframe_cache() -> None:
    """Drop the cached span frame (call after config reload or to force a refresh)."""
    _CACHE["df"] = None
    _CACHE["ts"] = 0.0


_GOVERNANCE_COMPONENTS = {"guard", "specialist", "workflow"}


def load_dataframe(*, governance_only: bool = True, force: bool = False) -> pd.DataFrame:
    """Load governance telemetry into an enriched DataFrame.

    By default only governance components (guard / specialist / workflow) are kept, which
    drops Copilot self-spans and infrastructure noise (e.g. Elasticsearch client spans) so
    the numbers reflect the review pipeline. Pass ``governance_only=False`` for everything.
    Results are briefly cached so multiple tool calls in one Copilot turn don't each
    re-fetch up to 500 spans.
    """
    now = time.time()
    if not force and _CACHE["df"] is not None and (now - _CACHE["ts"]) < _CACHE_TTL:
        df = _CACHE["df"]
    else:
        df = _build_dataframe()
        _CACHE["df"] = df
        _CACHE["ts"] = now

    if df.empty:
        return df
    if governance_only and "component" in df.columns:
        return df[df["component"].isin(_GOVERNANCE_COMPONENTS)].copy()
    return df.copy()
