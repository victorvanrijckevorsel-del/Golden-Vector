# Option Trading Progress

## Baseline

- Branch: `dev-vic`
- v2 review: ready to implement. Non-blocking note: v2 risk #1 mentions sizing inputs in the cache key, but §2d/§2h are the controlling contract; Batch 1 will use a provenance-only cache and sizing will not re-key it.
- Baseline test suite: `python -m pytest -q` -> 520 passed.

## Batch 1

- Step 1: implemented `hedge.option_trading` structured overview rows plus `serve.option_trading_data` provenance-keyed cache. Focused tests added in `tests/test_option_trading_data.py`.
- Step 2: implemented `/option-trading` route, nav tab, and native DataTable overview from structured rows. Focused route/render tests added.
- Self-review gate 1: fixed one unused import, escaped the put-P&L header, and guarded empty `underlying_price` chain values.
- Post-checkpoint review: fixed stale feature-row fallback so the tab ignores feature parquet rows whose `run_id` does not match the latest options manifest.
