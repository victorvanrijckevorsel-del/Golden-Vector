"""CLI routing for Golden Vector."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Sequence

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.latest_data import (
    LatestFoundationSnapshot,
    load_latest_foundation_snapshot,
    write_latest_foundation_manifest,
)
from golden_vector.app.logging import configure_logging
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.replay_manifest import (
    VERDICT_PREDATES_REPLAY_MANIFEST,
    VerifyResult,
    update_manifest_with_foundation,
    verify_manifest,
)
from golden_vector.app.run_context import RunContext, to_jsonable
from golden_vector.features.horizons import parse_requested_horizons
from golden_vector.features.pipeline import execute_horizon_pipeline
from golden_vector.features.returns import RETURN_COLUMNS, compute_horizon_returns_for_ticker
from golden_vector.ingestion.foundation import execute_foundation_pipeline
from golden_vector.model.pipeline import execute_tool_a_profile_pipeline
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
from golden_vector.serve.workspace import run_workspace_server

LOGGER = logging.getLogger(__name__)


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
    subparsers.add_parser(
        "update-data",
        help="Refresh market data, run QA, and publish the latest validated local artifacts.",
    )
    subparsers.add_parser(
        "tool-a",
        help="Run structural Tool A from the latest validated local USD-normalized snapshot.",
    )

    refresh_parser = subparsers.add_parser(
        "refresh",
        help=(
            "One-command operational refresh: runs update-data, then tool-a, then tool-b "
            "in sequence, then prints a one-screen status summary."
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
        return run_foundation(paths, command_name=args.command)

    if args.command == "tool-a":
        return run_tool_a(paths)

    if args.command == "tool-b":
        return run_tool_b(paths, gold_price=args.gold_price)

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


def run_foundation(paths: ProjectPaths, *, command_name: str = "foundation") -> int:
    run_context: RunContext | None = None

    try:
        loaded_config = load_app_config(paths)
        run_context = RunContext.start(
            paths=paths,
            command=command_name,
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
        run_context.finalize(
            status=result.overall_status,
            summary={**config_summary, **result.summary},
            notes=notes,
        )

        if result.overall_status == "FAIL":
            LOGGER.error("Foundation run completed with blocking QA failures.")
            return 1

        LOGGER.info(
            "Foundation run completed with status %s.",
            result.overall_status,
        )
        return 0
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command=command_name,
                parameters={},
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


def _load_latest_foundation_snapshot(
    *,
    paths: ProjectPaths,
    app_config: object,
    run_context: RunContext,
    include_gold_history: bool = True,
    include_equity_histories: bool = True,
    include_market_snapshots: bool = True,
    requested_tickers: list[str] | None = None,
) -> LatestFoundationSnapshot:
    snapshot = load_latest_foundation_snapshot(
        paths=paths,
        app_config=app_config,
        include_gold_history=include_gold_history,
        include_equity_histories=include_equity_histories,
        include_market_snapshots=include_market_snapshots,
        requested_tickers=requested_tickers,
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


def _combine_statuses(*statuses: str | None) -> str:
    active_statuses = [status for status in statuses if status]
    allowed_statuses = {"PASS", "WARN", "FAIL"}
    unknown_statuses = sorted(
        {status for status in active_statuses if status not in allowed_statuses}
    )
    if unknown_statuses:
        raise ValueError(
            "Unsupported pipeline statuses: " + ", ".join(unknown_statuses)
        )
    if any(status == "FAIL" for status in active_statuses):
        return "FAIL"
    if any(status == "WARN" for status in active_statuses):
        return "WARN"
    return "PASS"


# -------------------------- operational helpers (refresh + status) --------------------------


def run_refresh(
    paths: ProjectPaths,
    *,
    gold_price_override: float | None,
    skip_tool_b: bool,
) -> int:
    """One-command operational pipeline: update-data → tool-a → tool-b → status.

    Stops early and prints the partial status if any step fails. The whole point of
    this command is that the user runs ONE thing instead of remembering three commands
    plus a magic gold-price number.
    """

    print("== Step 1/3: update-data ==")
    update_exit = run_foundation(paths, command_name="update-data")
    if update_exit != 0:
        print()
        print("update-data failed (exit code {}). Skipping the rest of the refresh.".format(update_exit))
        run_status(paths)
        return update_exit

    print()
    print("== Step 2/3: tool-a ==")
    tool_a_exit = run_tool_a(paths)
    if tool_a_exit != 0:
        print()
        print("tool-a failed (exit code {}). Skipping Tool B.".format(tool_a_exit))
        run_status(paths)
        return tool_a_exit

    if skip_tool_b:
        print()
        print("== Step 3/3: tool-b SKIPPED (--skip-tool-b) ==")
    else:
        print()
        print("== Step 3/3: tool-b ==")
        tool_b_exit = run_tool_b(paths, gold_price=gold_price_override)
        if tool_b_exit != 0:
            print()
            print("tool-b failed (exit code {}).".format(tool_b_exit))
            run_status(paths)
            return tool_b_exit

    print()
    print("== Refresh complete. Operational status: ==")
    return run_status(paths)


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

    # Foundation manifest
    manifest_path = paths.latest_foundation_manifest_path
    if not manifest_path.exists():
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
    tool_a_path = paths.latest_tool_a_snapshot_parquet_path
    tool_a_run_ids: set[str] = set()
    if not tool_a_path.exists():
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
    tool_b_path = paths.latest_tool_b_snapshot_parquet_path
    tool_b_run_ids: set[str] = set()
    if not tool_b_path.exists():
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

    # Refresh-id alignment
    alignment_msg = "Refresh alignment:    OK"
    if manifest_run_id:
        if tool_a_run_ids and manifest_run_id not in tool_a_run_ids:
            alignment_msg = (
                f"Refresh alignment:    MISMATCH  "
                f"(manifest={manifest_run_id}, Tool A={sorted(tool_a_run_ids)[0]})"
            )
        elif tool_b_run_ids and manifest_run_id not in tool_b_run_ids:
            alignment_msg = (
                f"Refresh alignment:    MISMATCH  "
                f"(manifest={manifest_run_id}, Tool B={sorted(tool_b_run_ids)[0]})"
            )
    lines.append(alignment_msg)

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
