# Plan — Kill the Tool A output-assembly bottleneck (27.5 min → seconds) + make this class of bug impossible to miss again

**Author:** Claude Code (Opus 4.8)
**Status:** for Codex review (please criticise, like the round-2/round-3 reviews), then build.
**Measured:** after B1/B3, the refresh is ~30m38s. **Tool A stage = 27m37s.** Foundation fetch 1m47s (B1 ✅), Tool B/C/D 9s/30s/7s, options 27s (B3 ✅). The remaining wall is entirely Tool A.

---

## 1. Root cause (measured, not reasoned)
`_build_tool_a_outputs` (`golden_vector/model/pipeline.py:236`) loops `for (ticker, as_of_date), frame in grouped:` over **every ticker × every historical week** ≈ **60,000 groups**, each doing heavy per-group work (5× `_window_value_map` + `weighted_median`, stability/confidence scoring, `choose_structural_anchor_window`, component scores, and a slow per-group `volatility_index.loc[(ticker, as_of_date)]` MultiIndex lookup at `:349`).

**Direct measurement:** 6 tickers → `_build_tool_a_outputs` = **171.89s** (5,972 rows) → extrapolates to **28.6 min** for 60 tickers. Matches the observed 27.5-min stage.

**The waste:** `persist_tool_a_outputs` (`ingestion/persist.py:222`) immediately calls `_latest_snapshot(...)` which keeps **only the most-recent row per ticker (~60 rows)** and discards the other ~59,940. So we spend ~28 minutes building 60,000 rows and throw away 99.9% of them. The structural-metric history that the detail-page beta chart needs is a *different* artifact (`tool_a_structural_latest.parquet`, already built cheaply) — the tool_a **outputs** history is built and discarded.

## 2. The fix — build outputs only for the as_of dates that survive `_latest_snapshot`
`_latest_snapshot` keeps each ticker's latest `as_of_date`. The only output rows that survive are at the set **D = { max(as_of_date) per ticker }** — normally **1 date** (the latest weekly bar shared by all 60), occasionally 2–3 when a ticker lags a week behind from a normalization gap.

So: **restrict `_build_tool_a_outputs` to only the as_of dates in D, building the full cohort at each.** Concretely, before the group loop:
```python
latest_per_ticker = metrics.groupby("ticker")["as_of_date"].transform("max")
survivors = metrics["as_of_date"].isin(set(metrics.groupby("ticker")["as_of_date"].max()))
metrics = metrics[survivors]   # then group + build as today
```
Group count drops from ~60,000 to |D|×~60 ≈ **60–180**. Estimated **~28 min → < 1s.**

### Why this is output-identical (the parity argument — verify it, Codex)
- Ranking is **within `as_of_date`** (`scoring.py:108`, `.groupby("as_of_date").rank()`). For each date `d ∈ D`, we still build the **full cohort** present at `d` (every ticker has a row at `d` because each ticker has rows at every historical week up to its own max), so the within-`d` ranks are identical to the full-history build.
- Every as_of date **not** in D is discarded by `_latest_snapshot` in the current code, so not building those rows changes nothing downstream.
- Therefore `_latest_snapshot(build_all)` == `_latest_snapshot(build_restricted)`, row-for-row, rank-for-rank — including the lagging-ticker case (laggard comes from its own date `d`'s full cohort; non-laggards from the global-max date's cohort), exactly as today.

**Why not the naive options:** "build only global-max as_of" would drop a lagging ticker (re-introducing the exact 60→59 bug `_latest_snapshot`'s docstring says they fixed). "Build each ticker's latest row in isolation" would mis-rank laggards (wrong cohort). The D-set approach avoids both.

## 3. Parity gate (the guardrail — this changes the headline rankings + feeds Tool C)
- Keep the current full-build as a reference; assert `_latest_snapshot(reference)` equals `_latest_snapshot(new)` to `atol=1e-9` for floats, exact for ranks/labels/statuses/`as_of_date`, same row set/order.
- **Fixtures must include a lagging ticker** (one ticker whose latest weekly bar is a week behind the rest) so the laggard cohort/rank path is pinned — plus the normal all-aligned case.
- Re-run the full suite (Tool A + Tool C, which consumes Tool A latest).

## 4. Consumer safety (confirm, mostly verified)
- Persisted output = `_latest_snapshot` only (latest per ticker) — `persist.py:229`.
- Combined join asserts **unique per-ticker keys** (`combined/join.py:16`) — would fail on multi-week history, proving only latest flows downstream.
- Tool C / Candidate Finder / overview read the persisted latest parquet (60 rows), not the in-memory history.
- Confirm nothing reads the in-memory full `tool_a_outputs` frame returned by the pipeline before persist.

## 5. Scope / non-goals
- In scope: restrict the group set in `_build_tool_a_outputs`; same per-row math; same columns; same ranking. Pure waste-elimination, output-identical.
- Out of scope: changing any score/eligibility/ranking formula, the structural-metrics history build (needed by the beta chart — leave it), or the persisted schema.

---

## 6. PREVENTION — so "30 minutes and we don't know why" can't happen again
This bug survived three rounds of perf work because **every measurement was a proxy** (my synthetic 7s; Codex's cProfile-inflated 222s; the A0 harness's ~10s that silently skipped `_build_tool_a_outputs` + persist). The real refresh log had the truth the whole time. Fix the *system*, not just this function:

- **P1 — Per-step timing inside the REAL pipeline, persisted to the manifest.** Wrap each sub-step of `execute_tool_a_profile_pipeline` (structural build, persist structural, volatility, **output assembly**, rank, persist outputs) in a timing helper that logs `step / seconds / rows_built / rows_persisted` and writes the breakdown into the run summary + model-state manifest. Then every real run self-reports where the time and rows went — no harness, no guessing. Apply the same helper to the other tool pipelines. **This is the core guarantee.**
- **P2 — The perf harness must run the FULL stage and reconcile.** `perf_profile.py` should drive the actual pipeline path (include `_build_tool_a_outputs` + persist), and compare its total against the manifest's recorded `tool_a` stage time — **warn loudly if they diverge >~15%.** A harness that omits a step is worse than no harness (it gives false confidence). No more proxy timings.
- **P3 — Build-vs-keep waste guard.** Log `rows_built` vs `rows_persisted` per stage; emit a warning when the ratio is large (e.g. >5×). 60,000 built / 60 kept = 1000× would have screamed on the first slow run.
- **P4 — Reconcile-on-disagreement rule (process).** When two measurements disagree (harness vs manifest, agent vs agent), the disagreement IS the finding — trace it to the real run before optimizing anything.

---

## 7. Self-review
- The diagnosis is **measured** (171.89s/6 tickers → 28.6 min, matches the 27.5-min stage), not inferred — addressing the exact failure (trusting proxies) that hid it.
- The fix is **provably output-identical** via the D-set + within-as_of-ranking argument, with the lagging-ticker edge explicitly handled and gated.
- The prevention (P1 especially) makes the whole *class* of "unmeasured stage / build-and-discard" bug self-evident on every future run.
- Risks: (a) the laggard cohort claim — Codex should adversarially check a multi-laggard, multi-distinct-date fixture; (b) confirm no consumer of the in-memory full frame. Both are test-catchable. Ready to build after review.
