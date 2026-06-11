"""Harbourmaster Reviewer UI — the human-in-the-loop interface."""

import sys
import uuid
from pathlib import Path
from typing import Any

import streamlit as st
from langgraph.types import Command

_root = Path(__file__).resolve().parents[1]
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
from app.utils.workflow_progress import (  # noqa: E402
    WorkflowProgressTracker,
    stream_graph_run,
)
from harbourmaster.graph import graph  # noqa: E402
from harbourmaster.ingest import extract_text  # noqa: E402
from harbourmaster.policies import active_policies  # noqa: E402
from harbourmaster.reviews import list_reviews, save_review  # noqa: E402
from harbourmaster.telemetry import init_telemetry  # noqa: E402

SAMPLE_TENDER = _root / "data" / "sample_tender.md"

st.set_page_config(
    page_title="Harbourmaster",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Harbourmaster — Tender Review")
st.caption("Workflow governance control plane for agentic LLM tender review")
init_telemetry()

if "phase" not in st.session_state:
    st.session_state.phase = "idle"
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "run_config" not in st.session_state:
    st.session_state.run_config = None
if "interrupt_payload" not in st.session_state:
    st.session_state.interrupt_payload = None
if "final_result" not in st.session_state:
    st.session_state.final_result = None
if "tender_text" not in st.session_state:
    st.session_state.tender_text = ""
if "selected_policy_ids" not in st.session_state:
    st.session_state.selected_policy_ids = []
if "review_id" not in st.session_state:
    st.session_state.review_id = None
if "live_workflow" not in st.session_state:
    st.session_state.live_workflow = {}


def _render_phase_progress() -> None:
    phase_steps = ["idle", "processing", "awaiting_review", "complete"]
    labels = {
        "idle": "Submit",
        "processing": "Processing",
        "awaiting_review": "Human Review",
        "complete": "Complete",
    }
    current = st.session_state.phase
    if current == "analysing":
        current = "processing"
    if current not in phase_steps:
        current = "idle"
    progress = phase_steps.index(current) / (len(phase_steps) - 1)
    st.progress(progress, text=f"Phase: {labels[current]}")


def _render_history_link() -> None:
    if hasattr(st, "page_link"):
        st.page_link("pages/1_Review_History.py", label="Open Review History", icon="🗂️")
    else:
        st.markdown("Go to `Review History` from the left navigation.")


def _persist_completed_review(result: dict) -> None:
    thread_id = st.session_state.thread_id or f"review-{uuid.uuid4().hex[:8]}"
    saved = save_review(
        result=result,
        tender_text=st.session_state.tender_text,
        thread_id=thread_id,
    )
    st.session_state.review_id = saved.get("id")


def _reset() -> None:
    st.session_state.phase = "idle"
    st.session_state.thread_id = None
    st.session_state.run_config = None
    st.session_state.interrupt_payload = None
    st.session_state.final_result = None
    st.session_state.tender_text = ""
    st.session_state.selected_policy_ids = []
    st.session_state.review_id = None
    st.session_state.live_workflow = {}


def _run_workflow(
    inputs: Any,
    run_config: dict[str, Any],
    *,
    mode: str = "full",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    tracker = WorkflowProgressTracker(mode=mode)  # type: ignore[arg-type]
    tracker.mount()
    st.session_state.phase = "processing"
    st.session_state.live_workflow = tracker.sidebar_snapshot()

    final_state, interrupt_payload = stream_graph_run(
        graph,
        inputs,
        run_config,
        tracker,
        on_tick=lambda snap: st.session_state.update(live_workflow=snap),
    )

    st.session_state.live_workflow = tracker.sidebar_snapshot()
    return final_state, interrupt_payload


_render_phase_progress()

if st.session_state.phase == "idle":
    st.markdown("### Submit a tender document for review")
    st.caption("Upload a document or paste text to start the governed multi-agent workflow.")
    tab_paste, tab_upload, tab_sample = st.tabs(["Paste text", "Upload file", "Use sample"])
    tender_text = ""

    with tab_paste:
        tender_text = st.text_area(
            "Paste tender text below",
            height=300,
            placeholder="Paste the full tender / contract text here...",
        )

    with tab_upload:
        uploaded = st.file_uploader("Upload a tender document (.md / .txt / .pdf)", type=["md", "txt", "pdf"])
        if uploaded:
            tender_text = extract_text(uploaded)
            st.text_area("Preview", tender_text[:2000], height=200, disabled=True)

    with tab_sample:
        st.markdown(f"Load the built-in sample tender: `{SAMPLE_TENDER.name}`")
        if st.button("Load sample tender"):
            if SAMPLE_TENDER.exists():
                tender_text = SAMPLE_TENDER.read_text(encoding="utf-8")
                st.session_state.tender_text = tender_text
                st.success("Sample tender loaded.")
            else:
                st.error(f"Sample file not found: {SAMPLE_TENDER}")

    if st.session_state.tender_text and not tender_text:
        tender_text = st.session_state.tender_text

    policies = active_policies()
    policy_options = {p.get("id", ""): p for p in policies if p.get("id")}
    default_ids = [pid for pid in st.session_state.selected_policy_ids if pid in policy_options]
    if not default_ids:
        default_ids = list(policy_options.keys())
    selected_policy_ids = st.multiselect(
        "Active corporate policies",
        options=list(policy_options.keys()),
        default=default_ids,
        format_func=lambda pid: f"{pid} — {policy_options[pid].get('title', pid)}",
    )
    st.session_state.selected_policy_ids = selected_policy_ids

    st.divider()

    if st.button("Start Review", type="primary", disabled=not tender_text):
        thread_id = f"review-{uuid.uuid4().hex[:8]}"
        run_config = {"configurable": {"thread_id": thread_id}}
        st.session_state.tender_text = tender_text
        st.session_state.thread_id = thread_id
        st.session_state.run_config = run_config

        selected_policies = [policy_options[pid] for pid in selected_policy_ids if pid in policy_options]
        final_state, interrupt_payload = _run_workflow(
            {
                "tender_text": tender_text,
                "corporate_policies": selected_policies,
            },
            run_config,
            mode="full",
        )

        if interrupt_payload:
            st.session_state.phase = "awaiting_review"
            st.session_state.interrupt_payload = interrupt_payload
            st.rerun()

        st.session_state.phase = "complete"
        st.session_state.final_result = final_state or {}
        _persist_completed_review(st.session_state.final_result)
        st.rerun()

elif st.session_state.phase == "awaiting_review":
    payload = st.session_state.interrupt_payload or {}
    st.warning("Human oversight required — review findings and submit your decision.")

    overall_risk = payload.get("overall_risk", 0.0)
    blocked = payload.get("blocked", False)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Overall Risk", f"{overall_risk:.2f}")
    with col2:
        st.metric("Guard Blocked", "Yes" if blocked else "No")
    with col3:
        findings_list = payload.get("findings", {}).get("findings", [])
        high_count = sum(1 for f in findings_list if f.get("risk_level") == "high")
        st.metric("High-Risk Findings", high_count)
    with col4:
        st.metric("Policies Considered", len(payload.get("corporate_policies", [])))

    if blocked:
        st.error(f"Governance guard blocked this request: {payload.get('block_reason', 'unknown')}")

    st.divider()
    left, right = st.columns([3, 2])

    with left:
        st.markdown("### Aggregated Findings")
        display_findings(payload.get("findings", {}))
        st.markdown("### Compliance Findings")
        display_compliance_findings(payload.get("findings", {}))
        display_clauses(payload.get("clauses", []))
        display_specialist_findings(payload.get("specialist_findings", {}))
        display_verifier_notes(payload.get("verifier_notes", []))
        st.markdown("### Tender Text")
        with st.expander("View original tender", expanded=False):
            st.markdown(st.session_state.tender_text)

    with right:
        st.markdown("### Reviewer Decision")
        decision_choice = st.radio(
            "Decision",
            ["approve", "reject"],
            format_func=lambda x: "Approve — proceed to draft" if x == "approve" else "Reject — stop workflow",
            index=0,
        )
        reviewer_name = st.text_input("Reviewer name", value="reviewer")
        reviewer_note = st.text_area(
            "Notes for the drafter",
            placeholder="e.g. Refer unlimited indemnity to legal before signing.",
            height=120,
        )
        clause_notes = st.text_area(
            "Per-clause notes for negotiator (optional)",
            placeholder="e.g. C3: ask for capped LDs; C5: retain background IP ownership.",
            height=100,
        )

        if st.button("Submit Decision", type="primary"):
            decision = {
                "decision": decision_choice,
                "reviewer": reviewer_name,
                "note": reviewer_note,
                "clause_notes": clause_notes,
            }
            final_state, _ = _run_workflow(
                Command(resume=decision),
                st.session_state.run_config,
                mode="resume",
            )

            st.session_state.phase = "complete"
            st.session_state.final_result = final_state or {}
            _persist_completed_review(st.session_state.final_result)
            st.rerun()

elif st.session_state.phase == "complete":
    result = st.session_state.final_result or {}
    st.success("Review workflow complete.")
    if st.session_state.review_id:
        st.success(f"Review saved as `{st.session_state.review_id}` — view it in Review History.")
        _render_history_link()

    st.markdown("### Draft Summary")
    summary = result.get("draft_summary", "(no summary produced)")
    st.markdown(summary)
    st.divider()

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Overall Risk", f"{result.get('overall_risk', 0.0):.2f}")
    with col2:
        st.metric("Guard Blocked", "Yes" if result.get("blocked") else "No")
    with col3:
        reports = result.get("inspection_reports", [])
        st.metric("Inspection Reports", len(reports))
    with col4:
        decision = result.get("review_decision", {})
        st.metric("Decision", decision.get("decision", "auto-approved").title())
    with col5:
        st.metric("Policies Considered", len(result.get("corporate_policies", [])))

    findings = result.get("findings", {})
    if findings:
        st.markdown("### Verified Findings")
        display_findings(findings)
        st.markdown("### Compliance Findings")
        display_compliance_findings(findings)

    display_clauses(result.get("clauses", []))
    display_specialist_findings(result.get("specialist_findings", {}))
    display_verifier_notes(result.get("verifier_notes", []))
    display_counter_clauses(result.get("counter_clauses", []))

    reports = result.get("inspection_reports", [])
    if reports:
        st.markdown("### Governance Inspection Reports")
        display_inspection_reports(reports)

    st.divider()
    if st.button("Start New Review"):
        _reset()
        st.rerun()

with st.sidebar:
    st.markdown("### Harbourmaster")
    st.markdown(
        "Two-layer governance for agentic LLM tender review.\n\n"
        "- **Inline Guard** — conversation-layer risk gate\n"
        "- **Harbourmaster** — workflow-layer governor"
    )
    st.divider()
    st.markdown(f"**Status:** `{st.session_state.phase}`")
    if st.session_state.thread_id:
        st.markdown(f"**Thread:** `{st.session_state.thread_id}`")

    live = st.session_state.live_workflow or {}
    if live:
        st.markdown("### Live execution")
        st.markdown(f"**Step:** {live.get('current_step', '—')}")
        if live.get("guard_verdict"):
            st.markdown(f"**Guard:** `{live['guard_verdict']}`")
        st.markdown(
            f"**Specialists:** {live.get('specialists_done', 0)}/{live.get('specialists_total', 5)}"
        )
        if live.get("revision_round"):
            st.metric("Revision round", live.get("revision_round", 0))
        if live.get("overall_risk") is not None:
            st.metric("Overall risk", f"{float(live['overall_risk']):.2f}")

    st.metric("Saved Reviews", len(list_reviews()))
    st.divider()
    from app.utils.nav import render_sidebar_nav

    render_sidebar_nav(include_home=False)
