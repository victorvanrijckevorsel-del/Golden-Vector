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
from golden_vector.screening.targets import compute_target_prices
from golden_vector.screening.verdicts import (
    compute_tool_b_score,
    determine_screening_verdict,
)


TOOL_B_OUTPUT_COLUMNS = [
    "ticker",
    "as_of_date",
    "gold_price_assumption",
    "layer1_status",
    "layer1_pass",
    "layer1_fail_reasons",
    "layer2_incomplete_reasons",
    "screening_verdict",
    "confidence",
    "size_category",
    "market_cap_musd",
    "share_price_usd",
    "forward_revenue_musd",
    "forward_ebitda_musd",
    "forward_net_income_musd",
    "forward_eps",
    "forward_pe",
    "ev_ebitda",
    "sustainable_fcf_musd",
    "fcf_yield",
    "leverage",
    "adjusted_peer_pe",
    "adjusted_peak_pe",
    "target_price_peer_pe",
    "target_price_peak_pe",
    "target_price_peer_fcf",
    "target_price_peak_fcf",
    "target_price_peer_evebitda",
    "target_price_peak_evebitda",
    "best_target_price_usd",
    "best_upside_pct",
    "tool_b_score",
    "tool_b_rank",
    "missing_manual_fields",
    "next_financial_report_date",
    "next_production_report_date",
    "source_run_id",
]


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
) -> ToolBExecutionResult:
    tool_b_tickers = sorted(
        {
            ticker.ticker
            for ticker in app_config.universe.tickers
            if ticker.active and ticker.tool_b_enabled
        }
    )
    manual_data = load_manual_screening_data(
        paths,
        tickers=tool_b_tickers,
    )
    snapshots = _prepare_market_snapshots(
        normalized_market_snapshots,
        allowed_tickers=set(tool_b_tickers),
    )
    snapshot_anchor_date = _determine_snapshot_anchor_date(
        snapshots=snapshots,
        run_context=run_context,
    )
    company_inputs = manual_data.company_inputs.copy()
    reporting_calendar = manual_data.reporting_calendar.copy()
    base_frame = pd.DataFrame({"ticker": tool_b_tickers})

    company_inputs["ticker"] = company_inputs["ticker"].astype(str)
    reporting_calendar["ticker"] = reporting_calendar["ticker"].astype(str)
    merged = base_frame.merge(
        snapshots,
        how="left",
        on="ticker",
    )
    merged = merged.merge(
        company_inputs,
        how="left",
        on="ticker",
    )
    merged = merged.merge(
        reporting_calendar,
        how="left",
        on="ticker",
    )

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
        targets = compute_target_prices(
            pd.Series({**row.to_dict(), **layer1, **layer2}),
            app_config=app_config,
        )
        verdict = determine_screening_verdict(
            confidence=confidence,
            layer1_status=str(layer1["layer1_status"]),
            forward_pe=layer2["forward_pe"],
            thresholds=app_config.screening_params.verdict_thresholds,
        )
        tool_b_score = compute_tool_b_score(
            screening_verdict=verdict,
            best_upside_pct=targets["best_upside_pct"],
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
                "size_category": targets["size_category"],
                "market_cap_musd": row.get("market_cap_musd"),
                "share_price_usd": row.get("share_price_usd"),
                "forward_revenue_musd": layer2["forward_revenue_musd"],
                "forward_ebitda_musd": layer2["forward_ebitda_musd"],
                "forward_net_income_musd": layer2["forward_net_income_musd"],
                "forward_eps": layer2["forward_eps"],
                "forward_pe": layer2["forward_pe"],
                "ev_ebitda": layer2["ev_ebitda"],
                "sustainable_fcf_musd": layer1["sustainable_fcf_musd"],
                "fcf_yield": layer1["fcf_yield"],
                "leverage": layer1["leverage"],
                "adjusted_peer_pe": targets["adjusted_peer_pe"],
                "adjusted_peak_pe": targets["adjusted_peak_pe"],
                "target_price_peer_pe": targets["target_price_peer_pe"],
                "target_price_peak_pe": targets["target_price_peak_pe"],
                "target_price_peer_fcf": targets["target_price_peer_fcf"],
                "target_price_peak_fcf": targets["target_price_peak_fcf"],
                "target_price_peer_evebitda": targets["target_price_peer_evebitda"],
                "target_price_peak_evebitda": targets["target_price_peak_evebitda"],
                "best_target_price_usd": targets["best_target_price_usd"],
                "best_upside_pct": targets["best_upside_pct"],
                "tool_b_score": tool_b_score,
                "tool_b_rank": None,
                "missing_manual_fields": None if not missing_fields else ";".join(missing_fields),
                "next_financial_report_date": row.get("next_financial_report_date"),
                "next_production_report_date": row.get("next_production_report_date"),
                "source_run_id": run_context.run_id,
            }
        )

    tool_b_outputs = pd.DataFrame(rows, columns=TOOL_B_OUTPUT_COLUMNS)
    if not tool_b_outputs.empty:
        tool_b_outputs = rank_tool_b_outputs(tool_b_outputs)
        tool_b_outputs = tool_b_outputs.sort_values(
            ["as_of_date", "gold_price_assumption", "tool_b_rank", "ticker"],
            ascending=[True, True, True, True],
            na_position="last",
        ).reset_index(drop=True)
    persist_tool_b_outputs(
        paths=paths,
        run_context=run_context,
        tool_b_outputs=tool_b_outputs,
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
        "ranked_row_count": int(tool_b_outputs["tool_b_rank"].notna().sum()) if not tool_b_outputs.empty else 0,
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


def _prepare_market_snapshots(
    normalized_market_snapshots: pd.DataFrame,
    *,
    allowed_tickers: set[str],
) -> pd.DataFrame:
    working = normalized_market_snapshots.copy()
    if working.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "snapshot_date",
                "share_price_usd",
                "market_cap_usd",
                "market_cap_musd",
                "shares_outstanding",
            ]
        )

    allowed_tickers = set(allowed_tickers)
    if allowed_tickers:
        working["ticker"] = working["ticker"].astype(str)
        working = working[working["ticker"].isin(allowed_tickers)].copy()

    if working.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "snapshot_date",
                "share_price_usd",
                "market_cap_usd",
                "market_cap_musd",
                "shares_outstanding",
            ]
        )

    working["market_cap_musd"] = pd.to_numeric(
        working["market_cap_usd"],
        errors="coerce",
    ) / 1_000_000.0
    working = working.sort_values(["ticker", "snapshot_date"]).drop_duplicates(
        subset=["ticker"],
        keep="last",
    )
    return working.reset_index(drop=True)


def _determine_snapshot_anchor_date(
    *,
    snapshots: pd.DataFrame,
    run_context: RunContext,
) -> object:
    if not snapshots.empty and "snapshot_date" in snapshots.columns:
        snapshot_dates = pd.to_datetime(
            snapshots["snapshot_date"],
            errors="coerce",
        ).dropna()
        if not snapshot_dates.empty:
            return snapshot_dates.max().date()
    return pd.to_datetime(run_context.started_at_utc, utc=True).date()
