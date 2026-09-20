"""Governance Dashboard — regulator-readable view over Phoenix telemetry."""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.utils.audit import load_dataframe  # noqa: E402
from app.utils.auth import require_auth  # noqa: E402
from app.utils.layout import init_page, render_app_sidebar  # noqa: E402

init_page(
    "Governance Dashboard",
    icon="📊",
    subtitle="Phoenix traces + span attributes — real-time governance visibility",
)
require_auth()
df = load_dataframe()

if df.empty:
    render_app_sidebar("dashboard")
    st.warning(
        "No Phoenix telemetry found yet. Run at least one contract review from "
        "the Tender Review page, then refresh this dashboard."
    )
    if hasattr(st, "page_link"):
        st.page_link("Home.py", label="Go to Tender Review", icon="⚓")
    st.stop()

required_defaults = {
    "direction": "model_call",
    "action": "UNKNOWN",
    "agent_id": "unknown",
    "risk_score": 0.0,
    "has_explicit_risk": False,
    "has_mismatches": False,
    "intent_category": "",
    "rule_name": "",
    "timestamp": pd.NaT,
    "token_count": 0,
}
for col, default in required_defaults.items():
    if col not in df.columns:
        df[col] = default

def _dashboard_sidebar() -> None:
    st.markdown("### Filters")
    directions = sorted(df["direction"].dropna().unique().tolist())
    st.session_state.dash_directions = st.multiselect(
        "Direction", directions, default=directions, key="dash_dir"
    )
    actions = sorted(df["action"].dropna().unique().tolist())
    st.session_state.dash_actions = st.multiselect(
        "Action", actions, default=actions, key="dash_act"
    )
    agents = sorted(df["agent_id"].dropna().unique().tolist())
    st.session_state.dash_agents = st.multiselect(
        "Agent ID", agents, default=agents, key="dash_agents_sel"
    )
    st.session_state.dash_min_risk = st.slider(
        "Minimum risk score", 0.0, 1.0, 0.0, 0.05, key="dash_risk"
    )
    if st.button("Refresh data", use_container_width=True):
        st.rerun()


render_app_sidebar("dashboard", extra_blocks=_dashboard_sidebar)

sel_directions = st.session_state.get("dash_directions", sorted(df["direction"].dropna().unique().tolist()))
sel_actions = st.session_state.get("dash_actions", sorted(df["action"].dropna().unique().tolist()))
sel_agents = st.session_state.get("dash_agents", sorted(df["agent_id"].dropna().unique().tolist()))
min_risk = st.session_state.get("dash_min_risk", 0.0)

# Apply filters
mask = (
    df["direction"].isin(sel_directions)
    & df["action"].isin(sel_actions)
    & df["agent_id"].isin(sel_agents)
    & (df["risk_score"] >= min_risk)
)
filtered = df[mask].copy()
risk_filtered = filtered[filtered["has_explicit_risk"] == True].copy()  # noqa: E712
is_guard = (
    filtered["direction"].eq("guard")
    | filtered["agent_id"].isin(["governance-guard-v1", "harbourmaster.guard"])
)
denied_mask = filtered["action"].isin(["DENY", "QUARANTINE"])
guard_df = filtered[is_guard]
guard_denied_count = len(filtered[is_guard & denied_mask])
system_tool_denied_count = len(filtered[denied_mask & ~is_guard])

st.markdown("### Overview")
from harbourmaster.phoenix_audit import last_source  # noqa: E402

_src = last_source()
_src_label = {"mcp": "Phoenix MCP", "rest": "REST (MCP fallback)"}.get(_src, _src)
st.caption(f"Telemetry source: **{_src_label}**")

total = len(filtered)
blocked = len(filtered[filtered["action"].isin(["DENY", "QUARANTINE"])])
allowed = len(filtered[filtered["action"] == "ALLOW"])
logged = len(filtered[filtered["action"] == "LOG"])
risk_rows = len(risk_filtered)
avg_risk = risk_filtered["risk_score"].mean() if risk_rows > 0 else 0.0
mismatch_count = filtered["has_mismatches"].sum() if total > 0 else 0

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("Total Entries", total)
c2.metric("Denied", blocked)
c3.metric("Allowed", allowed)
c4.metric("Logged", logged)
c5.metric("Avg Risk", f"{avg_risk:.3f}")
c6.metric("Mismatches", int(mismatch_count))
c7.metric("Risk-bearing Spans", risk_rows)

