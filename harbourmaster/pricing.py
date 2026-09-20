"""Rough Gemini token pricing for cost estimates (USD per 1M tokens).

These are approximate list prices used only to attach an indicative ``cost_usd`` to
telemetry spans — they are NOT billing-accurate and should be treated as estimates.
Update as Google pricing changes.
"""

from __future__ import annotations

# model substring -> (input_usd_per_1M, output_usd_per_1M)
_PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-1.5-flash": (0.075, 0.30),
}
_DEFAULT: tuple[float, float] = (0.30, 2.50)  # fall back to a flash-class price


def model_prices(model: str) -> tuple[float, float]:
    """Return (input_per_1M, output_per_1M) for a model name (best-effort match)."""
    name = (model or "").lower()
    for key, price in _PRICES.items():
        if key in name:
            return price
    return _DEFAULT


def estimate_cost(model: str, prompt_tokens: float, completion_tokens: float) -> float:
    """Estimate USD cost for one call from its token split."""
    in_price, out_price = model_prices(model)
    return (
        float(prompt_tokens or 0) * in_price + float(completion_tokens or 0) * out_price
    ) / 1_000_000.0
