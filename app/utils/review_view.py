"""Shared, tabbed renderer for tender-review results.

One presentation surface used by the Tender Review complete view, the HITL
human-review screen, and the Review History page — a persistent summary band plus
tabs (Overview / Findings / Counter-Clauses / Clauses / Governance / Document).
Pure presentation: it reads the result dict and renders; no workflow/state logic.
"""

from __future__ import annotations

import html as _html
from typing import Any

import streamlit as st

from app.utils.render import (
    display_clauses,
    display_counter_clauses,
    display_inspection_reports,
    display_verifier_notes,
    render_findings,
    render_tender_document,
    risk_chip,
    risk_meter,
    status_chip,
)


def _finding_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    items = list((result.get("findings") or {}).get("findings", []))
    if not items:
        for spec, rows in (result.get("specialist_findings") or {}).items():
            for row in rows or []:
                merged = dict(row)
                merged.setdefault("specialist", spec)
                items.append(merged)
    return items


def _decision_label(result: dict[str, Any]) -> str:
    if result.get("blocked"):
        return "Blocked"
    decision = result.get("review_decision") or {}
    if decision.get("decision"):
        return str(decision["decision"]).title()
    return "Auto-approved"


def _summary_band(result: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    """Decision/status chips + risk meter + a compact metric strip."""
    blocked = bool(result.get("blocked"))
    decision = _decision_label(result)
    dec_chip = (
        '<span class="hm-chip hm-chip-error">Blocked</span>'
        if blocked
        else f'<span class="hm-chip hm-chip-neutral">Decision: {_html.escape(decision)}</span>'
    )
    guard = result.get("guard_verdict")
    chips = [dec_chip]
    if guard:
        chips.append(status_chip(str(guard)))

    high = sum(1 for f in findings if str(f.get("risk_level", "")).lower() == "high")
    metrics = [
        ("Overall risk", f"{float(result.get('overall_risk', 0.0) or 0.0):.2f}"),
        ("High-risk", str(high)),
        ("Findings", str(len(findings))),
        ("Clauses", str(len(result.get("clauses", []) or []))),
        ("Counter-clauses", str(len(result.get("counter_clauses", []) or []))),
        ("Policies", str(len(result.get("corporate_policies", []) or []))),
    ]
    strip = "".join(
        f'<div class="hm-metric-pill"><div class="v">{_html.escape(v)}</div>'
        f'<div class="k">{_html.escape(k)}</div></div>'
        for k, v in metrics
    )
    st.markdown(
        '<div class="hm-card">'
        '<div class="hm-card-title">Review summary</div>'
        f'<div class="hm-chip-row">{"".join(chips)}</div>'
        f'{risk_meter(result.get("overall_risk")) if result.get("overall_risk") is not None else ""}'
        f'<div class="hm-metric-strip">{strip}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def _retrieval_context(result: dict[str, Any]) -> None:
    rows = result.get("retrieval_context") or []
    if not rows:
        return
    st.markdown("**Retrieved policy / precedent context**")
    for row in rows:
        title = row.get("match_title") or row.get("query_title") or "Match"
        match_type = row.get("match_type", "")
        body = str(row.get("body", ""))[:280]
        st.markdown(f"- **{_html.escape(str(title))}** · `{_html.escape(str(match_type))}`")
        if body:
            st.caption(body + ("…" if len(str(row.get("body", ""))) > 280 else ""))


def render_review_results(
    result: dict[str, Any],
    *,
    tender_text: str = "",
    mode: str = "complete",
) -> None:
    """Render review results as a summary band + content tabs.

    ``mode`` is informational (complete / review / history); the structure is the
    same. Only tabs with content are shown (a blocked review yields just
    Overview / Governance / Document).
    """
    result = result or {}
    blocked = bool(result.get("blocked"))
    findings = _finding_items(result)

    _summary_band(result, findings)

    # Build the tab set dynamically so empty sections don't create empty tabs.
    specs: list[tuple[str, str]] = [("overview", "Overview")]
    if not blocked and findings:
        specs.append(("findings", f"Findings ({len(findings)})"))
    if not blocked and result.get("counter_clauses"):
        specs.append(("counter", f"Counter-Clauses ({len(result['counter_clauses'])})"))
    if not blocked and (result.get("clauses") or result.get("retrieval_context")):
        specs.append(("clauses", "Clauses"))
    if result.get("inspection_reports") or result.get("verifier_notes"):
        specs.append(("governance", "Governance"))
    specs.append(("document", "Document"))

    tabs = st.tabs([label for _, label in specs])
    for tab, (key, _label) in zip(tabs, specs):
        with tab:
            if key == "overview":
                _render_overview(result, findings)
            elif key == "findings":
                _render_findings_tab(result, mode)
            elif key == "counter":
                display_counter_clauses(
                    result.get("counter_clauses", []), result.get("clauses", [])
                )
            elif key == "clauses":
                display_clauses(result.get("clauses", []))
                _retrieval_context(result)
            elif key == "governance":
                reports = result.get("inspection_reports", [])
                if reports:
                    st.markdown("#### Governance Inspection Reports")
                    display_inspection_reports(reports)
                notes = result.get("verifier_notes", [])
                if notes:
                    display_verifier_notes(notes)
            elif key == "document":
                render_tender_document(
                    tender_text,
                    title="Reviewed tender" if mode != "review" else "Original tender",
                    truncated=bool(result.get("tender_text_truncated")),
                    expanded=False,
                )


def _render_overview(result: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    if result.get("blocked"):
        st.error(
            f"⛔ Blocked by the governance guard — {result.get('block_reason', 'DENY')}"
        )
        st.caption("The input was denied at ingress; specialist analysis was not run.")

    st.markdown("#### Draft Summary")
    st.markdown(result.get("draft_summary", "(no summary produced)"))

    highs = [f for f in findings if str(f.get("risk_level", "")).lower() == "high"]
    if highs:
        st.markdown("#### Top high-risk findings")
        for f in highs[:3]:
            clause_id = f.get("clause_id", "N/A")
            clause = f.get("clause", "")
            st.markdown(
                f"{risk_chip('high')} **{_html.escape(str(clause_id))} · "
                f"{_html.escape(str(clause))}**",
                unsafe_allow_html=True,
            )
            rationale = str(f.get("rationale", "")).strip()
            if rationale:
                st.caption(rationale)
        if len(highs) > 3:
            st.caption(f"+ {len(highs) - 3} more high-risk finding(s) in the Findings tab.")


def _render_findings_tab(result: dict[str, Any], mode: str) -> None:
    options = ["Risk", "Specialist", "Clause"]
    key = f"findings-group-{mode}"
    if hasattr(st, "segmented_control"):
        group_by = st.segmented_control(
            "Group by", options, default="Risk", key=key
        )
    else:  # older Streamlit
        group_by = st.radio("Group by", options, horizontal=True, key=key)
    render_findings(
        result.get("findings", {}),
        result.get("specialist_findings", {}),
        group_by=group_by or "Risk",
    )
