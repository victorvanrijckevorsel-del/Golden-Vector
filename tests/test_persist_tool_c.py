from datetime import date
import json

import pandas as pd

from golden_vector.app.replay_manifest import verify_manifest
from golden_vector.app.run_context import RunContext
from golden_vector.ingestion.persist_tool_c import persist_tool_c_outputs
from tests.helpers import build_test_paths


def test_persist_tool_c_outputs_writes_latest_and_source_snapshots(tmp_path):
    paths = build_test_paths(tmp_path)
    run_context = RunContext.start(
        paths=paths,
        command="tool-c",
        parameters={},
        config_hash="hash",
    )
    source_path = paths.output_tool_a_dir / "tool_a_latest.parquet"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"ticker": "AAA"}]).to_parquet(source_path, index=False)
    outputs = pd.DataFrame(
        [
            {"ticker": "AAA", "as_of_date": date(2026, 5, 1), "tool_c_downside_rank": 50.0},
            {"ticker": "AAA", "as_of_date": date(2026, 6, 1), "tool_c_downside_rank": 90.0},
            {"ticker": "BBB", "as_of_date": date(2026, 6, 1), "tool_c_downside_rank": 80.0},
        ]
    )

    written_paths = persist_tool_c_outputs(
        paths=paths,
        run_context=run_context,
        tool_c_outputs=outputs,
        source_paths={"tool_a_latest": source_path},
    )

    assert len(written_paths) == 8
    latest = pd.read_parquet(paths.latest_tool_c_snapshot_parquet_path)
    assert set(latest["ticker"]) == {"AAA", "BBB"}
    assert latest.loc[latest["ticker"] == "AAA", "as_of_date"].iloc[0] == date(2026, 6, 1)

    manifest = json.loads(
        (run_context.run_dir / "replay_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["tool_c_sources_status"] == "captured"
    asset = manifest["tool_c_sources_captured"]["source_assets"][0]
    assert asset["name"] == "tool_a_latest"
    assert (run_context.run_dir / asset["snapshot_path"]).exists()
    assert verify_manifest(run_context.run_dir).ok
