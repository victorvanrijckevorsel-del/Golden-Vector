"""M1a contract tests: ticker-page config surface, schemas, and reader stubs."""

from __future__ import annotations

import json
import shutil

import pandas as pd
import pytest
from pydantic import ValidationError

from golden_vector.app.config import EXPECTED_CONFIG_FILES, load_app_config
from golden_vector.app.model_state import write_current_model_state_manifest
from golden_vector.app.ticker_page_state import (
    STATUS_CORRUPT,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_PENDING_FIRST_PUBLISH,
    load_gold_response,
    load_performance_series,
    load_research_series,
    load_score_percentiles,
)
from golden_vector.common.files import sha256_file
from golden_vector.contracts.config_models import (
    TICKER_PAGE_SCORE_BUDGET_POINTS,
    TickerPageConfig,
)
from golden_vector.contracts.ticker_page import (
    GOLD_RESPONSE_COLUMNS,
    GOLD_RESPONSE_KEY_COLUMNS,
    PERCENTILES_COLUMNS,
    PERCENTILES_KEY_COLUMNS,
    PERFORMANCE_COLUMNS,
    PERFORMANCE_KEY_COLUMNS,
    RESEARCH_SERIES_COLUMNS,
    TICKER_PAGE_SCHEMA_VERSIONS,
    validate_frame_schema,
)
from tests.helpers import build_test_paths


def _metric(**overrides) -> dict[str, object]:
    metric = {
        "key": "margin_pct",
        "label": "Cash margin",
        "category": "corporate",
        "source_tool": "tool_b",
        "source_column": "margin_pct",
        "default_high_good": True,
        "unit": "percent",
        "basis": "fwd @ spot",
    }
    metric.update(overrides)
    return metric


def _score_builder(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "budget_points": 100,
        "min_eligible_peers": 10,
        "min_active_metric_coverage": 0.6,
        "rank_stability_shift_points": 10,
        "rank_stability_alert_positions": 3,
        "metrics": [
            _metric(),
            _metric(
                key="up_beta_core",
                label="Up beta",
                category="trading",
                source_tool="tool_a",
                source_column="up_beta_core",
                unit="ratio",
                basis="structural cross-window",
            ),
        ],
    }
    payload.update(overrides)
    return payload


def _config_payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": 1,
        "dial": {
            "min_gold_usd": 2000,
            "max_gold_usd": 6000,
            "step_usd": 1,
            "probe_gold_usd": [2000, 4000, 6000],
            "linearity_abs_tol_musd": 0.5,
            "linearity_abs_tol_eps": 0.005,
            "linearity_rel_tol": 0.001,
            "systemic_min_tickers": 5,
        },
        "chart": {"horizons": ["1Y", "3Y", "5Y"], "benchmark_max_staleness_days": 5},
        "lab": {"default_horizon_weeks": 8, "scatter_from_year": 2016},
        "score_builder": _score_builder(),
        "sizing": {"max_contracts": 10000},
    }
    payload.update(overrides)
    return payload


# --- (a) the real config file loads through the real loader ----------------


def test_ticker_page_yaml_is_required_and_loads(tmp_path) -> None:
    assert ("ticker_page", "ticker_page.yaml") in EXPECTED_CONFIG_FILES
    paths = build_test_paths(tmp_path / "repo")
    config = load_app_config(paths).app.ticker_page

    assert len(config.score_builder.metrics) == 19
    keys = [metric.key for metric in config.score_builder.metrics]
    assert len(set(keys)) == 19
    assert {metric.category for metric in config.score_builder.metrics} == {
        "trading",
        "corporate",
    }
    assert config.dial.min_gold_usd == 2000.0
    assert config.dial.max_gold_usd == 6000.0
    assert config.chart.horizons == ["1Y", "3Y", "5Y"]
    assert config.lab.default_horizon_weeks == 8
    assert config.score_builder.budget_points == TICKER_PAGE_SCORE_BUDGET_POINTS
    assert config.sizing.max_contracts == 10000


