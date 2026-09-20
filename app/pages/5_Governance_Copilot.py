"""Governance Copilot — hybrid chat over native tools and Phoenix MCP."""

from __future__ import annotations

import asyncio
import itertools
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.utils.auth import require_auth  # noqa: E402
from app.utils.layout import init_page, inject_theme_css, render_app_sidebar  # noqa: E402
from app.utils.links import render_external_link  # noqa: E402
from harbourmaster.copilot import CopilotMessage, chat_stream, reset_agent, run_health_checks  # noqa: E402

EXAMPLES = [
    "Show denial rate by agent and chart it.",
    "Plot average risk score over time (hourly).",
    "Which model burns the most tokens, and the estimated cost?",
    "List the top risk outliers and why they were flagged.",
    "Find similar high-risk indemnity clauses in procurement memory.",
    "Show the latest red-team experiment and key failures.",
]

if "copilot_messages" not in st.session_state:
    st.session_state.copilot_messages: list[dict[str, Any]] = []

init_page(
    "Governance Copilot",
    icon="🧭",
    subtitle="Chat over guard telemetry, saved reviews, procurement memory, and Phoenix experiments.",
)
require_auth()

def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _run_stream(make_agen, on_event):
    """Drive an async generator to completion in one loop, invoking on_event per item.

    Running the whole async-for inside a single run_until_complete keeps OpenInference
    context managers (e.g. suppress_tracing) paired within one OTel context — driving it
    step-by-step across separate run_until_complete calls breaks attach/detach and logs
    'Failed to detach context'.
    """

    async def _drive():
        async for event in make_agen():
            on_event(event)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_drive())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


_chart_seq = itertools.count()


def _render_chart(chart: dict) -> None:
    x = chart.get("x") or []
    y = chart.get("y") or []
    if not x or not y:
        return
    dfc = pd.DataFrame({"label": [str(v) for v in x], "value": y})
    title = chart.get("title", "")
    if str(chart.get("type")) == "line":
        fig = px.line(dfc, x="label", y="value", title=title, markers=True)
    else:
        fig = px.bar(dfc, x="label", y="value", title=title)
    fig.update_layout(
        template="plotly_white",
        margin=dict(t=44, b=10, l=10, r=10),
        xaxis_title=chart.get("x_label", ""),
        yaxis_title=chart.get("y_label", "value"),
        showlegend=False,
    )
    # Unique key per render: identical charts (e.g. a repeated question, or the same chart in
    # history + the new answer) otherwise collide on Streamlit's auto-generated element id.
    st.plotly_chart(fig, use_container_width=True, key=f"hm-chart-{next(_chart_seq)}")


def _to_history() -> list[CopilotMessage]:
    rows: list[CopilotMessage] = []
    for item in st.session_state.copilot_messages:
        role = item.get("role")
        content = str(item.get("content", ""))
        if role in {"user", "assistant"} and content.strip():
            rows.append(CopilotMessage(role=role, content=content, meta=item.get("meta", {})))
    return rows


def _copilot_sidebar() -> None:
    st.metric("Messages", len(st.session_state.copilot_messages))
    health = run_health_checks()
    inject_theme_css()
    chips = []
    for name, check in [
        ("Phoenix", health["phoenix"]),
        ("Elastic", health["elastic"]),
        ("Gemini", health["gemini"]),
    ]:
        level = "ok" if check.get("ok") else "warn"
        chips.append(f'<span class="hm-chip hm-chip-{level}">{name}</span>')
    st.markdown('<div class="hm-chip-row">' + "".join(chips) + "</div>", unsafe_allow_html=True)

    mcp = health.get("mcp", {})
    if mcp.get("loaded"):
        st.caption(f"MCP: {mcp.get('tool_count', 0)} tools loaded")
    elif mcp.get("error"):
        st.caption(f"MCP: lazy load ({str(mcp['error'])[:60]})")

    if st.button("Clear conversation", use_container_width=True):
        st.session_state.copilot_messages = []
        _run_async(reset_agent())
        st.rerun()

    if st.button("Reset MCP connection", use_container_width=True):
        _run_async(reset_agent())
        st.success("MCP agent reset.")


