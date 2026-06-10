"""Central settings resolver for local/cloud modes and MCP configuration."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

from dotenv import load_dotenv

from harbourmaster.runtime_config import (
    SECRET_KEYS,
    apply_runtime_to_environ,
    load_runtime_config,
    secret_is_set,
)

load_dotenv()

Mode = Literal["local", "cloud"]

PLACEHOLDER_PREFIXES = ("sk-phoenix-local", "sk-elastic-local", "your-", "changeme")

DEFAULT_PHOENIX_CLOUD_URL = "https://app.phoenix.arize.com"
DEFAULT_MCP_PHOENIX_PACKAGE = "@arizeai/phoenix-mcp@4.0.13"
DEFAULT_MCP_ELASTIC_PACKAGE = "@elastic/mcp-server-elasticsearch@0.4.0"

KNOWN_KEYS = frozenset(
    {
        "PHOENIX_MODE",
        "ELASTIC_MODE",
        "RUNNING_IN_DOCKER",
        "GEMINI_API_KEY",
        "GEMINI_BASE_URL",
        "GEMINI_ANALYST_MODEL",
        "GEMINI_DRAFTER_MODEL",
        "PHOENIX_BASE_URL",
        "PHOENIX_COLLECTOR_ENDPOINT",
        "PHOENIX_CONSOLE_URL",
        "PHOENIX_API_KEY",
        "PHOENIX_PROJECT_NAME",
        "PHOENIX_PORT",
        "ELASTIC_ENABLED",
        "ELASTIC_URL",
        "ELASTIC_API_KEY",
        "ELASTIC_USERNAME",
        "ELASTIC_PASSWORD",
        "ELASTIC_INDEX_PREFIX",
        "MCP_ENABLED",
        "MCP_PHOENIX_ENABLED",
        "MCP_ELASTIC_ENABLED",
        "MCP_PHOENIX_PACKAGE",
        "MCP_ELASTIC_PACKAGE",
        "MCP_LOAD_TIMEOUT_SEC",
        "REVIEW_RISK_THRESHOLD",
        "VERIFIER_MAX_REVISIONS",
        "NEGOTIATOR_INCLUDE_MEDIUM",
        "LEGAL_SPECIALIST_WEIGHT",
        "FINANCIAL_SPECIALIST_WEIGHT",
        "DELIVERY_SPECIALIST_WEIGHT",
        "IP_DATA_SPECIALIST_WEIGHT",
        "COMPLIANCE_SPECIALIST_WEIGHT",
    }
)

_snapshot: "ResolvedSettings | None" = None


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def is_placeholder_secret(value: Any) -> bool:
    stripped = str(value or "").strip().lower()
    if not stripped:
        return True
    return any(stripped.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def usable_secret(value: Any) -> str | None:
    stripped = str(value or "").strip()
    if not stripped or is_placeholder_secret(stripped):
        return None
    return stripped


def _running_in_docker(raw: dict[str, Any]) -> bool:
    return _as_bool(raw.get("RUNNING_IN_DOCKER"), False)


def _parse_mode(value: Any, default: Mode = "local") -> Mode:
    mode = str(value or default).strip().lower()
    return "cloud" if mode == "cloud" else "local"


@dataclass(frozen=True)
class PhoenixRuntime:
    mode: Mode
    api_base_url: str
    collector_endpoint: str
    console_url: str
    project_name: str
    api_key: str | None
    port: int
    auth_headers: dict[str, str]


@dataclass(frozen=True)
class ElasticRuntime:
    mode: Mode
    url: str
    api_key: str | None
    username: str | None
    password: str | None
    index_prefix: str
    enabled: bool


@dataclass(frozen=True)
class McpRuntime:
    enabled: bool
    phoenix_enabled: bool
    elastic_enabled: bool
    phoenix_package: str
    elastic_package: str
    load_timeout_sec: int
    npx_command: str


@dataclass(frozen=True)
class ResolvedSettings:
    phoenix: PhoenixRuntime
    elastic: ElasticRuntime
    mcp: McpRuntime
    gemini_api_key: str
    gemini_base_url: str
    analyst_model: str
    drafter_model: str
    review_risk_threshold: float
    verifier_max_revisions: int
    negotiator_include_medium: bool
    specialist_weights: dict[str, float]
    sources: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def _layered_values(runtime_override: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    """Build merged config with per-key source tracking."""
    sources: dict[str, str] = {}
    merged: dict[str, Any] = {}

    def set_value(key: str, value: Any, source: str) -> None:
        merged[key] = value
        sources[key] = source

    defaults: dict[str, Any] = {
        "PHOENIX_MODE": "local",
        "ELASTIC_MODE": "local",
        "PHOENIX_PROJECT_NAME": "harbourmaster",
        "PHOENIX_PORT": 6006,
        "ELASTIC_ENABLED": True,
        "ELASTIC_INDEX_PREFIX": "harbourmaster",
        "MCP_ENABLED": True,
        "MCP_PHOENIX_ENABLED": True,
        "MCP_ELASTIC_ENABLED": True,
        "MCP_PHOENIX_PACKAGE": DEFAULT_MCP_PHOENIX_PACKAGE,
        "MCP_ELASTIC_PACKAGE": DEFAULT_MCP_ELASTIC_PACKAGE,
        "MCP_LOAD_TIMEOUT_SEC": 45,
        "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_ANALYST_MODEL": "gemini-2.5-pro",
        "GEMINI_DRAFTER_MODEL": "gemini-2.5-flash",
        "REVIEW_RISK_THRESHOLD": 0.6,
        "VERIFIER_MAX_REVISIONS": 1,
        "NEGOTIATOR_INCLUDE_MEDIUM": False,
        "LEGAL_SPECIALIST_WEIGHT": 1.2,
        "FINANCIAL_SPECIALIST_WEIGHT": 1.1,
        "DELIVERY_SPECIALIST_WEIGHT": 1.0,
        "IP_DATA_SPECIALIST_WEIGHT": 1.1,
        "COMPLIANCE_SPECIALIST_WEIGHT": 1.3,
    }
    for key, value in defaults.items():
        set_value(key, value, "default")

    runtime = {**load_runtime_config(), **(runtime_override or {})}
    for key, value in runtime.items():
        if key in KNOWN_KEYS or key in SECRET_KEYS:
            set_value(key, value, "runtime")

    for key in sorted(KNOWN_KEYS | SECRET_KEYS):
        if key not in os.environ or os.environ[key] == "":
            continue
        raw = os.environ[key]
        if key in {
            "ELASTIC_ENABLED",
            "MCP_ENABLED",
            "MCP_PHOENIX_ENABLED",
            "MCP_ELASTIC_ENABLED",
            "NEGOTIATOR_INCLUDE_MEDIUM",
            "RUNNING_IN_DOCKER",
        }:
            set_value(key, _as_bool(raw), "env")
        elif key in {"PHOENIX_PORT", "MCP_LOAD_TIMEOUT_SEC", "VERIFIER_MAX_REVISIONS"}:
            set_value(key, _as_int(raw, int(merged.get(key, 0))), "env")
        elif key.endswith("_WEIGHT") or key == "REVIEW_RISK_THRESHOLD":
            set_value(key, _as_float(raw, float(merged.get(key, 0.0))), "env")
        else:
            set_value(key, raw, "env")

    return merged, sources


def _resolve_phoenix_console_url(api_base_url: str, port: int, raw: dict[str, Any]) -> str:
    explicit = str(raw.get("PHOENIX_CONSOLE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    parsed = urlparse(api_base_url)
    host = (parsed.hostname or "").lower()
    if host in {"phoenix", "127.0.0.1"}:
        return f"http://localhost:{port}"
    return api_base_url.rstrip("/")


def resolve_settings(runtime_override: dict[str, Any] | None = None) -> ResolvedSettings:
    raw, sources = _layered_values(runtime_override)
    phoenix_mode = _parse_mode(raw.get("PHOENIX_MODE"))
    elastic_mode = _parse_mode(raw.get("ELASTIC_MODE"))
    in_docker = _running_in_docker(raw)
    phoenix_port = _as_int(raw.get("PHOENIX_PORT"), 6006)

    if phoenix_mode == "cloud":
        api_base = str(raw.get("PHOENIX_BASE_URL") or DEFAULT_PHOENIX_CLOUD_URL).rstrip("/")
    elif str(raw.get("PHOENIX_BASE_URL") or "").strip():
        api_base = str(raw.get("PHOENIX_BASE_URL")).rstrip("/")
    elif in_docker:
        api_base = "http://phoenix:6006"
    else:
        api_base = f"http://localhost:{phoenix_port}"

    collector = str(raw.get("PHOENIX_COLLECTOR_ENDPOINT") or "").strip() or f"{api_base}/v1/traces"
    console_url = _resolve_phoenix_console_url(api_base, phoenix_port, raw)
    phoenix_key = usable_secret(raw.get("PHOENIX_API_KEY"))
    phoenix_headers: dict[str, str] = {}
    if phoenix_key:
        phoenix_headers["Authorization"] = f"Bearer {phoenix_key}"

    if elastic_mode == "cloud":
        elastic_url = str(raw.get("ELASTIC_URL") or "").strip()
    elif str(raw.get("ELASTIC_URL") or "").strip():
        elastic_url = str(raw.get("ELASTIC_URL")).rstrip("/")
    elif in_docker:
        elastic_url = "http://elastic:9200"
    else:
        elastic_url = "http://localhost:9200"

    mcp_enabled = _as_bool(raw.get("MCP_ENABLED"), True)
    mcp_phoenix = _as_bool(raw.get("MCP_PHOENIX_ENABLED"), mcp_enabled)
    mcp_elastic = _as_bool(raw.get("MCP_ELASTIC_ENABLED"), mcp_enabled)

    return ResolvedSettings(
        phoenix=PhoenixRuntime(
            mode=phoenix_mode,
            api_base_url=api_base,
            collector_endpoint=collector,
            console_url=console_url,
            project_name=str(raw.get("PHOENIX_PROJECT_NAME") or "harbourmaster"),
            api_key=phoenix_key,
            port=phoenix_port,
            auth_headers=phoenix_headers,
        ),
        elastic=ElasticRuntime(
            mode=elastic_mode,
            url=elastic_url,
            api_key=usable_secret(raw.get("ELASTIC_API_KEY")),
            username=str(raw.get("ELASTIC_USERNAME") or "").strip() or None,
            password=usable_secret(raw.get("ELASTIC_PASSWORD")),
            index_prefix=str(raw.get("ELASTIC_INDEX_PREFIX") or "harbourmaster"),
            enabled=_as_bool(raw.get("ELASTIC_ENABLED"), True),
        ),
        mcp=McpRuntime(
            enabled=mcp_enabled,
            phoenix_enabled=mcp_phoenix,
            elastic_enabled=mcp_elastic,
            phoenix_package=str(raw.get("MCP_PHOENIX_PACKAGE") or DEFAULT_MCP_PHOENIX_PACKAGE),
            elastic_package=str(raw.get("MCP_ELASTIC_PACKAGE") or DEFAULT_MCP_ELASTIC_PACKAGE),
            load_timeout_sec=_as_int(raw.get("MCP_LOAD_TIMEOUT_SEC"), 45),
            npx_command=shutil.which("npx") or "npx",
        ),
        gemini_api_key=str(raw.get("GEMINI_API_KEY") or ""),
        gemini_base_url=str(raw.get("GEMINI_BASE_URL") or ""),
        analyst_model=str(raw.get("GEMINI_ANALYST_MODEL") or "gemini-2.5-pro"),
        drafter_model=str(raw.get("GEMINI_DRAFTER_MODEL") or "gemini-2.5-flash"),
        review_risk_threshold=_as_float(raw.get("REVIEW_RISK_THRESHOLD"), 0.6),
        verifier_max_revisions=_as_int(raw.get("VERIFIER_MAX_REVISIONS"), 1),
        negotiator_include_medium=_as_bool(raw.get("NEGOTIATOR_INCLUDE_MEDIUM"), False),
        specialist_weights={
            "legal": _as_float(raw.get("LEGAL_SPECIALIST_WEIGHT"), 1.2),
            "financial": _as_float(raw.get("FINANCIAL_SPECIALIST_WEIGHT"), 1.1),
            "delivery": _as_float(raw.get("DELIVERY_SPECIALIST_WEIGHT"), 1.0),
            "ip_data": _as_float(raw.get("IP_DATA_SPECIALIST_WEIGHT"), 1.1),
            "compliance": _as_float(raw.get("COMPLIANCE_SPECIALIST_WEIGHT"), 1.3),
        },
        sources=sources,
        raw=raw,
    )


def get_snapshot() -> ResolvedSettings:
    global _snapshot
    if _snapshot is None:
        apply_runtime_to_environ(load_runtime_config())
        _snapshot = resolve_settings()
    return _snapshot


def reload() -> ResolvedSettings:
    """Clear cached settings and rebuild from env + runtime JSON."""
    global _snapshot
    _snapshot = None
    load_dotenv(override=True)
    apply_runtime_to_environ(load_runtime_config())
    _snapshot = resolve_settings()
    try:
        from harbourmaster import config as legacy_config

        legacy_config._apply_snapshot(_snapshot)
    except Exception:  # noqa: BLE001
        pass
    return _snapshot


def preview_settings(updates: dict[str, Any]) -> ResolvedSettings:
    """Resolve settings as if runtime overrides included updates (not yet saved)."""
    return resolve_settings(runtime_override=updates)


def validate(snapshot: ResolvedSettings | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the active configuration."""
    settings = snapshot or get_snapshot()
    errors: list[str] = []
    warnings: list[str] = []

    if settings.phoenix.mode == "cloud" and not settings.phoenix.api_key:
        errors.append("PHOENIX_MODE=cloud requires a real PHOENIX_API_KEY.")
    if settings.elastic.mode == "cloud" and not settings.elastic.api_key:
        errors.append("ELASTIC_MODE=cloud requires a real ELASTIC_API_KEY.")
    if settings.elastic.enabled and not settings.elastic.url:
        errors.append("ELASTIC_ENABLED=true requires ELASTIC_URL.")

    if _running_in_docker(settings.raw):
        host = urlparse(settings.phoenix.api_base_url).hostname or ""
        if settings.phoenix.mode == "local" and host in {"localhost", "127.0.0.1"}:
            errors.append(
                "Inside Docker, local PHOENIX_BASE_URL must use http://phoenix:6006, not localhost."
            )
        ehost = urlparse(settings.elastic.url).hostname or ""
        if settings.elastic.mode == "local" and settings.elastic.enabled and ehost in {"localhost", "127.0.0.1"}:
            errors.append(
                "Inside Docker, local ELASTIC_URL must use http://elastic:9200, not localhost."
            )

    if settings.mcp.enabled and not shutil.which("npx"):
        warnings.append("MCP_ENABLED=true but npx was not found on PATH.")
    if not usable_secret(settings.gemini_api_key):
        warnings.append("GEMINI_API_KEY is missing or placeholder; Governance Copilot chat will fail.")

    return errors, warnings


