from dataclasses import dataclass
from datetime import date
import json

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.latest_data import LatestFoundationSnapshot
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import build_parser, run_tool_d
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from tests.helpers import build_test_paths


@dataclass(frozen=True)
class _LoadedConfigStub:
    app: object
    combined_hash: str


def test_tool_d_parser_accepts_optional_gold_price():
    args = build_parser().parse_args(["tool-d", "--gold-price", "3100"])

    assert args.command == "tool-d"
    assert args.gold_price == 3100


def test_run_tool_d_defaults_gold_price_to_latest_spot(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_tool_b_latest(paths)
    snapshot = _latest_foundation_snapshot(paths)

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: snapshot,
    )
    captured = {"gold_price": None}

    def fake_compute_tool_d_outputs(**kwargs):
        captured["gold_price"] = kwargs["gold_price"]
        inputs = kwargs["inputs"]
        assert inputs.tool_b_latest["ticker"].tolist() == ["NEM"]
        assert inputs.spot_gold_usd == 4050.0
        assert inputs.spot_gold_date == "2026-06-01"
        return pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 6, 1),
                    "gold_price_used": kwargs["gold_price"],
                    "spot_gold_usd": inputs.spot_gold_usd,
                    "spot_gold_date": inputs.spot_gold_date,
                    "tool_d_quality_rank": 100.0,
                }
            ]
        )

    monkeypatch.setattr(
        "golden_vector.cli.compute_tool_d_outputs",
        fake_compute_tool_d_outputs,
    )

    exit_code = run_tool_d(paths, gold_price=None)

    assert exit_code == 0
    assert captured["gold_price"] == 4050.0
    latest = pd.read_parquet(paths.latest_tool_d_snapshot_parquet_path)
    assert latest["gold_price_used"].iloc[0] == 4050.0
    manifest = json.loads(
        next(paths.runs_dir.glob("*-tool-d-*")).joinpath("replay_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["tool_d_sources_captured"]["metadata"]["spot_gold_date"] == "2026-06-01"


def _write_tool_b_latest(paths):
    paths.output_tool_b_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 6, 1),
                "source_run_id": "tool-b-run",
                "snapshot_refresh_run_id": "refresh-run",
                "tool_b_rank": 1,
            }
        ]
    ).to_parquet(paths.latest_tool_b_snapshot_parquet_path, index=False)


def _latest_foundation_snapshot(paths) -> LatestFoundationSnapshot:
    run_dir = paths.runs_dir / "refresh-run"
    snapshot_dir = run_dir / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    gold_path = snapshot_dir / "raw_gold.parquet"
    market_path = snapshot_dir / "market_snapshots_usd.parquet"
    gold_history = pd.DataFrame(
        [
            {"date": date(2026, 5, 31), "adj_close_usd": 4000.0},
            {"date": date(2026, 6, 1), "adj_close_usd": 4050.0},
        ]
    )
    market_snapshots = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "snapshot_date": date(2026, 6, 1),
                "share_price_usd": 60.0,
                "market_cap_usd": 48_000_000_000.0,
                "shares_outstanding": 800_000_000.0,
                "normalization_status": "OK",
            }
        ]
    )
    gold_history.to_parquet(gold_path, index=False)
    market_snapshots.to_parquet(market_path, index=False)
    manifest_path = paths.latest_foundation_manifest_path
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": "refresh-run",
                "gold_history_path": gold_path.relative_to(paths.repo_root).as_posix(),
                "normalized_market_snapshots_snapshot_path": market_path.relative_to(
                    paths.repo_root
                ).as_posix(),
            }
        ),
        encoding="utf-8",
    )
    return LatestFoundationSnapshot(
        refresh_run_id="refresh-run",
        snapshot_as_of_date="2026-06-01",
        foundation_status="PASS",
        raw_qa_summary={"overall_status": "PASS"},
        normalization_qa_summary={"overall_status": "PASS"},
        summary={"foundation_marker": True},
        gold_history=gold_history,
        normalized_equity_histories={},
        normalized_market_snapshots=market_snapshots,
        manifest_path=manifest_path,
    )
