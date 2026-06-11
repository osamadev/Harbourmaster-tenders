"""Hybrid ReAct agent for Governance Copilot."""

from __future__ import annotations

import json
import re
from typing import Any

from harbourmaster import config
from harbourmaster.phoenix_audit import phoenix_console_url
from harbourmaster.copilot.models import CopilotMessage, CopilotResult, SourceCitation
from harbourmaster.copilot.prompts import SYSTEM_PROMPT
from harbourmaster.copilot.tools_mcp import load_mcp_tools, reset_mcp_tools
from harbourmaster.copilot.tools_native import native_tools
from harbourmaster.telemetry import init_telemetry

_agent = None
_use_mcp = False


def _needs_mcp(message: str) -> bool:
    text = message.lower()
    keywords = (
        "experiment",
        "dataset",
        "prompt template",
        "phoenix mcp",
        "list-datasets",
        "list-experiments",
        "arize",
    )
    return any(word in text for word in keywords)


async def _build_agent(*, include_mcp: bool):
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    init_telemetry()
    tools = native_tools()
    if include_mcp:
        tools.extend(await load_mcp_tools())

    llm = ChatOpenAI(
        model=config.DRAFTER_MODEL,
        temperature=0.1,
        api_key=config.GEMINI_API_KEY,
        base_url=config.GEMINI_BASE_URL,
    )
    return create_react_agent(llm, tools)


async def reset_agent() -> None:
    """Drop cached agent and MCP connections."""
    global _agent, _use_mcp
    _agent = None
    _use_mcp = False
    reset_mcp_tools()


def _history_messages(history: list[CopilotMessage]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in history:
        if item.content.strip():
            rows.append({"role": item.role, "content": item.content})
    return rows


def _message_content(msg: Any) -> str:
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(p for p in parts if p).strip()
    return str(content or "").strip()


def _tool_trace(messages: list[Any]) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for msg in messages:
        calls = getattr(msg, "tool_calls", None)
        if not isinstance(calls, list):
            continue
        for call in calls:
            if isinstance(call, dict):
                trace.append(
                    {
                        "name": call.get("name", ""),
                        "args": call.get("args", {}),
                    }
                )
            else:
                trace.append({"name": getattr(call, "name", ""), "args": getattr(call, "args", {})})
    return trace


def _sources_from_trace(trace: list[dict[str, Any]]) -> list[SourceCitation]:
    sources: list[SourceCitation] = []
    for item in trace:
        name = str(item.get("name", ""))
        args = item.get("args") or {}
        if name == "get_review_detail":
            rid = str(args.get("review_id", ""))
            if rid:
                sources.append(SourceCitation(kind="review", title=rid, detail="Saved contract review"))
        elif name == "search_procurement_memory":
            query = str(args.get("query", ""))
            if query:
                sources.append(SourceCitation(kind="elastic", title=query, detail="Procurement memory search"))
        elif name == "summarize_guard_telemetry":
            sources.append(
                SourceCitation(
                    kind="phoenix",
                    title="Guard telemetry",
                    link=phoenix_console_url(),
                )
            )
        elif name == "list_active_policies":
            sources.append(SourceCitation(kind="policy", title="Active policies"))
    return sources


def _answer_from_messages(messages: list[Any]) -> str:
    for msg in reversed(messages):
        role = getattr(msg, "type", "") or getattr(msg, "role", "")
        if str(role).endswith("ai") or role == "assistant":
            text = _message_content(msg)
            if text:
                return text

    for msg in reversed(messages):
        content = _message_content(msg)
        if content.startswith("{") or content.startswith("["):
            try:
                payload = json.loads(content)
                return json.dumps(payload, indent=2)[:4000]
            except json.JSONDecodeError:
                pass
        if content and len(content) > 40:
            return content[:4000]
    return ""


async def chat(message: str, history: list[CopilotMessage] | None = None) -> CopilotResult:
    """Run a conversational governance query with optional prior turns."""
    global _agent, _use_mcp

    history = history or []
    include_mcp = _needs_mcp(message)
    if _agent is None or include_mcp != _use_mcp:
        _agent = await _build_agent(include_mcp=include_mcp)
        _use_mcp = include_mcp

    payload_messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    payload_messages.extend(_history_messages(history))
    payload_messages.append({"role": "user", "content": message})

    try:
        result = await _agent.ainvoke({"messages": payload_messages})
    except Exception:
        await reset_agent()
        _agent = await _build_agent(include_mcp=include_mcp)
        _use_mcp = include_mcp
        result = await _agent.ainvoke({"messages": payload_messages})

    messages = result.get("messages", [])
    trace = _tool_trace(messages)
    answer = _answer_from_messages(messages)
    if not answer:
        answer = "I could not produce a textual answer. Expand tool calls for raw results."

    console_links = [phoenix_console_url()]
    for item in trace:
        if re.search(r"experiment|dataset|phoenix", str(item.get("name", "")), re.I):
            console_links.append(phoenix_console_url())
            break

    return CopilotResult(
        answer=answer,
        sources=_sources_from_trace(trace),
        tool_trace=trace,
        console_links=sorted(set(console_links)),
    )
