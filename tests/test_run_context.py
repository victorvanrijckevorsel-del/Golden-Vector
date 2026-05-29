import json
from datetime import date

from golden_vector.app.run_context import RunContext
from tests.helpers import build_test_paths


def test_run_context_writes_metadata_and_artifacts(tmp_path):
    paths = build_test_paths(tmp_path)
    context = RunContext.start(
        paths=paths,
        command="foundation",
        parameters={"dry_run": True},
        config_hash="abc123",
    )

    context.write_json("config_summary.json", {"tickers": 8})
    context.finalize(status="PASS", summary={"tickers": 8}, notes=["ok"])

    metadata = json.loads(context.metadata_path.read_text(encoding="utf-8"))
    assert metadata["run_id"] == context.run_id
    assert metadata["status"] == "PASS"
    assert metadata["summary"]["tickers"] == 8
    assert f"data/runs/{context.run_id}/config_summary.json" in metadata["artifacts"]


def test_run_context_start_writes_replay_manifest(tmp_path):
    paths = build_test_paths(tmp_path)

    context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={"fixture": True},
        config_hash="abc123",
    )

    manifest_path = context.run_dir / "replay_manifest.json"
    metadata = json.loads(context.metadata_path.read_text(encoding="utf-8"))

    assert manifest_path.exists()
    assert f"data/runs/{context.run_id}/replay_manifest.json" in metadata["artifacts"]


def test_run_context_serializes_dates_in_artifacts(tmp_path):
    paths = build_test_paths(tmp_path)
    context = RunContext.start(
        paths=paths,
        command="manual-data-show",
        parameters={},
        config_hash="abc123",
    )

    context.write_json(
        "manual_data_show.json",
        {"ticker": "NEM", "next_financial_report_date": date(2026, 5, 1)},
    )
    payload = json.loads((context.run_dir / "manual_data_show.json").read_text(encoding="utf-8"))

    assert payload["next_financial_report_date"] == "2026-05-01"
