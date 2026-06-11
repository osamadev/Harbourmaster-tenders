"""Fast Python-backed tools for Governance Copilot."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from harbourmaster.elastic_store import enabled as elastic_enabled
from harbourmaster.elastic_store import search as elastic_search
from harbourmaster.phoenix_audit import load_dataframe, phoenix_console_url
from harbourmaster.policies import active_policies
from harbourmaster.reviews import list_reviews, load_review


def _guard_mask(df) -> Any:
    guard_ids = {"governance-guard-v1", "harbourmaster.guard"}
    return (df["direction"].astype(str).str.lower() == "guard") | df["agent_id"].astype(str).isin(
        guard_ids
    )


@tool
def summarize_guard_telemetry() -> str:
    """Summarize guard verdicts, denial categories, and risk-bearing spans from Phoenix."""
    df = load_dataframe()
    if df.empty:
        return json.dumps(
            {
                "status": "empty",
                "message": "No Phoenix telemetry found. Run a contract review first.",
                "console_url": phoenix_console_url(),
            }
        )

    is_guard = _guard_mask(df)
    guard_df = df[is_guard]
    denied = df["action"].astype(str).str.upper() == "DENY"
    guard_denied = guard_df[guard_df["action"].astype(str).str.upper() == "DENY"]

    categories: dict[str, int] = {}
    for raw in guard_denied["intent_category"].fillna(""):
        for part in str(raw).split(","):
            label = part.strip()
            if label:
                categories[label] = categories.get(label, 0) + 1

    risk_bearing = int(df["has_explicit_risk"].fillna(False).sum()) if "has_explicit_risk" in df else 0
    system_denied = int((denied & ~is_guard).sum())

    return json.dumps(
        {
            "total_spans": int(len(df)),
            "guard_spans": int(len(guard_df)),
            "guard_denials": int(len(guard_denied)),
            "guard_categories": categories,
            "risk_bearing_spans": risk_bearing,
            "system_tool_denials": system_denied,
            "console_url": phoenix_console_url(),
        },
        indent=2,
    )


@tool
def list_recent_reviews(limit: int = 10) -> str:
    """List saved contract review summaries, newest first."""
    rows = list_reviews()[: max(1, min(limit, 25))]
    return json.dumps({"count": len(rows), "reviews": rows}, indent=2, default=str)


@tool
def get_review_detail(review_id: str) -> str:
    """Load one saved review by id with findings, risk, and decision."""
    try:
        review = load_review(review_id)
    except FileNotFoundError:
        return json.dumps({"error": f"Review not found: {review_id}"})
    summary = {
        "id": review.get("id"),
        "title": review.get("title"),
        "created_at": review.get("created_at"),
        "overall_risk": review.get("overall_risk"),
        "decision": review.get("review_decision", {}).get("decision"),
        "finding_count": len(review.get("findings", {}).get("findings", [])),
        "clause_count": len(review.get("clauses", [])),
        "policies": review.get("corporate_policies", []),
    }
    return json.dumps({"review": summary, "findings": review.get("findings", {})}, indent=2, default=str)


@tool
def search_procurement_memory(query: str, doc_types: str = "") -> str:
    """Search Elastic procurement memory for policies, clauses, precedents, and red-team cases."""
    if not elastic_enabled():
        return json.dumps(
            {
                "error": "Elastic is disabled or not configured.",
                "hint": "Set ELASTIC_ENABLED=true and run make index-elastic.",
            }
        )
    types = [t.strip() for t in doc_types.split(",") if t.strip()] or None
    hits = elastic_search(query, size=8, doc_types=types)
    slim = [
        {
            "doc_type": h.get("doc_type"),
            "title": h.get("title"),
            "source": h.get("source"),
            "policy_id": h.get("policy_id"),
            "score": h.get("_score"),
            "snippet": str(h.get("body", ""))[:400],
        }
        for h in hits
    ]
    return json.dumps({"query": query, "hits": slim}, indent=2)


@tool
def list_active_policies() -> str:
    """List active corporate procurement policies with ids and scope tags."""
    rows = [
        {
            "id": p.get("id"),
            "title": p.get("title"),
            "version": p.get("version"),
            "scope_tags": p.get("scope_tags", []),
        }
        for p in active_policies()
    ]
    return json.dumps({"count": len(rows), "policies": rows}, indent=2)


def native_tools() -> list:
    """Return all native LangChain tools."""
    return [
        summarize_guard_telemetry,
        list_recent_reviews,
        get_review_detail,
        search_procurement_memory,
        list_active_policies,
    ]
