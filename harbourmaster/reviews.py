"""Persistence helpers for completed contract review records."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

REVIEWS_DIR = Path(__file__).resolve().parents[1] / "data" / "reviews"
MAX_TENDER_PREVIEW_CHARS = 12000


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "review"


def _review_path(review_id: str) -> Path:
    return REVIEWS_DIR / f"{_slugify(review_id)}.json"


def _derive_title(tender_text: str) -> str:
    for line in tender_text.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:120]
    return "Untitled contract review"


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _policy_summaries(policies: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for policy in _safe_list(policies):
        if not isinstance(policy, dict):
            continue
        pid = str(policy.get("id", "")).strip()
        title = str(policy.get("title", "")).strip()
        if not pid and not title:
            continue
        rows.append({"id": pid, "title": title})
    return rows


def _review_summary(review: dict[str, Any]) -> dict[str, Any]:
    findings = _safe_dict(review.get("findings")).get("findings", [])
    counter = _safe_list(review.get("counter_clauses"))
    decision = _safe_dict(review.get("review_decision"))
    return {
        "id": review.get("id", ""),
        "created_at": review.get("created_at", ""),
        "title": review.get("title", "Untitled contract review"),
        "overall_risk": float(review.get("overall_risk", 0.0)),
        "blocked": bool(review.get("blocked", False)),
        "decision": str(decision.get("decision", "auto-approved")),
        "finding_count": len(findings) if isinstance(findings, list) else 0,
        "counter_clause_count": len(counter),
    }


def _build_review_record(result: dict[str, Any], tender_text: str, thread_id: str) -> dict[str, Any]:
    review_id = _slugify(thread_id or f"review-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}")
    decision = _safe_dict(result.get("review_decision"))
    findings = _safe_dict(result.get("findings"))

    return {
        "id": review_id,
        "thread_id": thread_id,
        "created_at": datetime.now(UTC).isoformat(),
        "title": _derive_title(tender_text),
        "overall_risk": float(result.get("overall_risk", findings.get("overall_risk", 0.0))),
        "blocked": bool(result.get("blocked", False)),
        "block_reason": str(result.get("block_reason", "")),
        "review_decision": decision,
        "draft_summary": str(result.get("draft_summary", "")),
        "findings": findings,
        "clauses": _safe_list(result.get("clauses")),
        "verified_findings": _safe_list(result.get("verified_findings")),
        "specialist_findings": _safe_dict(result.get("specialist_findings")),
        "verifier_notes": _safe_list(result.get("verifier_notes")),
        "counter_clauses": _safe_list(result.get("counter_clauses")),
        "inspection_reports": _safe_list(result.get("inspection_reports")),
        "corporate_policies": _policy_summaries(result.get("corporate_policies")),
        "tender_text": tender_text[:MAX_TENDER_PREVIEW_CHARS],
        "tender_text_truncated": len(tender_text) > MAX_TENDER_PREVIEW_CHARS,
    }


def save_review(result: dict[str, Any], tender_text: str, thread_id: str) -> dict[str, Any]:
    """Persist one review record using atomic file write semantics."""
    review = _build_review_record(result, tender_text, thread_id)
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    target = _review_path(review["id"])

    with NamedTemporaryFile("w", delete=False, dir=REVIEWS_DIR, encoding="utf-8") as tmp:
        json.dump(review, tmp, indent=2, ensure_ascii=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)

    tmp_path.replace(target)
    review["_file"] = target.name
    review["_summary"] = _review_summary(review)
    return review


def list_reviews() -> list[dict[str, Any]]:
    """Return lightweight review summaries sorted newest-first."""
    if not REVIEWS_DIR.exists():
        return []

    rows: list[dict[str, Any]] = []
    for path in sorted(REVIEWS_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            summary = _review_summary(raw)
            summary["_file"] = path.name
            rows.append(summary)
        except Exception:
            continue

    rows.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    return rows


def load_review(review_id: str) -> dict[str, Any]:
    """Load one review record by id."""
    path = _review_path(review_id)
    if not path.exists():
        raise FileNotFoundError(f"review not found: {review_id}")
    with open(path, "r", encoding="utf-8") as f:
        review = json.load(f)
    review["_file"] = path.name
    return review


def delete_review(review_id: str) -> bool:
    """Delete one review by id."""
    path = _review_path(review_id)
    if not path.exists():
        return False
    path.unlink()
    return True
