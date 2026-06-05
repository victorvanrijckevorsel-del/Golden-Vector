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
    as_of_dates = list(pd.to_datetime(weekly_series["as_of_date"]).sort_values().unique())
    rows: list[dict[str, object]] = []
    for as_of_timestamp in as_of_dates:
        as_of_date = pd.Timestamp(as_of_timestamp)
        issue_summary = summarize_normalization_issues(
            normalization_issues=normalization_issues,
            as_of_date=as_of_date,
        )
        for window_id in scoring_config.structural_windows:
            window_rows = build_trailing_window_rows(
                weekly_series=weekly_series,
                as_of_date=as_of_date,
                window_id=window_id,
            )
            rows.append(
                compute_window_metric(
                    ticker=ticker,
                    as_of_date=as_of_date,
                    window_id=window_id,
                    window_rows=window_rows,
                    issue_summary=issue_summary,
                    scoring_config=scoring_config,
                )
            )
    return pd.DataFrame(rows, columns=STRUCTURAL_WINDOW_COLUMNS)


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
        str(ticker).upper(): frame.sort_values("as_of_date").reset_index(drop=True)
        for ticker, frame in weekly.groupby("ticker", dropna=False)
    }

    metrics = structural_window_metrics.copy()
    if metrics.empty:
        return pd.DataFrame(columns=VOLATILITY_DIAGNOSTIC_COLUMNS)
    metrics["as_of_date"] = pd.to_datetime(metrics["as_of_date"]).dt.date

    rows: list[dict[str, object]] = []
    for (ticker, as_of_date), metric_frame in metrics.groupby(["ticker", "as_of_date"], dropna=False):
        normalized_ticker = str(ticker).upper()
        ordered = grouped_weekly.get(normalized_ticker, pd.DataFrame())
        if ordered.empty:
            continue
        as_of_timestamp = pd.Timestamp(as_of_date)
        trailing = ordered.loc[
            pd.to_datetime(ordered["as_of_date"]).le(as_of_timestamp)
        ].tail(52)
        anchor_window_id = choose_structural_anchor_window(
            window_metrics=metric_frame,
            scoring_config=scoring_config,
            require_eligible=True,
        ) or choose_structural_anchor_window(
            window_metrics=metric_frame,
            scoring_config=scoring_config,
            require_eligible=False,
        )
        anchor_metric = (
            metric_frame.loc[metric_frame["window_id"].astype(str).eq(anchor_window_id)].iloc[0]
            if anchor_window_id
            and not metric_frame.loc[metric_frame["window_id"].astype(str).eq(anchor_window_id)].empty
            else None
        )
        total_vol = annualize_weekly_volatility(trailing["stock_weekly_log_return"])
        downside_vol = annualize_downside_volatility(trailing["stock_weekly_log_return"])
        residual_vol = None
        if anchor_metric is not None:
            alpha = _optional_float(anchor_metric.get("intercept_alpha"))
            beta = _optional_float(anchor_metric.get("structural_delta"))
            if alpha is not None and beta is not None:
                x_values = pd.to_numeric(
                    trailing["gold_weekly_log_return"], errors="coerce"
                ).to_numpy(dtype=float)
                y_values = pd.to_numeric(
                    trailing["stock_weekly_log_return"], errors="coerce"
                ).to_numpy(dtype=float)
                valid_mask = np.isfinite(x_values) & np.isfinite(y_values)
                x_values = x_values[valid_mask]
                y_values = y_values[valid_mask]
                if len(x_values) >= 2:
                    residual_vol = annualize_weekly_volatility(
                        y_values - (alpha + (beta * x_values))
                    )
        rows.append(
            {
                "ticker": normalized_ticker,
                "as_of_date": as_of_timestamp.date(),
                "volatility_anchor_window_id": anchor_window_id,
                "total_volatility_52w": total_vol,
                "residual_volatility_52w": residual_vol,
                "downside_volatility_52w": downside_vol,
            }
        )
    return pd.DataFrame(rows, columns=VOLATILITY_DIAGNOSTIC_COLUMNS)


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
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    if len(series.index) < 2:
        return None
    return float(series.std(ddof=1) * np.sqrt(52.0))


def annualize_downside_volatility(values: Iterable[float]) -> float | None:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    downside = series.loc[series < 0]
    if len(downside.index) < 2:
        return None
    return float(downside.std(ddof=1) * np.sqrt(52.0))


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
