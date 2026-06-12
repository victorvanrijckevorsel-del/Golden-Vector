import json

import pandas as pd

from golden_vector.contracts.config_models import HedgeReadinessConfig
from golden_vector.hedge.header_context import build_header_context
from tests.helpers import build_test_paths


def test_build_header_context_reads_manifest_histories_and_price_moves(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_manifest_and_histories(paths)
    features = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "optionability_tier": "directly_hedgeable",
                "implied_move_90d": 0.08,
            }
        ]
    )
    tool_a = pd.DataFrame([{"ticker": "AEM", "down_beta_core": 1.40}])

    context = build_header_context(
        paths=paths,
        options_features=features,
        tool_a_frame=tool_a,
    )

    assert context.data_notes == []
    assert context.gold.price == 122.0
    assert context.gold.change_1d == 122.0 / 121.0 - 1.0
    assert context.gold.change_1w == 122.0 / 117.0 - 1.0
    assert context.gdx.price == 61.0
    assert context.gdx.change_1m == 61.0 / 40.0 - 1.0
    assert context.implied_vs_modeled_rows[0].verdict == "model > market (heuristic)"


def test_build_header_context_handles_missing_manifest_and_histories(tmp_path):
    paths = build_test_paths(tmp_path)

    context = build_header_context(
        paths=paths,
        options_features=pd.DataFrame(),
        tool_a_frame=pd.DataFrame(),
    )

    assert context.gold.price is None
    assert context.gdx.price is None
    assert context.implied_vs_modeled_rows == []
    assert "latest options manifest unavailable" in context.data_notes
    assert any("refresh_run_id is missing" in note for note in context.data_notes)
    assert any("benchmark_snapshot_paths has no GDX" in note for note in context.data_notes)


def test_build_header_context_handles_malformed_manifest(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.latest_options_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_options_manifest_path.write_text("[]", encoding="utf-8")

    context = build_header_context(
        paths=paths,
        options_features=pd.DataFrame(),
        tool_a_frame=pd.DataFrame(),
    )

    assert "latest options manifest unreadable: expected a JSON object" in context.data_notes
    assert context.gold.price is None
    assert context.gdx.price is None


def test_build_header_context_handles_corrupt_history_file(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_manifest_and_histories(paths)
    gdx_path = paths.runs_dir / "refresh-run" / "snapshots" / "benchmarks" / "GDX.parquet"
    gdx_path.write_text("not a parquet file", encoding="utf-8")

    context = build_header_context(
        paths=paths,
        options_features=pd.DataFrame(),
        tool_a_frame=pd.DataFrame(),
    )

    assert context.gold.price == 122.0
    assert context.gdx.price is None
    assert any("GDX history unreadable" in note for note in context.data_notes)


def test_build_header_context_handles_missing_implied_move_for_some_tickers(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_manifest_and_histories(paths)
    features = pd.DataFrame(
        [
            {"ticker": "AEM", "optionability_tier": "directly_hedgeable"},
            {
                "ticker": "NEM",
                "optionability_tier": "thin",
                "implied_move_90d": 0.20,
            },
            {"ticker": "AAUC.TO", "optionability_tier": "none", "implied_move_90d": 0.10},
        ]
    )
    tool_a = pd.DataFrame(
        [
            {"ticker": "AEM", "down_beta_core": 1.40},
            {"ticker": "NEM", "down_beta_core": 1.00},
        ]
    )

    context = build_header_context(
        paths=paths,
        options_features=features,
        tool_a_frame=tool_a,
    )

    assert [row.ticker for row in context.implied_vs_modeled_rows] == ["AEM", "NEM"]
    assert context.implied_vs_modeled_rows[0].verdict == "data unavailable (heuristic)"
    assert context.implied_vs_modeled_rows[1].verdict == "market > model (heuristic)"


def test_build_header_context_treats_negative_down_beta_as_zero_modeled_downside(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_manifest_and_histories(paths)
    features = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "optionability_tier": "directly_hedgeable",
                "implied_move_90d": 0.10,
            }
        ]
    )
    tool_a = pd.DataFrame([{"ticker": "AEM", "down_beta_core": -1.00}])

    context = build_header_context(
        paths=paths,
        options_features=features,
        tool_a_frame=tool_a,
    )

    row = context.implied_vs_modeled_rows[0]
    assert row.modeled_downside_at_minus10 == 0.0
    assert row.verdict == "market > model (heuristic)"


def test_build_header_context_clamps_extreme_modeled_downside_at_zero_stock_price(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_manifest_and_histories(paths)
    features = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "optionability_tier": "directly_hedgeable",
                "implied_move_90d": 0.80,
            }
        ]
    )
    tool_a = pd.DataFrame([{"ticker": "AEM", "down_beta_core": 15.00}])

    context = build_header_context(
        paths=paths,
        options_features=features,
        tool_a_frame=tool_a,
    )

    row = context.implied_vs_modeled_rows[0]
    assert row.modeled_downside_at_minus10 == 1.0
    assert row.verdict == "model ~= market (heuristic)"


