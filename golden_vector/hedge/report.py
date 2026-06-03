"""Markdown hedge-readiness report generation."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.replay_manifest import update_manifest_with_options
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.config_models import AppConfig
from golden_vector.hedge._helpers import (
    as_float as _as_float,
    is_optionable_tier as _is_optionable_tier,
    optionability_tier as _optionability_tier,
    row_float as _row_float,
    row_string as _row_string,
    rows_by_ticker_series as _index_by_ticker,
)
from golden_vector.hedge.candidate_puts import CandidatePut, build_candidate_put_grid
from golden_vector.hedge.comparison import (
    DEFAULT_COMPARISON_SORT,
    ComparisonRow,
    build_comparison_table,
)
from golden_vector.hedge.expected_downside import (
    PremiumVsDownsideCard,
    compute_premium_vs_downside,
)
from golden_vector.hedge.disclosures import (
    IV_RV_RATIO_CAVEAT,
    IV_SKEW_CAVEAT,
    LONG_OPTION_PREMIUM_CAVEAT,
    OPTION_REPRICE_ASSUMPTION,
    SENSITIVITY_RANKING_CAVEAT,
)
from golden_vector.hedge.header_context import HeaderContext, build_header_context
from golden_vector.hedge.holdings import Holding, load_holdings
from golden_vector.hedge.portfolio_totals import (
    PortfolioTotalsData,
    compute_portfolio_totals,
)
from golden_vector.hedge.proxy_hedge import ProxyMatch, map_proxy_hedges
from golden_vector.hedge.scenarios import (
    CandidateScenarioBundle,
    compute_scenario_bundle,
    scenario_model_note,
)
from golden_vector.hedge.sensitivity_ranking import (
    RANKING_PNL_GOLD_MOVE,
    SensitivityRankingData,
    build_sensitivity_ranking,
)
from golden_vector.hedge.speculation_section import (
    SpeculationTickerBlock,
    build_speculation_section,
)
from golden_vector.ingestion.persist_options import safe_options_file_name


@dataclass(frozen=True)
class HedgeReportResult:
    report_path: Path
    latest_path: Path
    markdown: str
    summary: dict[str, Any]


@dataclass(frozen=True)
class ContextAlignment:
    status: str
    message: str | None
    tool_a_refresh_run_ids: list[str]
    tool_b_refresh_run_ids: list[str]


@dataclass(frozen=True)
class SnapshotSummaryData:
    as_of_date: str
    refresh_run_id: str
    risk_free_rate: float | None
    risk_free_rate_is_fallback: bool
    holdings_count: int
    holdings_mode: str
    scenario_quantity: int
    ranking_max_tickers: int
    speculation_max_tickers: int
    optionability_counts: dict[str, int]
    context_alignment: ContextAlignment


@dataclass(frozen=True)
class HoldingPositionData:
    ticker: str
    exposure_usd: float | None
    optionability_tier: str
    current_stock_price: float | None
    down_beta_core: float | None
    confidence_score: float | None
    tool_b_verdict: str
    candidates: list[CandidatePut]
    scenario_bundles: list[CandidateScenarioBundle]
    premium_card: PremiumVsDownsideCard | None
    notes: list[str]


@dataclass(frozen=True)
class HeldPositionsData:
    holdings: list[HoldingPositionData]


@dataclass(frozen=True)
class SpeculationCandidatesData:
    blocks: list[SpeculationTickerBlock]
    sort_by: str
    max_tickers_applied: int


@dataclass(frozen=True)
class ComparisonViewData:
    rows: list[ComparisonRow]
    sort_by: str


@dataclass(frozen=True)
class ProxyHedgesData:
    target_tickers: list[str]
    by_target: dict[str, list[ProxyMatch]]


@dataclass(frozen=True)
class SourcesData:
    run_id: str
    options_snapshot_run_id: str
    risk_free_rate: float | None
    risk_free_rate_is_fallback: bool
    scenario_quantity: int
    ranking_max_tickers: int
    speculation_max_tickers: int
    replay_manifest_path: str
    latest_options_manifest_path: str
    raw_option_snapshot_count: int
    options_feature_row_count: int
    tool_a_row_count: int
    tool_b_row_count: int


@dataclass(frozen=True)
class HedgeReadinessSections:
    header: HeaderContext
    summary: SnapshotSummaryData
    sensitivity_ranking: SensitivityRankingData
    portfolio_totals: PortfolioTotalsData | None
    held_positions: HeldPositionsData | None
    speculation_candidates: SpeculationCandidatesData
    comparison: ComparisonViewData
    proxy_hedges: ProxyHedgesData | None
    sources: SourcesData


def write_hedge_readiness_report(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    app_config: AppConfig,
    comparison_sort_by: str | None = None,
    ranking_sort_by: str | None = None,
    ranking_max_tickers: int | None = None,
    speculation_max_tickers: int | None = None,
    quantity: int | None = None,
) -> HedgeReportResult:
    """Render and persist the latest hedge-readiness markdown report."""

    payload = _read_latest_options_manifest(paths)
    update_manifest_with_options(
        run_context.run_dir,
        options_manifest_path=paths.latest_options_manifest_path,
    )
    as_of_date = date.fromisoformat(str(payload["as_of_date"]))
    data = _load_report_data(paths=paths, manifest=payload)
    holdings = load_holdings(paths)
    sections = build_hedge_readiness_sections(
        paths=paths,
        run_context=run_context,
        app_config=app_config,
        manifest=payload,
        data=data,
        holdings=holdings,
        comparison_sort_by=comparison_sort_by,
        ranking_sort_by=ranking_sort_by,
        ranking_max_tickers=ranking_max_tickers,
        speculation_max_tickers=speculation_max_tickers,
        quantity=quantity,
    )
    markdown = render_markdown(sections=sections, paths=paths)
    summary = _summary_from_sections(sections)

    output_dir = paths.output_hedge_readiness_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{as_of_date.strftime('%Y%m%d')}_{run_context.run_id}.md"
    latest_path = output_dir / "latest.md"
    report_path.write_text(markdown, encoding="utf-8")
    shutil.copyfile(report_path, latest_path)
    run_context.record_artifact(report_path)
    run_context.record_artifact(latest_path)
    return HedgeReportResult(
        report_path=report_path,
        latest_path=latest_path,
        markdown=markdown,
        summary=summary,
    )


def render_hedge_readiness_report(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    manifest: dict[str, Any],
    data: dict[str, Any],
    holdings: list[Holding],
    comparison_sort_by: str | None = None,
    ranking_sort_by: str | None = None,
    ranking_max_tickers: int | None = None,
    speculation_max_tickers: int | None = None,
    quantity: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Backward-compatible helper for tests and direct rendering."""

    sections = build_hedge_readiness_sections(
        paths=paths,
        run_context=None,
        app_config=app_config,
        manifest=manifest,
        data=data,
        holdings=holdings,
        comparison_sort_by=comparison_sort_by,
        ranking_sort_by=ranking_sort_by,
        ranking_max_tickers=ranking_max_tickers,
        speculation_max_tickers=speculation_max_tickers,
        quantity=quantity,
    )
    return render_markdown(sections=sections, paths=paths), _summary_from_sections(sections)


