# Performance — what Codex did + Round 2 plan

**Author:** Claude Code (Opus 4.8)
**Reviewed:** the uncommitted working-tree perf changes (structural.py, options_liquidity.py, option_artifact_builder.py, cli.py + tests), first-hand + 3 adversarial deep-dives + full suite.

## What Codex already did (verified, output-identical, parity-tested)
1. **Tool A vectorization (the big one).** `compute_structural_window_metrics` rewritten with **prefix-sums + `searchsorted`** (calendar-exact windows, exactly as planned). **Measured ~65 min → ~7s.** It is **output-identical** to the old loop — proven by a real old-vs-new parity test at `atol=1e-9` (old loop kept as a reference oracle), covering gaps, `nan`/`inf`, an exact leap-year boundary landing, regime gates, and all `None`/status edge cases. Codex even added the **catastrophic-cancellation fallback** I flagged as a risk in the plan's self-review (`_needs_centered_window_fallback` → exact `compute_regression` on the raw slice). 8 structural tests green.
2. **Options-scan consolidation.** The build previously scanned each chain ~4× (puts slots, calls slots, liquidity, contract-metrics). Now it scans **once per chain** (`scan_option_chains_for_artifacts`) and reuses the `OptionChainScan` everywhere. Behavior-preserving — parity test extended (with-vs-without precomputed scans) + a no-rescan test; 30 option tests green.
3. **Full suite: 758 passed, 0 failed, 0 skipped.**

