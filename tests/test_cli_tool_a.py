from dataclasses import dataclass

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import _combine_statuses, run_tool_a
from golden_vector.ingestion.foundation import FoundationExecutionResult
from golden_vector.qa.horizon_quality import HorizonQaReport
from golden_vector.qa.normalization_quality import NormalizationQaReport
from golden_vector.qa.raw_quality import RawQaReport
from tests.helpers import build_test_paths


@dataclass(frozen=True)
class _LoadedConfigStub:
    app: object
    combined_hash: str


def _foundation_result(*, raw_status: str, normalization_status: str | None) -> FoundationExecutionResult:
    normalization_report = (
        None
        if normalization_status is None
        else NormalizationQaReport(
            overall_status=normalization_status,
            results=[],
        )
    )

    class _RegistryStub:
        def summary(self) -> dict[str, object]:
            return {"equity_target_count": 1}

    return FoundationExecutionResult(
        registry=_RegistryStub(),
        raw_qa_report=RawQaReport(overall_status=raw_status, results=[]),
        normalization_qa_report=normalization_report,
        overall_status=raw_status if normalization_status is None else normalization_status,
        gold_history=pd.DataFrame([{"date": "2026-01-01", "close_usd": 1.0, "adj_close_usd": 1.0}]),
        normalized_equity_histories={
            "NEM": pd.DataFrame(
                [{"ticker": "NEM", "date": "2026-01-01", "return_basis_usd": 1.0}]
            )
        },
        normalized_market_snapshots=pd.DataFrame(),
        summary={"foundation_marker": True},
    )


def test_run_tool_a_stops_before_phase3_when_raw_qa_fails(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.execute_foundation_pipeline",
        lambda **_: _foundation_result(raw_status="FAIL", normalization_status=None),
    )

    called = {"horizon": False}

    def _unexpected_horizon(**kwargs):
        called["horizon"] = True
        raise AssertionError("Horizon pipeline should not run when raw QA fails.")

    monkeypatch.setattr("golden_vector.cli.execute_horizon_pipeline", _unexpected_horizon)

    exit_code = run_tool_a(paths)

    assert exit_code == 1
    assert called["horizon"] is False


def test_run_tool_a_stops_before_phase3_when_normalization_qa_fails(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.execute_foundation_pipeline",
        lambda **_: _foundation_result(raw_status="PASS", normalization_status="FAIL"),
    )

    called = {"horizon": False}

    def _horizon_result(**kwargs):
        called["horizon"] = True
        return type(
            "HorizonResultStub",
            (),
            {
                "qa_report": HorizonQaReport(overall_status="PASS", results=[]),
                "overall_status": "PASS",
                "horizon_metrics": pd.DataFrame(
                    [
                        {
                            "ticker": "NEM",
                            "as_of_date": "2026-01-01",
                            "horizon_id": "5D",
                            "horizon_mode": "core",
                            "coverage_flag": "PASS",
                            "official_scoring_eligible": True,
                        }
                    ]
                ),
                "summary": {"horizon_row_count": 1},
            },
        )()

    monkeypatch.setattr("golden_vector.cli.execute_horizon_pipeline", _horizon_result)

    exit_code = run_tool_a(paths)

    assert exit_code == 1
    assert called["horizon"] is False


def test_run_tool_a_stops_before_scoring_when_horizon_qa_fails(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.execute_foundation_pipeline",
        lambda **_: _foundation_result(raw_status="PASS", normalization_status="PASS"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.execute_horizon_pipeline",
        lambda **_: type(
            "HorizonResultStub",
            (),
            {
                "qa_report": HorizonQaReport(overall_status="FAIL", results=[]),
                "overall_status": "FAIL",
                "horizon_metrics": pd.DataFrame(),
                "summary": {"horizon_row_count": 0},
            },
        )(),
    )

    called = {"profile": False}

    def _unexpected_profile(**kwargs):
        called["profile"] = True
        raise AssertionError("Tool A scoring should not run when horizon QA fails.")

    monkeypatch.setattr("golden_vector.cli.execute_tool_a_profile_pipeline", _unexpected_profile)

    exit_code = run_tool_a(paths)

    assert exit_code == 1
    assert called["profile"] is False


def test_combine_statuses_rejects_unknown_values():
    try:
        _combine_statuses("PASS", "NOT_IMPLEMENTED")
    except ValueError as exc:
        assert "NOT_IMPLEMENTED" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unsupported status values.")
