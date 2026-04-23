from __future__ import annotations

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import run_workspace
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from tests.helpers import build_test_paths


class _LoadedConfigStub:
    def __init__(self, app: object, combined_hash: str) -> None:
        self.app = app
        self.combined_hash = combined_hash


def test_run_workspace_fails_cleanly_when_manual_store_is_missing(tmp_path, monkeypatch, capsys):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )

    called = {"server": False}

    def fake_run_workspace_server(*, paths, app_config, tool_b_tickers, host, port):
        called["server"] = True
        return 0

    monkeypatch.setattr(
        "golden_vector.cli.run_workspace_server",
        fake_run_workspace_server,
    )

    exit_code = run_workspace(paths, host="127.0.0.1", port=8765)

    assert exit_code == 1
    assert called["server"] is False
    assert not paths.manual_screening_store_path.exists()
    captured = capsys.readouterr()
    assert "manual-data init" in captured.out


def test_run_workspace_starts_when_manual_store_exists(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )

    tool_b_tickers = [
        ticker.ticker
        for ticker in real_loaded.universe.tickers
        if ticker.active and ticker.tool_b_enabled
    ]
    bootstrap_manual_screening_data(paths, tickers=tool_b_tickers)

    def fake_run_workspace_server(*, paths, app_config, tool_b_tickers, host, port):
        captured["paths"] = paths
        captured["app_config"] = app_config
        captured["tool_b_tickers"] = tool_b_tickers
        captured["host"] = host
        captured["port"] = port
        return 0

    monkeypatch.setattr(
        "golden_vector.cli.run_workspace_server",
        fake_run_workspace_server,
    )

    exit_code = run_workspace(paths, host="127.0.0.1", port=8765)

    assert exit_code == 0
    assert paths.manual_screening_store_path.exists()
    assert captured["app_config"] is real_loaded
    assert captured["tool_b_tickers"]
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8765
