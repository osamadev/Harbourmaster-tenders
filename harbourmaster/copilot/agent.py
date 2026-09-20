"""Hybrid ReAct agent for Governance Copilot — streaming, chart-aware, self-tagged."""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

from harbourmaster import config
from harbourmaster.copilot.models import CopilotMessage, CopilotResult, SourceCitation
from harbourmaster.copilot.prompts import SYSTEM_PROMPT
from harbourmaster.copilot.tools_mcp import load_mcp_tools, reset_mcp_tools
from harbourmaster.copilot.tools_native import native_tools
from harbourmaster.phoenix_audit import phoenix_console_url
from harbourmaster.runtime_keys import resolve_gemini_key
from harbourmaster.telemetry import init_telemetry

_agent = None
_agent_key: str | None = None

# Tools whose results are governance/Phoenix telemetry (for citations + console links).
_PHOENIX_TOOLS = {
    "summarize_guard_telemetry",
    "query_telemetry",
    "aggregate_telemetry",
    "telemetry_timeseries",
    "token_cost_usage",
    "risk_outliers",
    "review_telemetry",
}


async def _build_agent():
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    init_telemetry()
    tools = native_tools()
    tools.extend(await load_mcp_tools())  # best-effort; [] if unavailable

    llm = ChatOpenAI(
        model=config.COPILOT_MODEL,
        temperature=0.1,
        api_key=resolve_gemini_key() or config.GEMINI_API_KEY,
        base_url=config.GEMINI_BASE_URL,
        streaming=True,
    )
    return create_react_agent(llm, tools)


async def _ensure_agent():
    global _agent, _agent_key
    current_key = resolve_gemini_key() or config.GEMINI_API_KEY
    if _agent is None or current_key != _agent_key:
        _agent = await _build_agent()
        _agent_key = current_key
    return _agent


async def reset_agent() -> None:
    """Drop cached agent and MCP connections."""
    global _agent, _agent_key
    _agent = None
    _agent_key = None
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


def _tool_output_text(output: Any) -> str:
    if output is None:
        return ""
    content = getattr(output, "content", None)
    if content is not None:
        return content if isinstance(content, str) else str(content)
    return output if isinstance(output, str) else str(output)


def _extract_chart(output: Any) -> dict[str, Any] | None:
    text = _tool_output_text(output)
    if not text or "chart" not in text:
        return None
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return None
    chart = data.get("chart") if isinstance(data, dict) else None
    if isinstance(chart, dict) and chart.get("x") and chart.get("y"):
        return chart
    return None


def _sources_from_trace(trace: list[dict[str, Any]]) -> list[SourceCitation]:
    sources: list[SourceCitation] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, title: str, **kw: Any) -> None:
        key = (kind, title)
        if title and key not in seen:
            seen.add(key)
            sources.append(SourceCitation(kind=kind, title=title, **kw))

    for item in trace:
        name = str(item.get("name", ""))
        args = item.get("args") or {}
        if name == "get_review_detail":
            add("review", str(args.get("review_id", "")), detail="Saved contract review")
        elif name == "review_telemetry":
            add("phoenix", f"Review telemetry: {args.get('review_id', '')}", link=phoenix_console_url())
        elif name == "search_procurement_memory":
            add("elastic", str(args.get("query", "")), detail="Procurement memory search")
        elif name == "list_active_policies":
            add("policy", "Active policies")
        elif name in _PHOENIX_TOOLS:
            add("phoenix", name.replace("_", " ").title(), link=phoenix_console_url())
        elif re.search(r"experiment|dataset|prompt", name, re.I):
            add("phoenix", f"MCP: {name}", link=phoenix_console_url())
    return sources


def _console_links(trace: list[dict[str, Any]]) -> list[str]:
    links = [phoenix_console_url()]
    for item in trace:
        if item.get("name") in _PHOENIX_TOOLS or re.search(
            r"experiment|dataset|phoenix", str(item.get("name", "")), re.I
        ):
            links.append(phoenix_console_url())
            break
    return sorted(set(links))


