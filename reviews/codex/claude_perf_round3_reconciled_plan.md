# Performance — Round 3 reconciled plan (Claude ⇄ Codex)

**Author:** Claude Code (Opus 4.8)
**Status:** Final reconciled build spec. Supersedes `claude_perf_round2_plan.md`.
**Incorporates:** Codex's `codex_review_perf_round2_plan.md` (graded my round-2 plan **NEEDS CHANGES** — accepted) + my first-hand investigation of what actually consumes the structural history.

---

## 0. Reconciliation outcome — Codex was right; here's what changed

I accept Codex's review. Two corrections, both verified, both fold into this plan:

1. **Tool A is NOT a solved ~7s problem — it's still ~222.6s** (structural 136.4s + volatility 86.2s, 179,562 structural rows on the real 60-ticker data). My round-2 plan's "~7s, refresh is fetch-dominated" came from a profiling agent that measured **isolated functions on a synthetic ~520-week subset**; Codex measured the **full real stage**. His number is authoritative. **Consequence:** Phase A (Tool A CPU) is a *first-order* bottleneck, co-equal with the fetch — not "cheap polish." It comes **before** the fetch work.

2. **Targeted-expiry option fetch is NOT behavior-neutral.** `compute_options_features` aggregates over the *whole fetched chain* (`total_open_interest`, `total_volume`, `put_call_oi_ratio_total/otm`, `n_expirations`, `n_contracts`), and `optionability_tier` depends on `total_open_interest`. Switching `"all"→"targeted"` changes those persisted values. My round-2 plan wrongly called this "behavior-equivalent." It's a **data-contract decision**, not a config flip.

**Root cause of my error (and the fix):** I trusted a synthetic-data micro-profile over a real-data full-stage measurement. That is *exactly* what Codex's **A0 perf harness** prevents — so A0 is step one and non-negotiable.

### One thing my round-2 idea got wrong too (resolved here)
I proposed "stop recomputing the full 25-year history; compute only the latest week." **I checked the consumers first-hand — this is not viable as a primary approach:**

