# Codex Options Liquidity Lab Progress

## 2026-06-03 - Phase 1

Review decision: v3 is sound for Phase 1. The prior blockers are resolved by moving GDX/GDXJ option-chain ingestion to Phase 2 and moving portfolio context/hedge sizing out of this brief.

Implemented:
- Added config-driven option liquidity thresholds and DTE bands.
- Added pure `options_liquidity` scanner with Tradable / Watch / No-trade tiers, spread-dominant score, bucket selection, standard-monthly preference, and the shared `is_usable_candidate()` primitive.
- Rewired Option Trading data loading to build bucket slots per side and horizon from cached chains.
- Cleaned the overview to the Phase 1 stopgap columns only.
- Replaced the wide detail candidate table with bucket/horizon rows, visible tier labels, spread and half-spread cost, Yahoo expiry links, and Select links only for usable contracts.
- Moved scenario output into the selected-contract sizing calculator.
- Added read-only `options-liquidity-summary` CLI over cached data.

Self-review notes:
- Invalid bid/ask/mid quotes are No-trade and never scored as usable.
- Wide spreads remain visible as Watch/No-trade near-misses where useful, but are not selectable.
- A far OTM AEM-style strike-50 put on a $175 stock is not accepted as a normal suggestion.
- Slot-level liquidity counts now count rejected far-OTM/invalid buckets as No-trade instead of inflating Tradable totals.
- Bucket tie-breaking now prefers the listed expiry closest to the named horizon inside the configured DTE band.
- Overview notes no longer mention hidden 60d scenario P&L when the Phase 1 table is only screening contract availability.
- Refresh remains a disabled placeholder; no live Yahoo fetch is implied by the UI.
- No portfolio hedge sizing or GDX/GDXJ option-chain ingestion was added in Phase 1.

Checks so far:
- `python -m pytest tests/test_option_trading_data.py tests/test_option_trading_overview.py tests/test_option_trading_detail_panel.py tests/test_option_trading_routes.py tests/test_hedge_modules.py tests/test_config_models.py -q` -> 95 passed baseline before edits.
- `python -m pytest tests/test_options_liquidity.py tests/test_options_liquidity_cli.py tests/test_config_models.py tests/test_option_trading_data.py tests/test_option_trading_overview.py tests/test_option_trading_detail_panel.py tests/test_option_trading_routes.py -q` -> 98 passed after Phase 1 edits.
- `python -m pytest tests/test_options_liquidity.py tests/test_options_liquidity_cli.py tests/test_config_models.py tests/test_hedge_modules.py tests/test_hedge_data_contracts.py tests/test_scenarios.py tests/test_option_trading_data.py tests/test_option_trading_overview.py tests/test_option_trading_detail_panel.py tests/test_option_trading_routes.py tests/test_speculation_section.py tests/test_sensitivity_ranking.py tests/test_comparison.py -q` -> 155 passed.
- `python -m pytest -q` -> 583 passed.
- `python -m pytest tests/test_options_liquidity.py tests/test_options_liquidity_cli.py tests/test_option_trading_data.py tests/test_option_trading_overview.py tests/test_option_trading_detail_panel.py tests/test_option_trading_routes.py -q` -> 36 passed after self-review fixes.
- `python -m pytest tests/test_options_liquidity.py tests/test_options_liquidity_cli.py tests/test_config_models.py tests/test_hedge_modules.py tests/test_hedge_data_contracts.py tests/test_scenarios.py tests/test_option_trading_data.py tests/test_option_trading_overview.py tests/test_option_trading_detail_panel.py tests/test_option_trading_routes.py tests/test_speculation_section.py tests/test_sensitivity_ranking.py tests/test_comparison.py -q` -> 156 passed after self-review fixes.
- `python -m pytest -q` -> 584 passed after self-review fixes.
- `python -m ruff check golden_vector tests` -> not run; `ruff` is not installed in this Python environment.
- `python -m mypy golden_vector` -> not run; `mypy` is not installed in this Python environment.
- `python -m pyright golden_vector` -> not run; `pyright` is not installed in this Python environment.
- `python main.py options-liquidity-summary --ticker AEM` -> printed cached tier counts after self-review fixes: `AEM | 7 | 5 | 8 | 9 | 0 | 7`.
- Browser verification on `http://127.0.0.1:8771/option-trading` -> overview shows exact Phase 1 columns, compact cache note, no P&L columns, no raw-report link, no long paragraph.
- Browser verification on `http://127.0.0.1:8771/ticker/AEM?lens=option-trading&side=put&horizon=60&bucket=most_liquid#option-sizing` -> bucket rows, corrected liquidity counts, stock price, snapshot date, spread/half-spread cost, disabled refresh placeholder, no old scenario tables, and selected bucket calculator verified.

