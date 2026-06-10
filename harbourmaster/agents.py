"""Governed agent primitives for the advanced multi-agent tender workflow."""

import json
import re
from typing import Any

from harbourmaster import config
from harbourmaster.llm import GovernedLLM, GovernedResponse

# --- Clause segmenter --------------------------------------------------------

_segmenter = GovernedLLM(
    agent_id="clause-segmenter-v1",
    declared_intent="parsing",
    model=config.ANALYST_MODEL,
    temperature=0.0,
)

SEGMENTER_SYSTEM = """Segment the tender into ordered clauses.

Return STRICT JSON only:
{
  "clauses": [
    {"id": "C1", "title": "<short title>", "text": "<full clause text>"}
  ]
}

Rules:
- Keep the original order.
- Use IDs C1, C2, C3... with no gaps.
- Include enough text for evidence-based review.
"""


def segment_tender_clauses(tender_text: str) -> tuple[list[dict[str, str]], GovernedResponse]:
    """Segment tender text into stable clause IDs."""
    resp = _segmenter.complete(
        [
            {"role": "system", "content": SEGMENTER_SYSTEM},
            {"role": "user", "content": tender_text},
        ]
    )
    parsed = _safe_json_obj(resp.text)
    clauses = parsed.get("clauses", [])
    normalised: list[dict[str, str]] = []
    for idx, clause in enumerate(clauses, 1):
        if not isinstance(clause, dict):
            continue
        cid = str(clause.get("id") or f"C{idx}").strip()
        title = str(clause.get("title") or f"Clause {idx}").strip()
        text = str(clause.get("text") or "").strip()
        if not text:
            continue
        normalised.append({"id": cid, "title": title, "text": text})

    if normalised:
        return normalised, resp

    return _fallback_segment(tender_text), resp


# --- Specialist analysts -----------------------------------------------------

SPECIALIST_DEFS: dict[str, dict[str, str]] = {
    "legal": {
        "agent_id": "legal-analyst-v1",
        "declared_intent": "risk_analysis_legal",
        "focus": "legal exposure, indemnity, liability, termination, governing-law issues",
    },
    "financial": {
        "agent_id": "financial-analyst-v1",
        "declared_intent": "risk_analysis_financial",
        "focus": "payment, penalties, cashflow risk, pricing and commercial imbalance",
    },
    "delivery": {
        "agent_id": "delivery-analyst-v1",
        "declared_intent": "risk_analysis_delivery",
        "focus": "timeline, dependencies, service levels, operational deliverability",
    },
    "ip_data": {
        "agent_id": "ip-data-analyst-v1",
        "declared_intent": "risk_analysis_ip_data",
        "focus": "IP transfer, data governance, privacy/security obligations",
    },
    "compliance": {
        "agent_id": "compliance-analyst-v1",
        "declared_intent": "risk_analysis_compliance",
        "focus": "alignment to internal corporate procurement policies, procedures, and regulations",
    },
}

SPECIALIST_KEYS = tuple(SPECIALIST_DEFS.keys())

_specialists = {
    key: GovernedLLM(
        agent_id=cfg["agent_id"],
        declared_intent=cfg["declared_intent"],
        model=config.ANALYST_MODEL,
        temperature=0.1,
    )
    for key, cfg in SPECIALIST_DEFS.items()
}


