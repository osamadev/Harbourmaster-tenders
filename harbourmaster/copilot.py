"""Backward-compatible shim for Governance Copilot."""

from __future__ import annotations

from typing import Any

from harbourmaster.copilot import CopilotMessage, chat


async def ask_governance_copilot(question: str) -> dict[str, Any]:
    """Execute a governance question (legacy single-turn API)."""
    result = await chat(question, history=[])
    return {
        "answer": result.answer,
        "tool_calls": result.tool_trace,
        "sources": [s.__dict__ for s in result.sources],
        "console_links": result.console_links,
    }
