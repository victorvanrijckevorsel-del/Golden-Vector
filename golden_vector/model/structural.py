"""Structural Tool A metric construction from USD-normalized weekly returns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from golden_vector.common.numeric import strict_optional_float as _optional_float
from golden_vector.contracts.config_models import ScoringConfig


WEEKLY_SERIES_COLUMNS = [
    "ticker",
    "as_of_date",
    "stock_week_date",
    "gold_week_date",
    "stock_basis_usd",
    "gold_basis_usd",
    "stock_weekly_log_return",
    "gold_weekly_log_return",
]

STRUCTURAL_WINDOW_COLUMNS = [
    "ticker",
    "as_of_date",
    "window_id",
    "week_count",
    "window_status",
    "window_reason",
    "structural_delta",
    "intercept_alpha",
    "r_squared",
    "up_week_count",
    "down_week_count",
    "up_beta",
    "down_beta",
    "gamma_value",
    "asymmetry_ratio",
    "normalization_issue_summary",
    "source_run_id",
]

VOLATILITY_DIAGNOSTIC_COLUMNS = [
    "ticker",
    "as_of_date",
    "volatility_anchor_window_id",
    "total_volatility_52w",
    "residual_volatility_52w",
    "downside_volatility_52w",
]

VALID_NORMALIZATION_STATUSES = {
    "OK",
    "MISSING_FX",
    "STALE_FX",
    "MISSING_RETURN_BASIS",
}
_CENTERED_SUM_FALLBACK_REL_TOL = 1e-12


@dataclass(frozen=True)
class StructuralTickerData:
    weekly_series: pd.DataFrame
    structural_window_metrics: pd.DataFrame
    normalization_issues: pd.DataFrame


@dataclass(frozen=True)
class RegressionResult:
    alpha: float
    beta: float
    r_squared: float
    residuals: np.ndarray


@dataclass(frozen=True)
class _RegressionPrefixSums:
    n: np.ndarray
    x: np.ndarray
    y: np.ndarray
    xy: np.ndarray
    xx: np.ndarray
    yy: np.ndarray


@dataclass(frozen=True)
class _RegressionWindowSums:
    n: np.ndarray
    x: np.ndarray
    y: np.ndarray
    xy: np.ndarray
    xx: np.ndarray
    yy: np.ndarray


@dataclass(frozen=True)
class _OlsMetric:
    alpha: float
    beta: float
    r_squared: float


@dataclass(frozen=True)
class _VectorizedWindowData:
    start_idx: np.ndarray
    end_idx: np.ndarray
    raw_count: np.ndarray
    up_count: np.ndarray
    down_count: np.ndarray
    full_sums: _RegressionWindowSums
    up_sums: _RegressionWindowSums
    down_sums: _RegressionWindowSums


@dataclass(frozen=True)
class _VolatilityWeeklyArrays:
    as_of_dates: np.ndarray
    stock_returns: np.ndarray
    gold_returns: np.ndarray


@dataclass(frozen=True)
class _VolatilityWindow:
    stock_returns: np.ndarray
    gold_returns: np.ndarray


@dataclass(frozen=True)
class _VolatilityAnchorRow:
    ticker: str
    as_of_date: object
    anchor_window_id: str | None
    intercept_alpha: object
    structural_delta: object


def build_structural_ticker_data(
    *,
    usd_equity_history: pd.DataFrame,
    gold_history: pd.DataFrame,
    scoring_config: ScoringConfig,
) -> StructuralTickerData:
    weekly_series, normalization_issues = build_structural_weekly_series(
        usd_equity_history=usd_equity_history,
        gold_history=gold_history,
    )
    window_metrics = compute_structural_window_metrics(
        weekly_series=weekly_series,
        normalization_issues=normalization_issues,
        scoring_config=scoring_config,
    )
    return StructuralTickerData(
        weekly_series=weekly_series,
        structural_window_metrics=window_metrics,
        normalization_issues=normalization_issues,
    )


def build_structural_weekly_series(
    *,
    usd_equity_history: pd.DataFrame,
    gold_history: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if usd_equity_history.empty or gold_history.empty:
        return (
            pd.DataFrame(columns=WEEKLY_SERIES_COLUMNS),
            pd.DataFrame(columns=["ticker", "date", "normalization_status"]),
        )

    equity = usd_equity_history.copy()
    equity["date"] = pd.to_datetime(equity["date"])
    if "ticker" not in equity.columns or equity["ticker"].dropna().empty:
        return (
            pd.DataFrame(columns=WEEKLY_SERIES_COLUMNS),
            pd.DataFrame(columns=["ticker", "date", "normalization_status"]),
        )

    ticker = str(equity["ticker"].dropna().iloc[0]).upper()
    equity["normalization_status"] = (
        equity.get("normalization_status", pd.Series(index=equity.index, dtype=object))
        .fillna("UNKNOWN")
        .astype(str)
        .str.upper()
    )
    basis_usd = pd.to_numeric(equity.get("return_basis_usd"), errors="coerce")
    issue_status = equity["normalization_status"].where(
        equity["normalization_status"].ne("OK"),
        np.where(basis_usd.gt(0), "OK", "MISSING_RETURN_BASIS"),
    )
    normalization_issues = equity.loc[
        pd.Series(issue_status, index=equity.index).astype(str).str.upper().ne("OK"),
        ["date"],
    ].copy()
    normalization_issues.insert(0, "ticker", ticker)
    normalization_issues["normalization_status"] = (
        pd.Series(issue_status, index=equity.index)
        .loc[normalization_issues.index]
        .astype(str)
        .str.upper()
        .to_numpy()
    )

    equity_ok = equity.loc[
        equity["normalization_status"].eq("OK") & basis_usd.gt(0)
    ].copy()
    if equity_ok.empty:
        return (
            pd.DataFrame(columns=WEEKLY_SERIES_COLUMNS),
            normalization_issues.reset_index(drop=True),
        )
    equity_ok["basis_usd"] = pd.to_numeric(equity_ok["return_basis_usd"], errors="coerce")
    equity_ok = equity_ok.loc[equity_ok["basis_usd"].gt(0)].copy()
    if equity_ok.empty:
        return (
            pd.DataFrame(columns=WEEKLY_SERIES_COLUMNS),
            normalization_issues.reset_index(drop=True),
        )

    gold = gold_history.copy()
    gold["date"] = pd.to_datetime(gold["date"])
    gold["basis_usd"] = pd.to_numeric(gold.get("adj_close_usd"), errors="coerce")
    if "close_usd" in gold.columns:
        gold["basis_usd"] = gold["basis_usd"].where(
            gold["basis_usd"].notna(),
            pd.to_numeric(gold["close_usd"], errors="coerce"),
        )
    gold = gold.loc[gold["basis_usd"].gt(0)].copy()
    if gold.empty:
        return (
            pd.DataFrame(columns=WEEKLY_SERIES_COLUMNS),
            normalization_issues.reset_index(drop=True),
        )

    stock_weekly = _last_trading_day_per_week(
        frame=equity_ok,
        basis_column="basis_usd",
        value_label="stock",
    )
    gold_weekly = _last_trading_day_per_week(
        frame=gold,
        basis_column="basis_usd",
        value_label="gold",
    )
    if stock_weekly.empty or gold_weekly.empty:
        return (
            pd.DataFrame(columns=WEEKLY_SERIES_COLUMNS),
            normalization_issues.reset_index(drop=True),
        )

    merged = stock_weekly.merge(
        gold_weekly,
        how="inner",
        on="week_period",
    ).sort_values("week_period")
    if merged.empty:
        return (
            pd.DataFrame(columns=WEEKLY_SERIES_COLUMNS),
            normalization_issues.reset_index(drop=True),
        )

    merged["ticker"] = ticker
    merged["as_of_date"] = (
        merged[["stock_week_date", "gold_week_date"]]
        .min(axis=1)
        .dt.date
    )
    merged["stock_weekly_log_return"] = np.log(
        merged["stock_basis_usd"] / merged["stock_basis_usd"].shift(1)
    )
    merged["gold_weekly_log_return"] = np.log(
        merged["gold_basis_usd"] / merged["gold_basis_usd"].shift(1)
    )
    merged = merged.loc[
        merged["stock_weekly_log_return"].notna()
        & merged["gold_weekly_log_return"].notna()
    ].copy()
    if merged.empty:
        return (
            pd.DataFrame(columns=WEEKLY_SERIES_COLUMNS),
            normalization_issues.reset_index(drop=True),
        )

    merged = merged[WEEKLY_SERIES_COLUMNS].reset_index(drop=True)
    return merged, normalization_issues.reset_index(drop=True)


def compute_structural_window_metrics(
    *,
    weekly_series: pd.DataFrame,
    normalization_issues: pd.DataFrame,
    scoring_config: ScoringConfig,
) -> pd.DataFrame:
    if weekly_series.empty:
        return pd.DataFrame(columns=STRUCTURAL_WINDOW_COLUMNS)

    ticker = str(weekly_series["ticker"].iloc[0]).upper()
    series = weekly_series.copy()
    series["_as_of_timestamp"] = pd.to_datetime(series["as_of_date"])
    series = series.sort_values("_as_of_timestamp").reset_index(drop=True)
    as_of_dates = pd.DatetimeIndex(series["_as_of_timestamp"].drop_duplicates().to_numpy())
    ordered_dates = series["_as_of_timestamp"].to_numpy(dtype="datetime64[ns]")
    x_values = pd.to_numeric(series["gold_weekly_log_return"], errors="coerce").to_numpy(
        dtype=float
    )
    y_values = pd.to_numeric(series["stock_weekly_log_return"], errors="coerce").to_numpy(
        dtype=float
    )
    full_prefix = _build_regression_prefix_sums(
        x_values=x_values,
        y_values=y_values,
        raw_mask=np.ones(len(series.index), dtype=bool),
    )
    up_raw_mask = x_values > 0
    down_raw_mask = x_values < 0
    up_count_prefix = _prefix_count(up_raw_mask)
    down_count_prefix = _prefix_count(down_raw_mask)
    up_prefix = _build_regression_prefix_sums(
        x_values=x_values,
        y_values=y_values,
        raw_mask=up_raw_mask,
    )
    down_prefix = _build_regression_prefix_sums(
        x_values=x_values,
        y_values=y_values,
        raw_mask=down_raw_mask,
    )
    window_data_by_id = {
        window_id: _build_vectorized_window_data(
            as_of_dates=as_of_dates,
            ordered_dates=ordered_dates,
            window_id=window_id,
            full_prefix=full_prefix,
            up_prefix=up_prefix,
            down_prefix=down_prefix,
            up_count_prefix=up_count_prefix,
            down_count_prefix=down_count_prefix,
        )
        for window_id in scoring_config.structural_windows
    }
    minimum_observations_by_window = {
        window_id: scoring_config.confidence_thresholds.minimum_observations_for_window(
            window_id
        )
        for window_id in scoring_config.structural_windows
    }
    minimum_regime_observations_by_window = {
        window_id: scoring_config.confidence_thresholds.minimum_regime_observations_for_window(
            window_id
        )
        for window_id in scoring_config.structural_windows
    }
    issue_summaries = _summarize_normalization_issues_by_as_of(
        normalization_issues=normalization_issues,
        as_of_dates=as_of_dates,
    )

    rows: list[dict[str, object]] = []
    for position, as_of_timestamp in enumerate(as_of_dates):
        as_of_date = pd.Timestamp(as_of_timestamp)
        for window_id in scoring_config.structural_windows:
            rows.append(
                _compute_vectorized_window_metric(
                    ticker=ticker,
                    as_of_date=as_of_date,
                    window_id=window_id,
                    position=position,
                    window_data=window_data_by_id[window_id],
                    x_values=x_values,
                    y_values=y_values,
                    up_raw_mask=up_raw_mask,
                    down_raw_mask=down_raw_mask,
                    issue_summary=issue_summaries[position],
                    minimum_observations=minimum_observations_by_window[window_id],
                    minimum_regime_observations=minimum_regime_observations_by_window[
                        window_id
                    ],
                )
            )
    return pd.DataFrame(rows, columns=STRUCTURAL_WINDOW_COLUMNS)


def _compute_vectorized_window_metric(
    *,
    ticker: str,
    as_of_date: pd.Timestamp,
    window_id: str,
    position: int,
    window_data: _VectorizedWindowData,
    x_values: np.ndarray,
    y_values: np.ndarray,
    up_raw_mask: np.ndarray,
    down_raw_mask: np.ndarray,
    issue_summary: str | None,
    minimum_observations: int,
    minimum_regime_observations: int,
) -> dict[str, object]:
    week_count = int(window_data.raw_count[position])
    if week_count < 2:
        return _empty_window_metric(
            ticker=ticker,
            as_of_date=as_of_date,
            window_id=window_id,
            week_count=week_count,
            window_reason="INSUFFICIENT_HISTORY",
            issue_summary=issue_summary,
        )

    regression = _ols_metric_at(
        window_data.full_sums,
        position,
        x_values=x_values,
        y_values=y_values,
        start_idx=window_data.start_idx,
        end_idx=window_data.end_idx,
    )
    if regression is None:
        return _empty_window_metric(
            ticker=ticker,
            as_of_date=as_of_date,
            window_id=window_id,
            week_count=week_count,
            window_reason="MISSING_GOLD_VARIANCE",
            issue_summary=issue_summary,
        )

    up_week_count = int(window_data.up_count[position])
    down_week_count = int(window_data.down_count[position])
    up_regression = (
        _ols_metric_at(
            window_data.up_sums,
            position,
            x_values=x_values,
            y_values=y_values,
            start_idx=window_data.start_idx,
            end_idx=window_data.end_idx,
            raw_mask=up_raw_mask,
        )
        if up_week_count >= minimum_regime_observations
        else None
    )
    down_regression = (
        _ols_metric_at(
            window_data.down_sums,
            position,
            x_values=x_values,
            y_values=y_values,
            start_idx=window_data.start_idx,
            end_idx=window_data.end_idx,
            raw_mask=down_raw_mask,
        )
        if down_week_count >= minimum_regime_observations
        else None
    )

    window_status = "ELIGIBLE" if week_count >= minimum_observations else "LOW_OBSERVATION"
    window_reason = "OK" if window_status == "ELIGIBLE" else "INSUFFICIENT_OBSERVATIONS"
    up_beta = None if up_regression is None else up_regression.beta
    down_beta = None if down_regression is None else down_regression.beta
    gamma_value = (
        None
        if up_beta is None or down_beta is None
        else float(down_beta - up_beta)
    )
    asymmetry_ratio = (
        None
        if up_beta is None or down_beta is None or abs(down_beta) < 1e-9
        else float(up_beta / down_beta)
    )

    return {
        "ticker": ticker,
        "as_of_date": as_of_date.date(),
        "window_id": window_id,
        "week_count": week_count,
        "window_status": window_status,
        "window_reason": window_reason,
        "structural_delta": regression.beta,
        "intercept_alpha": regression.alpha,
        "r_squared": regression.r_squared,
        "up_week_count": up_week_count,
        "down_week_count": down_week_count,
        "up_beta": up_beta,
        "down_beta": down_beta,
        "gamma_value": gamma_value,
        "asymmetry_ratio": asymmetry_ratio,
        "normalization_issue_summary": issue_summary,
    }


def _build_vectorized_window_data(
    *,
    as_of_dates: pd.DatetimeIndex,
    ordered_dates: np.ndarray,
    window_id: str,
    full_prefix: _RegressionPrefixSums,
    up_prefix: _RegressionPrefixSums,
    down_prefix: _RegressionPrefixSums,
    up_count_prefix: np.ndarray,
    down_count_prefix: np.ndarray,
) -> _VectorizedWindowData:
    start_idx, end_idx = _window_bounds(
        as_of_dates=as_of_dates,
        ordered_dates=ordered_dates,
        window_id=window_id,
    )
    return _VectorizedWindowData(
        start_idx=start_idx,
        end_idx=end_idx,
        raw_count=(end_idx - start_idx).astype(np.int64),
        up_count=_window_prefix_delta(up_count_prefix, start_idx, end_idx).astype(np.int64),
        down_count=_window_prefix_delta(down_count_prefix, start_idx, end_idx).astype(
            np.int64
        ),
        full_sums=_window_regression_sums(full_prefix, start_idx, end_idx),
        up_sums=_window_regression_sums(up_prefix, start_idx, end_idx),
        down_sums=_window_regression_sums(down_prefix, start_idx, end_idx),
    )


def _window_bounds(
    *,
    as_of_dates: pd.DatetimeIndex,
    ordered_dates: np.ndarray,
    window_id: str,
) -> tuple[np.ndarray, np.ndarray]:
    trailing_starts = np.array(
        [
            _window_start(pd.Timestamp(as_of_date), window_id).to_datetime64()
            for as_of_date in as_of_dates
        ],
        dtype="datetime64[ns]",
    )
    as_of_values = as_of_dates.to_numpy(dtype="datetime64[ns]")
    start_idx = np.searchsorted(ordered_dates, trailing_starts, side="right")
    end_idx = np.searchsorted(ordered_dates, as_of_values, side="right")
    return start_idx.astype(np.int64), end_idx.astype(np.int64)


def _build_regression_prefix_sums(
    *,
    x_values: np.ndarray,
    y_values: np.ndarray,
    raw_mask: np.ndarray,
) -> _RegressionPrefixSums:
    valid_mask = raw_mask & np.isfinite(x_values) & np.isfinite(y_values)
    x = np.where(valid_mask, x_values, 0.0)
    y = np.where(valid_mask, y_values, 0.0)
    return _RegressionPrefixSums(
        n=_prefix_count(valid_mask),
        x=_prefix_sum(x),
        y=_prefix_sum(y),
        xy=_prefix_sum(x * y),
        xx=_prefix_sum(x * x),
        yy=_prefix_sum(y * y),
    )


def _window_regression_sums(
    prefix: _RegressionPrefixSums,
    start_idx: np.ndarray,
    end_idx: np.ndarray,
) -> _RegressionWindowSums:
    return _RegressionWindowSums(
        n=_window_prefix_delta(prefix.n, start_idx, end_idx),
        x=_window_prefix_delta(prefix.x, start_idx, end_idx),
        y=_window_prefix_delta(prefix.y, start_idx, end_idx),
        xy=_window_prefix_delta(prefix.xy, start_idx, end_idx),
        xx=_window_prefix_delta(prefix.xx, start_idx, end_idx),
        yy=_window_prefix_delta(prefix.yy, start_idx, end_idx),
    )


def _window_prefix_delta(
    prefix: np.ndarray,
    start_idx: np.ndarray,
    end_idx: np.ndarray,
) -> np.ndarray:
    return prefix[end_idx] - prefix[start_idx]


def _prefix_sum(values: np.ndarray) -> np.ndarray:
    return np.concatenate(([0.0], np.cumsum(values, dtype=float)))


def _prefix_count(mask: np.ndarray) -> np.ndarray:
    return np.concatenate(([0], np.cumsum(mask.astype(np.int64), dtype=np.int64)))


def _ols_metric_at(
    sums: _RegressionWindowSums,
    position: int,
    *,
    x_values: np.ndarray,
    y_values: np.ndarray,
    start_idx: np.ndarray,
    end_idx: np.ndarray,
    raw_mask: np.ndarray | None = None,
) -> _OlsMetric | None:
    n = int(sums.n[position])
    if n < 2:
        return None

    n_float = float(n)
    sx = float(sums.x[position])
    sy = float(sums.y[position])
    sxy = float(sums.xy[position])
    sxx = float(sums.xx[position])
    syy = float(sums.yy[position])
    sxx_centered = sxx - ((sx * sx) / n_float)
    sxy_centered = sxy - ((sx * sy) / n_float)
    syy_centered = syy - ((sy * sy) / n_float)
    if _needs_centered_window_fallback(
        centered_xx=sxx_centered,
        centered_yy=syy_centered,
        xx=sxx,
        yy=syy,
        sx=sx,
        sy=sy,
        n=n_float,
    ):
        return _ols_metric_from_raw_window(
            x_values=x_values,
            y_values=y_values,
            start_idx=int(start_idx[position]),
            end_idx=int(end_idx[position]),
            raw_mask=raw_mask,
        )
    if sxx_centered <= 0:
        return None

    beta = float(sxy_centered / sxx_centered)
    alpha = float((sy / n_float) - (beta * (sx / n_float)))
    if syy_centered <= 0:
        r_squared = 0.0
    else:
        residual_sum_squares = syy_centered - (beta * sxy_centered)
        r_squared = max(
            0.0,
            min(1.0, 1.0 - (residual_sum_squares / syy_centered)),
        )
    return _OlsMetric(alpha=alpha, beta=beta, r_squared=float(r_squared))


def _needs_centered_window_fallback(
    *,
    centered_xx: float,
    centered_yy: float,
    xx: float,
    yy: float,
    sx: float,
    sy: float,
    n: float,
) -> bool:
    raw_x_scale = max(abs(xx), abs((sx * sx) / n), 1e-300)
    raw_y_scale = max(abs(yy), abs((sy * sy) / n), 1e-300)
    return (
        abs(centered_xx) <= (_CENTERED_SUM_FALLBACK_REL_TOL * raw_x_scale)
        or abs(centered_yy) <= (_CENTERED_SUM_FALLBACK_REL_TOL * raw_y_scale)
    )


def _ols_metric_from_raw_window(
    *,
    x_values: np.ndarray,
    y_values: np.ndarray,
    start_idx: int,
    end_idx: int,
    raw_mask: np.ndarray | None,
) -> _OlsMetric | None:
    x_window = x_values[start_idx:end_idx]
    y_window = y_values[start_idx:end_idx]
    if raw_mask is not None:
        mask = raw_mask[start_idx:end_idx]
        x_window = x_window[mask]
        y_window = y_window[mask]

    regression = compute_regression(pd.Series(x_window), pd.Series(y_window))
    if regression is None:
        return None
    return _OlsMetric(
        alpha=regression.alpha,
        beta=regression.beta,
        r_squared=regression.r_squared,
    )


def _summarize_normalization_issues_by_as_of(
    *,
    normalization_issues: pd.DataFrame,
    as_of_dates: pd.DatetimeIndex,
) -> list[str | None]:
    if normalization_issues.empty:
        return [None] * len(as_of_dates)

    issues = normalization_issues.copy()
    issues["date"] = pd.to_datetime(issues["date"])
    statuses = issues["normalization_status"].astype(str).str.upper()
    valid_mask = statuses.isin(VALID_NORMALIZATION_STATUSES) & statuses.ne("OK")
    issues = issues.loc[valid_mask].copy()
    if issues.empty:
        return [None] * len(as_of_dates)

    issues["normalization_status"] = statuses.loc[issues.index]
    issues = issues.sort_values("date").reset_index(drop=True)
    issue_dates = issues["date"].to_numpy(dtype="datetime64[ns]")
    issue_statuses = issues["normalization_status"].to_numpy(dtype=str)

    summaries: list[str | None] = []
    for as_of_date in as_of_dates:
        as_of_timestamp = pd.Timestamp(as_of_date)
        trailing_start = (as_of_timestamp - pd.DateOffset(years=3)).to_datetime64()
        as_of_value = as_of_timestamp.to_datetime64()
        start_idx = int(np.searchsorted(issue_dates, trailing_start, side="right"))
        end_idx = int(np.searchsorted(issue_dates, as_of_value, side="right"))
        if end_idx <= start_idx:
            summaries.append(None)
            continue
        statuses_in_window = sorted(set(issue_statuses[start_idx:end_idx]))
        summaries.append(",".join(statuses_in_window) if statuses_in_window else None)
    return summaries


def compute_window_metric(
    *,
    ticker: str,
    as_of_date: pd.Timestamp,
    window_id: str,
    window_rows: pd.DataFrame,
    issue_summary: str | None,
    scoring_config: ScoringConfig,
) -> dict[str, object]:
    """Compute full and regime-split Tool A betas for one trailing window.

    ``structural_delta`` is the OLS slope, with intercept, of weekly stock
    log-returns on weekly gold log-returns. ``up_beta`` and ``down_beta`` use
    the same OLS-with-intercept estimator on split samples where weekly gold
    returns are positive or negative. This is a descriptive conditional-beta
    split, not an Estrada/D-CAPM downside beta.
    """

    minimum_observations = scoring_config.confidence_thresholds.minimum_observations_for_window(
        window_id
    )
    week_count = int(len(window_rows.index))
    if week_count < 2:
        return _empty_window_metric(
            ticker=ticker,
            as_of_date=as_of_date,
            window_id=window_id,
            week_count=week_count,
            window_reason="INSUFFICIENT_HISTORY",
            issue_summary=issue_summary,
        )

    regression = compute_regression(
        x=window_rows["gold_weekly_log_return"],
        y=window_rows["stock_weekly_log_return"],
    )
    if regression is None:
        return _empty_window_metric(
            ticker=ticker,
            as_of_date=as_of_date,
            window_id=window_id,
            week_count=week_count,
            window_reason="MISSING_GOLD_VARIANCE",
            issue_summary=issue_summary,
        )

    up_rows = window_rows.loc[window_rows["gold_weekly_log_return"] > 0].copy()
    down_rows = window_rows.loc[window_rows["gold_weekly_log_return"] < 0].copy()
    up_week_count = int(len(up_rows.index))
    down_week_count = int(len(down_rows.index))
    minimum_regime_observations = (
        scoring_config.confidence_thresholds.minimum_regime_observations_for_window(window_id)
    )
    up_regression = (
        compute_regression(
            x=up_rows["gold_weekly_log_return"],
            y=up_rows["stock_weekly_log_return"],
        )
        if up_week_count >= minimum_regime_observations
        else None
    )
    down_regression = (
        compute_regression(
            x=down_rows["gold_weekly_log_return"],
            y=down_rows["stock_weekly_log_return"],
        )
        if down_week_count >= minimum_regime_observations
        else None
    )

    window_status = "ELIGIBLE" if week_count >= minimum_observations else "LOW_OBSERVATION"
    window_reason = "OK" if window_status == "ELIGIBLE" else "INSUFFICIENT_OBSERVATIONS"
    up_beta = None if up_regression is None else up_regression.beta
    down_beta = None if down_regression is None else down_regression.beta
    gamma_value = (
        None
        if up_beta is None or down_beta is None
        else float(down_beta - up_beta)
    )
    asymmetry_ratio = (
        None
        if up_beta is None or down_beta is None or abs(down_beta) < 1e-9
        else float(up_beta / down_beta)
    )

    return {
        "ticker": ticker,
        "as_of_date": as_of_date.date(),
        "window_id": window_id,
        "week_count": week_count,
        "window_status": window_status,
        "window_reason": window_reason,
        "structural_delta": regression.beta,
        "intercept_alpha": regression.alpha,
        "r_squared": regression.r_squared,
        "up_week_count": up_week_count,
        "down_week_count": down_week_count,
        "up_beta": up_beta,
        "down_beta": down_beta,
        "gamma_value": gamma_value,
        "asymmetry_ratio": asymmetry_ratio,
        "normalization_issue_summary": issue_summary,
    }


def compute_volatility_diagnostics(
    *,
    weekly_series: pd.DataFrame,
    structural_window_metrics: pd.DataFrame,
    scoring_config: ScoringConfig,
) -> pd.DataFrame:
    if weekly_series.empty:
        return pd.DataFrame(columns=VOLATILITY_DIAGNOSTIC_COLUMNS)

    weekly = weekly_series.copy()
    weekly["as_of_date"] = pd.to_datetime(weekly["as_of_date"]).dt.date
    grouped_weekly = {
        str(ticker).upper(): _prepare_volatility_weekly_arrays(frame)
        for ticker, frame in weekly.groupby("ticker", dropna=False)
    }

    metrics = structural_window_metrics.copy()
    if metrics.empty:
        return pd.DataFrame(columns=VOLATILITY_DIAGNOSTIC_COLUMNS)
    metrics["as_of_date"] = pd.to_datetime(metrics["as_of_date"]).dt.date

    rows: list[dict[str, object]] = []
    anchor_rows = _build_volatility_anchor_rows(
        metrics=metrics,
        scoring_config=scoring_config,
    )
    for anchor_row in anchor_rows:
        ordered = grouped_weekly.get(anchor_row.ticker)
        if ordered is None:
            continue
        as_of_timestamp = pd.Timestamp(anchor_row.as_of_date)
        trailing = _trailing_volatility_window(
            weekly_arrays=ordered,
            as_of_date=as_of_timestamp,
        )
        total_vol = _annualize_weekly_volatility_array(trailing.stock_returns)
        downside_vol = _annualize_downside_volatility_array(trailing.stock_returns)
        residual_vol = None
        alpha = _optional_float(anchor_row.intercept_alpha)
        beta = _optional_float(anchor_row.structural_delta)
        if alpha is not None and beta is not None:
            valid_mask = np.isfinite(trailing.gold_returns) & np.isfinite(
                trailing.stock_returns
            )
            if int(valid_mask.sum()) >= 2:
                residual_vol = _annualize_weekly_volatility_array(
                    trailing.stock_returns[valid_mask]
                    - (alpha + (beta * trailing.gold_returns[valid_mask]))
                )
        rows.append(
            {
                "ticker": anchor_row.ticker,
                "as_of_date": as_of_timestamp.date(),
                "volatility_anchor_window_id": anchor_row.anchor_window_id,
                "total_volatility_52w": total_vol,
                "residual_volatility_52w": residual_vol,
                "downside_volatility_52w": downside_vol,
            }
        )
    return pd.DataFrame(rows, columns=VOLATILITY_DIAGNOSTIC_COLUMNS)


def _build_volatility_anchor_rows(
    *,
    metrics: pd.DataFrame,
    scoring_config: ScoringConfig,
) -> list[_VolatilityAnchorRow]:
    if metrics.empty:
        return []

    working = metrics.copy()
    working["ticker_key"] = working["ticker"].astype(str).str.upper()
    working["window_key"] = working["window_id"].astype(str).str.upper()
    working["delta_numeric"] = pd.to_numeric(
        working["structural_delta"],
        errors="coerce",
    )
    key_columns = ["ticker_key", "as_of_date"]
    keys = (
        working[key_columns]
        .drop_duplicates()
        .sort_values(key_columns)
        .itertuples(index=False, name=None)
    )
    anchor_by_key: dict[tuple[str, object], str] = {}
    for require_eligible in (True, False):
        candidates = working.loc[working["delta_numeric"].notna()].copy()
        if require_eligible:
            candidates = candidates.loc[
                candidates["window_status"].astype(str).eq("ELIGIBLE")
            ].copy()
        if candidates.empty:
            continue
        for window_id in scoring_config.anchor_window_preference():
            window_rows = candidates.loc[candidates["window_key"].eq(window_id)]
            for row in window_rows[["ticker_key", "as_of_date"]].itertuples(
                index=False,
                name=None,
            ):
                anchor_by_key.setdefault((str(row[0]), row[1]), window_id)

    metric_lookup = {
        (str(row.ticker_key), row.as_of_date, str(row.window_key)): row
        for row in working.itertuples(index=False)
    }
    anchor_rows: list[_VolatilityAnchorRow] = []
    for ticker, as_of_date in keys:
        key = (str(ticker), as_of_date)
        anchor_window_id = anchor_by_key.get(key)
        anchor_metric = (
            metric_lookup.get((str(ticker), as_of_date, anchor_window_id))
            if anchor_window_id
            else None
        )
        anchor_rows.append(
            _VolatilityAnchorRow(
                ticker=str(ticker),
                as_of_date=as_of_date,
                anchor_window_id=anchor_window_id,
                intercept_alpha=(
                    None if anchor_metric is None else anchor_metric.intercept_alpha
                ),
                structural_delta=(
                    None if anchor_metric is None else anchor_metric.structural_delta
                ),
            )
        )
    return anchor_rows


def _prepare_volatility_weekly_arrays(frame: pd.DataFrame) -> _VolatilityWeeklyArrays:
    ordered = frame.sort_values("as_of_date").reset_index(drop=True)
    return _VolatilityWeeklyArrays(
        as_of_dates=pd.to_datetime(ordered["as_of_date"]).to_numpy(dtype="datetime64[ns]"),
        stock_returns=pd.to_numeric(
            ordered["stock_weekly_log_return"], errors="coerce"
        ).to_numpy(dtype=float),
        gold_returns=pd.to_numeric(
            ordered["gold_weekly_log_return"], errors="coerce"
        ).to_numpy(dtype=float),
    )


def _trailing_volatility_window(
    *,
    weekly_arrays: _VolatilityWeeklyArrays,
    as_of_date: pd.Timestamp,
) -> _VolatilityWindow:
    end_idx = int(
        np.searchsorted(
            weekly_arrays.as_of_dates,
            as_of_date.to_datetime64(),
            side="right",
        )
    )
    start_idx = max(0, end_idx - 52)
    return _VolatilityWindow(
        stock_returns=weekly_arrays.stock_returns[start_idx:end_idx],
        gold_returns=weekly_arrays.gold_returns[start_idx:end_idx],
    )


def choose_structural_anchor_window(
    *,
    window_metrics: pd.DataFrame,
    scoring_config: ScoringConfig,
    require_eligible: bool,
) -> str | None:
    if window_metrics.empty:
        return None
    candidates = window_metrics.copy()
    if require_eligible:
        candidates = candidates.loc[
            candidates["window_status"].astype(str).eq("ELIGIBLE")
        ].copy()
    candidates = candidates.loc[
        pd.to_numeric(candidates["structural_delta"], errors="coerce").notna()
    ].copy()
    if candidates.empty:
        return None
    candidate_ids = set(candidates["window_id"].astype(str).str.upper())
    for window_id in scoring_config.anchor_window_preference():
        if window_id in candidate_ids:
            return window_id
    return None


def build_trailing_window_rows(
    *,
    weekly_series: pd.DataFrame,
    as_of_date: pd.Timestamp,
    window_id: str,
) -> pd.DataFrame:
    series = weekly_series.copy()
    series["as_of_date"] = pd.to_datetime(series["as_of_date"])
    trailing_start = _window_start(as_of_date, window_id)
    mask = series["as_of_date"].gt(trailing_start) & series["as_of_date"].le(as_of_date)
    return series.loc[mask].copy()


def summarize_normalization_issues(
    *,
    normalization_issues: pd.DataFrame,
    as_of_date: pd.Timestamp,
) -> str | None:
    if normalization_issues.empty:
        return None
    issues = normalization_issues.copy()
    issues["date"] = pd.to_datetime(issues["date"])
    trailing_start = as_of_date - pd.DateOffset(years=3)
    recent = issues.loc[
        issues["date"].gt(trailing_start) & issues["date"].le(as_of_date)
    ].copy()
    if recent.empty:
        return None
    statuses = sorted(
        {
            status
            for status in recent["normalization_status"].astype(str).str.upper()
            if status in VALID_NORMALIZATION_STATUSES and status != "OK"
        }
    )
    return ",".join(statuses) if statuses else None


def annualize_weekly_volatility(values: Iterable[float]) -> float | None:
    values_array = pd.to_numeric(pd.Series(list(values)), errors="coerce").to_numpy(
        dtype=float
    )
    return _annualize_weekly_volatility_array(values_array)


def annualize_downside_volatility(values: Iterable[float]) -> float | None:
    values_array = pd.to_numeric(pd.Series(list(values)), errors="coerce").to_numpy(
        dtype=float
    )
    return _annualize_downside_volatility_array(values_array)


def _annualize_weekly_volatility_array(values: np.ndarray) -> float | None:
    numeric_values = np.asarray(values, dtype=float)
    numeric_values = numeric_values[~np.isnan(numeric_values)]
    if len(numeric_values) < 2:
        return None
    return float(np.std(numeric_values, ddof=1) * np.sqrt(52.0))


def _annualize_downside_volatility_array(values: np.ndarray) -> float | None:
    numeric_values = np.asarray(values, dtype=float)
    numeric_values = numeric_values[~np.isnan(numeric_values)]
    downside_values = numeric_values[numeric_values < 0]
    if len(downside_values) < 2:
        return None
    return float(np.std(downside_values, ddof=1) * np.sqrt(52.0))


def compute_regression(x: pd.Series, y: pd.Series) -> RegressionResult | None:
    """Return the ordinary least-squares line ``y = alpha + beta * x``.

    The estimator includes an intercept by centering both series before
    computing the slope. Tool A's full, up-week, and down-week beta metrics all
    use this same OLS-with-intercept regression.
    """

    x_values = pd.to_numeric(x, errors="coerce").to_numpy(dtype=float)
    y_values = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    valid_mask = np.isfinite(x_values) & np.isfinite(y_values)
    x_values = x_values[valid_mask]
    y_values = y_values[valid_mask]
    if len(x_values) < 2:
        return None

    x_mean = float(np.mean(x_values))
    y_mean = float(np.mean(y_values))
    centered_x = x_values - x_mean
    centered_y = y_values - y_mean
    denominator = float(np.sum(centered_x**2))
    if denominator <= 0:
        return None

    beta = float(np.sum(centered_x * centered_y) / denominator)
    alpha = float(y_mean - (beta * x_mean))
    fitted = alpha + (beta * x_values)
    residuals = y_values - fitted
    total_sum_squares = float(np.sum((y_values - y_mean) ** 2))
    if total_sum_squares <= 0:
        r_squared = 0.0
    else:
        residual_sum_squares = float(np.sum(residuals**2))
        r_squared = max(0.0, min(1.0, 1.0 - (residual_sum_squares / total_sum_squares)))

    return RegressionResult(
        alpha=alpha,
        beta=beta,
        r_squared=r_squared,
        residuals=residuals,
    )


def weighted_median(
    values: dict[str, float | None],
    *,
    weights: dict[str, float],
) -> float | None:
    usable = [
        (float(value), float(weights.get(key, 1.0)))
        for key, value in values.items()
        if value is not None and pd.notna(value)
    ]
    if not usable:
        return None
    usable.sort(key=lambda item: item[0])
    total_weight = sum(weight for _, weight in usable)
    cutoff = total_weight / 2.0
    running = 0.0
    for value, weight in usable:
        running += weight
        if running >= cutoff:
            return float(value)
    return float(usable[-1][0])


def _last_trading_day_per_week(
    *,
    frame: pd.DataFrame,
    basis_column: str,
    value_label: str,
) -> pd.DataFrame:
    weekly = frame.copy()
    weekly["date"] = pd.to_datetime(weekly["date"])
    weekly["week_period"] = weekly["date"].dt.to_period("W-FRI")
    weekly = weekly.sort_values("date")
    if weekly.empty:
        return pd.DataFrame(
            columns=["week_period", f"{value_label}_week_date", f"{value_label}_basis_usd"]
        )

    latest_date = pd.Timestamp(weekly["date"].max())
    latest_period = weekly["week_period"].max()
    latest_period_end = latest_period.end_time.normalize()
    if latest_period_end.date() > latest_date.date():
        weekly = weekly.loc[weekly["week_period"].ne(latest_period)].copy()
    if weekly.empty:
        return pd.DataFrame(
            columns=["week_period", f"{value_label}_week_date", f"{value_label}_basis_usd"]
        )

    weekly = weekly.groupby("week_period", as_index=False).tail(1).copy()
    return weekly.rename(
        columns={
            "date": f"{value_label}_week_date",
            basis_column: f"{value_label}_basis_usd",
        }
    )[
        [
            "week_period",
            f"{value_label}_week_date",
            f"{value_label}_basis_usd",
        ]
    ].reset_index(drop=True)


def _window_start(as_of_date: pd.Timestamp, window_id: str) -> pd.Timestamp:
    normalized = str(window_id).strip().upper()
    if normalized.endswith("M"):
        return as_of_date - pd.DateOffset(months=int(normalized[:-1]))
    if normalized.endswith("Y"):
        return as_of_date - pd.DateOffset(years=int(normalized[:-1]))
    raise ValueError(f"Unsupported structural window: {window_id}")


def _empty_window_metric(
    *,
    ticker: str,
    as_of_date: pd.Timestamp,
    window_id: str,
    week_count: int,
    window_reason: str,
    issue_summary: str | None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "as_of_date": as_of_date.date(),
        "window_id": window_id,
        "week_count": week_count,
        "window_status": "INELIGIBLE",
        "window_reason": window_reason,
        "structural_delta": None,
        "intercept_alpha": None,
        "r_squared": None,
        "up_week_count": 0,
        "down_week_count": 0,
        "up_beta": None,
        "down_beta": None,
        "gamma_value": None,
        "asymmetry_ratio": None,
        "normalization_issue_summary": issue_summary,
    }
