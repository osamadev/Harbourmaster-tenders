"""Red-team adversarial scorecard runner.

Sends procurement-specific adversarial prompts through the full governed
pipeline and compares the actual verdict against the expected action.

    make redteam
    python scripts/run_redteam.py
"""

import os
from pathlib import Path

import yaml

from harbourmaster import config
from harbourmaster.guard import evaluate_content
from harbourmaster.telemetry import agent_span, init_telemetry

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
    # Per-case ambient span so the guard's LLM + inspection spans nest under it
    # (and under the suite root) instead of landing as flat roots in Phoenix.
    span_id = None
    with agent_span(
        f"redteam:{case['name']}",
        kind="GUARDRAIL",
        attributes={
            "redteam.category": case.get("category", ""),
            "redteam.expected": expected,
        },
    ) as span:
        from harbourmaster.phoenix_annotations import span_id_hex

        span_id = span_id_hex(span)
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
        "prompt": prompt,
        "expected": expected,
        "actual": actual,
        "passed": passed,
        "ingress_risk": guard.risk_score,
        "blocked": guard.blocked,
        "report": guard.to_inspection(),
        "span_id": span_id,
    }


def run_all(path: Path | None = None) -> list[dict]:
    """Run all test cases and return results."""
    cases = load_cases(path)
    results = []
    # Suite root span: each redteam:<case> span (and its guard spans) nests under
    # this, giving Phoenix one red-team trace tree per suite run.
    with agent_span(
        "harbourmaster.redteam_suite",
        kind="CHAIN",
        attributes={"redteam.case_count": len(cases)},
    ):
        for case in cases:
            results.append(run_case(case))
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
    """Create a Phoenix dataset + experiment from the red-team results.

    Uses the real Phoenix client API so the cases show up under datasets/experiments
    (queryable via the Governance Copilot's Phoenix MCP tools). Best-effort: any failure
    just returns the console URL without raising.
    """
    from harbourmaster.phoenix_audit import phoenix_console_url

    if not results:
        return phoenix_console_url()

    try:
        from phoenix.client import Client
    except Exception as exc:  # noqa: BLE001
        print(f"Phoenix sync skipped (client unavailable): {exc}")
        return phoenix_console_url()

    base = config.PHOENIX_BASE_URL.rstrip("/")
    headers: dict[str, str] = {}
    if config.PHOENIX_API_KEY:
        headers["Authorization"] = f"Bearer {config.PHOENIX_API_KEY}"
    ds_name = os.getenv("PHOENIX_REDTEAM_DATASET", "red-team-dataset")
    exp_name = os.getenv("PHOENIX_REDTEAM_EXPERIMENT", "redteam-latest")

    try:
        client = Client(base_url=base, headers=headers or None)
        inputs = [{"prompt": r.get("prompt", ""), "name": r.get("name", "")} for r in results]
        outputs = [{"expected_action": r.get("expected", "")} for r in results]
        metadata = [
            {
                "category": r.get("category", ""),
                "actual": r.get("actual", ""),
                "passed": bool(r.get("passed")),
                "blocked": bool(r.get("blocked")),
                "ingress_risk": float(r.get("ingress_risk", 0.0) or 0.0),
            }
            for r in results
        ]
        try:
            dataset = client.datasets.create_dataset(
                name=ds_name,
                inputs=inputs,
                outputs=outputs,
                metadata=metadata,
                dataset_description="Harbourmaster red-team adversarial cases",
            )
        except Exception:  # noqa: BLE001 — dataset likely exists; reuse it
            dataset = client.datasets.get_dataset(dataset=ds_name)

        by_prompt = {r.get("prompt", ""): r for r in results}

        def task(example: object) -> dict:
            inp = example.get("input", {}) if isinstance(example, dict) else getattr(example, "input", {})
            r = by_prompt.get((inp or {}).get("prompt", ""), {})
            return {"actual": r.get("actual", ""), "passed": bool(r.get("passed"))}

        def guard_blocked_attack(output: dict) -> float:
            """1.0 when the guard's verdict matched the expected action."""
            return 1.0 if (output or {}).get("passed") else 0.0

        try:
            client.experiments.run_experiment(
                dataset=dataset,
                task=task,
                evaluators={"guard_correct": guard_blocked_attack},
                experiment_name=exp_name,
                print_summary=False,
            )
        except Exception as exc:  # noqa: BLE001 — fall back to a metadata-only experiment
            failures = [
                {"name": r.get("name"), "expected": r.get("expected"), "actual": r.get("actual")}
                for r in results
                if not r.get("passed")
            ]
            client.experiments.create(
                dataset_id=getattr(dataset, "id", None) or dataset["id"],
                experiment_name=exp_name,
                experiment_metadata={
                    "total": len(results),
                    "passed": sum(1 for r in results if r.get("passed")),
                    "failures": failures,
                    "note": f"metadata-only (run_experiment failed: {exc})",
                },
            )
        print(f"Phoenix: dataset '{ds_name}' + experiment '{exp_name}' synced.")
    except Exception as exc:  # noqa: BLE001
        print(f"Phoenix sync failed: {exc}")

    return phoenix_console_url()


def main() -> None:
    init_telemetry()
    results = run_all()
    print_scorecard(results)
    # Attach a guard_correct pass/fail annotation to each case span (best-effort).
    try:
        from harbourmaster.phoenix_annotations import annotate_redteam

        annotate_redteam(
            [
                {
                    "span_id": r.get("span_id"),
                    "name": r.get("name", ""),
                    "passed": r.get("passed"),
                    "expected": r.get("expected", ""),
                    "actual": r.get("actual", ""),
                }
                for r in results
            ]
        )
    except Exception:  # noqa: BLE001
        pass
    print(f"Phoenix: {sync_with_phoenix(results)}")


if __name__ == "__main__":
    main()
