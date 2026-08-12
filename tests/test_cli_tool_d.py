from dataclasses import dataclass, replace
from datetime import date
import json
from types import SimpleNamespace

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.latest_data import LatestFoundationSnapshot
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import build_parser, run_tool_d
from golden_vector.contracts.tool_d import (
    TOOL_D_OUTPUT_COLUMNS,
    TOOL_D_SCHEMA_VERSION,
)
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from tests.helpers import build_test_paths, tool_b_output_row


@dataclass(frozen=True)
class _LoadedConfigStub:
    app: object
    config_hash: str


def test_tool_d_parser_accepts_optional_gold_price():
    args = build_parser().parse_args(["tool-d", "--gold-price", "3100"])

    assert args.command == "tool-d"
    assert args.gold_price == 3100


def test_run_tool_d_defaults_gold_price_to_latest_spot(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = _nem_only_app_config(load_app_config(ProjectPaths.discover()).app)
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_tool_b_latest(paths)
    snapshot = _latest_foundation_snapshot(paths)

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: snapshot,
    )
    official_path = paths.output_fundamentals_dir / "official-used.parquet"
    official_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"ticker": "NEM"}]).to_parquet(official_path, index=False)
    monkeypatch.setattr(
        "golden_vector.cli.load_official_fundamentals_with_source_path",
        lambda *_args, **_kwargs: (pd.DataFrame(), official_path),
    )
    captured = {
        "gold_prices": [],
        "finance_sources": [],
        "upstream_ids": [],
    }

    def fake_compute_tool_d_outputs(**kwargs):
        captured["gold_prices"].append(kwargs["gold_price"])
        inputs = kwargs["inputs"]
        captured["finance_sources"].append(inputs.finance_source)
        captured["upstream_ids"].append(
            (
                id(inputs.manual_data),
                id(inputs.normalized_market_snapshots),
                id(inputs.tool_b_latest),
                id(inputs.official_fundamentals),
            )
        )
        assert inputs.tool_b_latest["ticker"].tolist() == ["NEM"]
        assert inputs.spot_gold_usd == 4050.0
        assert inputs.spot_gold_date == "2026-06-01"
        return _computed_tool_d_frame(kwargs)

    monkeypatch.setattr(
        "golden_vector.cli.compute_tool_d_outputs",
        fake_compute_tool_d_outputs,
    )

    exit_code = run_tool_d(paths, gold_price=None)

    assert exit_code == 0
    assert captured["gold_prices"] == [4050.0, 4050.0]
    assert captured["finance_sources"] == ["our", "yahoo"]
    assert captured["upstream_ids"][0] == captured["upstream_ids"][1]
    latest = pd.read_parquet(paths.latest_tool_d_snapshot_parquet_path)
    assert latest["gold_price_used"].eq(4050.0).all()
    assert set(latest["finance_source"]) == {"our", "yahoo"}
    spot_latest = pd.read_parquet(paths.latest_tool_d_spot_snapshot_parquet_path)
    assert spot_latest["gold_price_used"].eq(4050.0).all()
    run_dir = next(paths.runs_dir.glob("*-tool-d-*"))
    manifest = json.loads(
        run_dir.joinpath("replay_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["tool_d_sources_captured"]["metadata"]["spot_gold_date"] == "2026-06-01"
    source_assets = manifest["tool_d_sources_captured"]["source_assets"]
    official_asset = next(
        asset for asset in source_assets if asset["name"] == "official_fundamentals"
    )
    assert official_asset["original_path"].endswith("official-used.parquet")
    summary = json.loads(
        run_dir.joinpath("tool_d_output_summary.json").read_text(encoding="utf-8")
    )
    assert summary["tool_d_schema_version"] == TOOL_D_SCHEMA_VERSION
    assert summary["tool_d_source_summaries"]["our"]["rows"] == 1
    assert summary["tool_d_source_summaries"]["yahoo"]["rows"] == 1
    assert summary["tool_d_stage_timings"]["compute_our"]["rows_built"] == 1
    assert summary["tool_d_stage_timings"]["compute_yahoo"]["rows_persisted"] == 1


def test_run_tool_d_scenario_does_not_publish_spot_alias(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = _nem_only_app_config(load_app_config(ProjectPaths.discover()).app)
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_tool_b_latest(paths)
    snapshot = _latest_foundation_snapshot(paths)

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: snapshot,
    )

    def fake_compute_tool_d_outputs(**kwargs):
        return _computed_tool_d_frame(kwargs)

    monkeypatch.setattr(
        "golden_vector.cli.compute_tool_d_outputs",
        fake_compute_tool_d_outputs,
    )

    exit_code = run_tool_d(paths, gold_price=3500.0)

    assert exit_code == 0
    latest = pd.read_parquet(paths.latest_tool_d_snapshot_parquet_path)
    assert latest["gold_price_used"].eq(3500.0).all()
    assert set(latest["finance_source"]) == {"our", "yahoo"}
    assert not paths.latest_tool_d_spot_snapshot_parquet_path.exists()


def test_run_tool_d_scenario_leaves_existing_spot_alias_untouched(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = _nem_only_app_config(load_app_config(ProjectPaths.discover()).app)
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_tool_b_latest(paths)
    snapshot = _latest_foundation_snapshot(paths)

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: snapshot,
    )

    def fake_compute_tool_d_outputs(**kwargs):
        return _computed_tool_d_frame(kwargs)

    monkeypatch.setattr(
        "golden_vector.cli.compute_tool_d_outputs",
        fake_compute_tool_d_outputs,
    )

    assert run_tool_d(paths, gold_price=None) == 0
    spot_before = paths.latest_tool_d_spot_snapshot_parquet_path.read_bytes()
    assert run_tool_d(paths, gold_price=3500.0) == 0

    latest = pd.read_parquet(paths.latest_tool_d_snapshot_parquet_path)
    spot_latest = pd.read_parquet(paths.latest_tool_d_spot_snapshot_parquet_path)
    assert latest["gold_price_used"].eq(3500.0).all()
    assert spot_latest["gold_price_used"].eq(4050.0).all()
    assert paths.latest_tool_d_spot_snapshot_parquet_path.read_bytes() == spot_before


def test_run_tool_d_aborts_both_sources_before_publish_when_yahoo_compute_raises(
    tmp_path,
    monkeypatch,
):
    paths = build_test_paths(tmp_path)
    app_config = _nem_only_app_config(load_app_config(ProjectPaths.discover()).app)
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_tool_b_latest(paths)
    snapshot = _latest_foundation_snapshot(paths)
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=app_config, config_hash="hash"),
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        lambda **_: snapshot,
    )
    monkeypatch.setattr(
        "golden_vector.cli.compute_tool_d_outputs",
        lambda **kwargs: _computed_tool_d_frame(kwargs),
    )
    assert run_tool_d(paths, gold_price=None) == 0
    aliases_before = _tool_d_alias_bytes(paths)

    def fail_yahoo(**kwargs):
        if kwargs["inputs"].finance_source == "yahoo":
            raise RuntimeError("injected Yahoo Tool D failure")
        frame = _computed_tool_d_frame(kwargs)
        frame["tool_d_quality_rank"] = 1.0
        return frame

    monkeypatch.setattr("golden_vector.cli.compute_tool_d_outputs", fail_yahoo)

    assert run_tool_d(paths, gold_price=None) == 1
    assert _tool_d_alias_bytes(paths) == aliases_before


