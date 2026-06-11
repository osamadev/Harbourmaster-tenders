"""Shared external link helpers for Streamlit sidebars."""

from __future__ import annotations

import html

import streamlit as st

from harbourmaster.phoenix_audit import phoenix_console_url


def render_external_link(label: str, url: str) -> None:
    """Render a markdown link that opens in a new browser tab."""
    safe_label = html.escape(label)
    safe_url = html.escape(url, quote=True)
    st.markdown(
        f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_label}</a>',
        unsafe_allow_html=True,
    )


def render_phoenix_console_link(label: str = "Phoenix Console") -> None:
    """Sidebar helper for the Phoenix project console."""
    render_external_link(label, phoenix_console_url())
