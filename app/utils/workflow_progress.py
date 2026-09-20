"""Live workflow execution progress for the tender review UI."""

from __future__ import annotations

import html as _html
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Literal

import streamlit as st

from harbourmaster.agents import SPECIALIST_DEFS, SPECIALIST_KEYS

StepStatus = Literal["pending", "running", "done", "skipped", "error"]

STATUS_ICON = {
    "pending": "○",
    "running": "◉",
    "done": "✓",
    "skipped": "—",
    "error": "✗",
}

SPECIALIST_LABELS = {
    key: key.replace("_", " ").title() for key in SPECIALIST_KEYS
}

# Styled status badge content + row class for the activity/timeline indicators.
_STATUS_BADGE = {"done": "✓", "running": "●", "error": "✕", "skipped": "—", "pending": ""}
_STATUS_ROW_CLASS = {
    "done": "hm-act-done",
    "running": "hm-act-running",
    "error": "hm-act-error",
    "skipped": "hm-act-skipped",
    "pending": "hm-act-pending",
}


def _activity_row(status: str, label: str, detail: str = "") -> str:
    cls = _STATUS_ROW_CLASS.get(status, "hm-act-pending")
    badge = _STATUS_BADGE.get(status, "")
    body = f'<div class="hm-act-label">{label}</div>'
    if detail:
        body += f'<div class="hm-act-detail">{detail}</div>'
    return (
        f'<div class="hm-act-row {cls}"><div class="hm-act-badge">{badge}</div>'
        f'<div class="hm-act-body">{body}</div></div>'
    )


def _activity_panel(title: str, rows: list[str]) -> str:
    return f'<div class="hm-act-title">{title}</div><div class="hm-act">' + "".join(rows) + "</div>"


def _log_kind(line: str) -> tuple[str, str]:
    """Map an activity-log line to a (css-kind, icon) pair for colour-coded display."""
    low = line.lower()
    if low.startswith("started"):
        return "started", "▶"
    if low.startswith("completed"):
        return "done", "✓"
    if "block" in low:
        return "error", "⛔"
    if "error" in low:
        return "error", "✕"
    if "revision" in low:
        return "revision", "↻"
    if "awaiting" in low:
        return "started", "⏸"
    return "info", "•"

FULL_WORKFLOW_STEPS: tuple[dict[str, str], ...] = (
    {"id": "guard", "label": "Guard evaluation", "description": "Inline ALLOW / HUMAN_REVIEW / DENY check"},
    {"id": "segment", "label": "Clause segmentation", "description": "Split tender into reviewable clauses"},
    {"id": "retrieval", "label": "Elastic precedent retrieval", "description": "Load similar policies and precedents"},
    {"id": "specialists", "label": "Specialist analysts", "description": "Parallel legal, financial, delivery, IP, compliance review"},
    {"id": "aggregate", "label": "Risk aggregation", "description": "Weighted overall risk score"},
    {"id": "verifier", "label": "Verifier loop", "description": "Validate findings and request revisions"},
    {"id": "revision", "label": "Revision pass", "description": "Re-run specialists on flagged clauses"},
    {"id": "governance", "label": "Governance routing", "description": "Auto-continue or escalate to human review"},
    {"id": "human_review", "label": "Human review checkpoint", "description": "Pause for reviewer decision"},
    {"id": "negotiator", "label": "Counter-clause negotiation", "description": "Draft proposed redlines"},
    {"id": "draft", "label": "Summary draft", "description": "Produce reviewer-ready output"},
)

RESUME_WORKFLOW_STEPS: tuple[dict[str, str], ...] = (
    {"id": "negotiator", "label": "Counter-clause negotiation", "description": "Draft proposed redlines"},
    {"id": "draft", "label": "Summary draft", "description": "Produce reviewer-ready output"},
)

NODE_TO_STEPS: dict[str, list[str]] = {
    "guard": ["guard"],
    "segment": ["segment", "retrieval"],
    "specialists": ["specialists"],
    "aggregate": ["aggregate"],
    "verifier": ["verifier"],
    "revision": ["revision"],
    "governance": ["governance"],
    "human_review": ["human_review"],
    "negotiator": ["negotiator"],
    "draft": ["draft"],
}


