"""Data models for Governance Copilot responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class CopilotMessage:
    role: Literal["user", "assistant"]
    content: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceCitation:
    kind: str
    title: str
    detail: str = ""
    link: str = ""


@dataclass
class CopilotResult:
    answer: str
    sources: list[SourceCitation] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    console_links: list[str] = field(default_factory=list)
