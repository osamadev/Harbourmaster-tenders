"""Render helpers for the Configuration page."""

from __future__ import annotations

from typing import Any

import streamlit as st

from harbourmaster.settings import ResolvedSettings


def render_source_badge(source: str) -> None:
    colors = {"env": "blue", "runtime": "green", "default": "gray"}
    st.caption(f"source: :{colors.get(source, 'gray')}[{source}]")


def render_validation_results(errors: list[str], warnings: list[str]) -> None:
    if errors:
        for item in errors:
            st.error(item)
    if warnings:
        for item in warnings:
            st.warning(item)
    if not errors and not warnings:
        st.success("Configuration validation passed.")


def render_resolved_summary(snapshot: ResolvedSettings) -> None:
    st.markdown("**Resolved Phoenix**")
    st.write(
        {
            "mode": snapshot.phoenix.mode,
            "api_base_url": snapshot.phoenix.api_base_url,
            "collector_endpoint": snapshot.phoenix.collector_endpoint,
            "console_url": snapshot.phoenix.console_url,
            "project_name": snapshot.phoenix.project_name,
            "project_id": snapshot.phoenix.project_id or "(resolve via API)",
            "api_key": "set" if snapshot.phoenix.api_key else "not set",
        }
    )
    st.markdown("**Resolved Elastic**")
    st.write(
        {
            "mode": snapshot.elastic.mode,
            "url": snapshot.elastic.url,
            "enabled": snapshot.elastic.enabled,
            "api_key": "set" if snapshot.elastic.api_key else "not set",
            "index_prefix": snapshot.elastic.index_prefix,
        }
    )
    st.markdown("**Resolved MCP**")
    st.write(
        {
            "enabled": snapshot.mcp.enabled,
            "phoenix_enabled": snapshot.mcp.phoenix_enabled,
            "elastic_enabled": snapshot.mcp.elastic_enabled,
            "phoenix_package": snapshot.mcp.phoenix_package,
            "elastic_package": snapshot.mcp.elastic_package,
        }
    )


def render_field_sources(sources: dict[str, str], keys: list[str]) -> None:
    for key in keys:
        source = sources.get(key, "default")
        cols = st.columns([2, 1])
        cols[0].markdown(f"`{key}`")
        with cols[1]:
            render_source_badge(source)


def field_source(snapshot: ResolvedSettings, key: str) -> str:
    return snapshot.sources.get(key, "default")


def secret_placeholder(snapshot: ResolvedSettings, key: str, *, is_set: bool) -> str:
    if not is_set:
        return "not set"
    return f"set via {field_source(snapshot, key)}"
