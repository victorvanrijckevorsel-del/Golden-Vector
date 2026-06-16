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


def signal_horizon_from_row(
    signal: dict[str, object] | None,
    *,
    fallback: int | None = None,
) -> int | None:
    """The signal horizon a persisted row was built at (never recomputed).

    No stale-constant fallback (audit L2): when the row predates the horizon
    column, return None and let callers use their documented fallbacks
    (e.g. the history chart's min-of-points).
    """

    if not signal:
        return fallback
    value = optional_float(signal.get("signal_horizon_days"))
    return int(value) if value is not None else fallback


def option_signal_skew_display_value(
    signal: dict[str, object] | None,
    *,
    horizon: int | None = None,
) -> object | None:
    """Return the primary skew number to display for a persisted signal row.

    Single names show residual skew versus their benchmark. Benchmark ETFs are
    the sector gauge, so they show their own absolute skew while the residual
    remains zero by definition. The horizon comes from the row itself unless
    explicitly overridden.
    """

    if not signal:
        return None
    if horizon is None:
        horizon = signal_horizon_from_row(signal)
    if horizon is None:
        return None
    ticker = str(signal.get("ticker") or "").strip().upper()
    benchmark = str(signal.get("benchmark_symbol") or "").strip().upper()
    vehicle_type = str(signal.get("option_vehicle_type") or "").strip()
    if ticker and (ticker == benchmark or vehicle_type == "benchmark_etf"):
        return signal.get(f"name_skew_{horizon}d")
    return signal.get(f"skew_residual_{horizon}d")


def option_signal_skew_hover(
    signal: dict[str, object] | None,
    *,
    horizon: int | None = None,
) -> str | None:
    """Plain-text hover showing the actual skew calculation for one row.

    Built only from the persisted signal fields (name skew, benchmark skew,
    residual, benchmark symbol) — serve renders the stored math, it never
    recomputes it.
    """

    if not signal:
        return None
    if horizon is None:
        horizon = signal_horizon_from_row(signal)
    if horizon is None:
        return None
    ticker = str(signal.get("ticker") or "").strip().upper() or "This stock"
    benchmark = str(signal.get("benchmark_symbol") or "").strip().upper() or "the benchmark"
    vehicle_type = str(signal.get("option_vehicle_type") or "").strip()
    name_skew = optional_float(signal.get(f"name_skew_{horizon}d"))
    if ticker == benchmark or vehicle_type == "benchmark_etf":
        if name_skew is None:
            return None
        return (
            f"Benchmark skew, {horizon}d window:\n"
            f"{ticker} put/call skew: {format_vol_points(name_skew)}\n"
            "This is the sector baseline used to compare single-stock skew.\n"
            "Positive means puts are priced richer than calls."
        )
    sector_skew = optional_float(signal.get(f"sector_skew_{horizon}d"))
    residual = optional_float(signal.get(f"skew_residual_{horizon}d"))
    if name_skew is None and residual is None:
        return None
    return (
        f"Skew vs benchmark, {horizon}d window:\n"
        f"{ticker} stock skew: {format_vol_points(name_skew)}\n"
        f"Benchmark used: {benchmark}\n"
        f"{benchmark} benchmark skew: {format_vol_points(sector_skew)}\n"
        f"Difference: {format_vol_points(residual)}\n"
        f"Positive means {ticker} puts are priced richer than calls versus {benchmark}."
    )


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
        "NO_UPSIDE_VOLUME_PULSE": "badge-estimated",
    }.get(value, "badge")
