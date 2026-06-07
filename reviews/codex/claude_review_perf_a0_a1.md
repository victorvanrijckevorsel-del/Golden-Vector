# Claude review — Codex checkpoint A0 + A1 (perf round 3)

**Reviewer:** Claude Code (Opus 4.8), first-hand (read every changed file, ran the harness, independently verified the math).
**Scope:** `golden_vector/app/perf_profile.py` (new), `golden_vector/cli.py`, `golden_vector/model/structural.py`, `tests/test_structural.py`.
**Verdict: APPROVE A0 + A1.** Correct, output-identical, real speedup. One honest correction to the baseline framing (below), and a clear recommendation: **skip A2, go straight to B1.**

---

## Headline finding — the "222.6s" baseline was profiler-inflated

I measured pre-A1 vs post-A1 with the **same harness** (`perf_counter`, no profiler), by temporarily reverting only `structural.py`:

| Stage | Pre-A1 (HEAD 84700ac) | Post-A1 | A1 effect |
|---|---:|---:|---|
| structural build | **19.48s** | **4.74s** | −14.7s (~4×) ✅ |
| volatility diagnostics | 5.82s | 5.86s | unchanged (correct — A1 doesn't touch it) |
| Tool A compute | 25.30s | 10.60s | −14.7s (2.4×) |
| total cached profile | 28.80s | 14.52s | — |

**Tool A was never ~222s in wall-clock.** Codex's round-3 baseline (`222.6s`, structural 136s + volatility 86s) came from a cProfile run — the "cumulative time" table is pstats output, and cProfile adds large per-call overhead to functions called ~180k times. The tell: volatility "dropped" 86.2s → 9.63s in Codex's own A1 result **even though A1 never modified `compute_volatility_diagnostics`**. Clean wall-clock: volatility was ~5.8s all along.

**What this means for the plan:**
- The big Tool A win was the earlier vectorization (commit `85936c2`): the old nested loop took **65 minutes** in the 2026-06-05 refresh → ~25s clean. A1 is a solid incremental on top (25s → 10.6s).
- **The refresh is, and always was, fetch-dominated.** Real `update_data` = 220.9s (manifest, unprofiled). Tool A clean = ~10.6s. Fetch is ~20× Tool A. (My round-2 "fetch-dominated" *conclusion* was right even though my synthetic 7s number was wrong; Codex's real-data measurement was right to distrust my 7s, but the profiler made the absolute numbers ~9× too high.)
- A0 paid for itself immediately by exposing this. **Rule going forward: A0's `perf_counter` numbers are the single source of truth for headline timings; use cProfile only for *relative* hotspot ranking, never for absolute stage costs.**

---

## Q1 — Is A0 read-only and a useful real-data harness? **Yes.**
- **Read-only, verified:** no `RunContext`, no `persist`/`to_parquet`/`write`/`record_artifact`/`mkdir` calls in `perf_profile.py`; loads the cached foundation snapshot (`include_market_snapshots=False`), composes the real compute functions in memory, and option artifacts via `load_option_artifact_source_inputs(use_model_state=False)` + the real builders with throwaway `source_run_id="perf-profile"`. Prints "No Yahoo calls; no model artifacts written." Confirmed by running it.
- **Representative:** processes the identical workload — 179,562 structural rows, 59,854 weekly/volatility rows (matches the real run exactly), same 60 active+tool_a_enabled tickers, same functions.
- **Useful:** stage breakdown + slowest-ticker list + option-artifact sub-timings + total; `--json` for diffing; graceful "missing" path when no options manifest. Good design choice using `perf_counter` (wall-clock) over cProfile.

## Q2 — Does A1 preserve calendar semantics exactly (6M/12M/3Y, leap-day, month-end, strict `side="right"`)? **Yes — proven.**
The whole refactor reduces to one invariant: `_window_start_values(dates, w)` (vectorized `DatetimeIndex − DateOffset`) must equal the scalar `[_window_start(d, w)...]` loop. Everything downstream (`searchsorted(side="right")`, boundaries) is unchanged.
- **I verified bit-identity across 4,762 dates** (every calendar day 2014–2026 + leap-days, month-ends, year boundaries) × 8 windows incl. 6M/12M/3Y. **Zero mismatches** (pandas 3.0.2). Month-end clamping (e.g. 2021-03-31 −1M → 2021-02-28) and leap-days handled identically by the vectorized path.
- The refactor is clean: `_window_start` and `_window_start_values` both delegate to a new `_window_offset(window_id)` — single source of the offset, two application shapes.
- `_summarize_normalization_issues_by_as_of` now reuses `_window_start_values(..., "3Y")` (plan F5 — folded in correctly), with `zip(..., strict=True)` guarding length.

## Q3 — Are the tests sufficient? **Yes as a gate; one cheap enhancement recommended.**
- The broad parity test (`test_compute_structural_window_metrics_matches_reference_loop`) is a **genuine scalar-vs-vector** comparison: the reference oracle builds windows via `build_trailing_window_rows` (scalar `_window_start`), production uses vectorized `_window_bounds`/`_window_start_values`; compared at `atol=1e-9`. It passes.
- The new `test_trailing_window_calendar_boundaries_are_exact` pins **absolute** expected values for: leap→non-leap clamp (2024-02-29 −1Y → 2023-02-28), day-of-month preserved into a leap year (2025-02-28 −1Y → 2024-02-28, *not* Feb 29), month-end, and the strict `side="right"` boundary where the window-start lands exactly on a weekly date (excluded) with next-day included — for both a leap and a month-end boundary. Well-targeted, matches the plan's A1 gate.
- **Recommended (low priority, not a blocker):** add a parametrized test asserting `_window_start_values(date_range, w) == [_window_start(d, w)...]` over a multi-year daily range for 6M/12M/3Y, so the vectorized==scalar invariant is locked broadly against a future pandas upgrade (right now it's only pinned on the fixture dates + my ad-hoc sweep, which isn't committed).

## Q4 — Skip/defer A2 and move to B1? **Yes — emphatically. Tool A CPU is done; B1 is the only thing that matters.**
- Clean Tool A is ~10.6s (structural 4.7s + volatility 5.9s). The plan's A3 gate ("chase Tool A only if still >30–45s") is satisfied — we're far below it.
- A2 would cut volatility ~5.9s → ~1–2s, saving ~4s of a **~4-minute** refresh. That is noise. Defer it (keep it documented as an optional later polish; it's cheap and parity-able if ever wanted).
- **~221s of the ~240s refresh is the serial Yahoo fetch.** Go straight to **B1** (shared bounded concurrency + global limiter), per the round-3 plan: 3–4 workers, limiter inside `YahooClient`, jitter, limiter-before-retry, fake-client tests, foundation first, **confirm with Emanuel before merge (external API), validate on one real refresh.** This is the single change that gets the refresh toward ~1.5 min.

## Q5 — Cleanliness / duplication / architecture concerns before commit?
1. **Honest-baseline framing (most important — process, not code):** the round-3 plan's "Tool A ~222s, co-equal with fetch" was a profiler artifact. Update the shared mental model: Tool A ≈ 10.6s, fetch ≈ 221s. Don't let the inflated number justify further Tool A CPU work. (No code change — just stop quoting 222s.)
2. **Duplication (LOW now):** `perf_profile.py:56–92` re-implements the structural-build loop from `pipeline.py:135–159` (per-ticker `build_structural_ticker_data` → concat window metrics + weekly series). Divergent copies risk the harness silently measuring a stale path — the exact failure mode that started this saga. Suggest extracting a shared helper (e.g. `build_structural_frames(tickers, snapshot, scoring) -> (window_metrics, weekly_series)`) called by both. Severity is low *now* because Tool A compute is effectively frozen, but it's worth a quick cleanup. (Per the review rule I am **not** changing code mid-review — flagging only.)
3. **Minor nits (optional):** `slowest_tool_a_tickers[:10]` caps the list — fine for the human view, but consider emitting all 60 in `--json` so nothing is hidden from analysis. The option-artifact section composes the real builders (good — low duplication risk there).

---

## Bottom line
A0 + A1 are correct, output-identical (proven), read-only, and a genuine ~4× structural win — **approve and commit.** The one correction: Tool A was never the 222s co-bottleneck; clean wall-clock it's ~10.6s and the fetch (~221s) dominates. So **skip A2 and move to B1 (parallel fetch)** — that's the only remaining change that materially shortens the refresh.
