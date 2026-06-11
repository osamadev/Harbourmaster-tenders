"""Shared Streamlit layout, theme CSS, and sidebar shell."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from app.utils.nav import render_grouped_nav
from harbourmaster.copilot.health import check_elastic, check_gemini, check_phoenix
from harbourmaster.settings import get_snapshot

PHASE_LABELS = {
    "idle": "Submit",
    "processing": "Processing",
    "awaiting_review": "Human Review",
    "complete": "Complete",
}


def inject_theme_css() -> None:
    # Re-injected on every script run: Streamlit rebuilds the DOM each rerun, so a
    # one-shot guard would drop the styles after the first interaction.
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        /* ---- Design tokens (light corporate SaaS) ---- */
        :root {
            --hm-bg: #F6F8FB;
            --hm-surface: #FFFFFF;
            --hm-border: #E2E8F0;
            --hm-text: #0F2742;
            --hm-muted: #64748B;
            --hm-teal: #0EA5A4;
            --hm-teal-soft: #F0FDFA;
            --hm-ok: #15803D; --hm-ok-bg: #DCFCE7; --hm-ok-bd: #BBF7D0;
            --hm-warn: #B45309; --hm-warn-bg: #FEF3C7; --hm-warn-bd: #FDE68A;
            --hm-err: #B91C1C; --hm-err-bg: #FEE2E2; --hm-err-bd: #FECACA;
            --hm-shadow: 0 1px 2px rgba(15,39,66,.06), 0 6px 16px rgba(15,39,66,.05);
            --hm-shadow-hover: 0 8px 22px rgba(15,39,66,.12);
        }

        html, body, [class*="css"], .stApp, [data-testid="stAppViewContainer"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }
        .stApp { background: var(--hm-bg); }
        h1, h2, h3, h4 { color: var(--hm-text); letter-spacing: -0.01em; font-weight: 700; }
        a { color: var(--hm-teal); }
        hr { border-color: var(--hm-border); }

        /* ---- Hero header band ---- */
        .hm-hero {
            background: linear-gradient(135deg, #FFFFFF 0%, var(--hm-teal-soft) 100%);
            border: 1px solid var(--hm-border);
            border-left: 5px solid var(--hm-teal);
            border-radius: 14px;
            padding: 1.05rem 1.4rem;
            margin: 0.2rem 0 1.2rem 0;
            box-shadow: var(--hm-shadow);
        }
        .hm-hero-title { font-size: 1.65rem; font-weight: 800; color: var(--hm-text); line-height: 1.2; }
        .hm-hero-sub { color: var(--hm-muted); font-size: 0.92rem; margin-top: 0.25rem; }
        .hm-header { margin-bottom: 0.25rem; }
        .hm-tagline { color: var(--hm-muted); font-size: 0.82rem; margin-bottom: 0.4rem; }

        /* ---- Chips / badges ---- */
        .hm-chip-row { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.35rem 0 0.4rem 0; }
        .hm-chip {
            display: inline-flex; align-items: center; gap: 0.4rem;
            padding: 0.2rem 0.6rem; border-radius: 999px;
            font-size: 0.74rem; font-weight: 600; line-height: 1.2;
            border: 1px solid transparent;
        }
        .hm-chip::before {
            content: ""; width: 7px; height: 7px; border-radius: 50%;
            background: currentColor; opacity: 0.85;
        }
        .hm-chip-ok { background: var(--hm-ok-bg); color: var(--hm-ok); border-color: var(--hm-ok-bd); }
        .hm-chip-warn { background: var(--hm-warn-bg); color: var(--hm-warn); border-color: var(--hm-warn-bd); }
        .hm-chip-error { background: var(--hm-err-bg); color: var(--hm-err); border-color: var(--hm-err-bd); }
        .hm-chip-neutral { background: #F1F5F9; color: #475569; border-color: var(--hm-border); }

        /* ---- Phase stepper (numbered circles + connectors) ---- */
        .hm-stepper { display: flex; align-items: flex-start; gap: 0.4rem; margin: 0.4rem 0 1.3rem 0; }
        .hm-step { display: flex; flex-direction: column; align-items: center; gap: 0.4rem; min-width: 78px; }
        .hm-step-dot {
            width: 34px; height: 34px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-weight: 700; font-size: 0.9rem;
            background: var(--hm-surface); color: #94A3B8; border: 2px solid var(--hm-border);
            transition: all 0.2s ease;
        }
        .hm-step-label { font-size: 0.74rem; color: #94A3B8; font-weight: 600; text-align: center; }
        .hm-conn { flex: 1; height: 2px; min-width: 16px; margin-top: 16px; border-radius: 2px; background: var(--hm-border); }
        .hm-step-done .hm-step-dot { background: var(--hm-teal); border-color: var(--hm-teal); color: #fff; }
        .hm-step-done .hm-step-label { color: var(--hm-text); }
        .hm-conn-done { background: var(--hm-teal); }
        .hm-step-active .hm-step-dot {
            background: #fff; border-color: var(--hm-teal); color: var(--hm-teal);
            animation: hmPulse 1.8s infinite;
        }
        .hm-step-active .hm-step-label { color: var(--hm-teal); font-weight: 700; }
        @keyframes hmPulse {
            0% { box-shadow: 0 0 0 0 rgba(14,165,164,.30); }
            70% { box-shadow: 0 0 0 8px rgba(14,165,164,0); }
            100% { box-shadow: 0 0 0 0 rgba(14,165,164,0); }
        }

        /* ---- Live processing progress bar (top stepper) ---- */
        .hm-prog { margin: -0.4rem 0 1.2rem 0; }
        .hm-prog-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.35rem; }
        .hm-prog-step { font-weight: 600; color: var(--hm-text); font-size: 0.86rem; }
        .hm-prog-pct { font-weight: 700; color: var(--hm-teal); font-variant-numeric: tabular-nums; font-size: 0.86rem; }
        .hm-prog-track { height: 8px; border-radius: 999px; background: #EEF2F6; overflow: hidden;
            box-shadow: inset 0 1px 2px rgba(15,39,66,.06); }
        .hm-prog-fill {
            height: 100%; border-radius: 999px;
            background: linear-gradient(90deg, #5EEAD4, #14B8A6, #0EA5A4, #14B8A6);
            background-size: 200% 100%;
            transition: width 0.45s ease;
            animation: hmShimmer 1.6s linear infinite;
        }
        @keyframes hmShimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }
        .hm-prog-meta { margin-top: 0.4rem; display: flex; gap: 0.4rem; flex-wrap: wrap; }

        /* ---- Risk meter ---- */
        .hm-meter { display: flex; align-items: center; gap: 0.6rem; margin: 0.45rem 0 0.15rem 0; }
        .hm-meter-cap { font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
            letter-spacing: 0.05em; color: var(--hm-muted); min-width: 38px; }
        .hm-meter-track { position: relative; flex: 1; height: 10px; border-radius: 999px; background: #EEF2F6; overflow: visible; }
        .hm-meter-fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px; }
        .hm-meter-tick { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--hm-text); opacity: 0.5; }
        .hm-meter-val { font-weight: 700; font-variant-numeric: tabular-nums; color: var(--hm-text);
            min-width: 36px; text-align: right; font-size: 0.86rem; }

        /* ---- Summary card ---- */
        .hm-card {
            background: var(--hm-surface); border: 1px solid var(--hm-border);
            border-radius: 14px; padding: 1rem 1.15rem; margin-bottom: 1rem;
            box-shadow: var(--hm-shadow);
        }
        .hm-card-title { font-weight: 700; color: var(--hm-text); font-size: 0.95rem; margin-bottom: 0.5rem; }

        /* ---- Metric tiles -> cards ---- */
        div[data-testid="stMetric"] {
            background: var(--hm-surface); border: 1px solid var(--hm-border);
            border-left: 4px solid var(--hm-teal); border-radius: 12px;
            padding: 0.85rem 1.05rem; box-shadow: var(--hm-shadow);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        div[data-testid="stMetric"]:hover { transform: translateY(-2px); box-shadow: var(--hm-shadow-hover); }
        [data-testid="stMetricValue"] { color: var(--hm-text); font-weight: 700; font-variant-numeric: tabular-nums; }
        [data-testid="stMetricLabel"] p {
            color: var(--hm-muted); text-transform: uppercase;
            letter-spacing: 0.05em; font-size: 0.72rem; font-weight: 700;
        }

        /* ---- Buttons ---- */
        .stButton > button, .stDownloadButton > button {
            border-radius: 10px; border: 1px solid var(--hm-border);
            font-weight: 600; transition: all 0.15s ease;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            border-color: var(--hm-teal); color: var(--hm-teal);
        }
        .stButton > button[kind="primary"],
        [data-testid="stBaseButton-primary"], [data-testid="baseButton-primary"] {
            background: linear-gradient(180deg, #14B8A6 0%, var(--hm-teal) 100%);
            border: none; color: #fff;
        }
        .stButton > button[kind="primary"]:hover,
        [data-testid="stBaseButton-primary"]:hover, [data-testid="baseButton-primary"]:hover {
            filter: brightness(1.05); color: #fff; border: none;
        }

        /* ---- Surfaces: expanders, inputs, tabs, sidebar ---- */
        [data-testid="stExpander"] {
            border: 1px solid var(--hm-border); border-radius: 12px;
            background: var(--hm-surface); box-shadow: 0 1px 2px rgba(15,39,66,.04);
        }
        [data-testid="stExpander"] summary { font-weight: 600; color: var(--hm-text); }
        [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea { border-radius: 10px; }
        [data-testid="stTabs"] button[aria-selected="true"] { color: var(--hm-teal); }
        [data-testid="stTabs"] [data-baseweb="tab-highlight"] { background: var(--hm-teal); }
        [data-testid="stSidebar"] { background: var(--hm-surface); border-right: 1px solid var(--hm-border); }
        [data-testid="stChatMessage"] {
            background: var(--hm-surface); border: 1px solid var(--hm-border);
            border-radius: 12px; box-shadow: 0 1px 2px rgba(15,39,66,.04);
        }

        /* ---- Nav ---- */
        .hm-nav-active {
            color: var(--hm-teal); font-weight: 700; padding: 0.2rem 0.45rem;
            border-left: 3px solid var(--hm-teal); background: var(--hm-teal-soft); border-radius: 6px;
        }
        .hm-nav-group {
            color: #94A3B8; font-size: 0.7rem; font-weight: 700;
            letter-spacing: 0.08em; text-transform: uppercase; margin: 0.7rem 0 0.25rem 0;
        }

        /* ---- Scrollbar ---- */
        ::-webkit-scrollbar { width: 10px; height: 10px; }
        ::-webkit-scrollbar-thumb { background: #CBD5E1; border-radius: 999px; }
        ::-webkit-scrollbar-thumb:hover { background: #94A3B8; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _chip_html(label: str, level: str) -> str:
    cls = {
        "ok": "hm-chip-ok",
        "warn": "hm-chip-warn",
        "error": "hm-chip-error",
    }.get(level, "hm-chip-neutral")
    return f'<span class="hm-chip {cls}">{label}</span>'


def render_status_chips(compact: bool = True) -> None:
    """Sidebar system status for Gemini, Phoenix, and Elastic."""
    phoenix = check_phoenix()
    elastic = check_elastic()
    gemini = check_gemini()
    chips = [
        ("Gemini", "ok" if gemini["ok"] else "error"),
        ("Phoenix", "ok" if phoenix["ok"] else "warn"),
        ("Elastic", "ok" if elastic["ok"] else "warn"),
    ]
    html = '<div class="hm-chip-row">' + "".join(
        _chip_html(name, level) for name, level in chips
    ) + "</div>"
    st.markdown(html, unsafe_allow_html=True)
    if not compact:
        for label, check in [("Phoenix", phoenix), ("Elastic", elastic), ("Gemini", gemini)]:
            st.caption(f"{label}: {check.get('detail', '')}")


def init_page(
    title: str,
    *,
    icon: str = "⚓",
    subtitle: str | None = None,
    wide: bool = True,
    sidebar_expanded: bool | None = None,
) -> None:
    kwargs: dict[str, Any] = {
        "page_title": title,
        "page_icon": icon,
        "layout": "wide" if wide else "centered",
    }
    if sidebar_expanded is not None:
        kwargs["initial_sidebar_state"] = "expanded" if sidebar_expanded else "auto"
    st.set_page_config(**kwargs)
    inject_theme_css()
    sub_html = f'<div class="hm-hero-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="hm-hero"><div class="hm-hero-title">{icon} {title}</div>{sub_html}</div>',
        unsafe_allow_html=True,
    )


def _show_phoenix_link() -> bool:
    snapshot = get_snapshot()
    host = (snapshot.phoenix.console_url or "").lower()
    if "localhost" in host or "127.0.0.1" in host:
        if str(snapshot.raw.get("RUNNING_IN_DOCKER", "")).lower() in {"1", "true", "yes"}:
            return False
    return True


def render_app_sidebar(
    current_page: str,
    *,
    extra_blocks: Callable[[], None] | None = None,
    show_demo: bool = False,
) -> None:
    """Standard sidebar: header, status, nav, optional extras, Phoenix link."""
    with st.sidebar:
        st.markdown("### ⚓ Harbourmaster")
        st.markdown(
            '<p class="hm-tagline">Governed multi-agent tender review</p>',
            unsafe_allow_html=True,
        )
        render_status_chips(compact=True)
        st.divider()
        render_grouped_nav(current_page)
        if extra_blocks:
            st.divider()
            extra_blocks()
        if show_demo:
            _render_demo_callout()
        if _show_phoenix_link():
            st.divider()
            from app.utils.links import render_phoenix_console_link

            render_phoenix_console_link()


def _render_demo_callout() -> None:
    st.markdown("**Quick demo**")
    samples = [
        ("Human review", "data/sample_tender_human_review.md"),
        ("Standard", "data/sample_tender.md"),
        ("Low risk", "data/sample_tender_low_risk.md"),
    ]
    active = st.session_state.get("active_sample")
    for label, path in samples:
        if st.button(
            f"Load {label}",
            key=f"demo-{path}",
            use_container_width=True,
            type="primary" if label == active else "secondary",
        ):
            st.session_state.demo_sample_path = path
            st.session_state.phase = "idle"
            st.rerun()


def render_phase_stepper(phase: str, *, live: dict[str, Any] | None = None) -> None:
    steps = ["idle", "processing", "awaiting_review", "complete"]
    current = phase
    if current == "analysing":
        current = "processing"
    if current not in steps:
        current = "idle"
    idx = steps.index(current)
    parts: list[str] = []
    for i, step in enumerate(steps):
        if i < idx:
            cls, dot = "hm-step hm-step-done", "✓"
        elif i == idx:
            cls, dot = "hm-step hm-step-active", str(i + 1)
        else:
            cls, dot = "hm-step", str(i + 1)
        parts.append(
            f'<div class="{cls}"><div class="hm-step-dot">{dot}</div>'
            f'<div class="hm-step-label">{PHASE_LABELS[step]}</div></div>'
        )
        if i < len(steps) - 1:
            conn = "hm-conn hm-conn-done" if i < idx else "hm-conn"
            parts.append(f'<div class="{conn}"></div>')
    st.markdown(f'<div class="hm-stepper">{"".join(parts)}</div>', unsafe_allow_html=True)

    if current == "processing":
        _render_processing_bar(live or {})


def _render_processing_bar(live: dict[str, Any]) -> None:
    """Determinate, live progress bar shown under the stepper while processing."""
    try:
        frac = max(0.0, min(1.0, float(live.get("fraction") or 0.0)))
    except (TypeError, ValueError):
        frac = 0.0
    pct = int(round(frac * 100))
    current_label = str(live.get("current_step") or "").strip()
    if not current_label or current_label == "—":
        current_label = "Starting workflow…"

    chips: list[str] = []
    verdict = live.get("guard_verdict")
    if verdict:
        level = "ok" if verdict == "ALLOW" else "warn" if verdict == "HUMAN_REVIEW" else "error"
        chips.append(_chip_html(f"Guard: {verdict}", level))
    done = live.get("specialists_done")
    if done is not None:
        total = live.get("specialists_total", 5)
        chips.append(_chip_html(f"Specialists: {done}/{total}", "neutral"))
    revision = live.get("revision_round")
    if revision:
        chips.append(_chip_html(f"Revision {revision}", "warn"))
    risk = live.get("overall_risk")
    if risk is not None:
        level = "error" if float(risk) >= 0.7 else "warn" if float(risk) >= 0.4 else "ok"
        chips.append(_chip_html(f"Risk: {float(risk):.2f}", level))

    meta = f'<div class="hm-prog-meta">{"".join(chips)}</div>' if chips else ""
    st.markdown(
        '<div class="hm-prog">'
        '<div class="hm-prog-head">'
        f'<span class="hm-prog-step">{current_label}</span>'
        f'<span class="hm-prog-pct">{pct}%</span>'
        "</div>"
        '<div class="hm-prog-track">'
        f'<div class="hm-prog-fill" style="width:{frac * 100:.0f}%"></div>'
        "</div>"
        f"{meta}</div>",
        unsafe_allow_html=True,
    )


def render_summary_card(
    *,
    guard_verdict: str | None = None,
    overall_risk: float | None = None,
    specialists_done: int | None = None,
    specialists_total: int = 5,
    review_id: str | None = None,
    phase: str | None = None,
) -> None:
    chips = []
    if phase:
        chips.append(_chip_html(f"Phase: {PHASE_LABELS.get(phase, phase)}", "neutral"))
    if guard_verdict:
        level = "ok" if guard_verdict == "ALLOW" else "warn" if guard_verdict == "HUMAN_REVIEW" else "error"
        chips.append(_chip_html(f"Guard: {guard_verdict}", level))
    if specialists_done is not None:
        chips.append(_chip_html(f"Specialists: {specialists_done}/{specialists_total}", "neutral"))
    if review_id:
        chips.append(_chip_html(f"Review: {review_id[:12]}", "neutral"))

    from app.utils.render import risk_meter

    chip_row = '<div class="hm-chip-row">' + "".join(chips) + "</div>" if chips else ""
    meter = risk_meter(overall_risk) if overall_risk is not None else ""
    st.markdown(
        f'<div class="hm-card"><div class="hm-card-title">Workflow summary</div>{chip_row}{meter}</div>',
        unsafe_allow_html=True,
    )
