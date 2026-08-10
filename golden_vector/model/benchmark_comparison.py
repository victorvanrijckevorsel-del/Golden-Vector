"""Window-aware comparison of one stock's gold beta against GDX/GDXJ and the miner universe.

Emanuel's requirement: when the detail page switches window (6M / 12M / 3Y), the stock, the
GDX/GDXJ benchmarks, and the miner-universe distribution must ALL be measured over the SAME
window — otherwise the comparison is apples-to-oranges.

Every analytic decision lives here in the model layer: which column a window maps to, the
percentile rank within the universe, the axis domain, and each marker's fractional position
along that axis. ``serve``/``charts`` only format the resolved numbers — they never compute a
percentile, a rank, or a min/max. Degraded inputs degrade per item (a ticker with no beta for
the window is excluded from the distribution; a missing benchmark column yields ``None``), never
a crash.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.common.numeric import optional_finite_float
from golden_vector.common.windows import (
    WINDOW_LABELS,
    is_window,
    window_suffix as _registry_window_suffix,
)

# Suffix/label come from the ONE window registry (common/windows.py) so the universe
# comparison can't drift from the rest of the app (e.g. 12M renders as "1Y" everywhere,
# not "12-month" here). CORE is the only non-structural extra this panel adds.
_CORE_KEY = "CORE"


@dataclass(frozen=True)
class BetaMarker:
    """One point in the comparison: the subject stock, GDX, or GDXJ."""

    label: str
    is_subject: bool
    is_benchmark: bool
    down_beta: float | None
    up_beta: float | None
    # Fractional position (0..1) along the universe axis, resolved in the backend so serve
    # only multiplies by pixel width. None when the value is unavailable.
    down_pos: float | None
    up_pos: float | None
    # Percentile (0..100) within the miner universe for this window. None when unavailable.
    down_percentile: float | None
    up_percentile: float | None


@dataclass(frozen=True)
class BetaUniverseMark:
    """One miner's tick on the universe rug: its ticker + beta + 0..1 axis position.

    Carries the ticker so the strip can identify each otherwise-anonymous rug tick on hover
    ("NEM · 1.40"); the page only places ``position`` and shows ``ticker``/``beta`` — no math.
    """

    ticker: str
    beta: float
    position: float


@dataclass(frozen=True)
class BetaUniverseComparison:
    window_id: str
    window_label: str
    available: bool
    universe_down_n: int
    universe_up_n: int
    down_domain: tuple[float, float] | None
    up_domain: tuple[float, float] | None
    subject: BetaMarker | None
    benchmarks: tuple[BetaMarker, ...]
    note: str | None = None
    # EVERY scored miner as a (ticker, beta, 0..1 position) mark, for the universe "rug" on the
    # strip — shows the whole distribution AND lets each tick be identified on hover.
    down_universe_marks: tuple[BetaUniverseMark, ...] = ()
    up_universe_marks: tuple[BetaUniverseMark, ...] = ()




def _column_ticker_values(
    frame: pd.DataFrame | None, column: str
) -> list[tuple[str, float]]:
    """(ticker, beta) for each universe row with a finite beta — keeps the ticker so the rug
    tick can be identified on hover. Degrades per item: rows without a finite beta are skipped."""
    if (
        frame is None
        or frame.empty
        or column not in frame.columns
        or "ticker" not in frame.columns
    ):
        return []
    out: list[tuple[str, float]] = []
    for raw_ticker, raw_value in zip(frame["ticker"].tolist(), frame[column].tolist()):
        value = optional_finite_float(raw_value)
        ticker = str(raw_ticker or "").strip().upper()
        if value is not None and ticker:
            out.append((ticker, value))
    return out


def _percentile(sorted_values: list[float], value: float | None) -> float | None:
    """Share of the universe at or below ``value``, in percent (ties counted inclusively)."""

    if value is None or not sorted_values:
        return None
    count_at_or_below = sum(1 for item in sorted_values if item <= value)
    return 100.0 * count_at_or_below / len(sorted_values)


def _position(value: float | None, domain: tuple[float, float] | None) -> float | None:
    """Map a beta value to a 0..1 position along the axis domain (clamped)."""

    if value is None or domain is None:
        return None
    low, high = domain
    if high <= low:
        return 0.5
    return min(1.0, max(0.0, (value - low) / (high - low)))


def _domain(values: list[float]) -> tuple[float, float] | None:
    if not values:
        return None
    return (min(values), max(values))


def _subject_betas(
    universe_df: pd.DataFrame | None,
    ticker: str,
    down_col: str,
    up_col: str,
) -> tuple[float | None, float | None]:
    if (
        universe_df is None
        or universe_df.empty
        or "ticker" not in universe_df.columns
    ):
        return None, None
    match = universe_df.loc[
        universe_df["ticker"].astype(str).str.strip().str.upper() == ticker.strip().upper()
    ]
    if match.empty:
        return None, None
    row = match.iloc[0]
    return optional_finite_float(row.get(down_col)), optional_finite_float(row.get(up_col))


def _benchmark_betas(
    benchmark_df: pd.DataFrame | None,
    down_col: str,
    up_col: str,
) -> list[tuple[str, str, float | None, float | None]]:
    if (
        benchmark_df is None
        or benchmark_df.empty
        or "benchmark_ticker" not in benchmark_df.columns
    ):
        return []
    has_status = "benchmark_status" in benchmark_df.columns
    out: list[tuple[str, str, float | None, float | None]] = []
    for _, row in benchmark_df.iterrows():
        ticker = str(row.get("benchmark_ticker") or "").strip().upper()
        if not ticker:
            continue
        # Degraded benchmarks (LOW_CONFIDENCE / UNAVAILABLE / MISSING_*) must NOT appear as clean
        # comparables — exclude them rather than show a falsely-confident GDX/GDXJ marker. Treat a
        # missing status column as OK (older artifacts) so the comparison still works.
        if has_status:
            status = str(row.get("benchmark_status") or "").strip().upper()
            if status and status != "OK":
                continue
        # Display the short ticker (GDX/GDXJ) on the strip; the full ETF name is too long.
        out.append(
            (
                ticker,
                ticker,
                optional_finite_float(row.get(down_col)),
                optional_finite_float(row.get(up_col)),
            )
        )
    return out


def resolve_beta_universe_comparison(
    *,
    ticker: str,
    window_id: str,
    universe_df: pd.DataFrame | None,
    benchmark_df: pd.DataFrame | None,
) -> BetaUniverseComparison:
    """Resolve the stock-vs-(GDX/GDXJ)-vs-universe beta comparison for ONE window."""

    key = (window_id or "").upper()
    if key == _CORE_KEY:
        suffix = "core"
        label = "full-history"
    elif is_window(key):
        suffix = _registry_window_suffix(key)
        label = WINDOW_LABELS.get(key, key)
    else:
        suffix = None
        label = window_id
    if suffix is None:
        return BetaUniverseComparison(
            window_id=key,
            window_label=label,
            available=False,
            universe_down_n=0,
            universe_up_n=0,
            down_domain=None,
            up_domain=None,
            subject=None,
            benchmarks=(),
            note=f"No comparison column for window {window_id}.",
        )

    down_col, up_col = f"down_beta_{suffix}", f"up_beta_{suffix}"
    universe_down_pairs = _column_ticker_values(universe_df, down_col)
    universe_up_pairs = _column_ticker_values(universe_df, up_col)
    universe_down = [beta for _, beta in universe_down_pairs]
    universe_up = [beta for _, beta in universe_up_pairs]
    if not universe_down and not universe_up:
        return BetaUniverseComparison(
            window_id=key,
            window_label=label,
            available=False,
            universe_down_n=0,
            universe_up_n=0,
            down_domain=None,
            up_domain=None,
            subject=None,
            benchmarks=(),
            note="No universe betas are available for this window.",
        )

    subject_down, subject_up = _subject_betas(universe_df, ticker, down_col, up_col)
    raw_benchmarks = _benchmark_betas(benchmark_df, down_col, up_col)

    # The axis must span the universe AND every marker so each tick is visible.
    down_domain = _domain(
        universe_down
        + [v for v in [subject_down, *[b[2] for b in raw_benchmarks]] if v is not None]
    )
    up_domain = _domain(
        universe_up
        + [v for v in [subject_up, *[b[3] for b in raw_benchmarks]] if v is not None]
    )
    down_sorted = sorted(universe_down)
    up_sorted = sorted(universe_up)

    subject_marker: BetaMarker | None = None
    if subject_down is not None or subject_up is not None:
        subject_marker = BetaMarker(
            label=ticker.upper(),
            is_subject=True,
            is_benchmark=False,
            down_beta=subject_down,
            up_beta=subject_up,
            down_pos=_position(subject_down, down_domain),
            up_pos=_position(subject_up, up_domain),
            down_percentile=_percentile(down_sorted, subject_down),
            up_percentile=_percentile(up_sorted, subject_up),
        )

    benchmark_markers = tuple(
        BetaMarker(
            label=ticker_label,
            is_subject=False,
            is_benchmark=True,
            down_beta=down_value,
            up_beta=up_value,
            down_pos=_position(down_value, down_domain),
            up_pos=_position(up_value, up_domain),
            down_percentile=_percentile(down_sorted, down_value),
            up_percentile=_percentile(up_sorted, up_value),
        )
        for (ticker_key, ticker_label, down_value, up_value) in raw_benchmarks
        if down_value is not None or up_value is not None
    )

    down_universe_marks = tuple(
        BetaUniverseMark(ticker=tkr, beta=beta, position=pos)
        for (tkr, beta) in universe_down_pairs
        if (pos := _position(beta, down_domain)) is not None
    )
    up_universe_marks = tuple(
        BetaUniverseMark(ticker=tkr, beta=beta, position=pos)
        for (tkr, beta) in universe_up_pairs
        if (pos := _position(beta, up_domain)) is not None
    )

    return BetaUniverseComparison(
        window_id=key,
        window_label=label,
        available=True,
        universe_down_n=len(down_sorted),
        universe_up_n=len(up_sorted),
        down_domain=down_domain,
        up_domain=up_domain,
        subject=subject_marker,
        benchmarks=benchmark_markers,
        note=None,
        down_universe_marks=down_universe_marks,
        up_universe_marks=up_universe_marks,
    )


def resolve_beta_universe_comparisons_by_window(
    *,
    ticker: str,
    window_ids: tuple[str, ...],
    universe_df: pd.DataFrame | None,
    benchmark_df: pd.DataFrame | None,
) -> dict[str, BetaUniverseComparison]:
    """Resolve the comparison for every selectable window in one pass (cheap column reads)."""

    return {
        window_id: resolve_beta_universe_comparison(
            ticker=ticker,
            window_id=window_id,
            universe_df=universe_df,
            benchmark_df=benchmark_df,
        )
        for window_id in window_ids
    }