def test_real_hedge_readiness_history_quality_block(tmp_path) -> None:
    paths = build_test_paths(tmp_path / "repo")
    quality = load_app_config(paths).app.hedge_readiness.history_quality
    assert quality.partial_capture_min_ratio == pytest.approx(0.70)
    assert quality.iv_valid_range == [0.01, 3.0]
    assert quality.skew_valid_range == [-1.0, 1.0]
    assert quality.implied_move_valid_range == [0.0, 1.0]
    assert quality.expiry_floor_ratio == pytest.approx(0.5)
    assert quality.trailing_median_days == 20
    assert quality.coverage_floor_ratio == pytest.approx(0.5)


def test_healthy_control_payload_validates() -> None:
    assert TickerPageConfig.model_validate(_config_payload()).sizing.max_contracts == 10000


# --- (b) validators reject bad config --------------------------------------


@pytest.mark.parametrize(
    "payload, expected",
    [
        pytest.param(
            _config_payload(score_builder=_score_builder(budget_points=90)),
            "product-locked",
            id="budget_not_100",
        ),
        pytest.param(
            _config_payload(
                score_builder=_score_builder(
                    metrics=[_metric(category="fundamentals"), _metric(key="x")]
                )
            ),
            "category must be one of",
            id="unknown_category",
        ),
        pytest.param(
            _config_payload(
                score_builder=_score_builder(
                    metrics=[
                        _metric(),
                        _metric(),
                        _metric(key="up_beta_core", category="trading", source_tool="tool_a"),
                    ]
                )
            ),
            "Duplicate ticker_page score metric key",
            id="duplicate_metric_keys",
        ),
        pytest.param(
            _config_payload(
                dial={
                    "min_gold_usd": 2000,
                    "max_gold_usd": 6000,
                    "step_usd": 1,
                    "probe_gold_usd": [2000, 9000],
                    "linearity_abs_tol_musd": 0.5,
                    "linearity_abs_tol_eps": 0.005,
                    "linearity_rel_tol": 0.001,
                    "systemic_min_tickers": 5,
                }
            ),
            "must lie within",
            id="probe_outside_range",
        ),
        pytest.param(
            _config_payload(
                dial={
                    "min_gold_usd": 6000,
                    "max_gold_usd": 2000,
                    "step_usd": 1,
                    "probe_gold_usd": [3000],
                    "linearity_abs_tol_musd": 0.5,
                    "linearity_abs_tol_eps": 0.005,
                    "linearity_rel_tol": 0.001,
                    "systemic_min_tickers": 5,
                }
            ),
            "must be below max_gold_usd",
            id="min_above_max",
        ),
        pytest.param(
            _config_payload(chart={"horizons": ["2Y"], "benchmark_max_staleness_days": 5}),
            "must be a subset",
            id="unknown_chart_horizon",
        ),
        pytest.param(
            _config_payload(lab={"default_horizon_weeks": 7, "scatter_from_year": 2016}),
            "default_horizon_weeks must be one of",
            id="unknown_lab_horizon",
        ),
        pytest.param(
            _config_payload(
                score_builder=_score_builder(min_active_metric_coverage=1.5)
            ),
            "min_active_metric_coverage",
            id="coverage_above_one",
        ),
        pytest.param(
            _config_payload(sizing={"max_contracts": 0}),
            "max_contracts must be at least 1",
            id="zero_max_contracts",
        ),
        pytest.param(
            _config_payload(
                score_builder=_score_builder(
                    metrics=[
                        _metric(),
                        _metric(key="odd", source_tool="tool_a", category="trading", unit="furlongs"),
                    ]
                )
            ),
            "unit must be one of",
            id="unknown_unit",
        ),
    ],
)
def test_invalid_config_is_rejected(payload, expected) -> None:
    with pytest.raises(ValidationError) as error:
        TickerPageConfig.model_validate(payload)
    assert expected in str(error.value)


