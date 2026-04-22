from dataclasses import dataclass
from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import run_tool_b
from golden_vector.ingestion.foundation import FoundationExecutionResult
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
            return {"market_snapshot_target_count": 1}

    return FoundationExecutionResult(
        registry=_RegistryStub(),
        raw_qa_report=RawQaReport(overall_status=raw_status, results=[]),
        normalization_qa_report=normalization_report,
        overall_status=raw_status if normalization_status is None else normalization_status,
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
        summary={"foundation_marker": True},
    )


def test_run_tool_b_stops_when_raw_qa_fails(tmp_path, monkeypatch):
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

    called = {"tool_b": False}

    def _unexpected_tool_b(**kwargs):
        called["tool_b"] = True
        raise AssertionError("Tool B pipeline should not run when raw QA fails.")

    monkeypatch.setattr("golden_vector.cli.execute_tool_b_pipeline", _unexpected_tool_b)

    exit_code = run_tool_b(paths, gold_price=4000)

    assert exit_code == 1
    assert called["tool_b"] is False


def test_run_tool_b_stops_when_normalization_qa_fails(tmp_path, monkeypatch):
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

    called = {"tool_b": False}

    def _unexpected_tool_b(**kwargs):
        called["tool_b"] = True
        raise AssertionError("Tool B pipeline should not run when normalization QA fails.")

    monkeypatch.setattr("golden_vector.cli.execute_tool_b_pipeline", _unexpected_tool_b)

    exit_code = run_tool_b(paths, gold_price=4000)

    assert exit_code == 1
    assert called["tool_b"] is False


def test_run_tool_b_completes_when_backbone_and_screening_succeed(tmp_path, monkeypatch):
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