render_app_sidebar("copilot", extra_blocks=_copilot_sidebar)

st.markdown("### Suggested prompts")
cols = st.columns(2)
for idx, example in enumerate(EXAMPLES):
    if cols[idx % 2].button(example, key=f"example-{idx}", use_container_width=True):
        st.session_state.pending_prompt = example

for item in st.session_state.copilot_messages:
    with st.chat_message(item["role"]):
        st.write(item["content"])
        meta = item.get("meta") or {}
        for chart in meta.get("charts", []):
            _render_chart(chart)
        if item["role"] == "assistant" and (meta.get("sources") or meta.get("tool_trace")):
            with st.expander("Sources & tools", expanded=False):
                if meta.get("sources"):
                    st.markdown("**Sources**")
                    for source in meta["sources"]:
                        st.markdown(f"- `{source.get('kind', '')}` **{source.get('title', '')}**")
                        if source.get("detail"):
                            st.caption(source["detail"])
                        if source.get("link"):
                            render_external_link("Open in Phoenix", source["link"])
                if meta.get("tool_trace"):
                    st.markdown("**Tool trace**")
                    st.json(meta["tool_trace"])
                for link in meta.get("console_links", []):
                    render_external_link("Phoenix project", link)

prompt = st.chat_input("Ask a governance question...")
pending = st.session_state.pop("pending_prompt", None)
user_text = pending or prompt

if user_text:
    st.session_state.copilot_messages.append({"role": "user", "content": user_text, "meta": {}})
    with st.chat_message("user"):
        st.write(user_text)

    history = _to_history()[:-1]
    with st.chat_message("assistant"):
        status = st.empty()
        answer_box = st.empty()
        stream_state = {"answer": "", "final": None}

        def _on_event(event: dict) -> None:
            etype = event.get("type")
            if etype == "tool":
                status.markdown(f"🔧 Running `{event.get('name', '')}`…")
            elif etype == "token":
                stream_state["answer"] += event.get("text", "")
                answer_box.markdown(stream_state["answer"] + "▌")
            elif etype == "final":
                stream_state["final"] = event.get("result")

        try:
            _run_stream(lambda: chat_stream(user_text, history=history), _on_event)
            status.empty()
        except Exception as exc:  # noqa: BLE001
            status.empty()
            stream_state["answer"] = (
                f"Copilot failed: {exc}\n\nTry: confirm the Gemini key, run a review for "
                "Phoenix traces, and `make index-elastic` for procurement memory."
            )

        final_result = stream_state["final"]
        answer_text = stream_state["answer"]
        if final_result is not None:
            answer = final_result.answer or answer_text
            meta = {
                "sources": [s.__dict__ for s in final_result.sources],
                "tool_trace": final_result.tool_trace,
                "console_links": final_result.console_links,
                "charts": final_result.charts or [],
            }
        else:
            answer = answer_text
            meta = {}

        answer_box.markdown(answer)
        for chart in meta.get("charts", []):
            _render_chart(chart)

        st.session_state.copilot_messages.append(
            {"role": "assistant", "content": answer, "meta": meta}
        )

        if meta.get("sources") or meta.get("tool_trace"):
            with st.expander("Sources & tools", expanded=False):
                if meta.get("sources"):
                    st.markdown("**Sources**")
                    for source in meta["sources"]:
                        st.markdown(f"- `{source.get('kind', '')}` **{source.get('title', '')}**")
                        if source.get("detail"):
                            st.caption(source["detail"])
                        if source.get("link"):
                            render_external_link("Open in Phoenix", source["link"])
                if meta.get("tool_trace"):
                    st.markdown("**Tool trace**")
                    st.json(meta["tool_trace"])
                for link in meta.get("console_links", []):
                    render_external_link("Phoenix project", link)