# --- (c) validate_frame_schema ---------------------------------------------


def _percentile_row(ticker: str = "AEM", metric_key: str = "margin_pct") -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(PERCENTILES_COLUMNS, None)
    row.update(
        {
            "ticker": ticker,
            "finance_source": "our",
            "metric_key": metric_key,
            "category": "corporate",
            "raw_value": 0.4,
            "unit": "percent",
            "basis": "fwd @ spot",
            "source_tool": "tool_b",
            "source_as_of_date": "2026-08-10",
            "metric_available": True,
            "rank_eligible": True,
            "eligible_peer_count": 30,
            "schema_version": TICKER_PAGE_SCHEMA_VERSIONS["percentiles"],
            "source_run_id": "run-1",
            "snapshot_refresh_run_id": "refresh-1",
            "parent_refresh_id": "refresh-1",
            "config_hash": "abc",
        }
    )
    return row


def test_validate_frame_schema_accepts_healthy_control() -> None:
    frame = pd.DataFrame([_percentile_row(), _percentile_row(metric_key="fcf_yield")])
    assert (
        validate_frame_schema(
            frame, columns=PERCENTILES_COLUMNS, key_columns=PERCENTILES_KEY_COLUMNS
        )
        == []
    )


def test_validate_frame_schema_catches_missing_column() -> None:
    frame = pd.DataFrame([_percentile_row()]).drop(columns=["raw_value"])
    violations = validate_frame_schema(
        frame, columns=PERCENTILES_COLUMNS, key_columns=PERCENTILES_KEY_COLUMNS
    )
    assert any("missing columns: raw_value" in message for message in violations)


def test_validate_frame_schema_catches_null_key() -> None:
    bad = _percentile_row()
    bad["metric_key"] = None
    frame = pd.DataFrame([_percentile_row(metric_key="fcf_yield"), bad])
    violations = validate_frame_schema(
        frame, columns=PERCENTILES_COLUMNS, key_columns=PERCENTILES_KEY_COLUMNS
    )
    assert any("null values in key column metric_key" in message for message in violations)


def test_validate_frame_schema_catches_duplicate_key() -> None:
    frame = pd.DataFrame([_percentile_row(), _percentile_row()])
    violations = validate_frame_schema(
        frame, columns=PERCENTILES_COLUMNS, key_columns=PERCENTILES_KEY_COLUMNS
    )
    assert any("duplicate keys" in message for message in violations)


# --- (d) loader stubs -------------------------------------------------------


def _row(columns, **values) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(columns, None)
    row.update(values)
    return row


LOADERS = {
    "gold_response": (
        load_gold_response,
        "latest_ticker_page_gold_response_path",
        GOLD_RESPONSE_COLUMNS,
        {"ticker": "AEM", "finance_source": "our"},
        "ticker",
    ),
    "percentiles": (
        load_score_percentiles,
        "latest_ticker_page_percentiles_path",
        PERCENTILES_COLUMNS,
        {"ticker": "AEM", "finance_source": "our", "metric_key": "margin_pct"},
        "metric_key",
    ),
    "performance": (
        load_performance_series,
        "latest_ticker_page_performance_path",
        PERFORMANCE_COLUMNS,
        {
            "ticker": "AEM",
            "series": "stock",
            "view": "rebased",
            "horizon": "1Y",
            "date": "2026-08-10",
        },
        "horizon",
    ),
    "research_series": (
        load_research_series,
        "latest_ticker_page_research_series_path",
        RESEARCH_SERIES_COLUMNS,
        {"ticker": "AEM", "kind": "weekly", "date": "2026-08-10"},
        "kind",
    ),
}


@pytest.mark.parametrize("name", sorted(LOADERS))
def test_loader_reports_missing_on_empty_tree(tmp_path, name) -> None:
    loader = LOADERS[name][0]
    paths = build_test_paths(tmp_path / f"repo_{name}")
    state = loader(paths)
    assert state.status == STATUS_MISSING
    assert state.reason and name in state.reason
    assert state.frame.empty


