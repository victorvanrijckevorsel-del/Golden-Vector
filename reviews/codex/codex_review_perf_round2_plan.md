# Codex Review - Claude Perf Round 2 Plan

**Grade: NEEDS CHANGES**

The direction is broadly right, but the plan underestimates the remaining Tool A CPU cost and overstates that the refresh is already fetch-dominated. I re-measured the current committed code (`85936c2`) against the cached local foundation snapshot without calling Yahoo. On the current 60-ticker dataset, in-memory Tool A compute still took **222.6s**: structural/window metrics **136.4s**, volatility diagnostics **86.2s**, producing **179,562 structural rows**, **59,854 weekly rows**, and **59,854 volatility rows**. The current manifest records `update_data` at **220.9s**, so Tool A is not yet a solved 7s problem. Phase A is therefore not "cheap polish"; it is still the main local CPU bottleneck and should be fixed before parallelizing Yahoo.

## Re-measured Profile

Source: direct in-memory timing using `load_latest_foundation_snapshot`, `build_structural_ticker_data`, and `compute_volatility_diagnostics`; no new run was written and no live API was called.

| Area | Measured current cost | Notes |
|---|---:|---|
| Tool A structural/window metrics | 136.4s | Main remaining local CPU block before volatility. |
| Tool A volatility diagnostics | 86.2s | Still very expensive at full scale. |
| Total in-memory Tool A compute | 222.6s | Roughly equal to the recorded `update_data` stage. |
| Recorded `update_data` | 220.9s | From `data/intermediate/status/latest_model_state.json`; includes foundation + options fetch. |
| Recorded option artifacts | 32.3s | Stale manifest timing from before a fresh post-`85936c2` refresh; cached compute is much lower after scan consolidation, but persistence-stage timing needs a fresh run. |
| Tool C / Tool D / Tool B | 13.0s / 3.2s / 2.4s | Not first-order bottlenecks. |

Top profile entries from the current Tool A measurement:

| Function | Cumulative time |
|---|---:|
| `compute_structural_window_metrics` | 115.0s |
| `compute_volatility_diagnostics` | 86.1s |
| `_window_bounds` | 75.7s |
| `_window_start` | 71.4s |
| `np.std` stack inside volatility | 30.0s |
| `_build_volatility_anchor_rows` | 27.0s |
| `_summarize_normalization_issues_by_as_of` | 12.0s |
| `build_structural_weekly_series` | 21.1s |

## Findings

**F1 - The bottleneck ranking is wrong: Tool A is still a first-order bottleneck.**  
Claude's plan says Tool A structural metrics are now about 7s and the refresh is fetch-dominated. That does not match current cached-data measurement. Tool A still costs about **222.6s** in-memory, roughly the same as the recorded `update_data` stage. This matters because it changes the order of work: A1/A2 must come before B1, and after A1/A2 we need to reprofile before assuming Yahoo is the only serious wall-clock problem. References: `golden_vector/model/structural.py:523`, `golden_vector/model/structural.py:831`, `golden_vector/model/structural.py:1193`.

**F2 - A1 is right, but "vectorize `_window_start`" is too vague; preserve calendar semantics and share the result across callers.**  
The `_window_start` hotspot is real: **179,562 calls**, **71.4s cumulative**. The plan correctly targets it, but the implementation should centralize a helper that computes trailing-start arrays for a full `DatetimeIndex` and reuse it for both `_window_bounds` and `_summarize_normalization_issues_by_as_of`. Be careful: `12M` and `1Y` are calendar offsets, not fixed day counts. Leap-day, month-end, and the existing `side="right"` exclusion behavior must remain pinned. A pure "convert months to days" optimization would be wrong. References: `golden_vector/model/structural.py:523`, `golden_vector/model/structural.py:690`, `golden_vector/model/structural.py:1193`.

**F3 - A2 should not be implemented as a simple `groupby().rolling(52)` rewrite.**  
Volatility diagnostics are expensive, but the proposed `groupby("ticker").rolling(52)` approach is risky and probably not the best design. Total and downside volatility are count-based trailing 52-week windows, but residual volatility depends on the **anchor row's own alpha/beta**, which vary by ticker/date/window. A safer and faster design is prefix sums over each ticker's weekly arrays: stock count/sum/sumsq for total vol; negative-stock count/sum/sumsq for downside vol; and paired gold/stock count, `sum_x`, `sum_y`, `sum_xx`, `sum_xy`, `sum_yy` for residual variance under row-specific `alpha + beta * gold`. This also preserves the current behavior when an anchor `as_of_date` does not exactly exist in the weekly series, because the existing code uses `searchsorted(..., side="right")`, not an exact merge. References: `golden_vector/model/structural.py:831`, `golden_vector/model/structural.py:893`, `tests/test_structural.py:436`.

**F4 - The volatility parity gate needs two more edge cases.**  
The current reference parity test is valuable and strict (`atol=1e-12`), but it only uses anchor dates that are present in the weekly series and mostly usable deltas/intercepts. Add cases where the structural anchor date falls between two weekly dates, where alpha/beta are missing so residual volatility must stay `None`, where total/downside volatility still compute, and where fewer than two valid residual observations exist. Without these, a rolling merge implementation can pass the current test while changing sparse-calendar behavior. References: `tests/test_structural.py:436`, `golden_vector/model/structural.py:858`.

**F5 - The plan misses another structural hotspot: normalization issue summaries.**  
`_summarize_normalization_issues_by_as_of` costs about **12.0s** and repeats 3-year calendar offset math for every as-of date. If A1 creates a shared vectorized/cached trailing-start helper, this should be folded into A1. If left alone, it becomes a visible chunk after `_window_start` and volatility are improved. Reference: `golden_vector/model/structural.py:690`.

