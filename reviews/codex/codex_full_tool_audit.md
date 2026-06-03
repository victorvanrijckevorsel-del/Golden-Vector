# Codex Full Tool Audit

Overall grade: READY WITH IMPORTANT FIXES

The codebase is in a much stronger state than the start of the milestone: the workspace split is coherent, replay manifests exist, Tool A and Tool B preserve run context, the option engine uses per-contract IV, and the option trading UI now has useful user-facing workflows. The full test suite passes. I would not call it "perfect" or ready for real-money use without the fixes below, because a few issues are not syntax bugs: they are about model claims, replay depth, and user-facing honesty around speculative long-options workflows.

## Top 5 Fixes Before Shipping

1. Decide and lock the exact Tool A downside-beta formula. The implementation is an OLS-with-intercept split-regression, not the no-constant downside-truncated D-CAPM formula called out in the research audit.
2. Add stronger user-facing caveats for long premium buying: negative expectancy on average, constant-IV repricing, and linear beta approximations at -15%/-20% gold shocks.
3. Extend replay verification from captured manifests to the transitive source assets listed inside those manifests, especially option snapshots and foundation outputs.
4. Surface `iv_skew` and `iv_rv_ratio` as context signals, with caveats, because they are computed but not visible in the main decision surfaces.
5. Reduce scenario-sign ambiguity by centralizing conversion between positive downside magnitudes and signed scenario returns, with tests.

## Correctness Errors / Unsound Math

### Tool A Down-Beta Formula Needs an Explicit Decision

Severity: P1

`golden_vector/model/structural.py:287` computes up/down metrics by filtering weekly observations into positive and negative gold-return subsets, then calls `compute_regression`. `golden_vector/model/structural.py:524` implements ordinary least squares with an intercept by centering `x` and `y`. That is a valid descriptive split-beta calculation, but it is not the no-constant downside-truncated D-CAPM formula highlighted as a research check in `reviews/codex/research_academic_grounding_gold_model.md`. The code may still be right for the chosen Guo/Leung/Ward-style framework, but the product should not imply it is implementing the Estrada-style downside-beta definition unless the formula is changed or explicitly documented. This needs a formula contract test either way.

### Scenario Sign Conventions Are Correct Today But Fragile

Severity: P2

`golden_vector/hedge/expected_downside.py:32` treats configured `gold_down_scenarios` as positive downside magnitudes. `golden_vector/hedge/scenarios.py:75` treats scenario returns as signed values such as `-0.10`. The config model enforces both conventions separately in `contracts/config_models.py:225` and `contracts/config_models.py:234`, so current code is not wrong. The risk is cross-subsystem coherence: a future caller can pass positive downside magnitudes into the signed scenario engine and silently model upside instead of downside. A small conversion helper and tests would make this safer.

### Black-Scholes Pricing And Strategy Sign Rules Look Sound

Severity: informational

`golden_vector/features/black_scholes.py:51` and `golden_vector/features/black_scholes.py:80` handle put/call pricing, expiry, zero volatility, and spot-zero edge cases. `golden_vector/hedge/scenarios.py:220` applies long/short sign rules and `golden_vector/hedge/scenarios.py:293` handles breakevens. The parity and reference tests in `tests/test_black_scholes.py` are the right anchor. I did not find a pricing-sign bug in the current option math.

## Data-Integrity And Cross-Subsystem Coherence

### Replay Verification Is Manifest-Level, Not Fully Transitive

Severity: P1

`golden_vector/app/replay_manifest.py:171` verifies captured configs, manual DB snapshot, foundation manifest snapshot, and options manifest snapshot. `golden_vector/ingestion/persist_options.py:29` records per-snapshot `sha256` values inside the options manifest, but `verify_manifest` does not currently walk those nested snapshot entries and verify the underlying parquet files are still present and unchanged. This means the replay manifest can prove that the options manifest was captured, but not that every source artifact listed inside it is still available and intact. For audit-grade replay, verification should be transitive or the command should clearly say it is manifest-only.

### Foundation Currency QA Is Strong, But Stale FX Is Intentionally Non-Blocking

Severity: informational

`golden_vector/normalize/prices_usd.py:118` and `golden_vector/normalize/market_snapshot.py:83` mark missing or stale FX and invalid market snapshot values. `golden_vector/qa/normalization_quality.py:41` turns stale-only FX issues into WARN when `block_on_stale_fx` is false, and `config/qa.yaml` currently sets `block_on_stale_fx: false`. Tool A then filters structural series to `normalization_status == "OK"` in `golden_vector/model/structural.py:119`, which protects beta estimates. Tool B carries snapshot normalization status into output rows in `golden_vector/screening/pipeline.py:357`. This is coherent, but the policy should stay visible because stale FX can still affect market-cap and valuation screening.

