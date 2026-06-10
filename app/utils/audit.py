"""Shared utility for loading governance telemetry from Arize Phoenix."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from harbourmaster.phoenix_audit import load_dataframe as _load_dataframe
from harbourmaster.phoenix_audit import load_entries

__all__ = ["load_entries", "load_dataframe"]


def load_dataframe(path: Path | None = None) -> pd.DataFrame:
    """Load governance telemetry into a DataFrame used by dashboard charts."""
    _ = path  # retained for backward compatibility
    return _load_dataframe()
