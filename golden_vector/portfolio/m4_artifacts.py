"""M4 portfolio hedge, chart, and reconciliation-export artifact builders."""

from __future__ import annotations

import math

import pandas as pd

from golden_vector.common.numeric import optional_float, sum_optional_floats
from golden_vector.common.options import OPTION_CONTRACT_MULTIPLIER
from golden_vector.model.gold_shock import (
    DEFAULT_GOLD_DOWN_MIN_BETA,
    DEFAULT_GOLD_DOWN_SCENARIO_FRACTION,
    compute_gold_shock_exposure,
)
from golden_vector.portfolio.models import PORTFOLIO_SCHEMA_VERSION

GDX_BASIS_RISK_NOTE = (
    "GDX/GDXJ are sector proxies. They can under-cover high-beta small-caps; "
    "this is a modeled hedge size, not a recommendation."
)

HEDGE_SIZING_COLUMNS = [
    "schema_version",
    "source_run_id",
    "snapshot_refresh_run_id",
    "benchmark_ticker",
    "benchmark_label",
    "benchmark_status",
    "benchmark_status_reason",
    "benchmark_price_usd",
    "benchmark_price_date",
    "benchmark_down_beta",
    "effective_gold_exposure_usd",
    "modeled_short_notional_usd",
    "modeled_put_contracts",
    "contract_multiplier",
    "hedge_status",
    "hedge_status_reason",
    "basis_risk_note",
]

CORRELATION_COLUMNS = [
    "schema_version",
    "source_run_id",
    "snapshot_refresh_run_id",
    "row_ticker",
    "column_ticker",
    "correlation",
    "overlap_days",
    "row_nav_weight_fraction",
    "column_nav_weight_fraction",
    "pair_exposure_fraction",
    "pair_rank",
    "correlation_heat_bucket",
    "correlation_status",
    "correlation_status_reason",
]

VALUE_HISTORY_COLUMNS = [
    "schema_version",
    "source_run_id",
    "snapshot_refresh_run_id",
    "date",
    "covered_market_value_usd",
    "covered_position_count",
    "covered_book_weight_fraction",
    "chart_x",
    "chart_y",
    "history_status",
]

RECONCILIATION_EXPORT_COLUMNS = [
    "schema_version",
    "source_run_id",
    "snapshot_refresh_run_id",
    "lot_id",
    "ticker",
    "company",
    "buy_date",
    "shares",
    "buy_price",
    "buy_currency",
    "cost_local",
    "current_price_local",
    "value_local",
    "pnl_local",
    "pnl_fraction_local",
    "canonical_total_shares",
    "canonical_avg_cost_local",
    "canonical_value_local",
    "canonical_value_usd",
    "canonical_pnl_local",
    "position_status",
]


