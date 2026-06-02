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

## Batch 2

- Step 3: implemented the `/ticker/<T>?lens=option-trading` detail lens with an anchored Option Trading panel rendered from cached structured put candidate/scenario data.
- Step 4: redirected `/hedge-readiness` to `/option-trading` and kept the legacy markdown available only as a raw `latest.md` download.
- Self-review gate 2: reviewed the Batch 2 diff, reran the full suite (`532 passed`), and browser-verified the tab, ticker detail panel, and redirect with no warnings or errors. No code fixes required.
- Post-checkpoint review: fixed the detail-page window switcher so the Option Trading lens and `#option-trading` anchor survive 6M/12M/3Y window clicks; added a regression test.
- Claude review M1: changed the detail data path to reuse the already-cached overview row instead of rebuilding the full overview for one ticker; added a regression test pinning overview/detail row identity and P&L consistency.
- Claude review M2: threaded a `risk_free_rate_is_fallback` flag through the option-trading data, overview, and detail panel; the UI now discloses the 0% fallback and tests cover malformed manifests plus invalid lens fallback.
- Step 5: generalized `CandidatePut` to the backwards-compatible `OptionCandidate` model, added `build_candidate_grid`, renamed scenario beta inputs to `gold_beta`, kept old put wrappers/aliases working, and verified with the full suite (`540 passed`).
- Step 6: added call candidate grids, overview call context P&L, and ticker-detail Upside Call sections scaled with `up_beta_core` and labelled as bullish speculation; full suite stayed green (`542 passed`).
- Checkpoint C self-review: reviewed the Batch 3 diff as one change, confirmed put wrappers/CLI compatibility, call scenarios use `up_beta_core`, no frontend financial math or markdown regex path was introduced, and no additional fixes were needed.
- Step 7: added the GET-only sizing calculator with contracts and budget modes, server-side scenario rescaling, validation fallback notes, and a no-file-mutation route test; full suite stayed green (`546 passed`).
- Step 8: added workspace CSS for the put/call segments and sizing calculator, updated Hedge Readiness docs with the Option Trading tab and premium-budget semantics, and reran the full suite (`546 passed`).
- Checkpoint D self-review: verified no custom frontend financial math, no markdown renderer path, GET calculator no-mutation coverage, browser-tested overview/detail/contracts/budget flows on port 8766, and wrote the completion report.
- Post-completion self-review: fixed skipped sizing scenarios so they render an explanatory message instead of an empty table, replaced the calculator radio CSS `:has()` dependency with an explicit class, tightened sizing query typing, and refreshed option-generic labels/docstrings.
