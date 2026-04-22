"""CLI routing for Golden Vector."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.logging import configure_logging
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.combined.pipeline import execute_combined_pipeline
from golden_vector.features.horizons import parse_requested_horizons
from golden_vector.features.pipeline import execute_horizon_pipeline
from golden_vector.features.returns import RETURN_COLUMNS, compute_horizon_returns_for_ticker
from golden_vector.ingestion.foundation import execute_foundation_pipeline
from golden_vector.model.pipeline import execute_tool_a_profile_pipeline
from golden_vector.screening.pipeline import execute_tool_b_pipeline

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="golden-vector",
        description="Golden Vector pipeline runner.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "foundation",
        help="Run raw ingestion, raw QA, and USD normalization for the shared backbone.",
    )
    subparsers.add_parser(
        "tool-a",
        help="Run Tool A through the shared backbone, horizon returns, and metric/ranking outputs.",
    )

    tool_b_parser = subparsers.add_parser(
        "tool-b",
        help="Run Tool B through the shared backbone, manual screening inputs, and valuation outputs.",
    )
    tool_b_parser.add_argument(
        "--gold-price",
        type=float,
        required=True,
        help="Gold price assumption in USD per oz.",
    )

    combined_parser = subparsers.add_parser(
        "combined",
        help="Run Tool A and Tool B together, then publish the merged combined view.",
    )
    combined_parser.add_argument(
        "--gold-price",
        type=float,
        required=True,
        help="Gold price assumption in USD per oz.",
    )

    compare_parser = subparsers.add_parser(
        "compare-horizons",
        help="Compare configured and custom horizons for one Tool A ticker.",
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = ProjectPaths.discover()

    if args.command == "foundation":
        return run_foundation(paths)

    if args.command == "tool-a":
        return run_tool_a(paths)

    if args.command == "tool-b":
        return run_tool_b(paths, gold_price=args.gold_price)

    if args.command == "combined":
        return run_combined(paths, gold_price=args.gold_price)

    if args.command == "compare-horizons":
        return run_compare_horizons(
            paths,
            ticker=args.ticker,
            raw_horizons=args.horizons,
            csv_out=args.csv_out,
        )

    parser.error(f"Unsupported command: {args.command}")
    return 2


def run_foundation(paths: ProjectPaths) -> int:
    run_context: RunContext | None = None

    try:
        loaded_config = load_app_config(paths)
        run_context = RunContext.start(
            paths=paths,
            command="foundation",
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

        LOGGER.info("Starting foundation run %s", run_context.run_id)
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
            "Foundation pipeline completed.",
            f"Raw QA status: {result.raw_qa_report.overall_status}.",
        ]
        if result.normalization_qa_report is None:
            notes.append("Normalization stage skipped because raw QA failed.")
        else:
            notes.append(
                f"Normalization QA status: {result.normalization_qa_report.overall_status}."
            )
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
                command="foundation",
                parameters={},
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("Foundation run failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["Foundation run failed before completion."],
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
            "core_horizon_count": len(loaded_config.app.horizons.core_horizons),
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

        foundation_result = execute_foundation_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
        )
        run_context.write_json("fetch_plan.json", foundation_result.registry.summary())
        run_context.write_json("raw_qa_summary.json", foundation_result.raw_qa_report.summary())
        if foundation_result.normalization_qa_report is not None:
            run_context.write_json(
                "normalization_qa_summary.json",
                foundation_result.normalization_qa_report.summary(),
            )
        run_context.write_json(
            "foundation_qa_summary.json",
            {
                "overall_status": foundation_result.overall_status,
                "raw": foundation_result.raw_qa_report.summary(),
                "normalization": (
                    foundation_result.normalization_qa_report.summary()
                    if foundation_result.normalization_qa_report is not None
                    else {"overall_status": "SKIPPED"}
                ),
            },
        )

        if foundation_result.raw_qa_report.overall_status == "FAIL":
            notes = [
                "Tool A stopped because raw QA failed in the shared backbone.",
                f"Raw QA status: {foundation_result.raw_qa_report.overall_status}.",
            ]
            run_context.finalize(
                status="FAIL",
                summary={**config_summary, **foundation_result.summary},
                notes=notes,
            )
            LOGGER.error("Tool A stopped because raw QA failed.")
            return 1

        if foundation_result.normalization_qa_report is None:
            run_context.finalize(
                status="FAIL",
                summary={**config_summary, **foundation_result.summary},
                notes=["Tool A stopped because USD normalization did not run."],
            )
            LOGGER.error("Tool A stopped because USD normalization did not run.")
            return 1
        if foundation_result.normalization_qa_report.overall_status == "FAIL":
            run_context.write_json(
                "qa_summary.json",
                {
                    "overall_status": "FAIL",
                    "raw": foundation_result.raw_qa_report.summary(),
                    "normalization": foundation_result.normalization_qa_report.summary(),
                },
            )
            run_context.finalize(
                status="FAIL",
                summary={**config_summary, **foundation_result.summary},
                notes=["Tool A stopped because normalization QA failed."],
            )
            LOGGER.error("Tool A stopped because normalization QA failed.")
            return 1

        horizon_result = execute_horizon_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            gold_history=foundation_result.gold_history,
            normalized_equity_histories=foundation_result.normalized_equity_histories,
        )
        run_context.write_json("horizon_qa_summary.json", horizon_result.qa_report.summary())
        if horizon_result.overall_status == "FAIL":
            run_context.write_json(
                "qa_summary.json",
                {
                    "overall_status": "FAIL",
                    "raw": foundation_result.raw_qa_report.summary(),
                    "normalization": foundation_result.normalization_qa_report.summary(),
                    "horizon": horizon_result.qa_report.summary(),
                },
            )
            run_context.finalize(
                status="FAIL",
                summary={
                    **config_summary,
                    **foundation_result.summary,
                    **horizon_result.summary,
                },
                notes=["Tool A stopped because horizon QA failed."],
            )
            LOGGER.error("Tool A stopped because horizon QA failed.")
            return 1
        tool_a_result = execute_tool_a_profile_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            horizon_metrics=horizon_result.horizon_metrics,
        )
        run_context.write_json("tool_a_output_summary.json", tool_a_result.summary)

        overall_status = _combine_statuses(
            foundation_result.raw_qa_report.overall_status,
            foundation_result.normalization_qa_report.overall_status,
            horizon_result.overall_status,
            tool_a_result.overall_status,
        )
        run_context.write_json(
            "qa_summary.json",
            {
                "overall_status": overall_status,
                "raw": foundation_result.raw_qa_report.summary(),
                "normalization": foundation_result.normalization_qa_report.summary(),
                "horizon": horizon_result.qa_report.summary(),
                "tool_a_output": tool_a_result.summary,
            },
        )
        notes = [
            "Tool A horizon and metric stages completed.",
            f"Raw QA status: {foundation_result.raw_qa_report.overall_status}.",
            f"Normalization QA status: {foundation_result.normalization_qa_report.overall_status}.",
            f"Horizon QA status: {horizon_result.qa_report.overall_status}.",
            f"Tool A output status: {tool_a_result.overall_status}.",
        ]
        run_context.finalize(
            status=overall_status,
            summary={
                **config_summary,
                **foundation_result.summary,
                **horizon_result.summary,
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


def run_tool_b(paths: ProjectPaths, *, gold_price: float) -> int:
    run_context: RunContext | None = None

    try:
        if gold_price <= 0:
            raise ValueError("gold price must be positive")

        loaded_config = load_app_config(paths)
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

        foundation_result = execute_foundation_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
        )
        run_context.write_json("fetch_plan.json", foundation_result.registry.summary())
        run_context.write_json("raw_qa_summary.json", foundation_result.raw_qa_report.summary())
        if foundation_result.normalization_qa_report is not None:
            run_context.write_json(
                "normalization_qa_summary.json",
                foundation_result.normalization_qa_report.summary(),
            )
        run_context.write_json(
            "foundation_qa_summary.json",
            {
                "overall_status": foundation_result.overall_status,
                "raw": foundation_result.raw_qa_report.summary(),
                "normalization": (
                    foundation_result.normalization_qa_report.summary()
                    if foundation_result.normalization_qa_report is not None
                    else {"overall_status": "SKIPPED"}
                ),
            },
        )

        if foundation_result.raw_qa_report.overall_status == "FAIL":
            run_context.write_json(
                "qa_summary.json",
                {
                    "overall_status": "FAIL",
                    "raw": foundation_result.raw_qa_report.summary(),
                    "normalization": {"overall_status": "SKIPPED"},
                },
            )
            run_context.finalize(
                status="FAIL",
                summary={**config_summary, **foundation_result.summary},
                notes=["Tool B stopped because raw QA failed in the shared backbone."],
            )
            LOGGER.error("Tool B stopped because raw QA failed.")
            return 1

        if foundation_result.normalization_qa_report is None:
            run_context.write_json(
                "qa_summary.json",
                {
                    "overall_status": "FAIL",
                    "raw": foundation_result.raw_qa_report.summary(),
                    "normalization": {"overall_status": "SKIPPED"},
                },
            )
            run_context.finalize(
                status="FAIL",
                summary={**config_summary, **foundation_result.summary},
                notes=["Tool B stopped because USD normalization did not run."],
            )
            LOGGER.error("Tool B stopped because USD normalization did not run.")
            return 1
        if foundation_result.normalization_qa_report.overall_status == "FAIL":
            run_context.write_json(
                "qa_summary.json",
                {
                    "overall_status": "FAIL",
                    "raw": foundation_result.raw_qa_report.summary(),
                    "normalization": foundation_result.normalization_qa_report.summary(),
                },
            )
            run_context.finalize(
                status="FAIL",
                summary={**config_summary, **foundation_result.summary},
                notes=["Tool B stopped because normalization QA failed."],
            )
            LOGGER.error("Tool B stopped because normalization QA failed.")
            return 1

        tool_b_result = execute_tool_b_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            normalized_market_snapshots=foundation_result.normalized_market_snapshots,
            gold_price_assumption=gold_price,
        )
        run_context.write_json("tool_b_output_summary.json", tool_b_result.summary)

        overall_status = _combine_statuses(
            foundation_result.raw_qa_report.overall_status,
            foundation_result.normalization_qa_report.overall_status,
            tool_b_result.overall_status,
        )
        run_context.write_json(
            "qa_summary.json",
            {
                "overall_status": overall_status,
                "raw": foundation_result.raw_qa_report.summary(),
                "normalization": foundation_result.normalization_qa_report.summary(),
                "tool_b_output": tool_b_result.summary,
            },
        )
        notes = [
            "Tool B completed from normalized market snapshots and manual screening inputs.",
            f"Raw QA status: {foundation_result.raw_qa_report.overall_status}.",
            f"Normalization QA status: {foundation_result.normalization_qa_report.overall_status}.",
            f"Tool B output status: {tool_b_result.overall_status}.",
        ]
        if tool_b_result.summary.get("manual_template_files_created"):
            notes.append("Missing manual template files were created automatically.")
        if tool_b_result.summary.get("manual_template_files_updated"):
            notes.append("Existing manual template files were updated with newly configured Tool B tickers.")
        run_context.finalize(
            status=overall_status,
            summary={
                **config_summary,
                **foundation_result.summary,
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


def run_combined(paths: ProjectPaths, *, gold_price: float) -> int:
    run_context: RunContext | None = None

    try:
        if gold_price <= 0:
            raise ValueError("gold price must be positive")

        loaded_config = load_app_config(paths)
        run_context = RunContext.start(
            paths=paths,
            command="combined",
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

        LOGGER.info("Starting combined run %s", run_context.run_id)
        config_summary = {
            "configured_ticker_count": len(configured_tickers),
            "active_ticker_count": len(active_tickers),
            "tool_a_enabled_ticker_count": len(tool_a_enabled),
            "tool_b_enabled_ticker_count": len(tool_b_enabled),
            "gold_price_assumption": gold_price,
            "configured_gold_price_scenarios": loaded_config.app.screening_params.gold_price_scenarios,
            "core_horizon_count": len(loaded_config.app.horizons.core_horizons),
            "combined_config_hash": loaded_config.combined_hash,
        }
        run_context.write_json("config_summary.json", config_summary)
        if not tool_a_enabled:
            run_context.finalize(
                status="FAIL",
                summary=config_summary,
                notes=["Combined cannot run because no active Tool A tickers are configured."],
            )
            LOGGER.error("Combined stopped because no active Tool A tickers are configured.")
            return 1
        if not tool_b_enabled:
            run_context.finalize(
                status="FAIL",
                summary=config_summary,
                notes=["Combined cannot run because no active Tool B tickers are configured."],
            )
            LOGGER.error("Combined stopped because no active Tool B tickers are configured.")
            return 1

        foundation_result = execute_foundation_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
        )
        run_context.write_json("fetch_plan.json", foundation_result.registry.summary())
        run_context.write_json("raw_qa_summary.json", foundation_result.raw_qa_report.summary())
        if foundation_result.normalization_qa_report is not None:
            run_context.write_json(
                "normalization_qa_summary.json",
                foundation_result.normalization_qa_report.summary(),
            )
        run_context.write_json(
            "foundation_qa_summary.json",
            {
                "overall_status": foundation_result.overall_status,
                "raw": foundation_result.raw_qa_report.summary(),
                "normalization": (
                    foundation_result.normalization_qa_report.summary()
                    if foundation_result.normalization_qa_report is not None
                    else {"overall_status": "SKIPPED"}
                ),
            },
        )

        if foundation_result.raw_qa_report.overall_status == "FAIL":
            run_context.write_json(
                "qa_summary.json",
                {
                    "overall_status": "FAIL",
                    "raw": foundation_result.raw_qa_report.summary(),
                    "normalization": {"overall_status": "SKIPPED"},
                },
            )
            run_context.finalize(
                status="FAIL",
                summary={**config_summary, **foundation_result.summary},
                notes=["Combined stopped because raw QA failed in the shared backbone."],
            )
            LOGGER.error("Combined stopped because raw QA failed.")
            return 1

        if foundation_result.normalization_qa_report is None:
            run_context.write_json(
                "qa_summary.json",
                {
                    "overall_status": "FAIL",
                    "raw": foundation_result.raw_qa_report.summary(),
                    "normalization": {"overall_status": "SKIPPED"},
                },
            )
            run_context.finalize(
                status="FAIL",
                summary={**config_summary, **foundation_result.summary},
                notes=["Combined stopped because USD normalization did not run."],
            )
            LOGGER.error("Combined stopped because USD normalization did not run.")
            return 1
        if foundation_result.normalization_qa_report.overall_status == "FAIL":
            run_context.write_json(
                "qa_summary.json",
                {
                    "overall_status": "FAIL",
                    "raw": foundation_result.raw_qa_report.summary(),
                    "normalization": foundation_result.normalization_qa_report.summary(),
                },
            )
            run_context.finalize(
                status="FAIL",
                summary={**config_summary, **foundation_result.summary},
                notes=["Combined stopped because normalization QA failed."],
            )
            LOGGER.error("Combined stopped because normalization QA failed.")
            return 1

        horizon_result = execute_horizon_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            gold_history=foundation_result.gold_history,
            normalized_equity_histories=foundation_result.normalized_equity_histories,
        )
        run_context.write_json("horizon_qa_summary.json", horizon_result.qa_report.summary())
        if horizon_result.overall_status == "FAIL":
            run_context.write_json(
                "qa_summary.json",
                {
                    "overall_status": "FAIL",
                    "raw": foundation_result.raw_qa_report.summary(),
                    "normalization": foundation_result.normalization_qa_report.summary(),
                    "horizon": horizon_result.qa_report.summary(),
                },
            )
            run_context.finalize(
                status="FAIL",
                summary={
                    **config_summary,
                    **foundation_result.summary,
                    **horizon_result.summary,
                },
                notes=["Combined stopped because Tool A horizon QA failed."],
            )
            LOGGER.error("Combined stopped because Tool A horizon QA failed.")
            return 1

        tool_a_result = execute_tool_a_profile_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            horizon_metrics=horizon_result.horizon_metrics,
        )
        run_context.write_json("tool_a_output_summary.json", tool_a_result.summary)
        if tool_a_result.overall_status == "FAIL":
            run_context.write_json(
                "qa_summary.json",
                {
                    "overall_status": "FAIL",
                    "raw": foundation_result.raw_qa_report.summary(),
                    "normalization": foundation_result.normalization_qa_report.summary(),
                    "horizon": horizon_result.qa_report.summary(),
                    "tool_a_output": tool_a_result.summary,
                },
            )
            run_context.finalize(
                status="FAIL",
                summary={
                    **config_summary,
                    **foundation_result.summary,
                    **horizon_result.summary,
                    **tool_a_result.summary,
                },
                notes=["Combined stopped because Tool A output generation failed."],
            )
            LOGGER.error("Combined stopped because Tool A output generation failed.")
            return 1

        tool_b_result = execute_tool_b_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
            normalized_market_snapshots=foundation_result.normalized_market_snapshots,
            gold_price_assumption=gold_price,
        )
        run_context.write_json("tool_b_output_summary.json", tool_b_result.summary)

        combined_result = execute_combined_pipeline(
            paths=paths,
            run_context=run_context,
            scoring_config=loaded_config.app.scoring,
            tool_a_outputs=tool_a_result.tool_a_outputs,
            tool_b_outputs=tool_b_result.tool_b_outputs,
            gold_price_assumption=gold_price,
        )
        run_context.write_json("combined_output_summary.json", combined_result.summary)

        tool_b_status_for_rollup = (
            "WARN"
            if tool_b_result.overall_status == "FAIL"
            else tool_b_result.overall_status
        )
        overall_status = _combine_statuses(
            foundation_result.raw_qa_report.overall_status,
            foundation_result.normalization_qa_report.overall_status,
            horizon_result.overall_status,
            tool_a_result.overall_status,
            tool_b_status_for_rollup,
            combined_result.overall_status,
        )
        run_context.write_json(
            "qa_summary.json",
            {
                "overall_status": overall_status,
                "raw": foundation_result.raw_qa_report.summary(),
                "normalization": foundation_result.normalization_qa_report.summary(),
                "horizon": horizon_result.qa_report.summary(),
                "tool_a_output": tool_a_result.summary,
                "tool_b_output": tool_b_result.summary,
                "combined_output": combined_result.summary,
            },
        )
        notes = [
            "Combined completed by joining published Tool A and Tool B outputs.",
            f"Raw QA status: {foundation_result.raw_qa_report.overall_status}.",
            f"Normalization QA status: {foundation_result.normalization_qa_report.overall_status}.",
            f"Horizon QA status: {horizon_result.qa_report.overall_status}.",
            f"Tool A output status: {tool_a_result.overall_status}.",
            f"Tool B output status: {tool_b_result.overall_status}.",
            f"Combined output status: {combined_result.overall_status}.",
        ]
        if tool_b_result.overall_status == "FAIL":
            notes.append("Tool B produced no usable rows, so combined outputs are partial Tool A rows only.")
        if tool_b_result.summary.get("manual_template_files_updated"):
            notes.append("Existing manual template files were updated with newly configured Tool B tickers.")
        run_context.finalize(
            status=overall_status,
            summary={
                **config_summary,
                **foundation_result.summary,
                **horizon_result.summary,
                **tool_a_result.summary,
                **tool_b_result.summary,
                **combined_result.summary,
            },
            notes=notes,
        )

        if overall_status == "FAIL":
            LOGGER.error("Combined run completed with blocking failures.")
            return 1

        LOGGER.info("Combined run completed with status %s.", overall_status)
        return 0
    except Exception as exc:
        if run_context is None:
            run_context = RunContext.start(
                paths=paths,
                command="combined",
                parameters={"gold_price": gold_price},
                config_hash="UNAVAILABLE",
            )
            configure_logging(run_context.log_path)
        LOGGER.exception("Combined run failed.")
        run_context.finalize(
            status="FAIL",
            summary={"error": str(exc)},
            notes=["Combined run failed before completion."],
        )
        return 1


def run_placeholder(
    paths: ProjectPaths,
    command: str,
    parameters: dict[str, object],
) -> int:
    loaded_config = load_app_config(paths)
    run_context = RunContext.start(
        paths=paths,
        command=command,
        parameters=parameters,
        config_hash=loaded_config.combined_hash,
    )
    configure_logging(run_context.log_path)

    message = f"{command} is scaffolded but not implemented yet."
    LOGGER.warning(message)
    run_context.finalize(
        status="NOT_IMPLEMENTED",
        summary={"command": command},
        notes=[message],
    )
    return 1


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

        foundation_result = execute_foundation_pipeline(
            paths=paths,
            app_config=loaded_config.app,
            run_context=run_context,
        )
        run_context.write_json("fetch_plan.json", foundation_result.registry.summary())
        run_context.write_json("raw_qa_summary.json", foundation_result.raw_qa_report.summary())
        if foundation_result.normalization_qa_report is not None:
            run_context.write_json(
                "normalization_qa_summary.json",
                foundation_result.normalization_qa_report.summary(),
            )

        if foundation_result.raw_qa_report.overall_status == "FAIL":
            run_context.finalize(
                status="FAIL",
                summary={"ticker": normalized_ticker},
                notes=["compare-horizons stopped because raw QA failed."],
            )
            LOGGER.error("compare-horizons stopped because raw QA failed.")
            return 1

        if foundation_result.normalization_qa_report is None:
            run_context.finalize(
                status="FAIL",
                summary={"ticker": normalized_ticker},
                notes=["compare-horizons stopped because USD normalization did not run."],
            )
            LOGGER.error("compare-horizons stopped because USD normalization did not run.")
            return 1
        if foundation_result.normalization_qa_report.overall_status == "FAIL":
            run_context.write_json(
                "qa_summary.json",
                {
                    "overall_status": "FAIL",
                    "raw": foundation_result.raw_qa_report.summary(),
                    "normalization": foundation_result.normalization_qa_report.summary(),
                },
            )
            run_context.finalize(
                status="FAIL",
                summary={"ticker": normalized_ticker},
                notes=["compare-horizons stopped because normalization QA failed."],
            )
            LOGGER.error("compare-horizons stopped because normalization QA failed.")
            return 1

        comparison = compute_horizon_returns_for_ticker(
            usd_equity_history=foundation_result.normalized_equity_histories.get(
                normalized_ticker,
                pd.DataFrame(columns=RETURN_COLUMNS),
            ),
            gold_history=foundation_result.gold_history,
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
            foundation_result.raw_qa_report.overall_status,
            foundation_result.normalization_qa_report.overall_status,
            comparison_status,
        )
        summary = {
            "ticker": normalized_ticker,
            "requested_horizon_count": len(requested_horizons),
            "comparison_row_count": len(comparison.index),
            "pass_row_count": pass_rows,
            "fail_row_count": fail_rows,
            "raw_qa_status": foundation_result.raw_qa_report.overall_status,
            "normalization_qa_status": foundation_result.normalization_qa_report.overall_status,
            "comparison_status": comparison_status,
            "output_csv": str(output_path),
        }
        run_context.write_json("compare_summary.json", summary)
        run_context.write_json(
            "qa_summary.json",
            {
                "overall_status": overall_status,
                "raw": foundation_result.raw_qa_report.summary(),
                "normalization": foundation_result.normalization_qa_report.summary(),
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
                "compare-horizons completed.",
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