def flat_config(snapshot: ResolvedSettings | None = None) -> dict[str, Any]:
    """Flatten resolved settings for config.py compatibility."""
    s = snapshot or get_snapshot()
    return {
        "GEMINI_API_KEY": s.gemini_api_key,
        "GEMINI_BASE_URL": s.gemini_base_url,
        "GEMINI_ANALYST_MODEL": s.analyst_model,
        "GEMINI_DRAFTER_MODEL": s.drafter_model,
        "ANALYST_MODEL": s.analyst_model,
        "DRAFTER_MODEL": s.drafter_model,
        "PHOENIX_MODE": s.phoenix.mode,
        "ELASTIC_MODE": s.elastic.mode,
        "PHOENIX_BASE_URL": s.phoenix.api_base_url,
        "PHOENIX_COLLECTOR_ENDPOINT": s.phoenix.collector_endpoint,
        "PHOENIX_CONSOLE_URL": s.phoenix.console_url,
        "PHOENIX_API_KEY": s.phoenix.api_key or "",
        "PHOENIX_PROJECT_NAME": s.phoenix.project_name,
        "PHOENIX_PORT": s.phoenix.port,
        "ELASTIC_ENABLED": s.elastic.enabled,
        "ELASTIC_URL": s.elastic.url,
        "ELASTIC_API_KEY": s.elastic.api_key or "",
        "ELASTIC_USERNAME": s.elastic.username or "",
        "ELASTIC_PASSWORD": s.elastic.password or "",
        "ELASTIC_INDEX_PREFIX": s.elastic.index_prefix,
        "MCP_ENABLED": s.mcp.enabled,
        "MCP_PHOENIX_ENABLED": s.mcp.phoenix_enabled,
        "MCP_ELASTIC_ENABLED": s.mcp.elastic_enabled,
        "MCP_PHOENIX_PACKAGE": s.mcp.phoenix_package,
        "MCP_ELASTIC_PACKAGE": s.mcp.elastic_package,
        "MCP_LOAD_TIMEOUT_SEC": s.mcp.load_timeout_sec,
        "REVIEW_RISK_THRESHOLD": s.review_risk_threshold,
        "VERIFIER_MAX_REVISIONS": s.verifier_max_revisions,
        "NEGOTIATOR_INCLUDE_MEDIUM": s.negotiator_include_medium,
        "LEGAL_SPECIALIST_WEIGHT": s.specialist_weights["legal"],
        "FINANCIAL_SPECIALIST_WEIGHT": s.specialist_weights["financial"],
        "DELIVERY_SPECIALIST_WEIGHT": s.specialist_weights["delivery"],
        "IP_DATA_SPECIALIST_WEIGHT": s.specialist_weights["ip_data"],
        "COMPLIANCE_SPECIALIST_WEIGHT": s.specialist_weights["compliance"],
        "SPECIALIST_WEIGHTS": s.specialist_weights,
    }