- The Tool A *output* (`tool_a_latest.parquet`, 60 rows) reduces to the latest `as_of` per ticker (`pipeline.py:239-240`), so the **output** alone needs only the latest week. **But** the persisted full history (`tool_a_structural_latest.parquet`, 179,562 rows) is read by the **detail-page beta-over-time chart**: `_load_structural_delta_history` (`golden_vector/serve/workspace_state.py:289+`) reads **all** `as_of_date` rows per ticker/window (no date floor, no `.tail()`) to draw the 6M/12M/3Y beta-history lines (`detail_panels.py:1451` and the chart panel).
- **Therefore the history is genuinely needed, and we must make computing it fast (Codex's vectorization) rather than skip it.** Skipping would silently empty the chart — a Golden Vector "no silent breakage" violation.

The bounded/incremental variants of my idea survive only as a **future, optional** lever — see §5. They are *not* in the primary path.

---

## 1. Re-measured profile (Codex's numbers, accepted)

| Area | Cost | Note |
|---|---:|---|
| Tool A structural/window metrics | 136.4s | `compute_structural_window_metrics` 115s |
| Tool A volatility diagnostics | 86.2s | `compute_volatility_diagnostics` 86.1s |
| **Total in-memory Tool A** | **222.6s** | ≈ the recorded `update_data` stage |
| `update_data` (fetch + foundation + options) | 220.9s | fully serial Yahoo fetch |
| `_window_bounds` / `_window_start` | 75.7s / 71.4s | 179,562 `DateOffset` constructions in a Python list-comp |
| `np.std` stack (volatility) | 30.0s | tiny per-row std calls |
| `_build_volatility_anchor_rows` | 27.0s | `.itertuples()` |
| `_summarize_normalization_issues_by_as_of` | 12.0s | repeats 3yr calendar math per as_of |
| `build_structural_weekly_series` | 21.1s | weekly resample/log-returns |
| Tool C / D / B | 13.0s / 3.2s / 2.4s | not first-order |

**Tool A (~222s) and the fetch (~221s) are co-dominant.** Both must be fixed to get the refresh under ~2 min. Fix Tool A first (it's pure local CPU, output-identical, low external risk), then the fetch.

---

## 2. Phase A — Tool A CPU (do first; output-identical; test-pinned)

### A0 — Repeatable real-data perf harness *(do this first)*
A small CLI/script that loads the **cached** local foundation snapshot (no Yahoo call) and times + prints **row counts** for: structural build, volatility diagnostics, option scans/artifacts, and total compute. Run it before/after every A-step. This is the guardrail against "synthetic says 7s, real says 223s" drift that broke my round-2 plan.

### A1 — Centralize calendar trailing-start arrays
`_window_start` is **179,562 calls / 71.4s**. Replace the per-row list-comp in `_window_bounds` with **one vectorized trailing-start computation over the full `DatetimeIndex`**, and **reuse the same helper in `_summarize_normalization_issues_by_as_of`** (folds in its 12s — Codex F5).
- **Preserve calendar semantics exactly:** `12M`/`1Y`/`3Y` are `DateOffset(months/years)`, NOT fixed day counts. Leap-day, month-end, and the existing `searchsorted(..., side="right")` strict-greater boundary must stay pinned. A "convert months to days" shortcut would be wrong.
- **Gate:** existing structural reference-loop parity **+ explicit asserts** for leap-day, month-end, and a window-start landing exactly on a prior week date.
- Refs: `structural.py:523`, `:690`, `:1193`.

### A2 — Volatility diagnostics via prefix sums (NOT `groupby().rolling()`)
Codex F3 is correct and supersedes my round-2 `groupby.rolling(52)` suggestion. Total/downside vol are count-based trailing 52-week windows, but **residual vol depends on each anchor row's own alpha/beta** — a plain rolling can't express that. Use prefix sums over each ticker's weekly arrays:
- total vol: stock count / Σ / Σ²;
- downside vol: negative-stock count / Σ / Σ²;
- residual vol: paired gold/stock `n, Σx, Σy, Σxx, Σxy, Σyy` → variance of `y − (alpha + beta·x)` under the **row-specific** alpha/beta.
- Preserve the current `searchsorted(side="right")` membership (handles anchor `as_of` not exactly present in the weekly series — do **not** switch to an exact merge).
- **Gate:** old-reference parity at **1e-12** PLUS Codex F4's four edge cases: (a) anchor date falls *between* two weekly dates; (b) alpha/beta missing → residual vol stays `None` while total/downside still compute; (c) fewer than two valid residual observations → `None`; (d) sparse-calendar stretch.
- Refs: `structural.py:831`, `:893`, `tests/test_structural.py:436`.

### A3 — Reprofile before touching Yahoo (Codex F6)
Do **not** assume Phase A → 1.5s. After A1+A2, re-run A0. If Tool A is still >30–45s, inspect `build_structural_weekly_series` (21s), `_compute_vectorized_window_metric`/`_ols_metric_at` (~20s), and output assembly **before** moving to Phase B. Only when Tool A is genuinely small do we declare the fetch the sole remaining wall.

---

## 3. Phase B — the fetch (~221s → ~1 min); external-API risk → confirm before merge

### B1 — Shared bounded Yahoo concurrency + global rate limiter
Foundation fetchers are fully serial (`foundation.py:57`, `fetch_equities.py:22`, `fetch_market_snapshot.py:26` — 2 round-trips/ticker). Per-ticker isolation already exists (each has its own try/except + `FetchStatusRecord`), so a bounded thread pool is safe.
- **Codex F7 (accepted, replaces my "4–8 workers"):** start at **3–4 workers**; put a **global no-burst limiter around every Yahoo call inside `YahooClient`** (not a per-call sleep); config flags for `max_workers` and min inter-request interval; retry backoff **with jitter**; **the limiter must apply before retries too**, not only after successful calls.
- **Tests (fake Yahoo client):** bounded in-flight calls, deterministic output order, per-ticker failure isolation, shared rate limiting.
- **Foundation first**, then re-measure. **External API → confirm with Emanuel before merge; validate on one real refresh.**
- Refs: `foundation.py:57`, `fetch_equities.py:22`, `fetch_market_snapshot.py:26`, `collection_resilience.py:52`, `yahoo_client.py:28`.

### B2 — Targeted-expiry: a data-contract DECISION, not a default flip (Codex F9)
`options_phase.py` loops serially over 62 option targets; targeted fetch would cut per-ticker round-trips from 10–20+ to ~3–6 — real fetch savings. **But** it changes the persisted aggregate option features (§0 item 2). So **decide explicitly**, don't just set `targeted`:
- **Option (a):** redefine the aggregates as *"within the configured option DTE bands,"* rename/document them, and add parity tests on the **candidate outputs** (not just raw chain).
- **Option (b):** keep full-chain fetch for aggregate context, use targeted only for the candidate-oriented refresh path.
- This is a product/data choice for Emanuel — present both before implementing.
- Refs: `features/options.py:64-225`, `fetch_options.py:276`, `config_models.py:117`.

### B3 — Apply the bounded primitive to options fetch *after B2 is settled* (Codex F8)
Don't multiply Yahoo request pressure before B2 reduces expiration count. Sequence: foundation parallel (B1) → re-measure → B2 decision → then options fetch reuses the same bounded/limited primitive.

---

## 4. Phase C — minor cleanup (last; optional)
### C1 — Drop the options write-then-read round-trip
`options_phase.py:147` persists each snapshot, then `:300` re-reads the same parquet per ticker. Pass `result.frame` directly to feature computation; keep persisting the immutable snapshot; **test that the persisted frame equals the in-memory frame** (column order included). Low risk, small win — does not outrank A1/A2 or the fetch (Codex F10).

---

## 5. Secondary lever (FUTURE / optional — NOT in this build)
My "don't recompute the whole history" idea, correctly scoped after the consumer check:
- **Latest-only:** ❌ ruled out — the beta-history chart reads all `as_of` rows.
- **Bounded history:** viable *only if* Emanuel accepts the beta chart showing a recent window (e.g. last 8–10 yrs) instead of the full ~25 yrs. Clean proportional row cut, low complexity — but it's a **visible product change** to the chart. Ask before doing.
- **Incremental append:** preserves the full chart and turns O(all weeks) into O(new weeks) — **but** Yahoo *adjusted close* re-adjusts the entire back-history on splits/dividends, so a naive append drifts from a full recompute. Needs an invalidation strategy (detect upstream change → full recompute; else append). Real complexity.

**Recommendation:** ship Phase A vectorization first (safe, output-identical). Revisit §5 only if A1/A2 + B1 don't get the refresh comfortably under ~2 min, and only as an explicit product decision.

---

## 6. Final agreed sequence & gates
1. **A0** perf harness (real cached data; row counts + timings).
2. **A1** centralized calendar trailing-starts → `_window_bounds` + normalization summaries. Gate: structural parity + leap/month-end/boundary asserts.
3. **A2** prefix-sum volatility (row-specific residual alpha/beta). Gate: old-ref parity 1e-12 + 4 edge cases.
4. **A3** reprofile; chase remaining Tool A CPU only if still >30–45s.
5. **B1** shared bounded concurrency + global limiter, foundation only, 3–4 workers, jitter, limiter-before-retry, fake-client tests. **Confirm w/ Emanuel; validate on a real refresh.**
6. **B2** targeted-expiry **decision** (a or b) before any default change; parity tests on candidate outputs.
7. **B3** bounded concurrency for options fetch after B2.
8. **C1** drop options write-then-read.

**Every CPU change (A1, A2) keeps an old-vs-new parity test at the existing tolerance** (this math feeds Tool C and the whole stack). Fetch/IO changes (B1, B2, B3, C1) are validated by a real refresh + existing option parity tests.

## 7. Net expected outcome
- After Phase A: Tool A ~222s → target ≤ ~30s (A1 removes ~83s of `_window_start`/normalization; A2 removes most of the 86s volatility; reprofile decides the rest).
- After Phase B: fetch ~221s → ~40–70s.
- **Refresh target: well under ~2 min**, down from ~70 min — with **zero change to Tool A math** (parity-pinned) and an explicit decision on option aggregates.

---
### Self-assessment
Grounded in Codex's real-data profile (accepted over my synthetic one) + a first-hand consumer check that *resolved* the open "do we need the history?" question (yes — the beta chart reads all of it), which is why vectorization, not skipping, is the right primary path. The two genuine judgment calls left for Emanuel: B1 (external-API risk → confirm) and B2 (option-aggregate data-contract → product decision). Everything else is low-risk and test-pinned. Ready for Codex to review/build.
