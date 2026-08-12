from datetime import date
import json

import pandas as pd
import pytest

from golden_vector.app.replay_manifest import verify_manifest
from golden_vector.app.run_context import RunContext
from golden_vector.common.parquet import parquet_context_metadata
from golden_vector.contracts.tool_d import (
    TOOL_D_OUTPUT_COLUMNS,
    TOOL_D_SCHEMA_VERSION,
)
from golden_vector.ingestion.persist import _latest_snapshot
from golden_vector.ingestion.persist_tool_d import persist_tool_d_outputs
from tests.helpers import build_test_paths


def _tool_d_row(
    ticker: str,
    finance_source: str,
    as_of_date: date,
    rank: float,
) -> dict[str, object]:
    row = {column: None for column in TOOL_D_OUTPUT_COLUMNS}
    row.update(
        {
            "ticker": ticker,
            "finance_source": finance_source,
            "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
            "as_of_date": as_of_date,
            "resilience_data_status": "OK",
            "tool_d_quality_rank": rank,
        }
    )
    return row


def test_persist_tool_d_outputs_writes_latest_and_source_snapshots(tmp_path):
    paths = build_test_paths(tmp_path)
    run_context = RunContext.start(
        paths=paths,
        command="tool-d",
        parameters={"gold_price": 3000},
        config_hash="hash",
    )
    source_path = paths.output_tool_b_dir / "tool_b_latest.parquet"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"ticker": "AAA"}]).to_parquet(source_path, index=False)
    outputs = pd.DataFrame(
        [
            _tool_d_row("AAA", "our", date(2026, 6, 1), 90.0),
            _tool_d_row("AAA", "yahoo", date(2026, 6, 1), 91.0),
            _tool_d_row("BBB", "our", date(2026, 6, 1), 80.0),
            _tool_d_row("BBB", "yahoo", date(2026, 6, 1), 81.0),
        ],
        columns=TOOL_D_OUTPUT_COLUMNS,
    )

    written_paths = persist_tool_d_outputs(
        paths=paths,
        run_context=run_context,
        tool_d_outputs=outputs,
        source_paths={"tool_b_latest": source_path},
        provenance_metadata={
            "gold_price_used": 3000.0,
            "spot_gold_usd": 4000.0,
            "spot_gold_date": "2026-06-01",
        },
        publish_spot_latest_aliases=True,
    )

    assert len(written_paths) == 10
    latest = pd.read_parquet(paths.latest_tool_d_snapshot_parquet_path)
    assert set(latest["ticker"]) == {"AAA", "BBB"}
    assert len(latest.index) == 4
    assert set(latest["finance_source"]) == {"our", "yahoo"}
    assert latest.loc[latest["ticker"] == "AAA", "as_of_date"].eq(date(2026, 6, 1)).all()
    spot_latest = pd.read_parquet(paths.latest_tool_d_spot_snapshot_parquet_path)
    assert set(spot_latest["ticker"]) == {"AAA", "BBB"}
    assert len(spot_latest.index) == 4
    assert parquet_context_metadata(paths.latest_tool_d_snapshot_parquet_path)[
        "schema_version"
    ] == "4"

    manifest = json.loads(
        (run_context.run_dir / "replay_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["tool_d_sources_status"] == "captured"
    assert manifest["tool_d_sources_captured"]["metadata"]["spot_gold_date"] == "2026-06-01"
    asset = manifest["tool_d_sources_captured"]["source_assets"][0]
    assert asset["name"] == "tool_b_latest"
    assert (run_context.run_dir / asset["snapshot_path"]).exists()
    assert verify_manifest(run_context.run_dir).ok


def test_latest_snapshot_default_path_remains_ticker_keyed():
    frame = pd.DataFrame(
        [
            {"ticker": "AAA", "as_of_date": date(2026, 5, 1), "value": 1},
            {"ticker": "AAA", "as_of_date": date(2026, 6, 1), "value": 2},
            {"ticker": "BBB", "as_of_date": date(2026, 5, 1), "value": 3},
        ]
    )

    latest = _latest_snapshot(frame).set_index("ticker")

    assert latest.loc["AAA", "value"] == 2
    assert latest.loc["BBB", "value"] == 3


def test_latest_snapshot_composite_key_keeps_both_sources_and_fails_on_ambiguity():
    frame = pd.DataFrame(
        [
            {"ticker": "AAA", "finance_source": "our", "as_of_date": date(2026, 5, 1)},
            {"ticker": "AAA", "finance_source": "our", "as_of_date": date(2026, 6, 1)},
            {"ticker": "AAA", "finance_source": "yahoo", "as_of_date": date(2026, 6, 1)},
        ]
    )
    latest = _latest_snapshot(
        frame, key_columns=("ticker", "finance_source")
    )
    assert set(latest["finance_source"]) == {"our", "yahoo"}
    assert len(latest.index) == 2

    duplicate = pd.concat([frame, frame.iloc[[1]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate rows at the same authoritative date"):
        _latest_snapshot(duplicate, key_columns=("ticker", "finance_source"))


def test_latest_snapshot_validates_requested_keys_without_changing_empty_behavior():
    assert _latest_snapshot(pd.DataFrame()).empty
    with pytest.raises(ValueError, match="missing requested key columns: finance_source"):
        _latest_snapshot(
            pd.DataFrame([{"ticker": "AAA", "as_of_date": date(2026, 6, 1)}]),
            key_columns=("ticker", "finance_source"),
        )


def test_persist_tool_d_rejects_a_half_keyed_generation_before_writing(tmp_path):
    paths = build_test_paths(tmp_path)
    run_context = RunContext.start(
        paths=paths,
        command="tool-d",
        parameters={"gold_price": 3000},
        config_hash="hash",
    )
    outputs = pd.DataFrame(
        [_tool_d_row("AAA", "our", date(2026, 6, 1), 90.0)],
        columns=TOOL_D_OUTPUT_COLUMNS,
    )

    with pytest.raises(ValueError, match=r"missing expected .*\(AAA, yahoo\)"):
        persist_tool_d_outputs(
            paths=paths,
            run_context=run_context,
            tool_d_outputs=outputs,
            expected_tickers=["AAA"],
        )

    assert not list(paths.output_tool_d_dir.glob("tool_d_*"))
