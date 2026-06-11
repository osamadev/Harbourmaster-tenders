"""Shared Streamlit sidebar navigation."""

from __future__ import annotations

import streamlit as st

NAV_GROUPS: list[tuple[str, list[tuple[str, str, str, str]]]] = [
    (
        "Workflow",
        [
            ("home", "Home.py", "Tender Review", "⚓"),
            ("history", "pages/1_Review_History.py", "Review History", "🗂️"),
        ],
    ),
    (
        "Governance",
        [
            ("dashboard", "pages/2_Governance_Dashboard.py", "Governance Dashboard", "📊"),
            ("redteam", "pages/3_Red_Team_Scorecard.py", "Red-Team Scorecard", "🛡️"),
            ("copilot", "pages/5_Governance_Copilot.py", "Governance Copilot", "🧭"),
        ],
    ),
    (
        "Admin",
        [
            ("policies", "pages/4_Corporate_Policies.py", "Corporate Policies", "📚"),
            ("configuration", "pages/6_Configuration.py", "Configuration", "⚙️"),
        ],
    ),
]


def render_grouped_nav(current_page: str) -> None:
    """Render grouped page links with active-page highlighting."""
    if not hasattr(st, "page_link"):
        st.caption("Upgrade Streamlit to use in-app navigation.")
        return

    for group_name, items in NAV_GROUPS:
        st.markdown(f'<p class="hm-nav-group">{group_name}</p>', unsafe_allow_html=True)
        for page_id, path, label, icon in items:
            if page_id == current_page:
                st.markdown(
                    f'<p class="hm-nav-active">{icon} {label}</p>',
                    unsafe_allow_html=True,
                )
            else:
                st.page_link(path, label=label, icon=icon)


def render_sidebar_nav(
    *,
    current_page: str = "",
    home_label: str = "Tender Review",
    home_icon: str = "⚓",
    include_home: bool = True,
    include_phoenix_link: bool = True,
) -> None:
    """Legacy wrapper — prefer render_grouped_nav via layout.render_app_sidebar."""
    if include_phoenix_link:
        from app.utils.links import render_phoenix_console_link

        render_phoenix_console_link()
    if current_page:
        render_grouped_nav(current_page)
        return
    if hasattr(st, "page_link"):
        if include_home:
            st.page_link("Home.py", label=home_label, icon=home_icon)
        st.page_link("pages/1_Review_History.py", label="Review History", icon="🗂️")
        st.page_link("pages/2_Governance_Dashboard.py", label="Governance Dashboard", icon="📊")
        st.page_link("pages/3_Red_Team_Scorecard.py", label="Red-Team Scorecard", icon="🛡️")
        st.page_link("pages/4_Corporate_Policies.py", label="Corporate Policies", icon="📚")
        st.page_link("pages/5_Governance_Copilot.py", label="Governance Copilot", icon="🧭")
        st.page_link("pages/6_Configuration.py", label="Configuration", icon="⚙️")