def test_build_header_context_accepts_feature_frames_by_ticker(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_manifest_and_histories(paths)
    features = {
        "AEM": pd.DataFrame(
            [
                {
                    "optionability_tier": "directly_hedgeable",
                    "implied_move_90d": 0.14,
                }
            ]
        )
    }
    tool_a = pd.DataFrame([{"ticker": "AEM", "down_beta_core": 1.40}])

    context = build_header_context(
        paths=paths,
        options_features=features,
        tool_a_frame=tool_a,
    )

    assert context.implied_vs_modeled_rows[0].ticker == "AEM"
    assert context.implied_vs_modeled_rows[0].verdict == "model ~= market (heuristic)"


def test_implied_vs_modeled_verdict_boundaries_are_inclusive_to_middle_band(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_manifest_and_histories(paths)
    features = pd.DataFrame(
        [
            {
                "ticker": "HIGH",
                "optionability_tier": "directly_hedgeable",
                "implied_move_90d": 0.10,
            },
            {
                "ticker": "LOW",
                "optionability_tier": "directly_hedgeable",
                "implied_move_90d": 0.10,
            },
        ]
    )
    tool_a = pd.DataFrame(
        [
            {"ticker": "HIGH", "down_beta_core": 1.50},
            {"ticker": "LOW", "down_beta_core": 0.67},
        ]
    )

    context = build_header_context(
        paths=paths,
        options_features=features,
        tool_a_frame=tool_a,
    )

    assert [row.verdict for row in context.implied_vs_modeled_rows] == [
        "model ~= market (heuristic)",
        "model ~= market (heuristic)",
    ]


def test_implied_vs_modeled_verdict_uses_configured_thresholds(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_manifest_and_histories(paths)
    features = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "optionability_tier": "directly_hedgeable",
                "implied_move_90d": 0.10,
            }
        ]
    )
    tool_a = pd.DataFrame([{"ticker": "AEM", "down_beta_core": 1.40}])

    default_context = build_header_context(
        paths=paths,
        options_features=features,
        tool_a_frame=tool_a,
    )
    stricter_context = build_header_context(
        paths=paths,
        options_features=features,
        tool_a_frame=tool_a,
        hedge_config=HedgeReadinessConfig(option_verdict_model_over_market_ratio=1.3),
    )

    assert default_context.implied_vs_modeled_rows[0].verdict == "model ~= market (heuristic)"
    assert stricter_context.implied_vs_modeled_rows[0].verdict == "model > market (heuristic)"


def _write_manifest_and_histories(paths) -> None:
    run_id = "refresh-run"
    gold_path = paths.runs_dir / run_id / "snapshots" / "raw_gold.parquet"
    gdx_path = paths.runs_dir / run_id / "snapshots" / "benchmarks" / "GDX.parquet"
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    gdx_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "date": pd.date_range("2026-04-01", periods=22, freq="D"),
            "adj_close_usd": [101.0 + index for index in range(22)],
        }
    ).to_parquet(gold_path, index=False)
    pd.DataFrame(
        {
            "date": pd.date_range("2026-04-01", periods=22, freq="D"),
            "adj_close_local": [40.0 + index for index in range(22)],
        }
    ).to_parquet(gdx_path, index=False)
    paths.latest_options_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_options_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": run_id,
                "benchmark_snapshot_paths": [
                    gdx_path.relative_to(paths.repo_root).as_posix(),
                ],
            }
        ),
        encoding="utf-8",
    )
