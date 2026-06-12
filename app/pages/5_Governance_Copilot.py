"""Governance Copilot — hybrid chat over native tools and Phoenix MCP."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import streamlit as st

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.utils.auth import require_auth  # noqa: E402
from app.utils.layout import init_page, inject_theme_css, render_app_sidebar  # noqa: E402
from app.utils.links import render_external_link  # noqa: E402
from harbourmaster.copilot import CopilotMessage, chat, reset_agent, run_health_checks  # noqa: E402

EXAMPLES = [
    "Summarize guard denial categories from recent Phoenix traces.",
    "Find similar high-risk indemnity clauses in procurement memory.",
    "What active corporate policies apply to IP ownership?",
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

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                result = _run_async(chat(user_text, history=_to_history()[:-1]))
                answer = result.answer
                meta = {
                    "sources": [s.__dict__ for s in result.sources],
                    "tool_trace": result.tool_trace,
                    "console_links": result.console_links,
                }
            except Exception as exc:  # noqa: BLE001
                answer = (
                    f"Copilot failed: {exc}\n\n"
                    "Try: confirm GEMINI_API_KEY, run a review for Phoenix traces, "
                    "and `make index-elastic` for procurement memory."
                )
                meta = {"error": str(exc)}

        st.write(answer)
        st.session_state.copilot_messages.append(
            {"role": "assistant", "content": answer, "meta": meta}
        )
        if meta.get("sources") or meta.get("tool_trace"):
            with st.expander("Sources & tools", expanded=False):
                if meta.get("sources"):
                    for source in meta["sources"]:
                        st.markdown(f"- `{source.get('kind', '')}` **{source.get('title', '')}**")
                if meta.get("tool_trace"):
                    st.json(meta["tool_trace"])
