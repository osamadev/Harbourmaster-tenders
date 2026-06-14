"""Phoenix telemetry bootstrap helpers."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

# elasticsearch-py ships its own native OpenTelemetry instrumentation that auto-
# activates as soon as a global tracer provider exists (which phoenix.otel.register
# sets below). That floods Phoenix with "unknown" cluster.health / index /
# indices.exists / search spans — pure infrastructure noise. Disable it by default
# (setdefault so an explicit operator override still wins). Read at ES client
# construction time, so this lands before any Elasticsearch(...) is built.
os.environ.setdefault("OTEL_PYTHON_INSTRUMENTATION_ELASTICSEARCH_ENABLED", "false")

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

    # OpenAI instrumentation captures the model-level LLM spans. GovernedLLM calls
    # the Gemini OpenAI-compatible endpoint directly (raw SDK, bypassing LangChain),
    # so these spans nest under the ambient agent/node spans we open in the graph
    # (see ``agent_span`` + ``stream_graph_run``) via OTel context — that's what
    # turns the otherwise-flat pile of root spans into one review trace tree.
    #
    # NOTE: We deliberately do NOT enable LangChainInstrumentor. It builds its own
    # node tree from LangChain's run-id graph but does not push node spans into the
    # ambient OTel context, so the raw OpenAI + inspection spans would stay detached
    # roots AND its node layer would duplicate our ambient spans.
    try:
        from openinference.instrumentation.openai import OpenAIInstrumentor

        OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
    except Exception:  # noqa: BLE001
        pass

    _INITIALISED = True


_IO_LIMIT = 4000


def _io_attrs(value: Any) -> tuple[str, str]:
    """Render a value as (text, mime_type) for OpenInference input/output attrs."""
    if isinstance(value, (dict, list)):
        try:
            import json

            return json.dumps(value, default=str)[:_IO_LIMIT], "application/json"
        except Exception:  # noqa: BLE001
            return str(value)[:_IO_LIMIT], "text/plain"
    return str(value)[:_IO_LIMIT], "text/plain"


def set_span_output(span: Any, value: Any) -> None:
    """Set OpenInference ``output.value`` on a span (no-op if span is None).

    Phoenix's trace-list ``output`` column and the span detail view read this
    attribute; without it the row shows ``--``.
    """
    if span is None:
        return
    try:
        text, mime = _io_attrs(value)
        span.set_attribute("output.value", text)
        span.set_attribute("output.mime_type", mime)
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def agent_span(
    name: str,
    kind: str = "CHAIN",
    attributes: dict[str, Any] | None = None,
    input_value: Any = None,
):
    """Open an ambient span so child LLM/inspection spans nest under it.

    Used to wrap each graph node (and the whole review run) so the raw OpenAI
    calls and ``record_inspection_span`` spans created inside form a proper tree
    in Phoenix instead of a flat set of root spans. Sets OpenInference
    ``input.value`` (so Phoenix's input column is populated) and marks the span
    status OK on clean exit (ERROR is set automatically on exception). A no-op
    until telemetry is initialised so non-traced contexts (tests/CLI) keep working.
    """
    if not _INITIALISED or _TRACER is None:
        yield None
        return
    from opentelemetry.trace import Status, StatusCode

    with _TRACER.start_as_current_span(name) as span:
        try:
            span.set_attribute("openinference.span.kind", kind)
            if input_value is not None:
                text, mime = _io_attrs(input_value)
                span.set_attribute("input.value", text)
                span.set_attribute("input.mime_type", mime)
            for key, value in (attributes or {}).items():
                if value is not None:
                    span.set_attribute(key, value)
        except Exception:  # noqa: BLE001
            pass
        yield span
        # Only reached when the body did not raise (start_as_current_span sets
        # ERROR on exception); mark a clean run OK so Phoenix shows a status.
        try:
            span.set_status(Status(StatusCode.OK))
        except Exception:  # noqa: BLE001
            pass


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

            # Tag a span kind so these governance records render as proper spans in
            # Phoenix (not "unknown"). CHAIN — not LLM — so they don't look like a
            # duplicate of the real ChatCompletion span sitting beside them. The
            # dashboard still reads the explicit `direction` attribute (see
            # phoenix_audit), which takes precedence over span kind there.
            span.set_attribute("openinference.span.kind", "CHAIN")
            span.set_attribute("direction", direction)
            span.set_attribute("agent_id", _coerce_str(report.get("agent_id")))
            span.set_attribute("inspection.verdict", _coerce_str(report.get("verdict", "UNKNOWN")))
            span.set_attribute("inspection.reason", _coerce_str(report.get("reason", "")))
            span.set_attribute("inspection.risk_score", float(report.get("risk_score", 0.0) or 0.0))
            span.set_attribute("inspection.categories", categories_text)

            # Populate input/output so the span detail view isn't empty: the
            # governance verdict + reason is the meaningful "output" of this record.
            verdict = _coerce_str(report.get("verdict", "UNKNOWN"))
            reason = _coerce_str(report.get("reason", ""))
            span.set_attribute("output.value", f"{verdict}: {reason}".strip(": "))
            span.set_attribute("output.mime_type", "text/plain")

            # Inherit OpenInference context attributes (e.g. session.id from the
            # workflow run) so inspection spans group by review like the LLM spans.
            try:
                from openinference.instrumentation import get_attributes_from_context

                for attr_key, attr_value in get_attributes_from_context():
                    span.set_attribute(attr_key, attr_value)
            except Exception:  # noqa: BLE001
                pass

            try:
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.OK))
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        return


def log_guard_annotation(*, trace_id: str, agent_id: str, report: dict) -> None:
    """Backward-compatible wrapper for older callsites."""
    enriched = dict(report)
    enriched["agent_id"] = enriched.get("agent_id") or agent_id
    record_inspection_span("harbourmaster.guard", enriched, direction="guard")
