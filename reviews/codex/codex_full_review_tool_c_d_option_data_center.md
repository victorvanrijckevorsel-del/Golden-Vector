# Full Codex Review - Tool C/D, Option Trading, Candidate Finder, and Data-Center Architecture

Grade: NEEDS CHANGES

Date: 2026-06-05
Reviewer: Codex
Scope: read-only review of the committed codebase, with focus on Tool C, Tool D, Candidate Finder wiring, Option Trading UI data flow, performance, centralization of computation, replay/provenance, and test coverage. Source code was not changed.

## Executive Summary

The test suite is green, but the current architecture is not ready as a fast, reliable user-facing workflow. The biggest issue is not a syntax bug: option-chain analytics are still computed at UI request time. On the current cached local data, a true cold `/option-trading` load spent about 19.8 seconds building option data for 60 chains and 7,097 contracts. A true cold Candidate Finder load took about 7.3 seconds because it also calls the option-trading loader. Warm in-process cache is fast, but the first page hit after server start, cache clear, or source change is doing model work that belongs in the refresh/pipeline layer.

There are also correctness/contract gaps: Tool C carries GDXJ returns but does not use GDXJ downstream or emit the locked per-benchmark week-count contract; Tool D's rank directions are hard-coded instead of config-pinned; a manual non-spot `tool-d --gold-price` run can overwrite the stable latest Tool D file and make Candidate Finder lose its Tool D criterion; thin Tool C tail metrics are output but not tagged as thin history. These are not caught by the current tests.

## Findings

### P1 - Option Trading and Candidate Finder still do heavy computation inside UI request paths

`golden_vector/serve/workspace.py:188` calls `load_option_trading_data()` for `/option-trading`, `golden_vector/serve/workspace.py:202` calls `load_candidate_finder_data()` for `/candidate-finder`, and `golden_vector/serve/workspace.py:265` calls `load_option_trading_data()` again for option ticker detail. Inside `golden_vector/serve/option_trading_data.py:329`, the loader reads latest parquet inputs, loads every cached chain, builds put slots at `golden_vector/serve/option_trading_data.py:356`, builds call slots at `golden_vector/serve/option_trading_data.py:367`, and separately computes liquidity measurements at `golden_vector/serve/option_trading_data.py:387`. Each slot pass calls `build_bucket_slots()`, which calls `scan_option_chain()` at `golden_vector/hedge/options_liquidity.py:216`; scanning adds Black-Scholes deltas at `golden_vector/hedge/options_liquidity.py:189` and iterates rows at `golden_vector/hedge/options_liquidity.py:207`. Liquidity measurement scans chains again via `scan_option_chain()` at `golden_vector/serve/option_trading_data.py:665`. Timing probe on current local cached data: option true cold load 19.797s, option warm load 0.026s, Candidate Finder true cold load 7.269s, 60 chains, 7,097 contracts, 132 put slots, 132 call slots. This should move to a refresh-time/pipeline artifact. The UI should read persisted option-contract metrics, candidate slots, option overview rows, and Candidate Finder input frames, not recompute them.

### P1 - A non-spot Tool D run can overwrite the latest file that Candidate Finder depends on

The locked rule says Candidate Finder consumes spot Tool D only. The reader defends that: `golden_vector/serve/candidate_finder_data.py:116` reads `latest_tool_d_snapshot_parquet_path`, `_spot_tool_d_source()` at `golden_vector/serve/candidate_finder_data.py:708` blanks `tool_d_quality_rank` when the latest file is not a spot run, and the regression test is at `tests/test_candidate_finder_data.py:185`. But the writer side still publishes every Tool D run to the stable latest alias: `golden_vector/cli.py:1235` allows `resolved_gold_price` to be any CLI value, and `golden_vector/cli.py:1267` calls `persist_tool_d_outputs(..., publish_latest_aliases=not tool_d_outputs.empty)` regardless of whether that run used spot. So if Emanuel runs `python main.py tool-d --gold-price 3000`, `tool_d_latest.parquet` becomes non-spot, and Candidate Finder correctly refuses to use it. The practical effect is that a valid stress run can break the Finder's Tool D criterion until a spot Tool D run is regenerated. Fix direction: persist separate aliases for spot and scenario Tool D outputs, or publish the Finder-consumed alias only when `gold_price_used == spot_gold_usd`.

### P1 - Tool C does not fully meet the locked GDX/GDXJ and per-benchmark count contract

The build brief required `weekly_returns` to emit gold/GDX/GDXJ returns plus per-benchmark intersection counts, and downstream metrics should use each benchmark's own count. `golden_vector/features/weekly_returns.py:10` defines only `ticker`, `week_period`, `stock_log_ret`, `gold_log_ret`, `gdx_log_ret`, and `gdxj_log_ret`; there are no `n_weeks_gold`, `n_weeks_gdx`, or `n_weeks_gdxj` fields. `golden_vector/features/relative_behavior.py:7` defines only gold and GDX relative metrics. It never computes `rel_weakness_vs_gdxj_*` or `rel_strength_vs_gdxj_*`, even though `gdxj_log_ret` is present in the weekly frame. Tests currently assert GDXJ is joined in `tests/test_weekly_returns.py`, but `tests/test_relative_behavior.py` only checks GDX. This means Tool C is partly wired for GDXJ but does not actually use it in ranks or output counts, which weakens the intended junior-miner benchmark comparison.

