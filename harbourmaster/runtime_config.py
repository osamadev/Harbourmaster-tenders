"""Load and persist UI-managed runtime configuration overrides."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

RUNTIME_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "runtime_settings" / "runtime_config.json"
)

SECRET_KEYS = frozenset(
    {
        "GEMINI_API_KEY",
        "PHOENIX_API_KEY",
        "ELASTIC_API_KEY",
        "ELASTIC_PASSWORD",
    }
)

MASK = "••••••"


def load_runtime_config() -> dict[str, Any]:
    """Return persisted runtime overrides or an empty dict."""
    if not RUNTIME_CONFIG_PATH.exists():
        return {}
    try:
        with open(RUNTIME_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_runtime_config(updates: dict[str, Any]) -> None:
    """Merge updates into runtime config and atomically persist."""
    current = load_runtime_config()
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip() and key in SECRET_KEYS:
            continue
        current[key] = value
    RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=RUNTIME_CONFIG_PATH.parent, encoding="utf-8") as tmp:
        json.dump(current, tmp, indent=2, ensure_ascii=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(RUNTIME_CONFIG_PATH)


def clear_runtime_config() -> None:
    """Remove persisted runtime overrides."""
    if RUNTIME_CONFIG_PATH.exists():
        RUNTIME_CONFIG_PATH.unlink()


def secret_is_set(value: Any) -> bool:
    return bool(str(value or "").strip())


def to_public_view(config: dict[str, Any]) -> dict[str, Any]:
    """Mask secret values for UI display."""
    public: dict[str, Any] = {}
    for key, value in config.items():
        if key in SECRET_KEYS:
            public[key] = MASK if secret_is_set(value) else ""
        else:
            public[key] = value
    return public


def export_env_snippet(values: dict[str, Any]) -> str:
    """Render a copy-paste .env snippet from resolved values."""
    lines: list[str] = []
    for key in sorted(values):
        if key.startswith("_"):
            continue
        raw = values.get(key)
        if raw is None:
            continue
        if key in SECRET_KEYS and secret_is_set(raw):
            lines.append(f"{key}=<set-in-your-env-file>")
            continue
        if isinstance(raw, bool):
            lines.append(f"{key}={'true' if raw else 'false'}")
        else:
            lines.append(f"{key}={raw}")
    return "\n".join(lines) + ("\n" if lines else "")


def apply_runtime_to_environ(runtime: dict[str, Any]) -> None:
    """Apply runtime overrides to os.environ when env does not already define them."""
    for key, value in runtime.items():
        if os.environ.get(key):
            continue
        if value is None:
            continue
        if isinstance(value, bool):
            os.environ[key] = "true" if value else "false"
        else:
            os.environ[key] = str(value)
