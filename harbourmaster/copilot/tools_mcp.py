"""Lazy Phoenix and Elastic MCP tool loading."""

from __future__ import annotations

import asyncio
from typing import Any

from harbourmaster.settings import get_snapshot

_mcp_tools: list[Any] | None = None
_mcp_error: str | None = None


def _base_env() -> dict[str, str]:
    """A safe base environment (crucially including PATH) for stdio subprocesses.

    When a custom ``env`` is given to an MCP stdio server, the SDK uses it verbatim — so
    omitting PATH means the spawned ``npx``/``node`` can't be found ("...: not found").
    """
    try:
        from mcp.client.stdio import get_default_environment

        return dict(get_default_environment())
    except Exception:  # noqa: BLE001
        import os

        keep = {
            "PATH", "HOME", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP",
            "APPDATA", "LOCALAPPDATA", "USERPROFILE", "NODE_PATH",
        }
        return {k: v for k, v in os.environ.items() if k in keep}


def _phoenix_mcp_server(phoenix, mcp) -> dict[str, Any]:
    args = ["-y", mcp.phoenix_package, "--baseUrl", phoenix.api_base_url]
    if phoenix.api_key:
        args.extend(["--apiKey", phoenix.api_key])
    return {"command": mcp.npx_command, "args": args, "transport": "stdio"}


def _elastic_mcp_server(elastic, mcp) -> dict[str, Any]:
    env = {
        **_base_env(),
        "ES_URL": elastic.url,
        "ES_VERSION": "8",
        "OTEL_LOG_LEVEL": "none",
    }
    if elastic.api_key:
        env["ES_API_KEY"] = elastic.api_key
    elif elastic.username and elastic.password:
        env["ES_USERNAME"] = elastic.username
        env["ES_PASSWORD"] = elastic.password
    return {
        "command": mcp.npx_command,
        "args": ["-y", mcp.elastic_package],
        "env": env,
        "transport": "stdio",
    }


async def load_mcp_tools(*, force: bool = False) -> list[Any]:
    """Load MCP tools with lazy init and cached error state."""
    global _mcp_tools, _mcp_error
    snapshot = get_snapshot()

    if not snapshot.mcp.enabled:
        _mcp_tools = []
        _mcp_error = None
        return []

    if _mcp_tools is not None and not force:
        return _mcp_tools
    if force:
        _mcp_tools = None
        _mcp_error = None

    from langchain_mcp_adapters.client import MultiServerMCPClient

    servers: dict[str, Any] = {}
    if snapshot.mcp.phoenix_enabled:
        servers["phoenix"] = _phoenix_mcp_server(snapshot.phoenix, snapshot.mcp)
    if snapshot.mcp.elastic_enabled and snapshot.elastic.enabled and snapshot.elastic.url:
        servers["elastic"] = _elastic_mcp_server(snapshot.elastic, snapshot.mcp)

    if not servers:
        _mcp_tools = []
        _mcp_error = "No MCP servers enabled"
        return _mcp_tools

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            client = MultiServerMCPClient(servers)
            tools = await asyncio.wait_for(
                client.get_tools(),
                timeout=snapshot.mcp.load_timeout_sec,
            )
            _mcp_tools = list(tools)
            _mcp_error = None
            return _mcp_tools
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await asyncio.sleep(1)

    _mcp_tools = []
    _mcp_error = str(last_error) if last_error else "MCP tool load failed"
    return _mcp_tools


def mcp_status() -> dict[str, Any]:
    """Return MCP initialization status for health checks."""
    snapshot = get_snapshot()
    return {
        "enabled": snapshot.mcp.enabled,
        "phoenix_enabled": snapshot.mcp.phoenix_enabled,
        "elastic_enabled": snapshot.mcp.elastic_enabled,
        "loaded": _mcp_tools is not None,
        "tool_count": len(_mcp_tools or []),
        "error": _mcp_error,
        "phoenix_package": snapshot.mcp.phoenix_package,
        "elastic_package": snapshot.mcp.elastic_package,
    }


def reset_mcp_tools() -> None:
    """Clear cached MCP tools so the next request reconnects."""
    global _mcp_tools, _mcp_error
    _mcp_tools = None
    _mcp_error = None
