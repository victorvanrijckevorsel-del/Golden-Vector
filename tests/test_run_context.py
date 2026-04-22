import json

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