FOUNDATION_RUN_ID = "20260601T120000Z-refresh"


def _identity(**values) -> dict[str, object]:
    """Provenance every published artifact row carries (kept aligned with the
    foundation manifest below so the manifest never flags the row as stale)."""

    return {
        # Every artifact is at schema_version 1; the loader rejects a row that
        # cannot prove which version wrote it.
        "schema_version": 1,
        "source_run_id": FOUNDATION_RUN_ID,
        "snapshot_refresh_run_id": FOUNDATION_RUN_ID,
        "parent_refresh_id": FOUNDATION_RUN_ID,
        **values,
    }


def _write_foundation_manifest(paths) -> None:
    paths.latest_foundation_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_foundation_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": FOUNDATION_RUN_ID,
                "foundation_status": "PASS",
                "snapshot_as_of_date": "2026-08-10",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _publish(paths, name: str, path_attr: str, frame: pd.DataFrame) -> None:
    """Write ``frame`` as a run-stamped immutable + its alias and publish a
    model-state manifest naming it, so the manifest-first loaders resolve it.

    Mirrors ``test_ticker_page_stage.py`` -- the alias alone is never the
    loading authority.
    """

    paths.output_ticker_page_dir.mkdir(parents=True, exist_ok=True)
    immutable = paths.output_ticker_page_dir / f"{name}_latest_{FOUNDATION_RUN_ID}.parquet"
    frame.to_parquet(immutable, index=False)
    alias = getattr(paths, path_attr)
    alias.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(immutable, alias)
    _write_foundation_manifest(paths)
    write_current_model_state_manifest(
        paths=paths,
        config_hash="abc",
        parent_refresh_id=FOUNDATION_RUN_ID,
        stage_timings={},
    )


@pytest.mark.parametrize("name", sorted(LOADERS))
def test_loader_reports_pending_first_publish_on_an_alias_no_manifest_names(
    tmp_path, name
) -> None:
    """A standalone build writes the alias but no refresh published it: the
    loader must say PENDING_FIRST_PUBLISH, never OK."""

    loader, path_attr, columns, keys, _ = LOADERS[name]
    paths = build_test_paths(tmp_path / f"repo_{name}")
    path = getattr(paths, path_attr)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([_row(columns, **_identity(**keys))]).to_parquet(path)

    state = loader(paths)
    assert state.status == STATUS_PENDING_FIRST_PUBLISH, state.reason
    assert "awaiting first refresh publication" in (state.reason or "")
    assert state.frame.empty


@pytest.mark.parametrize("name", sorted(LOADERS))
def test_loader_reports_ok_on_healthy_frame(tmp_path, name) -> None:
    loader, path_attr, columns, keys, _ = LOADERS[name]
    paths = build_test_paths(tmp_path / f"repo_{name}")
    _publish(paths, name, path_attr, pd.DataFrame([_row(columns, **_identity(**keys))]))

    state = loader(paths)
    assert state.status == STATUS_OK, state.reason
    assert state.reason is None
    assert len(state.frame) == 1


@pytest.mark.parametrize("name", sorted(LOADERS))
def test_loader_reports_corrupt_when_key_column_missing(tmp_path, name) -> None:
    loader, path_attr, columns, keys, dropped_key = LOADERS[name]
    paths = build_test_paths(tmp_path / f"repo_{name}")
    frame = pd.DataFrame([_row(columns, **_identity(**keys))]).drop(columns=[dropped_key])
    _publish(paths, name, path_attr, frame)

    # The manifest resolves the artifact; schema validation is what fails.
    state = loader(paths)
    assert state.status == STATUS_CORRUPT, state.reason
    assert state.reason and dropped_key in state.reason
    assert state.frame.empty


