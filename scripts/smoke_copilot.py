#!/usr/bin/env python3
"""Smoke test for Governance Copilot health and native tool path."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harbourmaster.copilot import chat, reset_agent
from harbourmaster.copilot.health import run_health_checks
from harbourmaster.copilot.tools_native import summarize_guard_telemetry
from harbourmaster.settings import validate


def main() -> int:
    print("== Governance Copilot smoke ==")

    errors, warnings = validate()
    if errors:
        print("[WARN] config validation errors:")
        for item in errors:
            print(f"  - {item}")
    for item in warnings:
        print(f"[WARN] {item}")

    health = run_health_checks()
    for name in ("phoenix", "elastic", "node", "gemini"):
        check = health[name]
        status = "OK" if check.get("ok") else "WARN"
        print(f"[{status}] {name}: {check.get('detail', '')}")

    print(f"[INFO] console_url: {health.get('console_url', '')}")

    native_raw = summarize_guard_telemetry.invoke({})
    native = json.loads(native_raw)
    print(f"[OK] native summarize_guard_telemetry: total_spans={native.get('total_spans', 0)}")

    if not health["gemini"].get("ok"):
        print("[SKIP] Gemini key missing — skipping chat()")
        return 0

    async def _ask() -> None:
        result = await chat(
            "Summarize guard denial categories from recent Phoenix traces.",
            history=[],
        )
        preview = (result.answer or "").strip().replace("\n", " ")[:200]
        print(f"[OK] chat() answer preview: {preview or '(empty)'}")
        print(f"[OK] tool_trace steps: {len(result.tool_trace)}")

    try:
        asyncio.run(_ask())
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] chat() raised: {exc}")
        return 1
    finally:
        asyncio.run(reset_agent())

    print("Smoke copilot passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