def test_run_tool_d_standalone_refuses_when_shared_writer_lock_is_busy(
    tmp_path,
    monkeypatch,
):
    paths = build_test_paths(tmp_path)
    lock = SimpleNamespace(
        already_running=True,
        started=False,
        adopted=False,
        status=SimpleNamespace(process_id=123, job_id="busy"),
    )
    monkeypatch.setattr("golden_vector.cli.acquire_refresh_lock", lambda *_a, **_k: lock)

    assert run_tool_d(paths, gold_price=None) == 2
    assert not list(paths.runs_dir.glob("*-tool-d-*"))


def test_run_tool_d_standalone_uses_model_state_foundation_and_tool_b(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = _nem_only_app_config(load_app_config(ProjectPaths.discover()).app)
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    old_tool_b_path = paths.output_tool_b_dir / "tool_b_latest_refresh-old.parquet"
    old_tool_b_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            tool_b_output_row(
                "NEM",
                as_of_date=date(2026, 6, 1),
                source_run_id="tool-b-old",
                snapshot_refresh_run_id="refresh-old",
            )
        ]
    ).to_parquet(old_tool_b_path, index=False)
    pd.DataFrame(
        [
            tool_b_output_row(
                "STALE_ALIAS",
                as_of_date=date(2026, 6, 2),
                source_run_id="tool-b-new",
                snapshot_refresh_run_id="refresh-new",
            )
        ]
    ).to_parquet(paths.latest_tool_b_snapshot_parquet_path, index=False)

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
                    "tool_b": {
                        "path": old_tool_b_path.relative_to(paths.repo_root).as_posix(),
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
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )

    def fake_load_latest_foundation_snapshot(**kwargs):
        assert kwargs["manifest_path"] == old_foundation_path
        return old_snapshot

    monkeypatch.setattr(
        "golden_vector.cli.load_latest_foundation_snapshot",
        fake_load_latest_foundation_snapshot,
    )

    def fake_compute_tool_d_outputs(**kwargs):
        inputs = kwargs["inputs"]
        assert inputs.tool_b_latest["ticker"].tolist() == ["NEM"]
        assert inputs.snapshot_refresh_run_id == "refresh-old"
        assert inputs.spot_gold_usd == 4050.0
        return _computed_tool_d_frame(kwargs)

    monkeypatch.setattr(
        "golden_vector.cli.compute_tool_d_outputs",
        fake_compute_tool_d_outputs,
    )

    assert run_tool_d(paths, gold_price=None) == 0


