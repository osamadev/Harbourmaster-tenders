"""Shared Streamlit render helpers for review pages."""

from __future__ import annotations

import difflib
import html as _html
import re
from typing import Any

import streamlit as st


def _inline_redline(original: str, revised: str) -> str:
    """Word-level track-changes HTML: deletions struck-through (red), insertions (green)."""
    a = re.findall(r"\S+\s*", original or "")
    b = re.findall(r"\S+\s*", revised or "")
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        old = _html.escape("".join(a[i1:i2]))
        new = _html.escape("".join(b[j1:j2]))
        if tag == "equal":
            parts.append(new)
        elif tag == "delete":
            parts.append(f'<del class="hm-red-del">{old}</del>')
        elif tag == "insert":
            parts.append(f'<ins class="hm-red-ins">{new}</ins>')
        elif tag == "replace":
            parts.append(f'<del class="hm-red-del">{old}</del><ins class="hm-red-ins">{new}</ins>')
    return "".join(parts)


def risk_label(level: str) -> str:
    colours = {"high": "🔴", "medium": "🟠", "low": "🟢"}
    return f"{colours.get(level, '⚪')} {level}"


def render_tender_document(
    text: str,
    *,
    title: str = "Original tender document",
    truncated: bool = False,
    expanded: bool = False,
    height: int = 460,
) -> None:
    """Collapsible, scrollable, markdown-rendered viewer for a tender document.

    Renders the document as formatted markdown (headings/clauses) inside a fixed-height
    scrollable card, with a header showing a character count, a truncation note, and a
    raw-text toggle.
    """
    text = (text or "").strip()
    if not text:
        st.info("No tender text available.")
        return

    suffix = " · truncated when saved" if truncated else ""
    with st.expander(f"📄 {title} · {len(text):,} characters{suffix}", expanded=expanded):
        show_raw = st.toggle("Raw text", value=False, key=f"tender-raw-{abs(hash((title, text[:64])))}")
        with st.container(height=height, border=True):
            if show_raw:
                st.code(text, language="markdown")
            else:
                st.markdown(text)


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


_RISK_ORDER = {"high": 0, "medium": 1, "low": 2}
_SPECIALIST_LABELS = {
    "legal": "Legal",
    "financial": "Financial",
    "delivery": "Delivery",
    "ip_data": "IP & Data",
    "compliance": "Compliance",
}


def _finding_card(finding: dict[str, Any], *, show_specialist: bool = True) -> None:
    """Render a single finding as a chip-decorated card."""
    level = str(finding.get("risk_level", "unknown")).lower()
    clause = finding.get("clause", "Unknown clause")
    clause_id = finding.get("clause_id", "N/A")
    specialist = str(finding.get("specialist", "general"))
    rationale = str(finding.get("rationale", "")).strip()
    evidence = str(finding.get("evidence_quote", "")).strip()
    policy_id = str(finding.get("policy_id", "")).strip()
    policy_reference = str(finding.get("policy_reference", "")).strip()

    chips = [risk_chip(level)]
    if show_specialist:
        spec_label = _SPECIALIST_LABELS.get(specialist, specialist)
        chips.append(f'<span class="hm-chip hm-chip-neutral">{_html.escape(spec_label)}</span>')
    if policy_id:
        chips.append(f'<span class="hm-chip hm-chip-neutral">📘 {_html.escape(policy_id)}</span>')

    st.markdown(
        f'<div class="hm-finding">'
        f'<div class="hm-finding-head">'
        f'<span class="hm-finding-clause">{_html.escape(str(clause_id))} · {_html.escape(str(clause))}</span>'
        f'<span class="hm-chip-row">{"".join(chips)}</span>'
        f"</div></div>",
        unsafe_allow_html=True,
    )
    if rationale:
        st.write(rationale)
    if evidence:
        st.caption(f'Evidence: "{evidence}"')
    if policy_reference:
        st.caption(f'Policy reference: "{policy_reference}"')


def render_findings(
    findings: dict[str, Any],
    specialist_findings: dict[str, list[dict[str, Any]]] | None = None,
    *,
    group_by: str = "Risk",
) -> None:
    """Unified findings view grouped by Risk, Specialist, or Clause.

    Replaces the old display_findings / display_compliance_findings /
    display_specialist_findings trio — every finding is shown once, with risk +
    specialist + policy chips. Compliance policy info renders inline.
    """
    items = list(findings.get("findings", []) if isinstance(findings, dict) else [])
    # Fall back to specialist_findings when the merged list is empty (e.g. HITL payload).
    if not items and specialist_findings:
        for spec, rows in specialist_findings.items():
            for row in rows or []:
                merged = dict(row)
                merged.setdefault("specialist", spec)
                items.append(merged)
    if not items:
        st.info("No findings reported.")
        return

    if group_by == "Specialist":
        groups: dict[str, list[dict[str, Any]]] = {}
        for f in items:
            groups.setdefault(str(f.get("specialist", "general")), []).append(f)
        for spec in sorted(groups):
            label = _SPECIALIST_LABELS.get(spec, spec)
            with st.expander(f"{label} ({len(groups[spec])})", expanded=True):
                for f in groups[spec]:
                    _finding_card(f, show_specialist=False)
    elif group_by == "Clause":
        groups = {}
        for f in items:
            groups.setdefault(str(f.get("clause_id", "N/A")), []).append(f)
        for cid in sorted(groups):
            clause_title = str(groups[cid][0].get("clause", "")).strip()
            header = f"{cid} — {clause_title}" if clause_title else cid
            with st.expander(f"{header} ({len(groups[cid])})", expanded=True):
                for f in groups[cid]:
                    _finding_card(f)
    else:  # Risk (default)
        ordered = sorted(items, key=lambda f: _RISK_ORDER.get(str(f.get("risk_level", "")).lower(), 3))
        for f in ordered:
            _finding_card(f)


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


def display_counter_clauses(
    counter_clauses: list[dict[str, Any]],
    clauses: list[dict[str, Any]] | None = None,
) -> None:
    if not counter_clauses:
        st.info("No counter-clause proposals generated.")
        return

    clause_map = {str(c.get("id", "")): c for c in (clauses or []) if isinstance(c, dict)}
    st.markdown("### Proposed Counter-Clauses")
    st.markdown(
        '<span class="hm-red-legend"><del class="hm-red-del">removed</del> '
        '<ins class="hm-red-ins">added</ins></span>',
        unsafe_allow_html=True,
    )
    for row in counter_clauses:
        clause_id = str(row.get("clause_id", "N/A"))
        redline = row.get("proposed_redline", "")
        justification = row.get("justification", "")
        source = clause_map.get(clause_id, {})
        original = str(source.get("text", ""))
        title = str(source.get("title", "")).strip()
        header = f"Counter-clause for {clause_id}" + (f" — {title}" if title else "")
        with st.expander(header, expanded=False):
            if original and redline:
                st.markdown("**Redline — original → proposed**")
                st.markdown(
                    f'<div class="hm-red-doc">{_inline_redline(original, redline)}</div>',
                    unsafe_allow_html=True,
                )
                with st.expander("Proposed text only", expanded=False):
                    st.write(redline)
            else:
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
        agent_id = report.get("agent_id", "N/A")
        with st.expander(f"#{i} · {agent_id} — {verdict}", expanded=False):
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
            if st.toggle("Raw report", value=False, key=f"insp-raw-{i}-{abs(hash(str(agent_id)))}"):
                st.json(report)
