"""Most-liquid expiry selection per ticker, side, and configured horizon window.

Milestone C3 backend contract (plan v3, Codex-agreed): the "Most liquid"
default is chosen here during the option-artifact build — never in serve.
Selection evaluates ONLY configured horizon windows, uses tradable contracts
only (Milestone B's aggregation primitive), scores with robust medians rather
than raw sums, is side-aware, and breaks every tie deterministically.

This module is pure: it takes contract metrics plus the configured windows
and returns selections. Wiring into the artifact build / UI switcher is C3b.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from golden_vector.hedge.options_liquidity import (
    OptionContractMetrics,
    OptionSideType,
    aggregate_tradable_liquidity,
)


@dataclass(frozen=True)
class ExpiryLiquidity:
    """Tradable-liquidity aggregate for one ticker/side/window/expiry."""

    ticker: str
    side: OptionSideType
    horizon_days: int
    expiration: str
    days_to_expiry: int
    tradable_count: int
    median_rel_spread: float | None
    median_open_interest: float | None
    median_volume: float | None
    median_near_spot_depth: float | None
    is_standard_monthly: bool


@dataclass(frozen=True)
class MostLiquidSelection:
    """The chosen most-liquid expiry for one ticker/side/window."""

    ticker: str
    side: OptionSideType
    horizon_days: int
    expiration: str
    days_to_expiry: int
    tradable_count: int
    median_rel_spread: float | None
    median_open_interest: float | None
    median_volume: float | None
    median_near_spot_depth: float | None
    is_standard_monthly: bool = False


def rank_expiry_liquidity(
    *,
    metrics: Iterable[OptionContractMetrics],
    ticker: str,
    side: OptionSideType,
    horizon_days: int,
    band: tuple[int, int],
) -> tuple[ExpiryLiquidity, ...]:
    """Aggregate tradable liquidity per expiry inside one configured window."""

    lower, upper = band
    in_window = [
        metric
        for metric in metrics
        if metric.ticker.upper() == ticker.upper()
        and metric.option_type == side
        and lower <= metric.days_to_expiry <= upper
    ]
    by_expiry: dict[str, list[OptionContractMetrics]] = {}
    for metric in in_window:
        by_expiry.setdefault(metric.expiration, []).append(metric)
    results: list[ExpiryLiquidity] = []
    for expiration in sorted(by_expiry):
        expiry_metrics = by_expiry[expiration]
        aggregate = aggregate_tradable_liquidity(expiry_metrics)
        if aggregate.tradable_count == 0:
            continue
        results.append(
            ExpiryLiquidity(
                ticker=ticker.upper(),
                side=side,
                horizon_days=int(horizon_days),
                expiration=expiration,
                days_to_expiry=min(metric.days_to_expiry for metric in expiry_metrics),
                tradable_count=aggregate.tradable_count,
                median_rel_spread=aggregate.median_tradable_rel_spread,
                median_open_interest=aggregate.median_tradable_open_interest,
                median_volume=aggregate.median_tradable_volume,
                median_near_spot_depth=aggregate.median_tradable_near_spot_depth,
                is_standard_monthly=any(
                    metric.is_standard_monthly for metric in expiry_metrics
                ),
            )
        )
    return tuple(results)


def _expiry_sort_key(candidate: ExpiryLiquidity, *, target_days: int) -> tuple:
    """Deterministic ranking: robust liquidity first, tie-breakers last.

    Order (plan v3): tradable count desc, median spread asc, median OI desc,
    median volume desc, median near-spot depth desc, standard monthly first,
    DTE distance to the window target asc, earlier expiration, lexical.
    """

    return (
        -candidate.tradable_count,
        candidate.median_rel_spread if candidate.median_rel_spread is not None else float("inf"),
        -(candidate.median_open_interest or 0.0),
        -(candidate.median_volume or 0.0),
        -(candidate.median_near_spot_depth or 0.0),
        not candidate.is_standard_monthly,
        abs(candidate.days_to_expiry - target_days),
        candidate.expiration,
    )


def select_most_liquid_expiry(
    *,
    metrics: Iterable[OptionContractMetrics],
    ticker: str,
    side: OptionSideType,
    horizon_days: int,
    band: tuple[int, int],
) -> MostLiquidSelection | None:
    """The most-liquid listed expiry for one ticker/side inside one window."""

    candidates = rank_expiry_liquidity(
        metrics=metrics,
        ticker=ticker,
        side=side,
        horizon_days=horizon_days,
        band=band,
    )
    if not candidates:
        return None
    best = min(candidates, key=lambda item: _expiry_sort_key(item, target_days=horizon_days))
    return MostLiquidSelection(
        ticker=best.ticker,
        side=best.side,
        horizon_days=best.horizon_days,
        expiration=best.expiration,
        days_to_expiry=best.days_to_expiry,
        tradable_count=best.tradable_count,
        median_rel_spread=best.median_rel_spread,
        median_open_interest=best.median_open_interest,
        median_volume=best.median_volume,
        median_near_spot_depth=best.median_near_spot_depth,
        is_standard_monthly=best.is_standard_monthly,
    )


def select_ticker_default_window(
    *,
    metrics: Iterable[OptionContractMetrics],
    ticker: str,
    side: OptionSideType,
    dte_bands: Mapping[int, tuple[int, int]],
) -> MostLiquidSelection | None:
    """A ticker's best window/expiry for one side (detail-page default).

    Windows compete on their best expiry's aggregates with the same
    deterministic chain (incl. standard-monthly-first); the DTE-distance
    tie-breaker does not apply across windows, so the final cross-window
    tie-breaks are the smaller horizon, then lexical expiration.
    """

    metric_list = list(metrics)
    per_window = [
        selection
        for horizon_days, band in sorted(dte_bands.items())
        for selection in (
            select_most_liquid_expiry(
                metrics=metric_list,
                ticker=ticker,
                side=side,
                horizon_days=horizon_days,
                band=tuple(band),
            ),
        )
        if selection is not None
    ]
    if not per_window:
        return None
    return min(
        per_window,
        key=lambda item: (
            -item.tradable_count,
            item.median_rel_spread if item.median_rel_spread is not None else float("inf"),
            -(item.median_open_interest or 0.0),
            -(item.median_volume or 0.0),
            -(item.median_near_spot_depth or 0.0),
            not item.is_standard_monthly,
            item.horizon_days,
            item.expiration,
        ),
    )


def select_group_default_window(
    *,
    metrics: Iterable[OptionContractMetrics],
    tickers: Iterable[str],
    side: OptionSideType,
    dte_bands: Mapping[int, tuple[int, int]],
    exclude_tickers: Iterable[str] = (),
    precomputed: Mapping[str, MostLiquidSelection | None] | None = None,
) -> int | None:
    """Group-level default window for the overview (single-stock miners).

    Per-ticker normalized voting (plan v3): every eligible ticker votes for
    its own best window, so one ticker with thousands of contracts (or the
    benchmark ETFs, which are excluded) cannot dominate the default. Ties
    break by vote count desc, then the smaller horizon for determinism.
    ``precomputed`` lets the artifact build reuse already-computed per-ticker
    selections instead of re-running them (audit M8).
    """

    excluded = {str(ticker).upper() for ticker in exclude_tickers}
    metric_list = list(metrics) if precomputed is None else []
    votes: dict[int, int] = {}
    for ticker in sorted({str(ticker).upper() for ticker in tickers} - excluded):
        if precomputed is not None:
            best = precomputed.get(ticker)
        else:
            best = select_ticker_default_window(
                metrics=metric_list,
                ticker=ticker,
                side=side,
                dte_bands=dte_bands,
            )
        if best is None:
            continue
        votes[best.horizon_days] = votes.get(best.horizon_days, 0) + 1
    if not votes:
        return None
    return min(votes, key=lambda horizon: (-votes[horizon], horizon))
