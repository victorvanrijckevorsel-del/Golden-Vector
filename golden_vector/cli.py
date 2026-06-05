"""CLI routing for Golden Vector."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Sequence
from uuid import uuid4

import pandas as pd

from golden_vector.common.status import combine_statuses as _combine_statuses
from golden_vector.app.config import load_app_config
from golden_vector.app.latest_data import (
    LatestFoundationSnapshot,
    load_latest_foundation_snapshot,
    write_latest_foundation_manifest,
)
from golden_vector.app.logging import configure_logging
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    resolve_current_foundation_manifest_path,
    resolve_current_model_artifact_path,
    summarize_model_state_manifest,
    write_current_model_state_manifest,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.replay_manifest import (
    VERDICT_PREDATES_REPLAY_MANIFEST,
    VerifyResult,
    update_manifest_with_foundation,
    verify_manifest,
)
from golden_vector.app.run_context import RunContext, to_jsonable
from golden_vector.features.horizons import parse_requested_horizons
from golden_vector.features.returns import RETURN_COLUMNS, compute_horizon_returns_for_ticker
from golden_vector.hedge.comparison import COMPARISON_SORT_COLUMNS
from golden_vector.hedge.option_artifact_builder import (
    build_option_artifact_inputs,
    scan_option_contract_metrics,
)
from golden_vector.hedge.option_artifact_frames import build_option_artifact_frames
from golden_vector.hedge.option_artifact_sources import load_option_artifact_source_inputs
from golden_vector.hedge.options_liquidity import slot_tier_counts
from golden_vector.ingestion.foundation import execute_foundation_pipeline
from golden_vector.ingestion.options_phase import (
    run_options_ingestion_phase,
    skipped_options_phase_summary,
)
from golden_vector.ingestion.persist_options import safe_options_file_name
from golden_vector.ingestion.persist_option_artifacts import persist_option_artifact_frames
from golden_vector.ingestion.persist_tool_c import persist_tool_c_outputs
from golden_vector.ingestion.persist_tool_d import persist_tool_d_outputs
from golden_vector.hedge.report import write_hedge_readiness_report
from golden_vector.model.pipeline import execute_tool_a_profile_pipeline
from golden_vector.model.tool_c import ToolCExecutionInputs, compute_tool_c_outputs
from golden_vector.model.tool_d import ToolDExecutionInputs, compute_tool_d_outputs
from golden_vector.screening.manual_data import (
    bootstrap_manual_screening_data,
    load_manual_screening_data,
)
from golden_vector.screening.manual_store import (
    add_stock_note,
    export_store_to_csv,
    import_support_csvs_into_store,
    list_stock_notes,
    manual_store_exists,
    upsert_company_input,
    upsert_reporting_calendar,
    upsert_source_verification,
)
from golden_vector.screening.pipeline import execute_tool_b_pipeline
from golden_vector.serve.candidate_finder_data import (
    candidate_finder_result_frame,
    load_candidate_finder_data,
    load_candidate_finder_spec,
    run_candidate_finder_screen,
)
from golden_vector.serve.option_trading_data import load_option_trading_data
from golden_vector.serve.workspace import run_workspace_server

LOGGER = logging.getLogger(__name__)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="golden-vector",
        description="Golden Vector pipeline runner.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "foundation",
        help="Legacy alias for update-data; refresh raw ingestion, QA, and USD normalization.",
    )
    update_data_parser = subparsers.add_parser(
        "update-data",
        help="Refresh market data, run QA, and publish the latest validated local artifacts.",
    )
    update_data_options = update_data_parser.add_mutually_exclusive_group()
    update_data_options.add_argument(
        "--options",
        dest="options",
        action="store_true",
        default=True,
        help="Fetch and persist hedge-readiness options data after the foundation refresh.",
    )
    update_data_options.add_argument(
        "--no-options",
        dest="options",
        action="store_false",
        help="Skip the hedge-readiness options phase for this update-data run.",
    )
    subparsers.add_parser(
        "tool-a",
        help="Run structural Tool A from the latest validated local USD-normalized snapshot.",
    )
    subparsers.add_parser(
        "tool-c",
        help="Run symmetric Tool C behavior ranking from Tool A and weekly return history.",
    )
    tool_d_parser = subparsers.add_parser(
        "tool-d",
        help="Run Tool D gold-stressed quality scorecard from Tool B/manual data.",
    )
    tool_d_parser.add_argument(
        "--gold-price",
        type=float,
        default=None,
        help="Gold price G in USD per oz. Defaults to the latest spot gold close.",
    )

    refresh_parser = subparsers.add_parser(
        "refresh",
        help=(
            "One-command operational refresh: runs update-data, tool-a, tool-b, "
            "tool-c, and spot tool-d, then prints a one-screen status summary."
        ),
    )
    refresh_parser.add_argument(
        "--gold-price",
        type=float,
        default=None,
        help=(
            "Override the gold price assumption for the Tool B step. Defaults to "
            "screening_params.default_gold_price_assumption."
        ),
    )
    refresh_parser.add_argument(
        "--skip-tool-b",
        action="store_true",
        help=(
            "Skip the Tool B step. Useful if the manual-data store hasn't been populated yet."
        ),
    )

    status_parser = subparsers.add_parser(
        "status",
        help=(
            "Print a one-screen operational summary: snapshot date, latest Tool A and "
            "Tool B run state, manual-data coverage per ticker, refresh-id alignment."
        ),
    )

    tool_b_parser = subparsers.add_parser(
        "tool-b",
        help="Run Tool B through the shared backbone, manual screening inputs, and valuation outputs.",
    )
    tool_b_parser.add_argument(
        "--gold-price",
        type=float,
        default=None,
        help=(
            "Gold price assumption in USD per oz. "
            "Defaults to screening_params.default_gold_price_assumption (or the first "
            "configured scenario if no default is set)."
        ),
    )

    hedge_readiness_parser = subparsers.add_parser(
        "hedge-readiness",
        help="Render the local hedge-readiness markdown report from latest options data.",
    )
    hedge_readiness_parser.add_argument(
        "--comparison-sort-by",
        choices=COMPARISON_SORT_COLUMNS,
        default=None,
        help="Sort column for the cross-ticker comparison view.",
    )
    hedge_readiness_parser.add_argument(
        "--ranking-sort-by",
        choices=["down_beta_core"],
        default=None,
        help="Sort column for the sensitivity ranking.",
    )
    hedge_readiness_parser.add_argument(
        "--ranking-max-tickers",
        type=_positive_int,
        default=None,
        help="Maximum rows to show in the sensitivity ranking.",
    )
    hedge_readiness_parser.add_argument(
        "--speculation-max-tickers",
        type=_positive_int,
        default=None,
        help="Maximum tickers to show in the speculation candidates section.",
    )
    hedge_readiness_parser.add_argument(
        "--quantity",
        type=_positive_int,
        default=None,
        help="Put-contract quantity for scenario P&L.",
    )

    liquidity_parser = subparsers.add_parser(
        "options-liquidity-summary",
        help="Print cached option-liquidity tier counts by ticker.",
    )
    liquidity_parser.add_argument(
        "--ticker",
        default=None,
        help="Optional ticker to inspect.",
    )

    candidate_finder_parser = subparsers.add_parser(
        "candidate-finder",
        help="Run a Candidate Finder screen spec and write a ranked parquet.",
    )
    candidate_finder_parser.add_argument(
        "--spec",
        required=True,
        help="JSON/YAML screen spec with preset, criteria, options_side, and top_n.",
    )
    candidate_finder_parser.add_argument(
        "--out",
        default=None,
        help=(
            "Output parquet path. Defaults to "
            "data/output/candidate_finder/candidate_finder_latest.parquet."
        ),
    )

    manual_data_parser = subparsers.add_parser(
        "manual-data",
        help="Manage Tool B slow-moving manual company inputs in the local app store.",
    )
    manual_data_subparsers = manual_data_parser.add_subparsers(
        dest="manual_data_command",
        required=True,
    )

    manual_data_subparsers.add_parser(
        "init",
        help="Create or sync the local Tool B manual-data store for the active Tool B universe.",
    )
    manual_data_subparsers.add_parser(
        "import-csv",
        help="Import support CSV files into the local Tool B manual-data store.",
    )
    manual_data_subparsers.add_parser(
        "export-csv",
        help="Export the local Tool B manual-data store back to support CSV files.",
    )

    show_parser = manual_data_subparsers.add_parser(
        "show",
        help="Show the current manual Tool B record for one ticker.",
    )
    show_parser.add_argument("--ticker", required=True, help="Ticker to inspect.")

    set_company_parser = manual_data_subparsers.add_parser(
        "set-company",
        help="Update one or more Tool B company-input fields for a ticker.",
    )
    set_company_parser.add_argument("--ticker", required=True, help="Ticker to update.")
    set_company_parser.add_argument("--production-oz", type=float)
    set_company_parser.add_argument("--aisc-usd-per-oz", type=float)
    set_company_parser.add_argument("--cash-cost-usd-per-oz", type=float)
    set_company_parser.add_argument("--royalty-rate", type=float)
    set_company_parser.add_argument("--sustaining-capex-musd", type=float)
    set_company_parser.add_argument("--da-musd", type=float)
    set_company_parser.add_argument("--interest-expense-musd", type=float)
    set_company_parser.add_argument("--tax-rate", type=float)
    set_company_parser.add_argument("--reserve-life-years", type=float)
    set_company_parser.add_argument("--net-debt-musd", type=float)
    set_company_parser.add_argument("--ebitda-ltm-musd", type=float)
    set_company_parser.add_argument(
        "--clear-fields",
        nargs="+",
        choices=[
            "production_oz",
            "aisc_usd_per_oz",
            "cash_cost_usd_per_oz",
            "royalty_rate",
            "sustaining_capex_musd",
            "da_musd",
            "interest_expense_musd",
            "tax_rate",
            "reserve_life_years",
            "net_debt_musd",
            "ebitda_ltm_musd",
        ],
        default=[],
        help="One or more company-input fields to clear back to blank/NULL.",
    )

    set_reporting_parser = manual_data_subparsers.add_parser(
        "set-reporting",
        help="Update reporting-calendar fields for a ticker.",
    )
    set_reporting_parser.add_argument("--ticker", required=True, help="Ticker to update.")
    set_reporting_parser.add_argument("--next-financial-report-date")
    set_reporting_parser.add_argument("--next-production-report-date")
    set_reporting_parser.add_argument("--notes")
    set_reporting_parser.add_argument(
        "--clear-fields",
        nargs="+",
        choices=[
            "next_financial_report_date",
            "next_production_report_date",
            "notes",
        ],
        default=[],
        help="One or more reporting-calendar fields to clear back to blank/NULL.",
    )

    set_verification_parser = manual_data_subparsers.add_parser(
        "set-verification",
        help="Update a source-verification record for one manual Tool B field.",
    )
    set_verification_parser.add_argument("--ticker", required=True, help="Ticker to update.")
    set_verification_parser.add_argument("--field-name", required=True)
    set_verification_parser.add_argument("--verification-status", required=True)
    set_verification_parser.add_argument("--source-date")
    set_verification_parser.add_argument("--source-url")
    set_verification_parser.add_argument("--notes")
    set_verification_parser.add_argument(
        "--clear-fields",
        nargs="+",
        choices=["source_date", "source_url", "notes"],
        default=[],
        help="Optional source-verification metadata fields to clear back to blank/NULL.",
    )

    manual_note_parser = subparsers.add_parser(
        "manual-note",
        help="Manage per-stock follow-up notes in the local Tool B manual-data store.",
    )
    manual_note_subparsers = manual_note_parser.add_subparsers(
        dest="manual_note_command",
        required=True,
    )

    add_note_parser = manual_note_subparsers.add_parser(
        "add",
        help="Add a follow-up note for one stock.",
    )
    add_note_parser.add_argument("--ticker", required=True)
    add_note_parser.add_argument("--note", required=True)
    add_note_parser.add_argument("--tag")
    add_note_parser.add_argument("--status", default="OPEN")

    list_note_parser = manual_note_subparsers.add_parser(
        "list",
        help="List recent notes for one stock or for the whole store.",
    )
    list_note_parser.add_argument("--ticker")
    list_note_parser.add_argument("--limit", type=int, default=20)

    compare_parser = subparsers.add_parser(
        "compare-horizons",
        help="Compare configured and custom horizons for one Tool A ticker as exploratory analysis only.",
    )
    compare_parser.add_argument("--ticker", required=True, help="Ticker to inspect.")
    compare_parser.add_argument(
        "--horizons",
        required=True,
        help="Comma-separated horizon ids such as 5D,10D,3M.",
    )
    compare_parser.add_argument(
        "--csv-out",
        help="Optional CSV output path for the comparison table.",
    )

    workspace_parser = subparsers.add_parser(
        "workspace",
        help="Start the local Golden Vector workspace for Tool B inputs, notes, and latest Tool A / Tool B outputs.",
    )
    workspace_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind the local workspace server to.",
    )
    workspace_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to bind the local workspace server to.",
    )

    verify_parser = subparsers.add_parser(
        "verify-replay",
        help="Verify replay manifest snapshots for one retained run.",
    )
    verify_parser.add_argument(
        "run_id_or_path",
        help="Run id under data/runs, or a direct path to a run directory.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = ProjectPaths.discover()

    if args.command in {"foundation", "update-data"}:
        return run_foundation(
            paths,
            command_name=args.command,
            include_options=getattr(args, "options", True),
        )

    if args.command == "tool-a":
        return run_tool_a(paths)

    if args.command == "tool-c":
        return run_tool_c(paths)

    if args.command == "tool-d":
        return run_tool_d(paths, gold_price=args.gold_price)

    if args.command == "tool-b":
        return run_tool_b(paths, gold_price=args.gold_price)

    if args.command == "hedge-readiness":
        return run_hedge_readiness(
            paths,
            comparison_sort_by=args.comparison_sort_by,
            ranking_sort_by=args.ranking_sort_by,
            ranking_max_tickers=args.ranking_max_tickers,
            speculation_max_tickers=args.speculation_max_tickers,
            quantity=args.quantity,
        )

    if args.command == "options-liquidity-summary":
        return run_options_liquidity_summary(paths, ticker=args.ticker)

    if args.command == "candidate-finder":
        return run_candidate_finder(paths, spec_path=args.spec, out_path=args.out)

    if args.command == "refresh":
        return run_refresh(
            paths,
            gold_price_override=args.gold_price,
            skip_tool_b=args.skip_tool_b,
        )

    if args.command == "status":
        return run_status(paths)

    if args.command == "manual-data":
        return run_manual_data(paths, args)

    if args.command == "manual-note":
        return run_manual_note(paths, args)

    if args.command == "compare-horizons":
        return run_compare_horizons(
            paths,
            ticker=args.ticker,
            raw_horizons=args.horizons,
            csv_out=args.csv_out,
        )

    if args.command == "workspace":
        return run_workspace(paths, host=args.host, port=args.port)

    if args.command == "verify-replay":
        return run_verify_replay(paths, run_id_or_path=args.run_id_or_path)

    parser.error(f"Unsupported command: {args.command}")
    return 2


def run_options_liquidity_summary(
    paths: ProjectPaths,
    *,
    ticker: str | None = None,
) -> int:
    loaded_config = load_app_config(paths)
    data = load_option_trading_data(paths, app_config=loaded_config.app)
    rows = list(data.overview.rows)
    if ticker:
        normalized = ticker.strip().upper()
        rows = [row for row in rows if row.ticker == normalized]
    if not rows:
        reason = data.overview.reason or "No matching option-liquidity rows."
        print(reason)
        return 0

    print(
        "Ticker | Put Tradable | Put Watch | Put No-trade | "
        "Call Tradable | Call Watch | Call No-trade"
    )
    for row in rows:
        put_counts = slot_tier_counts(data.candidate_slots.get(row.ticker, []))
        call_counts = slot_tier_counts(data.call_candidate_slots.get(row.ticker, []))
        print(
            f"{row.ticker} | "
            f"{put_counts['tradable']} | {put_counts['watch']} | {put_counts['no_trade']} | "
            f"{call_counts['tradable']} | {call_counts['watch']} | {call_counts['no_trade']}"
        )
    return 0


def run_candidate_finder(
    paths: ProjectPaths,
    *,
    spec_path: str,
    out_path: str | None = None,
) -> int:
    run_context: RunContext | None = None
    parameters = {"spec_path": spec_path, "out_path": out_path}
    try:
        loaded_config = load_app_config(paths)
        run_context = RunContext.start(
            paths=paths,
            command="candidate-finder",
            parameters=parameters,
            config_hash=loaded_config.combined_hash,
        )
        configure_logging(run_context.log_path)
        spec_file = Path(spec_path)
        if not spec_file.is_absolute():
            spec_file = paths.repo_root / spec_file
        spec = load_candidate_finder_spec(spec_file)
        data = load_candidate_finder_data(paths, app_config=loaded_config.app)
        screen = run_candidate_finder_screen(data, spec=spec)
        ranked = candidate_finder_result_frame(screen)
        output_path = _candidate_finder_output_path(paths, out_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ranked.to_parquet(output_path, index=False)
        run_context.record_artifact(output_path)
        output_display_path = _display_path(paths, output_path)
        summary = {
            "candidate_finder_row_count": len(ranked.index),
            "candidate_finder_peer_count": len(screen.peer_frame.index),
            "candidate_finder_options_side": screen.options_side,
            "candidate_finder_top_n": screen.top_n,
            "candidate_finder_alignment_status": screen.data.alignment.status,
            "candidate_finder_alignment_message": screen.data.alignment.message,
            "candidate_finder_warning_count": len(screen.warnings),
            "candidate_finder_output_path": output_display_path,
        }
        run_context.write_json("candidate_finder_summary.json", summary)
        final_status = "PASS" if not screen.warnings else "WARN"
        run_context.finalize(
            status=final_status,
            summary=summary,
            notes=[
                "Candidate Finder screen rendered.",
                f"Output path: {output_display_path}.",
            ],
        )
        print(
            "Candidate Finder ranked parquet written: "
            f"{output_display_path}"
        )
        print(
            f"Rows: {len(ranked.index)}; peer pool: {len(screen.peer_frame.index)}; "
            f"options side: {screen.options_side}."
        )
        if screen.warnings:
            print("Warnings:")
            for warning in screen.warnings:
                print(f"- {warning}")
        if ranked.empty:
            print("No ranked rows.")
        else:
            preview_cols = [
                column
                for column in (
                    "rank",
                    "ticker",
                    "score",
                    "rank_eligible",
                    "present_criteria_count",
                    "selected_criteria_count",
                    "top_n_tally",
                )
                if column in ranked.columns
            ]
            print("Preview:")
            print(ranked[preview_cols].head(10).to_string(index=False))
        return 0
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command="candidate-finder",
                parameters=parameters,
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("Candidate Finder screen failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["Candidate Finder screen failed before completion."],
        )
        print(f"Candidate Finder failed: {exc}")
        return 1


def _candidate_finder_output_path(paths: ProjectPaths, out_path: str | None) -> Path:
    if out_path:
        path = Path(out_path)
        return path if path.is_absolute() else paths.repo_root / path
    return paths.output_dir / "candidate_finder" / "candidate_finder_latest.parquet"


def _display_path(paths: ProjectPaths, path: Path) -> str:
    try:
        return path.relative_to(paths.repo_root).as_posix()
    except ValueError:
        return str(path)


def run_foundation(
    paths: ProjectPaths,
    *,
    command_name: str = "foundation",
    include_options: bool = True,
) -> int:
    run_context: RunContext | None = None

    try:
        loaded_config = load_app_config(paths)
        run_context = RunContext.start(
            paths=paths,
            command=command_name,
            parameters={"options": include_options},
            config_hash=loaded_config.combined_hash,
        )
        configure_logging(run_context.log_path)

        configured_tickers = loaded_config.app.universe.tickers
        active_tickers = [ticker for ticker in configured_tickers if ticker.active]
        tool_a_enabled = [
            ticker for ticker in active_tickers if ticker.tool_a_enabled
        ]
        tool_b_enabled = [
            ticker for ticker in active_tickers if ticker.tool_b_enabled
        ]

        LOGGER.info("Starting %s run %s", command_name, run_context.run_id)
        LOGGER.info(
            "Loaded %s active tickers out of %s configured.",
            len(active_tickers),
            len(configured_tickers),
        )

        config_summary = {
            "configured_ticker_count": len(configured_tickers),
            "active_ticker_count": len(active_tickers),
            "tool_a_enabled_ticker_count": len(tool_a_enabled),
            "tool_b_enabled_ticker_count": len(tool_b_enabled),
            "core_horizon_count": len(loaded_config.app.horizons.core_horizons),
            "gold_price_scenarios": loaded_config.app.screening_params.gold_price_scenarios,
            "combined_config_hash": loaded_config.combined_hash,
            "options_phase_requested": include_options,
        }
        run_context.write_json("config_summary.json", config_summary)

        result = execute_foundation_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
        )
        run_context.write_json("fetch_plan.json", result.registry.summary())
        qa_summary = {
            "overall_status": result.overall_status,
            "raw": result.raw_qa_report.summary(),
            "normalization": (
                result.normalization_qa_report.summary()
                if result.normalization_qa_report is not None
                else {"overall_status": "SKIPPED"}
            ),
        }
        run_context.write_json("qa_summary.json", qa_summary)
        run_context.write_json("raw_qa_summary.json", result.raw_qa_report.summary())
        if result.normalization_qa_report is not None:
            run_context.write_json(
                "normalization_qa_summary.json",
                result.normalization_qa_report.summary(),
            )

        notes = [
            "Market-data refresh completed.",
            f"Raw QA status: {result.raw_qa_report.overall_status}.",
        ]
        if result.normalization_qa_report is None:
            notes.append("Normalization stage skipped because raw QA failed.")
        else:
            notes.append(
                f"Normalization QA status: {result.normalization_qa_report.overall_status}."
            )
        if result.overall_status != "FAIL":
            manifest_path = write_latest_foundation_manifest(
                paths=paths,
                run_context=run_context,
                app_config=loaded_config.app,
                foundation_result=result,
            )
            notes.append("Latest validated local market-data snapshot was updated.")
            notes.append(f"Snapshot manifest: {manifest_path.relative_to(paths.repo_root).as_posix()}.")
        else:
            notes.append("Latest validated local market-data snapshot was left unchanged.")

        if include_options and result.overall_status != "FAIL":
            snapshot_date = _foundation_result_as_of_date(result)
            options_result = run_options_ingestion_phase(
                paths=paths,
                run_context=run_context,
                app_config=loaded_config.app,
                normalized_equity_histories=result.normalized_equity_histories,
                as_of_date=snapshot_date,
            )
            options_summary = options_result.summary
            notes.append(
                "Options phase completed with "
                f"{options_summary['options_phase_status']} status "
                f"({options_summary['options_success_count']} optionable, "
                f"{options_summary['options_empty_count']} empty, "
                f"{options_summary['options_error_count']} errors)."
            )
        elif include_options:
            options_summary = skipped_options_phase_summary(
                reason="Foundation status was FAIL.",
            )
            run_context.write_json("options_phase_summary.json", options_summary)
            notes.append("Options phase skipped because foundation failed.")
        else:
            options_summary = skipped_options_phase_summary(
                reason="Operator passed --no-options.",
            )
            run_context.write_json("options_phase_summary.json", options_summary)
            notes.append("Options phase skipped by --no-options.")

        final_status = _combine_statuses(
            result.overall_status,
            str(options_summary.get("options_phase_status", "SKIPPED")),
        )
        run_context.finalize(
            status=final_status,
            summary={**config_summary, **result.summary, **options_summary},
            notes=notes,
        )

        if final_status == "FAIL":
            LOGGER.error("Foundation run completed with blocking QA failures.")
            return 1

        LOGGER.info(
            "Foundation run completed with status %s.",
            final_status,
        )
        return 0
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command=command_name,
                parameters={"options": include_options},
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("%s run failed.", command_name)
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=[f"{command_name} run failed before completion."],
        )
        return 1


def _foundation_result_as_of_date(result: object) -> date:
    market_snapshots = getattr(result, "normalized_market_snapshots", pd.DataFrame())
    if isinstance(market_snapshots, pd.DataFrame) and not market_snapshots.empty:
        if "snapshot_date" in market_snapshots.columns:
            values = market_snapshots["snapshot_date"].dropna()
            if not values.empty:
                return pd.to_datetime(values.max()).date()
    gold_history = getattr(result, "gold_history", pd.DataFrame())
    if isinstance(gold_history, pd.DataFrame) and not gold_history.empty:
        if "date" in gold_history.columns:
            values = gold_history["date"].dropna()
            if not values.empty:
                return pd.to_datetime(values.max()).date()
    return pd.Timestamp.utcnow().date()


def run_hedge_readiness(
    paths: ProjectPaths,
    *,
    comparison_sort_by: str | None = None,
    ranking_sort_by: str | None = None,
    ranking_max_tickers: int | None = None,
    speculation_max_tickers: int | None = None,
    quantity: int | None = None,
) -> int:
    run_context: RunContext | None = None
    parameters = {
        "comparison_sort_by": comparison_sort_by,
        "ranking_sort_by": ranking_sort_by,
        "ranking_max_tickers": ranking_max_tickers,
        "speculation_max_tickers": speculation_max_tickers,
        "quantity": quantity,
    }
    try:
        loaded_config = load_app_config(paths)
        run_context = RunContext.start(
            paths=paths,
            command="hedge-readiness",
            parameters=parameters,
            config_hash=loaded_config.combined_hash,
        )
        configure_logging(run_context.log_path)
        report = write_hedge_readiness_report(
            paths=paths,
            run_context=run_context,
            app_config=loaded_config.app,
            comparison_sort_by=comparison_sort_by,
            ranking_sort_by=ranking_sort_by,
            ranking_max_tickers=ranking_max_tickers,
            speculation_max_tickers=speculation_max_tickers,
            quantity=quantity,
        )
        context_alignment_status = str(
            report.summary.get("context_alignment_status") or "OK"
        )
        final_status = "PASS" if context_alignment_status == "OK" else "WARN"
        notes = [
            "Hedge-readiness report rendered.",
            f"Report path: {report.report_path.relative_to(paths.repo_root).as_posix()}.",
        ]
        context_alignment_message = report.summary.get("context_alignment_message")
        if context_alignment_message:
            notes.append(f"Context alignment: {context_alignment_message}")
        run_context.write_json("hedge_readiness_summary.json", report.summary)
        run_context.finalize(
            status=final_status,
            summary=report.summary,
            notes=notes,
        )
        print(
            "Hedge readiness report written: "
            f"{report.report_path.relative_to(paths.repo_root).as_posix()}"
        )
        print(
            "Summary: "
            f"{report.summary['directly_hedgeable_count']} directly hedgeable, "
            f"{report.summary['thin_count']} thin, "
            f"{report.summary['none_count']} no listed options, "
            f"{report.summary['holdings_count']} holdings."
        )
        if final_status == "WARN":
            print(
                f"Context alignment: {context_alignment_status} - "
                f"{context_alignment_message}"
            )
        return 0
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command="hedge-readiness",
                parameters=parameters,
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("Hedge-readiness report failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["Hedge-readiness report failed before completion."],
        )
        print(f"Hedge readiness report failed: {exc}")
        return 1


def run_tool_a(paths: ProjectPaths) -> int:
    run_context: RunContext | None = None

    try:
        loaded_config = load_app_config(paths)
        run_context = RunContext.start(
            paths=paths,
            command="tool-a",
            parameters={},
            config_hash=loaded_config.combined_hash,
        )
        configure_logging(run_context.log_path)

        configured_tickers = loaded_config.app.universe.tickers
        active_tickers = [ticker for ticker in configured_tickers if ticker.active]
        tool_a_enabled = [
            ticker for ticker in active_tickers if ticker.tool_a_enabled
        ]
        tool_b_enabled = [
            ticker for ticker in active_tickers if ticker.tool_b_enabled
        ]

        LOGGER.info("Starting Tool A run %s", run_context.run_id)
        config_summary = {
            "configured_ticker_count": len(configured_tickers),
            "active_ticker_count": len(active_tickers),
            "tool_a_enabled_ticker_count": len(tool_a_enabled),
            "tool_b_enabled_ticker_count": len(tool_b_enabled),
            "exploratory_horizon_count": len(loaded_config.app.horizons.core_horizons),
            "structural_window_count": len(loaded_config.app.scoring.structural_windows),
            "combined_config_hash": loaded_config.combined_hash,
        }
        run_context.write_json("config_summary.json", config_summary)
        if not tool_a_enabled:
            run_context.finalize(
                status="FAIL",
                summary=config_summary,
                notes=["Tool A cannot run because no active Tool A tickers are configured."],
            )
            LOGGER.error("Tool A stopped because no active Tool A tickers are configured.")
            return 1

        foundation_snapshot = _load_latest_foundation_snapshot(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            include_gold_history=True,
            include_equity_histories=True,
            include_market_snapshots=False,
        )
        _capture_foundation_for_replay_manifest(run_context, foundation_snapshot)

        tool_a_result = execute_tool_a_profile_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            gold_history=foundation_snapshot.gold_history,
            normalized_equity_histories=foundation_snapshot.normalized_equity_histories,
            snapshot_refresh_run_id=foundation_snapshot.refresh_run_id,
        )
        run_context.write_json("tool_a_output_summary.json", tool_a_result.summary)

        overall_status = _combine_statuses(
            foundation_snapshot.raw_qa_summary.get("overall_status"),
            foundation_snapshot.normalization_qa_summary.get("overall_status"),
            tool_a_result.overall_status,
        )
        run_context.write_json(
            "qa_summary.json",
            {
                "overall_status": overall_status,
                "raw": foundation_snapshot.raw_qa_summary,
                "normalization": foundation_snapshot.normalization_qa_summary,
                "tool_a_output": tool_a_result.summary,
            },
        )
        notes = [
            "Tool A ran from the latest validated local market-data snapshot.",
            f"Snapshot refresh run: {foundation_snapshot.refresh_run_id}.",
            f"Snapshot as-of date: {foundation_snapshot.snapshot_as_of_date}.",
            f"Raw QA status: {foundation_snapshot.raw_qa_summary.get('overall_status')}.",
            f"Normalization QA status: {foundation_snapshot.normalization_qa_summary.get('overall_status')}.",
            "Official Tool A scoring now uses the structural weekly model.",
            "Custom horizon analytics remain exploratory only.",
            f"Tool A output status: {tool_a_result.overall_status}.",
        ]
        run_context.finalize(
            status=overall_status,
            summary={
                **config_summary,
                **foundation_snapshot.summary,
                "snapshot_refresh_run_id": foundation_snapshot.refresh_run_id,
                "snapshot_as_of_date": foundation_snapshot.snapshot_as_of_date,
                **tool_a_result.summary,
            },
            notes=notes,
        )

        if overall_status == "FAIL":
            LOGGER.error("Tool A run completed with blocking failures.")
            return 1

        LOGGER.info("Tool A run completed with status %s.", overall_status)
        return 0
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command="tool-a",
                parameters={},
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("Tool A run failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["Tool A run failed before completion."],
        )
        return 1


def run_tool_c(
    paths: ProjectPaths,
    *,
    _use_model_state_inputs: bool = True,
) -> int:
    run_context: RunContext | None = None

    try:
        loaded_config = load_app_config(paths)
        run_context = RunContext.start(
            paths=paths,
            command="tool-c",
            parameters={},
            config_hash=loaded_config.combined_hash,
        )
        configure_logging(run_context.log_path)

        configured_tickers = loaded_config.app.universe.tickers
        active_tickers = [ticker for ticker in configured_tickers if ticker.active]
        tool_a_enabled = [
            ticker for ticker in active_tickers if ticker.tool_a_enabled
        ]
        config_summary = {
            "configured_ticker_count": len(configured_tickers),
            "active_ticker_count": len(active_tickers),
            "tool_a_enabled_ticker_count": len(tool_a_enabled),
            "combined_config_hash": loaded_config.combined_hash,
            "tool_c_min_events": loaded_config.app.tool_c.min_events,
            "tool_c_regime_rolling_weeks": loaded_config.app.tool_c.regime_rolling_weeks,
            "tool_c_regime_min_weeks": loaded_config.app.tool_c.regime_min_weeks,
        }
        run_context.write_json("config_summary.json", config_summary)
        if not tool_a_enabled:
            run_context.finalize(
                status="FAIL",
                summary=config_summary,
                notes=["Tool C cannot run because no active Tool A tickers are configured."],
            )
            LOGGER.error("Tool C stopped because no active Tool A tickers are configured.")
            return 1

        foundation_snapshot = _load_latest_foundation_snapshot(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            include_gold_history=True,
            include_equity_histories=True,
            include_market_snapshots=False,
            use_model_state=_use_model_state_inputs,
        )
        _capture_foundation_for_replay_manifest(run_context, foundation_snapshot)

        tool_a_latest_path = _tool_input_path(
            paths=paths,
            artifact_name="tool_a",
            fallback_path=paths.latest_tool_a_snapshot_parquet_path,
            use_model_state=_use_model_state_inputs,
            missing_message="No Tool A current output exists yet. Run `python main.py tool-a` first.",
        )
        tool_a_latest = pd.read_parquet(tool_a_latest_path)
        benchmark_histories = _load_cached_benchmark_histories(
            paths=paths,
            app_config=loaded_config.app,
        )
        tool_c_outputs = compute_tool_c_outputs(
            inputs=ToolCExecutionInputs(
                normalized_equity_histories=foundation_snapshot.normalized_equity_histories,
                gold_history=foundation_snapshot.gold_history,
                benchmark_histories=benchmark_histories,
                tool_a_latest=tool_a_latest,
            ),
            config=loaded_config.app.tool_c,
            source_run_id=run_context.run_id,
        )
        source_paths = _tool_c_source_paths(
            paths=paths,
            foundation_snapshot=foundation_snapshot,
            app_config=loaded_config.app,
            tool_a_latest_path=tool_a_latest_path,
        )
        persist_tool_c_outputs(
            paths=paths,
            run_context=run_context,
            tool_c_outputs=tool_c_outputs,
            source_paths=source_paths,
            publish_latest_aliases=not tool_c_outputs.empty,
        )

        ranked_downside = (
            int(tool_c_outputs["tool_c_downside_rank"].notna().sum())
            if "tool_c_downside_rank" in tool_c_outputs.columns
            else 0
        )
        ranked_upside = (
            int(tool_c_outputs["tool_c_upside_rank"].notna().sum())
            if "tool_c_upside_rank" in tool_c_outputs.columns
            else 0
        )
        tool_c_status = "PASS"
        if tool_c_outputs.empty:
            tool_c_status = "FAIL"
        elif ranked_downside == 0 and ranked_upside == 0:
            tool_c_status = "WARN"
        summary = {
            "tool_c_output_row_count": len(tool_c_outputs.index),
            "tool_c_ranked_downside_row_count": ranked_downside,
            "tool_c_ranked_upside_row_count": ranked_upside,
            "tool_c_output_overall_status": tool_c_status,
            "benchmark_history_count": len(benchmark_histories),
        }
        run_context.write_json("tool_c_output_summary.json", summary)
        overall_status = _combine_statuses(
            foundation_snapshot.raw_qa_summary.get("overall_status"),
            foundation_snapshot.normalization_qa_summary.get("overall_status"),
            tool_c_status,
        )
        run_context.write_json(
            "qa_summary.json",
            {
                "overall_status": overall_status,
                "raw": foundation_snapshot.raw_qa_summary,
                "normalization": foundation_snapshot.normalization_qa_summary,
                "tool_c_output": summary,
            },
        )
        notes = [
            "Tool C ran from the latest validated local market-data snapshot, latest Tool A output, and cached benchmark histories.",
            f"Snapshot refresh run: {foundation_snapshot.refresh_run_id}.",
            f"Snapshot as-of date: {foundation_snapshot.snapshot_as_of_date}.",
            f"Tool C output status: {tool_c_status}.",
        ]
        run_context.finalize(
            status=overall_status,
            summary={
                **config_summary,
                **foundation_snapshot.summary,
                "snapshot_refresh_run_id": foundation_snapshot.refresh_run_id,
                "snapshot_as_of_date": foundation_snapshot.snapshot_as_of_date,
                **summary,
            },
            notes=notes,
        )

        if overall_status == "FAIL":
            LOGGER.error("Tool C run completed with blocking failures.")
            return 1

        LOGGER.info("Tool C run completed with status %s.", overall_status)
        return 0
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command="tool-c",
                parameters={},
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("Tool C run failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["Tool C run failed before completion."],
        )
        return 1


def run_tool_d(
    paths: ProjectPaths,
    *,
    gold_price: float | None,
    _use_model_state_inputs: bool = True,
) -> int:
    run_context: RunContext | None = None

    try:
        loaded_config = load_app_config(paths)
        run_context = RunContext.start(
            paths=paths,
            command="tool-d",
            parameters={"gold_price": gold_price},
            config_hash=loaded_config.combined_hash,
        )
        configure_logging(run_context.log_path)

        configured_tickers = loaded_config.app.universe.tickers
        active_tickers = [ticker for ticker in configured_tickers if ticker.active]
        tool_b_enabled = [
            ticker for ticker in active_tickers if ticker.tool_b_enabled
        ]
        config_summary = {
            "configured_ticker_count": len(configured_tickers),
            "active_ticker_count": len(active_tickers),
            "tool_b_enabled_ticker_count": len(tool_b_enabled),
            "combined_config_hash": loaded_config.combined_hash,
        }
        run_context.write_json("config_summary.json", config_summary)
        if not tool_b_enabled:
            run_context.finalize(
                status="FAIL",
                summary=config_summary,
                notes=["Tool D cannot run because no active Tool B tickers are configured."],
            )
            LOGGER.error("Tool D stopped because no active Tool B tickers are configured.")
            return 1
        if not manual_store_exists(paths):
            missing_store_note = _missing_manual_store_note()
            run_context.finalize(
                status="FAIL",
                summary=config_summary,
                notes=[missing_store_note],
            )
            LOGGER.error("%s", missing_store_note)
            return 1

        foundation_snapshot = _load_latest_foundation_snapshot(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            include_gold_history=True,
            include_equity_histories=False,
            include_market_snapshots=True,
            use_model_state=_use_model_state_inputs,
        )
        _capture_foundation_for_replay_manifest(run_context, foundation_snapshot)
        spot_gold_usd, spot_gold_date = _spot_gold_from_history(
            foundation_snapshot.gold_history
        )
        resolved_gold_price = float(gold_price) if gold_price is not None else spot_gold_usd
        if resolved_gold_price <= 0:
            raise ValueError("gold price must be positive")

        tool_b_latest_path = _tool_input_path(
            paths=paths,
            artifact_name="tool_b",
            fallback_path=paths.latest_tool_b_snapshot_parquet_path,
            use_model_state=_use_model_state_inputs,
            missing_message="No Tool B current output exists yet. Run `python main.py tool-b` first.",
        )
        tool_b_latest = pd.read_parquet(tool_b_latest_path)
        manual_data = load_manual_screening_data(
            paths,
            tickers=sorted(
                ticker.ticker
                for ticker in loaded_config.app.universe.tickers
                if ticker.active and ticker.tool_b_enabled
            ),
        )
        tool_d_outputs = compute_tool_d_outputs(
            inputs=ToolDExecutionInputs(
                app_config=loaded_config.app,
                manual_data=manual_data,
                normalized_market_snapshots=foundation_snapshot.normalized_market_snapshots,
                tool_b_latest=tool_b_latest,
                spot_gold_usd=spot_gold_usd,
                spot_gold_date=spot_gold_date,
                snapshot_refresh_run_id=foundation_snapshot.refresh_run_id,
                snapshot_as_of_date=foundation_snapshot.snapshot_as_of_date,
            ),
            config=loaded_config.app.tool_d,
            gold_price=resolved_gold_price,
            source_run_id=run_context.run_id,
        )
        persist_tool_d_outputs(
            paths=paths,
            run_context=run_context,
            tool_d_outputs=tool_d_outputs,
            source_paths=_tool_d_source_paths(
                paths=paths,
                foundation_snapshot=foundation_snapshot,
                tool_b_latest_path=tool_b_latest_path,
            ),
            provenance_metadata={
                "gold_price_used": resolved_gold_price,
                "spot_gold_usd": spot_gold_usd,
                "spot_gold_date": spot_gold_date,
            },
            publish_latest_aliases=not tool_d_outputs.empty,
            publish_spot_latest_aliases=(
                not tool_d_outputs.empty
                and _is_same_gold_price(resolved_gold_price, spot_gold_usd)
            ),
        )

        ranked = (
            int(tool_d_outputs["tool_d_quality_rank"].notna().sum())
            if "tool_d_quality_rank" in tool_d_outputs.columns
            else 0
        )
        tool_d_status = "PASS"
        if tool_d_outputs.empty:
            tool_d_status = "FAIL"
        elif ranked == 0:
            tool_d_status = "WARN"
        summary = {
            "tool_d_output_row_count": len(tool_d_outputs.index),
            "tool_d_ranked_row_count": ranked,
            "tool_d_output_overall_status": tool_d_status,
            "gold_price_used": resolved_gold_price,
            "spot_gold_usd": spot_gold_usd,
            "spot_gold_date": spot_gold_date,
        }
        run_context.write_json("tool_d_output_summary.json", summary)
        overall_status = _combine_statuses(
            foundation_snapshot.raw_qa_summary.get("overall_status"),
            foundation_snapshot.normalization_qa_summary.get("overall_status"),
            tool_d_status,
        )
        run_context.write_json(
            "qa_summary.json",
            {
                "overall_status": overall_status,
                "raw": foundation_snapshot.raw_qa_summary,
                "normalization": foundation_snapshot.normalization_qa_summary,
                "tool_d_output": summary,
            },
        )
        notes = [
            "Tool D ran from the latest validated local market-data snapshot, latest Tool B output, and the local manual-data store.",
            f"Snapshot refresh run: {foundation_snapshot.refresh_run_id}.",
            f"Spot gold reference: ${spot_gold_usd:.2f}/oz on {spot_gold_date}.",
            f"Gold price used: ${resolved_gold_price:.2f}/oz.",
            f"Tool D output status: {tool_d_status}.",
        ]
        run_context.finalize(
            status=overall_status,
            summary={
                **config_summary,
                **foundation_snapshot.summary,
                "snapshot_refresh_run_id": foundation_snapshot.refresh_run_id,
                "snapshot_as_of_date": foundation_snapshot.snapshot_as_of_date,
                **summary,
            },
            notes=notes,
        )

        if overall_status == "FAIL":
            LOGGER.error("Tool D run completed with blocking failures.")
            return 1

        LOGGER.info("Tool D run completed with status %s.", overall_status)
        return 0
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command="tool-d",
                parameters={"gold_price": gold_price},
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("Tool D run failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["Tool D run failed before completion."],
        )
        return 1


def _is_same_gold_price(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= 0.01


def run_option_artifacts(
    paths: ProjectPaths,
    *,
    parent_refresh_id: str | None,
) -> int:
    run_context: RunContext | None = None

    try:
        loaded_config = load_app_config(paths)
        run_context = RunContext.start(
            paths=paths,
            command="option-artifacts",
            parameters={"parent_refresh_id": parent_refresh_id},
            config_hash=loaded_config.combined_hash,
        )
        configure_logging(run_context.log_path)

        sources = load_option_artifact_source_inputs(paths, use_model_state=False)
        if sources is None:
            run_context.finalize(
                status="FAIL",
                summary={"error": "No latest options manifest is available."},
                notes=["Option artifacts require the latest options manifest."],
            )
            LOGGER.error("Option artifact build stopped because no options manifest exists.")
            return 1

        built = build_option_artifact_inputs(
            app_config=loaded_config.app,
            features=sources.features,
            tool_a=sources.tool_a,
            tool_b=sources.tool_b,
            chains=sources.chains,
            risk_free_rate=sources.risk_free_rate,
            risk_free_rate_is_fallback=sources.risk_free_rate_is_fallback,
            manifest=sources.manifest,
        )
        contract_metrics = scan_option_contract_metrics(
            app_config=loaded_config.app,
            features=sources.features,
            tool_b=sources.tool_b,
            chains=sources.chains,
            risk_free_rate=sources.risk_free_rate,
            manifest=sources.manifest,
        )
        frames = build_option_artifact_frames(
            built=built,
            contract_metrics=contract_metrics,
            options_features=sources.features,
            manifest=sources.manifest,
            source_run_id=run_context.run_id,
            parent_refresh_id=parent_refresh_id,
            config_hash=loaded_config.combined_hash,
            risk_free_rate=sources.risk_free_rate,
            risk_free_rate_is_fallback=sources.risk_free_rate_is_fallback,
        )
        persist_option_artifact_frames(
            paths=paths,
            run_context=run_context,
            frames=frames,
        )

        row_counts = {name: int(len(frame.index)) for name, frame in frames.items()}
        summary = {
            "option_artifact_status": "PASS",
            "options_refresh_run_id": str(sources.manifest.get("refresh_run_id") or ""),
            "options_as_of_date": str(sources.manifest.get("as_of_date") or ""),
            "parent_refresh_id": parent_refresh_id,
            "risk_free_rate": sources.risk_free_rate,
            "risk_free_rate_is_fallback": sources.risk_free_rate_is_fallback,
            "artifact_row_counts": row_counts,
        }
        run_context.write_json("option_artifact_summary.json", summary)
        run_context.finalize(
            status="PASS",
            summary=summary,
            notes=[
                "Option artifacts were built from latest local options, Tool A, and Tool B outputs.",
                "The model-state manifest is published only after this step succeeds.",
            ],
        )
        LOGGER.info("Option artifact build completed.")
        return 0
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command="option-artifacts",
                parameters={"parent_refresh_id": parent_refresh_id},
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("Option artifact build failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["Option artifact build failed before completion."],
        )
        return 1


def run_tool_b(paths: ProjectPaths, *, gold_price: float | None) -> int:
    run_context: RunContext | None = None

    try:
        loaded_config = load_app_config(paths)
        # Resolve gold price: CLI override → config default → first scenario.
        # This lets `tool-b` (and the new `refresh` command) work without
        # requiring the user to remember the magic number every run.
        resolved_gold_price = loaded_config.app.screening_params.resolve_gold_price(gold_price)
        if resolved_gold_price <= 0:
            raise ValueError("gold price must be positive")
        gold_price = resolved_gold_price

        run_context = RunContext.start(
            paths=paths,
            command="tool-b",
            parameters={"gold_price": gold_price},
            config_hash=loaded_config.combined_hash,
        )
        configure_logging(run_context.log_path)

        configured_tickers = loaded_config.app.universe.tickers
        active_tickers = [ticker for ticker in configured_tickers if ticker.active]
        tool_a_enabled = [
            ticker for ticker in active_tickers if ticker.tool_a_enabled
        ]
        tool_b_enabled = [
            ticker for ticker in active_tickers if ticker.tool_b_enabled
        ]

        LOGGER.info("Starting Tool B run %s", run_context.run_id)
        config_summary = {
            "configured_ticker_count": len(configured_tickers),
            "active_ticker_count": len(active_tickers),
            "tool_a_enabled_ticker_count": len(tool_a_enabled),
            "tool_b_enabled_ticker_count": len(tool_b_enabled),
            "gold_price_assumption": gold_price,
            "configured_gold_price_scenarios": loaded_config.app.screening_params.gold_price_scenarios,
            "combined_config_hash": loaded_config.combined_hash,
        }
        run_context.write_json("config_summary.json", config_summary)
        if not tool_b_enabled:
            run_context.finalize(
                status="FAIL",
                summary=config_summary,
                notes=["Tool B cannot run because no active Tool B tickers are configured."],
            )
            LOGGER.error("Tool B stopped because no active Tool B tickers are configured.")
            return 1

        if not manual_store_exists(paths):
            missing_store_note = _missing_manual_store_note()
            run_context.finalize(
                status="FAIL",
                summary=config_summary,
                notes=[missing_store_note],
            )
            LOGGER.error("%s", missing_store_note)
            return 1

        foundation_snapshot = _load_latest_foundation_snapshot(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            include_gold_history=False,
            include_equity_histories=False,
            include_market_snapshots=True,
        )
        _capture_foundation_for_replay_manifest(run_context, foundation_snapshot)

        tool_b_result = execute_tool_b_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            normalized_market_snapshots=foundation_snapshot.normalized_market_snapshots,
            gold_price_assumption=gold_price,
            snapshot_refresh_run_id=foundation_snapshot.refresh_run_id,
            snapshot_as_of_date=foundation_snapshot.snapshot_as_of_date,
        )
        run_context.write_json("tool_b_output_summary.json", tool_b_result.summary)

        overall_status = _combine_statuses(
            foundation_snapshot.raw_qa_summary.get("overall_status"),
            foundation_snapshot.normalization_qa_summary.get("overall_status"),
            tool_b_result.overall_status,
        )
        run_context.write_json(
            "qa_summary.json",
            {
                "overall_status": overall_status,
                "raw": foundation_snapshot.raw_qa_summary,
                "normalization": foundation_snapshot.normalization_qa_summary,
                "tool_b_output": tool_b_result.summary,
            },
        )
        notes = [
            "Tool B ran from the latest validated local market-data snapshot and the local Tool B manual-data store.",
            f"Snapshot refresh run: {foundation_snapshot.refresh_run_id}.",
            f"Snapshot as-of date: {foundation_snapshot.snapshot_as_of_date}.",
            f"Raw QA status: {foundation_snapshot.raw_qa_summary.get('overall_status')}.",
            f"Normalization QA status: {foundation_snapshot.normalization_qa_summary.get('overall_status')}.",
            f"Tool B output status: {tool_b_result.overall_status}.",
        ]
        if tool_b_result.summary.get("manual_store_created"):
            notes.append("A new local Tool B manual-data store was created automatically.")
        if tool_b_result.summary.get("manual_csv_imported_files"):
            notes.append("Legacy support CSV files were imported into the local Tool B manual-data store.")
        run_context.finalize(
            status=overall_status,
            summary={
                **config_summary,
                **foundation_snapshot.summary,
                "snapshot_refresh_run_id": foundation_snapshot.refresh_run_id,
                "snapshot_as_of_date": foundation_snapshot.snapshot_as_of_date,
                **tool_b_result.summary,
            },
            notes=notes,
        )

        if overall_status == "FAIL":
            LOGGER.error("Tool B run completed with blocking failures.")
            return 1

        LOGGER.info("Tool B run completed with status %s.", overall_status)
        return 0
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command="tool-b",
                parameters={"gold_price": gold_price},
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("Tool B run failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["Tool B run failed before completion."],
        )
        return 1


def run_manual_data(paths: ProjectPaths, args: argparse.Namespace) -> int:
    run_context: RunContext | None = None

    try:
        loaded_config = load_app_config(paths)
        command_name = f"manual-data-{args.manual_data_command}"
        parameters = {
            key: value
            for key, value in vars(args).items()
            if key not in {"command", "manual_data_command"} and value is not None
        }
        run_context = RunContext.start(
            paths=paths,
            command=command_name,
            parameters=parameters,
            config_hash=loaded_config.combined_hash,
        )
        configure_logging(run_context.log_path)

        tool_b_tickers = _active_tool_b_tickers(loaded_config)
        tool_b_universe = set(tool_b_tickers)

        if args.manual_data_command == "init":
            loaded = bootstrap_manual_screening_data(
                paths,
                tickers=tool_b_tickers,
                import_csv_if_empty=False,
            )
            summary = {
                "manual_store_path": str(loaded.store_path),
                "store_created": loaded.store_created,
                "seeded_ticker_count": len(loaded.seeded_tickers),
                "csv_import_count": len(loaded.imported_csv_files),
                "company_input_row_count": len(loaded.company_inputs.index),
                "source_verification_row_count": len(loaded.source_verification.index),
                "reporting_calendar_row_count": len(loaded.reporting_calendar.index),
                "stock_note_row_count": len(loaded.stock_notes.index),
            }
            if loaded.imported_csv_files:
                summary["imported_csv_files"] = loaded.imported_csv_files
            run_context.write_json("manual_data_summary.json", summary)
            run_context.finalize(
                status="PASS",
                summary=summary,
                notes=[
                    "Manual Tool B data store is ready for direct in-tool editing.",
                    f"Store path: {loaded.store_path.relative_to(paths.repo_root).as_posix()}.",
                ],
            )
            print(json.dumps(to_jsonable(summary), indent=2))
            return 0

        if args.manual_data_command == "import-csv":
            result = import_support_csvs_into_store(paths, tickers=tool_b_tickers)
            summary = {
                "manual_store_path": str(result.store_path),
                "store_created": result.created_store,
                "seeded_ticker_count": len(result.seeded_tickers),
                "csv_import_count": len(result.imported_csv_files),
            }
            if result.imported_csv_files:
                summary["imported_csv_files"] = result.imported_csv_files
            run_context.write_json("manual_data_import_summary.json", summary)
            run_context.finalize(
                status="PASS",
                summary=summary,
                notes=["Support CSV files were imported into the local Tool B manual-data store."],
            )
            print(json.dumps(to_jsonable(summary), indent=2))
            return 0

        if args.manual_data_command == "export-csv":
            if not manual_store_exists(paths):
                missing_store_note = _missing_manual_store_note()
                run_context.finalize(
                    status="FAIL",
                    summary={"manual_store_path": str(paths.manual_screening_store_path)},
                    notes=[missing_store_note],
                )
                LOGGER.error("%s", missing_store_note)
                return 1
            export_result = export_store_to_csv(paths)
            summary = {
                "manual_store_path": str(paths.manual_screening_store_path),
                "exported_file_count": len(export_result.exported_files),
                "exported_files": export_result.exported_files,
                "backup_file_count": len(export_result.backup_files),
            }
            if export_result.backup_files:
                summary["backup_files"] = export_result.backup_files
            run_context.write_json("manual_data_export_summary.json", summary)
            run_context.finalize(
                status="PASS",
                summary=summary,
                notes=[
                    "The local Tool B manual-data store was exported to support CSV files.",
                    "Existing support CSV files were backed up before overwrite."
                    if export_result.backup_files
                    else "No existing support CSV files needed backup.",
                ],
            )
            print(json.dumps(to_jsonable(summary), indent=2))
            return 0

        ticker = str(args.ticker).strip().upper()
        if ticker not in tool_b_universe:
            run_context.finalize(
                status="FAIL",
                summary={"ticker": ticker},
                notes=[f"{ticker} is not an active Tool B ticker in the configured universe."],
            )
            return 1

        if not manual_store_exists(paths):
            missing_store_note = _missing_manual_store_note()
            run_context.finalize(
                status="FAIL",
                summary={"ticker": ticker, "manual_store_path": str(paths.manual_screening_store_path)},
                notes=[missing_store_note],
            )
            LOGGER.error("%s", missing_store_note)
            return 1

        if args.manual_data_command == "show":
            loaded = load_manual_screening_data(paths, tickers=tool_b_tickers)
            company_row = loaded.company_inputs[loaded.company_inputs["ticker"] == ticker].to_dict(orient="records")
            reporting_row = loaded.reporting_calendar[loaded.reporting_calendar["ticker"] == ticker].to_dict(orient="records")
            verification_rows = loaded.source_verification[
                loaded.source_verification["ticker"] == ticker
            ].to_dict(orient="records")
            note_rows = loaded.stock_notes[
                loaded.stock_notes["ticker"] == ticker
            ].to_dict(orient="records")
            payload = {
                "ticker": ticker,
                "company_inputs": company_row[0] if company_row else None,
                "reporting_calendar": reporting_row[0] if reporting_row else None,
                "source_verification": verification_rows,
                "stock_notes": note_rows,
                "manual_store_path": str(loaded.store_path),
            }
            run_context.write_json("manual_data_show.json", payload)
            run_context.finalize(
                status="PASS",
                summary={
                    "ticker": ticker,
                    "verification_row_count": len(verification_rows),
                    "stock_note_row_count": len(note_rows),
                },
                notes=[f"Displayed local Tool B manual data for {ticker}."],
            )
            print(json.dumps(to_jsonable(payload), indent=2))
            return 0

        if args.manual_data_command == "set-company":
            values = {
                "production_oz": args.production_oz,
                "aisc_usd_per_oz": args.aisc_usd_per_oz,
                "cash_cost_usd_per_oz": args.cash_cost_usd_per_oz,
                "royalty_rate": args.royalty_rate,
                "sustaining_capex_musd": args.sustaining_capex_musd,
                "da_musd": args.da_musd,
                "interest_expense_musd": args.interest_expense_musd,
                "tax_rate": args.tax_rate,
                "reserve_life_years": args.reserve_life_years,
                "net_debt_musd": args.net_debt_musd,
                "ebitda_ltm_musd": args.ebitda_ltm_musd,
            }
            clear_fields = sorted(set(getattr(args, "clear_fields", []) or []))
            provided_values = {
                key: value for key, value in values.items() if value is not None
            }
            provided_values.update({field_name: None for field_name in clear_fields})
            if not provided_values:
                run_context.finalize(
                    status="FAIL",
                    summary={"ticker": ticker},
                    notes=["manual-data set-company requires at least one field to update."],
                )
                return 1
            upsert_company_input(paths, ticker=ticker, values=provided_values)
            run_context.finalize(
                status="PASS",
                summary={"ticker": ticker, "updated_field_count": len(provided_values)},
                notes=[f"Updated {len(provided_values)} Tool B company-input field(s) for {ticker}."],
            )
            print(
                json.dumps(
                    to_jsonable(
                        {"ticker": ticker, "updated_fields": sorted(provided_values)}
                    ),
                    indent=2,
                )
            )
            return 0

        if args.manual_data_command == "set-reporting":
            updates = {
                "next_financial_report_date": args.next_financial_report_date,
                "next_production_report_date": args.next_production_report_date,
                "notes": args.notes,
            }
            clear_fields = sorted(set(getattr(args, "clear_fields", []) or []))
            provided_updates = {
                key: value for key, value in updates.items() if value is not None
            }
            provided_updates.update({field_name: None for field_name in clear_fields})
            if not provided_updates:
                run_context.finalize(
                    status="FAIL",
                    summary={"ticker": ticker},
                    notes=["manual-data set-reporting requires at least one field to update."],
                )
                return 1
            upsert_reporting_calendar(
                paths,
                ticker=ticker,
                values=provided_updates,
            )
            run_context.finalize(
                status="PASS",
                summary={"ticker": ticker, "updated_field_count": len(provided_updates)},
                notes=[f"Updated reporting-calendar data for {ticker}."],
            )
            print(json.dumps(to_jsonable({"ticker": ticker, "updated_fields": sorted(provided_updates)}), indent=2))
            return 0

        if args.manual_data_command == "set-verification":
            verification_values = {}
            if args.source_date is not None:
                verification_values["source_date"] = args.source_date
            if args.source_url is not None:
                verification_values["source_url"] = args.source_url
            if args.notes is not None:
                verification_values["notes"] = args.notes
            for field_name in sorted(set(getattr(args, "clear_fields", []) or [])):
                verification_values[field_name] = None
            upsert_source_verification(
                paths,
                ticker=ticker,
                field_name=args.field_name,
                verification_status=args.verification_status,
                values=verification_values,
            )
            run_context.finalize(
                status="PASS",
                summary={"ticker": ticker, "field_name": args.field_name},
                notes=[f"Updated Tool B source verification for {ticker} / {args.field_name}."],
            )
            print(
                json.dumps(
                    to_jsonable(
                    {
                        "ticker": ticker,
                        "field_name": args.field_name,
                        "verification_status": str(args.verification_status).upper(),
                    }
                    ),
                    indent=2,
                )
            )
            return 0

        raise ValueError(f"Unsupported manual-data command: {args.manual_data_command}")
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command=f"manual-data-{getattr(args, 'manual_data_command', 'unknown')}",
                parameters={},
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("manual-data command failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["manual-data command failed before completion."],
        )
        return 1


def run_manual_note(paths: ProjectPaths, args: argparse.Namespace) -> int:
    run_context: RunContext | None = None

    try:
        loaded_config = load_app_config(paths)
        command_name = f"manual-note-{args.manual_note_command}"
        parameters = {
            key: value
            for key, value in vars(args).items()
            if key not in {"command", "manual_note_command"} and value is not None
        }
        run_context = RunContext.start(
            paths=paths,
            command=command_name,
            parameters=parameters,
            config_hash=loaded_config.combined_hash,
        )
        configure_logging(run_context.log_path)

        tool_b_tickers = _active_tool_b_tickers(loaded_config)
        if not manual_store_exists(paths):
            missing_store_note = _missing_manual_store_note()
            run_context.finalize(
                status="FAIL",
                summary={"manual_store_path": str(paths.manual_screening_store_path)},
                notes=[missing_store_note],
            )
            LOGGER.error("%s", missing_store_note)
            return 1

        if args.manual_note_command == "add":
            ticker = str(args.ticker).strip().upper()
            if ticker not in set(tool_b_tickers):
                run_context.finalize(
                    status="FAIL",
                    summary={"ticker": ticker},
                    notes=[f"{ticker} is not an active Tool B ticker in the configured universe."],
                )
                return 1
            note_id = add_stock_note(
                paths,
                ticker=ticker,
                note_text=args.note,
                note_tag=args.tag,
                note_status=args.status,
            )
            summary = {"ticker": ticker, "note_id": note_id}
            run_context.write_json("manual_note_add.json", summary)
            run_context.finalize(
                status="PASS",
                summary=summary,
                notes=[f"Added a stock note for {ticker}."],
            )
            print(json.dumps(to_jsonable(summary), indent=2))
            return 0

        if args.manual_note_command == "list":
            note_rows = list_stock_notes(
                paths,
                ticker=args.ticker,
                limit=args.limit,
            )
            payload = {
                "ticker": str(args.ticker).strip().upper() if args.ticker else None,
                "limit": int(args.limit),
                "note_count": len(note_rows.index),
                "notes": note_rows.to_dict(orient="records"),
            }
            run_context.write_json("manual_note_list.json", payload)
            run_context.finalize(
                status="PASS",
                summary={
                    "note_count": len(note_rows.index),
                    "ticker": payload["ticker"],
                },
                notes=["Listed stock notes from the local Tool B manual-data store."],
            )
            print(json.dumps(to_jsonable(payload), indent=2))
            return 0

        raise ValueError(f"Unsupported manual-note command: {args.manual_note_command}")
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command=f"manual-note-{getattr(args, 'manual_note_command', 'unknown')}",
                parameters={},
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("manual-note command failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["manual-note command failed before completion."],
        )
        return 1


def _active_tool_b_tickers(loaded_config: object) -> list[str]:
    return sorted(
        {
            ticker.ticker
            for ticker in loaded_config.app.universe.tickers
            if ticker.active and ticker.tool_b_enabled
        }
    )


def run_workspace(
    paths: ProjectPaths,
    *,
    host: str,
    port: int,
) -> int:
    loaded_config = load_app_config(paths)
    tool_b_tickers = _active_tool_b_tickers(loaded_config)
    if not tool_b_tickers:
        LOGGER.error("Workspace cannot start because no active Tool B tickers are configured.")
        return 1

    if not manual_store_exists(paths):
        message = _missing_manual_store_note()
        LOGGER.error("%s", message)
        print(message)
        return 1

    return run_workspace_server(
        paths=paths,
        app_config=loaded_config.app,
        tool_b_tickers=tool_b_tickers,
        host=host,
        port=port,
    )


def run_verify_replay(paths: ProjectPaths, *, run_id_or_path: str) -> int:
    run_dir = _resolve_verify_replay_run_dir(paths, run_id_or_path)
    if not run_dir.exists():
        print(f"Run directory not found: {run_dir}")
        return 1
    result = verify_manifest(run_dir)
    print(_format_verify_replay_result(result))
    return 0 if result.ok else 1


def _resolve_verify_replay_run_dir(paths: ProjectPaths, run_id_or_path: str) -> Path:
    candidate = Path(run_id_or_path)
    if candidate.is_absolute() or candidate.exists() or any(
        separator in run_id_or_path for separator in ("/", "\\")
    ):
        return candidate
    return paths.runs_dir / run_id_or_path


def _format_verify_replay_result(result: VerifyResult) -> str:
    lines = [
        f"Replay manifest: {result.manifest_path}",
    ]
    if result.verdict == VERDICT_PREDATES_REPLAY_MANIFEST:
        lines.extend(
            [
                "",
                "Snapshot integrity:",
                "  [INFO] run predates replay manifests",
                "",
                "Code state at run time:",
                "  unavailable - no replay manifest exists for this run",
                "",
                "Drift since run:",
                "  unavailable - no replay manifest exists for this run",
                "",
                "Verdict: PREDATES REPLAY MANIFEST. This older run has no replay manifest to verify.",
            ]
        )
        return "\n".join(lines)

    lines.append(f"Run directory: {result.run_dir}")
    if result.asset_statuses:
        lines.extend(["", "Snapshot integrity:"])
        for asset in result.asset_statuses:
            # ASCII markers stay readable in older Windows terminals.
            marker = "[OK]" if asset.status == "ok" else "[FAIL]"
            lines.append(f"  {marker} {asset.name} - {asset.message}")
    else:
        lines.extend(["", "Snapshot integrity:", "  [INFO] no snapshot assets recorded"])

    lines.extend(["", "Code state at run time:"])
    lines.extend(_format_recorded_git_state(result.run_dir))

    lines.extend(["", "Drift since run:"])
    if result.drift_findings:
        lines.extend(f"  {finding}" for finding in result.drift_findings)
    else:
        lines.append("  unavailable - no current-checkout drift findings")

    verdict = result.verdict.replace("_", " ")
    lines.extend(["", f"Verdict: {verdict}."])
    return "\n".join(lines)


def _format_recorded_git_state(run_dir: Path) -> list[str]:
    manifest_path = run_dir / "replay_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return ["  unavailable - replay manifest could not be read"]

    git_state = manifest.get("git", {})
    if git_state.get("unavailable_reason"):
        return [f"  Git unavailable at run time: {git_state['unavailable_reason']}"]

    dirty = git_state.get("dirty")
    dirty_label = "dirty" if dirty else "clean"
    return [
        f"  Git commit recorded: {git_state.get('commit') or 'unknown'}",
        f"  Working tree at run: {dirty_label}",
    ]


def run_compare_horizons(
    paths: ProjectPaths,
    *,
    ticker: str,
    raw_horizons: str,
    csv_out: str | None,
) -> int:
    run_context: RunContext | None = None

    try:
        normalized_ticker = ticker.strip().upper()
        loaded_config = load_app_config(paths)
        requested_horizons = parse_requested_horizons(
            raw_horizons,
            loaded_config.app.horizons,
        )
        run_context = RunContext.start(
            paths=paths,
            command="compare-horizons",
            parameters={
                "ticker": normalized_ticker,
                "horizons": [item.horizon_id for item in requested_horizons],
                "csv_out": csv_out,
            },
            config_hash=loaded_config.combined_hash,
        )
        configure_logging(run_context.log_path)

        tool_a_tickers = {
            item.ticker
            for item in loaded_config.app.universe.tickers
            if item.active and item.tool_a_enabled
        }
        if normalized_ticker not in tool_a_tickers:
            run_context.finalize(
                status="FAIL",
                summary={"ticker": normalized_ticker},
                notes=[
                    "compare-horizons only supports active Tool A tickers in universe.yaml.",
                ],
            )
            LOGGER.error(
                "compare-horizons stopped because %s is not an active Tool A ticker.",
                normalized_ticker,
            )
            return 1

        foundation_snapshot = _load_latest_foundation_snapshot(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            include_gold_history=True,
            include_equity_histories=True,
            include_market_snapshots=False,
            requested_tickers=[normalized_ticker],
        )
        _capture_foundation_for_replay_manifest(run_context, foundation_snapshot)

        comparison = compute_horizon_returns_for_ticker(
            usd_equity_history=foundation_snapshot.normalized_equity_histories.get(
                normalized_ticker,
                pd.DataFrame(columns=RETURN_COLUMNS),
            ),
            gold_history=foundation_snapshot.gold_history,
            horizons=requested_horizons,
            near_zero_gold_return_threshold=loaded_config.app.qa.near_zero_gold_return_threshold,
        )

        output_path = (
            Path(csv_out)
            if csv_out is not None
            else run_context.run_dir / f"{normalized_ticker.lower()}_horizon_compare.csv"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        comparison.to_csv(output_path, index=False)
        run_context.record_artifact(output_path)
        run_context.write_json(
            "requested_horizons.json",
            {
                "ticker": normalized_ticker,
                "requested_horizons": [
                    {
                        "horizon_id": item.horizon_id,
                        "mode": item.mode,
                        "unit": item.unit,
                        "value": item.value,
                    }
                    for item in requested_horizons
                ],
            },
        )

        pass_rows = int((comparison["coverage_flag"] == "PASS").sum()) if not comparison.empty else 0
        fail_rows = int((comparison["coverage_flag"] == "FAIL").sum()) if not comparison.empty else 0
        comparison_status = "PASS"
        if comparison.empty or pass_rows == 0:
            comparison_status = "FAIL"
        elif fail_rows > 0:
            comparison_status = "WARN"
        overall_status = _combine_statuses(
            foundation_snapshot.raw_qa_summary.get("overall_status"),
            foundation_snapshot.normalization_qa_summary.get("overall_status"),
            comparison_status,
        )
        summary = {
            "ticker": normalized_ticker,
            "requested_horizon_count": len(requested_horizons),
            "comparison_row_count": len(comparison.index),
            "pass_row_count": pass_rows,
            "fail_row_count": fail_rows,
            "snapshot_refresh_run_id": foundation_snapshot.refresh_run_id,
            "snapshot_as_of_date": foundation_snapshot.snapshot_as_of_date,
            "raw_qa_status": foundation_snapshot.raw_qa_summary.get("overall_status"),
            "normalization_qa_status": foundation_snapshot.normalization_qa_summary.get("overall_status"),
            "comparison_status": comparison_status,
            "output_csv": str(output_path),
        }
        run_context.write_json("compare_summary.json", summary)
        run_context.write_json(
            "qa_summary.json",
            {
                "overall_status": overall_status,
                "raw": foundation_snapshot.raw_qa_summary,
                "normalization": foundation_snapshot.normalization_qa_summary,
                "comparison": {
                    "status": comparison_status,
                    "pass_row_count": pass_rows,
                    "fail_row_count": fail_rows,
                },
            },
        )
        run_context.finalize(
            status=overall_status,
            summary=summary,
            notes=[
                "compare-horizons completed from the latest validated local market-data snapshot.",
                "Custom horizons are exploratory only and do not change official scores.",
            ],
        )
        if overall_status == "FAIL":
            LOGGER.error("compare-horizons completed with no usable rows.")
            return 1
        LOGGER.info("compare-horizons completed with status %s.", overall_status)
        return 0
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command="compare-horizons",
                parameters={"ticker": ticker, "horizons": raw_horizons, "csv_out": csv_out},
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("compare-horizons failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["compare-horizons failed before completion."],
        )
        return 1


def _load_cached_benchmark_histories(
    *,
    paths: ProjectPaths,
    app_config: object,
) -> dict[str, pd.DataFrame]:
    histories: dict[str, pd.DataFrame] = {}
    for benchmark in getattr(app_config.benchmarks, "benchmarks", []):
        if not getattr(benchmark, "active", True):
            continue
        ticker = str(benchmark.ticker).upper()
        path = paths.benchmarks_dir / f"{safe_options_file_name(ticker)}.parquet"
        if not path.exists():
            continue
        try:
            histories[ticker] = pd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001 - Tool C can run without benchmark metrics.
            LOGGER.warning("Benchmark history %s could not be read: %s", ticker, exc)
    return histories


def _tool_c_source_paths(
    *,
    paths: ProjectPaths,
    foundation_snapshot: LatestFoundationSnapshot,
    app_config: object,
    tool_a_latest_path: Path,
) -> dict[str, Path]:
    source_paths: dict[str, Path] = {
        "tool_a_latest": tool_a_latest_path,
    }
    try:
        manifest = json.loads(foundation_snapshot.manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - source capture degrades to available files.
        LOGGER.warning("Foundation manifest could not be read for Tool C sources: %s", exc)
        manifest = {}
    for name, field in (
        ("foundation_raw_gold", "gold_history_path"),
        ("foundation_usd_equities", "normalized_equities_snapshot_path"),
    ):
        raw_path = str(manifest.get(field, "")).strip()
        if raw_path:
            source_paths[name] = paths.resolve_repo_relative(raw_path)

    for benchmark in getattr(app_config.benchmarks, "benchmarks", []):
        if not getattr(benchmark, "active", True):
            continue
        ticker = str(benchmark.ticker).upper()
        path = paths.benchmarks_dir / f"{safe_options_file_name(ticker)}.parquet"
        if path.exists():
            source_paths[f"benchmark_{ticker}"] = path
    return source_paths


def _tool_d_source_paths(
    *,
    paths: ProjectPaths,
    foundation_snapshot: LatestFoundationSnapshot,
    tool_b_latest_path: Path,
) -> dict[str, Path]:
    source_paths: dict[str, Path] = {
        "tool_b_latest": tool_b_latest_path,
        "manual_screening_store": paths.manual_screening_store_path,
    }
    try:
        manifest = json.loads(foundation_snapshot.manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - source capture degrades to available files.
        LOGGER.warning("Foundation manifest could not be read for Tool D sources: %s", exc)
        manifest = {}
    raw_gold_path = str(manifest.get("gold_history_path", "")).strip()
    if raw_gold_path:
        source_paths["foundation_raw_gold"] = paths.resolve_repo_relative(raw_gold_path)
    return source_paths


def _spot_gold_from_history(gold_history: pd.DataFrame) -> tuple[float, str | None]:
    if gold_history.empty or "date" not in gold_history.columns:
        raise ValueError("Latest foundation snapshot has no gold history for Tool D spot reference.")
    working = gold_history.copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    if "adj_close_usd" in working.columns:
        working["spot_gold_usd"] = pd.to_numeric(working["adj_close_usd"], errors="coerce")
    else:
        working["spot_gold_usd"] = pd.NA
    if "close_usd" in working.columns:
        working["spot_gold_usd"] = working["spot_gold_usd"].where(
            working["spot_gold_usd"].notna(),
            pd.to_numeric(working["close_usd"], errors="coerce"),
        )
    working = working.loc[
        working["date"].notna() & pd.to_numeric(working["spot_gold_usd"], errors="coerce").gt(0)
    ].copy()
    if working.empty:
        raise ValueError("Latest foundation snapshot has no positive gold close for Tool D.")
    row = working.sort_values("date").iloc[-1]
    return float(row["spot_gold_usd"]), str(pd.Timestamp(row["date"]).date())


def _load_latest_foundation_snapshot(
    *,
    paths: ProjectPaths,
    app_config: object,
    run_context: RunContext,
    include_gold_history: bool = True,
    include_equity_histories: bool = True,
    include_market_snapshots: bool = True,
    requested_tickers: list[str] | None = None,
    use_model_state: bool = False,
) -> LatestFoundationSnapshot:
    manifest_path = None
    if use_model_state:
        manifest_path = resolve_current_foundation_manifest_path(
            paths,
            require_current_manifest=True,
        )
    snapshot = load_latest_foundation_snapshot(
        paths=paths,
        app_config=app_config,
        include_gold_history=include_gold_history,
        include_equity_histories=include_equity_histories,
        include_market_snapshots=include_market_snapshots,
        requested_tickers=requested_tickers,
        manifest_path=manifest_path,
    )
    run_context.write_json(
        "foundation_snapshot_summary.json",
        {
            "refresh_run_id": snapshot.refresh_run_id,
            "snapshot_as_of_date": snapshot.snapshot_as_of_date,
            "foundation_status": snapshot.foundation_status,
            "raw": snapshot.raw_qa_summary,
            "normalization": snapshot.normalization_qa_summary,
            "manifest_path": _artifact_name(paths, snapshot.manifest_path),
        },
    )
    return snapshot


def _capture_foundation_for_replay_manifest(
    run_context: RunContext,
    foundation_snapshot: LatestFoundationSnapshot,
) -> None:
    update_manifest_with_foundation(
        run_dir=run_context.run_dir,
        foundation_run_id=foundation_snapshot.refresh_run_id,
        foundation_manifest_path=foundation_snapshot.manifest_path,
    )


def _artifact_name(paths: ProjectPaths, path: Path) -> str:
    try:
        return path.relative_to(paths.repo_root).as_posix()
    except ValueError:
        return str(path)


def _missing_manual_store_note() -> str:
    return (
        "No local Tool B manual-data store exists yet. "
        "Run `python main.py manual-data init` first."
    )


def _tool_input_path(
    *,
    paths: ProjectPaths,
    artifact_name: str,
    fallback_path: Path,
    use_model_state: bool,
    missing_message: str,
) -> Path:
    if use_model_state:
        resolved = resolve_current_model_artifact_path(
            paths,
            artifact_name,
            fallback_path=fallback_path,
        )
    else:
        resolved = fallback_path if fallback_path.exists() else None
    if resolved is None:
        raise FileNotFoundError(missing_message)
    return resolved


# -------------------------- operational helpers (refresh + status) --------------------------


def run_refresh(
    paths: ProjectPaths,
    *,
    gold_price_override: float | None,
    skip_tool_b: bool,
    _fault_after_step: str | None = None,
) -> int:
    """One-command operational pipeline through the latest ranking tools.

    Stops early and prints the partial status if any step fails. The whole point of
    this command is that the user runs one operational command instead of remembering
    the individual tool commands.
    """

    total_steps = 6 if not skip_tool_b else 3
    stage_timings: dict[str, dict[str, object]] = {}
    parent_refresh_id = _new_parent_refresh_id()

    def record_step(name: str, started_at: float, exit_code: int) -> None:
        stage_timings[name] = {
            "duration_seconds": round(perf_counter() - started_at, 3),
            "exit_code": int(exit_code),
        }

    def injected_fault_after(name: str) -> int | None:
        if _fault_after_step != name:
            return None
        print()
        print(
            "Injected refresh fault after {}. Model-state manifest was not published.".format(
                name
            )
        )
        run_status(paths)
        return 97

    print(f"Parent refresh id: {parent_refresh_id}")
    print(f"== Step 1/{total_steps}: update-data ==")
    started_at = perf_counter()
    update_exit = run_foundation(paths, command_name="update-data")
    record_step("update_data", started_at, update_exit)
    if update_exit != 0:
        print()
        print("update-data failed (exit code {}). Skipping the rest of the refresh.".format(update_exit))
        run_status(paths)
        return update_exit
    fault_exit = injected_fault_after("update_data")
    if fault_exit is not None:
        return fault_exit

    print()
    print(f"== Step 2/{total_steps}: tool-a ==")
    started_at = perf_counter()
    tool_a_exit = run_tool_a(paths)
    record_step("tool_a", started_at, tool_a_exit)
    if tool_a_exit != 0:
        print()
        print("tool-a failed (exit code {}). Skipping downstream tools.".format(tool_a_exit))
        run_status(paths)
        return tool_a_exit
    fault_exit = injected_fault_after("tool_a")
    if fault_exit is not None:
        return fault_exit

    if skip_tool_b:
        print()
        print("== Step 3/3: tool-b/tool-c/tool-d SKIPPED (--skip-tool-b) ==")
        loaded_config = load_app_config(paths)
        model_state = write_current_model_state_manifest(
            paths=paths,
            config_hash=loaded_config.combined_hash,
            parent_refresh_id=parent_refresh_id,
            stage_timings=stage_timings,
        )
        print()
        print(
            "Model state manifest published after partial refresh: "
            f"{paths.latest_model_state_manifest_path.relative_to(paths.repo_root).as_posix()} "
            f"({str(model_state.get('state')).upper()})"
        )
    else:
        print()
        print("== Step 3/6: tool-b ==")
        started_at = perf_counter()
        tool_b_exit = run_tool_b(paths, gold_price=gold_price_override)
        record_step("tool_b", started_at, tool_b_exit)
        if tool_b_exit != 0:
            print()
            print("tool-b failed (exit code {}). Skipping Tool C and Tool D.".format(tool_b_exit))
            run_status(paths)
            return tool_b_exit
        fault_exit = injected_fault_after("tool_b")
        if fault_exit is not None:
            return fault_exit
        print()
        print("== Step 4/6: tool-c ==")
        started_at = perf_counter()
        tool_c_exit = run_tool_c(paths, _use_model_state_inputs=False)
        record_step("tool_c", started_at, tool_c_exit)
        if tool_c_exit != 0:
            print()
            print("tool-c failed (exit code {}). Skipping Tool D.".format(tool_c_exit))
            run_status(paths)
            return tool_c_exit
        fault_exit = injected_fault_after("tool_c")
        if fault_exit is not None:
            return fault_exit
        print()
        print("== Step 5/6: tool-d (spot gold) ==")
        started_at = perf_counter()
        tool_d_exit = run_tool_d(
            paths,
            gold_price=None,
            _use_model_state_inputs=False,
        )
        record_step("tool_d", started_at, tool_d_exit)
        if tool_d_exit != 0:
            print()
            print("tool-d failed (exit code {}).".format(tool_d_exit))
            run_status(paths)
            return tool_d_exit
        fault_exit = injected_fault_after("tool_d")
        if fault_exit is not None:
            return fault_exit

        print()
        print("== Step 6/6: option-artifacts ==")
        started_at = perf_counter()
        option_artifacts_exit = run_option_artifacts(
            paths,
            parent_refresh_id=parent_refresh_id,
        )
        record_step("option_artifacts", started_at, option_artifacts_exit)
        if option_artifacts_exit != 0:
            print()
            print(
                "option-artifacts failed (exit code {}). Model-state manifest was not published.".format(
                    option_artifacts_exit
                )
            )
            run_status(paths)
            return option_artifacts_exit
        fault_exit = injected_fault_after("option_artifacts")
        if fault_exit is not None:
            return fault_exit

        loaded_config = load_app_config(paths)
        model_state = write_current_model_state_manifest(
            paths=paths,
            config_hash=loaded_config.combined_hash,
            parent_refresh_id=parent_refresh_id,
            stage_timings=stage_timings,
        )
        print()
        print(
            "Model state manifest published: "
            f"{paths.latest_model_state_manifest_path.relative_to(paths.repo_root).as_posix()} "
            f"({str(model_state.get('state')).upper()})"
        )

    print()
    print("== Refresh complete. Operational status: ==")
    return run_status(paths)


def _new_parent_refresh_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-refresh-{uuid4().hex[:8]}"


def run_status(paths: ProjectPaths) -> int:
    """Print a one-screen operational summary.

    Surfaces the things a user actually needs to know after a refresh:
    - is the foundation snapshot fresh and what date does it cover
    - did tool-a publish a current ranking
    - did tool-b score every active Tool B ticker, and if not which ones are blocked
    - are the three artifact families aligned to the same refresh run id
    - which active tickers are missing manual data (the most common operational gap)
    """

    print(_render_status_summary(paths))
    return 0


def _render_status_summary(paths: ProjectPaths) -> str:
    from datetime import datetime, timezone

    from golden_vector.screening.manual_store import load_store_tables

    lines: list[str] = []
    lines.append("Golden Vector - operational status")
    lines.append("=" * 60)
    lines.extend(summarize_model_state_manifest(load_current_model_state_manifest(paths)))
    lines.append("")

    # Foundation manifest
    manifest_path = resolve_current_model_artifact_path(
        paths,
        "foundation",
        fallback_path=paths.latest_foundation_manifest_path,
    )
    if manifest_path is None or not manifest_path.exists():
        lines.append("Foundation snapshot:  NOT FOUND. Run `python main.py update-data` first.")
        manifest_run_id: str | None = None
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_run_id = str(manifest.get("refresh_run_id") or "")
            snapshot_date = manifest.get("snapshot_as_of_date", "?")
            foundation_status = manifest.get("foundation_status", "?")
            mtime = datetime.fromtimestamp(manifest_path.stat().st_mtime, tz=timezone.utc)
            age_hours = (datetime.now(tz=timezone.utc) - mtime).total_seconds() / 3600.0
            freshness = "fresh" if age_hours < 24 else "STALE (> 24h)"
            lines.append(
                f"Foundation snapshot:  {foundation_status}  "
                f"as-of {snapshot_date}  ({age_hours:.1f}h old, {freshness})"
            )
            lines.append(f"  refresh_run_id:     {manifest_run_id}")
        except Exception as exc:
            lines.append(f"Foundation snapshot:  ERROR reading manifest ({exc}).")
            manifest_run_id = None

    # Tool A latest
    tool_a_path = resolve_current_model_artifact_path(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )
    tool_a_run_ids: set[str] = set()
    if tool_a_path is None or not tool_a_path.exists():
        lines.append("Tool A latest output: NOT FOUND. Run `python main.py tool-a`.")
    else:
        try:
            df = pd.read_parquet(tool_a_path)
            ranked = int(df["tool_a_rank"].notna().sum()) if "tool_a_rank" in df.columns else 0
            withheld = int((~df["score_eligible"].fillna(False)).sum()) if "score_eligible" in df.columns else 0
            if "snapshot_refresh_run_id" in df.columns:
                tool_a_run_ids = {
                    str(value)
                    for value in df["snapshot_refresh_run_id"].dropna().unique()
                    if str(value) and str(value).lower() != "nan"
                }
            lines.append(
                f"Tool A latest output: {len(df.index)} rows, {ranked} ranked, "
                f"{withheld} score-withheld."
            )
        except Exception as exc:
            lines.append(f"Tool A latest output: ERROR reading parquet ({exc}).")

    # Tool B latest
    tool_b_path = resolve_current_model_artifact_path(
        paths,
        "tool_b",
        fallback_path=paths.latest_tool_b_snapshot_parquet_path,
    )
    tool_b_run_ids: set[str] = set()
    if tool_b_path is None or not tool_b_path.exists():
        lines.append("Tool B latest output: NOT FOUND. Run `python main.py tool-b`.")
    else:
        try:
            df = pd.read_parquet(tool_b_path)
            scored = int(df["tool_b_rank"].notna().sum()) if "tool_b_rank" in df.columns else 0
            incomplete_tickers = []
            if "screening_verdict" in df.columns and "ticker" in df.columns:
                incomplete_tickers = sorted(
                    df.loc[df["screening_verdict"].astype(str).str.upper() == "INCOMPLETE", "ticker"]
                    .astype(str)
                    .tolist()
                )
            if "snapshot_refresh_run_id" in df.columns:
                tool_b_run_ids = {
                    str(value)
                    for value in df["snapshot_refresh_run_id"].dropna().unique()
                    if str(value) and str(value).lower() != "nan"
                }
            gold_price = "?"
            if "gold_price_assumption" in df.columns and len(df.index):
                gold_price = f"${df['gold_price_assumption'].iloc[0]:.0f}/oz"
            lines.append(
                f"Tool B latest output: {len(df.index)} rows, {scored} scored, "
                f"{len(incomplete_tickers)} INCOMPLETE.  Gold-price assumption: {gold_price}"
            )
            if incomplete_tickers:
                lines.append(
                    f"  Incomplete tickers: {', '.join(incomplete_tickers)} "
                    "(missing manual data - see manual-data summary below)."
                )
        except Exception as exc:
            lines.append(f"Tool B latest output: ERROR reading parquet ({exc}).")

    # Tool C latest
    tool_c_path = resolve_current_model_artifact_path(
        paths,
        "tool_c",
        fallback_path=paths.latest_tool_c_snapshot_parquet_path,
    )
    tool_c_run_ids: set[str] = set()
    if tool_c_path is None or not tool_c_path.exists():
        lines.append("Tool C latest output: NOT FOUND. Run `python main.py tool-c`.")
    else:
        try:
            df = pd.read_parquet(tool_c_path)
            ranked_down = (
                int(df["tool_c_downside_rank"].notna().sum())
                if "tool_c_downside_rank" in df.columns
                else 0
            )
            ranked_up = (
                int(df["tool_c_upside_rank"].notna().sum())
                if "tool_c_upside_rank" in df.columns
                else 0
            )
            if "snapshot_refresh_run_id" in df.columns:
                tool_c_run_ids = {
                    str(value)
                    for value in df["snapshot_refresh_run_id"].dropna().unique()
                    if str(value) and str(value).lower() != "nan"
                }
            lines.append(
                f"Tool C latest output: {len(df.index)} rows, "
                f"{ranked_down} downside ranked, {ranked_up} upside ranked."
            )
        except Exception as exc:
            lines.append(f"Tool C latest output: ERROR reading parquet ({exc}).")

    # Tool D latest
    tool_d_path = resolve_current_model_artifact_path(
        paths,
        "tool_d",
        fallback_path=paths.latest_tool_d_snapshot_parquet_path,
    )
    tool_d_run_ids: set[str] = set()
    if tool_d_path is None or not tool_d_path.exists():
        lines.append("Tool D latest output: NOT FOUND. Run `python main.py tool-d`.")
    else:
        try:
            df = pd.read_parquet(tool_d_path)
            ranked = (
                int(df["tool_d_quality_rank"].notna().sum())
                if "tool_d_quality_rank" in df.columns
                else 0
            )
            if "snapshot_refresh_run_id" in df.columns:
                tool_d_run_ids = {
                    str(value)
                    for value in df["snapshot_refresh_run_id"].dropna().unique()
                    if str(value) and str(value).lower() != "nan"
                }
            gold_price = "?"
            if "gold_price_used" in df.columns and len(df.index):
                gold_price = f"${df['gold_price_used'].iloc[0]:.0f}/oz"
            spot_date = "?"
            if "spot_gold_date" in df.columns and len(df.index):
                spot_date = str(df["spot_gold_date"].iloc[0])
            lines.append(
                f"Tool D latest output: {len(df.index)} rows, {ranked} ranked, "
                f"gold price used {gold_price}, spot date {spot_date}."
            )
        except Exception as exc:
            lines.append(f"Tool D latest output: ERROR reading parquet ({exc}).")

    # Refresh-id alignment
    alignment_messages: list[str] = []
    if manifest_run_id:
        if tool_a_run_ids and manifest_run_id not in tool_a_run_ids:
            alignment_messages.append(
                f"Tool A={', '.join(sorted(tool_a_run_ids))}"
            )
        if tool_b_run_ids and manifest_run_id not in tool_b_run_ids:
            alignment_messages.append(
                f"Tool B={', '.join(sorted(tool_b_run_ids))}"
            )
        if tool_c_run_ids and manifest_run_id not in tool_c_run_ids:
            alignment_messages.append(
                f"Tool C={', '.join(sorted(tool_c_run_ids))}"
            )
        if tool_d_run_ids and manifest_run_id not in tool_d_run_ids:
            alignment_messages.append(
                f"Tool D={', '.join(sorted(tool_d_run_ids))}"
            )
    if not manifest_run_id:
        lines.append("Refresh alignment:    UNKNOWN  (foundation refresh id missing)")
    elif alignment_messages:
        lines.append(
            "Refresh alignment:    MISMATCH  "
            f"(manifest={manifest_run_id}; {'; '.join(alignment_messages)})"
        )
    else:
        lines.append("Refresh alignment:    OK")

    # Manual data coverage
    lines.append("")
    lines.append("Manual data coverage (Tool B):")
    if not manual_store_exists(paths):
        lines.append("  No manual-data store yet. Run `python main.py manual-data init` first.")
    else:
        try:
            loaded = load_app_config(paths)
            tool_b_tickers = sorted(
                ticker.ticker
                for ticker in loaded.app.universe.tickers
                if ticker.active and ticker.tool_b_enabled
            )
            company_inputs, _, _, _ = load_store_tables(paths)
            numeric_cols = [
                "production_oz", "aisc_usd_per_oz", "cash_cost_usd_per_oz", "royalty_rate",
                "sustaining_capex_musd", "da_musd", "interest_expense_musd", "tax_rate",
                "reserve_life_years", "net_debt_musd", "ebitda_ltm_musd",
            ]
            full_count = 0
            blank_tickers: list[str] = []
            partial: list[tuple[str, int]] = []
            for ticker in tool_b_tickers:
                row = company_inputs.loc[company_inputs["ticker"].astype(str) == ticker]
                if row.empty:
                    blank_tickers.append(ticker)
                    continue
                row = row.iloc[0]
                present = sum(1 for col in numeric_cols if col in row.index and pd.notna(row[col]))
                if present == len(numeric_cols):
                    full_count += 1
                elif present == 0:
                    blank_tickers.append(ticker)
                else:
                    partial.append((ticker, present))
            lines.append(
                f"  {full_count}/{len(tool_b_tickers)} tickers fully populated; "
                f"{len(partial)} partial; {len(blank_tickers)} blank."
            )
            if blank_tickers:
                lines.append(
                    f"  Blank: {', '.join(blank_tickers)}  "
                    "-> open the workspace and edit each, or use `python main.py manual-data set-company`."
                )
            if partial:
                partial_list = ", ".join(f"{t} ({n}/11)" for t, n in partial)
                lines.append(f"  Partial: {partial_list}")
        except Exception as exc:
            lines.append(f"  ERROR reading manual data store ({exc}).")

    lines.append("")
    lines.append("Next:  `python main.py workspace`  to inspect outputs in the browser.")
    return "\n".join(lines)