**F6 - Do not assume Phase A gets Tool A to 1.5s.**  
Even after removing most `_window_start` and volatility cost, there are still measured chunks in `_compute_vectorized_window_metric` / `_ols_metric_at` (~20s cumulative), `build_structural_weekly_series` (~21s), and output assembly/scoring. The expected "structural CPU ~12s -> ~1.5s" is not supported by the current full-scale profile. The better gate is: implement A1, reprofile; implement A2, reprofile; only then decide whether to chase additional Tool A CPU or switch to fetch.

**F7 - B1 parallel fetch is directionally right, but start more conservative and make the limiter a shared YahooClient primitive.**  
The current foundation fetchers are fully serial (`fetch_equity_histories`, `fetch_market_snapshots`), and options fetch is also serial in `run_options_ingestion_phase`. Bounded threads are appropriate because yfinance is blocking; async would add complexity without obvious benefit. But I would not start with 8 workers. Start with **3-4 workers**, a global no-burst limiter around every Yahoo call in `YahooClient`, and config flags for `max_workers` and minimum inter-request interval. Retry backoff should include jitter, and the limiter must apply before retries too, not only after successful calls. Tests should use a fake Yahoo client to prove bounded in-flight calls, deterministic output order, per-ticker failure isolation, and shared rate limiting. References: `golden_vector/ingestion/foundation.py:57`, `golden_vector/ingestion/fetch_equities.py:22`, `golden_vector/ingestion/fetch_market_snapshot.py:26`, `golden_vector/ingestion/collection_resilience.py:52`, `golden_vector/ingestion/yahoo_client.py:28`.

**F8 - B1 should explicitly cover options fetch, or defer it intentionally.**  
The plan describes foundation fetch parallelization, but the recorded `update_data` includes options fetching too, and `options_phase.py` loops serially over 62 option targets. If B1 only parallelizes equity histories and market snapshots, options may remain a large serial wall-clock block. I would sequence this as: build one shared bounded parallel map/rate limiter, apply it to foundation first, re-measure, then decide whether options fetch uses the same primitive after B2 reduces expiration count. References: `golden_vector/ingestion/options_phase.py:112`, `golden_vector/ingestion/fetch_options.py:51`.

**F9 - B2 targeted expiry fetch is not behavior-neutral; it changes aggregate option features.**  
Claude says derived features should be equivalent because only 60/90/120d horizons are used. That is only partly true. `compute_options_features` also persists aggregate fields over the fetched frame: `n_expirations`, `n_contracts`, `total_open_interest`, `total_volume`, `put_call_oi_ratio_total`, and `put_call_oi_ratio_otm`. Switching from `"all"` to `"targeted"` will change those values and may change `optionability_tier` because it depends on `total_open_interest`. This can be acceptable, but it must be explicit: either redefine those aggregates as "within configured option DTE bands", or keep full-chain fetch for aggregate context while using targeted fetch only for candidate-oriented refresh. References: `golden_vector/features/options.py:64`, `golden_vector/features/options.py:66`, `golden_vector/features/options.py:69`, `golden_vector/features/options.py:225`, `golden_vector/ingestion/fetch_options.py:276`.

**F10 - C1 is reasonable, but it should not outrank the Tool A fixes.**  
The options phase does persist each option snapshot and then re-read it inside `_compute_feature_row`. Passing `result.frame` directly into feature computation is a clean low-risk improvement, as long as persistence still records the immutable snapshot and tests prove the persisted frame matches the in-memory frame. It is not the next bottleneck compared with A1/A2 and fetch. References: `golden_vector/ingestion/options_phase.py:147`, `golden_vector/ingestion/options_phase.py:288`, `golden_vector/ingestion/options_phase.py:300`.

## Recommended Revised Sequence

1. **A0: Add a repeatable local perf harness** for cached Tool A and option-artifact compute. It should print row counts and timings for structural build, volatility diagnostics, option scans/artifacts, and total compute. This avoids future "synthetic says 7s, real data says 223s" drift.
2. **A1: Centralize calendar trailing-start arrays** and reuse them in `_window_bounds` and `_summarize_normalization_issues_by_as_of`. Gate with existing structural parity plus explicit leap-day/month-end/`side="right"` assertions.
3. **A2: Rewrite volatility diagnostics with prefix sums, not `groupby().rolling()`**, preserving searchsorted window membership and row-specific residual alpha/beta. Gate with old-reference parity plus the new sparse-date/missing-alpha edge cases.
4. **A3: Reprofile Tool A before touching Yahoo.** If Tool A is still >30-45s, inspect `build_structural_weekly_series`, `_ols_metric_at`, and output assembly before moving on.
5. **B1: Add shared bounded Yahoo concurrency and global rate limiting**, starting with foundation fetch only. Use low default concurrency, deterministic result ordering, fake-client tests, and one real refresh validation.
6. **B2: Decide targeted expiry semantics before flipping the default.** If we accept band-limited aggregate option features, rename/document them and add parity tests for candidate outputs. If we still want full-chain aggregate context, do not make `"targeted"` the default globally.
7. **B3: Apply the same bounded concurrency primitive to options fetch only after B2 is settled**, so we do not multiply Yahoo request pressure unnecessarily.
8. **C1: Remove the options write-then-read round trip** once the bigger CPU/fetch issues are under control.

## Bottom Line

Approve the goal, not the plan as written. The next work should start with Tool A CPU because the current full-scale measurement says it is still about as slow as `update_data`. Parallel Yahoo fetch is still important, but it should come after the remaining Tool A hotspots are fixed and reprofiled. The targeted expiry idea is promising for speed, but it changes persisted aggregate option features and should be treated as a product/data-contract decision, not a harmless config flip.
