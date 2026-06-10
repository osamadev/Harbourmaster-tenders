"""Review History page for browsing persisted contract reviews."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

import pandas as pd
import streamlit as st

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.utils.render import (  # noqa: E402
    display_clauses,
    display_compliance_findings,
    display_counter_clauses,
    display_findings,
    display_inspection_reports,
    display_specialist_findings,
    display_verifier_notes,
)
from harbourmaster import config  # noqa: E402
from harbourmaster.reviews import delete_review, list_reviews, load_review  # noqa: E402


def _summary_markdown(review: dict) -> str:
    decision = review.get("review_decision", {}).get("decision", "auto-approved")
    findings = review.get("findings", {}).get("findings", [])
    lines = [
        f"# Contract Review: {review.get('title', 'Untitled')}",
        "",
        f"- Review ID: `{review.get('id', '')}`",
        f"- Created At: `{review.get('created_at', '')}`",
        f"- Decision: `{decision}`",
        f"- Overall Risk: `{float(review.get('overall_risk', 0.0)):.2f}`",
        f"- Guard Blocked: `{'yes' if review.get('blocked') else 'no'}`",
        f"- Findings: `{len(findings)}`",
        "",
        "## Draft Summary",
        "",
        str(review.get("draft_summary", "(none)")).strip() or "(none)",
    ]
    return "\n".join(lines) + "\n"


st.set_page_config(page_title="Review History", page_icon="🗂️", layout="wide")
st.title("Review History")
st.caption("Browse, inspect, download, and manage saved contract review records.")

reviews = list_reviews()
if not reviews:
    st.info("No saved reviews yet. Complete a review on the Home page to populate history.")
    with st.sidebar:
        st.markdown("### Review History")
        from app.utils.nav import render_sidebar_nav

        render_sidebar_nav()
    st.stop()

decisions = [str(row.get("decision", "auto-approved")) for row in reviews]
risks = [float(row.get("overall_risk", 0.0)) for row in reviews]
approved_count = sum(1 for d in decisions if d == "approve")
rejected_count = sum(1 for d in decisions if d == "reject")
auto_count = sum(1 for d in decisions if d == "auto-approved")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Reviews", len(reviews))
c2.metric("Avg Risk", f"{mean(risks):.2f}" if risks else "0.00")
c3.metric("Approved / Rejected", f"{approved_count} / {rejected_count}")
c4.metric("Auto-approved", auto_count)

st.divider()
st.markdown("### Filters")
decision_options = sorted({d for d in decisions if d})
fcol1, fcol2, fcol3 = st.columns([2, 2, 3])
with fcol1:
    selected_decisions = st.multiselect("Decision", decision_options, default=decision_options)
with fcol2:
    min_risk = st.slider("Min Risk", 0.0, 1.0, 0.0, 0.05)
with fcol3:
    title_query = st.text_input("Search Title", placeholder="Type text to filter review titles")

filtered = [
    row
    for row in reviews
    if row.get("decision") in selected_decisions
    and float(row.get("overall_risk", 0.0)) >= min_risk
    and title_query.lower().strip() in str(row.get("title", "")).lower()
]

if not filtered:
    st.warning("No reviews match the selected filters.")
    st.stop()

rows = []
for row in filtered:
    rows.append(
        {
            "Created": row.get("created_at", ""),
            "Title": row.get("title", ""),
            "Risk": float(row.get("overall_risk", 0.0)),
            "Decision": row.get("decision", "auto-approved"),
            "Findings": int(row.get("finding_count", 0)),
            "Review ID": row.get("id", ""),
        }
    )

st.markdown("### Saved Reviews")
df = pd.DataFrame(rows).sort_values(by="Created", ascending=False)
st.dataframe(df, use_container_width=True, hide_index=True)
selected_review_id = st.selectbox(
    "Select Review",
    options=df["Review ID"].tolist(),
    index=0,
)

review = load_review(selected_review_id)
st.divider()
st.markdown(f"## {review.get('title', 'Untitled contract review')}")
st.caption(f"Review ID: `{review.get('id', '')}` • Created: `{review.get('created_at', '')}`")

m1, m2, m3, m4 = st.columns(4)
decision = review.get("review_decision", {}).get("decision", "auto-approved")
m1.metric("Overall Risk", f"{float(review.get('overall_risk', 0.0)):.2f}")
m2.metric("Decision", str(decision).title())
m3.metric("Guard Blocked", "Yes" if review.get("blocked") else "No")
m4.metric("Inspection Reports", len(review.get("inspection_reports", [])))

st.markdown("### Draft Summary")
st.markdown(review.get("draft_summary", "(no summary produced)"))

st.markdown("### Verified Findings")
display_findings(review.get("findings", {}))
st.markdown("### Compliance Findings")
display_compliance_findings(review.get("findings", {}))
display_clauses(review.get("clauses", []))
display_specialist_findings(review.get("specialist_findings", {}))
display_verifier_notes(review.get("verifier_notes", []))
display_counter_clauses(review.get("counter_clauses", []))

reports = review.get("inspection_reports", [])
if reports:
    st.markdown("### Governance Inspection Reports")
    display_inspection_reports(reports)

with st.expander("Original Tender Text", expanded=False):
    st.text(review.get("tender_text", ""))
    if review.get("tender_text_truncated"):
        st.caption("Tender text was truncated when saved.")

st.divider()
action_col1, action_col2, action_col3 = st.columns(3)
with action_col1:
    st.download_button(
        "Download JSON",
        data=json.dumps(review, indent=2, ensure_ascii=True),
        file_name=f"{review.get('id', 'review')}.json",
        mime="application/json",
    )
with action_col2:
    st.download_button(
        "Download Summary (Markdown)",
        data=_summary_markdown(review),
        file_name=f"{review.get('id', 'review')}.md",
        mime="text/markdown",
    )
with action_col3:
    if st.button("Delete Review", type="secondary"):
        if delete_review(selected_review_id):
            st.success(f"Deleted review `{selected_review_id}`")
            st.rerun()
        st.error(f"Could not delete review `{selected_review_id}`")

with st.sidebar:
    st.markdown("### Review History")
    st.metric("Saved Reviews", len(reviews))
    from app.utils.nav import render_sidebar_nav

    render_sidebar_nav()