def build_hedge_readiness_sections(
    *,
    paths: ProjectPaths,
    run_context: RunContext | None,
    app_config: AppConfig,
    manifest: dict[str, Any],
    data: dict[str, Any],
    holdings: list[Holding],
    comparison_sort_by: str | None = None,
    ranking_sort_by: str | None = None,
    ranking_max_tickers: int | None = None,
    speculation_max_tickers: int | None = None,
    quantity: int | None = None,
) -> HedgeReadinessSections:
    """Build the reusable section data for the markdown report."""

    config = app_config.hedge_readiness
    features = data["features"]
    tool_a = data["tool_a"]
    tool_b = data["tool_b"]
    chains = data["chains"]
    risk_free_rate = _as_float(manifest.get("risk_free_rate"))
    risk_free_rate_is_fallback = risk_free_rate is None
    effective_risk_free_rate = risk_free_rate if risk_free_rate is not None else 0.0
    comparison_sort = comparison_sort_by or DEFAULT_COMPARISON_SORT
    ranking_sort = ranking_sort_by or "down_beta_core"
    resolved_ranking_max = ranking_max_tickers or config.ranking_max_tickers_default
    resolved_speculation_max = (
        speculation_max_tickers or config.speculation_max_tickers_default
    )
    resolved_quantity = quantity or config.default_scenario_quantity
    refresh_run_id = str(manifest.get("refresh_run_id", "unknown"))

    candidate_grids = _candidate_grids(
        app_config=app_config,
        features=features,
        tool_b=tool_b,
        chains=chains,
        risk_free_rate=effective_risk_free_rate,
    )
    alignment = _context_alignment(
        options_refresh_run_id=refresh_run_id,
        tool_a=tool_a,
        tool_b=tool_b,
    )
    optionability_counts = _value_counts(features, "optionability_tier")
    optionable_tickers = _optionable_tickers(features)
    non_optionable_held = [
        holding.ticker
        for holding in holdings
        if holding.ticker not in optionable_tickers
    ]
    proxy_map = map_proxy_hedges(
        non_optionable_tickers=non_optionable_held,
        optionable_tickers=sorted(optionable_tickers),
        tool_a_frame=tool_a,
        tool_b_frame=tool_b,
        benchmark_tickers=tuple(config.benchmark_tickers),
        top_n=config.proxy_top_n,
        max_beta_diff=config.proxy_max_beta_diff,
        low_basis_max_beta_diff=config.proxy_low_basis_max_beta_diff,
        medium_basis_max_beta_diff=config.proxy_medium_basis_max_beta_diff,
        low_basis_min_confidence=config.proxy_low_basis_min_confidence,
    )

    header = build_header_context(
        paths=paths,
        options_features=features,
        tool_a_frame=tool_a,
    )
    sensitivity = build_sensitivity_ranking(
        tool_a_frame=tool_a,
        options_features=features,
        candidate_grids=candidate_grids,
        risk_free_rate=risk_free_rate,
        down_beta_min_for_scenario=config.down_beta_min_for_scenario,
        sort_by=ranking_sort,
        max_tickers=resolved_ranking_max,
    )
    portfolio = (
        compute_portfolio_totals(
            holdings=holdings,
            tool_a_frame=tool_a,
            tool_b_frame=tool_b,
            options_features=features,
            candidate_grids=candidate_grids,
            config=config,
        )
        if holdings
        else None
    )
    held_positions = (
        _build_held_positions(
            app_config=app_config,
            holdings=holdings,
            features=features,
            tool_a=tool_a,
            tool_b=tool_b,
            candidate_grids=candidate_grids,
            risk_free_rate=effective_risk_free_rate,
            risk_free_rate_is_fallback=risk_free_rate_is_fallback,
            quantity=resolved_quantity,
        )
        if holdings
        else None
    )
    speculation = SpeculationCandidatesData(
        blocks=build_speculation_section(
            paths=paths,
            options_features=features,
            tool_a_frame=tool_a,
            tool_b_frame=tool_b,
            raw_options_by_ticker=chains,
            risk_free_rate=risk_free_rate,
            config=config,
            quantity=resolved_quantity,
            max_tickers=resolved_speculation_max,
        ),
        sort_by="iv_percentile_cross_sectional",
        max_tickers_applied=resolved_speculation_max,
    )
    comparison_bundles = _comparison_bundles(
        app_config=app_config,
        tool_a=tool_a,
        candidate_grids=candidate_grids,
        risk_free_rate=effective_risk_free_rate,
        quantity=resolved_quantity,
    )
    comparison = ComparisonViewData(
        rows=build_comparison_table(
            bundles=comparison_bundles,
            sort_by=comparison_sort,
        ),
        sort_by=comparison_sort,
    )
    return HedgeReadinessSections(
        header=header,
        summary=SnapshotSummaryData(
            as_of_date=str(manifest.get("as_of_date", "unknown")),
            refresh_run_id=refresh_run_id,
            risk_free_rate=risk_free_rate,
            risk_free_rate_is_fallback=risk_free_rate_is_fallback,
            holdings_count=len(holdings),
            holdings_mode=_holdings_mode(holdings),
            scenario_quantity=resolved_quantity,
            ranking_max_tickers=resolved_ranking_max,
            speculation_max_tickers=resolved_speculation_max,
            optionability_counts=optionability_counts,
            context_alignment=alignment,
        ),
        sensitivity_ranking=sensitivity,
        portfolio_totals=portfolio,
        held_positions=held_positions,
        speculation_candidates=speculation,
        comparison=comparison,
        proxy_hedges=(
            ProxyHedgesData(
                target_tickers=sorted(non_optionable_held),
                by_target=proxy_map,
            )
            if non_optionable_held
            else None
        ),
        sources=SourcesData(
            run_id=run_context.run_id if run_context is not None else "render-only",
            options_snapshot_run_id=refresh_run_id,
            risk_free_rate=risk_free_rate,
            risk_free_rate_is_fallback=risk_free_rate_is_fallback,
            scenario_quantity=resolved_quantity,
            ranking_max_tickers=resolved_ranking_max,
            speculation_max_tickers=resolved_speculation_max,
            replay_manifest_path=(
                (run_context.run_dir / "replay_manifest.json")
                .relative_to(paths.repo_root)
                .as_posix()
                if run_context is not None
                else "n/a"
            ),
            latest_options_manifest_path=(
                paths.latest_options_manifest_path.relative_to(paths.repo_root).as_posix()
            ),
            raw_option_snapshot_count=len(manifest.get("snapshots", [])),
            options_feature_row_count=len(features.index),
            tool_a_row_count=len(tool_a.index),
            tool_b_row_count=len(tool_b.index),
        ),
    )