### P2 - Tool D rank orientation is hard-coded instead of pinned in `tool_d.yaml`

`config/tool_d.yaml` currently contains only `version` and `max_reasonable_ev_ebitda`. `ToolDConfig` at `golden_vector/contracts/config_models.py:369` mirrors only that field. But the locked brief said the three component directions should be pinned in config. The implementation hard-codes them in `_add_quality_scores()` at `golden_vector/model/tool_d.py:233`: headroom uses `high_good=True` at `golden_vector/model/tool_d.py:238`, leverage uses `high_good=False` at `golden_vector/model/tool_d.py:242`, and EV/EBITDA uses `high_good=False` at `golden_vector/model/tool_d.py:246`. The math is currently correct, but the direction contract is not auditable from config and cannot be changed or validated centrally.

### P2 - Tool C thin-tail metrics are not tagged even though the plan says thin tails are flagged

Tool C outputs tail columns at `golden_vector/model/tool_c.py:40` through `golden_vector/model/tool_c.py:47`. The plan and brief explicitly require thin tails to be flagged and excluded. They are excluded from rank, but the tags do not inspect tail counts. `_downside_tags()` only passes relative and hit-rate fields into `_has_thin_history()` at `golden_vector/model/tool_c.py:269`; `_upside_tags()` does the same at `golden_vector/model/tool_c.py:297`. Tail fields such as `tail_avg_return_worst10pct_n` and `tail_avg_return_best10pct_n` are not included. Existing tests assert tail counts can be below `min_events` in `tests/test_relative_behavior.py:52`, and assert a thin relative metric creates `thin_history` in `tests/test_tool_c.py:90`, but there is no test that a thin tail creates a tag. This creates a misleading output: a ticker can have unusable tail context without the explanation warning the user.

### P2 - The option data cache key is too coarse for correctness and tuning

`OptionTradingCacheKey` at `golden_vector/serve/option_trading_data.py:50` contains only `options_refresh_run_id`, Tool A refresh IDs, and Tool B refresh IDs. `_cache_key()` at `golden_vector/serve/option_trading_data.py:465` does not include the options manifest hash, chain snapshot hashes, options feature hashes, risk-free rate, or the option-liquidity config values used by `settings_from_config()` at `golden_vector/serve/option_trading_data.py:552` and `golden_vector/serve/option_trading_data.py:639`. If a file is corrected under the same refresh ID, if the risk-free rate in the manifest changes, or if liquidity thresholds are changed while the server process stays alive, the UI can serve stale candidate slots until the process restarts or cache is manually cleared. Candidate Finder has a stronger hash-based cache key for Tool A/B/C/D latest files, but it delegates option booleans and features to this coarser option cache.

### P2 - Option-selection rules are only partly centralized in config

The broad fields live in `HedgeReadinessConfig` starting at `golden_vector/contracts/config_models.py:91`, including `option_dte_bands` at `golden_vector/contracts/config_models.py:117`. But the newer selection behavior is hard-coded as defaults in `OptionLiquiditySettings`: near-ATM OTM range at `golden_vector/hedge/options_liquidity.py:76`, directional preferred OTM range at `golden_vector/hedge/options_liquidity.py:78`, strict near-ATM spread/OI/mid thresholds at `golden_vector/hedge/options_liquidity.py:82`, and directional strict thresholds at `golden_vector/hedge/options_liquidity.py:88`. `settings_from_config()` at `golden_vector/hedge/options_liquidity.py:152` maps only a subset of config fields and leaves these tuning values in code. This is exactly the area Emanuel has been iterating on in product discussion, so it should be centrally tunable and replay-captured, not buried in Python defaults.

### P2 - Replay verification appears to conflate immutable replay snapshots with mutable current source files

Tool C/D source snapshots are copied into the run at `_update_manifest_with_named_sources()` starting `golden_vector/app/replay_manifest.py:673`, with `snapshot_path` and `sha256` recorded at `golden_vector/app/replay_manifest.py:696`. `verify_manifest()` first validates those copied snapshots at `golden_vector/app/replay_manifest.py:270`, which is correct. It then loops over `_manifest_source_assets()` at `golden_vector/app/replay_manifest.py:284`, and `_manifest_source_assets()` includes Tool C/D source assets again at `golden_vector/app/replay_manifest.py:482` and `golden_vector/app/replay_manifest.py:484`. `_verify_source_asset()` at `golden_vector/app/replay_manifest.py:426` checks the mutable original path against the captured hash and contributes failures to the main verdict. That means an intact replay snapshot can be marked failed after the live `latest` file moves on. Current persistence tests only call `verify_manifest()` immediately after writing (`tests/test_persist_tool_c.py:50`, `tests/test_persist_tool_d.py:56`), so they do not cover the normal later state where latest files have changed. Drift against current files should be reported as drift, not snapshot-integrity failure.

