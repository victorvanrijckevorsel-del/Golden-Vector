"""Top-of-report market context for hedge-readiness output."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.app.model_state import resolve_current_model_artifact_path
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import HedgeReadinessConfig
from golden_vector.hedge._helpers import (
    as_float as _as_float,
    is_optionable_tier as _is_optionable_tier,
    rows_by_ticker_dict as _rows_by_ticker,
)
from golden_vector.model.gold_shock import (
    DEFAULT_GOLD_DOWN_SCENARIO_FRACTION,
    compute_gold_shock_exposure,
)


@dataclass(frozen=True)
class PriceMoveContext:
    price: float | None
    change_1d: float | None
    change_1w: float | None
    change_1m: float | None


@dataclass(frozen=True)
class ImpliedVsModeledRow:
    ticker: str
    implied_move_60d: float | None
    modeled_downside_at_minus10: float | None
    verdict: str


@dataclass(frozen=True)
class HeaderContext:
    gold: PriceMoveContext
    gdx: PriceMoveContext
    implied_vs_modeled_rows: list[ImpliedVsModeledRow]
    data_notes: list[str]


def build_header_context(
    *,
    paths: ProjectPaths,
    options_features: pd.DataFrame | dict[str, pd.DataFrame],
    tool_a_frame: pd.DataFrame,
    hedge_config: HedgeReadinessConfig | None = None,
) -> HeaderContext:
    """Compute market context and implied-vs-modeled downside rows."""

    resolved_config = hedge_config or HedgeReadinessConfig()
    manifest, notes = _read_latest_options_manifest(paths)
    gold_history = _load_gold_history(paths=paths, manifest=manifest, notes=notes)
    gdx_history = _load_gdx_history(paths=paths, manifest=manifest, notes=notes)
    return HeaderContext(
        gold=_price_move_context(gold_history),
        gdx=_price_move_context(gdx_history),
        implied_vs_modeled_rows=_implied_vs_modeled_rows(
            options_features=options_features,
            tool_a_frame=tool_a_frame,
            hedge_config=resolved_config,
        ),
        data_notes=notes,
    )


def _read_latest_options_manifest(paths: ProjectPaths) -> tuple[dict[str, Any], list[str]]:
    manifest_path = resolve_current_model_artifact_path(
        paths,
        "options",
        fallback_path=paths.latest_options_manifest_path,
    )
    if manifest_path is None:
        return {}, ["latest options manifest unavailable"]
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"latest options manifest unreadable: {exc}"]
    if not isinstance(payload, dict):
        return {}, ["latest options manifest unreadable: expected a JSON object"]
    return payload, []


def _load_gold_history(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
    notes: list[str],
) -> pd.DataFrame:
    refresh_run_id = str(manifest.get("refresh_run_id") or "").strip()
    if not refresh_run_id:
        notes.append("gold history unavailable because refresh_run_id is missing")
        return pd.DataFrame()
    gold_path = paths.runs_dir / refresh_run_id / "snapshots" / "raw_gold.parquet"
    return _read_history(gold_path, notes, "gold history")


def _load_gdx_history(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
    notes: list[str],
) -> pd.DataFrame:
    for value in manifest.get("benchmark_snapshot_paths", []):
        path = paths.resolve_repo_relative(str(value))
        if path.stem.upper() == "GDX":
            return _read_history(path, notes, "GDX history")
    notes.append("GDX history unavailable because benchmark_snapshot_paths has no GDX entry")
    return pd.DataFrame()


def _read_history(path: Path, notes: list[str], label: str) -> pd.DataFrame:
    if not path.exists():
        notes.append(f"{label} unavailable at {path}")
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        # Header context is diagnostic only; bad context files should degrade the
        # report, not block the hedge-readiness command.
        notes.append(f"{label} unreadable at {path}: {exc}")
        return pd.DataFrame()


def _price_move_context(history: pd.DataFrame) -> PriceMoveContext:
    prices = _price_series(history)
    if prices.empty:
        return PriceMoveContext(None, None, None, None)
    return PriceMoveContext(
        price=float(prices.iloc[-1]),
        change_1d=_period_change(prices, 1),
        change_1w=_period_change(prices, 5),
        change_1m=_period_change(prices, 21),
    )


def _price_series(history: pd.DataFrame) -> pd.Series:
    if history.empty:
        return pd.Series(dtype=float)
    frame = history.copy()
    if "date" in frame.columns:
        frame = frame.sort_values("date")
    for column in ("adj_close_usd", "close_usd", "adj_close_local", "close_local"):
        if column in frame.columns:
            return pd.to_numeric(frame[column], errors="coerce").dropna().reset_index(drop=True)
    return pd.Series(dtype=float)


def _period_change(prices: pd.Series, periods: int) -> float | None:
    if len(prices.index) <= periods:
        return None
    previous = float(prices.iloc[-(periods + 1)])
    if previous == 0:
        return None
    return float(prices.iloc[-1]) / previous - 1.0


def _implied_vs_modeled_rows(
    *,
    options_features: pd.DataFrame | dict[str, pd.DataFrame],
    tool_a_frame: pd.DataFrame,
    hedge_config: HedgeReadinessConfig,
) -> list[ImpliedVsModeledRow]:
    tool_a_by_ticker = _rows_by_ticker(tool_a_frame)
    rows: list[ImpliedVsModeledRow] = []
    for feature in _feature_rows(options_features):
        ticker = str(feature.get("ticker") or "").upper()
        if not ticker or not _is_optionable_tier(feature.get("optionability_tier")):
            continue
        implied_move = _as_float(feature.get("implied_move_60d"))
        down_beta = _as_float(tool_a_by_ticker.get(ticker, {}).get("down_beta_core"))
        modeled_downside = _modeled_downside_at_minus10(down_beta)
        rows.append(
            ImpliedVsModeledRow(
                ticker=ticker,
                implied_move_60d=implied_move,
                modeled_downside_at_minus10=modeled_downside,
                verdict=_verdict(
                    implied_move_60d=implied_move,
                    modeled_downside_at_minus10=modeled_downside,
                    hedge_config=hedge_config,
                ),
            )
        )
    return sorted(rows, key=lambda row: row.ticker)


def _modeled_downside_at_minus10(down_beta: float | None) -> float | None:
    if down_beta is None:
        return None
    shock = compute_gold_shock_exposure(
        value_usd=1.0,
        beta=down_beta,
        shock_fraction=DEFAULT_GOLD_DOWN_SCENARIO_FRACTION,
        min_effective_beta=None,
    )
    return shock.loss_usd


def _feature_rows(
    options_features: pd.DataFrame | dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    if isinstance(options_features, pd.DataFrame):
        return [
            row.to_dict()
            for _, row in options_features.iterrows()
        ]
    rows: list[dict[str, Any]] = []
    for ticker, frame in options_features.items():
        if frame.empty:
            rows.append({"ticker": ticker})
            continue
        row = frame.iloc[-1].to_dict()
        row.setdefault("ticker", ticker)
        rows.append(row)
    return rows


def _verdict(
    *,
    implied_move_60d: float | None,
    modeled_downside_at_minus10: float | None,
    hedge_config: HedgeReadinessConfig,
) -> str:
    if (
        implied_move_60d is None
        or implied_move_60d <= 0
        or modeled_downside_at_minus10 is None
    ):
        return "data unavailable (heuristic)"
    model_over_market = float(hedge_config.option_verdict_model_over_market_ratio)
    market_over_model = float(hedge_config.option_verdict_market_over_model_ratio)
    if modeled_downside_at_minus10 > model_over_market * implied_move_60d:
        return "model > market (heuristic)"
    if modeled_downside_at_minus10 < market_over_model * implied_move_60d:
        return "market > model (heuristic)"
    return "model ~= market (heuristic)"
