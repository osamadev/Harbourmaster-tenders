"""Corporate Policies manager page."""

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.utils.auth import require_auth  # noqa: E402
from app.utils.layout import init_page, inject_theme_css, render_app_sidebar  # noqa: E402
from harbourmaster.ingest import extract_text  # noqa: E402
from harbourmaster.policies import (  # noqa: E402
    ALLOWED_SCOPE_TAGS,
    active_policies,
    delete_policy,
    list_policies,
    load_policy,
    save_policy,
)

init_page(
    "Corporate Policies",
    icon="📚",
    subtitle="Define and maintain internal policy rules used by the compliance specialist.",
)
require_auth()

def _refresh() -> None:
    st.rerun()


policies = list_policies()
active_count = len(active_policies())


def _policies_sidebar() -> None:
    st.metric("Stored Policies", len(policies))
    st.metric("Active Policies", active_count)


render_app_sidebar("policies", extra_blocks=_policies_sidebar)

col1, col2 = st.columns(2)
col1.metric("Stored policies", len(policies))
col2.metric("Active policies", active_count)

st.divider()
st.markdown("### Existing Policies")

if not policies:
    st.info("No saved policies yet. Create one below.")
else:
    for policy in policies:
        title = policy.get("title", "Untitled")
        pid = policy.get("id", "policy")
        version = policy.get("version", "1.0")
        scopes = ", ".join(policy.get("scope_tags", [])) or "all"
        is_active = bool(policy.get("active"))
        chip_cls = "hm-chip-ok" if is_active else "hm-chip-neutral"
        status_label = "active" if is_active else "inactive"
        inject_theme_css()
        st.markdown(
            f'**{title}** (`{pid}`) <span class="hm-chip {chip_cls}">{status_label}</span>',
            unsafe_allow_html=True,
        )
        st.caption(f"v{version} · Scope: {scopes}")
        with st.expander("View policy body", expanded=False):
            st.write(policy.get("body", ""))

            edit_col, del_col = st.columns(2)
            if edit_col.button(f"Edit {pid}", key=f"edit-{pid}"):
                st.session_state["editing_policy_slug"] = pid
                _refresh()
            if del_col.button(f"Delete {pid}", key=f"delete-{pid}"):
                delete_policy(pid)
                st.success(f"Deleted policy `{pid}`")
                _refresh()

st.divider()
st.markdown("### Create or Edit Policy")

editing_slug = st.session_state.get("editing_policy_slug")
editing = None
if editing_slug:
    try:
        editing = load_policy(editing_slug)
    except FileNotFoundError:
        st.session_state.pop("editing_policy_slug", None)
        editing_slug = None

with st.form("policy_form", clear_on_submit=False):
    default_title = editing.get("title", "") if editing else ""
    default_version = editing.get("version", "1.0") if editing else "1.0"
    default_active = bool(editing.get("active", True)) if editing else True
    default_scopes = editing.get("scope_tags", []) if editing else []
    default_body = editing.get("body", "") if editing else ""

    title = st.text_input("Policy title", value=default_title, placeholder="e.g. Procurement Delegation Policy")
    version = st.text_input("Version", value=default_version)
    scope_tags = st.multiselect(
        "Scope tags",
        options=sorted(ALLOWED_SCOPE_TAGS),
        default=default_scopes,
        help="Which specialists should consider this policy.",
    )
    active = st.checkbox("Active", value=default_active)

    uploaded_pdf = st.file_uploader(
        "Optional PDF upload to populate policy body",
        type=["pdf"],
        key="policy_pdf_uploader",
    )
    policy_body = st.text_area(
        "Policy body",
        value=default_body,
        height=260,
        placeholder="Paste policy/procedure/regulation text here...",
    )

    submitted = st.form_submit_button("Save policy", type="primary")
    cancel_edit = st.form_submit_button("Cancel edit")

if cancel_edit:
    st.session_state.pop("editing_policy_slug", None)
    _refresh()

if submitted:
    if uploaded_pdf is not None:
        extracted = extract_text(uploaded_pdf)
        if extracted:
            policy_body = extracted

    if not title.strip():
        st.error("Policy title is required.")
    elif not policy_body.strip():
        st.error("Policy body is required.")
    else:
        payload = {
            "id": editing.get("id") if editing else title,
            "title": title,
            "version": version,
            "scope_tags": scope_tags,
            "active": active,
            "body": policy_body,
        }
        saved = save_policy(payload, slug=editing.get("id") if editing else None)
        st.success(f"Saved policy `{saved['id']}`")
        st.session_state.pop("editing_policy_slug", None)
        _refresh()