### P3 - Ticker detail still performs some analytics at request time

This is much smaller than the option-chain issue, but it points in the same architectural direction. `_load_tool_a_detail()` at `golden_vector/serve/workspace_state.py:110` now reads published structural metrics, which is good, but it still loads the latest foundation snapshot with equity/gold history and builds weekly series plus latest horizon returns inside the request. The comments explain this was optimized from a worse state, but if the goal is a central computation/data center, detail pages should eventually read published per-ticker detail artifacts too. This is not blocking, but it is the same pattern to remove over time.

## Centralized Computation / Data-Center Recommendation

The practical target should be: refresh commands do computation; UI routes only read small, already-published artifacts and render HTML. I would not solve this by adding more request caches. The caches hide the issue after the first hit, but the first user hit is still slow and the cache keys become increasingly fragile.

Recommended staged architecture:

1. Add an option analytics publish step after `update-data --options`.
   - Read raw option chains once.
   - Normalize and delta-price once.
   - Persist `option_contract_metrics_latest.parquet`: one row per contract with DTE, strike, side, bid/ask/mid, IV, delta, relative spread, OI, volume, liquidity tier, quote flags, near-spot depth, and provenance.
   - Persist `option_candidate_slots_latest.parquet`: one row per ticker/side/horizon/bucket with accepted/rejected status, candidate fields, score, and reason.
   - Persist `option_trading_overview_latest.parquet`: one row per ticker/vehicle for the overview table.

2. Make `load_option_trading_data()` a reader/adapter.
   - It should read the published option metrics/slots/overview artifacts and build dataclasses for the renderer.
   - It should not call `scan_option_chain()` in the UI path.
   - It should not iterate all raw contracts on page request.

3. Add a Candidate Finder input artifact.
   - Persist `candidate_finder_input_latest.parquet`, joining Tool A/B/C/D latest, manual ratios, option availability booleans, and source context.
   - Candidate Finder then ranks from this one frame instead of calling `load_option_trading_data()`.

4. Use artifact hashes and config hashes as freshness keys.
   - Cache keys should include the hash or mtime/signature of the published input artifacts plus config hash.
   - Cache should be a speed optimization, not the only protection against stale inputs.

5. Separate Tool D spot and scenario outputs.
   - Keep `tool_d_latest_spot.parquet` for Candidate Finder.
   - Keep scenario outputs retained by run ID and optionally a separate `tool_d_latest_scenario.parquet`.
   - Do not let an exploratory gold-price run overwrite the spot artifact consumed by Finder.

6. Keep raw chains for audit, not rendering.
   - Raw option snapshots are still valuable for replay and inspection.
   - They should not be the primary UI serving data.

## Verification Performed

- `python -m compileall golden_vector`
  - Result: passed.
- `python -m pytest`
  - Result: 674 passed in 168.22s.
- Lint/type tooling:
  - No project config files found for `pyproject.toml`, `setup.cfg`, `tox.ini`, `mypy.ini`, or `.ruff.toml`.
  - `python -m ruff --version`: module not installed.
  - `python -m mypy --version`: module not installed.
  - `python -m pyright --version`: module not installed.
- Performance probe, read-only against current local cached data:
  - Option Trading true cold load: 19.797s.
  - Option Trading warm load: 0.026s.
  - Candidate Finder true cold load: 7.269s.
  - Loaded 60 option chains and 7,097 option contracts.

## Test Gaps To Add Before Fixing

- Tool C weekly-return contract includes `n_weeks_gold`, `n_weeks_gdx`, and `n_weeks_gdxj`.
- Tool C relative behavior computes and ranks/exports GDXJ-relative metrics or explicitly documents why GDXJ is context-only.
- Tool C thin-tail counts create `thin_history` tags.
- Tool D config contains component direction pins, and tests fail if model code ignores config.
- A non-spot `tool-d --gold-price` run does not overwrite the Finder-consumed spot latest artifact.
- Option Trading cache invalidates on manifest hash, risk-free rate, option-liquidity config, and chain/feature artifact changes.
- Replay verification remains OK when copied replay snapshots are intact but live original source files have since changed.
- UI loaders for `/option-trading` and `/candidate-finder` can render from persisted option/candidate artifacts without scanning raw chains.

## Bottom Line

The current code is directionally good and test-green, but it still mixes model computation with UI serving in the option layer. That is why the app can feel slow or "busy" even with cached data. The next improvement should not be another UI patch; it should be a data-center/published-artifact step that computes option metrics, candidate slots, and Candidate Finder input frames during refresh, with the UI reduced to fast reads and rendering.
