from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from golden_vector.app.config import load_app_config
from golden_vector.app.latest_successful_refresh import load_latest_successful_model_refresh
from golden_vector.serve.data_status import build_data_status
from golden_vector.serve.option_refresh import OptionRefreshStatus, write_option_refresh_status
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths, call_wsgi_app


def _write_model_state(
    paths,
    *,
    generated_at: str,
    state: str = "complete",
    full_refresh_completed_at: str | None = None,
    include_full_refresh_field: bool = False,
):
    paths.latest_model_state_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest_version": 1,
        "manifest_readable": True,
        "state": state,
        "generated_at_utc": generated_at,
        "parent_refresh_id": "refresh-1",
    }
    if full_refresh_completed_at is not None or include_full_refresh_field:
        payload["full_refresh_completed_at_utc"] = full_refresh_completed_at
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_data_status_uses_latest_complete_manifest_and_newer_failed_attempt(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_model_state(paths, generated_at="2026-08-11T20:00:00Z")
    write_option_refresh_status(
        paths,
        OptionRefreshStatus(
            status="failed",
            job_id="job-2",
            started_at="2026-08-12T20:00:00Z",
            finished_at="2026-08-12T20:05:00Z",
        ),
    )

    status = build_data_status(paths, now=datetime(2026, 8, 12, 21, 0, tzinfo=UTC))

    assert status.status == "failed"
    assert status.tone == "warning"
    assert status.last_successful_refresh_at_utc == "2026-08-11T20:00:00Z"
    assert status.text == "Updated Aug 11, 4:00 PM ET · latest refresh failed"


def test_data_status_running_text_keeps_the_dates_own_casing(tmp_path):
    """Only the lead-in word is lowercased.

    Regression: ``label.lower()`` mangled the whole label into
    "updated aug 11, 4:00 pm et" -- month name and timezone included.
    """

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_model_state(paths, generated_at="2026-08-11T20:00:00Z")
    write_option_refresh_status(
        paths,
        OptionRefreshStatus(
            status="running",
            job_id="job-3",
            process_id=None,
            started_at="2026-08-12T20:00:00Z",
        ),
    )

    status = build_data_status(paths, now=datetime(2026, 8, 12, 20, 1, tzinfo=UTC))

    assert status.status == "running"
    assert status.text == "Refreshing · updated Aug 11, 4:00 PM ET"


def test_data_status_marks_two_trading_day_old_data_stale(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_model_state(paths, generated_at="2026-08-07T21:00:00Z")  # Friday, 17:00 ET

    status = build_data_status(paths, now=datetime(2026, 8, 11, 21, 0, tzinfo=UTC))

    assert status.status == "stale"
    assert status.age_trading_days == 2
    assert status.text.endswith("data may be stale")


def test_latest_success_uses_full_refresh_time_not_later_republish_time(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_model_state(
        paths,
        generated_at="2026-08-12T20:00:00Z",
        full_refresh_completed_at="2026-08-11T20:00:00Z",
    )

    latest = load_latest_successful_model_refresh(paths)

    assert latest is not None
    assert latest.generated_at_utc == "2026-08-11T20:00:00Z"
    assert latest.parent_refresh_id == "refresh-1"


def test_new_non_refresh_publication_without_prior_refresh_is_not_success(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_model_state(
        paths,
        generated_at="2026-08-12T20:00:00Z",
        full_refresh_completed_at=None,
        include_full_refresh_field=True,
    )

    assert load_latest_successful_model_refresh(paths) is None


def _count_retained_scans(monkeypatch) -> list[str]:
    """Record every directory scan of the retained model-state manifests."""

    scans: list[str] = []
    original = Path.glob

    def counting_glob(self, pattern, *args, **kwargs):
        scans.append(pattern)
        return original(self, pattern, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", counting_glob)
    return scans


def test_a_complete_pointer_never_scans_the_retained_manifests(tmp_path, monkeypatch):
    """/api/data-status polls this every 60s per tab on a single-threaded server.

    Reading every retained manifest on each poll measured 1.8s at 400 files, so
    a complete, dated pointer must answer without touching the directory at all.
    """

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_model_state(
        paths,
        generated_at="2026-08-12T20:00:00Z",
        full_refresh_completed_at="2026-08-12T20:00:00Z",
    )
    for index in range(25):
        (paths.model_state_manifests_dir / f"model_state_old-{index}.json").write_text(
            json.dumps(
                {
                    "manifest_readable": True,
                    "state": "complete",
                    "generated_at_utc": "2026-08-01T20:00:00Z",
                    "parent_refresh_id": f"old-{index}",
                }
            ),
            encoding="utf-8",
        )
    scans = _count_retained_scans(monkeypatch)

    latest = load_latest_successful_model_refresh(paths)

    assert latest is not None
    assert latest.parent_refresh_id == "refresh-1"
    assert scans == []


def test_an_incomplete_pointer_still_scans_and_finds_the_last_good_manifest(
    tmp_path, monkeypatch
):
    """The healthy control for the fast path: the fallback still runs."""

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_model_state(
        paths,
        generated_at="2026-08-12T20:00:00Z",
        state="incomplete",
    )
    (paths.model_state_manifests_dir / "model_state_refresh-good.json").write_text(
        json.dumps(
            {
                "manifest_readable": True,
                "state": "complete",
                "generated_at_utc": "2026-08-11T20:00:00Z",
                "parent_refresh_id": "refresh-good",
            }
        ),
        encoding="utf-8",
    )
    scans = _count_retained_scans(monkeypatch)

    latest = load_latest_successful_model_refresh(paths)

    assert latest is not None
    assert latest.parent_refresh_id == "refresh-good"
    assert scans == ["model_state_*.json"]


def test_latest_success_falls_back_to_retained_complete_manifest(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_model_state(
        paths,
        generated_at="2026-08-12T20:00:00Z",
        state="incomplete",
    )
    retained = paths.model_state_manifests_dir / "model_state_refresh-good.json"
    retained.write_text(
        json.dumps(
            {
                "manifest_readable": True,
                "state": "complete",
                "generated_at_utc": "2026-08-11T20:00:00Z",
                "parent_refresh_id": "refresh-good",
            }
        ),
        encoding="utf-8",
    )
    (paths.model_state_manifests_dir / "model_state_corrupt.json").write_text(
        "{bad",
        encoding="utf-8",
    )

    latest = load_latest_successful_model_refresh(paths)

    assert latest is not None
    assert latest.parent_refresh_id == "refresh-good"
    assert latest.source_path == retained


def test_older_failed_attempt_does_not_override_newer_success(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_model_state(paths, generated_at="2026-08-12T20:00:00Z")
    write_option_refresh_status(
        paths,
        OptionRefreshStatus(
            status="failed",
            job_id="old-job",
            finished_at="2026-08-11T20:00:00Z",
        ),
    )

    status = build_data_status(paths, now=datetime(2026, 8, 12, 20, 30, tzinfo=UTC))

    assert status.status == "current"
    assert "failed" not in status.text


def test_data_status_endpoint_is_read_only_json_no_store(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_model_state(paths, generated_at="2026-08-12T20:00:00Z")
    app = create_workspace_app(
        paths,
        app_config=load_app_config(paths).app,
        tool_b_tickers=[],
    )

    response = call_wsgi_app(app, method="GET", path="/api/data-status")
    payload = json.loads(response["body"])

    assert response["status"] == "200 OK"
    assert response["headers"]["Content-Type"] == "application/json; charset=utf-8"
    assert response["headers"]["Cache-Control"] == "no-store"
    assert payload["schema_version"] == 1
    assert payload["text"].startswith("Updated Aug 12")


def test_shell_contains_one_discreet_global_status_placeholder(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app = create_workspace_app(
        paths,
        app_config=load_app_config(paths).app,
        tool_b_tickers=[],
    )
    response = call_wsgi_app(app, method="GET", path="/favicon.ico")
    assert response["status"] == "204 No Content"

    from golden_vector.serve.ui.shell import _page_shell

    html = _page_shell("Test", "<p>body</p>")
    assert html.count('data-data-status-endpoint="/api/data-status"') == 1
    assert 'aria-live="polite"' in html


def test_shell_javascript_loads_display_ready_data_status():
    script = r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const status = {
  attrs: { "data-data-status-endpoint": "/api/data-status" },
  textContent: "Checking data",
  getAttribute(name) { return this.attrs[name] || null; },
  setAttribute(name, value) { this.attrs[name] = String(value); },
};
const document = {
  readyState: "complete",
  activeElement: null,
  querySelector(selector) {
    return selector === "[data-data-status-endpoint]" ? status : null;
  },
  querySelectorAll() { return []; },
  getElementById() { return null; },
  addEventListener() {},
};
let request = null;
const window = {
  location: { hash: "" },
  fetch(endpoint, options) {
    request = { endpoint, options };
    return Promise.resolve({
      ok: true,
      json() { return Promise.resolve({ text: "Updated Aug 12, 4:00 PM ET", tone: "ok" }); },
    });
  },
  addEventListener() {},
  setInterval() {},
  requestAnimationFrame(callback) { callback(); },
};
vm.runInNewContext(
  fs.readFileSync("golden_vector/serve/static/workspace-shell.js", "utf8"),
  { document, window, console, Promise }
);
setImmediate(() => {
  assert.equal(request.endpoint, "/api/data-status");
  assert.equal(request.options.cache, "no-store");
  assert.equal(status.textContent, "Updated Aug 12, 4:00 PM ET");
  assert.equal(status.attrs["data-tone"], "ok");
});
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
