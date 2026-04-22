from datetime import date

import pandas as pd

from golden_vector.app.run_context import RunContext
from golden_vector.ingestion.persist import persist_tool_a_outputs
from tests.helpers import build_test_paths


def test_persist_tool_a_outputs_writes_full_and_latest_exports(tmp_path):
    paths = build_test_paths(tmp_path)
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="hash",
    )
    tool_a_outputs = pd.DataFrame(
        [
            {"ticker": "GOLD", "as_of_date": date(2026, 1, 31), "tool_a_rank": 2},
            {"ticker": "NEM", "as_of_date": date(2026, 1, 31), "tool_a_rank": 1},
            {"ticker": "NEM", "as_of_date": date(2026, 2, 1), "tool_a_rank": 2},
            {"ticker": "GOLD", "as_of_date": date(2026, 2, 1), "tool_a_rank": 1},
        ]
    )

    written_paths = persist_tool_a_outputs(
        paths=paths,
        run_context=run_context,
        tool_a_outputs=tool_a_outputs,
    )

    assert len(written_paths) == 7
    latest_csv_path = next(path for path in written_paths if path.name.endswith("latest_" + run_context.run_id + ".csv"))
    latest_parquet_path = next(path for path in written_paths if path.name.endswith("latest_" + run_context.run_id + ".parquet"))
    latest_csv = pd.read_csv(latest_csv_path)
    latest_parquet = pd.read_parquet(latest_parquet_path)
    stable_latest = pd.read_parquet(paths.latest_tool_a_snapshot_parquet_path)

    assert list(latest_csv["ticker"]) == ["GOLD", "NEM"]
    assert len(latest_csv.index) == 2
    assert len(latest_parquet.index) == 2
    assert list(stable_latest["ticker"]) == ["GOLD", "NEM"]
