"""Phoenix telemetry bootstrap helpers."""

from __future__ import annotations

from typing import Any

from harbourmaster import config

_INITIALISED = False
_TRACER = None


def init_telemetry() -> None:
    """Initialise Phoenix/OpenInference instrumentation once per process."""
    global _INITIALISED, _TRACER
    if _INITIALISED:
        return

    try:
        from phoenix.otel import register
    except Exception:  # noqa: BLE001
        return

    headers: dict[str, str] = {}
    if config.PHOENIX_API_KEY:
        headers["api_key"] = config.PHOENIX_API_KEY

    tracer_provider = register(
        project_name=config.PHOENIX_PROJECT_NAME,
        endpoint=config.PHOENIX_COLLECTOR_ENDPOINT,
        headers=headers or None,
        auto_instrument=False,
    )
    _TRACER = tracer_provider.get_tracer("harbourmaster.telemetry")

    # Temporarily skip LangChain auto-instrumentation: current OpenInference
    # callback implementation can miss newer LangGraph callback methods
    # (e.g. on_interrupt/on_resume), which surfaces noisy runtime errors.
    # OpenAI instrumentation still captures model-level traces in Phoenix.

    try:
        from openinference.instrumentation.openai import OpenAIInstrumentor

        OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
    except Exception:  # noqa: BLE001
        pass

    _INITIALISED = True


def _coerce_str(value: Any) -> str:
    return str(value) if value is not None else ""


def record_inspection_span(name: str, report: dict[str, Any], direction: str = "inspection") -> None:
    """Record inspection metadata as a short-lived span for dashboard queries."""
    if not _INITIALISED or _TRACER is None:
        return
    try:
        with _TRACER.start_as_current_span(name) as span:
            categories = report.get("categories", [])
            if isinstance(categories, list):
                categories_text = ",".join(str(cat).strip() for cat in categories if str(cat).strip())
            else:
                categories_text = _coerce_str(categories)

            span.set_attribute("direction", direction)
            span.set_attribute("agent_id", _coerce_str(report.get("agent_id")))
            span.set_attribute("inspection.verdict", _coerce_str(report.get("verdict", "UNKNOWN")))
            span.set_attribute("inspection.reason", _coerce_str(report.get("reason", "")))
            span.set_attribute("inspection.risk_score", float(report.get("risk_score", 0.0) or 0.0))
            span.set_attribute("inspection.categories", categories_text)
    except Exception:  # noqa: BLE001
        return


def log_guard_annotation(*, trace_id: str, agent_id: str, report: dict) -> None:
    """Backward-compatible wrapper for older callsites."""
    enriched = dict(report)
    enriched["agent_id"] = enriched.get("agent_id") or agent_id
    record_inspection_span("harbourmaster.guard", enriched, direction="guard")