def render_markdown(*, sections: HedgeReadinessSections, paths: ProjectPaths) -> str:
    """Render already-built hedge-readiness section data to markdown."""

    lines: list[str] = []
    lines.extend(_render_header_section(sections.header, sections.summary))
    lines.extend(_render_snapshot_summary(sections.summary))
    lines.extend(_render_sensitivity_ranking(sections.sensitivity_ranking))
    if sections.portfolio_totals is not None:
        lines.extend(_render_portfolio_totals(sections.portfolio_totals))
    if sections.held_positions is not None:
        lines.extend(
            _render_held_positions(
                sections.held_positions,
                risk_free_rate_is_fallback=sections.summary.risk_free_rate_is_fallback,
            )
        )
    lines.extend(
        _render_speculation_candidates(
            sections.speculation_candidates,
            risk_free_rate_is_fallback=sections.summary.risk_free_rate_is_fallback,
        )
    )
    lines.extend(_render_comparison_view(sections.comparison))
    if sections.proxy_hedges is not None:
        lines.extend(_render_proxy_hedges(sections.proxy_hedges))
    lines.extend(_render_sources_section(sections.sources, paths=paths))
    return "\n".join(lines).rstrip() + "\n"


def _render_header_section(
    header: HeaderContext,
    summary: SnapshotSummaryData,
) -> list[str]:
    lines = [
        "# Hedge Readiness Report",
        "",
        f"- Options snapshot date: {summary.as_of_date}",
        f"- Options source run: `{summary.refresh_run_id}`",
        f"- Risk-free rate for deltas: {_fmt_rate_with_fallback(summary)}",
        f"- Holdings mode: {summary.holdings_mode}",
        "",
        "Market context:",
        "",
        "| Asset | Price | 1d | 1w | 1m |",
        "|---|---:|---:|---:|---:|",
        f"| Gold | {_fmt_money(header.gold.price)} | {_fmt_pct(header.gold.change_1d)} | "
        f"{_fmt_pct(header.gold.change_1w)} | {_fmt_pct(header.gold.change_1m)} |",
        f"| GDX | {_fmt_money(header.gdx.price)} | {_fmt_pct(header.gdx.change_1d)} | "
        f"{_fmt_pct(header.gdx.change_1w)} | {_fmt_pct(header.gdx.change_1m)} |",
        "",
        "Implied vs modeled downside:",
        "",
    ]
    if header.implied_vs_modeled_rows:
        lines.extend(
            [
                "| Ticker | Implied move 60d | Modeled downside at gold -10% | Verdict |",
                "|---|---:|---:|---|",
            ]
        )
        for row in header.implied_vs_modeled_rows[:10]:
            lines.append(
                "| "
                f"{row.ticker} | "
                f"{_fmt_pct(row.implied_move_60d)} | "
                f"{_fmt_pct(row.modeled_downside_at_minus10)} | "
                f"{row.verdict} |"
            )
    else:
        lines.append("No optionable rows had enough data for the header heuristic.")
    if header.data_notes:
        lines.extend(["", "Header data notes:"])
        lines.extend(f"- {note}" for note in header.data_notes)
    lines.append("")
    return lines


def _render_snapshot_summary(summary: SnapshotSummaryData) -> list[str]:
    alignment = summary.context_alignment
    lines = [
        "## Snapshot Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Options source run | `{summary.refresh_run_id}` |",
        f"| Options snapshot date | {summary.as_of_date} |",
        f"| Risk-free rate | {_fmt_rate_with_fallback(summary)} |",
        f"| Directly hedgeable | {summary.optionability_counts.get('directly_hedgeable', 0)} |",
        f"| Thin options | {summary.optionability_counts.get('thin', 0)} |",
        f"| No listed options | {summary.optionability_counts.get('none', 0)} |",
        f"| Holdings loaded | {summary.holdings_count} |",
        f"| Holdings mode | {summary.holdings_mode} |",
        f"| Scenario quantity | {summary.scenario_quantity} contracts |",
        f"| Ranking max tickers | {summary.ranking_max_tickers} |",
        f"| Speculation max tickers | {summary.speculation_max_tickers} |",
        f"| Tool A snapshot refresh | {_fmt_run_ids(alignment.tool_a_refresh_run_ids)} |",
        f"| Tool B snapshot refresh | {_fmt_run_ids(alignment.tool_b_refresh_run_ids)} |",
        f"| Analytical context alignment | {alignment.status} |",
        "",
    ]
    if summary.risk_free_rate_is_fallback:
        lines.extend(
            [
                "Risk-free-rate note: latest options data has no risk-free rate; "
                "scenario Black-Scholes values use a 0% fallback.",
                "",
            ]
        )
    if alignment.message:
        lines.extend([f"Alignment note: {alignment.message}", ""])
    return lines


