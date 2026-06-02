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
from golden_vector.hedge.candidate_puts import CandidatePut, build_candidate_put_grid
from golden_vector.hedge.expected_downside import compute_premium_vs_downside
from golden_vector.hedge.holdings import Holding, load_holdings
from golden_vector.hedge.proxy_hedge import ProxyMatch, map_proxy_hedges
from golden_vector.ingestion.persist_options import safe_options_file_name


@dataclass(frozen=True)
class HedgeReportResult:
    report_path: Path
    latest_path: Path
    markdown: str
    summary: dict[str, Any]


def write_hedge_readiness_report(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    app_config: AppConfig,
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
    markdown, summary = render_hedge_readiness_report(
        paths=paths,
        app_config=app_config,
        manifest=payload,
        data=data,
        holdings=holdings,
    )
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
) -> tuple[str, dict[str, Any]]:
    """Assemble the full hedge-readiness report as markdown."""

    features = data["features"]
    tool_a = data["tool_a"]
    tool_b = data["tool_b"]
    chains = data["chains"]
    risk_free_rate = _as_float(manifest.get("risk_free_rate"))
    as_of_date = str(manifest.get("as_of_date", "unknown"))
    refresh_run_id = str(manifest.get("refresh_run_id", "unknown"))
    optionability_counts = _value_counts(features, "optionability_tier")
    alignment = _context_alignment(
        options_refresh_run_id=refresh_run_id,
        tool_a=tool_a,
        tool_b=tool_b,
    )
    optionable_tickers = _optionable_tickers(features)
    held_tickers = [holding.ticker for holding in holdings]
    non_optionable_held = [
        ticker
        for ticker in held_tickers
        if ticker not in optionable_tickers
    ]
    proxy_map = map_proxy_hedges(
        non_optionable_tickers=non_optionable_held,
        optionable_tickers=sorted(optionable_tickers),
        tool_a_frame=tool_a,
        tool_b_frame=tool_b,
        benchmark_tickers=tuple(app_config.hedge_readiness.benchmark_tickers),
        top_n=app_config.hedge_readiness.proxy_top_n,
        max_beta_diff=app_config.hedge_readiness.proxy_max_beta_diff,
        low_basis_max_beta_diff=(
            app_config.hedge_readiness.proxy_low_basis_max_beta_diff
        ),
        medium_basis_max_beta_diff=(
            app_config.hedge_readiness.proxy_medium_basis_max_beta_diff
        ),
        low_basis_min_confidence=(
            app_config.hedge_readiness.proxy_low_basis_min_confidence
        ),
    )

    lines = [
        "# Hedge Readiness Report",
        "",
        f"- Options snapshot date: {as_of_date}",
        f"- Options source run: `{refresh_run_id}`",
        f"- Risk-free rate for deltas: {_fmt_pct(risk_free_rate)}",
        f"- Holdings mode: {'positions from holdings.yaml' if holdings else 'cross-sectional only'}",
        "",
        "## Snapshot Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Tickers in options manifest | {len(features.index)} |",
        f"| Directly hedgeable | {optionability_counts.get('directly_hedgeable', 0)} |",
        f"| Thin options | {optionability_counts.get('thin', 0)} |",
        f"| No listed options | {optionability_counts.get('none', 0)} |",
        f"| Holdings loaded | {len(holdings)} |",
        f"| Tool A snapshot refresh | {_fmt_run_ids(alignment['tool_a_refresh_run_ids'])} |",
        f"| Tool B snapshot refresh | {_fmt_run_ids(alignment['tool_b_refresh_run_ids'])} |",
        f"| Analytical context alignment | {alignment['status']} |",
        "",
    ]
    if alignment["message"]:
        lines.extend([f"Alignment note: {alignment['message']}", ""])
    lines.extend(_render_holdings_section(
        app_config=app_config,
        holdings_file_exists=paths.holdings_path.exists(),
        holdings=holdings,
        features=features,
        chains=chains,
        tool_a=tool_a,
        tool_b=tool_b,
        risk_free_rate=risk_free_rate,
    ))
    lines.extend(_render_cross_sectional_section(features))
    lines.extend(_render_proxy_section(proxy_map, holdings))
    lines.extend(_render_sources_section(paths=paths, manifest=manifest, data=data))

    summary = {
        "options_as_of_date": as_of_date,
        "options_refresh_run_id": refresh_run_id,
        "ticker_count": len(features.index),
        "holdings_count": len(holdings),
        "directly_hedgeable_count": optionability_counts.get("directly_hedgeable", 0),
        "thin_count": optionability_counts.get("thin", 0),
        "none_count": optionability_counts.get("none", 0),
        "proxy_target_count": len(proxy_map),
        "context_alignment_status": alignment["status"],
        "context_alignment_message": alignment["message"],
        "tool_a_snapshot_refresh_run_ids": alignment["tool_a_refresh_run_ids"],
        "tool_b_snapshot_refresh_run_ids": alignment["tool_b_refresh_run_ids"],
    }
    return "\n".join(lines).rstrip() + "\n", summary


