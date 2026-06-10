"""Shared state for the Harbourmaster review graph."""

from typing import Any, TypedDict


class ReviewState(TypedDict, total=False):
    # --- input ---
    tender_text: str
    corporate_policies: list[dict[str, Any]]

    # --- segmentation and specialist analysis ---
    clauses: list[dict[str, str]]
    specialist_findings: dict[str, list[dict[str, Any]]]
    retrieval_context: list[dict[str, Any]]

    # --- merged + verified findings ---
    findings: dict[str, Any]  # {"overall_risk": float, "findings": [...]} (aggregated)
    verified_findings: list[dict[str, Any]]
    verifier_notes: list[dict[str, str]]
    pending_revisions: dict[str, list[dict[str, str]]]
    revision_round: int

    overall_risk: float

    # --- governance ---
    blocked: bool  # True when the inline guard returns DENY
    block_reason: str
    inspection_reports: list[dict]  # guard + model inspection payloads for audit
    review_decision: dict[str, Any]  # human decision returned from interrupt()

    # --- negotiation ---
    counter_clauses: list[dict[str, str]]

    # --- output ---
    draft_summary: str
