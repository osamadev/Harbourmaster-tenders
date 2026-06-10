"""Central configuration resolved from settings (env + runtime JSON)."""

from __future__ import annotations

from typing import Any

from harbourmaster.settings import get_snapshot, reload as reload_settings


def _apply_snapshot(snapshot: Any | None = None) -> None:
    from harbourmaster.settings import flat_config

    values = flat_config(snapshot)
    g = globals()
    for key, value in values.items():
        g[key] = value


def reload() -> None:
    """Reload configuration from environment and runtime overrides."""
    snapshot = reload_settings()
    _apply_snapshot(snapshot)


_apply_snapshot(get_snapshot())
