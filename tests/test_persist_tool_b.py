from datetime import date

import pandas as pd

from golden_vector.app.run_context import RunContext
from golden_vector.ingestion.persist import persist_tool_b_outputs
from tests.helpers import build_test_paths, tool_b_output_row


def test_persist_tool_b_outputs_writes_latest_snapshot_sorted_by_fundamental_rank(tmp_path):
    paths = build_test_paths(tmp_path)
    run_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 4000},
        config_hash="hash",
    )
    tool_b_outputs = pd.DataFrame(
        [
            tool_b_output_row("GOLD", as_of_date=date(2026, 1, 31), fundamental_check_rank=2),
            tool_b_output_row("NEM", as_of_date=date(2026, 1, 31), fundamental_check_rank=1),
            tool_b_output_row("NEM", as_of_date=date(2026, 2, 1), fundamental_check_rank=2),
            tool_b_output_row("GOLD", as_of_date=date(2026, 2, 1), fundamental_check_rank=1),
        ]
    )

    written_paths = persist_tool_b_outputs(
        paths=paths,
        run_context=run_context,
        tool_b_outputs=tool_b_outputs,
    )

    assert len(written_paths) == 7
    latest_csv_path = next(path for path in written_paths if path.name.endswith("latest_" + run_context.run_id + ".csv"))
    latest_csv = pd.read_csv(latest_csv_path)
    stable_latest = pd.read_parquet(paths.latest_tool_b_snapshot_parquet_path)

    assert list(latest_csv["ticker"]) == ["GOLD", "NEM"]
    assert list(stable_latest["ticker"]) == ["GOLD", "NEM"]


def test_persist_tool_b_outputs_can_preserve_previous_stable_latest_alias_on_empty_run(tmp_path):
    paths = build_test_paths(tmp_path)
    initial_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 4000},
        config_hash="hash",
    )
    persist_tool_b_outputs(
        paths=paths,
        run_context=initial_context,
        tool_b_outputs=pd.DataFrame(
            [
                tool_b_output_row(
                    "NEM",
                    as_of_date=date(2026, 2, 1),
                    fundamental_check_rank=1,
                )
            ]
        ),
    )

    empty_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 4000},
        config_hash="hash",
    )
    persist_tool_b_outputs(
        paths=paths,
        run_context=empty_context,
        tool_b_outputs=pd.DataFrame(
            columns=[
                "ticker",
                "as_of_date",
                "gold_price_assumption",
                "fundamental_check_rank",
            ]
        ),
        publish_latest_aliases=False,
    )

    stable_latest = pd.read_parquet(paths.latest_tool_b_snapshot_parquet_path)
    assert list(stable_latest["ticker"]) == ["NEM"]