def build_m4_portfolio_artifacts(
    *,
    positions: pd.DataFrame,
    lines: pd.DataFrame,
    summary: pd.DataFrame,
    benchmark_betas: pd.DataFrame,
    normalized_equity_histories: dict[str, pd.DataFrame],
    source_run_id: str,
    snapshot_refresh_run_id: str,
    gold_down_min_beta: float = DEFAULT_GOLD_DOWN_MIN_BETA,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    hedge = build_hedge_sizing_frame(
        positions=positions,
        benchmark_betas=benchmark_betas,
        source_run_id=source_run_id,
        snapshot_refresh_run_id=snapshot_refresh_run_id,
        gold_down_min_beta=gold_down_min_beta,
    )
    correlations = build_correlation_frame(
        positions=positions,
        normalized_equity_histories=normalized_equity_histories,
        source_run_id=source_run_id,
        snapshot_refresh_run_id=snapshot_refresh_run_id,
    )
    value_history = build_value_history_frame(
        positions=positions,
        normalized_equity_histories=normalized_equity_histories,
        summary=summary,
        source_run_id=source_run_id,
        snapshot_refresh_run_id=snapshot_refresh_run_id,
    )
    reconciliation_export = build_reconciliation_export_frame(
        lines=lines,
        positions=positions,
        source_run_id=source_run_id,
        snapshot_refresh_run_id=snapshot_refresh_run_id,
    )
    return hedge, correlations, value_history, reconciliation_export


def build_hedge_sizing_frame(
    *,
    positions: pd.DataFrame,
    benchmark_betas: pd.DataFrame,
    source_run_id: str,
    snapshot_refresh_run_id: str,
    gold_down_min_beta: float = DEFAULT_GOLD_DOWN_MIN_BETA,
) -> pd.DataFrame:
    effective_exposure = _effective_gold_exposure_usd(
        positions,
        gold_down_min_beta=gold_down_min_beta,
    )
    rows = []
    for row in benchmark_betas.to_dict(orient="records"):
        status = str(row.get("benchmark_status") or "")
        beta = optional_float(row.get("down_beta_core"))
        price = optional_float(row.get("benchmark_price_usd"))
        reason = row.get("benchmark_status_reason")
        hedge_status = "OK"
        hedge_reason = None
        notional = None
        contracts = None
        if effective_exposure <= 0:
            hedge_status = "NO_MEASURED_EXPOSURE"
            hedge_reason = "No measured gold exposure to hedge."
        elif status != "OK":
            hedge_status = "UNAVAILABLE"
            hedge_reason = reason or f"Benchmark status is {status or 'UNKNOWN'}."
        elif beta is None or beta <= 0:
            hedge_status = "UNAVAILABLE"
            hedge_reason = "Benchmark gold-down beta is unavailable."
        elif price is None or price <= 0:
            hedge_status = "UNAVAILABLE"
            hedge_reason = "Benchmark price is unavailable."
        else:
            notional = effective_exposure / beta
            contracts = math.ceil(notional / (price * OPTION_CONTRACT_MULTIPLIER))
        rows.append(
            {
                "schema_version": PORTFOLIO_SCHEMA_VERSION,
                "source_run_id": source_run_id,
                "snapshot_refresh_run_id": snapshot_refresh_run_id,
                "benchmark_ticker": row.get("benchmark_ticker"),
                "benchmark_label": row.get("benchmark_label"),
                "benchmark_status": status,
                "benchmark_status_reason": reason,
                "benchmark_price_usd": price,
                "benchmark_price_date": row.get("benchmark_price_date"),
                "benchmark_down_beta": beta,
                "effective_gold_exposure_usd": effective_exposure,
                "modeled_short_notional_usd": notional,
                "modeled_put_contracts": contracts,
                "contract_multiplier": OPTION_CONTRACT_MULTIPLIER,
                "hedge_status": hedge_status,
                "hedge_status_reason": hedge_reason,
                "basis_risk_note": GDX_BASIS_RISK_NOTE,
            }
        )
    return _with_metadata(
        pd.DataFrame(rows, columns=HEDGE_SIZING_COLUMNS),
        source_run_id,
        snapshot_refresh_run_id,
    )


def build_correlation_frame(
    *,
    positions: pd.DataFrame,
    normalized_equity_histories: dict[str, pd.DataFrame],
    source_run_id: str,
    snapshot_refresh_run_id: str,
) -> pd.DataFrame:
    covered = _covered_positions(positions)
    returns_by_ticker = {
        ticker: _daily_return_series(normalized_equity_histories.get(ticker, pd.DataFrame()))
        for ticker in covered["ticker"].astype(str).tolist()
    }
    weights = {
        str(row.get("ticker") or "").upper(): optional_float(row.get("nav_weight_fraction"))
        for row in covered.to_dict(orient="records")
    }
    rows = []
    for left in weights:
        for right in weights:
            correlation, overlap = _pair_correlation(
                returns_by_ticker.get(left),
                returns_by_ticker.get(right),
            )
            status, reason = _correlation_status(correlation, overlap)
            pair_exposure = (weights.get(left) or 0.0) + (weights.get(right) or 0.0)
            rows.append(
                {
                    "schema_version": PORTFOLIO_SCHEMA_VERSION,
                    "source_run_id": source_run_id,
                    "snapshot_refresh_run_id": snapshot_refresh_run_id,
                    "row_ticker": left,
                    "column_ticker": right,
                    "correlation": correlation,
                    "overlap_days": overlap,
                    "row_nav_weight_fraction": weights.get(left),
                    "column_nav_weight_fraction": weights.get(right),
                    "pair_exposure_fraction": None if left == right else pair_exposure,
                    "pair_rank": None,
                    "correlation_heat_bucket": _correlation_heat_bucket(correlation),
                    "correlation_status": status,
                    "correlation_status_reason": reason,
                }
            )
    frame = pd.DataFrame(rows, columns=CORRELATION_COLUMNS)
    if not frame.empty:
        off_diagonal = frame["row_ticker"].astype(str) < frame["column_ticker"].astype(str)
        ranked = frame.loc[off_diagonal].sort_values(
            ["pair_exposure_fraction", "row_ticker", "column_ticker"],
            ascending=[False, True, True],
        )
        for rank, index in enumerate(ranked.index, start=1):
            frame.loc[index, "pair_rank"] = rank
    return _with_metadata(frame, source_run_id, snapshot_refresh_run_id)


def build_value_history_frame(
    *,
    positions: pd.DataFrame,
    normalized_equity_histories: dict[str, pd.DataFrame],
    summary: pd.DataFrame,
    source_run_id: str,
    snapshot_refresh_run_id: str,
) -> pd.DataFrame:
    covered = _covered_positions(positions)
    if covered.empty:
        return _with_metadata(
            pd.DataFrame(columns=VALUE_HISTORY_COLUMNS),
            source_run_id,
            snapshot_refresh_run_id,
        )
    total_nav = optional_float(summary.iloc[0].get("nav_value_usd")) if not summary.empty else None
    value_frames = []
    included_weights = []
    for row in covered.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "").upper()
        shares = optional_float(row.get("total_shares"))
        history = normalized_equity_histories.get(ticker, pd.DataFrame())
        if shares is None or shares <= 0 or history.empty or "close_usd" not in history.columns:
            continue
        series = history[["date", "close_usd"]].copy()
        series["date"] = pd.to_datetime(series["date"], errors="coerce")
        series["position_value_usd"] = pd.to_numeric(series["close_usd"], errors="coerce") * shares
        series = series.dropna(subset=["date", "position_value_usd"])
        if series.empty:
            continue
        series["ticker"] = ticker
        value_frames.append(series[["date", "ticker", "position_value_usd"]])
        included_weights.append(optional_float(row.get("nav_weight_fraction")))
    if not value_frames:
        return _with_metadata(
            pd.DataFrame(columns=VALUE_HISTORY_COLUMNS),
            source_run_id,
            snapshot_refresh_run_id,
        )
    combined = pd.concat(value_frames, ignore_index=True)
    pivoted = combined.pivot_table(
        index="date",
        columns="ticker",
        values="position_value_usd",
        aggfunc="last",
    ).dropna(how="any")
    if pivoted.empty:
        return _with_metadata(
            pd.DataFrame(columns=VALUE_HISTORY_COLUMNS),
            source_run_id,
            snapshot_refresh_run_id,
        )
    grouped = pivoted.sum(axis=1).rename("covered_market_value_usd").reset_index()
    grouped["schema_version"] = PORTFOLIO_SCHEMA_VERSION
    grouped["source_run_id"] = source_run_id
    grouped["snapshot_refresh_run_id"] = snapshot_refresh_run_id
    grouped["covered_position_count"] = len(value_frames)
    covered_weight = sum_optional_floats(included_weights) or 0.0
    grouped["covered_book_weight_fraction"] = covered_weight if total_nav and total_nav > 0 else None
    grouped = _with_chart_coordinates(grouped, value_column="covered_market_value_usd")
    grouped["history_status"] = "OK"
    grouped["date"] = grouped["date"].dt.date
    return _with_metadata(
        grouped[VALUE_HISTORY_COLUMNS],
        source_run_id,
        snapshot_refresh_run_id,
    )


