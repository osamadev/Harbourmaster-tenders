"""The Harbourmaster advanced multi-agent tender-review graph."""

import contextvars
from concurrent.futures import ThreadPoolExecutor, as_completed

from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from harbourmaster import config
from harbourmaster.agents import (
    SPECIALIST_KEYS,
    analyse_with_specialist,
    draft_summary,
    negotiate_counter_clauses,
    segment_tender_clauses,
    verify_findings,
)
from harbourmaster.elastic_store import index_review_artifact, retrieval_context_for_clauses
from harbourmaster.guard import evaluate_content
from harbourmaster.state import ReviewState
from harbourmaster.telemetry import record_inspection_span


def _emit(event: dict) -> None:
    """Best-effort custom stream event for live UI progress."""
    try:
        get_stream_writer()(event)
    except Exception:  # noqa: BLE001
        return


def segment_node(state: ReviewState) -> dict:
    """Segment the tender into stable clauses."""
    tender_text = state["tender_text"]
    guard = evaluate_content(tender_text, context="tender_input")
    _emit(
        {
            "type": "guard_complete",
            "verdict": guard.verdict,
            "blocked": guard.blocked,
        }
    )
    record_inspection_span(
        "harbourmaster.guard",
        {**guard.to_inspection(), "agent_id": "governance-guard-v1"},
        direction="guard",
    )
    clauses, resp = segment_tender_clauses(state["tender_text"])
    _emit({"type": "segment_complete", "clause_count": len(clauses)})
    retrieval_context = retrieval_context_for_clauses(clauses)
    _emit({"type": "retrieval_complete", "snippet_count": len(retrieval_context)})
    blocked = guard.blocked
    reports = [guard.to_inspection(), resp.inspection]
    return {
        "clauses": clauses,
        "retrieval_context": retrieval_context,
        "inspection_reports": reports,
        "blocked": blocked,
        "block_reason": f"Guard verdict: {guard.verdict}" if blocked else "",
        "revision_round": 0,
        "pending_revisions": {},
        "specialist_findings": {},
    }


def specialists_node(state: ReviewState) -> dict:
    """Run specialist analysts (full run or revision pass)."""
    clauses = state.get("clauses", [])
    corporate_policies = state.get("corporate_policies", [])
    retrieval_context = state.get("retrieval_context", [])
    pending = state.get("pending_revisions", {})
    existing = dict(state.get("specialist_findings", {}))
    reports = list(state.get("inspection_reports", []))

    targets = [s for s in SPECIALIST_KEYS if s in pending] if pending else list(SPECIALIST_KEYS)
    revision_round = state.get("revision_round", 0)
    if revision_round:
        _emit({"type": "revision_round", "round": revision_round, "targets": targets})

    blocked = state.get("blocked", False)
    block_reason = state.get("block_reason", "")

    for specialist in targets:
        _emit({"type": "specialist_start", "specialist": specialist, "revision_round": revision_round})

    with ThreadPoolExecutor(max_workers=len(targets) or 1) as executor:
        # Run each worker inside a fresh copy of the current context so the
        # per-session Gemini key (a ContextVar) propagates into the thread pool.
        # A separate copy per task is required — one Context can't be entered by
        # two threads at once.
        futures = {
            executor.submit(
                contextvars.copy_context().run,
                analyse_with_specialist,
                specialist,
                clauses,
                pending.get(specialist),
                _policies_for_specialist(corporate_policies, specialist),
                retrieval_context,
            ): specialist
            for specialist in targets
        }
        for future in as_completed(futures):
            specialist = futures[future]
            findings, resp = future.result()
            existing[specialist] = findings
            reports.append(resp.inspection)
            _emit(
                {
                    "type": "specialist_complete",
                    "specialist": specialist,
                    "findings": len(findings),
                    "revision_round": revision_round,
                }
            )
            if resp.blocked:
                blocked = True
                block_reason = f"Model verdict: {resp.verdict}"

    return {
        "specialist_findings": existing,
        "inspection_reports": reports,
        "blocked": blocked,
        "block_reason": block_reason,
        "pending_revisions": {},
    }


