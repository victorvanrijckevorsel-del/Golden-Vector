from dataclasses import dataclass, replace
from datetime import date
import json

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.latest_data import LatestFoundationSnapshot
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import build_parser, run_tool_c
from tests.helpers import build_test_paths


@dataclass(frozen=True)
class _LoadedConfigStub:
    app: object
    combined_hash: str


def test_tool_c_parser_accepts_command():
    args = build_parser().parse_args(["tool-c"])

    assert args.command == "tool-c"


def test_run_tool_c_uses_latest_local_inputs(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    _write_tool_a_latest(paths)
    snapshot = _latest_foundation_snapshot(paths)

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: snapshot,
    )
    captured = {"called": False}

    def fake_compute_tool_c_outputs(**kwargs):
        captured["called"] = True
        inputs = kwargs["inputs"]
        assert inputs.tool_a_latest["ticker"].tolist() == ["NEM"]
        assert inputs.gold_history.equals(snapshot.gold_history)
        assert "NEM" in inputs.normalized_equity_histories
        return pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 6, 1),
                    "tool_c_downside_rank": 100.0,
                    "tool_c_upside_rank": 50.0,
                }
            ]
        )

    monkeypatch.setattr(
        "golden_vector.cli.compute_tool_c_outputs",
        fake_compute_tool_c_outputs,
    )

    exit_code = run_tool_c(paths)

    assert exit_code == 0
    assert captured["called"] is True
    latest = pd.read_parquet(paths.latest_tool_c_snapshot_parquet_path)
    assert latest["ticker"].tolist() == ["NEM"]


def test_run_tool_c_standalone_uses_model_state_foundation_and_tool_a(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app

    old_tool_a_path = paths.output_tool_a_dir / "tool_a_latest_refresh-old.parquet"
    old_tool_a_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 6, 1),
                "source_run_id": "tool-a-old",
                "snapshot_refresh_run_id": "refresh-old",
                "down_beta_core": 1.4,
                "up_beta_core": 1.2,
                "score_eligible": True,
            }
        ]
    ).to_parquet(old_tool_a_path, index=False)
    pd.DataFrame(
        [
            {
                "ticker": "STALE_ALIAS",
                "as_of_date": date(2026, 6, 2),
                "source_run_id": "tool-a-new",
                "snapshot_refresh_run_id": "refresh-new",
                "down_beta_core": 1.0,
                "up_beta_core": 1.0,
                "score_eligible": True,
            }
        ]
    ).to_parquet(paths.latest_tool_a_snapshot_parquet_path, index=False)

    old_snapshot = _latest_foundation_snapshot(paths)
    old_foundation_path = paths.intermediate_status_dir / "foundation_manifest_refresh-old.json"
    old_foundation_path.write_bytes(paths.latest_foundation_manifest_path.read_bytes())
    old_snapshot = replace(
        old_snapshot,
        refresh_run_id="refresh-old",
        manifest_path=old_foundation_path,
    )
    paths.latest_foundation_manifest_path.write_text(
        json.dumps({"refresh_run_id": "refresh-new"}),
        encoding="utf-8",
    )
    paths.latest_model_state_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "manifest_readable": True,
                "state": "complete",
                "artifacts": {
                    "foundation": {
                        "path": old_foundation_path.relative_to(
                            paths.repo_root
                        ).as_posix(),
                        "usable": True,
                        "immutable": True,
                    },
                    "tool_a": {
                        "path": old_tool_a_path.relative_to(paths.repo_root).as_posix(),
                        "usable": True,
                        "immutable": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )

    def fake_load_latest_foundation_snapshot(**kwargs):
        assert kwargs["manifest_path"] == old_foundation_path
        return old_snapshot

    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        fake_load_latest_foundation_snapshot,
    )

    def fake_compute_tool_c_outputs(**kwargs):
        inputs = kwargs["inputs"]
        assert inputs.tool_a_latest["ticker"].tolist() == ["NEM"]
        assert inputs.gold_history.equals(old_snapshot.gold_history)
        assert "NEM" in inputs.normalized_equity_histories
        return pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 6, 1),
                    "tool_c_downside_rank": 100.0,
                    "tool_c_upside_rank": 50.0,
                }
            ]
        )

    monkeypatch.setattr(
        "golden_vector.cli.compute_tool_c_outputs",
        fake_compute_tool_c_outputs,
    )

    assert run_tool_c(paths) == 0


def _write_tool_a_latest(paths):
    paths.output_tool_a_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 6, 1),
                "source_run_id": "tool-a-run",
                "snapshot_refresh_run_id": "refresh-run",
                "down_beta_core": 1.4,
                "up_beta_core": 1.2,
                "score_eligible": True,
            }
        ]
    ).to_parquet(paths.latest_tool_a_snapshot_parquet_path, index=False)


def _latest_foundation_snapshot(paths) -> LatestFoundationSnapshot:
    run_dir = paths.runs_dir / "refresh-run"
    snapshot_dir = run_dir / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    gold_path = snapshot_dir / "raw_gold.parquet"
    equities_path = snapshot_dir / "usd_equities.parquet"
    gold_history = pd.DataFrame(
        [
            {"date": date(2026, 5, 29), "adj_close_usd": 3300.0},
            {"date": date(2026, 6, 5), "adj_close_usd": 3310.0},
        ]
    )
    equity_history = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "date": date(2026, 5, 29),
                "return_basis_usd": 100.0,
                "normalization_status": "OK",
            },
            {
                "ticker": "NEM",
                "date": date(2026, 6, 5),
                "return_basis_usd": 101.0,
                "normalization_status": "OK",
            },
        ]
    )
    gold_history.to_parquet(gold_path, index=False)
    equity_history.to_parquet(equities_path, index=False)
    manifest_path = paths.latest_foundation_manifest_path
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": "refresh-run",
                "gold_history_path": gold_path.relative_to(paths.repo_root).as_posix(),
                "normalized_equities_snapshot_path": equities_path.relative_to(
                    paths.repo_root
                ).as_posix(),
            }
        ),
        encoding="utf-8",
    )
    return LatestFoundationSnapshot(
        refresh_run_id="refresh-run",
        snapshot_as_of_date="2026-06-05",
        foundation_status="PASS",
        raw_qa_summary={"overall_status": "PASS"},
        normalization_qa_summary={"overall_status": "PASS"},
        summary={"foundation_marker": True},
        gold_history=gold_history,
        normalized_equity_histories={"NEM": equity_history},
        normalized_market_snapshots=pd.DataFrame(),
        manifest_path=manifest_path,
    )