def build_reconciliation_export_frame(
    *,
    lines: pd.DataFrame,
    positions: pd.DataFrame,
    source_run_id: str,
    snapshot_refresh_run_id: str,
) -> pd.DataFrame:
    if lines.empty:
        return _with_metadata(
            pd.DataFrame(columns=RECONCILIATION_EXPORT_COLUMNS),
            source_run_id,
            snapshot_refresh_run_id,
        )
    position_columns = [
        "ticker",
        "total_shares",
        "avg_cost_local",
        "value_local",
        "value_usd",
        "pnl_local",
        "position_status",
    ]
    joined = lines.merge(
        positions[position_columns],
        on="ticker",
        how="left",
        suffixes=("", "_position"),
    )
    joined["schema_version"] = PORTFOLIO_SCHEMA_VERSION
    joined["source_run_id"] = source_run_id
    joined["snapshot_refresh_run_id"] = snapshot_refresh_run_id
    joined = joined.rename(
        columns={
            "total_shares": "canonical_total_shares",
            "avg_cost_local": "canonical_avg_cost_local",
            "value_local_position": "canonical_value_local",
            "value_usd_position": "canonical_value_usd",
            "pnl_local_position": "canonical_pnl_local",
        }
    )
    return _with_metadata(
        joined[RECONCILIATION_EXPORT_COLUMNS],
        source_run_id,
        snapshot_refresh_run_id,
    )