st.divider()
st.markdown("### Filters")
f1, f2, f3, f4 = st.columns(4)
f1.caption(f"Directions: {len(sel_directions)}")
f2.caption(f"Actions: {len(sel_actions)}")
f3.caption(f"Agents: {len(sel_agents)}")
f4.caption(f"Min risk: {min_risk:.2f}")

st.divider()
st.markdown("### Charts")
chart_left, chart_right = st.columns(2)

with chart_left:
    st.markdown("#### Action Distribution")
    action_counts = filtered["action"].value_counts().reset_index()
    action_counts.columns = ["Action", "Count"]
    colour_map = {
        "ALLOW": "#2ecc71",
        "DENY": "#e74c3c",
        "QUARANTINE": "#e67e22",
        "LOG": "#3498db",
        "HUMAN_REVIEW": "#9b59b6",
    }
    fig_pie = px.pie(
        action_counts,
        names="Action",
        values="Count",
        color="Action",
        color_discrete_map=colour_map,
    )
    fig_pie.update_layout(template="plotly_white", margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig_pie, use_container_width=True)

with chart_right:
    st.markdown("#### Risk Score Distribution")
    if risk_filtered.empty:
        st.info("No spans with explicit risk metadata in the current filter.")
    else:
        fig_hist = px.histogram(
            risk_filtered,
            x="risk_score",
            nbins=20,
            color="direction",
            barmode="overlay",
            labels={"risk_score": "Risk Score"},
        )
        fig_hist.update_layout(template="plotly_white", margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_hist, use_container_width=True)

def _category_counts(frame: pd.DataFrame) -> dict[str, int]:
    return (
        frame["intent_category"]
        .fillna("")
        .str.split(",")
        .explode()
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .value_counts()
        .to_dict()
    )


st.markdown("#### Guard Categories (Guard Spans)")
st.caption(f"Guard spans in filter: {len(guard_df)}")
guard_denied_df = guard_df[guard_df["action"].isin(["DENY", "QUARANTINE"])]
category_source = guard_denied_df
category_caption = "Categories from guard-denied spans."
if category_source.empty and not guard_df.empty:
    category_source = guard_df
    category_caption = (
        "No guard-denied spans in filter; showing categories from all guard spans "
        "(ALLOW / HUMAN_REVIEW / DENY)."
    )

if category_source.empty:
    st.info("No guard spans in the current filter.")
else:
    attack_counts = _category_counts(category_source)
    if attack_counts:
        st.caption(category_caption)
        attack_df = pd.DataFrame(
            {"Attack Type": list(attack_counts.keys()), "Count": list(attack_counts.values())}
        )
        fig_bar = px.bar(
            attack_df,
            y="Attack Type",
            x="Count",
            orientation="h",
            color="Count",
            color_continuous_scale="Reds",
        )
        fig_bar.update_layout(template="plotly_white", margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("No guard spans with categories in the current filter.")

# Timeline
if "timestamp" in risk_filtered.columns and risk_filtered["timestamp"].notna().any():
    st.markdown("#### Request Timeline")
    fig_timeline = px.scatter(
        risk_filtered.dropna(subset=["timestamp"]),
        x="timestamp",
        y="risk_score",
        color="action",
        color_discrete_map=colour_map,
        hover_data=["agent_id", "direction", "rule_name"],
        labels={"timestamp": "Time", "risk_score": "Risk Score"},
    )
    fig_timeline.update_layout(template="plotly_white", margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig_timeline, use_container_width=True)
else:
    st.info("No risk-bearing timeline points for this filter.")

st.markdown("#### System / Tool Denied Events")
denial_col1, denial_col2 = st.columns(2)
denial_col1.metric("Guard Denied", guard_denied_count)
denial_col2.metric("System / Tool Denied", system_tool_denied_count)

tool_denials = filtered[denied_mask & ~is_guard]
if tool_denials.empty:
    st.info("No system/tool denied events in the current filter.")
else:
    st.dataframe(
        tool_denials[["timestamp", "agent_id", "direction", "action", "rule_name"]],
        use_container_width=True,
        height=220,
    )

# ---------------------------------------------------------------------------
# Raw audit log table
# ---------------------------------------------------------------------------
st.markdown("#### Trace/Span Log")
display_cols = [
    "timestamp", "direction", "action", "rule_name", "agent_id",
    "risk_score", "intent_category", "has_mismatches", "token_count",
]
available_cols = [c for c in display_cols if c in filtered.columns]
st.dataframe(filtered[available_cols], use_container_width=True, height=400)

# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
csv = filtered.to_csv(index=False)
st.download_button(
    "Download filtered log as CSV",
    data=csv,
    file_name="harbourmaster_audit_log.csv",
    mime="text/csv",
)