def test_loader_reports_corrupt_on_unreadable_file(tmp_path) -> None:
    """A manifest-vouched file that is not readable parquet is CORRUPT (not
    STALE): the sha still matches, so only the content is bad."""

    loader, path_attr, columns, keys, _ = LOADERS["gold_response"]
    paths = build_test_paths(tmp_path / "repo_corrupt")
    _publish(
        paths, "gold_response", path_attr, pd.DataFrame([_row(columns, **_identity(**keys))])
    )
    assert loader(paths).status == STATUS_OK  # healthy control before corruption

    manifest_path = paths.latest_model_state_manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["artifacts"]["ticker_page_gold_response"]
    immutable = paths.resolve_repo_relative(entry["path"])
    immutable.write_bytes(b"not a parquet file")
    entry["sha256"] = sha256_file(immutable)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    state = load_gold_response(paths)
    assert state.status == STATUS_CORRUPT, state.reason
    assert state.frame.empty


def test_gold_response_columns_cover_every_line_metric() -> None:
    for metric in (
        "forward_revenue_musd",
        "forward_ebitda_musd",
        "forward_net_income_musd",
        "forward_eps",
        "sustainable_fcf_musd",
    ):
        assert f"line_slope_{metric}" in GOLD_RESPONSE_COLUMNS
        assert f"line_intercept_{metric}" in GOLD_RESPONSE_COLUMNS
    assert GOLD_RESPONSE_KEY_COLUMNS == ("ticker", "finance_source")
    assert PERFORMANCE_KEY_COLUMNS[0] == "ticker"


# --- (e) P5 catalog regressions --------------------------------------------


def test_asymmetry_is_higher_good_and_banned_metrics_absent(tmp_path) -> None:
    paths = build_test_paths(tmp_path / "repo_catalog")
    metrics = {
        metric.key: metric
        for metric in load_app_config(paths).app.ticker_page.score_builder.metrics
    }
    assert metrics["asymmetry_ratio_core"].default_high_good is True
    assert "confidence_score" not in metrics
    assert "cost_curve_aisc_percentile" not in metrics
    assert not any("cost_curve" in key for key in metrics)
    assert not any("confidence" in key for key in metrics)


# --- (e) dtype map + margin basis -------------------------------------------


def test_every_contract_column_declares_an_expected_dtype():
    """An undeclared column silently falls back to object on an empty build."""

    from golden_vector.contracts.ticker_page import ARTIFACT_COLUMNS, EXPECTED_DTYPES

    assert set(EXPECTED_DTYPES) == set(ARTIFACT_COLUMNS)
    for artifact, columns in ARTIFACT_COLUMNS.items():
        undeclared = [c for c in columns if c not in EXPECTED_DTYPES[artifact]]
        assert not undeclared, (artifact, undeclared)
        extra = [c for c in EXPECTED_DTYPES[artifact] if c not in columns]
        assert not extra, (artifact, extra)


def test_empty_artifact_frames_are_schema_typed_not_object():
    from golden_vector.contracts.ticker_page import (
        ARTIFACT_COLUMNS,
        EXPECTED_DTYPES,
        empty_artifact_frame,
    )

    for artifact, columns in ARTIFACT_COLUMNS.items():
        frame = empty_artifact_frame(artifact)
        assert frame.empty
        assert list(frame.columns) == list(columns)
        for column in columns:
            assert str(frame[column].dtype) == EXPECTED_DTYPES[artifact][column], (
                artifact,
                column,
            )


def test_gold_response_carries_a_machine_readable_margin_basis():
    """The pack ships BOTH aisc and cash_cost, so 'margin' must name its basis."""

    from golden_vector.contracts.ticker_page import (
        GOLD_RESPONSE_COLUMNS,
        GOLD_RESPONSE_MARGIN_BASES,
    )

    assert "spot_margin_basis" in GOLD_RESPONSE_COLUMNS
    assert "aisc_usd_per_oz" in GOLD_RESPONSE_COLUMNS
    assert "cash_cost_usd_per_oz" in GOLD_RESPONSE_COLUMNS
    assert "aisc" in GOLD_RESPONSE_MARGIN_BASES