def aggregate_node(state: ReviewState) -> dict:
    """Deterministically merge specialist outputs and compute overall risk."""
    specialist_findings = state.get("specialist_findings", {})
    clauses = state.get("clauses", [])
    clause_map = {c["id"]: c for c in clauses}

    merged: list[dict] = []
    seen = set()
    specialist_scores: dict[str, float] = {k: 0.0 for k in SPECIALIST_KEYS}

    for specialist, items in specialist_findings.items():
        max_score = 0.0
        for finding in items:
            clause_id = finding.get("clause_id")
            if clause_id not in clause_map:
                continue

            risk_level = str(finding.get("risk_level", "medium")).lower()
            max_score = max(max_score, _risk_to_score(risk_level))

            key = (
                specialist,
                clause_id,
                risk_level,
                str(finding.get("rationale", "")).strip(),
            )
            if key in seen:
                continue
            seen.add(key)

            clause = clause_map[clause_id]
            merged.append(
                {
                    "specialist": specialist,
                    "clause_id": clause_id,
                    "clause": clause["title"],
                    "risk_level": risk_level,
                    "rationale": str(finding.get("rationale", "")).strip(),
                    "evidence_quote": str(finding.get("evidence_quote", "")).strip(),
                    "policy_id": str(finding.get("policy_id", "")).strip(),
                    "policy_reference": str(finding.get("policy_reference", "")).strip(),
                }
            )

        specialist_scores[specialist] = max_score

    overall = _weighted_overall_risk(specialist_scores)
    high_risk_count = sum(1 for row in merged if row.get("risk_level") == "high")
    _emit(
        {
            "type": "risk_computed",
            "overall_risk": overall,
            "high_risk_count": high_risk_count,
        }
    )
    verdict = "HUMAN_REVIEW" if overall >= config.REVIEW_RISK_THRESHOLD else "ALLOW"
    record_inspection_span(
        "harbourmaster.workflow.overall_risk",
        {
            "agent_id": "workflow-governance",
            "verdict": verdict,
            "risk_score": overall,
            "reason": "Weighted aggregate risk from specialist findings.",
        },
        direction="workflow_risk",
    )
    return {
        "findings": {"overall_risk": overall, "findings": merged},
        "overall_risk": overall,
    }


def verifier_node(state: ReviewState) -> dict:
    """Verify merged findings; request revisions when needed."""
    clauses = state.get("clauses", [])
    merged_findings = state.get("findings", {}).get("findings", [])
    decisions, resp = verify_findings(clauses, merged_findings)

    reports = list(state.get("inspection_reports", [])) + [resp.inspection]
    decision_map = {
        (d.get("specialist"), d.get("clause_id")): d
        for d in decisions
        if d.get("specialist") and d.get("clause_id")
    }

    verified: list[dict] = []
    pending: dict[str, list[dict[str, str]]] = {}

    for finding in merged_findings:
        specialist = finding.get("specialist", "")
        clause_id = finding.get("clause_id", "")
        decision = decision_map.get((specialist, clause_id), {"action": "keep", "reason": ""})
        action = str(decision.get("action", "keep")).lower()

        if action == "drop":
            continue
        if action == "revise":
            pending.setdefault(specialist, []).append(
                {
                    "specialist": specialist,
                    "clause_id": clause_id,
                    "action": action,
                    "reason": str(decision.get("reason", "")),
                }
            )
            continue
        verified.append(finding)

    if not verified and merged_findings:
        verified = merged_findings

    pending_count = sum(len(items) for items in pending.values())
    _emit({"type": "verifier_complete", "pending_revisions": pending_count})

    return {
        "verifier_notes": decisions,
        "verified_findings": verified,
        "pending_revisions": pending,
        "inspection_reports": reports,
    }


def route_after_verifier(state: ReviewState) -> str:
    """Loop back to specialists when verifier requested revisions."""
    pending = state.get("pending_revisions", {})
    round_num = state.get("revision_round", 0)
    if pending and round_num < config.VERIFIER_MAX_REVISIONS:
        return "revision"
    return "governance"


def revision_node(state: ReviewState) -> dict:
    """Increment revision round before re-running specialists."""
    round_num = state.get("revision_round", 0) + 1
    targets = list(state.get("pending_revisions", {}).keys()) or list(SPECIALIST_KEYS)
    _emit({"type": "revision_round", "round": round_num, "targets": targets})
    return {"revision_round": round_num}


def governance_node(state: ReviewState) -> dict:
    """Pass-through node used for governance routing."""
    if state.get("blocked"):
        route = "human_review (guard blocked)"
    elif state.get("overall_risk", 0.0) >= config.REVIEW_RISK_THRESHOLD:
        route = "human_review (risk threshold)"
    else:
        route = "auto-continue"
    _emit({"type": "route_decision", "route": route})
    return {}


def route_governance(state: ReviewState) -> str:
    """Decide whether workflow needs human review."""
    if state.get("blocked"):
        return "human_review"
    if state.get("overall_risk", 0.0) >= config.REVIEW_RISK_THRESHOLD:
        return "human_review"
    return "negotiator"


def human_review_node(state: ReviewState) -> dict:
    """Pause workflow for human oversight."""
    decision = interrupt(
        {
            "type": "tender_review_required",
            "overall_risk": state.get("overall_risk"),
            "blocked": state.get("blocked", False),
            "block_reason": state.get("block_reason", ""),
            "findings": {
                "overall_risk": state.get("overall_risk", 1.0),
                "findings": state.get("verified_findings", state.get("findings", {}).get("findings", [])),
            },
            "clauses": state.get("clauses", []),
            "specialist_findings": state.get("specialist_findings", {}),
            "verifier_notes": state.get("verifier_notes", []),
            "corporate_policies": state.get("corporate_policies", []),
            "prompt": "Approve, reject, or annotate this tender review.",
        }
    )
    return {"review_decision": decision}