def _render_sensitivity_ranking(ranking: SensitivityRankingData) -> list[str]:
    lines = [
        "## Sensitivity Ranking",
        "",
        SENSITIVITY_RANKING_CAVEAT,
        IV_SKEW_CAVEAT,
        IV_RV_RATIO_CAVEAT,
        "",
        f"Sorted by `{ranking.sort_by}`. "
        f"Showing {len(ranking.rows)} of {ranking.total_count} tickers.",
        "",
    ]
    if not ranking.rows:
        return [*lines, "No Tool A rows are available for sensitivity ranking.", ""]
    lines.extend(
        [
            "| Rank | Ticker | Down beta | Plain beta | Up beta | Confidence | IV percentile | "
            "IV skew 60d | IV/RV 60d | "
            f"P&L/share at gold {RANKING_PNL_GOLD_MOVE:.0%} | "
            "Optionability | Notes |",
            "|---:|---|---:|---:|---:|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in ranking.rows:
        lines.append(
            "| "
            f"{row.rank if row.rank is not None else 'n/a'} | "
            f"{row.ticker} | "
            f"{_fmt_number(row.down_beta_core)} | "
            f"{_fmt_number(row.structural_delta_core)} | "
            f"{_fmt_number(row.up_beta_core)} | "
            f"{row.confidence_label} | "
            f"{_fmt_number(row.iv_percentile_cross_sectional)} | "
            f"{_fmt_pct(row.iv_skew_60d)} | "
            f"{_fmt_number(row.iv_rv_ratio_60d)} | "
            f"{_fmt_price(row.pnl_at_minus10_60d)} | "
            f"{row.optionability_tier} | "
            f"{'; '.join(row.notes) if row.notes else ''} |"
        )
    lines.append("")
    return lines


def _render_portfolio_totals(totals: PortfolioTotalsData) -> list[str]:
    lines = [
        "## Portfolio Totals",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Holdings loaded | {totals.holdings_count} |",
        f"| Holdings in total value | {totals.holdings_resolved_count} |",
        f"| Current portfolio notional | {_fmt_money(totals.current_total_value)} |",
        "",
        "Portfolio scenarios:",
        "",
        "| Gold move | Portfolio value | Loss dollars | Loss pct |",
        "|---:|---:|---:|---:|",
    ]
    for row in totals.scenario_rows:
        lines.append(
            "| "
            f"{_fmt_pct(row.gold_pct_change)} | "
            f"{_fmt_money(row.portfolio_value_at_scenario)} | "
            f"{_fmt_money(row.portfolio_loss_dollars)} | "
            f"{_fmt_pct(row.portfolio_loss_pct)} |"
        )
    lines.extend(["", "Hedge-cost estimates:", ""])
    lines.extend(["| Protection level | Estimated premium |", "|---:|---:|"])
    for level, cost in sorted(totals.hedge_cost_by_protection.items()):
        lines.append(f"| {_fmt_pct(level)} | {_fmt_money(cost)} |")
    lines.append("")
    lines.extend(_render_reason_list(
        title="Excluded from portfolio totals",
        reasons=totals.holdings_excluded_from_totals,
    ))
    lines.extend(_render_reason_list(
        title="Downside model skipped",
        reasons=totals.downside_model_skipped,
    ))
    lines.extend(_render_reason_list(
        title="Hedge-cost skipped",
        reasons=totals.hedge_cost_skipped,
    ))
    if totals.interpretive_notes:
        lines.extend(["Portfolio notes:"])
        lines.extend(f"- {note}" for note in totals.interpretive_notes)
        lines.append("")
    return lines


def _render_held_positions(
    data: HeldPositionsData,
    *,
    risk_free_rate_is_fallback: bool,
) -> list[str]:
    lines = ["## Held Positions", ""]
    if not data.holdings:
        return [*lines, "No holdings are configured.", ""]
    if risk_free_rate_is_fallback:
        lines.extend(
            [
                "Scenario note: Black-Scholes current values use a 0% risk-free-rate fallback.",
                "",
            ]
        )
    for holding in data.holdings:
        lines.extend(
            [
                f"### {holding.ticker}",
                "",
                f"- Exposure: {_fmt_money(holding.exposure_usd)}",
                f"- Current stock price: {_fmt_price(holding.current_stock_price)}",
                f"- Optionability: {holding.optionability_tier}",
                f"- Tool A down beta: {_fmt_number(holding.down_beta_core)}",
                f"- Tool A confidence: {_fmt_number(holding.confidence_score)}",
                f"- Tool B verdict: {holding.tool_b_verdict}",
                "",
            ]
        )
        if holding.notes:
            lines.extend(f"- {note}" for note in holding.notes)
            lines.append("")
        if holding.candidates:
            lines.extend(_render_candidate_table(holding.candidates))
        if holding.premium_card is not None:
            lines.extend(_render_premium_card(holding.premium_card))
        else:
            lines.extend(
                [
                    "Premium vs modeled downside:",
                    "",
                    "No premium comparison available because no candidate put was found.",
                    "",
                ]
            )
        if holding.scenario_bundles:
            lines.extend(_render_scenario_bundles(holding.scenario_bundles))
    return lines


def _render_speculation_candidates(
    data: SpeculationCandidatesData,
    *,
    risk_free_rate_is_fallback: bool,
) -> list[str]:
    lines = [
        "## Speculation Candidates",
        "",
        f"Sorted by `{data.sort_by}` ascending. "
        f"Showing up to {data.max_tickers_applied} optionable tickers.",
        LONG_OPTION_PREMIUM_CAVEAT,
        IV_SKEW_CAVEAT,
        IV_RV_RATIO_CAVEAT,
        "",
    ]
    if risk_free_rate_is_fallback:
        lines.extend(
            [
                "Scenario note: Black-Scholes current values use a 0% risk-free-rate fallback.",
                "",
            ]
        )
    if not data.blocks:
        return [*lines, "No speculative put candidates are available.", ""]
    for block in data.blocks:
        lines.extend(
            [
                f"### {block.ticker}",
                "",
                f"- Current stock price: {_fmt_price(block.current_stock_price)}",
                f"- Optionability: {block.optionability_tier}",
                f"- IV percentile: {_fmt_number(block.iv_percentile_cross_sectional)}",
                f"- IV skew 60d: {_fmt_pct(block.iv_skew_60d)}",
                f"- IV/RV ratio 60d: {_fmt_number(block.iv_rv_ratio_60d)}",
                f"- Tool A down beta: {_fmt_number(block.down_beta_core)}",
                f"- Tool A confidence: {block.confidence_label}",
                "",
            ]
        )
        if block.annotations:
            lines.extend(f"- {annotation}" for annotation in block.annotations)
            lines.append("")
        if block.candidates:
            lines.extend(_render_candidate_table(block.candidates))
        if block.scenario_bundles:
            lines.extend(_render_scenario_bundles(block.scenario_bundles))
    return lines


def _render_comparison_view(data: ComparisonViewData) -> list[str]:
    lines = [
        "## Cross-ticker Comparison View",
        "",
        f"Sorted by `{data.sort_by}`.",
        "P&L columns are option quote-style per-share values; net dollar P&L uses "
        "the selected contract quantity and the standard 100-share multiplier.",
        "",
    ]
    if not data.rows:
        return [*lines, "No comparable scenario rows are available.", ""]
    lines.extend(
        [
            "| Ticker | Horizon | Strike | Expiry | Premium | Breakeven gold | "
            "P&L/share -5% | P&L/share -10% | P&L/share -20% | P&L/$ premium -10% |",
            "|---|---:|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in data.rows:
        lines.append(
            "| "
            f"{row.ticker} | "
            f"{row.horizon} | "
            f"{_fmt_number(row.strike)} | "
            f"{row.expiry} | "
            f"{_fmt_price(row.premium_mid)} | "
            f"{_fmt_pct(row.breakeven_gold_pct)} | "
            f"{_fmt_price(row.pnl_per_contract_minus5)} | "
            f"{_fmt_price(row.pnl_per_contract_minus10)} | "
            f"{_fmt_price(row.pnl_per_contract_minus20)} | "
            f"{_fmt_number(row.pnl_per_dollar_premium_minus10)} |"
        )
    lines.append("")
    return lines


def _render_proxy_hedges(data: ProxyHedgesData) -> list[str]:
    lines = ["## Proxy Hedges", ""]
    if not data.by_target:
        targets = ", ".join(data.target_tickers)
        return [
            *lines,
            "Held non-optionable tickers were found, but no proxy matches "
            f"passed the filters: {targets}.",
            "",
        ]
    lines.extend(
        [
            "| Target | Proxy | Type | Down-beta diff | Basis risk | Context |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for target, matches in sorted(data.by_target.items()):
        for match in matches:
            context = match.reason
            if match.tool_b_verdict:
                context = f"Tool B {match.tool_b_verdict}; {context}"
            lines.append(
                "| "
                f"{target} | "
                f"{match.proxy_ticker} | "
                f"{match.proxy_type} | "
                f"{_fmt_number(match.down_beta_diff)} | "
                f"{match.basis_risk_label} | "
                f"{context} |"
            )
    lines.append("")
    return lines


def _render_sources_section(sources: SourcesData, *, paths: ProjectPaths) -> list[str]:
    _ = paths
    return [
        "## Sources / Run Summary",
        "",
        f"- Hedge readiness run id: `{sources.run_id}`",
        f"- Options snapshot run id: `{sources.options_snapshot_run_id}`",
        f"- Latest options manifest: `{sources.latest_options_manifest_path}`",
        f"- Replay manifest: `{sources.replay_manifest_path}`",
        f"- Risk-free rate: {_fmt_source_rate(sources)}",
        f"- Scenario quantity: {sources.scenario_quantity} contracts",
        f"- Ranking max tickers: {sources.ranking_max_tickers}",
        f"- Speculation max tickers: {sources.speculation_max_tickers}",
        f"- Tool A rows: {sources.tool_a_row_count}",
        f"- Tool B rows: {sources.tool_b_row_count}",
        f"- Raw option snapshots: {sources.raw_option_snapshot_count}",
        f"- Options feature rows: {sources.options_feature_row_count}",
        "",
    ]


def _render_reason_list(
    *,
    title: str,
    reasons: list[tuple[str, str]],
) -> list[str]:
    if not reasons:
        return []
    lines = [f"{title}:", ""]
    lines.extend(f"- {ticker}: {reason}" for ticker, reason in reasons)
    lines.append("")
    return lines


def _render_candidate_table(candidates: list[CandidatePut]) -> list[str]:
    lines = ["Candidate puts:", ""]
    if not candidates:
        return [*lines, "No usable listed put candidate found for the configured horizons.", ""]
    lines.extend(
        [
            "| Horizon | Expiration | Strike | Delta | Delta gap | Mid | OI | Volume | Premium % spot |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for candidate in candidates:
        lines.append(
            "| "
            f"{candidate.horizon_days}d | "
            f"{candidate.expiration} | "
            f"{_fmt_number(candidate.strike)} | "
            f"{_fmt_number(candidate.delta)} | "
            f"{_fmt_number(candidate.delta_gap)} | "
            f"{_fmt_price(candidate.mid)} | "
            f"{candidate.open_interest if candidate.open_interest is not None else 'n/a'} | "
            f"{candidate.volume if candidate.volume is not None else 'n/a'} | "
            f"{_fmt_pct(candidate.premium_pct_spot)} |"
        )
    lines.append("")
    return lines


def _render_premium_card(card: PremiumVsDownsideCard) -> list[str]:
    lines = [
        "Premium vs modeled downside:",
        "",
        f"Using {card.horizon_days}d candidate.",
        "",
        "| Gold down | Modeled stock down | Modeled downside | Full hedge premium | Hedge ratio | Tag |",
        "|---:|---:|---:|---:|---:|---|",
    ]
    for scenario in card.scenarios:
        lines.append(
            "| "
            f"{_fmt_pct(scenario.gold_down_pct)} | "
            f"{_fmt_pct(scenario.modeled_stock_down_pct)} | "
            f"{_fmt_money(scenario.modeled_downside_usd)} | "
            f"{_fmt_money(scenario.hedge_premium_usd)} | "
            f"{_fmt_number(scenario.hedge_ratio)} | "
            f"{scenario.tag} |"
        )
    lines.append("")
    return lines


def _render_scenario_bundles(bundles: list[CandidateScenarioBundle]) -> list[str]:
    lines = [
        "Scenario P&L:",
        "",
        "Modeled option values use Black-Scholes with unchanged days-to-expiry "
        "and constant implied volatility; they are not live market quotes. "
        f"{OPTION_REPRICE_ASSUMPTION}",
        "P&L/share starts from the listed per-share option premium; net P&L applies "
        "the selected contract quantity and the standard 100-share multiplier.",
        "",
    ]
    if not bundles:
        return [*lines, "No scenario bundles are available.", ""]
    for bundle in bundles:
        lines.extend(
            [
                f"{bundle.horizon} candidate, strike {_fmt_number(bundle.candidate.strike)}:",
                "",
            ]
        )
        if bundle.skipped_reason:
            lines.extend([bundle.skipped_reason, ""])
            continue
        if bundle.breakeven_annotation:
            lines.extend([bundle.breakeven_annotation, ""])
        lines.extend(
            [
                "| Gold move | Modeled stock | Modeled value at expiry | "
                "Modeled value now | P&L/share expiry | P&L/share today | "
                "Net P&L expiry | Model note |",
                "|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in bundle.rows:
            clamp_note = " (clamped)" if row.stock_clamped_at_zero else ""
            model_note = scenario_model_note(row.gold_pct_change)
            lines.append(
                "| "
                f"{_fmt_pct(row.gold_pct_change)} | "
                f"{_fmt_price(row.implied_stock_price)}{clamp_note} | "
                f"{_fmt_price(row.expiry_value_per_contract)} | "
                f"{_fmt_price(row.current_value_per_contract)} | "
                f"{_fmt_price(row.pnl_per_contract_at_expiry)} | "
                f"{_fmt_price(row.pnl_per_contract_if_closed_today)} | "
                f"{_fmt_money(row.net_pnl_at_expiry)} | "
                f"{model_note} |"
            )
        lines.append("")
    return lines


def _load_report_data(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    tool_a = _read_required_parquet(
        paths.latest_tool_a_snapshot_parquet_path,
        "Tool A latest output",
    )
    tool_b = _read_optional_parquet(paths.latest_tool_b_snapshot_parquet_path)
    chains = _load_chains(paths=paths, manifest=manifest)
    features = _load_features(paths=paths, manifest=manifest)
    return {
        "tool_a": tool_a,
        "tool_b": tool_b,
        "chains": chains,
        "features": features,
    }


def _load_chains(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    chains: dict[str, pd.DataFrame] = {}
    for item in manifest.get("snapshots", []):
        ticker = str(item.get("ticker", "")).upper()
        if not ticker:
            continue
        snapshot_path = paths.resolve_repo_relative(str(item.get("snapshot_path", "")))
        chains[ticker] = _read_optional_parquet(snapshot_path)
    return chains


def _load_features(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
) -> pd.DataFrame:
    rows: list[pd.Series] = []
    refresh_run_id = str(manifest.get("refresh_run_id", ""))
    for item in manifest.get("snapshots", []):
        ticker = str(item.get("ticker", ""))
        feature_path = paths.options_features_dir / f"{safe_options_file_name(ticker)}.parquet"
        frame = _read_optional_parquet(feature_path)
        if frame.empty:
            continue
        if "run_id" in frame.columns:
            matching = frame[frame["run_id"].astype(str) == refresh_run_id]
            if not matching.empty:
                rows.append(matching.iloc[-1])
            continue
        rows.append(frame.iloc[-1])
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).reset_index(drop=True)


def _build_held_positions(
    *,
    app_config: AppConfig,
    holdings: list[Holding],
    features: pd.DataFrame,
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
    candidate_grids: dict[str, list[CandidatePut]],
    risk_free_rate: float,
    risk_free_rate_is_fallback: bool,
    quantity: int,
) -> HeldPositionsData:
    config = app_config.hedge_readiness
    feature_by_ticker = _index_by_ticker(features)
    tool_a_by_ticker = _index_by_ticker(tool_a)
    tool_b_by_ticker = _index_by_ticker(tool_b)
    positions: list[HoldingPositionData] = []
    for holding in holdings:
        feature = feature_by_ticker.get(holding.ticker)
        tool_a_row = tool_a_by_ticker.get(holding.ticker)
        tool_b_row = tool_b_by_ticker.get(holding.ticker)
        price = _current_stock_price(
            feature=feature,
            tool_b_row=tool_b_row,
            chain=pd.DataFrame(),
        )
        candidates = candidate_grids.get(holding.ticker, [])
        if price is None and candidates:
            price = candidates[0].underlying_price
        exposure = holding.exposure_usd(share_price=price)
        down_beta = _row_float(tool_a_row, "down_beta_core")
        confidence_label = _confidence_label(tool_a_row)
        scenario_bundles = [
            compute_scenario_bundle(
                candidate=candidate,
                current_stock_price=candidate.underlying_price,
                gold_beta=down_beta,
                confidence_label=confidence_label,
                risk_free_rate=risk_free_rate,
                gold_beta_min_for_scenario=config.down_beta_min_for_scenario,
                gold_scenarios=tuple(config.default_scenarios),
                quantity=quantity,
            )
            for candidate in candidates
        ]
        preferred = _preferred_candidate(candidates) if candidates else None
        premium_card = (
            compute_premium_vs_downside(
                ticker=holding.ticker,
                down_beta=down_beta,
                confidence_score=_row_float(tool_a_row, "confidence_score"),
                holding=holding,
                candidate_put=preferred,
                gold_scenarios=tuple(config.gold_down_scenarios),
                cheap_ratio_max=config.hedge_ratio_cheap_max,
                expensive_ratio_min=config.hedge_ratio_expensive_min,
            )
            if preferred is not None
            else None
        )
        notes: list[str] = []
        if not candidates:
            notes.append("No usable listed put candidate found for this holding.")
        if risk_free_rate_is_fallback and scenario_bundles:
            notes.append("Risk-free rate unavailable; scenario values use 0% fallback.")
        positions.append(
            HoldingPositionData(
                ticker=holding.ticker,
                exposure_usd=exposure,
                optionability_tier=_optionability_tier(
                    _row_string(feature, "optionability_tier")
                ),
                current_stock_price=price,
                down_beta_core=down_beta,
                confidence_score=_row_float(tool_a_row, "confidence_score"),
                tool_b_verdict=_row_string(tool_b_row, "screening_verdict") or "n/a",
                candidates=candidates,
                scenario_bundles=scenario_bundles,
                premium_card=premium_card,
                notes=notes,
            )
        )
    return HeldPositionsData(positions)


def _candidate_grids(
    *,
    app_config: AppConfig,
    features: pd.DataFrame,
    tool_b: pd.DataFrame,
    chains: dict[str, pd.DataFrame],
    risk_free_rate: float,
) -> dict[str, list[CandidatePut]]:
    tool_b_by_ticker = _index_by_ticker(tool_b)
    grids: dict[str, list[CandidatePut]] = {}
    for feature in _feature_rows(features):
        ticker = str(feature.get("ticker") or "").upper()
        if not ticker:
            continue
        chain = chains.get(ticker, pd.DataFrame())
        price = _current_stock_price(
            feature=feature,
            tool_b_row=tool_b_by_ticker.get(ticker),
            chain=chain,
        )
        if price is None or price <= 0:
            grids[ticker] = []
            continue
        grids[ticker] = build_candidate_put_grid(
            ticker=ticker,
            chain=chain,
            underlying_price=price,
            risk_free_rate=risk_free_rate,
            target_horizons_days=tuple(app_config.hedge_readiness.target_horizons_days),
            target_delta=app_config.hedge_readiness.target_delta,
            max_spread_pct=app_config.hedge_readiness.candidate_max_spread_pct,
            min_open_interest=app_config.hedge_readiness.candidate_min_open_interest,
            min_volume=app_config.hedge_readiness.candidate_min_volume,
            min_implied_volatility=(
                app_config.hedge_readiness.candidate_min_implied_volatility
            ),
            max_implied_volatility=(
                app_config.hedge_readiness.candidate_max_implied_volatility
            ),
            max_delta_gap=app_config.hedge_readiness.delta_gap_warning_threshold,
        )
    return grids


def _comparison_bundles(
    *,
    app_config: AppConfig,
    tool_a: pd.DataFrame,
    candidate_grids: dict[str, list[CandidatePut]],
    risk_free_rate: float,
    quantity: int,
) -> list[CandidateScenarioBundle]:
    config = app_config.hedge_readiness
    tool_a_by_ticker = _index_by_ticker(tool_a)
    bundles: list[CandidateScenarioBundle] = []
    for ticker, candidates in sorted(candidate_grids.items()):
        tool_a_row = tool_a_by_ticker.get(ticker)
        down_beta = _row_float(tool_a_row, "down_beta_core")
        confidence_label = _confidence_label(tool_a_row)
        for candidate in candidates:
            bundles.append(
                compute_scenario_bundle(
                    candidate=candidate,
                    current_stock_price=candidate.underlying_price,
                    gold_beta=down_beta,
                    confidence_label=confidence_label,
                    risk_free_rate=risk_free_rate,
                    gold_beta_min_for_scenario=config.down_beta_min_for_scenario,
                    gold_scenarios=tuple(config.default_scenarios),
                    quantity=quantity,
                )
            )
    return bundles


def _current_stock_price(
    *,
    feature: pd.Series | dict[str, Any] | None,
    tool_b_row: pd.Series | None,
    chain: pd.DataFrame,
) -> float | None:
    for value in (
        _row_float(feature, "underlying_price"),
        _first_chain_value(chain, "underlying_price"),
        _row_float(tool_b_row, "share_price_usd"),
    ):
        price = _as_float(value)
        if price is not None and price > 0:
            return price
    return None


def _feature_rows(features: pd.DataFrame) -> list[dict[str, Any]]:
    if features.empty:
        return []
    return [row.to_dict() for _, row in features.iterrows()]


def _first_chain_value(chain: pd.DataFrame, column: str) -> object:
    if chain.empty or column not in chain.columns:
        return None
    values = chain[column].dropna()
    return values.iloc[0] if not values.empty else None


def _preferred_candidate(candidates: list[CandidatePut]) -> CandidatePut:
    return min(candidates, key=lambda item: (abs(item.horizon_days - 60), item.horizon_days))


def _optionable_tickers(features: pd.DataFrame) -> set[str]:
    if features.empty or "ticker" not in features.columns:
        return set()
    if "optionability_tier" not in features.columns:
        return set()
    optionable = features[features["optionability_tier"].map(_is_optionable_tier)]
    return set(optionable["ticker"].astype(str).str.upper())


def _read_latest_options_manifest(paths: ProjectPaths) -> dict[str, Any]:
    if not paths.latest_options_manifest_path.exists():
        raise FileNotFoundError(
            "No hedge-readiness options snapshot exists yet. Run `python main.py update-data` first."
        )
    return json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))


def _read_required_parquet(path: Path, description: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing {description}: {path}")
    return pd.read_parquet(path)


def _read_optional_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    counts = frame[column].fillna("unknown").astype(str).value_counts()
    return {str(key): int(value) for key, value in counts.items()}


def _context_alignment(
    *,
    options_refresh_run_id: str,
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
) -> ContextAlignment:
    tool_a_refresh_ids = _unique_strings(tool_a, "snapshot_refresh_run_id")
    tool_b_refresh_ids = _unique_strings(tool_b, "snapshot_refresh_run_id")
    if not options_refresh_run_id or options_refresh_run_id == "unknown":
        return ContextAlignment(
            status="UNKNOWN",
            message="Options refresh run id is missing.",
            tool_a_refresh_run_ids=tool_a_refresh_ids,
            tool_b_refresh_run_ids=tool_b_refresh_ids,
        )

    missing: list[str] = []
    if not tool_a_refresh_ids:
        missing.append("Tool A snapshot refresh run id is missing")
    if not tool_b.empty and not tool_b_refresh_ids:
        missing.append("Tool B snapshot refresh run id is missing")
    if missing:
        return ContextAlignment(
            status="UNKNOWN",
            message="; ".join(missing) + ".",
            tool_a_refresh_run_ids=tool_a_refresh_ids,
            tool_b_refresh_run_ids=tool_b_refresh_ids,
        )

    mismatches: list[str] = []
    if tool_a_refresh_ids and options_refresh_run_id not in tool_a_refresh_ids:
        mismatches.append("Tool A snapshot refresh does not match options source run")
    if tool_b_refresh_ids and options_refresh_run_id not in tool_b_refresh_ids:
        mismatches.append("Tool B snapshot refresh does not match options source run")
    if mismatches:
        return ContextAlignment(
            status="WARN",
            message="; ".join(mismatches) + ".",
            tool_a_refresh_run_ids=tool_a_refresh_ids,
            tool_b_refresh_run_ids=tool_b_refresh_ids,
        )
    return ContextAlignment(
        status="OK",
        message=None,
        tool_a_refresh_run_ids=tool_a_refresh_ids,
        tool_b_refresh_run_ids=tool_b_refresh_ids,
    )


def _summary_from_sections(sections: HedgeReadinessSections) -> dict[str, Any]:
    summary = sections.summary
    return {
        "options_as_of_date": summary.as_of_date,
        "options_refresh_run_id": summary.refresh_run_id,
        "ticker_count": sections.sensitivity_ranking.total_count,
        "holdings_count": summary.holdings_count,
        "holdings_mode": summary.holdings_mode,
        "directly_hedgeable_count": summary.optionability_counts.get(
            "directly_hedgeable",
            0,
        ),
        "thin_count": summary.optionability_counts.get("thin", 0),
        "none_count": summary.optionability_counts.get("none", 0),
        "sensitivity_row_count": len(sections.sensitivity_ranking.rows),
        "portfolio_totals_present": sections.portfolio_totals is not None,
        "held_positions_present": sections.held_positions is not None,
        "speculation_candidate_count": len(sections.speculation_candidates.blocks),
        "comparison_row_count": len(sections.comparison.rows),
        "proxy_target_count": (
            len(sections.proxy_hedges.target_tickers)
            if sections.proxy_hedges is not None
            else 0
        ),
        "context_alignment_status": summary.context_alignment.status,
        "context_alignment_message": summary.context_alignment.message,
        "tool_a_snapshot_refresh_run_ids": summary.context_alignment.tool_a_refresh_run_ids,
        "tool_b_snapshot_refresh_run_ids": summary.context_alignment.tool_b_refresh_run_ids,
        "risk_free_rate": summary.risk_free_rate,
        "risk_free_rate_is_fallback": summary.risk_free_rate_is_fallback,
        "scenario_quantity": summary.scenario_quantity,
        "comparison_sort_by": sections.comparison.sort_by,
        "ranking_sort_by": sections.sensitivity_ranking.sort_by,
        "ranking_max_tickers": summary.ranking_max_tickers,
        "speculation_max_tickers": sections.speculation_candidates.max_tickers_applied,
        "options_feature_row_count": sections.sources.options_feature_row_count,
    }


def _holdings_mode(holdings: list[Holding]) -> str:
    if not holdings:
        return "empty"
    has_shares = any(holding.shares is not None for holding in holdings)
    has_dollars = any(holding.dollar_exposure is not None for holding in holdings)
    if has_shares and has_dollars:
        return "mixed"
    if has_shares:
        return "shares"
    return "dollar_exposure"


def _unique_strings(frame: pd.DataFrame, column: str) -> list[str]:
    if frame.empty or column not in frame.columns:
        return []
    values = frame[column].dropna().astype(str).str.strip()
    return sorted(value for value in values.unique().tolist() if value)


def _confidence_label(row: pd.Series | None) -> str:
    label = _row_string(row, "confidence_label")
    if label:
        return label
    confidence_score = _row_float(row, "confidence_score")
    return f"score {confidence_score:.2f}" if confidence_score is not None else "n/a"


def _fmt_number(value: object, digits: int = 2) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:.{digits}f}"


def _fmt_pct(value: object) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric * 100:.1f}%"


def _fmt_money(value: object) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "n/a"
    return f"${numeric:,.0f}"


def _fmt_price(value: object) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return "n/a"
    return f"${numeric:,.2f}"


def _fmt_run_ids(values: object) -> str:
    if not isinstance(values, list) or not values:
        return "n/a"
    if len(values) == 1:
        return str(values[0])
    return ", ".join(str(value) for value in values)


def _fmt_rate_with_fallback(summary: SnapshotSummaryData) -> str:
    if summary.risk_free_rate_is_fallback:
        return "0.0% fallback"
    return _fmt_pct(summary.risk_free_rate)


def _fmt_source_rate(sources: SourcesData) -> str:
    if sources.risk_free_rate_is_fallback:
        return "unavailable; 0.0% fallback used for scenario values"
    return _fmt_pct(sources.risk_free_rate)
