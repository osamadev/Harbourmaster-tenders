"""Red-Team Scorecard — adversarial testing of the governance pipeline.

Runs procurement-specific adversarial prompts through the full governed
pipeline and reports pass/fail results.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from scripts.run_redteam import load_cases, run_case  # noqa: E402
from harbourmaster import config  # noqa: E402

st.set_page_config(page_title="Red-Team Scorecard", page_icon="🛡", layout="wide")
st.title("Red-Team Scorecard")
st.caption("Adversarial testing with guard verdicts and Phoenix experiment logging")

# ---------------------------------------------------------------------------
# Test case overview
# ---------------------------------------------------------------------------
cases = load_cases()
st.markdown(f"**{len(cases)} test cases** loaded from `configs/redteam_cases.yaml`")

with st.expander("View test cases"):
    for case in cases:
        st.markdown(
            f"- **{case['name']}** ({case.get('category', 'N/A')}) — "
            f"expected: `{case['expected_action']}` — {case.get('description', '')}"
        )

st.divider()

# ---------------------------------------------------------------------------
# Run scorecard
# ---------------------------------------------------------------------------
if "redteam_results" not in st.session_state:
    st.session_state.redteam_results = None

if st.button("Run Scorecard", type="primary"):
    results = []
    progress = st.progress(0, text="Running adversarial tests...")

    for i, case in enumerate(cases):
        progress.progress(
            (i + 1) / len(cases),
            text=f"Testing: {case['name']} ({i + 1}/{len(cases)})",
        )
        result = run_case(case)
        results.append(result)

    progress.empty()
    st.session_state.redteam_results = results
    st.rerun()

# ---------------------------------------------------------------------------
# Display results
# ---------------------------------------------------------------------------
results = st.session_state.redteam_results

if results is None:
    st.info("Click **Run Scorecard** to execute the adversarial test suite.")
    st.stop()

# Summary metrics
total = len(results)
passed = sum(1 for r in results if r["passed"])
failed = total - passed
blocked = sum(1 for r in results if r["blocked"])

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Tests", total)
c2.metric("Passed", passed)
c3.metric("Failed", failed)
c4.metric("Blocked", blocked)

score_pct = (100 * passed / total) if total else 0
if score_pct == 100:
    st.success(f"Score: {passed}/{total} ({score_pct:.0f}%) — All tests passed!")
elif score_pct >= 80:
    st.warning(f"Score: {passed}/{total} ({score_pct:.0f}%) — Some tests failed.")
else:
    st.error(f"Score: {passed}/{total} ({score_pct:.0f}%) — Multiple test failures.")

st.divider()

# Results table
st.markdown("### Results")

rows = []
for r in results:
    rows.append({
        "Status": "PASS" if r["passed"] else "FAIL",
        "Name": r["name"],
        "Category": r["category"],
        "Expected": r["expected"],
        "Actual": r["actual"],
        "Ingress Risk": f"{r['ingress_risk']:.2f}",
        "Blocked": "Yes" if r["blocked"] else "No",
    })

results_df = pd.DataFrame(rows)
st.dataframe(
    results_df.style.apply(
        lambda row: [
            "background-color: #d4edda" if row["Status"] == "PASS" else "background-color: #f8d7da"
        ] * len(row),
        axis=1,
    ),
    use_container_width=True,
    height=min(400, 40 + 35 * len(rows)),
)

# Per-category breakdown
st.markdown("### By Category")
categories = {}
for r in results:
    cat = r["category"]
    if cat not in categories:
        categories[cat] = {"total": 0, "passed": 0}
    categories[cat]["total"] += 1
    if r["passed"]:
        categories[cat]["passed"] += 1

cat_rows = []
for cat, stats in sorted(categories.items()):
    cat_rows.append({
        "Category": cat,
        "Tests": stats["total"],
        "Passed": stats["passed"],
        "Failed": stats["total"] - stats["passed"],
        "Rate": f"{100 * stats['passed'] / stats['total']:.0f}%",
    })
st.dataframe(pd.DataFrame(cat_rows), use_container_width=True)

# Detailed inspection reports
st.markdown("### Detailed Reports")
for r in results:
    icon = "✅" if r["passed"] else "❌"
    with st.expander(f"{icon} {r['name']} — {r['actual']} (expected {r['expected']})"):
        st.markdown(f"**Category:** {r['category']}")
        st.markdown(f"**Description:** {r['description']}")
        st.markdown(f"**Ingress Risk:** {r['ingress_risk']:.3f}")
        st.json(r["report"])

with st.sidebar:
    st.markdown("### Red-Team Scorecard")
    st.metric("Cases Loaded", len(cases))
    from app.utils.nav import render_sidebar_nav

    render_sidebar_nav()
