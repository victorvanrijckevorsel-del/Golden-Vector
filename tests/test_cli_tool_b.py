from dataclasses import dataclass
from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.latest_data import LatestFoundationSnapshot
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import run_tool_b
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from tests.helpers import build_test_paths


@dataclass(frozen=True)
class _LoadedConfigStub:
    app: object
    combined_hash: str


def _latest_foundation_snapshot(*, raw_status: str = "PASS", normalization_status: str = "PASS") -> LatestFoundationSnapshot:
    return LatestFoundationSnapshot(
        refresh_run_id="refresh-run",
        snapshot_as_of_date="2026-02-01",
        foundation_status=normalization_status,
        raw_qa_summary={"overall_status": raw_status},
        normalization_qa_summary={"overall_status": normalization_status},
        summary={"foundation_marker": True},
        gold_history=pd.DataFrame(),
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
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
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
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
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
                            "tool_b_score": 82.0,
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
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
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
                            "tool_b_score": 82.0,
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
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
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
