"""Advanced Phoenix-telemetry analytics tools for Governance Copilot.

Each tool returns a JSON string. Analytical tools embed a ``chart`` spec
(``{"type","title","x","y",...}``) that the Streamlit UI renders with Plotly.
All read the enriched, copilot-excluded span frame from ``phoenix_audit.load_dataframe``.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from langchain_core.tools import tool

from harbourmaster import config
from harbourmaster.phoenix_audit import load_dataframe, phoenix_console_url

_DENY = {"DENY", "QUARANTINE"}


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _frame() -> pd.DataFrame:
    return load_dataframe()


def _empty(message: str) -> str:
    return json.dumps(
        {"status": "empty", "message": message, "console_url": phoenix_console_url()}, indent=2
    )


def _bar(title: str, x: list, y: list, y_label: str = "value") -> dict[str, Any]:
    return {"type": "bar", "title": title, "x": list(x), "y": list(y), "y_label": y_label}


def _line(title: str, x: list, y: list, y_label: str = "value") -> dict[str, Any]:
    return {"type": "line", "title": title, "x": [str(v) for v in x], "y": list(y), "y_label": y_label}


def _slim(df: pd.DataFrame, cols: list[str], limit: int) -> list[dict[str, Any]]:
    keep = [c for c in cols if c in df.columns]
    out = df[keep].head(limit).copy()
    if "timestamp" in out.columns:
        out["timestamp"] = out["timestamp"].astype(str)
    return out.to_dict(orient="records")


@tool
def query_telemetry(
    action: str = "",
    agent: str = "",
    component: str = "",
    min_risk: float = 0.0,
    since_hours: int = 0,
    limit: int = 20,
) -> str:
    """Filter governance telemetry spans and return matching rows plus summary counts.

    action: ALLOW/DENY/QUARANTINE/LOG (optional). agent: substring of agent id.
    component: guard/specialist/workflow/other. min_risk: minimum risk score.
    since_hours: only spans within the last N hours (0 = all). limit: max rows returned.
    """
    df = _frame()
    if df.empty:
        return _empty("No Phoenix telemetry found. Run a contract review first.")
    if action:
        df = df[df["action"].astype(str).str.upper() == action.strip().upper()]
    if agent:
        df = df[df["agent_id"].astype(str).str.contains(agent.strip(), case=False, na=False)]
    if component:
        df = df[df["component"].astype(str) == component.strip().lower()]
    if min_risk > 0:
        df = df[df["risk_score"].fillna(0) >= float(min_risk)]
    if since_hours > 0 and "timestamp" in df.columns:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=since_hours)
        df = df[df["timestamp"] >= cutoff]

    risk_rows = df[df["has_explicit_risk"] == True]  # noqa: E712
    summary = {
        "matched": int(len(df)),
        "denied": int(df["action"].astype(str).str.upper().isin(_DENY).sum()),
        "avg_risk": round(float(risk_rows["risk_score"].mean()), 3) if len(risk_rows) else 0.0,
        "total_tokens": int(df.get("total_tokens", pd.Series(dtype=int)).fillna(0).sum()),
        "est_cost_usd": round(float(df.get("cost_usd", pd.Series(dtype=float)).fillna(0).sum()), 4),
    }
    rows = _slim(
        df.sort_values("timestamp", ascending=False) if "timestamp" in df else df,
        ["timestamp", "component", "agent_id", "action", "risk_score", "model", "total_tokens", "rule_name"],
        max(1, min(limit, 50)),
    )
    return json.dumps({"summary": summary, "rows": rows}, indent=2, default=str)


@tool
def aggregate_telemetry(group_by: str = "agent", metric: str = "count") -> str:
    """Group telemetry and compute a metric, returning a table and a bar chart.

    group_by: agent | action | component | model | category | day.
    metric: count | avg_risk | denial_rate | sum_tokens | avg_latency | sum_cost.
    """
    df = _frame()
    if df.empty:
        return _empty("No Phoenix telemetry found. Run a contract review first.")

    m = metric.strip().lower()
    # Verdict/risk metrics are only meaningful on inspection spans (real guard/specialist
    # verdicts); token/cost/latency only on model-call spans. Filter before grouping so
    # HTTP-status LLM spans don't dilute the numbers.
    if m in {"denial_rate", "avg_risk"}:
        df = df[df["span_type"] == "inspection"]
    elif m in {"sum_tokens", "sum_cost", "avg_latency"}:
        df = df[df["span_type"] == "llm"]
    if df.empty:
        return _empty(f"No spans available for metric '{metric}'.")

    gb = group_by.strip().lower()
    if gb == "agent":
        df = df.assign(_g=df["agent_id"].astype(str))
    elif gb == "action":
        df = df.assign(_g=df["action"].astype(str).str.upper())
    elif gb == "component":
        df = df.assign(_g=df["component"].astype(str))
    elif gb == "model":
        df = df.assign(_g=df["model"].astype(str).replace("", "(none)"))
    elif gb == "day":
        df = df.assign(_g=df["timestamp"].dt.date.astype(str))
    elif gb == "category":
        exploded = (
            df.assign(_g=df["intent_category"].fillna("").str.split(","))
            .explode("_g")
        )
        exploded["_g"] = exploded["_g"].astype(str).str.strip()
        df = exploded[exploded["_g"] != ""]
    else:
        return json.dumps({"error": f"Unknown group_by: {group_by}"})

    if df.empty:
        return _empty(f"No rows to aggregate for group_by={group_by}.")

    grp = df.groupby("_g")
    if m == "count":
        series = grp.size()
    elif m == "avg_risk":
        series = grp["risk_score"].mean().round(3)
    elif m == "denial_rate":
        series = grp["action"].apply(lambda s: round(s.astype(str).str.upper().isin(_DENY).mean(), 3))
    elif m == "sum_tokens":
        series = grp["total_tokens"].sum()
    elif m == "avg_latency":
        series = grp["latency_ms"].mean().round(1)
    elif m == "sum_cost":
        series = grp["cost_usd"].sum().round(4)
    else:
        return json.dumps({"error": f"Unknown metric: {metric}"})

    series = series.sort_values(ascending=False)
    table = [{"group": str(k), metric: (float(v) if pd.notna(v) else 0)} for k, v in series.items()]
    chart = _bar(f"{metric} by {group_by}", [r["group"] for r in table], [r[metric] for r in table], metric)
    return json.dumps({"group_by": group_by, "metric": metric, "table": table, "chart": chart}, indent=2)


@tool
def telemetry_timeseries(metric: str = "volume", bucket: str = "hour") -> str:
    """Trend a telemetry metric over time, returning a series and a line chart.

    metric: volume | avg_risk | denials | tokens | cost. bucket: hour | day.
    """
    df = _frame()
    if df.empty:
        return _empty("No Phoenix telemetry found. Run a contract review first.")
    if "timestamp" not in df or df["timestamp"].isna().all():
        return _empty("Telemetry has no usable timestamps.")

    m = metric.strip().lower()
    if m == "avg_risk":  # only verdict spans carry meaningful risk
        df = df[df["span_type"] == "inspection"]
    if df.empty:
        return _empty(f"No spans available for metric '{metric}'.")

    df = df.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
    rule = "1D" if bucket.strip().lower() == "day" else "1h"
    res = df.resample(rule)
    if m == "volume":
        series = res.size()
    elif m == "avg_risk":
        series = res["risk_score"].mean().round(3)
    elif m == "denials":
        series = res["action"].apply(lambda s: int(s.astype(str).str.upper().isin(_DENY).sum()))
    elif m == "tokens":
        series = res["total_tokens"].sum()
    elif m == "cost":
        series = res["cost_usd"].sum().round(4)
    else:
        return json.dumps({"error": f"Unknown metric: {metric}"})

    series = series.fillna(0)
    x = [t.isoformat() for t in series.index]
    y = [float(v) for v in series.values]
    chart = _line(f"{metric} over time ({bucket})", x, y, metric)
    return json.dumps({"metric": metric, "bucket": bucket, "points": len(y), "chart": chart}, indent=2)


@tool
def token_cost_usage(group_by: str = "model") -> str:
    """Break down token usage and estimated cost. group_by: model | agent | component."""
    df = _frame()
    if df.empty:
        return _empty("No Phoenix telemetry found. Run a contract review first.")
    df = df[(df["total_tokens"].fillna(0) > 0) | (df["cost_usd"].fillna(0) > 0)]
    if df.empty:
        return _empty("No token-bearing spans found yet.")

    col = {"model": "model", "agent": "agent_id", "component": "component"}.get(group_by.strip().lower(), "model")
    df = df.assign(_g=df[col].astype(str).replace("", "(none)"))
    agg = df.groupby("_g").agg(
        prompt_tokens=("prompt_tokens", "sum"),
        completion_tokens=("completion_tokens", "sum"),
        total_tokens=("total_tokens", "sum"),
        est_cost_usd=("cost_usd", "sum"),
    ).sort_values("est_cost_usd", ascending=False)

    table = [
        {
            "group": str(k),
            "prompt_tokens": int(r.prompt_tokens),
            "completion_tokens": int(r.completion_tokens),
            "total_tokens": int(r.total_tokens),
            "est_cost_usd": round(float(r.est_cost_usd), 4),
        }
        for k, r in agg.iterrows()
    ]
    chart = _bar(f"Estimated cost by {group_by}", [r["group"] for r in table], [r["est_cost_usd"] for r in table], "usd")
    totals = {
        "total_tokens": int(agg["total_tokens"].sum()),
        "est_cost_usd": round(float(agg["est_cost_usd"].sum()), 4),
    }
    return json.dumps({"group_by": group_by, "totals": totals, "table": table, "chart": chart}, indent=2)


@tool
def risk_outliers(limit: int = 10) -> str:
    """Return the highest-risk and denied spans with agent, action, reason, and risk."""
    df = _frame()
    if df.empty:
        return _empty("No Phoenix telemetry found. Run a contract review first.")
    denied = df[df["action"].astype(str).str.upper().isin(_DENY)]
    risky = df.sort_values("risk_score", ascending=False)
    combined = pd.concat([denied, risky]).drop_duplicates(subset=["request_id"]).head(max(1, min(limit, 25)))
    rows = _slim(
        combined,
        ["timestamp", "component", "agent_id", "action", "risk_score", "intent_category", "rule_name"],
        max(1, min(limit, 25)),
    )
    return json.dumps({"count": len(rows), "outliers": rows}, indent=2, default=str)


@tool
def review_telemetry(review_id: str) -> str:
    """Return the telemetry spans for one saved review (by its review/thread id).

    Groups guard, specialist, and model spans for that review with verdicts, risk,
    and latency. Requires the review to have been run with session tagging enabled.
    """
    rid = (review_id or "").strip()
    if not rid:
        return json.dumps({"error": "review_id is required."})
    df = _frame()
    if df.empty:
        return _empty("No Phoenix telemetry found. Run a contract review first.")
    sub = df[df["session_id"].astype(str).str.contains(rid, case=False, na=False)]
    if sub.empty:
        return json.dumps(
            {
                "status": "empty",
                "message": f"No spans linked to review '{rid}'. Only reviews run after session "
                "tagging was enabled are linkable.",
            }
        )
    summary = {
        "spans": int(len(sub)),
        "denied": int(sub["action"].astype(str).str.upper().isin(_DENY).sum()),
        "max_risk": round(float(sub["risk_score"].fillna(0).max() or 0.0), 3),
        "total_tokens": int(sub["total_tokens"].fillna(0).sum()),
        "est_cost_usd": round(float(sub["cost_usd"].fillna(0).sum()), 4),
    }
    rows = _slim(
        sub.sort_values("timestamp"),
        ["timestamp", "component", "agent_id", "action", "risk_score", "latency_ms", "total_tokens"],
        50,
    )
    return json.dumps({"review_id": rid, "summary": summary, "spans": rows}, indent=2, default=str)


def _summarize_redteam(dataset_name: str, examples: list, experiments: list) -> str:
    """Build the red-team summary JSON from dataset examples (MCP or client shape)."""
    cases, failures = [], []
    for ex in examples or []:
        meta = _get(ex, "metadata", {}) or {}
        out = _get(ex, "output", {}) or {}
        inp = _get(ex, "input", {}) or {}
        row = {
            "name": inp.get("name", ""),
            "category": meta.get("category", ""),
            "expected": out.get("expected_action", ""),
            "actual": meta.get("actual", ""),
            "passed": bool(meta.get("passed")),
            "ingress_risk": meta.get("ingress_risk"),
        }
        cases.append(row)
        if not row["passed"]:
            failures.append(row)
    total = len(cases)
    passed = sum(1 for c in cases if c["passed"])
    return json.dumps(
        {
            "dataset": dataset_name,
            "experiment_count": len(experiments or []),
            "latest_experiment_id": _get((experiments or [None])[0], "id") if experiments else None,
            "total_cases": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 3) if total else 0.0,
            "key_failures": failures,
            "console_url": phoenix_console_url(),
        },
        indent=2,
        default=str,
    )


def _redteam_via_mcp() -> str | None:
    """Read the red-team dataset/experiments via the Phoenix MCP server (None on failure)."""
    from harbourmaster.mcp_client import (
        mcp_dataset_examples,
        mcp_list_datasets,
        mcp_list_experiments,
    )

    datasets = mcp_list_datasets()
    if not datasets:
        return None
    target = next(
        (d for d in datasets if "redteam" in str(_get(d, "name", "")).lower().replace("-", "")),
        None,
    )
    if target is None:
        return None
    dataset_id = _get(target, "id")
    examples = mcp_dataset_examples(dataset_id)
    if examples is None:
        return None
    experiments = mcp_list_experiments(dataset_id) or []
    return _summarize_redteam(_get(target, "name", "red-team-dataset"), examples, experiments)


def _redteam_via_client() -> str:
    """Native fallback: read the red-team dataset/experiments via the Phoenix client."""
    try:
        from phoenix.client import Client
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Phoenix client unavailable: {exc}"})

    headers: dict[str, str] = {}
    if config.PHOENIX_API_KEY:
        headers["Authorization"] = f"Bearer {config.PHOENIX_API_KEY}"
    try:
        client = Client(base_url=config.PHOENIX_BASE_URL.rstrip("/"), headers=headers or None)
        datasets = client.datasets.list()
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Could not reach Phoenix: {exc}"})

    target = next(
        (d for d in datasets if "redteam" in str(_get(d, "name", "")).lower().replace("-", "")),
        None,
    )
    if target is None:
        return json.dumps(
            {
                "status": "empty",
                "message": "No red-team dataset in Phoenix yet. Run `make redteam` or the "
                "Red-Team Scorecard page to create one.",
                "console_url": phoenix_console_url(),
            }
        )
    dataset_id = _get(target, "id")
    dataset_name = _get(target, "name", "red-team-dataset")
    full = client.datasets.get_dataset(dataset=dataset_id)
    examples = list(_get(full, "examples", []) or [])
    try:
        experiments = client.experiments.list(dataset_id=dataset_id)
    except Exception:  # noqa: BLE001
        experiments = []
    return _summarize_redteam(dataset_name, examples, experiments)


@tool
def latest_redteam_experiment() -> str:
    """Return the latest red-team experiment summary and key failures from Phoenix.

    Reads the red-team dataset + experiments via the Phoenix MCP server (native client as
    fallback). Use this for any question about red-team experiments, the adversarial
    scorecard, or which attack cases the guard failed — NOT Elastic procurement memory.
    """
    try:
        result = _redteam_via_mcp()
        if result is not None:
            return result
    except Exception:  # noqa: BLE001
        pass
    return _redteam_via_client()


def telemetry_tools() -> list:
    """Return all advanced telemetry analytics tools."""
    return [
        query_telemetry,
        aggregate_telemetry,
        telemetry_timeseries,
        token_cost_usage,
        risk_outliers,
        review_telemetry,
        latest_redteam_experiment,
    ]
