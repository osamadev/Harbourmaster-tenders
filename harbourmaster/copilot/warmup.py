"""Background warm-up of the MCP server tools to remove Copilot/dashboard cold-start latency.

The first Copilot query (and the first MCP-first telemetry read) otherwise pays the cost of
spawning the ``npx`` Phoenix/Elastic MCP subprocesses and doing the stdio handshake. Calling
``warm_up_mcp()`` once on app start kicks that off in the background so the cache
(``tools_mcp._mcp_tools``) is populated before the user needs it.
"""

from __future__ import annotations

import asyncio
import logging
import threading

logger = logging.getLogger("harbourmaster.copilot.warmup")

_started = False
_lock = threading.Lock()


def warm_up_mcp(*, build_agent: bool = False) -> None:
    """Start a one-time background load of the MCP tools (optionally pre-build the agent).

    Idempotent per process and best-effort — failures are logged, never raised, and the tools
    simply lazy-load on first use as before.
    """
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def _run() -> None:
        try:
            from harbourmaster.copilot.tools_mcp import load_mcp_tools, mcp_status

            asyncio.run(load_mcp_tools())
            logger.info("MCP warm-up complete: %s tools cached", mcp_status().get("tool_count"))
            if build_agent:
                from harbourmaster.copilot.agent import _ensure_agent

                asyncio.run(_ensure_agent())
                logger.info("Copilot agent pre-built")
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP warm-up failed (will lazy-load on first use): %s", exc)

    threading.Thread(target=_run, name="mcp-warmup", daemon=True).start()
