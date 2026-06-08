# Claude review — Codex Option Signals Milestone 1

**Reviewer:** Claude Code (Opus 4.8), first-hand + **empirically verified on live data** (ran the signal build, triggered the fail-closed guard, inspected the residuals).
**Scope reviewed:** the uncommitted working-tree M1 — `option_signals.py` (+839), `option_signal_render.py`, the wiring across config/contracts/serve/cli, + tests (~1,636 lines). **Full suite: 792 passed.**
**Verdict: APPROVE — strong, faithful to the v2 plan.** One spec deviation to address (asymmetry), plus two confirm-items. None block; all are quick.

## Verified first-hand (the load-bearing parts)
- **Sector-relative skew is the headline, correct.** `residual_{h} = name iv_skew_{h} − benchmark iv_skew_{h}`; single names use the **60d residual**, GDX/GDXJ use **absolute** skew (residual-vs-self = 0). Threshold ±0.03. (`option_signals.py:165-172`)
- **4 transparent lanes, no black-box composite** — Direction / Activity / Cost / Data Quality, each with value + label + **reason**. (`_summary_row`)
- **Deterministic benchmark rule** — config `option_benchmark_symbol`, else junior (`.V`/TSXV) → GDXJ, else GDX. No UI inference. (`_benchmark_map`, `_default_benchmark`)
- **Signal-area coverage** measured on **45–150 DTE / 10–35Δ / sane IV / nonzero underlying**, separate from raw-chain coverage. (`_signal_area_metrics`)
- ⭐ **Fail-closed on the benchmark — verified live.** `_publish_blockers` keys on GDX/GDXJ (missing OR `data_quality_label != OK`); the CLI then `return 1` **before any persist**, keeping the previous complete model state with a "run refresh during US market hours" message (`cli.py:1543-1558`). A stale **single-name** row is marked unavailable (`STALE_QUOTES`/`SPARSE`/`LOW_LIQUIDITY`/`NO_BENCHMARK`) **without** blocking the universe. I ran it on the current pre-market data → `publish_blockers: GDX=SPARSE; GDXJ=SPARSE … keeping the previous complete model state`, everything UNAVAILABLE/SPARSE. **No silent garbage.**
- **OI = honest confirmation** — compared **session-over-session** against `prior_contract_metrics`, matched by **stable contract identity** (`(ticker, expiry, type, strike)` tuple), unsigned. No fake bucket-roll changes. (`_prior_metrics_by_contract`)
- **Backend-only** — the serve layer (`option_signal_render.py`, `detail_panels.py`, `overview_option_trading.py`) only **reads** persisted signal fields; no skew/coverage/IV/OI math added in the request path. (The `residual_volatility` references are the pre-existing Tool A vol, not this work.)
- **Artifacts + migration** — 4 new registered (`option_signal_summary`, `option_skew_curve_points`, `option_oi_strike_points`, `option_signal_history_points`); `OPTION_ARTIFACT_SCHEMA_VERSION` bumped 1→2; the reader validates schema_version + required columns and **raises** on mismatch (`option_trading_data.py:527-549`).
- **History store** — append-only `option_signal_history.parquet`; IV-rank gated by **≥20 samples** else `LIMITED_HISTORY`; **protected from pruning** (test `test_prune_runs_preserves_option_signal_history_store`).
- **Normalized chart data** — skew curve bucketed by **delta**, not raw strikes.
- **Targeted tests** — sector-relative skew, benchmark-is-gauge-not-self, missing/stale-benchmark-blocks-publish, single-name-doesn't-block, IV-rank-min-history, refuses-empty-benchmark, history-preserved-by-pruning.

## Findings

**F1 — MEDIUM: the asymmetric bearish/bullish reads aren't implemented.** `_direction_label` is a **symmetric** threshold: `residual ≥ +0.03 → DOWNSIDE`, `residual ≤ −0.03 → UPSIDE` (`option_signals.py` `_direction_label`). The v2 plan §4 (and your own v1 review) called for *two interpretations with different evidence bars* — equity skew is structurally downside-biased, and the bullish/UPSIDE read should need extra confirmation (call activity), not the mirror-image bar. **Mitigation already present:** because the label runs on the **sector-relative residual** (structural skew subtracted), a symmetric threshold is far more defensible than on absolute skew. **Recommendation:** either (a) hold UPSIDE to a higher bar / require call-side activity confirmation before labeling UPSIDE, or (b) consciously accept the residual-symmetric design and document it. Right now the Activity lane is shown but does **not** gate the direction differently per side.

**F2 — LOW: confirm the read-side schema-mismatch renders a friendly page, not a 500.** The fail-loud guard (`option_trading_data.py:549 raise ValueError`) is correct, but confirm the workspace catches it and shows a calm "your option data is from the previous version — run refresh" page (like the Tool B stale guard), so a post-migration old artifact doesn't surface as a raw 500.

**F3 — LOW/verify: a couple of edge tests.** The 8 targeted tests cover the critical paths well. Worth adding: OI-change when there's **no prior snapshot** (first run → `oi_change_valid=False`, not a crash) and an **asymmetric-label** test once F1 is decided.

## Correctly scoped OUT of M1 (good)
Scheduler (M2), row-level stale carry-forward, volatility-surface modeling — none built, as agreed.

## Bottom line
This is a careful, faithful M1: sector-relative skew as the headline, the four transparent lanes, fail-closed on the benchmark (proven live), honest OI-by-contract confirmation, backend-only, normalized charts, schema-version migration with a fail-loud read guard, and a pruning-protected history store — all green (792). Address **F1** (the asymmetry — decide: enforce it or document the residual-symmetric choice), tidy **F2/F3**, and this is READY. Then proceed to Milestone 2 (the market-hours scheduler).
