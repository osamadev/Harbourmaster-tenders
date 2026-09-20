"""MCP-first data access for Phoenix telemetry and Elastic, with native fallback.

Every READ of Phoenix spans / projects / datasets / experiments and Elastic search is routed
through the MCP servers when available. Each helper returns parsed data on success, or ``None``
on any failure / when MCP-first is disabled — callers then fall back to the native REST/ES path.

Writes and liveness probes are intentionally NOT here: both MCP servers are read-only.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any

from harbourmaster.settings import get_snapshot


# --------------------------------------------------------------------------- gating
def _data_first() -> bool:
    return str(os.getenv("MCP_DATA_FIRST", "true")).strip().lower() in {"1", "true", "yes", "on"}


def _servers() -> dict[str, Any]:
    from harbourmaster.copilot.tools_mcp import _elastic_mcp_server, _phoenix_mcp_server

    snap = get_snapshot()
    servers: dict[str, Any] = {}
    if snap.mcp.enabled and snap.mcp.phoenix_enabled:
        servers["phoenix"] = _phoenix_mcp_server(snap.phoenix, snap.mcp)
    if snap.mcp.enabled and snap.mcp.elastic_enabled and snap.elastic.enabled and snap.elastic.url:
        servers["elastic"] = _elastic_mcp_server(snap.elastic, snap.mcp)
    return servers


def phoenix_first_enabled() -> bool:
    s = get_snapshot()
    return _data_first() and s.mcp.enabled and s.mcp.phoenix_enabled


def elastic_first_enabled() -> bool:
    s = get_snapshot()
    return _data_first() and s.mcp.enabled and s.mcp.elastic_enabled and s.elastic.enabled


# --------------------------------------------------------------------------- async bridge
_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _background_loop() -> asyncio.AbstractEventLoop:
    """A single long-lived event loop on a daemon thread, shared by all MCP calls.

    Using one persistent loop (instead of ``asyncio.run`` per call) keeps the loop alive when
    MCP stdio subprocess transports are finalized — otherwise their ``__del__`` runs against a
    closed loop and logs 'RuntimeError: Event loop is closed'.
    """
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="mcp-data-loop", daemon=True).start()
        return _loop


def _run(make_coro, timeout: float = 25.0):
    """Run a coroutine on the persistent background loop; None on any failure/timeout.

    Safe to call from sync (Streamlit) or async-in-thread (Copilot) contexts — the coroutine
    is scheduled onto a separate, always-running loop.
    """

    async def _guarded():
        try:
            return await asyncio.wait_for(make_coro(), timeout)
        except Exception:  # noqa: BLE001
            return None

    try:
        future = asyncio.run_coroutine_threadsafe(_guarded(), _background_loop())
        return future.result(timeout=timeout + 10)
    except Exception:  # noqa: BLE001
        return None


def _result_json(result: Any) -> Any:
    """Extract a JSON payload from an MCP CallToolResult (structured or text content)."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured.get("result", structured)
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    joined = "\n".join(parts).strip()
    if not joined:
        return None
    try:
        return json.loads(joined)
    except Exception:  # noqa: BLE001
        return joined


async def _call(server: str, tool: str, args: dict) -> Any:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    servers = _servers()
    if server not in servers:
        return None
    client = MultiServerMCPClient(servers)
    async with client.session(server) as session:
        return _result_json(await session.call_tool(tool, args))


# --------------------------------------------------------------------------- Phoenix reads
def _normalize_span(span: dict) -> dict:
    """Coerce an MCP get-spans row into the shape phoenix_audit expects from REST."""
    ctx = span.get("context") or {}
    out = dict(span)
    out["trace_id"] = span.get("trace_id") or ctx.get("trace_id", "")
    out["span_id"] = span.get("span_id") or ctx.get("span_id", "")
    status = span.get("status_code") or span.get("status")
    if isinstance(status, dict):
        status = status.get("code") or status.get("status_code") or ""
    out["status_code"] = status or ""
    return out