def _render_holdings_section(
    *,
    app_config: AppConfig,
    holdings_file_exists: bool,
    holdings: list[Holding],
    features: pd.DataFrame,
    chains: dict[str, pd.DataFrame],
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
    risk_free_rate: float | None,
) -> list[str]:
    lines = ["## Held Positions", ""]
    if not holdings:
        message = (
            "No holdings are configured in `data/manual/holdings/holdings.yaml`; "
            "showing universe-level hedge readiness only."
            if holdings_file_exists
            else "No `data/manual/holdings/holdings.yaml` file was found; "
            "showing universe-level hedge readiness only."
        )
        return [
            *lines,
            message,
            "",
        ]

    feature_by_ticker = _index_by_ticker(features)
    tool_a_by_ticker = _index_by_ticker(tool_a)
    tool_b_by_ticker = _index_by_ticker(tool_b)
    for holding in holdings:
        feature = feature_by_ticker.get(holding.ticker)
        tool_a_row = tool_a_by_ticker.get(holding.ticker)
        tool_b_row = tool_b_by_ticker.get(holding.ticker)
        price = _row_float(feature, "underlying_price") or _row_float(tool_b_row, "share_price_usd")
        exposure = holding.exposure_usd(share_price=price)
        optionability = _row_string(feature, "optionability_tier") or "none"
        lines.extend(
            [
                f"### {holding.ticker}",
                "",
                f"- Exposure: {_fmt_money(exposure)}",
                f"- Optionability: {optionability}",
                f"- Tool A down beta: {_fmt_number(_row_float(tool_a_row, 'down_beta_core'))}",
                f"- Tool A confidence: {_fmt_number(_row_float(tool_a_row, 'confidence_score'))}",
                f"- Tool B verdict: {_row_string(tool_b_row, 'screening_verdict') or 'n/a'}",
                "",
            ]
        )
        chain = chains.get(holding.ticker, pd.DataFrame())
        candidates = _candidate_grid(
            app_config=app_config,
            ticker=holding.ticker,
            chain=chain,
            feature=feature,
            risk_free_rate=risk_free_rate,
        )
        lines.extend(_render_candidate_table(candidates))
        lines.extend(
            _render_premium_cards(
                app_config=app_config,
                holding=holding,
                candidates=candidates,
                down_beta=_row_float(tool_a_row, "down_beta_core"),
                confidence_score=_row_float(tool_a_row, "confidence_score"),
            )
        )
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
            f"{_fmt_number(candidate.mid)} | "
            f"{candidate.open_interest if candidate.open_interest is not None else 'n/a'} | "
            f"{candidate.volume if candidate.volume is not None else 'n/a'} | "
            f"{_fmt_pct(candidate.premium_pct_spot)} |"
        )
    lines.append("")
    return lines


