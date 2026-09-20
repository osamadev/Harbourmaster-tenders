"""Write automated governance evaluations to Phoenix as span annotations.

Annotations are a separate Phoenix concept from tracing: they attach to a span by
``span_id`` and surface in the trace-list "Annotations" column + the span detail
Annotations tab. This module turns Harbourmaster's governance signal (guard
verdict, risk band, decision; red-team pass/fail) into ``annotator_kind="CODE"``
annotations.

Everything here is best-effort: any failure (Phoenix unreachable, span not yet
ingested, annotations disabled) is swallowed so a review/red-team run is never
broken by telemetry. NOTE: annotations POST to ``PHOENIX_BASE_URL`` (REST), so it
must point at the same Phoenix instance the spans are ingested into
(``PHOENIX_COLLECTOR_ENDPOINT`` target) — a split setup will silently drop them.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from harbourmaster import config


def enabled() -> bool:
    """Annotations are on unless explicitly disabled and a Phoenix base URL exists."""
    if os.getenv("PHOENIX_ANNOTATIONS_ENABLED", "true").strip().lower() == "false":
        return False
    return bool(config.PHOENIX_BASE_URL)


def span_id_hex(span: Any) -> str | None:
    """Return the OTLP span_id as 16-hex (Phoenix's id form), or None."""
    if span is None:
        return None
    try:
        ctx = span.get_span_context()
        if ctx is None or not ctx.span_id:
            return None
        return f"{ctx.span_id:016x}"
    except Exception:  # noqa: BLE001
        return None


def _client():
    """Build a phoenix.client.Client from the configured base URL + auth headers."""
    try:
        from phoenix.client import Client

        from harbourmaster.phoenix_audit import _phoenix_headers

        headers = _phoenix_headers()
        return Client(base_url=config.PHOENIX_BASE_URL.rstrip("/"), headers=headers or None)
    except Exception:  # noqa: BLE001
        return None


def _flush() -> None:
    """Force-flush exported spans so Phoenix has ingested them before we annotate."""
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception:  # noqa: BLE001
        pass


def _risk_band(score: float, threshold: float) -> str:
    if score >= threshold:
        return "high"
    if score >= threshold / 2:
        return "medium"
    return "low"


def annotate(
    client: Any,
    span_id: str,
    name: str,
    *,
    label: str | None = None,
    score: float | None = None,
    explanation: str | None = None,
    retries: int = 4,
    delay: float = 1.5,
) -> bool:
    """Post a single CODE annotation, retrying while the span is still ingesting."""
    if client is None or not span_id:
        return False
    for attempt in range(retries):
        try:
            client.spans.add_span_annotation(
                span_id=span_id,
                annotation_name=name,
                annotator_kind="CODE",
                label=label,
                score=score,
                explanation=(explanation or None),
                sync=True,
            )
            return True
        except Exception:  # noqa: BLE001 — usually span not yet ingested; retry then give up
            if attempt < retries - 1:
                time.sleep(delay)
    return False


def annotate_review(
    span_id: str | None,
    *,
    guard_verdict: str,
    overall_risk: float,
    threshold: float,
    decision: str,
    reason: str = "",
) -> None:
    """Attach guard_verdict / overall_risk / review_decision annotations to a review."""
    if not enabled() or not span_id:
        return
    _flush()
    client = _client()
    if client is None:
        return
    try:
        risk = float(overall_risk or 0.0)
    except Exception:  # noqa: BLE001
        risk = 0.0
    annotate(
        client,
        span_id,
        "guard_verdict",
        label=str(guard_verdict or "UNKNOWN"),
        explanation=reason or None,
    )
    annotate(
        client,
        span_id,
        "overall_risk",
        label=_risk_band(risk, threshold or 0.6),
        score=risk,
    )
    annotate(client, span_id, "review_decision", label=str(decision or "unknown"))


def annotate_redteam(items: list[dict[str, Any]]) -> None:
    """Attach a guard_correct pass/fail annotation to each red-team case span."""
    if not enabled() or not items:
        return
    _flush()
    client = _client()
    if client is None:
        return
    for item in items:
        span_id = item.get("span_id")
        if not span_id:
            continue
        passed = bool(item.get("passed"))
        annotate(
            client,
            span_id,
            "guard_correct",
            label="pass" if passed else "fail",
            score=1.0 if passed else 0.0,
            explanation=f"expected {item.get('expected', '')}, got {item.get('actual', '')}",
        )


def submit_review_async(span_id: str | None, **kwargs: Any) -> None:
    """Fire-and-forget review annotation on a daemon thread (never blocks the UI)."""
    if not enabled() or not span_id:
        return
    threading.Thread(
        target=annotate_review,
        args=(span_id,),
        kwargs=kwargs,
        daemon=True,
    ).start()