Checkpoint 1 status: reached. Phase 1 code implemented and verified.

## 2026-06-03 - Phase 2, Step P2.1

Implemented:
- Extended options ingestion targets from universe-only to universe plus active benchmark ETFs configured in `hedge_readiness.benchmark_tickers`.
- GDX/GDXJ option chains are now fetched through the same per-ticker best-effort path, persisted under `snapshots/options`, included in the latest options manifest, and captured by the replay manifest source-asset list.
- Added `option_vehicle_type` and `options_source_symbol` to option feature rows so benchmark ETF rows remain auditable when they later surface in the lab.
- Reused persisted benchmark histories as price history context for benchmark ETF option features.

Self-review notes:
- No live data path was introduced in tests; fixture client covers AEM, GDX, and GDXJ.
- GDX/GDXJ are config-driven through `benchmarks.yaml` + `hedge_readiness.benchmark_tickers`; there is no hard-coded fetch in the loop.
- Per-ticker failure isolation still wraps the full fetch/persist/feature pipeline for each option target.
- Replay manifest capture needed no custom branch because it already enumerates every latest-options manifest snapshot.

Checks:
- `python -m pytest tests/test_options_phase.py tests/test_replay_manifest.py tests/test_persist_options.py -q` -> 29 passed.
- `python -m pytest tests/test_options_phase.py tests/test_option_trading_data.py tests/test_options_liquidity.py -q` -> 19 passed.

## 2026-06-03 - Phase 2, Step P2.2

Implemented:
- Benchmark ETF option feature rows now flow through the same Option Trading overview/detail path as miner rows when their cached snapshots exist.
- Overview rows carry `option_vehicle_type`; GDX/GDXJ benchmark ETF rows are labelled in Notes and sorted ahead of single-stock miners so they are easy to find.
- Added cached liquidity measurements comparing Benchmark ETFs vs Single-stock miners: ticker count, measured contract count, median relative spread, median open interest, median volume, and median near-spot depth.
- Rendered the liquidity measurement as a compact informational table on the Option Trading overview.

Self-review notes:
- The measurement is descriptive only and uses cached contracts with usable bid/ask/mid; it does not recommend a trade or size a hedge.
- GDX/GDXJ still require a fresh `python main.py update-data` run before they appear in Emanuel's local cached website data, because the current cache predates benchmark option-chain ingestion.
- No refresh button behavior was added; the disabled placeholder remains honest.
- The Phase 1 `is_usable_candidate()` gate remains the only suggested-contract gate.

Checks:
- `python -m pytest tests/test_option_trading_data.py tests/test_option_trading_overview.py tests/test_option_trading_routes.py tests/test_options_liquidity.py -q` -> 34 passed.
- `python -m pytest tests/test_options_phase.py tests/test_option_trading_data.py tests/test_option_trading_overview.py tests/test_option_trading_routes.py tests/test_options_liquidity.py tests/test_options_liquidity_cli.py -q` -> 40 passed.
- `python -m pytest tests/test_options_phase.py tests/test_replay_manifest.py tests/test_persist_options.py tests/test_option_trading_data.py tests/test_option_trading_overview.py tests/test_option_trading_routes.py tests/test_options_liquidity.py tests/test_options_liquidity_cli.py tests/test_config_models.py -q` -> 128 passed.
- `python -m pytest -q` -> 585 passed.
