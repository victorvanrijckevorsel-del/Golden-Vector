from __future__ import annotations

import io
import json

from golden_vector.app.config import load_app_config
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.serve.option_refresh import (
    OptionRefreshStatus,
    complete_options_refresh,
    option_refresh_status_path,
    read_option_refresh_status,
    start_options_refresh,
    write_option_refresh_status,
)
from golden_vector.serve.option_trading_data import clear_option_trading_cache
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths
from tests.test_option_trading_data import _write_option_inputs


def test_option_refresh_status_defaults_idle(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()

    status = read_option_refresh_status(paths)

    assert status.status == "idle"
    assert not status.is_running


def test_option_refresh_status_recovers_stale_running_process(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    write_option_refresh_status(
        paths,
        OptionRefreshStatus(
            status="running",
            job_id="job-1",
            process_id=12345,
            started_at="2026-06-04T10:00:00Z",
            command=("python", "main.py", "update-data", "--options"),
        ),
    )

    status = read_option_refresh_status(paths, process_exists=lambda _pid: False)
    persisted = json.loads(option_refresh_status_path(paths).read_text(encoding="utf-8"))

    assert status.status == "failed"
    assert status.error_summary == "Refresh process is no longer running."
    assert persisted["status"] == "failed"


def test_option_refresh_status_handles_corrupt_json(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    option_refresh_status_path(paths).write_text("{not-json", encoding="utf-8")

    status = read_option_refresh_status(paths)

    assert status.status == "unknown"
    assert "Could not read refresh status" in str(status.error_summary)


def test_start_options_refresh_spawns_runner_and_records_command(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    calls = []

    class FakeProcess:
        pid = 456

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    result = start_options_refresh(paths, popen_factory=fake_popen)

    assert result.started
    assert result.status.status == "running"
    assert result.status.process_id == 456
    assert result.status.command[-2:] == ("update-data", "--options")
    assert str(result.status.command[-3]).endswith("main.py")
    assert calls
    command, kwargs = calls[0]
    assert command[:3] == [
        result.status.command[0],
        "-m",
        "golden_vector.serve.option_refresh",
    ]
    assert kwargs["cwd"] == paths.repo_root


def test_start_options_refresh_blocks_duplicate_running_job(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    write_option_refresh_status(
        paths,
        OptionRefreshStatus(status="running", job_id="job-1", process_id=456),
    )

    result = start_options_refresh(
        paths,
        process_exists=lambda _pid: True,
        popen_factory=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()),
    )

    assert not result.started
    assert result.already_running
    assert result.status.job_id == "job-1"


def test_complete_options_refresh_records_latest_options_run_id(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    write_option_refresh_status(
        paths,
        OptionRefreshStatus(
            status="running",
            job_id="job-1",
            process_id=456,
            started_at="2026-06-04T10:00:00Z",
            command=("python", "main.py", "update-data", "--options"),
        ),
    )
    paths.latest_options_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_options_manifest_path.write_text(
        json.dumps({"refresh_run_id": "options-run"}),
        encoding="utf-8",
    )

    status = complete_options_refresh(paths, job_id="job-1", return_code=0)

    assert status.status == "succeeded"
    assert status.latest_run_id == "options-run"
    assert status.error_summary is None


def test_complete_options_refresh_does_not_clobber_newer_job(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    write_option_refresh_status(
        paths,
        OptionRefreshStatus(
            status="running",
            job_id="newer-job",
            process_id=789,
            started_at="2026-06-04T10:01:00Z",
        ),
    )

    status = complete_options_refresh(
        paths,
        job_id="older-job",
        return_code=0,
    )
    persisted = json.loads(option_refresh_status_path(paths).read_text(encoding="utf-8"))

    assert status.job_id == "newer-job"
    assert status.status == "running"
    assert persisted["job_id"] == "newer-job"
    assert persisted["status"] == "running"


def test_option_refresh_route_starts_job_and_returns_to_detail(tmp_path, monkeypatch):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    calls = []

    def fake_start_options_refresh(received_paths):
        calls.append(received_paths)

    monkeypatch.setattr(
        "golden_vector.serve.workspace.start_options_refresh",
        fake_start_options_refresh,
    )
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/option-trading/refresh",
        body="return_to=/ticker/AEM?lens=option-trading%23option-trading",
    )

    assert calls == [paths]
    assert response["status"].startswith("303")
    assert response["headers"]["Location"] == "/ticker/AEM?lens=option-trading#option-trading"


def test_option_refresh_route_rejects_external_return_to(tmp_path, monkeypatch):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    monkeypatch.setattr(
        "golden_vector.serve.workspace.start_options_refresh",
        lambda _paths: None,
    )
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])

    response = _call_wsgi_app(
        app,
        method="POST",
        path="/option-trading/refresh",
        body="return_to=https://example.com",
    )

    assert response["status"].startswith("303")
    assert response["headers"]["Location"] == "/option-trading"


def test_option_trading_overview_shows_refresh_status(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
    )
    write_option_refresh_status(
        paths,
        OptionRefreshStatus(
            status="running",
            job_id="job-1",
            started_at="2026-06-04T10:00:00Z",
        ),
    )

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["AEM"])
    response = _call_wsgi_app(app, method="GET", path="/option-trading")

    assert response["status"].startswith("200")
    assert "Model build state needs attention" in response["body"]
    assert "Refresh cached options data" in response["body"]
    assert "Options refresh running since 2026-06-04T10:00:00Z." in response["body"]


def _call_wsgi_app(app, *, method: str, path: str, body: str = "") -> dict[str, object]:
    payload = body.encode("utf-8")
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    if "?" in path:
        path_info, _, query_string = path.partition("?")
    else:
        path_info, query_string = path, ""

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path_info,
        "QUERY_STRING": query_string,
        "CONTENT_LENGTH": str(len(payload)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(payload),
        "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    body_bytes = b"".join(app(environ, start_response))
    return {
        "status": captured["status"],
        "headers": dict(captured["headers"]),
        "body": body_bytes.decode("utf-8"),
    }
