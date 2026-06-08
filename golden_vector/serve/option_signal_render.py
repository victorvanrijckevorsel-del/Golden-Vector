"""Small shared HTML helpers for persisted option-signal labels."""

from __future__ import annotations

from html import escape

from golden_vector.common.numeric import optional_float


def render_option_signal_badge(value: object) -> str:
    text = str(value or "-")
    label = text.replace("_", " ").title()
    return f"<span class=\"badge {_badge_class(text)}\">{escape(label)}</span>"


def format_vol_points(value: object) -> str:
    numeric = optional_float(value)
    if numeric is None:
        return "-"
    return f"{numeric * 100:.1f} vol pts"


def option_signal_skew_display_value(
    signal: dict[str, object] | None,
    *,
    horizon: int = 60,
) -> object | None:
    """Return the primary skew number to display for a persisted signal row.

    Single names show residual skew versus their benchmark. Benchmark ETFs are
    the sector gauge, so they show their own absolute skew while the residual
    remains zero by definition.
    """

    if not signal:
        return None
    ticker = str(signal.get("ticker") or "").strip().upper()
    benchmark = str(signal.get("benchmark_symbol") or "").strip().upper()
    vehicle_type = str(signal.get("option_vehicle_type") or "").strip()
    if ticker and (ticker == benchmark or vehicle_type == "benchmark_etf"):
        return signal.get(f"name_skew_{horizon}d")
    return signal.get(f"skew_residual_{horizon}d")


def _badge_class(value: str) -> str:
    return {
        "OK": "badge-verified",
        "DOWNSIDE": "badge-incomplete",
        "UPSIDE": "badge-verified",
        "NEUTRAL": "badge-estimated",
        "RICH": "badge-incomplete",
        "CHEAP": "badge-verified",
        "LIMITED_HISTORY": "badge-estimated",
        "STALE_QUOTES": "badge-incomplete",
        "LOW_LIQUIDITY": "badge-estimated",
        "SPARSE": "badge-estimated",
        "NO_BENCHMARK": "badge-missing",
        "NO_BULLISH_CONFIRMATION": "badge-estimated",
    }.get(value, "badge")
