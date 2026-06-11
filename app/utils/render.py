"""Shared Streamlit render helpers for review pages."""

from __future__ import annotations

from typing import Any

import streamlit as st


def risk_label(level: str) -> str:
    colours = {"high": "🔴", "medium": "🟠", "low": "🟢"}
    return f"{colours.get(level, '⚪')} {level}"


def risk_meter(value: float | None, threshold: float = 0.6) -> str:
    """Return an HTML risk meter: track + banded fill + threshold tick + value.

    Colour bands: low (<0.4) green, medium (<0.7) amber, high red. Relies on the
    ``.hm-meter*`` classes injected by ``layout.inject_theme_css``.
    """
    try:
        val = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return ""
    colour = "#16A34A" if val < 0.4 else "#D97706" if val < 0.7 else "#DC2626"
    pct = val * 100
    tick = max(0.0, min(1.0, threshold)) * 100
    return (
        '<div class="hm-meter">'
        '<span class="hm-meter-cap">Risk</span>'
        '<div class="hm-meter-track">'
        f'<div class="hm-meter-fill" style="width:{pct:.1f}%;background:{colour};"></div>'
        f'<div class="hm-meter-tick" style="left:{tick:.1f}%;" title="threshold"></div>'
        "</div>"
        f'<span class="hm-meter-val">{val:.2f}</span>'
        "</div>"
    )


def render_risk_meter(value: float | None, threshold: float = 0.6) -> None:
    html = risk_meter(value, threshold)
    if html:
        st.markdown(html, unsafe_allow_html=True)


def risk_chip(level: str) -> str:
    cls = {
        "high": "hm-chip-error",
        "medium": "hm-chip-warn",
        "low": "hm-chip-ok",
    }.get(str(level).lower(), "hm-chip-neutral")
    return f'<span class="hm-chip {cls}">{level}</span>'


def status_chip(action: str) -> str:
    cls = {
        "ALLOW": "hm-chip-ok",
        "HUMAN_REVIEW": "hm-chip-warn",
        "DENY": "hm-chip-error",
        "QUARANTINE": "hm-chip-error",
        "LOG": "hm-chip-neutral",
    }.get(str(action).upper(), "hm-chip-neutral")
    return f'<span class="hm-chip {cls}">{action}</span>'


def render_risk_chip(level: str) -> None:
    st.markdown(risk_chip(level), unsafe_allow_html=True)


def render_status_chip(action: str) -> None:
    st.markdown(status_chip(action), unsafe_allow_html=True)


def display_clauses(clauses: list[dict[str, Any]]) -> None:
    if not clauses:
        st.info("No clause segmentation available.")
        return
    with st.expander("Segmented clauses", expanded=False):
        for clause in clauses:
            cid = clause.get("id", "N/A")
            title = clause.get("title", "Clause")
            text = str(clause.get("text", ""))
            st.markdown(f"**{cid} — {title}**")
            st.caption(text[:400] + ("..." if len(text) > 400 else ""))


def display_findings(findings: dict[str, Any]) -> None:
    items = findings.get("findings", [])
    if not items:
        st.info("No specific findings reported.")
        return

    for finding in items:
        level = str(finding.get("risk_level", "unknown"))
        clause = finding.get("clause", "Unknown clause")
        clause_id = finding.get("clause_id", "N/A")
        specialist = finding.get("specialist", "general")
        rationale = str(finding.get("rationale", ""))
        evidence = str(finding.get("evidence_quote", ""))

        st.markdown(f"**{risk_label(level)}** — **{clause_id}: {clause}** (`{specialist}`)")
        if rationale:
            st.write(rationale)
        if evidence:
            st.caption(f'Evidence: "{evidence}"')


def display_compliance_findings(findings: dict[str, Any]) -> None:
    items = [f for f in findings.get("findings", []) if f.get("specialist") == "compliance"]
    if not items:
        st.info("No compliance findings reported.")
        return

    for finding in items:
        clause_id = finding.get("clause_id", "N/A")
        clause = finding.get("clause", "Unknown clause")
        level = str(finding.get("risk_level", "unknown"))
        policy_id = finding.get("policy_id", "N/A")
        rationale = str(finding.get("rationale", ""))
        evidence = str(finding.get("evidence_quote", ""))
        policy_reference = str(finding.get("policy_reference", ""))

        st.markdown(f"**{risk_label(level)}** — **{clause_id}: {clause}**")
        st.write(f"Policy: `{policy_id}`")
        if rationale:
            st.write(rationale)
        if evidence:
            st.caption(f'Evidence: "{evidence}"')
        if policy_reference:
            st.caption(f'Policy reference: "{policy_reference}"')


def display_specialist_findings(specialist_findings: dict[str, list[dict[str, Any]]]) -> None:
    if not specialist_findings:
        st.info("No specialist outputs available.")
        return

    st.markdown("### Specialist Findings")
    for specialist, items in specialist_findings.items():
        with st.expander(f"{specialist} ({len(items)})", expanded=False):
            if not items:
                st.write("No findings from this specialist.")
                continue
            for finding in items:
                clause_id = finding.get("clause_id", "N/A")
                clause = finding.get("clause", "Clause")
                level = finding.get("risk_level", "unknown")
                rationale = str(finding.get("rationale", ""))
                evidence = str(finding.get("evidence_quote", ""))
                st.markdown(f"- **{clause_id} {clause}** [{level}] — {rationale}")
                if evidence:
                    st.caption(f'Evidence: "{evidence}"')


def display_verifier_notes(verifier_notes: list[dict[str, Any]]) -> None:
    if not verifier_notes:
        st.info("No verifier annotations captured.")
        return
    st.markdown("### Verifier Notes")
    for note in verifier_notes:
        specialist = note.get("specialist", "unknown")
        clause_id = note.get("clause_id", "N/A")
        action = note.get("action", "keep")
        reason = note.get("reason", "")
        st.markdown(f"- `{action}` — **{specialist} / {clause_id}**: {reason}")


def display_counter_clauses(counter_clauses: list[dict[str, Any]]) -> None:
    if not counter_clauses:
        st.info("No counter-clause proposals generated.")
        return

    st.markdown("### Proposed Counter-Clauses")
    for row in counter_clauses:
        clause_id = row.get("clause_id", "N/A")
        redline = row.get("proposed_redline", "")
        justification = row.get("justification", "")
        with st.expander(f"Counter-clause for {clause_id}", expanded=False):
            st.markdown("**Proposed redline**")
            st.write(redline or "(none)")
            st.markdown("**Justification**")
            st.write(justification or "(none)")


def display_inspection_reports(reports: list[dict[str, Any]]) -> None:
    if not reports:
        st.info("No inspection reports captured.")
        return
    for i, report in enumerate(reports, 1):
        verdict = report.get("verdict", "UNKNOWN")
        with st.expander(f"Inspection Report #{i} — Verdict: {verdict}"):
            st.markdown(status_chip(verdict), unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Governance**")
                render_risk_meter(float(report.get("risk_score", 0.0)))
                categories = report.get("categories", [])
                st.write(f"Categories: {', '.join(categories) if categories else 'none'}")
                if report.get("reason"):
                    st.caption(report["reason"])
            with col2:
                st.markdown("**Agent Context**")
                st.write(f"Agent: {report.get('agent_id', 'N/A')}")
                st.write(f"Intent: {report.get('declared_intent', 'N/A')}")
            st.json(report)
