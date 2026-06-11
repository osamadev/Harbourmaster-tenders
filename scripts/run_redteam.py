"""Red-team adversarial scorecard runner.

Sends procurement-specific adversarial prompts through the full governed
pipeline and compares the actual verdict against the expected action.

    make redteam
    python scripts/run_redteam.py
"""

import os
from pathlib import Path

import httpx
import yaml

from harbourmaster import config
from harbourmaster.guard import evaluate_content
from harbourmaster.telemetry import init_telemetry

CASES_FILE = Path(__file__).resolve().parents[1] / "configs" / "redteam_cases.yaml"


def load_cases(path: Path | None = None) -> list[dict]:
    """Load adversarial test cases from the YAML file."""
    path = path or CASES_FILE
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("test_cases", [])


def run_case(case: dict) -> dict:
    """Run a single test case and return the result."""
    prompt = case["prompt"]
    expected = case["expected_action"]
    guard = evaluate_content(prompt, context="redteam_prompt")
    actual = guard.verdict

    # Determine pass/fail. For expected DENY, accept DENY or QUARANTINE as a
    # pass (both block the request). For expected QUARANTINE, only QUARANTINE
    # passes. For expected ALLOW, ALLOW or LOG both count as pass.
    if expected == "DENY":
        passed = actual in ("DENY",)
    elif expected == "ALLOW":
        passed = actual in ("ALLOW",)
    else:
        passed = actual == expected

    return {
        "name": case["name"],
        "category": case.get("category", ""),
        "description": case.get("description", ""),
        "expected": expected,
        "actual": actual,
        "passed": passed,
        "ingress_risk": guard.risk_score,
        "blocked": guard.blocked,
        "report": guard.to_inspection(),
    }


def run_all(path: Path | None = None) -> list[dict]:
    """Run all test cases and return results."""
    cases = load_cases(path)
    results = []
    for case in cases:
        result = run_case(case)
        results.append(result)
    return results


def print_scorecard(results: list[dict]) -> None:
    """Print a formatted scorecard to stdout."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    blocked = sum(1 for r in results if r["blocked"])

    print("=" * 80)
    print("  HARBOURMASTER RED-TEAM SCORECARD")
    print("=" * 80)
    print()
    print(f"  {'Name':<35} {'Category':<18} {'Expected':<12} {'Actual':<12} {'Result'}")
    print(f"  {'-'*35} {'-'*18} {'-'*12} {'-'*12} {'-'*6}")

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        marker = "  " if r["passed"] else "!!"
        print(
            f"{marker}{r['name']:<35} {r['category']:<18} "
            f"{r['expected']:<12} {r['actual']:<12} {status}"
        )

    print()
    print(f"  Total: {total}  |  Passed: {passed}  |  Failed: {total - passed}  |  Blocked: {blocked}")
    print(f"  Score: {passed}/{total} ({100 * passed / total:.0f}%)" if total else "  No tests run.")
    print("=" * 80)


def sync_with_phoenix(results: list[dict]) -> str:
    """Best-effort metadata push to Phoenix (dataset + experiment marker)."""
    base = config.PHOENIX_BASE_URL.rstrip("/")
    api_key = config.PHOENIX_API_KEY
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "dataset_name": os.getenv("PHOENIX_REDTEAM_DATASET", "red-team-dataset"),
        "experiment_name": os.getenv("PHOENIX_REDTEAM_EXPERIMENT", "redteam-latest"),
        "rows": results,
    }
    endpoints = [f"{base}/v1/experiments", f"{base}/api/v1/experiments"]
    for endpoint in endpoints:
        try:
            response = httpx.post(endpoint, headers=headers, json=payload, timeout=10)
            if response.status_code in (200, 201, 202):
                from harbourmaster.phoenix_audit import phoenix_console_url

                return phoenix_console_url()
        except Exception:  # noqa: BLE001
            continue
    from harbourmaster.phoenix_audit import phoenix_console_url

    return phoenix_console_url()


def main() -> None:
    init_telemetry()
    results = run_all()
    print_scorecard(results)
    print(f"Phoenix: {sync_with_phoenix(results)}")


if __name__ == "__main__":
    main()