def _render_premium_cards(
    *,
    app_config: AppConfig,
    holding: Holding,
    candidates: list[CandidatePut],
    down_beta: float | None,
    confidence_score: float | None,
) -> list[str]:
    lines = ["Premium vs modeled downside:", ""]
    if not candidates:
        return [*lines, "No premium comparison available because no candidate put was found.", ""]
    candidate = _preferred_candidate(candidates)
    card = compute_premium_vs_downside(
        ticker=holding.ticker,
        down_beta=down_beta,
        confidence_score=confidence_score,
        holding=holding,
        candidate_put=candidate,
        gold_scenarios=tuple(app_config.hedge_readiness.gold_down_scenarios),
        cheap_ratio_max=app_config.hedge_readiness.hedge_ratio_cheap_max,
        expensive_ratio_min=app_config.hedge_readiness.hedge_ratio_expensive_min,
    )
    lines.extend(
        [
            f"Using {candidate.horizon_days}d candidate at strike {_fmt_number(candidate.strike)}.",
            "",
            "| Gold down | Modeled stock down | Modeled downside | Full hedge premium | Hedge ratio | Tag |",
            "|---:|---:|---:|---:|---:|---|",
        ]
    )
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


def _render_cross_sectional_section(features: pd.DataFrame) -> list[str]:
    lines = ["## Cross-Sectional IV Ranking", ""]
    if features.empty or "iv_percentile_cross_sectional" not in features.columns:
        return [*lines, "No options feature rows are available.", ""]
    ranked = features.copy()
    ranked["iv_percentile_cross_sectional"] = pd.to_numeric(
        ranked["iv_percentile_cross_sectional"],
        errors="coerce",
    )
    ranked = ranked.dropna(subset=["iv_percentile_cross_sectional"]).sort_values(
        "iv_percentile_cross_sectional",
        ascending=True,
    )
    if ranked.empty:
        return [*lines, "No usable 60d ATM IV values are available.", ""]
    lines.extend(
        [
            "| Ticker | Optionability | ATM IV 60d | IV percentile | Put 25d IV 60d | Implied move 60d |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for _, row in ranked.head(10).iterrows():
        lines.append(
            "| "
            f"{row.get('ticker')} | "
            f"{row.get('optionability_tier', 'n/a')} | "
            f"{_fmt_pct(_row_float(row, 'atm_iv_60d'))} | "
            f"{_fmt_number(_row_float(row, 'iv_percentile_cross_sectional'))} | "
            f"{_fmt_pct(_row_float(row, 'put_iv_25d_60d'))} | "
            f"{_fmt_pct(_row_float(row, 'implied_move_60d'))} |"
        )
    lines.append("")
    return lines


def _render_proxy_section(
    proxy_map: dict[str, list[ProxyMatch]],
    holdings: list[Holding],
) -> list[str]:
    lines = ["## Proxy-Hedge Map", ""]
    if not holdings:
        return [*lines, "No holdings loaded, so no held non-optionable tickers require proxy mapping.", ""]
    if not proxy_map:
        return [*lines, "All held tickers with available data are directly optionable.", ""]
    lines.extend(
        [
            "| Target | Proxy | Type | Down-beta diff | Basis risk | Context |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for target, matches in sorted(proxy_map.items()):
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


def _render_sources_section(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
    data: dict[str, Any],
) -> list[str]:
    return [
        "## Sources",
        "",
        f"- Latest options manifest: `{paths.latest_options_manifest_path.relative_to(paths.repo_root).as_posix()}`",
        f"- Tool A rows: {len(data['tool_a'].index)}",
        f"- Tool B rows: {len(data['tool_b'].index)}",
        f"- Raw option snapshots: {len(manifest.get('snapshots', []))}",
        "",
    ]


def _load_report_data(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    tool_a = _read_required_parquet(paths.latest_tool_a_snapshot_parquet_path, "Tool A latest output")
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
        ticker = str(item.get("ticker", ""))
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


def _candidate_grid(
    *,
    app_config: AppConfig,
    ticker: str,
    chain: pd.DataFrame,
    feature: pd.Series | None,
    risk_free_rate: float | None,
) -> list[CandidatePut]:
    underlying_price = _row_float(feature, "underlying_price")
    if underlying_price is None or underlying_price <= 0:
        return []
    return build_candidate_put_grid(
        ticker=ticker,
        chain=chain,
        underlying_price=underlying_price,
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
    )


def _preferred_candidate(candidates: list[CandidatePut]) -> CandidatePut:
    return min(candidates, key=lambda item: (abs(item.horizon_days - 60), item.horizon_days))


def _optionable_tickers(features: pd.DataFrame) -> set[str]:
    if features.empty:
        return set()
    optionable = features[
        features.get("optionability_tier", pd.Series(dtype=str)).astype(str) != "none"
    ]
    return set(optionable["ticker"].astype(str))


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


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, pd.Series]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    return {
        str(row["ticker"]).upper(): row
        for _, row in frame.iterrows()
        if not pd.isna(row.get("ticker"))
    }


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
) -> dict[str, Any]:
    tool_a_refresh_ids = _unique_strings(tool_a, "snapshot_refresh_run_id")
    tool_b_refresh_ids = _unique_strings(tool_b, "snapshot_refresh_run_id")
    if not options_refresh_run_id or options_refresh_run_id == "unknown":
        return {
            "status": "UNKNOWN",
            "message": "Options refresh run id is missing.",
            "tool_a_refresh_run_ids": tool_a_refresh_ids,
            "tool_b_refresh_run_ids": tool_b_refresh_ids,
        }

    missing: list[str] = []
    if not tool_a_refresh_ids:
        missing.append("Tool A snapshot refresh run id is missing")
    if not tool_b.empty and not tool_b_refresh_ids:
        missing.append("Tool B snapshot refresh run id is missing")
    if missing:
        return {
            "status": "UNKNOWN",
            "message": "; ".join(missing) + ".",
            "tool_a_refresh_run_ids": tool_a_refresh_ids,
            "tool_b_refresh_run_ids": tool_b_refresh_ids,
        }

    mismatches: list[str] = []
    if tool_a_refresh_ids and options_refresh_run_id not in tool_a_refresh_ids:
        mismatches.append("Tool A snapshot refresh does not match options source run")
    if tool_b_refresh_ids and options_refresh_run_id not in tool_b_refresh_ids:
        mismatches.append("Tool B snapshot refresh does not match options source run")
    if mismatches:
        return {
            "status": "WARN",
            "message": "; ".join(mismatches) + ".",
            "tool_a_refresh_run_ids": tool_a_refresh_ids,
            "tool_b_refresh_run_ids": tool_b_refresh_ids,
        }
    return {
        "status": "OK",
        "message": None,
        "tool_a_refresh_run_ids": tool_a_refresh_ids,
        "tool_b_refresh_run_ids": tool_b_refresh_ids,
    }


def _unique_strings(frame: pd.DataFrame, column: str) -> list[str]:
    if frame.empty or column not in frame.columns:
        return []
    values = frame[column].dropna().astype(str).str.strip()
    return sorted(value for value in values.unique().tolist() if value)


def _row_float(row: pd.Series | None, column: str) -> float | None:
    if row is None or column not in row.index:
        return None
    value = pd.to_numeric(row[column], errors="coerce")
    if pd.isna(value):
        return None
    return float(value)


def _row_string(row: pd.Series | None, column: str) -> str | None:
    if row is None or column not in row.index or pd.isna(row[column]):
        return None
    return str(row[column])


def _as_float(value: object) -> float | None:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return float(numeric)


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


def _fmt_run_ids(values: object) -> str:
    if not isinstance(values, list) or not values:
        return "n/a"
    if len(values) == 1:
        return str(values[0])
    return ", ".join(str(value) for value in values)
