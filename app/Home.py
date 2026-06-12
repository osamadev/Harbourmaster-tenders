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

from app.utils.layout import (  # noqa: E402
    init_page,
    render_app_sidebar,
    render_phase_stepper,
    render_summary_card,
)
from app.utils.auth import require_auth  # noqa: E402
from app.utils.render import (  # noqa: E402
    display_clauses,
    display_compliance_findings,
    display_counter_clauses,
    display_findings,
    display_inspection_reports,
    display_specialist_findings,
    display_verifier_notes,
    render_tender_document,
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

SAMPLE_TENDERS = {
    "Human review": _root / "data" / "sample_tender_human_review.md",
    "Standard": _root / "data" / "sample_tender.md",
    "Low risk": _root / "data" / "sample_tender_low_risk.md",
}

init_page(
    "Harbourmaster — Tender Review",
    icon="⚓",
    subtitle="Workflow governance control plane for agentic LLM tender review",
    sidebar_expanded=True,
)

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
if "active_sample" not in st.session_state:
    st.session_state.active_sample = None

# Reverse lookup: sample filename -> human label (for sidebar demo buttons).
_SAMPLE_BY_NAME = {path.name: label for label, path in SAMPLE_TENDERS.items()}

require_auth()
init_telemetry()


def _home_sidebar_extra() -> None:
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


render_app_sidebar("home", extra_blocks=_home_sidebar_extra, show_demo=True)

if demo_path := st.session_state.pop("demo_sample_path", None):
    sample_file = _root / demo_path
    if sample_file.exists():
        st.session_state.tender_text = sample_file.read_text(encoding="utf-8")
        st.session_state.phase = "idle"
        st.session_state.active_sample = _SAMPLE_BY_NAME.get(sample_file.name)


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
    st.session_state.active_sample = None


def _run_workflow(
    inputs: Any,
    run_config: dict[str, Any],
    *,
    mode: str = "full",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    tracker = WorkflowProgressTracker(mode=mode)  # type: ignore[arg-type]
    st.session_state.phase = "processing"
    st.session_state.live_workflow = tracker.sidebar_snapshot()
    _draw_stepper(st.session_state.live_workflow)
    tracker.mount()

    def _tick(snap: dict[str, Any]) -> None:
        st.session_state.live_workflow = snap
        _draw_stepper(snap)

    final_state, interrupt_payload = stream_graph_run(
        graph,
        inputs,
        run_config,
        tracker,
        on_tick=_tick,
    )

    st.session_state.live_workflow = tracker.sidebar_snapshot()
    return final_state, interrupt_payload


def _render_workflow_summary() -> None:
    live = st.session_state.live_workflow or {}
    result = st.session_state.final_result or {}
    render_summary_card(
        phase=st.session_state.phase,
        guard_verdict=live.get("guard_verdict") or result.get("guard_verdict"),
        overall_risk=live.get("overall_risk") if live.get("overall_risk") is not None else result.get("overall_risk"),
        specialists_done=live.get("specialists_done"),
        specialists_total=live.get("specialists_total", 5),
        review_id=st.session_state.review_id,
        blocked=bool(result.get("blocked")),
    )


_stepper_slot = st.empty()


def _draw_stepper(live: dict[str, Any] | None = None) -> None:
    snapshot = live if live is not None else (st.session_state.live_workflow or {})
    blocked = bool((st.session_state.final_result or {}).get("blocked"))
    with _stepper_slot.container():
        render_phase_stepper(st.session_state.phase, live=snapshot, blocked=blocked)


_draw_stepper()
if st.session_state.phase in {"processing", "awaiting_review", "complete"} or st.session_state.live_workflow:
    _render_workflow_summary()

if st.session_state.phase == "idle":
    st.markdown("### Submit a tender document for review")
    st.caption("Upload a document, paste text, or load a sample to start the governed multi-agent workflow.")

    st.markdown("**Sample tenders**")
    scols = st.columns(len(SAMPLE_TENDERS))
    tender_text = st.session_state.tender_text
    active_sample = st.session_state.active_sample
    for col, (label, path) in zip(scols, SAMPLE_TENDERS.items()):
        is_active = label == active_sample
        if col.button(
            f"Load {label}",
            use_container_width=True,
            key=f"sample-{label}",
            type="primary" if is_active else "secondary",
        ):
            if path.exists():
                tender_text = path.read_text(encoding="utf-8")
                st.session_state.tender_text = tender_text
                st.session_state.active_sample = label
                st.rerun()
            st.error(f"Sample file not found: {path}")

    if active_sample:
        st.markdown(
            f'<span class="hm-chip hm-chip-ok">Sample loaded: {active_sample}</span>',
            unsafe_allow_html=True,
        )

    tab_upload, tab_paste = st.tabs(["Upload file", "Paste text"])
    with tab_upload:
        uploaded = st.file_uploader("Upload a tender document (.md / .txt / .pdf)", type=["md", "txt", "pdf"])
        if uploaded:
            tender_text = extract_text(uploaded)
            st.session_state.active_sample = None
            st.text_area("Preview", tender_text[:2000], height=200, disabled=True)
    with tab_paste:
        pasted = st.text_area(
            "Paste tender text below",
            value=tender_text,
            height=300,
            placeholder="Paste the full tender / contract text here...",
            key="tender_paste_area",
        )
        if pasted:
            tender_text = pasted

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
        st.markdown("### Tender Document")
        render_tender_document(st.session_state.tender_text, title="Original tender", expanded=False)

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
    is_blocked = bool(result.get("blocked"))
    if is_blocked:
        st.error(f"⛔ Blocked by the governance guard — {result.get('block_reason', 'DENY')}")
        st.caption("The input was denied at ingress; specialist analysis was not run.")
    else:
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
        if is_blocked:
            decision_label = "Blocked"
        else:
            decision = result.get("review_decision", {})
            decision_label = decision.get("decision", "auto-approved").title()
        st.metric("Decision", decision_label)
    with col5:
        st.metric("Policies Considered", len(result.get("corporate_policies", [])))

    if not is_blocked:
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

    st.markdown("### Tender Document")
    render_tender_document(st.session_state.tender_text, title="Reviewed tender", expanded=False)

    st.divider()
    if st.button("Start New Review"):
        _reset()
        st.rerun()
