# Codex Holistic Review: Phase 3 Wiring

## Scope
- Shared backbone execution path
- Tool A Phase 3 horizon-return path
- Horizon comparison path
- QA and audit behavior around the new stage

## Findings And Fixes

### P1. Phase 3 logic existed, but `tool-a` was still a placeholder
- Why it mattered:
  The repo had horizon parsing and return code, but no executable Tool A path. That meant Phase 3 looked present in the codebase while still being unavailable from the CLI.
- Fix applied:
  Implemented a real `tool-a` command in [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py) and added [golden_vector/features/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/pipeline.py) to run core horizons, persist the long-format table, and write horizon QA.

### P1. Tickers disabled for both tools could still leak into the backbone
- Why it mattered:
  An active ticker with `tool_a_enabled: false` and `tool_b_enabled: false` had no product consumer, but the old registry still fetched and QA-checked it. That could create false failures and make tool independence weaker.
- Fix applied:
  Tightened [golden_vector/ingestion/registry.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/registry.py) so the shared backbone only plans data for active tickers that are enabled for Tool A or Tool B.

### P1. Horizon QA could crash on an empty DataFrame
- Why it mattered:
  `evaluate_horizon_quality()` accessed `horizon_metrics["ticker"]` even when the DataFrame was empty with no columns. That would turn a missing-output condition into an exception instead of a clean QA failure.
- Fix applied:
  Hardened [golden_vector/qa/horizon_quality.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/qa/horizon_quality.py) to normalize empty inputs before ticker-level checks.

### P2. Horizon QA could mark a ticker healthy even when zero rows were officially usable
- Why it mattered:
  Near-zero gold moves produce `PASS` rows that are intentionally not eligible for official scoring. The previous QA only counted `PASS`, so a ticker could appear healthy with zero officially eligible core rows.
- Fix applied:
  Horizon QA now reports both passing core rows and officially eligible core rows, and warns if eligibility is zero.

### P2. Run metadata pointed at mutable cache files with no immutable snapshot for the run
- Why it mattered:
  Static cache paths like `data/raw/equities/*.parquet` are overwritten by later runs. That weakens auditability because an old run can point to files whose contents changed later.
- Fix applied:
  Added immutable per-run snapshot files in [golden_vector/ingestion/persist.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/persist.py) for consolidated raw equities, raw FX, raw gold, and USD-normalized equities, while keeping the latest cache files as working data.

### P2. Flexible horizon support existed internally, but no usable comparison command exposed it
- Why it mattered:
  The user explicitly wants custom horizons and easy comparison. Without a CLI path, that flexibility remained hidden in helper code.
- Fix applied:
  Implemented `compare-horizons` in [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py), using config-validated custom horizons and exporting the comparison table to CSV.

## Test Coverage Added
- [tests/test_horizon_quality.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_horizon_quality.py)
- [tests/test_cli_tool_a.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_cli_tool_a.py)
- Added extra cases to:
  - [tests/test_horizons.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_horizons.py)
  - [tests/test_registry.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_registry.py)

## Residual Risks
- I still could not execute `pytest` or the CLI in this shell because there is no usable local Python launcher exposed here. The new tests and command paths are code-reviewed but not locally executed by me in this environment.
- The new `compare-horizons` command is implemented, but it still depends on live Yahoo fetch behavior through the shared backbone. It needs one real end-to-end run in the working Python environment.
- Tool A now finishes Phase 3, but Tool A metrics and ranking are still not built. That remains Phase 4.

## Verdict
- Phase 3 is now code-complete at the horizon-return layer:
  - shared backbone runs
  - Tool A horizon outputs run
  - horizon QA runs
  - custom horizon comparison runs
- The next constraint is execution verification, not missing architecture.