**Action first:** this work is currently **uncommitted** and is verified-correct + green — **commit and push it** before starting Round 2 (don't leave a 1,200-line verified change sitting in the working tree).

## The new bottleneck profile (after Codex's work)
Tool A is no longer the problem. Measured at full scale (60 tickers × full weekly history):
| Stage | Now | Note |
|---|---|---|
| **update-data / Yahoo fetch** | **~3.5 min** | **fully serial** — now the dominant cost |
| Tool A structural metrics | ~7s | of which ~5s is leftover `_window_start` date math (#A1) |
| `compute_volatility_diagnostics` | ~5.4s | **still a per-row Python loop** (not vectorized) (#A2) |
| options build | ~32s | scans consolidated; still fetches **all** expirations (#B2) |
| Tool B / C / D | ~2s / 13s / 4s | fine, not worth touching |

**The refresh is now fetch-dominated.** So the biggest remaining *wall-clock* win is parallelizing the fetch — the CPU items are smaller polish.

## Round 2 plan (sequenced by value × safety)

### Phase A — low-risk CPU polish (finish the structural step) — do first, cheap & safe
- **A1. Vectorize `_window_start`** (`structural.py:1193`, called per-row in `_window_bounds` ~`:529-535`). It constructs ~93,600 `DateOffset`s in a Python list comp — the single largest leftover CPU cost in the "vectorized" path (~3.4s self / 8.6s cumulative). Compute all trailing-start dates with a vectorized offset over the `DatetimeIndex` instead of per-element. **Risk: low** — pure date arithmetic, must preserve month/year calendar semantics; the existing structural reference-loop parity test pins it. Est. ~5s → <0.5s.
- **A2. Vectorize `compute_volatility_diagnostics`** (`structural.py:831`, the per-(ticker,as_of) loop calling tiny `np.std`s + `_build_volatility_anchor_rows` `.itertuples()`). Replace with `groupby("ticker").rolling(52)` for total/downside/residual vol, merged onto anchor rows. **Risk: medium** — the residual-vol path and the `<2 valid obs → None` edges must match exactly; a reference-loop parity test already exists (`test_compute_volatility_diagnostics_matches_reference_loop`). Est. ~5.4s → ~1s. **Gate: old-vs-new parity at 1e-9 (1e-12 for vol, matching the existing tolerance).**

Phase A together: structural CPU ~12s → ~1.5s. (Small in absolute terms now, but cheap, low-risk, and it finishes the job cleanly.)

### Phase B — the real wall-clock win: the fetch (~3.5 min → ~1 min)
- **B1. Parallelize the Yahoo fetch with bounded concurrency.** The fetchers (`foundation.py:57-64`; `fetch_equities.py`, `fetch_market_snapshot.py` which does 2 round-trips/ticker) run fully serial, ~180+ network round-trips back-to-back. Each ticker already has its own try/except + `FetchStatusRecord`, so **per-ticker isolation is preserved** under a thread pool. Use a `ThreadPoolExecutor` with a **small global cap (4-8 workers)** plus a **shared rate limiter** (replace the per-call 0.15s sleep with a global token-bucket so total request rate stays gentle). Est. **3-6× → ~40-70s.**
  - **Risk: medium, and external.** Yahoo/yfinance is unofficial and rate-limits/soft-bans aggressive callers. So: cap concurrency, keep a global rate limit, keep per-ticker best-effort isolation, and **validate against a real refresh** (not just unit tests) before shipping. Per the project rule, this touches a live external API → confirm with Emanuel before merging. **This is the milestone that actually gets the refresh under ~2 minutes.**
- **B2. Targeted expiry fetch (complements B1).** `options_expiry_fetch_mode` defaults to `"all"` (`config_models.py:117`), so every listed expiration is fetched, but only the 3 horizons (60/90/120d) are used. Set `options_expiry_fetch_mode: targeted` in `config/hedge_readiness.yaml` (the `_selected_expirations` band logic already exists, `fetch_options.py:276-296`). Cuts per-ticker option round-trips from 10-20+ to ~3-6. **Risk: medium** — it changes the *persisted raw option snapshot* (fewer expirations), though derived features should be equivalent; **validate against a real refresh** + confirm the option candidates are unchanged (the existing option parity test + a real-data spot check).

### Phase C — minor cleanup (optional, low priority)
- **C1. Drop the options write-then-read round-trip** (`options_phase.py:138` persists then `:300` re-reads the same parquet per ticker). Pass `result.frame` directly to feature computation. **Risk: low** — confirm the persisted frame equals `result.frame` (column order). Small win.
- Tool C's repeated `pd.to_numeric` re-conversions + `.apply(axis=1)` (relative_behavior / tool_c) — only ~60 rows, ~13s; **not worth it now**.

## Recommended sequence & gates
1. **Commit/push Codex's current verified perf work** (Tool A vectorize + options consolidation).
2. **Phase A** (A1 then A2) — cheap, low-risk, each gated by the existing structural/volatility reference-loop parity tests at 1e-9/1e-12.
3. **Phase B1** (parallel fetch) — the big wall-clock win; bounded concurrency + global rate limit + per-ticker isolation; **validate with a real refresh; confirm before merge (external API).**
4. **Phase B2** (targeted expiry) — config flip; validate against a real refresh + option parity.
5. (Optional) **Phase C1**.

**Every CPU change (A1, A2) must keep an old-vs-new parity test at the existing tolerance** (these feed Tool C and the whole stack). The fetch/IO changes (B1, B2, C1) are validated by a real refresh + the existing option parity tests, since they're I/O not math.

## Net expected outcome
After Phase A+B: refresh ≈ **~1.5-2.5 minutes** (fetch ~1 min, Tool A ~1.5s, volatility ~1s, options reduced, B/C/D ~20s) — down from ~70 min. The single highest-leverage remaining item is **B1 (parallel fetch)**; the CPU items are quick, safe finishing touches.

---
## Self-assessment
This plan is grounded in measured profiling (not guesses): each item has a file:line, an estimated impact, and a risk level. The sequencing is right — do the cheap/safe CPU polish (A) first, then the high-value-but-external-risk fetch parallelization (B) with real-refresh validation and a confirmation gate. The one judgment call is B1's risk: parallel calls to an unofficial API can trigger throttling, so the design must be *bounded concurrency + global rate limit*, not "remove the sleep" — and it must be proven on a real refresh, not just unit tests. Everything else is low-risk and test-pinned. Ready for Codex to review.
