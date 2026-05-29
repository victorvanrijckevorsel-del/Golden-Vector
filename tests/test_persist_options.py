import json
from datetime import date

import pandas as pd

from golden_vector.app.run_context import RunContext
from golden_vector.ingestion.persist_options import (
    persist_options_snapshot,
    write_latest_options_manifest,
)
from tests.helpers import build_test_paths


def test_persist_options_snapshot_writes_run_local_parquet(tmp_path):
    paths = build_test_paths(tmp_path)
    context = _run_context(paths)
    frame = pd.DataFrame(
        [
            {
                "expiration": "2026-06-19",
                "option_type": "P",
                "strike": 45.0,
                "bid": 1.0,
                "ask": 1.2,
                "mid": 1.1,
                "last_price": 1.05,
                "volume": 12,
                "open_interest": 120,
                "implied_volatility": 0.42,
                "underlying_price": 50.0,
                "moneyness": 0.9,
                "days_to_expiry": 21,
            }
        ]
    )

    record = persist_options_snapshot(
        paths=paths,
        run_context=context,
        ticker="AEM",
        frame=frame,
        as_of_date=date(2026, 5, 29),
        options_available=True,
    )

    assert record.snapshot_path == context.run_dir / "snapshots" / "options" / "AEM.parquet"
    assert record.snapshot_path.exists()
    assert record.row_count == 1
    snapshot = pd.read_parquet(record.snapshot_path)
    assert snapshot.loc[0, "ticker"] == "AEM"
    assert snapshot.loc[0, "as_of_date"] == "2026-05-29"
    assert snapshot.loc[0, "run_id"] == context.run_id
    assert bool(snapshot.loc[0, "options_available"]) is True
    assert record.snapshot_path.relative_to(paths.repo_root).as_posix() in context.artifacts


def test_persist_options_snapshot_writes_empty_chain_marker(tmp_path):
    paths = build_test_paths(tmp_path)
    context = _run_context(paths)

    record = persist_options_snapshot(
        paths=paths,
        run_context=context,
        ticker="AAUC.TO",
        frame=pd.DataFrame(),
        as_of_date=date(2026, 5, 29),
        options_available=False,
        message="No listed options returned by Yahoo.",
    )

    snapshot = pd.read_parquet(record.snapshot_path)
    assert record.options_available is False
    assert record.row_count == 1
    assert snapshot.loc[0, "ticker"] == "AAUC.TO"
    assert bool(snapshot.loc[0, "options_available"]) is False
    assert snapshot.loc[0, "empty_reason"] == "No listed options returned by Yahoo."


def test_write_latest_options_manifest_points_at_run_snapshots(tmp_path):
    paths = build_test_paths(tmp_path)
    context = _run_context(paths)
    record = persist_options_snapshot(
        paths=paths,
        run_context=context,
        ticker="AEM",
        frame=pd.DataFrame([{"strike": 45.0}]),
        as_of_date=date(2026, 5, 29),
        options_available=True,
    )

    manifest_path = write_latest_options_manifest(
        paths=paths,
        run_context=context,
        as_of_date=date(2026, 5, 29),
        snapshot_records=[record],
        risk_free_rate=0.043,
        summary={"success_count": 1},
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_path == paths.latest_options_manifest_path
    assert payload["refresh_run_id"] == context.run_id
    assert payload["as_of_date"] == "2026-05-29"
    assert payload["options_snapshot_dir"] == f"data/runs/{context.run_id}/snapshots/options"
    assert payload["risk_free_rate"] == 0.043
    assert payload["summary"] == {"success_count": 1}
    assert payload["snapshots"][0]["ticker"] == "AEM"
    assert payload["snapshots"][0]["sha256"] == record.sha256
    assert payload["snapshots"][0]["snapshot_path"] == (
        f"data/runs/{context.run_id}/snapshots/options/AEM.parquet"
    )
    assert manifest_path.relative_to(paths.repo_root).as_posix() in context.artifacts


def _run_context(paths) -> RunContext:
    run_id = "20260529T000000Z-update-data-options"
    run_dir = paths.ensure_run_dir(run_id)
    return RunContext(
        paths=paths,
        command="update-data",
        parameters={},
        config_hash="test-config-hash",
        run_id=run_id,
        run_dir=run_dir,
        started_at_utc="2026-05-29T00:00:00Z",
        metadata_path=run_dir / "metadata.json",
        log_path=run_dir / "run.log",
    )
