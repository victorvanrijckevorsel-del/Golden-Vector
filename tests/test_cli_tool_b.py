from dataclasses import dataclass
from datetime import date

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.latest_data import LatestFoundationSnapshot
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import run_refresh, run_tool_b
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from tests.helpers import build_test_paths


@dataclass(frozen=True)
class _LoadedConfigStub:
    app: object
    config_hash: str


def _gold_history() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "2026-06-06", "close_usd": 4200.0},
            {"date": "2026-06-09", "close_usd": 4321.5},
        ]
    )


def _latest_foundation_snapshot(
    *,
    raw_status: str = "PASS",
    normalization_status: str = "PASS",
    gold_history: pd.DataFrame | None = None,
) -> LatestFoundationSnapshot:
    return LatestFoundationSnapshot(
        refresh_run_id="refresh-run",
        snapshot_as_of_date="2026-02-01",
        foundation_status=normalization_status,
        raw_qa_summary={"overall_status": raw_status},
        normalization_qa_summary={"overall_status": normalization_status},
        summary={"foundation_marker": True},
        gold_history=gold_history if gold_history is not None else pd.DataFrame(),
        normalized_equity_histories={},
        normalized_market_snapshots=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "snapshot_date": date(2026, 2, 1),
                    "share_price_usd": 60.0,
                    "market_cap_usd": 48_000_000_000.0,
                    "shares_outstanding": 800_000_000.0,
                    "normalization_status": "OK",
                }
            ]
        ),
        manifest_path=ProjectPaths.discover().repo_root / "data" / "intermediate" / "status" / "latest_foundation_manifest.json",
    )


def test_run_tool_b_stops_when_local_snapshot_is_missing(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: (_ for _ in ()).throw(FileNotFoundError("missing local snapshot")),
    )

    called = {"tool_b": False}

    def _unexpected_tool_b(**kwargs):
        called["tool_b"] = True
        raise AssertionError("Tool B pipeline should not run when local snapshot loading fails.")

    monkeypatch.setattr("golden_vector.cli.execute_tool_b_pipeline", _unexpected_tool_b)

    exit_code = run_tool_b(paths, gold_price=4000)

    assert exit_code == 1
    assert called["tool_b"] is False


def test_run_tool_b_uses_latest_local_snapshot(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: _latest_foundation_snapshot(),
    )

    called = {"tool_b": False}

    def _tool_b_result(**kwargs):
        called["tool_b"] = True
        assert len(kwargs["normalized_market_snapshots"].index) == 1
        return type(
            "ToolBResultStub",
            (),
            {
                "tool_b_outputs": pd.DataFrame(
                    [
                        {
                            "ticker": "NEM",
                            "as_of_date": date(2026, 2, 1),
                            "gold_price_assumption": 4000.0,
                            "fundamental_check_score": 85.7143,
                        }
                    ]
                ),
                "overall_status": "PASS",
                "summary": {"tool_b_output_row_count": 1, "tool_b_output_overall_status": "PASS"},
            },
        )()

    monkeypatch.setattr("golden_vector.cli.execute_tool_b_pipeline", _tool_b_result)

    exit_code = run_tool_b(paths, gold_price=4000)

    assert exit_code == 0
    assert called["tool_b"] is True


def test_run_tool_b_completes_when_backbone_and_screening_succeed(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: _latest_foundation_snapshot(),
    )
    monkeypatch.setattr(
        "golden_vector.cli.execute_tool_b_pipeline",
        lambda **_: type(
            "ToolBResultStub",
            (),
            {
                "tool_b_outputs": pd.DataFrame(
                    [
                        {
                            "ticker": "NEM",
                            "as_of_date": date(2026, 2, 1),
                            "gold_price_assumption": 4000.0,
                            "fundamental_check_score": 85.7143,
                        }
                    ]
                ),
                "overall_status": "PASS",
                "summary": {"tool_b_output_row_count": 1, "tool_b_output_overall_status": "PASS"},
            },
        )(),
    )

    exit_code = run_tool_b(paths, gold_price=4000)

    assert exit_code == 0


