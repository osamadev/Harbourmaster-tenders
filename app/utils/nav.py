"""Shared Streamlit sidebar navigation."""

from __future__ import annotations

import streamlit as st

from app.utils.links import render_phoenix_console_link


def render_sidebar_nav(
    *,
    home_label: str = "Tender Review",
    home_icon: str = "⚓",
    include_home: bool = True,
    include_phoenix_link: bool = True,
) -> None:
    """Render common sidebar page links and Phoenix console link."""
    if include_phoenix_link:
        render_phoenix_console_link()
    if hasattr(st, "page_link"):
        if include_home:
            st.page_link("Home.py", label=home_label, icon=home_icon)
        st.page_link("pages/1_Review_History.py", label="Review History", icon="🗂️")
        st.page_link("pages/2_Governance_Dashboard.py", label="Governance Dashboard", icon="📊")
        st.page_link("pages/3_Red_Team_Scorecard.py", label="Red-Team Scorecard", icon="🛡️")
        st.page_link("pages/4_Corporate_Policies.py", label="Corporate Policies", icon="📚")
        st.page_link("pages/5_Governance_Copilot.py", label="Governance Copilot", icon="🧭")
        st.page_link("pages/6_Configuration.py", label="Configuration", icon="⚙️")
