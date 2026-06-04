from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import run_candidate_finder
from golden_vector.ingestion.persist_options import safe_options_file_name
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.screening.manual_store import upsert_company_input
from golden_vector.serve.candidate_finder_data import (
    clear_candidate_finder_cache,
    load_candidate_finder_data,
    run_candidate_finder_screen,
)
from tests.helpers import build_test_paths


def test_candidate_finder_data_joins_sources_and_derives_ratios(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")

    data = load_candidate_finder_data(paths, app_config=app_config)
    frame = data.frame.set_index("ticker")

    assert data.alignment.status == "OK"
    assert data.cache_key.options_refresh_run_id == "refresh-run"
    assert data.cache_key.manual_store_hash is not None
    assert bool(frame.loc["AEM", "has_usable_put_candidate"]) is True
    assert bool(frame.loc["AEM", "has_usable_call_candidate"]) is True
    assert bool(frame.loc["NEM", "has_usable_put_candidate"]) is True
    assert bool(frame.loc["NEM", "has_usable_call_candidate"]) is False
    assert frame.loc["AEM", "debt_to_mktcap"] == pytest.approx(0.20)
    assert frame.loc["AEM", "ebitda_to_mktcap"] == pytest.approx(0.50)
    assert frame.loc["AEM", "revenue_to_mktcap"] == pytest.approx(1.20)
    assert frame.loc["AEM", "netincome_to_mktcap"] == pytest.approx(0.30)


def test_candidate_finder_configured_source_fields_exist_in_joined_frame(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")

    data = load_candidate_finder_data(paths, app_config=app_config)
    missing = [
        criterion.source_field
        for criterion in app_config.candidate_finder.criteria
        if criterion.source_field not in data.frame.columns
    ]

    assert missing == []


def test_candidate_finder_data_handles_missing_sources(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app

    data = load_candidate_finder_data(paths, app_config=app_config)

    assert data.alignment.status == "UNKNOWN"
    assert not data.frame.empty
    assert "debt_to_mktcap" in data.frame.columns
    assert data.frame["debt_to_mktcap"].isna().all()
    assert data.frame["has_usable_put_candidate"].eq(False).all()
    assert data.frame["has_usable_call_candidate"].eq(False).all()


def test_candidate_finder_data_cache_notices_new_corrupt_latest_file(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    first = load_candidate_finder_data(paths, app_config=app_config)
    paths.latest_tool_a_snapshot_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_tool_a_snapshot_parquet_path.write_text("not parquet", encoding="utf-8")

    second = load_candidate_finder_data(paths, app_config=app_config)

    assert first.cache_key != second.cache_key
    assert any("Tool A latest parquet could not be read" in item for item in second.alignment.messages)


def test_candidate_finder_data_warns_when_latest_parquet_is_corrupt(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    paths.latest_tool_a_snapshot_parquet_path.write_text("not parquet", encoding="utf-8")

    data = load_candidate_finder_data(paths, app_config=app_config)
    screen = run_candidate_finder_screen(data, spec={"preset": "bearish_put"})

    assert data.alignment.status == "UNKNOWN"
    assert any("Tool A latest parquet could not be read" in item for item in screen.warnings)


def test_candidate_finder_screen_filters_peer_pool_before_ranking(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    data = load_candidate_finder_data(paths, app_config=app_config)

    screen = run_candidate_finder_screen(
        data,
        spec={
            "options_side": "calls",
            "criteria": [{"id": "up_beta", "weight": 1.0}],
            "top_n": 5,
        },
    )

    assert screen.options_side == "calls"
    assert screen.peer_frame["ticker"].tolist() == ["AEM"]
    assert [row.ticker for row in screen.ranking.rows] == ["AEM"]
    assert screen.ranking.rows[0].score == 100.0


def test_candidate_finder_screen_surfaces_invalid_spec_warnings(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    data = load_candidate_finder_data(paths, app_config=app_config)

    screen = run_candidate_finder_screen(
        data,
        spec={
            "preset": "missing",
            "options_side": "banana",
            "top_n": 0,
            "criteria": "down_beta",
        },
    )

    assert screen.options_side == "either"
    assert screen.top_n == app_config.candidate_finder.default_top_n
    assert "Unknown preset ignored: missing." in screen.warnings
    assert "Invalid options_side ignored: banana." in screen.warnings
    assert "Invalid top_n ignored: 0; using 10." in screen.warnings
    assert "Invalid criteria ignored: expected a list." in screen.warnings
    assert "Pick at least one criterion." in screen.warnings


def test_candidate_finder_data_warns_on_mixed_refreshes(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(
        paths,
        refresh_run_id="options-run",
        tool_a_refresh_run_id="tool-a-run",
        tool_b_refresh_run_id="tool-b-run",
    )

    data = load_candidate_finder_data(paths, app_config=app_config)

    assert data.alignment.status == "WARN"
    assert data.alignment.message is not None
    assert "Tool A" in data.alignment.message
    assert "Tool B" in data.alignment.message
    assert "Options" in data.alignment.message


def test_candidate_finder_data_warns_when_manual_store_is_newer_than_tool_b(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(
        paths,
        refresh_run_id="refresh-run",
        tool_b_source_run_id="20200101T000000Z-tool-b-old",
    )

    data = load_candidate_finder_data(paths, app_config=app_config)

    assert data.alignment.status == "WARN"
    assert any("Manual store was updated after" in item for item in data.alignment.messages)


def test_candidate_finder_cli_writes_ranked_parquet(tmp_path, capsys):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    spec_path = tmp_path / "screen.yaml"
    output_path = tmp_path / "candidate_finder.parquet"
    spec_path.write_text(
        """
options_side: puts
top_n: 5
criteria:
  - id: down_beta
    direction: high_good
    weight: 1
  - id: debt_to_mktcap
    direction: high_good
    weight: 1
""",
        encoding="utf-8",
    )

    exit_code = run_candidate_finder(
        paths,
        spec_path=str(spec_path),
        out_path=str(output_path),
    )
    captured = capsys.readouterr().out
    ranked = pd.read_parquet(output_path)

    assert exit_code == 0
    assert output_path.exists()
    assert "Candidate Finder ranked parquet written" in captured
    assert {"AEM", "NEM"}.issubset(set(ranked["ticker"]))
    assert "percentile_down_beta" in ranked.columns
    assert "percentile_debt_to_mktcap" in ranked.columns


def test_candidate_finder_cli_allows_output_outside_repo(tmp_path, capsys):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    spec_path = tmp_path / "screen.yaml"
    output_path = tmp_path.parent / "candidate_finder_external.parquet"
    spec_path.write_text("preset: bearish_put\noptions_side: puts\n", encoding="utf-8")

    exit_code = run_candidate_finder(
        paths,
        spec_path=str(spec_path),
        out_path=str(output_path),
    )
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert output_path.exists()
    assert str(output_path) in captured


def _write_candidate_finder_inputs(
    paths,
    *,
    refresh_run_id: str,
    tool_a_refresh_run_id: str | None = None,
    tool_b_refresh_run_id: str | None = None,
    tool_b_source_run_id: str | None = None,
) -> None:
    paths.ensure_runtime_dirs()
    tool_a_run = tool_a_refresh_run_id or refresh_run_id
    tool_b_run = tool_b_refresh_run_id or refresh_run_id
    paths.output_tool_a_dir.mkdir(parents=True, exist_ok=True)
    paths.output_tool_b_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "down_beta_core": 1.4,
                "up_beta_core": 1.2,
                "structural_delta_core": 1.3,
                "downside_volatility_52w": 0.35,
                "confidence_score": 0.9,
                "score_eligible": True,
                "snapshot_refresh_run_id": tool_a_run,
            },
            {
                "ticker": "NEM",
                "down_beta_core": 1.1,
                "up_beta_core": 0.9,
                "structural_delta_core": 1.0,
                "downside_volatility_52w": 0.25,
                "confidence_score": 0.8,
                "score_eligible": True,
                "snapshot_refresh_run_id": tool_a_run,
            },
        ]
    ).to_parquet(paths.latest_tool_a_snapshot_parquet_path, index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "market_cap_musd": 1000.0,
                "share_price_usd": 100.0,
                "forward_revenue_musd": 1200.0,
                "forward_ebitda_musd": 500.0,
                "forward_net_income_musd": 300.0,
                "forward_pe": 8.0,
                "ev_ebitda": 2.4,
                "fcf_yield": 0.18,
                "leverage": 0.4,
                "best_upside_pct": 0.30,
                "snapshot_refresh_run_id": tool_b_run,
                "source_run_id": tool_b_source_run_id,
            },
            {
                "ticker": "NEM",
                "market_cap_musd": 2000.0,
                "share_price_usd": 100.0,
                "forward_revenue_musd": 1600.0,
                "forward_ebitda_musd": 600.0,
                "forward_net_income_musd": 260.0,
                "forward_pe": 10.0,
                "ev_ebitda": 3.6,
                "fcf_yield": 0.12,
                "leverage": 0.2,
                "best_upside_pct": 0.20,
                "snapshot_refresh_run_id": tool_b_run,
                "source_run_id": tool_b_source_run_id,
            },
        ]
    ).to_parquet(paths.latest_tool_b_snapshot_parquet_path, index=False)
    bootstrap_manual_screening_data(paths, tickers=["AEM", "NEM"])
    upsert_company_input(paths, ticker="AEM", values={"net_debt_musd": 200.0, "aisc_usd_per_oz": 1700.0})
    upsert_company_input(paths, ticker="NEM", values={"net_debt_musd": 100.0, "aisc_usd_per_oz": 1500.0})
    _write_options(paths, refresh_run_id=refresh_run_id)


def _write_options(paths, *, refresh_run_id: str) -> None:
    snapshot_dir = paths.runs_dir / refresh_run_id / "snapshots" / "options"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_items = []
    for ticker, include_call in (("AEM", True), ("NEM", False)):
        snapshot_path = snapshot_dir / f"{safe_options_file_name(ticker)}.parquet"
        _chain(ticker, include_call=include_call).to_parquet(snapshot_path, index=False)
        snapshot_items.append(
            {
                "ticker": ticker,
                "options_available": True,
                "snapshot_path": snapshot_path.relative_to(paths.repo_root).as_posix(),
            }
        )
        feature = {
            "ticker": ticker,
            "run_id": refresh_run_id,
            "as_of_date": "2026-05-29",
            "optionability_tier": "directly_hedgeable",
            "iv_percentile_cross_sectional": 40.0 if ticker == "AEM" else 60.0,
            "iv_skew_60d": 0.05,
            "underlying_price": 100.0,
        }
        for horizon in (30, 60, 90):
            feature[f"put_iv_25d_{horizon}d"] = 0.4
            feature[f"call_iv_25d_{horizon}d"] = 0.4 if include_call else None
        paths.options_features_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([feature]).to_parquet(
            paths.options_features_dir / f"{safe_options_file_name(ticker)}.parquet",
            index=False,
        )
    paths.latest_options_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_options_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": refresh_run_id,
                "as_of_date": "2026-05-29",
                "risk_free_rate": 0.04,
                "snapshots": snapshot_items,
            }
        ),
        encoding="utf-8",
    )


def _chain(ticker: str, *, include_call: bool) -> pd.DataFrame:
    rows = [
        _option(ticker, "P", 95.0, 4.0, 4.4),
        _option(ticker, "P", 90.0, 2.0, 2.3),
    ]
    if include_call:
        rows.append(_option(ticker, "C", 105.0, 4.0, 4.4))
    return pd.DataFrame(rows)


def _option(ticker: str, option_type: str, strike: float, bid: float, ask: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "expiration": date(2026, 7, 17).isoformat(),
        "option_type": option_type,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2,
        "last_price": (bid + ask) / 2,
        "open_interest": 100,
        "volume": 20,
        "implied_volatility": 0.40,
        "underlying_price": 100.0,
        "days_to_expiry": 49,
        "options_available": True,
    }