### Hedge Data-Contract Tests Are Useful But Too Shallow

Severity: P2

`tests/test_hedge_data_contracts.py` checks that minimal Tool A, Tool B, and options feature columns exist. The actual consumers read a broader contract: `golden_vector/serve/option_trading_data.py:375`, `golden_vector/hedge/sensitivity_ranking.py:113`, and `golden_vector/hedge/report.py:1070` depend on additional fields such as `underlying_price`, `atm_iv_60d`, strategy scenario fields, run IDs, and candidate metadata. The current tests catch total breakage but not narrower producer-consumer drift. Add a fuller fixture-based contract test for every field consumed by the option trading UI and hedge report.

### Tool A / Options Freshness Handling Is Mostly Solid

Severity: informational

`golden_vector/serve/option_trading_data.py:37` keys the option trading cache by options refresh ID and Tool A / Tool B refresh IDs. `golden_vector/serve/option_trading_data.py:332` also skips stale feature rows whose `run_id` does not match the current options manifest. `golden_vector/hedge/report.py:1208` reports context alignment between Tool A, Tool B, and options runs. This is the right direction. Future Tool C/D work should keep the distinction clear between a Tool A output run ID and the underlying foundation refresh run ID.

## Research-Grounded Improvements

### Long Option Negative Expectancy Is Not Disclosed Clearly Enough

Severity: P1

The option trading UI says calls are speculative and lose to time decay if gold stalls in `golden_vector/serve/detail_panels.py:274`, and it states constant-IV Black-Scholes assumptions in `golden_vector/serve/detail_panels.py:42`. That is useful, but it does not say the main research point: buying options is usually expensive on average because option premiums include compensation for volatility risk. The markdown report has the same gap around speculation candidates in `golden_vector/hedge/report.py:677`. This matters because the tool is designed for speculative put/call buying. The disclosure should be plain English, not academic: "Buying puts/calls can be right on direction and still lose money if the move is too small or too slow."

### `iv_skew` And `iv_rv_ratio` Are Computed But Not Surfaced

Severity: P2

`golden_vector/features/options.py:137` computes `iv_skew_{h}d = put_iv - call_iv`, which is the correct sign convention for downside protection being more expensive than upside calls. `golden_vector/features/options.py:140` computes `iv_rv_ratio_{h}d`, which is a useful "options look expensive versus realized volatility" context signal. I did not find these fields surfaced in the main workspace option lens or hedge report. They should not become hard triggers, but they are more decision-relevant than raw put-call ratio and should be visible with caveats.

### Put-Call Open Interest Ratio Is Appropriately De-Emphasized

Severity: informational

`golden_vector/features/options.py:67` computes total and OTM put-call open interest ratios. The current UI does not appear to oversell this as a predictive signal, which is correct given the research review. Keep it as context only.

### Down-Beta Is Descriptive, Not Predictive

Severity: P2

`golden_vector/hedge/sensitivity_ranking.py:45` ranks names by `down_beta_core`, and `golden_vector/hedge/report.py:545` renders the Sensitivity Ranking section. This is useful for prioritizing names that have historically moved more when gold fell, but the report should explicitly say it is a descriptive stress-sensitivity view, not a forecast of future returns. This is especially important if Emanuel uses the ranking to choose speculative puts.

## Honesty / Labeling Gaps

### Scenario Tables Need Stronger Model-Value Labels

Severity: P2

`golden_vector/hedge/report.py:899` labels columns as "Expiry quote" and "Current quote". These values are modeled Black-Scholes values, not observed market quotes. The UI is clearer because `golden_vector/serve/detail_panels.py:42` defines the repricing assumption and reuses it in scenario hints. The markdown report should use labels like "Modeled value at expiry" and "Modeled value now" and should repeat the constant-IV assumption near the tables.

### Extreme Gold-Shock Rows Need A Linear-Model Caveat

Severity: P2

`golden_vector/hedge/scenarios.py:126` maps gold shocks to stock prices with a linear `current_stock_price * (1 + beta * gold_pct_change)` model. That is acceptable for a first-pass decision tool, but -15% and -20% gold scenarios can be outside the range where linear beta is reliable, especially for leveraged miners. The research audit called this out explicitly. The UI and markdown report should flag those rows as approximate and remind the user that operating leverage, balance sheet stress, and liquidity can make real moves non-linear.

### Tool B Gold-Price Assumption Is Preserved Correctly

Severity: informational

`golden_vector/cli.py:811` resolves the Tool B gold price assumption, and `golden_vector/screening/pipeline.py:319` persists it into Tool B rows. This is good: screening output is not pretending to be independent of the gold-price assumption.

### Option Calculator Is GET-Only And Non-Mutating

