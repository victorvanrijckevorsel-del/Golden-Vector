# Claude review — B1 bounded parallel Yahoo fetch

**Reviewer:** Claude Code (Opus 4.8), first-hand (read every changed file, traced the concurrency path, ran the tests).
**Commits:** `b2e05bf` (Parallelize bounded Yahoo foundation fetch) + `18e17aa` (Clean up bounded fetch helpers). Working tree clean.
**Verdict: APPROVE the code.** Well-engineered — correct on every concurrency hazard I checked. **Remaining gate: one real refresh (live API)** before this is trusted in production — see below.

---

## The 5 concurrency hazards — all handled correctly

**#1 — Limiter applied before *every* attempt, including retries. ✅**
`call_with_retries` calls `before_attempt()` at the top of every loop iteration (`collection_resilience.py`), and `YahooClient` passes `before_attempt=self._rate_limiter.wait` to all four fetch methods (history, fast_info, options_expirations, option_chain). So the limiter fires before the first attempt *and* before each retry — exactly Codex's own F7 requirement. Bonus: `YahooClient` sets `throttle_seconds=0.0` on the retry policy, so the old per-call sleep is removed and replaced by the global limiter — no double-throttle.

**#2 — Single shared limiter across all threads, with a correct lock. ✅**
- `foundation.py:55` creates **one** `YahooClient` and passes the same instance to every fetcher (equity, fx, gold, snapshot). One client → one `YahooRateLimiter` → the global rate is governed continuously across the whole foundation phase, including between phases.
- `YahooRateLimiter.wait()` reserves the next slot *inside* a `Lock` (computing `sleep_seconds` and advancing `_next_allowed_at` atomically), then sleeps *outside* the lock. This is the correct no-burst pattern — threads serialize only on the tiny reservation, not on the sleep.
- The same `client` is captured in each fetcher's `lambda target: _fetch_*(client, target)`, so all pool threads share it.

**#3 — Per-ticker failure isolation. ✅**
Both `_fetch_equity_history` and `_fetch_market_snapshot` wrap the whole task in try/except and return a `FAIL` `FetchStatusRecord` (equity returns an empty standardized frame; snapshot returns `None`, filtered out). A task never raises, so one bad ticker can't abort the batch.

**#4 — Deterministic output ordering. ✅**
`map_with_bounded_workers` uses `executor.map(func, item_list)`, which returns results in **input order** regardless of completion order (docstring says so; serial fallback `[func(x) for x ...]` when ≤1 worker is also in-order). The order-sensitive `statuses` lists are therefore deterministic. Confirmed by tests asserting `[s.entity ...] == ["AAA","BBB","CCC","DDD"]`.

**#5 — Limiter spacing vs worker count is sane. ✅**
Config: `yahoo_max_workers: 4`, `yahoo_throttle_seconds: 0.15` (→ limiter min-interval), `yahoo_backoff_jitter_seconds: 0.1`, `yahoo_max_attempts: 3`. The limiter caps the *global* launch rate at ~1 per 0.15s (~6.7/s) while 4 workers overlap Yahoo's response latency. For ~185 foundation calls that's a ~28s spacing floor + overlapped latency, vs ~serial minutes — a real win that stays gentle. Crucially, the limiter caps the rate **regardless of worker count**, so even a misconfigured large `yahoo_max_workers` (bounded by `bounded_worker_count` to the item count) cannot burst Yahoo faster than the interval. Defensive.

## Code quality
- **No duplication:** the executor logic is a single shared `map_with_bounded_workers` helper used by both fetchers (the F8 "one shared bounded parallel map"). Clean.
- **Testable:** injectable `sleep_func`/`monotonic_func`/`random_func` throughout; `bounded_worker_count` and `_jitter_seconds` are small pure helpers with validators.
- **Safe defaults:** `max_workers=1` default in both fetchers (serial unless wired), positive-value validators on config.

## Tests — strong, prove the actual properties
- `test_parallel_foundation_fetch.py`: asserts `1 < max_in_flight <= 2` (bounded **and** genuinely concurrent), input-order entities, and FAIL-isolation (BBB fails, others PASS) for **both** fetchers.
- `test_yahoo_client.py`: no-burst spacing (`sleeps == [0.25, 0.50]`) and **limiter-fires-before-retry** (`history_calls == 2`, sleep recorded before the retry).
- B1-focused suite: **95 passed**. Full suite: **770 passed, 0 failed** (verified first-hand).

## Minor nits (non-blocking)
1. `_fetch_equity_history`'s except branch calls `standardize_equity_history(..., frame=pd.DataFrame())`. If that empty-frame standardize ever raised, it would propagate out of the task to `executor.map` and abort the batch. Low risk (empty path is standard), but a `try/except` around the fallback (mirroring the snapshot fetcher, which just returns `None`) would be strictly safer.
2. FX and gold fetches run serially (no `max_workers`), which is fine given their small counts — just noting it's intentional, not an omission.

## Scope reminder — what B1 does NOT cover
- **Options fetch is still serial** (`options_phase.py`). B1 parallelized the *foundation* fetch only (per plan F8/B3 — B3 waits for the B2 decision). So the real-refresh speedup will show on the foundation portion; options fetch won't speed up until B3.

## The remaining gate: one real refresh (live API)
The unit tests use a fake client — they prove the *logic* (bounded, ordered, isolated, spaced, limiter-before-retry) but **cannot** prove that real Yahoo tolerates 4 concurrent workers at 0.15s spacing without throttling or soft-bans. That requires **one real refresh**, confirming: (a) the foundation fetch is materially faster, and (b) no new FAIL statuses / rate-limit errors vs a serial baseline. Per the project rule (live external API), this needs Emanuel's go-ahead before merge/trust.

## Bottom line
Approve the code — it's a careful, correct, well-tested bounded-concurrency implementation that nails every hazard (shared limiter, lock-then-sleep, before-retry, isolation, ordering, rate-cap-independent-of-workers). Validate on one real refresh, then it's done. Next build task should be **C1** (options write-then-read cleanup) — safe, Yahoo-free, independent of the B2 decision.
