"""GovernedLLM wired directly to Gemini's OpenAI-compatible endpoint."""

import json
from dataclasses import dataclass, field
from typing import Any

from openai import APIStatusError, OpenAI

from harbourmaster import config
from harbourmaster.telemetry import record_inspection_span


@dataclass
class GovernedResponse:
    """A model response paired with a governance inspection report."""

    text: str
    inspection: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        """Overall governance verdict: ALLOW | HUMAN_REVIEW | DENY."""
        return str(self.inspection.get("verdict", "UNKNOWN"))

    @property
    def blocked(self) -> bool:
        return self.verdict in ("DENY",)

    @property
    def ingress_risk(self) -> float:
        return float(self.inspection.get("ingress_risk", self.inspection.get("risk_score", 0.0)))

    @property
    def egress_risk(self) -> float:
        return float(self.inspection.get("egress_risk", self.inspection.get("risk_score", 0.0)))

    @property
    def mismatches(self) -> list:
        """Compatibility property retained for legacy UI paths."""
        return list(self.inspection.get("mismatches", []))

class GovernedLLM:
    """An agent-scoped LLM client that calls Gemini directly."""

    def __init__(
        self,
        agent_id: str,
        declared_intent: str,
        model: str,
        temperature: float = 0.2,
    ) -> None:
        self.agent_id = agent_id
        self.declared_intent = declared_intent
        self.model = model
        self.temperature = temperature
        self._client = OpenAI(
            base_url=config.GEMINI_BASE_URL,
            api_key=config.GEMINI_API_KEY,
        )

    def complete(self, messages: list[dict], **kwargs: Any) -> GovernedResponse:
        """Send a chat completion and return output + inspection metadata."""

        try:
            raw = self._client.chat.completions.with_raw_response.create(
                model=self.model,
                messages=messages,
                temperature=kwargs.pop("temperature", self.temperature),
                **kwargs,
            )
            payload = json.loads(raw.text)
        except APIStatusError as exc:
            try:
                payload = exc.response.json()
            except Exception:  # noqa: BLE001
                payload = {
                    "inspection": {"verdict": "UNKNOWN", "error": str(exc)},
                    "choices": [],
                }

        payload, upstream_error = _normalise_payload(payload)

        report = {
            "verdict": "ALLOW",
            "agent_id": self.agent_id,
            "declared_intent": self.declared_intent,
        }
        if isinstance(payload.get("inspection"), dict):
            report.update(payload["inspection"])
        choices = payload.get("choices", [])
        text = ""
        if choices:
            text = choices[0].get("message", {}).get("content") or ""
        if not text and upstream_error:
            # Surface the upstream error (e.g. Gemini 4xx JSON array) so the
            # caller can see something useful instead of an empty string.
            text = upstream_error
        record_inspection_span(
            name=f"harbourmaster.llm.{self.agent_id}",
            report=report,
            direction="model_call",
        )
        return GovernedResponse(text=text, inspection=report, raw=payload)


def _normalise_payload(payload: Any) -> tuple[dict, str]:
    """Coerce upstream payload into a dict and extract any error message.

    Gemini's Generative Language API returns errors as a JSON array, e.g.
    ``[{"error": {"code": 400, "message": "..."}}]``. The OpenAI SDK happily
    decodes that as a Python ``list``, which then breaks the dict-shaped code
    below. Normalise it here so the rest of ``complete`` can assume a dict.
    """
    if isinstance(payload, dict):
        return payload, ""

    if isinstance(payload, list):
        error_text = ""
        for item in payload:
            if isinstance(item, dict) and "error" in item:
                err = item.get("error") or {}
                if isinstance(err, dict):
                    error_text = err.get("message") or json.dumps(err)
                else:
                    error_text = str(err)
                break
        if not error_text:
            error_text = json.dumps(payload)[:500]
        return (
            {
                "inspection": {"verdict": "UNKNOWN", "error": error_text},
                "choices": [],
            },
            error_text,
        )

    # Anything else (string, None, ...) — wrap defensively.
    return (
        {
            "inspection": {"verdict": "UNKNOWN", "error": f"unexpected payload: {type(payload).__name__}"},
            "choices": [],
        },
        str(payload)[:500],
    )
