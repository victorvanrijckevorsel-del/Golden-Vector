"""Tool B screening pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.config_models import AppConfig
from golden_vector.ingestion.persist import persist_tool_b_outputs
from golden_vector.screening.layer1 import evaluate_layer1
from golden_vector.screening.layer2 import compute_layer2_metrics
from golden_vector.screening.manual_data import (
    LoadedManualScreeningData,
    determine_manual_confidence,
    load_manual_screening_data,
    missing_required_manual_fields,
)
from golden_vector.screening.ranking import rank_tool_b_outputs
from golden_vector.screening.schema import TOOL_B_OUTPUT_COLUMNS
from golden_vector.screening.verdicts import (
    compute_fundamental_checks,
    determine_screening_verdict,
)


@dataclass(frozen=True)
class ToolBExecutionResult:
    tool_b_outputs: pd.DataFrame
    manual_data: LoadedManualScreeningData
    overall_status: str
    summary: dict[str, object]


def execute_tool_b_pipeline(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    run_context: RunContext,
    normalized_market_snapshots: pd.DataFrame,
    gold_price_assumption: float,
    snapshot_refresh_run_id: str | None = None,
    snapshot_as_of_date: object = None,
) -> ToolBExecutionResult:
    tool_b_tickers = _active_tool_b_tickers(app_config)
    manual_data = load_manual_screening_data(
        paths,
        tickers=tool_b_tickers,
    )
    merged, snapshot_anchor_date = _merge_inputs_for_tool_b(
        app_config=app_config,
        manual_data=manual_data,
        normalized_market_snapshots=normalized_market_snapshots,
        snapshot_as_of_date=snapshot_as_of_date,
        tool_b_tickers=tool_b_tickers,
    )

    rows = _build_tool_b_rows(
        merged=merged,
        manual_data=manual_data,
        app_config=app_config,
        gold_price_assumption=gold_price_assumption,
        snapshot_anchor_date=snapshot_anchor_date,
        snapshot_refresh_run_id=snapshot_refresh_run_id,
        source_run_id=run_context.run_id,
    )

    tool_b_outputs = _frame_from_rows(rows)
    persist_tool_b_outputs(
        paths=paths,
        run_context=run_context,
        tool_b_outputs=tool_b_outputs,
        publish_latest_aliases=not tool_b_outputs.empty,
    )

    verdict_counts = (
        tool_b_outputs["screening_verdict"].value_counts().to_dict()
        if not tool_b_outputs.empty
        else {}
    )
    overall_status = "PASS"
    if tool_b_outputs.empty:
        overall_status = "FAIL"
    elif verdict_counts.get("INCOMPLETE", 0) == len(tool_b_outputs.index):
        overall_status = "WARN"
    elif verdict_counts.get("INCOMPLETE", 0) > 0:
        overall_status = "WARN"

    summary = {
        "tool_b_output_row_count": len(tool_b_outputs.index),
        "tool_b_output_overall_status": overall_status,
        "tool_b_enabled_ticker_count": len(tool_b_tickers),
        "manual_store_path": str(manual_data.store_path),
        "manual_store_created": manual_data.store_created,
        "manual_seeded_ticker_count": len(manual_data.seeded_tickers),
        "manual_csv_import_count": len(manual_data.imported_csv_files),
        "manual_stock_note_count": len(manual_data.stock_notes.index),
        "missing_market_snapshot_row_count": int(merged["snapshot_date"].isna().sum()),
        "ranked_row_count": int(tool_b_outputs["fundamental_check_rank"].notna().sum()) if not tool_b_outputs.empty else 0,
        "incomplete_row_count": int((tool_b_outputs["screening_verdict"] == "INCOMPLETE").sum()) if not tool_b_outputs.empty else 0,
        "strong_candidate_row_count": int((tool_b_outputs["screening_verdict"] == "STRONG_CANDIDATE").sum()) if not tool_b_outputs.empty else 0,
        "watchlist_row_count": int((tool_b_outputs["screening_verdict"] == "WATCHLIST").sum()) if not tool_b_outputs.empty else 0,
    }
    if manual_data.imported_csv_files:
        summary["manual_csv_imported_files"] = manual_data.imported_csv_files
    if manual_data.seeded_tickers:
        summary["manual_seeded_tickers"] = manual_data.seeded_tickers
    if not tool_b_outputs.empty:
        summary["latest_output_as_of_date"] = str(tool_b_outputs["as_of_date"].max())

    return ToolBExecutionResult(
        tool_b_outputs=tool_b_outputs,
        manual_data=manual_data,
        overall_status=overall_status,
        summary=summary,
    )


def compute_tool_b_in_memory(
    *,
    app_config: AppConfig,
    manual_data: LoadedManualScreeningData,
    normalized_market_snapshots: pd.DataFrame,
    gold_price_assumption: float,
    snapshot_refresh_run_id: str | None = None,
    snapshot_as_of_date: object = None,
    source_run_id: str = "in-memory",
) -> pd.DataFrame:
    """Run the Tool B math without any persistence.

    This is the shared math seam used by both `execute_tool_b_pipeline`
    (which additionally writes parquet / CSV / manifest and emits a
    ToolBExecutionResult) and the workspace's live-override view (which
    needs a fresh DataFrame per page hit without side effects).

    All inputs are already-loaded objects so the caller controls what's
    injected (e.g., the workspace re-uses its cached manual_data +
    snapshots and only varies gold_price_assumption / config overrides).
    """
    tool_b_tickers = _active_tool_b_tickers(app_config)
    merged, snapshot_anchor_date = _merge_inputs_for_tool_b(
        app_config=app_config,
        manual_data=manual_data,
        normalized_market_snapshots=normalized_market_snapshots,
        snapshot_as_of_date=snapshot_as_of_date,
        tool_b_tickers=tool_b_tickers,
    )
    rows = _build_tool_b_rows(
        merged=merged,
        manual_data=manual_data,
        app_config=app_config,
        gold_price_assumption=gold_price_assumption,
        snapshot_anchor_date=snapshot_anchor_date,
        snapshot_refresh_run_id=snapshot_refresh_run_id,
        source_run_id=source_run_id,
    )
    return _frame_from_rows(rows)


def _active_tool_b_tickers(app_config: AppConfig) -> list[str]:
    return sorted(
        {
            ticker.ticker
            for ticker in app_config.universe.tickers
            if ticker.active and ticker.tool_b_enabled
        }
    )


def _merge_inputs_for_tool_b(
    *,
    app_config: AppConfig,
    manual_data: LoadedManualScreeningData,
    normalized_market_snapshots: pd.DataFrame,
    snapshot_as_of_date: object,
    tool_b_tickers: list[str],
) -> tuple[pd.DataFrame, object]:
    """Produce the merged per-ticker frame used by the row builder."""
    snapshots = _prepare_market_snapshots(
        normalized_market_snapshots,
        allowed_tickers=set(tool_b_tickers),
    )
    snapshot_anchor_date = _determine_snapshot_anchor_date(
        snapshots=snapshots,
        snapshot_as_of_date=snapshot_as_of_date,
    )
    company_inputs = manual_data.company_inputs.copy()
    reporting_calendar = manual_data.reporting_calendar.copy()
    company_inputs["ticker"] = company_inputs["ticker"].astype(str)
    reporting_calendar["ticker"] = reporting_calendar["ticker"].astype(str)

    base_frame = pd.DataFrame({"ticker": tool_b_tickers})
    merged = base_frame.merge(snapshots, how="left", on="ticker")
    merged = merged.merge(company_inputs, how="left", on="ticker")
    merged = merged.merge(reporting_calendar, how="left", on="ticker")

    universe_map = {
        ticker.ticker: ticker
        for ticker in app_config.universe.tickers
        if ticker.active and ticker.tool_b_enabled
    }
    merged["jurisdiction_tier"] = merged["ticker"].map(
        lambda ticker: universe_map.get(str(ticker)).jurisdiction_tier
        if universe_map.get(str(ticker)) is not None
        else None
    )
    merged["as_of_date"] = merged["snapshot_date"].where(
        merged["snapshot_date"].notna(),
        snapshot_anchor_date,
    )
    return merged, snapshot_anchor_date


def _build_tool_b_rows(
    *,
    merged: pd.DataFrame,
    manual_data: LoadedManualScreeningData,
    app_config: AppConfig,
    gold_price_assumption: float,
    snapshot_anchor_date: object,
    snapshot_refresh_run_id: str | None,
    source_run_id: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for _, row in merged.iterrows():
        ticker = str(row["ticker"])
        confidence = determine_manual_confidence(
            ticker=ticker,
            company_row=row,
            source_verification=manual_data.source_verification,
        )
        missing_fields = missing_required_manual_fields(row)
        layer1 = evaluate_layer1(
            row,
            gold_price_assumption=gold_price_assumption,
            thresholds=app_config.screening_params.layer1_thresholds,
        )
        layer2 = compute_layer2_metrics(
            pd.Series({**row.to_dict(), **layer1}),
            gold_price_assumption=gold_price_assumption,
        )
        verdict = determine_screening_verdict(
            confidence=confidence,
            layer1_status=str(layer1["layer1_status"]),
            forward_pe=layer2["forward_pe"],
            thresholds=app_config.screening_params.verdict_thresholds,
        )
        fundamental_checks = compute_fundamental_checks(
            layer1_check_statuses=layer1["layer1_check_statuses"],
            forward_pe=layer2["forward_pe"],
            thresholds=app_config.screening_params.verdict_thresholds,
        )

        rows.append(
            {
                "ticker": ticker,
                "as_of_date": row["as_of_date"],
                "gold_price_assumption": gold_price_assumption,
                "layer1_status": layer1["layer1_status"],
                "layer1_pass": bool(layer1["layer1_pass"]),
                "layer1_fail_reasons": layer1["layer1_fail_reasons"],
                "layer2_incomplete_reasons": layer2["layer2_incomplete_reasons"],
                "screening_verdict": verdict,
                "confidence": confidence,
                "jurisdiction_tier": row.get("jurisdiction_tier"),
                "market_cap_musd": row.get("market_cap_musd"),
                "share_price_usd": row.get("share_price_usd"),
                "enterprise_value_musd": layer2["enterprise_value_musd"],
                "production_oz": row.get("production_oz"),
                "aisc_usd_per_oz": row.get("aisc_usd_per_oz"),
                "cash_cost_usd_per_oz": row.get("cash_cost_usd_per_oz"),
                "net_debt_musd": row.get("net_debt_musd"),
                "reserve_life_years": row.get("reserve_life_years"),
                "cash_margin_usd_per_oz": layer1["cash_margin_usd_per_oz"],
                "margin_pct": layer1["margin_pct"],
                "forward_revenue_musd": layer2["forward_revenue_musd"],
                "forward_ebitda_musd": layer2["forward_ebitda_musd"],
                "forward_net_income_musd": layer2["forward_net_income_musd"],
                "forward_eps": layer2["forward_eps"],
                "forward_pe": layer2["forward_pe"],
                "ev_ebitda": layer2["ev_ebitda"],
                "sustainable_fcf_musd": layer1["sustainable_fcf_musd"],
                "fcf_yield": layer1["fcf_yield"],
                "leverage": layer1["leverage"],
                "fundamental_check_score": fundamental_checks["fundamental_check_score"],
                "fundamental_check_rank": None,
                "fundamental_checks_passed": fundamental_checks["fundamental_checks_passed"],
                "fundamental_checks_total": fundamental_checks["fundamental_checks_total"],
                "fundamental_check_summary": fundamental_checks["fundamental_check_summary"],
                "missing_manual_fields": None if not missing_fields else ";".join(missing_fields),
                "next_financial_report_date": row.get("next_financial_report_date"),
                "next_production_report_date": row.get("next_production_report_date"),
                "snapshot_refresh_run_id": snapshot_refresh_run_id,
                "snapshot_as_of_date": snapshot_anchor_date,
                "snapshot_normalization_status": _coerce_status(
                    row.get("snapshot_normalization_status")
                ),
                "fx_staleness_days": _coerce_optional_int(row.get("fx_staleness_days")),
                "fx_policy_max_staleness_days": int(app_config.qa.max_fx_staleness_days),
                "fx_policy_block_on_stale_fx": bool(app_config.qa.block_on_stale_fx),
                "source_run_id": source_run_id,
            }
        )
    return rows


def _frame_from_rows(rows: list[dict[str, object]]) -> pd.DataFrame:
    tool_b_outputs = pd.DataFrame(rows, columns=TOOL_B_OUTPUT_COLUMNS)
    if not tool_b_outputs.empty:
        tool_b_outputs = rank_tool_b_outputs(tool_b_outputs)
        tool_b_outputs = tool_b_outputs.sort_values(
            ["as_of_date", "gold_price_assumption", "fundamental_check_rank", "ticker"],
            ascending=[True, True, True, True],
            na_position="last",
        ).reset_index(drop=True)
    return tool_b_outputs


def _prepare_market_snapshots(
    normalized_market_snapshots: pd.DataFrame,
    *,
    allowed_tickers: set[str],
) -> pd.DataFrame:
    snapshot_columns = [
        "ticker",
        "snapshot_date",
        "share_price_usd",
        "market_cap_usd",
        "market_cap_musd",
        "shares_outstanding",
        "snapshot_normalization_status",
        "fx_staleness_days",
    ]
    working = normalized_market_snapshots.copy()
    if working.empty:
        return pd.DataFrame(columns=snapshot_columns)

    allowed_tickers = set(allowed_tickers)
    if allowed_tickers:
        working["ticker"] = working["ticker"].astype(str)
        working = working[working["ticker"].isin(allowed_tickers)].copy()

    if working.empty:
        return pd.DataFrame(columns=snapshot_columns)

    working["market_cap_musd"] = pd.to_numeric(
        working["market_cap_usd"],
        errors="coerce",
    ) / 1_000_000.0
    working["snapshot_normalization_status"] = (
        working.get("normalization_status", pd.Series(index=working.index, dtype=object))
        .astype(object)
    )
    if "fx_staleness_days" not in working.columns:
        working["fx_staleness_days"] = pd.NA
    working = working.sort_values(["ticker", "snapshot_date"]).drop_duplicates(
        subset=["ticker"],
        keep="last",
    )
    return working.reset_index(drop=True)[snapshot_columns]


def _determine_snapshot_anchor_date(
    *,
    snapshots: pd.DataFrame,
    snapshot_as_of_date: object = None,
) -> object:
    if not snapshots.empty and "snapshot_date" in snapshots.columns:
        snapshot_dates = pd.to_datetime(
            snapshots["snapshot_date"],
            errors="coerce",
        ).dropna()
        if not snapshot_dates.empty:
            return snapshot_dates.max().date()
    if snapshot_as_of_date is not None:
        coerced = pd.to_datetime(snapshot_as_of_date, errors="coerce")
        if pd.notna(coerced):
            return coerced.date()
    return None


def _coerce_status(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text.upper() if text else None


def _coerce_optional_int(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