def _nem_only_app_config(app_config):
    nem = next(ticker for ticker in app_config.universe.tickers if ticker.ticker == "NEM")
    universe = app_config.universe.model_copy(update={"tickers": [nem]})
    return app_config.model_copy(update={"universe": universe})


def _computed_tool_d_frame(kwargs) -> pd.DataFrame:
    inputs = kwargs["inputs"]
    row = {column: None for column in TOOL_D_OUTPUT_COLUMNS}
    row.update(
        {
            "ticker": "NEM",
            "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
            "as_of_date": date(2026, 6, 1),
            "source_run_id": kwargs["source_run_id"],
            "finance_source": inputs.finance_source,
            "snapshot_refresh_run_id": inputs.snapshot_refresh_run_id,
            "gold_price_used": kwargs["gold_price"],
            "spot_gold_usd": inputs.spot_gold_usd,
            "spot_gold_date": inputs.spot_gold_date,
            "resilience_data_status": "OK",
            "tool_d_quality_score": 100.0,
            "tool_d_quality_rank": 100.0,
        }
    )
    return pd.DataFrame([row], columns=TOOL_D_OUTPUT_COLUMNS)


def _tool_d_alias_bytes(paths) -> dict[object, bytes]:
    alias_paths = (
        paths.latest_tool_d_snapshot_csv_path,
        paths.latest_tool_d_snapshot_parquet_path,
        paths.latest_tool_d_spot_snapshot_csv_path,
        paths.latest_tool_d_spot_snapshot_parquet_path,
    )
    return {path: path.read_bytes() for path in alias_paths}


def _write_tool_b_latest(paths):
    paths.output_tool_b_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            tool_b_output_row(
                "NEM",
                as_of_date=date(2026, 6, 1),
                source_run_id="tool-b-run",
                snapshot_refresh_run_id="refresh-run",
            )
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