def mcp_get_spans(*, project: str, limit: int = 500) -> list[dict] | None:
    """Fetch up to ``limit`` spans for a project via Phoenix MCP get-spans (paginated)."""
    if not phoenix_first_enabled():
        return None

    async def _go():
        from langchain_mcp_adapters.client import MultiServerMCPClient

        servers = _servers()
        if "phoenix" not in servers:
            return None
        client = MultiServerMCPClient(servers)
        spans: list[dict] = []
        cursor: str | None = None
        async with client.session("phoenix") as session:
            while len(spans) < limit:
                args: dict[str, Any] = {
                    "project_identifier": project,
                    "limit": min(100, limit - len(spans)),
                }
                if cursor:
                    args["cursor"] = cursor
                payload = _result_json(await session.call_tool("get-spans", args))
                if not isinstance(payload, dict):
                    break
                page = payload.get("spans") or []
                if not page:
                    break
                spans.extend(_normalize_span(s) for s in page if isinstance(s, dict))
                cursor = payload.get("nextCursor")
                if not cursor:
                    break
        return spans[:limit]

    out = _run(_go)
    return out if out else None  # empty/failure -> native fallback


def mcp_resolve_project_id(name: str) -> str | None:
    """Resolve a Phoenix project id by name via MCP list-projects."""
    if not phoenix_first_enabled():
        return None
    payload = _run(lambda: _call("phoenix", "list-projects", {}))
    rows = payload.get("projects") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and str(row.get("name", "")) == name and row.get("id"):
            return str(row["id"])
    return None


def mcp_list_datasets() -> list[dict] | None:
    if not phoenix_first_enabled():
        return None
    payload = _run(lambda: _call("phoenix", "list-datasets", {}))
    rows = payload.get("datasets") if isinstance(payload, dict) else payload
    return rows if isinstance(rows, list) and rows else None


def mcp_dataset_examples(dataset_id: str) -> list[dict] | None:
    if not phoenix_first_enabled():
        return None
    payload = _run(lambda: _call("phoenix", "get-dataset-examples", {"dataset_id": dataset_id}))
    if isinstance(payload, dict):
        rows = payload.get("examples") or payload.get("data")
        return rows if isinstance(rows, list) and rows else None
    return payload if isinstance(payload, list) and payload else None


def mcp_list_experiments(dataset_id: str) -> list[dict] | None:
    if not phoenix_first_enabled():
        return None
    payload = _run(
        lambda: _call("phoenix", "list-experiments-for-dataset", {"dataset_id": dataset_id})
    )
    rows = payload.get("experiments") if isinstance(payload, dict) else payload
    return rows if isinstance(rows, list) and rows else None


# --------------------------------------------------------------------------- Elastic reads
def mcp_elastic_search(
    *, query: str, size: int, index: str, doc_types: list[str] | None = None
) -> list[dict] | None:
    """Search procurement memory via the Elastic MCP `search` tool. None on failure/empty."""
    if not elastic_first_enabled():
        return None
    filters: list[dict[str, Any]] = []
    if doc_types:
        filters.append({"terms": {"doc_type": doc_types}})
    body = {
        "size": size,
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["title^3", "body", "content", "tags^2", "policy_id^2"],
                        }
                    }
                ],
                "filter": filters,
            }
        },
    }
    payload = _run(lambda: _call("elastic", "search", {"index": index, "queryBody": body}))
    if not isinstance(payload, dict):
        return None
    hits = (payload.get("hits") or {}).get("hits")
    if not isinstance(hits, list) or not hits:
        return None
    out: list[dict] = []
    for hit in hits:
        source = dict(hit.get("_source", {}) or {})
        source["_score"] = hit.get("_score", 0)
        source["_index"] = hit.get("_index", "")
        out.append(source)
    return out
