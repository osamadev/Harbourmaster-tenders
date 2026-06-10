#!/usr/bin/env python3
"""Print resolved Harbourmaster settings and validation results."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harbourmaster.runtime_config import to_public_view
from harbourmaster.settings import KNOWN_KEYS, SECRET_KEYS, get_snapshot, validate


def main() -> int:
    snapshot = get_snapshot()
    errors, warnings = validate(snapshot)
    payload = {
        "phoenix_mode": snapshot.phoenix.mode,
        "elastic_mode": snapshot.elastic.mode,
        "phoenix_api_base_url": snapshot.phoenix.api_base_url,
        "phoenix_console_url": snapshot.phoenix.console_url,
        "elastic_url": snapshot.elastic.url,
        "mcp": {
            "enabled": snapshot.mcp.enabled,
            "phoenix_enabled": snapshot.mcp.phoenix_enabled,
            "elastic_enabled": snapshot.mcp.elastic_enabled,
            "phoenix_package": snapshot.mcp.phoenix_package,
            "elastic_package": snapshot.mcp.elastic_package,
        },
        "sources": {k: v for k, v in snapshot.sources.items() if k in KNOWN_KEYS | SECRET_KEYS},
        "secrets": to_public_view(
            {k: snapshot.raw[k] for k in snapshot.raw if k in KNOWN_KEYS | SECRET_KEYS}
        ),
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(payload, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
