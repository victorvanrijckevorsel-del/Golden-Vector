from dataclasses import dataclass

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.latest_data import LatestFoundationSnapshot
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import _combine_statuses, run_tool_a
from tests.helpers import build_test_paths


@dataclass(frozen=True)
class _LoadedConfigStub:
    app: object
    config_hash: str


def _latest_foundation_snapshot(
    *,
    raw_status: str = "PASS",
    normalization_status: str = "PASS",
) -> LatestFoundationSnapshot:
    return LatestFoundationSnapshot(
        refresh_run_id="refresh-run",
        snapshot_as_of_date="2026-01-01",
        foundation_status=normalization_status,
        raw_qa_summary={"overall_status": raw_status},
        normalization_qa_summary={"overall_status": normalization_status},
        summary={"foundation_marker": True},
        gold_history=pd.DataFrame(
            [
                {"date": "2025-01-03", "close_usd": 1.0, "adj_close_usd": 1.0},
                {"date": "2025-01-10", "close_usd": 1.1, "adj_close_usd": 1.1},
            ]
        ),
        normalized_equity_histories={
            "NEM": pd.DataFrame(
                [
                    {
                        "ticker": "NEM",
                        "date": "2025-01-03",
                        "return_basis_usd": 10.0,
                        "normalization_status": "OK",
                    },
                    {
                        "ticker": "NEM",
                        "date": "2025-01-10",
                        "return_basis_usd": 10.5,
                        "normalization_status": "OK",
                    },
                ]
            )
        },
        normalized_market_snapshots=pd.DataFrame(),
        manifest_path=ProjectPaths.discover().repo_root / "data" / "intermediate" / "status" / "latest_foundation_manifest.json",
    )


def test_run_tool_a_uses_local_snapshot_and_stops_when_it_is_missing(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: (_ for _ in ()).throw(FileNotFoundError("missing local snapshot")),
    )

    called = {"tool_a": False}

    def _unexpected_tool_a(**kwargs):
        called["tool_a"] = True
        raise AssertionError("Structural Tool A should not run when local snapshot loading fails.")

    monkeypatch.setattr("golden_vector.cli.execute_tool_a_profile_pipeline", _unexpected_tool_a)

    exit_code = run_tool_a(paths)

    assert exit_code == 1
    assert called["tool_a"] is False


def test_run_tool_a_uses_latest_local_snapshot_for_structural_phase(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )
    snapshot = _latest_foundation_snapshot()
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: snapshot,
    )

    called = {"tool_a": False}

    def _tool_a_result(**kwargs):
        called["tool_a"] = True
        assert kwargs["gold_history"].equals(snapshot.gold_history)
        assert kwargs["normalized_equity_histories"]["NEM"].equals(
            snapshot.normalized_equity_histories["NEM"]
        )
        assert kwargs["snapshot_refresh_run_id"] == "refresh-run"
        return type(
            "ToolAResultStub",
            (),
            {
                "tool_a_outputs": pd.DataFrame(
                    [{"ticker": "NEM", "as_of_date": "2026-01-01"}]
                ),
                "structural_window_metrics": pd.DataFrame(),
                "overall_status": "PASS",
                "summary": {"tool_a_output_row_count": 1},
            },
        )()

    monkeypatch.setattr("golden_vector.cli.execute_tool_a_profile_pipeline", _tool_a_result)

    exit_code = run_tool_a(paths)

    assert exit_code == 0
    assert called["tool_a"] is True


def test_combine_statuses_rejects_unknown_values():
    try:
        _combine_statuses("PASS", "NOT_IMPLEMENTED")
    except ValueError as exc:
        assert "NOT_IMPLEMENTED" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unsupported status values.")