@dataclass
class WorkflowProgressTracker:
    """Track and render LangGraph execution phases."""

    mode: Literal["full", "resume"] = "full"
    steps: list[dict[str, str]] = field(default_factory=list)
    statuses: dict[str, StepStatus] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)
    specialist_status: dict[str, StepStatus] = field(default_factory=dict)
    activity_log: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    current_step: str = ""
    _progress_bar: Any = None
    _progress_text: Any = None
    _timeline: Any = None
    _metrics_row: Any = None
    _activity: Any = None
    _specialists_panel: Any = None

    def __post_init__(self) -> None:
        if not self.steps:
            self.steps = list(RESUME_WORKFLOW_STEPS if self.mode == "resume" else FULL_WORKFLOW_STEPS)
        for step in self.steps:
            sid = step["id"]
            if sid not in self.statuses:
                self.statuses[sid] = "pending"
        for key in SPECIALIST_KEYS:
            self.specialist_status.setdefault(key, "pending")

    def mount(self) -> None:
        """Create Streamlit placeholders for live updates."""
        st.markdown("### Processing tender")
        self._progress_bar = st.progress(0.0)
        self._progress_text = st.empty()
        self._metrics_row = st.empty()
        self._specialists_panel = st.empty()
        self._timeline = st.empty()
        self._activity = st.empty()
        self.render()

    def _step_ids(self) -> list[str]:
        return [step["id"] for step in self.steps]

    def _fraction_done(self) -> float:
        ids = self._step_ids()
        if not ids:
            return 0.0
        done = sum(1 for sid in ids if self.statuses.get(sid) in {"done", "skipped"})
        running = sum(0.5 for sid in ids if self.statuses.get(sid) == "running")
        return min(1.0, (done + running) / len(ids))

    def _log(self, message: str) -> None:
        if self.activity_log and self.activity_log[-1] == message:
            return  # collapse consecutive duplicates (e.g. guard completed twice)
        self.activity_log.append(message)
        self.activity_log = self.activity_log[-10:]

    def _has_step(self, step_id: str) -> bool:
        return step_id in self._step_ids()

    def start(self, step_id: str, detail: str | None = None) -> None:
        if not self._has_step(step_id):
            return
        self.statuses[step_id] = "running"
        self.current_step = step_id
        if detail:
            self.details[step_id] = detail
        label = next((s["label"] for s in self.steps if s["id"] == step_id), step_id)
        self._log(f"Started: {label}")

    def complete(self, step_id: str, detail: str | None = None) -> None:
        if not self._has_step(step_id):
            return
        self.statuses[step_id] = "done"
        if detail:
            self.details[step_id] = detail
        label = next((s["label"] for s in self.steps if s["id"] == step_id), step_id)
        suffix = f" — {detail}" if detail else ""
        self._log(f"Completed: {label}{suffix}")

    def skip(self, step_id: str, detail: str | None = None) -> None:
        if not self._has_step(step_id):
            return
        self.statuses[step_id] = "skipped"
        if detail:
            self.details[step_id] = detail

    def fail(self, step_id: str, error: str) -> None:
        if not self._has_step(step_id):
            return
        self.statuses[step_id] = "error"
        self.details[step_id] = error
        self._log(f"Error in {step_id}: {error}")

    def reset_specialists(self, targets: list[str] | None = None) -> None:
        for key in targets or list(SPECIALIST_KEYS):
            self.specialist_status[key] = "pending"

    def apply_node_update(self, node_name: str, update: dict[str, Any] | None = None) -> None:
        """Mark steps complete when a LangGraph node finishes."""
        update = update or {}
        if node_name == "guard":
            verdict = update.get("guard_verdict")
            if verdict:
                self.metrics["guard_verdict"] = verdict
            if update.get("blocked"):
                self.metrics["guard_blocked"] = True
            self.complete("guard", verdict)
        elif node_name == "blocked":
            # Guard denied the input: nothing else ran — mark the remaining steps skipped so
            # the progress bar resolves to a clean blocked state.
            self.metrics["guard_blocked"] = True
            for step in self.steps:
                sid = step["id"]
                if self.statuses.get(sid) not in {"done", "skipped"} and sid != "guard":
                    self.skip(sid, "blocked at ingress")
            self._log("Workflow blocked by governance guard (DENY)")
        elif node_name == "segment":
            if self.statuses.get("segment") != "done":
                clause_count = len(update.get("clauses", []))
                self.metrics["clause_count"] = clause_count
                self.complete("segment", f"{clause_count} clauses")
            if self.statuses.get("retrieval") != "done":
                snippet_count = len(update.get("retrieval_context", []))
                self.metrics["retrieval_count"] = snippet_count
                self.complete("retrieval", f"{snippet_count} snippets")
        elif node_name == "specialists":
            self.complete("specialists", f"{self._specialists_done_count()}/{len(SPECIALIST_KEYS)} analysts")
        elif node_name == "aggregate":
            risk = update.get("overall_risk")
            if risk is not None:
                self.metrics["overall_risk"] = risk
            findings = update.get("findings", {}).get("findings", [])
            high = sum(1 for f in findings if f.get("risk_level") == "high")
            self.metrics["high_risk_count"] = high
            # Aggregation only runs once every specialist has produced findings, so reflect
            # all specialists as done (a later revision reset would otherwise under-count).
            for key in SPECIALIST_KEYS:
                self.specialist_status[key] = "done"
            self.complete("aggregate", f"risk {float(risk or 0):.2f}")
        elif node_name == "verifier":
            pending = update.get("pending_revisions", {})
            count = sum(len(v) for v in pending.values())
            self.complete("verifier", f"{count} revisions pending" if count else "verified")
        elif node_name == "revision":
            round_num = update.get("revision_round", 0)
            self.metrics["revision_round"] = round_num
            self.complete("revision", f"round {round_num}")
            self.reset_specialists(list(update.get("pending_revisions", {}).keys()) or None)
            self.start("specialists", f"Revision round {round_num}")
        elif node_name == "governance":
            route = self.metrics.get("governance_route", "continue")
            self.complete("governance", route)
        elif node_name == "human_review":
            self.complete("human_review", "awaiting reviewer")
        elif node_name == "negotiator":
            count = len(update.get("counter_clauses", []))
            self.complete("negotiator", f"{count} counter-clauses")
        elif node_name == "draft":
            self.complete("draft", "summary ready")

    def apply_custom_event(self, event: dict[str, Any]) -> None:
        """Handle fine-grained stream events from graph nodes."""
        event_type = str(event.get("type", ""))
        if event_type == "guard_complete":
            self.metrics["guard_verdict"] = event.get("verdict", "UNKNOWN")
            self.metrics["guard_blocked"] = bool(event.get("blocked"))
            self.start("guard")
            self.complete("guard", str(event.get("verdict", "UNKNOWN")))
        elif event_type == "segment_complete":
            count = int(event.get("clause_count", 0))
            self.metrics["clause_count"] = count
            self.start("segment")
            self.complete("segment", f"{count} clauses")
        elif event_type == "retrieval_complete":
            count = int(event.get("snippet_count", 0))
            self.metrics["retrieval_count"] = count
            self.start("retrieval")
            self.complete("retrieval", f"{count} snippets")
        elif event_type == "specialist_start":
            key = str(event.get("specialist", ""))
            if key in self.specialist_status:
                self.specialist_status[key] = "running"
                if self.statuses.get("specialists") == "pending":
                    self.start("specialists")
        elif event_type == "specialist_complete":
            key = str(event.get("specialist", ""))
            findings = int(event.get("findings", 0))
            if key in self.specialist_status:
                self.specialist_status[key] = "done"
                label = SPECIALIST_LABELS.get(key, key)
                self._log(f"{label} analyst completed — {findings} findings")
        elif event_type == "risk_computed":
            risk = float(event.get("overall_risk", 0))
            self.metrics["overall_risk"] = risk
            self.metrics["high_risk_count"] = int(event.get("high_risk_count", 0))
        elif event_type == "verifier_complete":
            pending = int(event.get("pending_revisions", 0))
            self.metrics["pending_revisions"] = pending
        elif event_type == "revision_round":
            round_num = int(event.get("round", 0))
            self.metrics["revision_round"] = round_num
            targets = event.get("targets") or list(SPECIALIST_KEYS)
            self.reset_specialists(list(targets))
            self._log(f"Revision round {round_num} — re-running specialists")
        elif event_type == "route_decision":
            route = str(event.get("route", "continue"))
            self.metrics["governance_route"] = route
        elif event_type == "negotiator_complete":
            count = int(event.get("counter_clauses", 0))
            self.metrics["counter_clause_count"] = count
        elif event_type == "draft_complete":
            self.metrics["draft_ready"] = True

    def handle_stream_chunk(self, mode: str, chunk: Any) -> dict[str, Any] | None:
        """Process a stream chunk; return interrupt payload when execution pauses."""
        if mode == "updates" and isinstance(chunk, dict):
            if "__interrupt__" in chunk:
                interrupts = chunk["__interrupt__"]
                if interrupts:
                    payload = interrupts[0].value
                    # Advance the live step to the actual pause point so the panel reads
                    # "Human review checkpoint" (not a stale earlier step).
                    self.start("human_review", "awaiting reviewer")
                    return payload if isinstance(payload, dict) else None
            for node_name, update in chunk.items():
                if node_name.startswith("__"):
                    continue
                self.apply_node_update(node_name, update if isinstance(update, dict) else {})
        elif mode == "custom":
            payload = chunk
            if isinstance(chunk, (list, tuple)) and chunk:
                payload = chunk[-1]
            if isinstance(payload, dict):
                self.apply_custom_event(payload)
        return None

    def _specialists_done_count(self) -> int:
        return sum(1 for status in self.specialist_status.values() if status == "done")

    def sidebar_snapshot(self) -> dict[str, Any]:
        current_label = next(
            (s["label"] for s in self.steps if s["id"] == self.current_step),
            self.current_step or "—",
        )
        return {
            "current_step": current_label,
            "fraction": self._fraction_done(),
            "revision_round": self.metrics.get("revision_round", 0),
            "specialists_done": self._specialists_done_count(),
            "specialists_total": len(SPECIALIST_KEYS),
            "guard_verdict": self.metrics.get("guard_verdict"),
            "overall_risk": self.metrics.get("overall_risk"),
        }

    def render(self) -> None:
        if self._progress_bar is None:
            return

        fraction = self._fraction_done()
        current_label = next(
            (s["label"] for s in self.steps if s["id"] == self.current_step),
            "Preparing…",
        )
        self._progress_bar.progress(fraction)
        self._progress_text.markdown(f"**{int(fraction * 100)}%** — {current_label}")

        metrics = self.metrics
        cols = self._metrics_row.columns(5)
        cols[0].metric("Clauses", metrics.get("clause_count", "—"))
        cols[1].metric("Guard", metrics.get("guard_verdict", "—"))
        cols[2].metric(
            "Specialists",
            f"{self._specialists_done_count()}/{len(SPECIALIST_KEYS)}",
        )
        risk = metrics.get("overall_risk")
        cols[3].metric("Overall risk", f"{float(risk):.2f}" if risk is not None else "—")
        cols[4].metric("Revision", metrics.get("revision_round", 0))

        if self.mode == "full" and "specialists" in self._step_ids():
            rows = [
                _activity_row(
                    self.specialist_status.get(key, "pending"),
                    SPECIALIST_LABELS.get(key, key),
                    SPECIALIST_DEFS[key]["focus"][:70],
                )
                for key in SPECIALIST_KEYS
            ]
            self._specialists_panel.markdown(
                _activity_panel("Specialist agents", rows), unsafe_allow_html=True
            )

        timeline_rows = [
            _activity_row(
                self.statuses.get(step["id"], "pending"),
                step["label"],
                self.details.get(step["id"], "") or step.get("description", ""),
            )
            for step in self.steps
        ]
        self._timeline.markdown(
            _activity_panel("Execution timeline", timeline_rows), unsafe_allow_html=True
        )

        if self.activity_log:
            log_rows = []
            for line in reversed(self.activity_log[-8:]):  # newest first
                kind, icon = _log_kind(line)
                log_rows.append(
                    f'<div class="hm-log-row hm-log-{kind}"><span class="hm-log-ic">{icon}</span>'
                    f'<span class="hm-log-text">{_html.escape(line)}</span></div>'
                )
            self._activity.markdown(
                '<div class="hm-act-title">Activity</div><div class="hm-log">'
                + "".join(log_rows)
                + "</div>",
                unsafe_allow_html=True,
            )


