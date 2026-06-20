# Codex Review - Auto-Fresh Fundamentals Refresh Wiring

Verdict: PASS after one P1 refresh-fallback fix.

## Findings

### P1 - Fixed - Refresh alias bypass could crash Tool B on an unreadable latest alias

- File: `golden_vector/fundamentals/artifacts.py:70`
- Evidence: `refresh` intentionally calls `run_tool_b(..., _use_model_state_inputs=False)`, which passes `prefer_latest_fundamentals_alias=True`. Before this review fix, `load_official_fundamentals(prefer_latest_alias=True)` selected `fetched_fundamentals_latest.parquet` whenever it existed, then performed a required read. If the freshness guard was due because that alias was unreadable, and the optional fetch failed or was publish-blocked, Tool B would still try to read the unreadable alias and fail the refresh, despite a last-good official fundamentals artifact being available through the model-state manifest.
- Impact: this violated the intended optional-failure behavior: a fundamentals fetch failure should leave published state intact and allow refresh to continue on last-good fundamentals/manual data.
- Fix applied: the alias bypass now means "prefer a valid latest alias." It first tries the alias, then falls back to the manifest-resolved immutable artifact if the alias read/validation fails; if no published artifact exists, it returns the empty optional fundamentals frame. Regression coverage added at `tests/test_fundamentals_artifact_contract.py:201`.

## Property Audit

- All-or-nothing publish: `run_fetch_fundamentals(..., publish_model_state=False)` sets summary state to `deferred_to_caller` and does not call `write_current_model_state_manifest`; the full refresh branch still publishes once at the end with `option_publish_block`.
- No HIGH-2 option carry-forward regression found: the fetch step records timing but does not promote model state before option artifacts; carried-forward/blocking state is still handled only in the final manifest publish.
- Alias routing: `run_tool_b` passes `prefer_latest_fundamentals_alias=not _use_model_state_inputs`, so standalone defaults to manifest, while refresh bypass reads the fresh alias if valid.
- Serve routing: `overview_tool_b.py` and `candidate_finder_data.py` still call `load_official_fundamentals(paths)` with the default `prefer_latest_alias=False`; no alias-mode leak found.
- Freshness guard: missing alias, unreadable parquet, missing `fetched_at_utc`, and all-NaT resolve due; timestamp parsing uses `utc=True`; threshold comes from `app_config.fundamentals.refresh_fetch_max_age_days`.

## Lab Parity

- Tool A per-ticker-week reconstruction is sound: Tool A cores are per-ticker outputs at each ticker's own latest as-of week, not cross-sectional percentiles.
- Tool C skip is acceptable for the current test shape: Tool C scores are cross-sectional percentiles, and the existing reconstruction API takes one W-FRI period. A mixed-week live artifact needs a separate mixed-cross-section reconstruction helper to reproduce exactly. The single-week parity check should skip rather than pretend it proves parity on a mixed-week universe.

## Verification

- `python -m pytest tests/test_fundamentals_artifact_contract.py tests/test_cli_refresh_and_status.py::test_fundamentals_due_for_refresh_guard tests/test_cli_refresh_and_status.py::test_refresh_runs_guarded_fundamentals_step_before_tool_b tests/test_cli_tool_b.py::test_run_tool_b_defaults_to_latest_gold_close tests/test_cli_tool_b.py::test_run_tool_b_reads_fresh_fundamentals_alias_when_bypassing_model_state tests/test_config_models.py::test_fundamentals_config_refresh_fetch_max_age_days_defaults_and_validates` - 21 passed.
- `python -m pytest tests/test_cli_refresh_and_status.py tests/test_cli_tool_b.py tests/test_fundamentals_artifact_contract.py tests/test_fundamentals_fetch.py tests/test_config_models.py::test_fundamentals_config_refresh_fetch_max_age_days_defaults_and_validates tests/test_option_carry_forward.py` - 85 passed.
- `python -m pytest tests/test_candidate_finder_data.py tests/test_candidate_finder_page.py` - 42 passed.
- `python -m pytest tests/test_workspace_app.py -k "tool_b or tool-b or Corporate or override or candidate"` - 19 passed.
- `python -m pytest tests/test_lab_validation.py` - 23 passed, 1 skipped.
- `git diff --check` - no whitespace errors; Git reported only CRLF conversion warnings for edited files.
- `venv\Scripts\python.exe -m ruff check golden_vector/fundamentals/artifacts.py tests/test_fundamentals_artifact_contract.py golden_vector/cli.py golden_vector/screening/pipeline.py tests/test_cli_refresh_and_status.py tests/test_cli_tool_b.py` - all checks passed.
