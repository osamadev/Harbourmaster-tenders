"""Shared Streamlit render helpers for review pages."""

from __future__ import annotations

from typing import Any

import streamlit as st


def risk_label(level: str) -> str:
    colours = {"high": "🔴", "medium": "🟠", "low": "🟢"}
    return f"{colours.get(level, '⚪')} {level}"


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
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Governance**")
                st.metric("Risk Score", f"{float(report.get('risk_score', 0.0)):.2f}")
                categories = report.get("categories", [])
                st.write(f"Categories: {', '.join(categories) if categories else 'none'}")
                if report.get("reason"):
                    st.caption(report["reason"])
            with col2:
                st.markdown("**Agent Context**")
                st.write(f"Agent: {report.get('agent_id', 'N/A')}")
                st.write(f"Intent: {report.get('declared_intent', 'N/A')}")
            st.json(report)