def stream_graph_run(
    graph: Any,
    inputs: Any,
    run_config: dict[str, Any],
    tracker: WorkflowProgressTracker,
    *,
    on_tick: Any | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Stream a graph run with live progress. Returns (final_state, interrupt_payload)."""
    interrupt_payload: dict[str, Any] | None = None

    # Tag this run's spans with the review's thread id so telemetry can be grouped
    # per review (powers the Copilot's review_telemetry tool).
    thread_id = str((run_config or {}).get("configurable", {}).get("thread_id", "") or "")
    try:
        from openinference.instrumentation import using_attributes

        session_ctx = using_attributes(session_id=thread_id) if thread_id else nullcontext()
    except Exception:  # noqa: BLE001
        session_ctx = nullcontext()

    # Root span for the whole run: node spans (and their LLM/inspection children)
    # nest under this, so Phoenix shows one review trace tree instead of a flat
    # pile of root spans. Carries input.value (tender text) / output.value (final
    # summary) + status so Phoenix's trace-list columns are populated rather than
    # showing "--". A guard DENY / HITL pause just ends this span early; the resume
    # call opens a fresh root sharing the same session_id.
    def set_span_output(*_a, **_k):  # fallback if telemetry import fails
        return None

    try:
        from harbourmaster.telemetry import agent_span, set_span_output

        root_ctx = agent_span(
            "harbourmaster.tender_review",
            kind="CHAIN",
            attributes={"session.id": thread_id},
            input_value=_root_input_text(inputs),
        )
    except Exception:  # noqa: BLE001
        root_ctx = nullcontext()

    final_state: dict[str, Any] | None = None
    root_span_id: str | None = None
    with session_ctx, root_ctx as root_span:
        for mode, chunk in graph.stream(inputs, run_config, stream_mode=["updates", "custom"]):
            payload = tracker.handle_stream_chunk(mode, chunk)
            if payload is not None:
                interrupt_payload = payload
            tracker.render()
            if on_tick is not None:
                on_tick(tracker.sidebar_snapshot())

        # Capture the root span_id while the span is still live (for annotations).
        try:
            from harbourmaster.phoenix_annotations import span_id_hex

            root_span_id = span_id_hex(root_span)
        except Exception:  # noqa: BLE001
            root_span_id = None

        # Record the run's output on the root span before it closes.
        if interrupt_payload is not None:
            set_span_output(root_span, "Paused — awaiting human review")
        else:
            snapshot = graph.get_state(run_config)
            final_state = dict(snapshot.values or {})
            set_span_output(
                root_span, final_state.get("draft_summary") or "Review completed"
            )

    _submit_review_annotations(graph, run_config, root_span_id, final_state, interrupt_payload)

    if interrupt_payload is not None:
        return None, interrupt_payload

    return final_state, None


def _submit_review_annotations(
    graph: Any,
    run_config: dict[str, Any],
    root_span_id: str | None,
    final_state: dict[str, Any] | None,
    interrupt_payload: dict[str, Any] | None,
) -> None:
    """Fire automated governance annotations onto the review's root span (best-effort)."""
    if not root_span_id:
        return
    try:
        from harbourmaster import config
        from harbourmaster.phoenix_annotations import submit_review_async

        state = final_state
        if state is None:  # interrupt branch — read the paused state for verdict/risk
            try:
                state = dict(graph.get_state(run_config).values or {})
            except Exception:  # noqa: BLE001
                state = {}

        if state.get("blocked"):
            decision = "blocked"
        elif interrupt_payload is not None:
            decision = "awaiting_review"
        elif state.get("review_decision"):
            decision = str(state["review_decision"].get("decision", "unknown"))
        else:
            decision = "auto-approved"

        submit_review_async(
            root_span_id,
            guard_verdict=str(state.get("guard_verdict", "UNKNOWN")),
            overall_risk=state.get("overall_risk", 0.0),
            threshold=config.REVIEW_RISK_THRESHOLD,
            decision=decision,
            reason=str(state.get("block_reason", "")),
        )
    except Exception:  # noqa: BLE001
        return


def _root_input_text(inputs: Any) -> str:
    """Best-effort input text for the review root span (tender text or resume note)."""
    if isinstance(inputs, dict):
        return str(inputs.get("tender_text", ""))
    return "Resume after human review"
