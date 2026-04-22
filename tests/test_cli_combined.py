from dataclasses import dataclass
from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import run_combined
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
        else NormalizationQaReport(overall_status=normalization_status, results=[])
    )

    class _RegistryStub:
        def summary(self) -> dict[str, object]:
            return {"equity_target_count": 1}

    return FoundationExecutionResult(
        registry=_RegistryStub(),
        raw_qa_report=RawQaReport(overall_status=raw_status, results=[]),
        normalization_qa_report=normalization_report,
        overall_status=raw_status if normalization_status is None else normalization_status,
        gold_history=pd.DataFrame([{"date": "2026-02-01", "close_usd": 1.0, "adj_close_usd": 1.0}]),
        normalized_equity_histories={
            "NEM": pd.DataFrame([{"ticker": "NEM", "date": "2026-02-01", "return_basis_usd": 1.0}])
        },
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
        summary={"foundation_marker": True},
    )


def test_run_combined_stops_when_horizon_qa_fails(tmp_path, monkeypatch):
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

    called = {"combined": False}

    def _unexpected_combined(**kwargs):
        called["combined"] = True
        raise AssertionError("Combined pipeline should not run when horizon QA fails.")

    monkeypatch.setattr("golden_vector.cli.execute_combined_pipeline", _unexpected_combined)

    exit_code = run_combined(paths, gold_price=4000)

    assert exit_code == 1
    assert called["combined"] is False


def test_run_combined_continues_with_partial_merge_when_tool_b_has_no_rows(tmp_path, monkeypatch):
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
                "qa_report": HorizonQaReport(overall_status="PASS", results=[]),
                "overall_status": "PASS",
                "horizon_metrics": pd.DataFrame(
                    [
                        {
                            "ticker": "NEM",
                            "as_of_date": date(2026, 2, 1),
                            "horizon_id": "5D",
                            "horizon_mode": "core",
                            "coverage_flag": "PASS",
                            "official_scoring_eligible": True,
                        }
                    ]
                ),
                "summary": {"horizon_row_count": 1},
            },
        )(),
    )
    monkeypatch.setattr(
        "golden_vector.cli.execute_tool_a_profile_pipeline",
        lambda **_: type(
            "ToolAResultStub",
            (),
            {
                "tool_a_outputs": pd.DataFrame(
                    [
                        {
                            "ticker": "NEM",
                            "as_of_date": date(2026, 2, 1),
                            "tool_a_score": 80.0,
                            "tool_a_rank": 1,
                            "core_delta": 1.2,
                            "regime_tag": "BULLISH",
                            "coverage_summary": "PASS",
                            "source_run_id": "tool-a-run",
                        }
                    ]
                ),
                "overall_status": "PASS",
                "summary": {"tool_a_output_row_count": 1, "tool_a_output_overall_status": "PASS"},
            },
        )(),
    )
    monkeypatch.setattr(
        "golden_vector.cli.execute_tool_b_pipeline",
        lambda **_: type(
            "ToolBResultStub",
            (),
            {
                "tool_b_outputs": pd.DataFrame(),
                "overall_status": "FAIL",
                "summary": {"tool_b_output_row_count": 0, "tool_b_output_overall_status": "FAIL"},
            },
        )(),
    )

    called = {"combined": False}

    def _combined_stub(**kwargs):
        called["combined"] = True
        return type(
            "CombinedResultStub",
            (),
            {
                "combined_outputs": pd.DataFrame(
                    [
                        {
                            "ticker": "NEM",
                            "as_of_date": date(2026, 2, 1),
                            "gold_price_assumption": 4000.0,
                            "join_status": "PARTIAL",
                        }
                    ]
                ),
                "overall_status": "WARN",
                "summary": {"combined_output_row_count": 1, "combined_output_overall_status": "WARN"},
            },
        )()

    monkeypatch.setattr("golden_vector.cli.execute_combined_pipeline", _combined_stub)

    exit_code = run_combined(paths, gold_price=4000)

    assert exit_code == 0
    assert called["combined"] is True