def _answer_from_messages(messages: list[Any]) -> str:
    for msg in reversed(messages):
        role = getattr(msg, "type", "") or getattr(msg, "role", "")
        if str(role).endswith("ai") or role == "assistant":
            text = _message_content(msg)
            if text:
                return text
    for msg in reversed(messages):
        content = _message_content(msg)
        if content and len(content) > 40:
            return content[:4000]
    return ""


async def chat_stream(
    message: str, history: list[CopilotMessage] | None = None
) -> AsyncIterator[dict[str, Any]]:
    """Stream a governance answer.

    Yields events: {"type":"tool", "name", "args"} when a tool starts,
    {"type":"token","text"} for answer tokens, and a final
    {"type":"final","result": CopilotResult}.
    """
    from openinference.instrumentation import suppress_tracing

    history = history or []
    agent = await _ensure_agent()
    payload = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *_history_messages(history),
        {"role": "user", "content": message},
    ]

    trace: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    answer_parts: list[str] = []
    last_ai_text = ""

    try:
        # Suppress tracing so the Copilot's own LLM calls never enter the governance
        # telemetry it reports on.
        with suppress_tracing():
            async for event in agent.astream_events({"messages": payload}, version="v2"):
                kind = event.get("event", "")
                data = event.get("data", {}) or {}
                if kind == "on_tool_start":
                    entry = {"name": event.get("name", ""), "args": data.get("input", {})}
                    trace.append(entry)
                    yield {"type": "tool", "name": entry["name"], "args": entry["args"]}
                elif kind == "on_tool_end":
                    chart = _extract_chart(data.get("output"))
                    if chart:
                        charts.append(chart)
                elif kind == "on_chat_model_stream":
                    text = _message_content(data.get("chunk"))
                    if text:
                        answer_parts.append(text)
                        yield {"type": "token", "text": text}
                elif kind == "on_chat_model_end":
                    out = data.get("output")
                    txt = _message_content(out) if out is not None else ""
                    if txt:
                        last_ai_text = txt
    except Exception:  # noqa: BLE001 — fall back to a single non-streaming invoke
        await reset_agent()
        agent = await _ensure_agent()
        with suppress_tracing():
            result = await agent.ainvoke({"messages": payload})
        messages = result.get("messages", [])
        trace = _tool_trace(messages)
        charts = []
        for msg in messages:
            if str(getattr(msg, "type", "")) == "tool":
                chart = _extract_chart(msg)
                if chart:
                    charts.append(chart)
        last_ai_text = _answer_from_messages(messages)
        answer_parts = []

    answer = "".join(answer_parts).strip() or last_ai_text.strip()
    if not answer:
        answer = "I could not produce a textual answer. Expand tool calls for raw results."

    yield {
        "type": "final",
        "result": CopilotResult(
            answer=answer,
            sources=_sources_from_trace(trace),
            tool_trace=trace,
            console_links=_console_links(trace),
            charts=charts,
            steps=[{"tool": t.get("name", "")} for t in trace],
        ),
    }


def _tool_trace(messages: list[Any]) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for msg in messages:
        calls = getattr(msg, "tool_calls", None)
        if not isinstance(calls, list):
            continue
        for call in calls:
            if isinstance(call, dict):
                trace.append({"name": call.get("name", ""), "args": call.get("args", {})})
            else:
                trace.append({"name": getattr(call, "name", ""), "args": getattr(call, "args", {})})
    return trace


async def chat(message: str, history: list[CopilotMessage] | None = None) -> CopilotResult:
    """Non-streaming wrapper (drains chat_stream) — kept for smoke tests/back-compat."""
    result: CopilotResult | None = None
    async for event in chat_stream(message, history):
        if event.get("type") == "final":
            result = event["result"]
    return result or CopilotResult(answer="(no answer produced)")