def analyse_with_specialist(
    specialist: str,
    clauses: list[dict[str, str]],
    revision_requests: list[dict[str, Any]] | None = None,
    corporate_policies: list[dict[str, Any]] | None = None,
    retrieval_context: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], GovernedResponse]:
    """Run one specialist agent over segmented clauses."""
    if specialist not in SPECIALIST_DEFS:
        raise ValueError(f"Unknown specialist: {specialist}")

    cfg = SPECIALIST_DEFS[specialist]
    base_schema = """
{
  "findings": [
    {
      "clause_id": "C1",
      "risk_level": "low|medium|high",
      "rationale": "one concise sentence",
      "evidence_quote": "short verbatim quote from the clause text"
    }
  ]
}
""".strip()
    if specialist == "compliance":
        base_schema = """
{
  "findings": [
    {
      "clause_id": "C1",
      "policy_id": "starter-procurement-policy",
      "risk_level": "low|medium|high",
      "rationale": "one concise sentence",
      "evidence_quote": "short verbatim quote from the clause text",
      "policy_reference": "short excerpt from the cited policy body"
    }
  ]
}
""".strip()

    system = f"""You are a procurement risk specialist.
Focus only on: {cfg['focus']}.

Given clause objects with IDs, return STRICT JSON only:
{base_schema}

Rules:
- Every finding MUST cite a clause_id that exists.
- evidence_quote MUST be a verbatim substring of that clause text.
- For compliance specialist, policy_id MUST reference one of the supplied corporate policies.
- If retrieval_context is supplied, use it only as supporting precedent/policy context.
  Do not invent findings from retrieval_context unless the tender clause itself supports them.
- Do not include markdown fences.
"""

    payload: dict[str, Any] = {"clauses": clauses}
    if revision_requests:
        payload["revision_requests"] = revision_requests
    if specialist == "compliance":
        payload["corporate_policies"] = corporate_policies or []
    if retrieval_context:
        payload["retrieval_context"] = retrieval_context

    resp = _specialists[specialist].complete(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload)},
        ]
    )

    parsed = _safe_json_obj(resp.text)
    findings = parsed.get("findings", [])
    clause_map = {c["id"]: c for c in clauses}
    policy_map = {
        str(p.get("id") or "").strip(): str(p.get("body") or "")
        for p in (corporate_policies or [])
        if isinstance(p, dict)
    }

    normalised: list[dict[str, Any]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        clause_id = str(item.get("clause_id") or "").strip()
        if clause_id not in clause_map:
            continue

        risk_level = str(item.get("risk_level") or "").strip().lower()
        if risk_level not in {"low", "medium", "high"}:
            risk_level = "medium"

        rationale = str(item.get("rationale") or "").strip()
        evidence_quote = str(item.get("evidence_quote") or "").strip()
        clause = clause_map[clause_id]
        if evidence_quote and evidence_quote not in clause["text"]:
            evidence_quote = ""

        policy_id = str(item.get("policy_id") or "").strip()
        policy_reference = str(item.get("policy_reference") or "").strip()
        if specialist == "compliance":
            if policy_id not in policy_map:
                continue
            policy_body = policy_map.get(policy_id, "")
            if policy_reference and policy_reference not in policy_body:
                policy_reference = ""

        normalised.append(
            {
                "specialist": specialist,
                "clause_id": clause_id,
                "clause": clause["title"],
                "risk_level": risk_level,
                "rationale": rationale,
                "evidence_quote": evidence_quote,
                "policy_id": policy_id,
                "policy_reference": policy_reference,
            }
        )

    return normalised, resp


# --- Verifier ----------------------------------------------------------------

_verifier = GovernedLLM(
    agent_id="findings-verifier-v1",
    declared_intent="verification",
    model=config.DRAFTER_MODEL,
    temperature=0.0,
)

VERIFIER_SYSTEM = """You are a strict verifier for procurement risk findings.

Return STRICT JSON only:
{
  "decisions": [
    {
      "specialist": "legal|financial|delivery|ip_data|compliance",
      "clause_id": "C1",
      "action": "keep|revise|drop",
      "reason": "short reason"
    }
  ]
}

Mark action=revise if the rationale is plausible but evidence is weak/missing.
Mark action=drop if claim is unsupported by the clause text.
"""


def verify_findings(
    clauses: list[dict[str, str]],
    findings: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], GovernedResponse]:
    """Run verifier over merged findings."""
    resp = _verifier.complete(
        [
            {"role": "system", "content": VERIFIER_SYSTEM},
            {"role": "user", "content": json.dumps({"clauses": clauses, "findings": findings})},
        ]
    )
    parsed = _safe_json_obj(resp.text)
    decisions = parsed.get("decisions", [])
    normalised: list[dict[str, str]] = []

    for d in decisions:
        if not isinstance(d, dict):
            continue
        specialist = str(d.get("specialist") or "").strip()
        clause_id = str(d.get("clause_id") or "").strip()
        action = str(d.get("action") or "keep").strip().lower()
        if action not in {"keep", "revise", "drop"}:
            action = "keep"
        reason = str(d.get("reason") or "").strip()
        normalised.append(
            {
                "specialist": specialist,
                "clause_id": clause_id,
                "action": action,
                "reason": reason,
            }
        )

    return normalised, resp


# --- Negotiator --------------------------------------------------------------

_negotiator = GovernedLLM(
    agent_id="counter-clause-negotiator-v1",
    declared_intent="general",
    model=config.DRAFTER_MODEL,
    temperature=0.2,
)