def negotiator_node(state: ReviewState) -> dict:
    """Draft counter-clauses for high-risk findings."""
    decision = state.get("review_decision") or {}
    if decision.get("decision") == "reject":
        _emit({"type": "negotiator_complete", "counter_clauses": 0, "skipped": True})
        return {"counter_clauses": []}

    findings = state.get("verified_findings") or state.get("findings", {}).get("findings", [])
    counter_clauses, resp = negotiate_counter_clauses(
        clauses=state.get("clauses", []),
        findings=findings,
        review_note=decision.get("note"),
        clause_notes=decision.get("clause_notes"),
    )
    reports = list(state.get("inspection_reports", [])) + [resp.inspection]
    _emit({"type": "negotiator_complete", "counter_clauses": len(counter_clauses)})
    return {"counter_clauses": counter_clauses, "inspection_reports": reports}


def draft_node(state: ReviewState) -> dict:
    """Produce reviewer-facing summary (or record rejection)."""
    decision = state.get("review_decision") or {}

    if decision.get("decision") == "reject":
        reviewer = decision.get("reviewer", "reviewer")
        note = decision.get("note", "no note provided")
        _emit({"type": "draft_complete", "rejected": True})
        return {"draft_summary": f"REVIEW REJECTED by {reviewer}: {note}"}

    final_findings = {
        "overall_risk": state.get("overall_risk", 1.0),
        "findings": state.get("verified_findings", state.get("findings", {}).get("findings", [])),
    }

    summary, resp = draft_summary(
        final_findings,
        review_note=decision.get("note"),
        counter_clauses=state.get("counter_clauses", []),
        verifier_notes=state.get("verifier_notes", []),
    )
    _index_review_memory(summary, state)
    reports = list(state.get("inspection_reports", [])) + [resp.inspection]
    _emit({"type": "draft_complete", "rejected": False})
    return {
        "draft_summary": summary,
        "inspection_reports": reports,
        "findings": final_findings,
    }


def _risk_to_score(level: str) -> float:
    return {"low": 0.25, "medium": 0.6, "high": 0.9}.get(level, 0.6)


def _index_review_memory(summary: str, state: ReviewState) -> None:
    """Best-effort persistence of useful review artifacts into Elastic."""
    try:
        index_review_artifact(
            "review_summary",
            "Tender review summary",
            summary,
            {
                "overall_risk": state.get("overall_risk", 0.0),
                "finding_count": len(state.get("verified_findings", [])),
            },
        )
        for row in state.get("counter_clauses", []):
            index_review_artifact(
                "counter_clause",
                f"Counter-clause for {row.get('clause_id', 'unknown')}",
                row.get("proposed_redline", ""),
                {
                    "clause_id": row.get("clause_id", ""),
                    "justification": row.get("justification", ""),
                },
            )
    except Exception:  # noqa: BLE001
        return


def _weighted_overall_risk(scores: dict[str, float]) -> float:
    weights = config.SPECIALIST_WEIGHTS
    weighted_sum = 0.0
    total_weight = 0.0
    for specialist, score in scores.items():
        weight = float(weights.get(specialist, 1.0))
        weighted_sum += score * weight
        total_weight += weight
    if total_weight <= 0:
        return 1.0
    return round(min(1.0, weighted_sum / total_weight), 4)


def _policies_for_specialist(
    policies: list[dict[str, object]],
    specialist: str,
) -> list[dict[str, object]]:
    """Return policies applicable to a specialist by scope tags."""
    selected: list[dict[str, object]] = []
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        scope_tags = policy.get("scope_tags") or []
        if not scope_tags:
            selected.append(policy)
            continue
        if specialist in {str(tag).strip() for tag in scope_tags}:
            selected.append(policy)
    return selected


def build_graph():
    """Compile the advanced multi-agent review graph."""
    g = StateGraph(ReviewState)

    g.add_node("segment", segment_node)
    g.add_node("specialists", specialists_node)
    g.add_node("aggregate", aggregate_node)
    g.add_node("verifier", verifier_node)
    g.add_node("revision", revision_node)
    g.add_node("governance", governance_node)
    g.add_node("human_review", human_review_node)
    g.add_node("negotiator", negotiator_node)
    g.add_node("draft", draft_node)

    g.add_edge(START, "segment")
    g.add_edge("segment", "specialists")
    g.add_edge("specialists", "aggregate")
    g.add_edge("aggregate", "verifier")

    g.add_conditional_edges(
        "verifier",
        route_after_verifier,
        {"revision": "revision", "governance": "governance"},
    )

    g.add_edge("revision", "specialists")

    g.add_conditional_edges(
        "governance",
        route_governance,
        {"human_review": "human_review", "negotiator": "negotiator"},
    )

    g.add_edge("human_review", "negotiator")
    g.add_edge("negotiator", "draft")
    g.add_edge("draft", END)

    return g.compile(checkpointer=MemorySaver())


# Module-level compiled graph for convenient import.
graph = build_graph()