Severity: informational

`golden_vector/serve/option_trading_data.py:105` parses calculator inputs from query parameters, and the option trading lens is rendered without writing user selections. This matches the expected local-first workspace behavior and avoids hidden state.

## Test Gaps

### Missing Test For Tool A Regression Formula Choice

Severity: P1

There should be a small deterministic fixture proving the intended relationship between gold returns and equity returns for full beta, up beta, and down beta. If the intended method is OLS-with-intercept on up/down subsets, test that explicitly. If the intended method is no-constant downside-truncated D-CAPM, the implementation needs to change and the test should lock it.

### Missing Tests For Shipping-Safety Disclosures

Severity: P2

There are tests for option math and UI plumbing, but not for the most important user-facing warnings: constant-IV repricing, long-premium negative expectancy, model values versus market quotes, and approximate extreme shock rows. These should be tested in both markdown report output and the option trading lens.

### Missing Transitive Replay Verification Tests

Severity: P2

`tests/test_replay_manifest.py` covers manifest creation and direct snapshot verification. It should also cover a changed or missing options/foundation parquet that is listed inside a captured manifest. If the intended behavior remains manifest-only, the command output and tests should make that limitation explicit.

### Missing Full Hedge Producer-Consumer Contract Test

Severity: P2

The current contract tests are a good start, but they do not guarantee the hedge report, option trading UI, comparison table, portfolio totals, and sensitivity ranking all receive every field they consume. A fixture-level test that builds the option trading model and markdown report from representative Tool A / Tool B / options rows would catch drift earlier.

### Missing Scenario Sign-Convention Guard

Severity: P2

A test should fail loudly if positive downside magnitudes are passed into the signed scenario engine without conversion. This is a small test but prevents a high-impact future mistake.

## Subsystem Notes

### Ingestion & Foundation

The build sequence is sound: `golden_vector/ingestion/foundation.py:94` runs raw QA before normalized outputs, and `golden_vector/cli.py:493` only updates the latest foundation manifest when the foundation run does not fail. Currency normalization is explicit and auditable. The biggest foundation risk is not a current bug; it is making sure WARN-level stale FX remains visible when screening outputs are interpreted.

### Tool A Structural Betas

The data preparation is careful: `golden_vector/model/structural.py:99` builds weekly USD series, filters bad normalization statuses, and drops incomplete current weeks. The concern is formula identity and claim precision. Tool A should state exactly what it computes and avoid borrowing academic labels that imply a different estimator.

### Tool B Fundamental Screening

Tool B preserves the gold-price assumption and source run IDs, and the layer logic handles missing or invalid values as incomplete rather than forcing false precision. I did not find a blocking Tool B correctness issue in this audit.

### Options Engine

The pricing core is good. Per-contract IV is used, put-call parity is tested, and strategy P&L signs are covered. The main gap is not the math; it is surfacing option-expensiveness context and making the limitations impossible to miss.

### Option Trading UI

The UI is materially useful: it is ticker-centric, has puts/calls views, computes scenarios, and keeps calculator state in the URL. It also avoids POST mutation. The remaining work is plain-English risk labeling and showing the computed IV context signals.

### Workspace Serve Layer

The serve split appears coherent. The workspace owns HTML and data attributes, with the vendored DataTables enhancement staying in-page. I did not find evidence that the option trading UI broke the local WSGI ownership model.

### Config / Provenance / Replay

Config hashing and run context are well placed. Replay is good enough for "what manifests did this run use?" but not yet good enough for "can I prove every source artifact behind this number is still intact?" unless transitive verification is added.

### CLI

`golden_vector/cli.py:66` exposes the expected commands, including `hedge-readiness` flags for sorting, quantity, and max tickers. `golden_vector/cli.py:1695` refreshes foundation, Tool A, Tool B, and status. Tool C/D are not yet implemented; when they are, refresh/status should be extended without weakening the existing build sequence.

## Open Citation Gaps

- Exact academic formula for the chosen Tool A down-beta implementation.
- Constant-IV Black-Scholes scenario repricing citation or internal methodology note.
- Cross-commodity beta / convexity evidence for future Tool C.
- AISC-to-margin stress methodology for future Tool D.
- Single-name miner option skew interpretation; current `put_iv - call_iv` sign is right, but threshold interpretation should remain cautious.

## Commands And Results

- `python -m pytest -q` -> `550 passed in 79.69s (0:01:19)`.
- `git status --short` -> existing unrelated modified/untracked files were present before this review file was created; I did not revert or edit them.
- Static inspection used targeted `rg` searches and focused file reads across ingestion, normalization QA, Tool A, Tool B, options features, hedge scenarios, report rendering, workspace serve modules, replay manifests, and CLI.