def _effective_gold_exposure_usd(
    positions: pd.DataFrame,
    *,
    gold_down_min_beta: float,
) -> float:
    total = 0.0
    for row in _covered_positions(positions).to_dict(orient="records"):
        shock = compute_gold_shock_exposure(
            value_usd=row.get("value_usd"),
            beta=row.get("down_beta_core"),
            shock_fraction=DEFAULT_GOLD_DOWN_SCENARIO_FRACTION,
            min_effective_beta=gold_down_min_beta,
        )
        total += shock.effective_exposure_usd or 0.0
    return total


def _covered_positions(positions: pd.DataFrame) -> pd.DataFrame:
    if positions.empty or "effective_exposure_bucket" not in positions.columns:
        return pd.DataFrame(columns=positions.columns)
    return positions.loc[positions["effective_exposure_bucket"].eq("Measured beta")].copy()


def _daily_return_series(history: pd.DataFrame | None) -> pd.Series:
    if history is None or history.empty or "date" not in history.columns:
        return pd.Series(dtype="float64")
    price_column = "return_basis_usd" if "return_basis_usd" in history.columns else "close_usd"
    if price_column not in history.columns:
        return pd.Series(dtype="float64")
    working = history[["date", price_column]].copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    working = working.dropna(subset=["date"]).sort_values("date")
    prices = pd.to_numeric(working[price_column], errors="coerce")
    returns = prices.pct_change()
    returns.index = working["date"]
    return returns.dropna()


def _pair_correlation(
    left: pd.Series | None,
    right: pd.Series | None,
) -> tuple[float | None, int]:
    if left is None or right is None or left.empty or right.empty:
        return None, 0
    joined = pd.concat([left.rename("left"), right.rename("right")], axis=1).dropna()
    overlap = len(joined.index)
    if overlap < 30:
        return None, overlap
    if joined["left"].std() == 0 or joined["right"].std() == 0:
        return None, overlap
    value = joined["left"].corr(joined["right"])
    return (float(value) if pd.notna(value) else None), overlap


def _correlation_status(correlation: float | None, overlap: int) -> tuple[str, str | None]:
    if overlap < 30:
        return "INSUFFICIENT_HISTORY", "Fewer than 30 overlapping return observations."
    if correlation is None:
        return "UNAVAILABLE", "Correlation could not be estimated."
    return "OK", None


def _correlation_heat_bucket(correlation: float | None) -> str:
    if correlation is None:
        return "unavailable"
    if correlation >= 0.8:
        return "very-high"
    if correlation >= 0.6:
        return "high"
    if correlation >= 0.3:
        return "medium"
    return "low"


def _with_chart_coordinates(frame: pd.DataFrame, *, value_column: str) -> pd.DataFrame:
    """Attach small SVG-ready coordinates so the UI only renders artifact data."""

    working = frame.sort_values("date").reset_index(drop=True).copy()
    if working.empty:
        working["chart_x"] = []
        working["chart_y"] = []
        return working
    values = pd.to_numeric(working[value_column], errors="coerce")
    count = len(working.index)
    if count == 1:
        working["chart_x"] = 50.0
    else:
        working["chart_x"] = [round(index * 100.0 / (count - 1), 4) for index in range(count)]
    minimum = float(values.min()) if values.notna().any() else 0.0
    maximum = float(values.max()) if values.notna().any() else 0.0
    span = maximum - minimum
    if span <= 0:
        working["chart_y"] = 20.0
    else:
        working["chart_y"] = [
            round(40.0 - ((float(value) - minimum) / span * 40.0), 4)
            if pd.notna(value)
            else 20.0
            for value in values
        ]
    return working


def _with_metadata(
    frame: pd.DataFrame,
    source_run_id: str,
    snapshot_refresh_run_id: str,
) -> pd.DataFrame:
    frame.attrs["schema_version"] = PORTFOLIO_SCHEMA_VERSION
    frame.attrs["source_run_id"] = source_run_id
    frame.attrs["snapshot_refresh_run_id"] = snapshot_refresh_run_id
    return frame
