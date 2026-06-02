# Codex Self-Review: Full Option Trading UI + Put/Call Workflow

Grade: READY WITH MINOR CHANGES

Scope reviewed: the full option-trading UI range through `0377cef`, including candidate generalization, scenario math usage, structured option-trading data loading/cache, overview route, ticker detail lens/panel, sizing calculator, docs, and tests.

## Findings

### P1 - Normal ticker detail pages now pay the full option-data load cost

`golden_vector/serve/workspace.py:189-217` loads `load_option_trading_data()` and builds ticker option detail for every `GET /ticker/<T>` request, before `render_detail_page()` knows whether the user asked for `lens=option-trading`. `golden_vector/serve/detail_page.py:89` then always appends the Option Trading panel, even for the default combined ticker view. That means the existing normal ticker page inherits the option stack's cold-start cost and failure surface. On current local data, a cold `load_option_trading_data()` call took `3.902s`; warm cache was `0.022815s`. The cache helps after first hit, but the first ordinary `/ticker/AEM` page after server start can feel unexpectedly slow. I would fix this before treating the milestone as fully polished: only load/build option detail when the option lens is active, or render a lightweight collapsed/CTA panel on the normal detail page and lazy-load the full data when the user enters `/ticker/<T>?lens=option-trading`.

### P2 - Scenario "now" labels need stronger assumption disclosure

`golden_vector/hedge/scenarios.py:129-135` computes `current_value_per_contract` by Black-Scholes repricing the same listed contract at the modeled stock price while keeping the original time-to-expiry and implied volatility. The UI labels this as `Value Now`, `P&L/share Now`, and `Net P&L Now` in `golden_vector/serve/detail_panels.py:357-360` and `golden_vector/serve/detail_panels.py:473-480`. That is mathematically defensible as an instant constant-IV model, but a non-expert user can easily read "now" as a real market quote after gold moves. The detail and calculator hints should explicitly say "instant model, same days-to-expiry, constant IV; not a live market mark." This is not a calculation bug, but it is a user-risk issue for an options screen.

### P2 - Call discovery is still gated by put-shaped optionability

The overview row builder filters to `is_optionable_tier(optionability_tier)` at `golden_vector/hedge/option_trading.py:116-120`, and `_candidate_grids()` uses the same tier gate for both puts and calls at `golden_vector/serve/option_trading_data.py:379-381`. That tier comes from the Hedge Readiness options feature model, which was originally put/downside-oriented. The UI now presents a put/call workflow, but a ticker with usable call liquidity and insufficient put-side coverage can be excluded entirely. If the intended product is "Hedge Readiness optionable subset with call context," this is acceptable but should be named that way. If the intended product is truly "put/call trading," side-specific optionability should be computed or at least exposed so calls are not hidden by a put-side gate.

### P3 - Budget mode still validates the contracts quantity field

`parse_option_sizing_request()` validates `quantity` before looking at whether the request is in budget mode (`golden_vector/serve/option_trading_data.py:129-149`). The current form usually sends a valid default quantity, so this is not breaking normal use. But a budget request with `quantity=0` or another invalid value can show an "Invalid quantity" note even though quantity does not drive the budget calculation. This makes the calculator feel noisier than necessary. The parser should validate quantity only for contract mode, or suppress the quantity note when budget mode is valid.

### P3 - The cache contract carries unused raw chain data

`OptionTradingData` stores `raw_options_by_ticker` at `golden_vector/serve/option_trading_data.py:51` and populates it at `golden_vector/serve/option_trading_data.py:246`, but no workspace option-trading code reads it. This is not harmful at current scale, but it makes the cache object heavier and the contract less clear. Either remove it until needed, or document the near-term consumer. A related small concern: `_CACHE` at `golden_vector/serve/option_trading_data.py:57` retains every distinct cache key for the server process lifetime. That is probably fine locally, but a one-entry "latest only" cache would better match the current usage.

## Additional Observations

The `CandidatePut = OptionCandidate` alias in `golden_vector/hedge/candidate_puts.py:42` is a reasonable compatibility bridge. I would not rename the module in this milestone because the CLI report and existing tests still depend on the put-shaped path, but a later cleanup should move the generic type into an option-neutral module once the call workflow stabilizes.

The GET-only calculator is the right architecture for this use case. It avoids pretending a trade or holding was saved, keeps back/refresh behavior understandable, and tests cover no file mutation.

The structured data path is materially better than the old markdown-rendering path. The cache key includes options, Tool A, and Tool B provenance, and stale feature rows with mismatched `run_id` are ignored. I did not find a data-mixing bug in the reviewed path.

## Checks Run

| Check | Result |
|---|---|
| `python -m pytest tests/test_option_trading_data.py tests/test_option_trading_routes.py tests/test_option_trading_overview.py tests/test_hedge_modules.py tests/test_scenarios.py tests/test_strategy_generic_math.py -q` | `55 passed in 11.44s` |
| `python -m pytest -q` | `548 passed in 170.70s` |
| `git diff --check` | Passed; only existing CRLF warning for `tests/test_workspace_app.py` |
| `python -m ruff --version` | Could not run: `No module named ruff` |
| `python -m mypy --version` | Could not run: `No module named mypy` |

## Open Questions For Merge With Claude Review

1. Should the Option Trading panel be visible on every ticker detail page, or only when `lens=option-trading` is active?
2. Should the product name remain "Option Trading" if the universe is still Hedge Readiness optionable names rather than side-specific put/call availability?
3. Should the calculator show zero-contract budget scenarios as a table with zero net P&L, or as a no-contract message?

## Suggested Decision

I would merge Claude's review against this one, then make only the small load-bearing fixes: avoid unconditional option loading on normal ticker detail pages, strengthen constant-IV/same-expiry assumption labels, and clean the budget-mode quantity note. The rest can wait unless Claude finds a true correctness issue.
