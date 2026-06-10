"""System configuration — modes, credentials, and MCP settings."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.utils.config_ui import (  # noqa: E402
    render_field_sources,
    render_resolved_summary,
    render_validation_results,
)
from app.utils.links import render_phoenix_console_link  # noqa: E402
from app.utils.nav import render_sidebar_nav  # noqa: E402
from harbourmaster import config  # noqa: E402
from harbourmaster.copilot.health import check_elastic, run_health_checks  # noqa: E402
from harbourmaster.copilot.tools_mcp import reset_mcp_tools  # noqa: E402
from harbourmaster.runtime_config import (  # noqa: E402
    clear_runtime_config,
    export_env_snippet,
    load_runtime_config,
    save_runtime_config,
    to_public_view,
)
from harbourmaster.settings import get_snapshot, preview_settings, reload, validate  # noqa: E402

st.set_page_config(page_title="Configuration", page_icon="⚙️", layout="wide")
st.title("Configuration")
st.caption("Manage Phoenix, Elastic, MCP, and Gemini settings. Environment variables override saved runtime values.")

snapshot = get_snapshot()
runtime = load_runtime_config()
public_runtime = to_public_view(runtime)

with st.sidebar:
    st.markdown("### Configuration")
    render_sidebar_nav()

col_modes, col_status = st.columns([2, 1])
with col_modes:
    st.markdown("### Deployment modes")
    phoenix_mode = st.selectbox(
        "PHOENIX_MODE",
        options=["local", "cloud"],
        index=0 if snapshot.phoenix.mode == "local" else 1,
    )
    elastic_mode = st.selectbox(
        "ELASTIC_MODE",
        options=["local", "cloud"],
        index=0 if snapshot.elastic.mode == "local" else 1,
    )
    st.caption("Mixed setups are supported, e.g. local Phoenix with cloud Elastic.")

with col_status:
    st.markdown("### Live status")
    health = run_health_checks()
    st.write(f"Phoenix: {'OK' if health['phoenix']['ok'] else 'WARN'} ({health['phoenix_mode']})")
    st.write(f"Elastic: {'OK' if health['elastic']['ok'] else 'WARN'} ({health['elastic_mode']})")
    render_phoenix_console_link()

st.divider()

tab_phoenix, tab_elastic, tab_mcp, tab_summary = st.tabs(
    ["Phoenix", "Elastic", "MCP & Gemini", "Resolved summary"]
)

with tab_phoenix:
    phoenix_base = st.text_input(
        "PHOENIX_BASE_URL",
        value=str(runtime.get("PHOENIX_BASE_URL") or snapshot.phoenix.api_base_url),
    )
    phoenix_console = st.text_input(
        "PHOENIX_CONSOLE_URL",
        value=str(runtime.get("PHOENIX_CONSOLE_URL") or snapshot.phoenix.console_url),
    )
    phoenix_collector = st.text_input(
        "PHOENIX_COLLECTOR_ENDPOINT",
        value=str(runtime.get("PHOENIX_COLLECTOR_ENDPOINT") or snapshot.phoenix.collector_endpoint),
    )
    phoenix_project = st.text_input(
        "PHOENIX_PROJECT_NAME",
        value=str(runtime.get("PHOENIX_PROJECT_NAME") or snapshot.phoenix.project_name),
    )
    phoenix_port = st.number_input(
        "PHOENIX_PORT",
        min_value=1,
        max_value=65535,
        value=int(runtime.get("PHOENIX_PORT") or snapshot.phoenix.port),
    )
    phoenix_key = st.text_input(
        "PHOENIX_API_KEY",
        value="",
        type="password",
        help="Leave blank to keep the current stored value.",
        placeholder="set" if public_runtime.get("PHOENIX_API_KEY") else "not set",
    )

with tab_elastic:
    elastic_enabled = st.toggle(
        "ELASTIC_ENABLED",
        value=bool(runtime.get("ELASTIC_ENABLED", snapshot.elastic.enabled)),
    )
    elastic_url = st.text_input(
        "ELASTIC_URL",
        value=str(runtime.get("ELASTIC_URL") or snapshot.elastic.url),
    )
    elastic_index = st.text_input(
        "ELASTIC_INDEX_PREFIX",
        value=str(runtime.get("ELASTIC_INDEX_PREFIX") or snapshot.elastic.index_prefix),
    )
    elastic_username = st.text_input(
        "ELASTIC_USERNAME",
        value=str(runtime.get("ELASTIC_USERNAME") or snapshot.elastic.username or ""),
    )
    elastic_password = st.text_input(
        "ELASTIC_PASSWORD",
        value="",
        type="password",
        placeholder="set" if public_runtime.get("ELASTIC_PASSWORD") else "not set",
    )
    elastic_api_key = st.text_input(
        "ELASTIC_API_KEY",
        value="",
        type="password",
        placeholder="set" if public_runtime.get("ELASTIC_API_KEY") else "not set",
    )
    elastic_health = check_elastic()
    st.info(f"Elastic connectivity: {elastic_health.get('detail', 'unknown')}")

with tab_mcp:
    mcp_enabled = st.toggle("MCP_ENABLED", value=bool(runtime.get("MCP_ENABLED", snapshot.mcp.enabled)))
    mcp_phoenix = st.toggle(
        "MCP_PHOENIX_ENABLED",
        value=bool(runtime.get("MCP_PHOENIX_ENABLED", snapshot.mcp.phoenix_enabled)),
    )
    mcp_elastic = st.toggle(
        "MCP_ELASTIC_ENABLED",
        value=bool(runtime.get("MCP_ELASTIC_ENABLED", snapshot.mcp.elastic_enabled)),
    )
    gemini_key = st.text_input(
        "GEMINI_API_KEY",
        value="",
        type="password",
        placeholder="set" if public_runtime.get("GEMINI_API_KEY") else "not set",
    )
    gemini_base = st.text_input(
        "GEMINI_BASE_URL",
        value=str(runtime.get("GEMINI_BASE_URL") or config.GEMINI_BASE_URL),
    )
    with st.expander("Advanced MCP settings"):
        mcp_phoenix_pkg = st.text_input(
            "MCP_PHOENIX_PACKAGE",
            value=str(runtime.get("MCP_PHOENIX_PACKAGE") or snapshot.mcp.phoenix_package),
        )
        mcp_elastic_pkg = st.text_input(
            "MCP_ELASTIC_PACKAGE",
            value=str(runtime.get("MCP_ELASTIC_PACKAGE") or snapshot.mcp.elastic_package),
        )
        mcp_timeout = st.number_input(
            "MCP_LOAD_TIMEOUT_SEC",
            min_value=5,
            max_value=180,
            value=int(runtime.get("MCP_LOAD_TIMEOUT_SEC") or snapshot.mcp.load_timeout_sec),
        )

with tab_summary:
    render_resolved_summary(snapshot)
    st.markdown("### Field sources")
    render_field_sources(
        snapshot.sources,
        [
            "PHOENIX_MODE",
            "PHOENIX_BASE_URL",
            "PHOENIX_CONSOLE_URL",
            "ELASTIC_MODE",
            "ELASTIC_URL",
            "MCP_ENABLED",
            "GEMINI_API_KEY",
        ],
    )

st.divider()
action1, action2, action3, action4 = st.columns(4)

pending_updates: dict[str, object] = {
    "PHOENIX_MODE": phoenix_mode,
    "ELASTIC_MODE": elastic_mode,
    "PHOENIX_BASE_URL": phoenix_base.strip(),
    "PHOENIX_CONSOLE_URL": phoenix_console.strip(),
    "PHOENIX_COLLECTOR_ENDPOINT": phoenix_collector.strip(),
    "PHOENIX_PROJECT_NAME": phoenix_project.strip(),
    "PHOENIX_PORT": int(phoenix_port),
    "ELASTIC_ENABLED": elastic_enabled,
    "ELASTIC_URL": elastic_url.strip(),
    "ELASTIC_INDEX_PREFIX": elastic_index.strip(),
    "ELASTIC_USERNAME": elastic_username.strip(),
    "MCP_ENABLED": mcp_enabled,
    "MCP_PHOENIX_ENABLED": mcp_phoenix,
    "MCP_ELASTIC_ENABLED": mcp_elastic,
    "GEMINI_BASE_URL": gemini_base.strip(),
    "MCP_PHOENIX_PACKAGE": mcp_phoenix_pkg,
    "MCP_ELASTIC_PACKAGE": mcp_elastic_pkg,
    "MCP_LOAD_TIMEOUT_SEC": int(mcp_timeout),
}
if phoenix_key.strip():
    pending_updates["PHOENIX_API_KEY"] = phoenix_key.strip()
if elastic_password.strip():
    pending_updates["ELASTIC_PASSWORD"] = elastic_password.strip()
if elastic_api_key.strip():
    pending_updates["ELASTIC_API_KEY"] = elastic_api_key.strip()
if gemini_key.strip():
    pending_updates["GEMINI_API_KEY"] = gemini_key.strip()

if action1.button("Save configuration", type="primary"):
    merged_runtime = {**load_runtime_config(), **pending_updates}
    trial = preview_settings(merged_runtime)
    errors, warnings = validate(trial)
    if errors:
        render_validation_results(errors, warnings)
    else:
        save_runtime_config(pending_updates)
        reload()
        config.reload()
        reset_mcp_tools()
        st.success("Configuration saved. MCP package changes may require restarting the UI container.")
        if warnings:
            render_validation_results([], warnings)
        st.rerun()

if action2.button("Reset to environment"):
    clear_runtime_config()
    reload()
    config.reload()
    reset_mcp_tools()
    st.success("Runtime overrides cleared. Active values now come from environment defaults.")
    st.rerun()

if action3.button("Run validation"):
    errors, warnings = validate(get_snapshot())
    render_validation_results(errors, warnings)

if action4.button("Export .env snippet"):
    snippet = export_env_snippet(get_snapshot().raw)
    st.code(snippet, language="bash")