def test_run_tool_b_fails_when_manual_store_is_missing(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )

    called = {"snapshot": False, "tool_b": False}

    def _unexpected_snapshot(**kwargs):
        called["snapshot"] = True
        raise AssertionError("Tool B should fail before loading the market snapshot when the manual store is missing.")

    def _unexpected_tool_b(**kwargs):
        called["tool_b"] = True
        raise AssertionError("Tool B pipeline should not run when the manual store is missing.")

    monkeypatch.setattr("golden_vector.cli.load_latest_foundation_snapshot", _unexpected_snapshot)
    monkeypatch.setattr("golden_vector.cli.execute_tool_b_pipeline", _unexpected_tool_b)

    exit_code = run_tool_b(paths, gold_price=4000)

    assert exit_code == 1
    assert called == {"snapshot": False, "tool_b": False}


def _tool_b_result_stub() -> object:
    return type(
        "ToolBResultStub",
        (),
        {
            "tool_b_outputs": pd.DataFrame(
                [
                    {
                        "ticker": "NEM",
                        "as_of_date": date(2026, 6, 9),
                        "gold_price_assumption": 4321.5,
                        "fundamental_check_score": 85.7143,
                    }
                ]
            ),
            "overall_status": "PASS",
            "summary": {"tool_b_output_row_count": 1, "tool_b_output_overall_status": "PASS"},
        },
    )()


def test_run_tool_b_defaults_to_latest_gold_close(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: _latest_foundation_snapshot(gold_history=_gold_history()),
    )

    captured: dict[str, object] = {}

    def _capture_tool_b(**kwargs):
        captured.update(kwargs)
        return _tool_b_result_stub()

    monkeypatch.setattr("golden_vector.cli.execute_tool_b_pipeline", _capture_tool_b)

    exit_code = run_tool_b(paths, gold_price=None)

    assert exit_code == 0
    assert captured["gold_price_assumption"] == pytest.approx(4321.5)
    assert captured["spot_gold_usd"] == pytest.approx(4321.5)
    assert captured["spot_gold_date"] == "2026-06-09"
    assert captured["gold_price_basis"] == "latest_daily_gold_close"
    assert captured["publish_latest_aliases"] is True


def test_run_tool_b_fails_closed_before_persistence_when_spot_gold_missing(
    tmp_path, monkeypatch
):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: _latest_foundation_snapshot(gold_history=pd.DataFrame()),
    )

    called = {"tool_b": False}

    def _unexpected_tool_b(**kwargs):
        called["tool_b"] = True
        raise AssertionError(
            "Tool B must not persist anything when spot gold is unavailable "
            "and no explicit gold price was given."
        )

    monkeypatch.setattr("golden_vector.cli.execute_tool_b_pipeline", _unexpected_tool_b)

    exit_code = run_tool_b(paths, gold_price=None)

    assert exit_code == 1
    assert called["tool_b"] is False


def test_run_tool_b_custom_gold_price_is_isolated_scenario_run(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: _latest_foundation_snapshot(gold_history=_gold_history()),
    )

    captured: dict[str, object] = {}

    def _capture_tool_b(**kwargs):
        captured.update(kwargs)
        return _tool_b_result_stub()

    monkeypatch.setattr("golden_vector.cli.execute_tool_b_pipeline", _capture_tool_b)

    exit_code = run_tool_b(paths, gold_price=3000)

    assert exit_code == 0
    assert captured["gold_price_assumption"] == pytest.approx(3000.0)
    assert captured["gold_price_basis"] == "custom_scenario"
    # Scenario runs never publish the latest alias the workspace consumes.
    assert captured["publish_latest_aliases"] is False
    # Spot provenance still stamped so the delta-vs-spot is auditable.
    assert captured["spot_gold_usd"] == pytest.approx(4321.5)
    assert captured["spot_gold_date"] == "2026-06-09"


def test_run_refresh_refuses_gold_price_override(tmp_path, capsys):
    paths = build_test_paths(tmp_path)

    exit_code = run_refresh(paths, gold_price_override=3000.0, skip_tool_b=False)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "latest daily gold close" in captured.out
    assert "tool-b --gold-price" in captured.out