NEGOTIATOR_SYSTEM = """You propose contract redlines for risky clauses.

Return STRICT JSON only:
{
  "counter_clauses": [
    {
      "clause_id": "C1",
      "proposed_redline": "replacement wording",
      "justification": "1-2 short sentences"
    }
  ]
}
"""


def negotiate_counter_clauses(
    clauses: list[dict[str, str]],
    findings: list[dict[str, Any]],
    review_note: str | None = None,
    clause_notes: str | None = None,
) -> tuple[list[dict[str, str]], GovernedResponse]:
    """Draft counter-clauses for high-risk items."""
    targets: list[dict[str, Any]] = []
    for f in findings:
        level = str(f.get("risk_level") or "").lower()
        if level == "high" or (config.NEGOTIATOR_INCLUDE_MEDIUM and level == "medium"):
            targets.append(f)

    payload: dict[str, Any] = {"clauses": clauses, "findings": targets}
    if review_note:
        payload["review_note"] = review_note
    if clause_notes:
        payload["clause_notes"] = clause_notes

    resp = _negotiator.complete(
        [
            {"role": "system", "content": NEGOTIATOR_SYSTEM},
            {"role": "user", "content": json.dumps(payload)},
        ]
    )

    parsed = _safe_json_obj(resp.text)
    rows = parsed.get("counter_clauses", [])
    normalised: list[dict[str, str]] = []
    clause_ids = {c["id"] for c in clauses}

    for row in rows:
        if not isinstance(row, dict):
            continue
        clause_id = str(row.get("clause_id") or "").strip()
        if clause_id not in clause_ids:
            continue
        normalised.append(
            {
                "clause_id": clause_id,
                "proposed_redline": str(row.get("proposed_redline") or "").strip(),
                "justification": str(row.get("justification") or "").strip(),
            }
        )

    return normalised, resp


# --- Drafter -----------------------------------------------------------------

_drafter = GovernedLLM(
    agent_id="review-drafter-v1",
    declared_intent="general",
    model=config.DRAFTER_MODEL,
    temperature=0.3,
)

DRAFTER_SYSTEM = """You write concise procurement review notes for a human approver
at a contracting organisation.

Given verified findings and optional counter-clauses, produce a short,
plain-English summary (maximum 220 words) that a reviewer can act on directly.
Use UK English. If a human review note is supplied, reflect it in the summary.
"""


def draft_summary(
    findings: dict,
    review_note: str | None = None,
    counter_clauses: list[dict[str, str]] | None = None,
    verifier_notes: list[dict[str, str]] | None = None,
) -> tuple[str, GovernedResponse]:
    """Run the drafter over verified findings. Returns (summary, response)."""
    payload: dict[str, Any] = {"findings": findings}
    if review_note:
        payload["human_review_note"] = review_note
    if counter_clauses:
        payload["counter_clauses"] = counter_clauses
    if verifier_notes:
        payload["verifier_notes"] = verifier_notes

    resp = _drafter.complete(
        [
            {"role": "system", "content": DRAFTER_SYSTEM},
            {"role": "user", "content": json.dumps(payload)},
        ]
    )
    return resp.text, resp


# --- helpers -----------------------------------------------------------------

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_HEADING = re.compile(r"^#{2,6}\s+(.*)$")


def _extract_json(text: str) -> str:
    """Strip a ```json ... ``` fence if the model added one."""
    match = _FENCE.match(text.strip())
    return match.group(1).strip() if match else text.strip()


def _safe_json_obj(text: str) -> dict[str, Any]:
    """Parse JSON object output safely; return empty object on failure."""
    try:
        parsed = json.loads(_extract_json(text))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _fallback_segment(tender_text: str) -> list[dict[str, str]]:
    """Simple heading-based fallback if segmenter output is invalid."""
    lines = tender_text.splitlines()
    clauses: list[dict[str, str]] = []
    current_title = "Document Body"
    current_lines: list[str] = []

    def flush() -> None:
        if not current_lines:
            return
        cid = f"C{len(clauses) + 1}"
        text = "\n".join(current_lines).strip()
        if text:
            clauses.append({"id": cid, "title": current_title, "text": text})

    for line in lines:
        m = _HEADING.match(line.strip())
        if m:
            flush()
            current_title = m.group(1).strip() or f"Clause {len(clauses) + 1}"
            current_lines = []
            continue
        current_lines.append(line)

    flush()

    if clauses:
        return clauses
    return [{"id": "C1", "title": "Document Body", "text": tender_text.strip()}]
