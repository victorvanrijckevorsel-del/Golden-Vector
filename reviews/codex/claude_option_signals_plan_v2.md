# Plan v2 — Symmetric option-chain signals (build-ready)

**Author:** Claude Code (Opus 4.8)
**Status:** for a final Codex confirm, then build. Supersedes `claude_option_signals_plan.md`.
**Incorporates:** Codex's review `codex_review_claude_option_signals_plan.md` (graded v1 NEEDS CHANGES — accepted in full). The concept is unchanged; this version locks the parts that make the signal *trustworthy*: artifact contracts, sector-relative headline, honest OI semantics, fail-closed stale handling, history/retention, and asymmetric interpretation.

## 0. What changed from v1 (accepting Codex)
1. **Headline = sector-relative 25Δ skew** (name minus GDX/GDXJ), not raw skew.
2. **OI is confirmation, not "flow"** — public OI is post-clearing/daily; intraday OI deltas are noise; compare session-over-session by stable contract only. Volume is intraday but unsigned.
3. **Explicit persisted artifact contracts** (schemas + manifest registration + migration + fail-loud stale guard).
4. **Stale quotes → fail-closed** (don't publish; keep last complete manifest). Row-level carry-forward deferred to a later milestone.
5. **Freshness measured on the signal area** (45–150 DTE, near-ATM + 10–35Δ), not the whole chain.
6. **Two interpretations (bearish vs bullish) with different evidence bars** — one shared data model, asymmetric reads.
7. **IV-rank/skew-trend need a retained history store + min-sample**; until then they read `LIMITED_HISTORY`.
8. **Charts = signal card + normalized chart data**, not raw strike curves.
9. **Scheduler split to milestone 2.**
10. **Blunt = clear and accurate, never more certain than the data.**

## 1. Principles
- Evidence-based (our research briefs), backend-computed + persisted, serve layer reads/plots only. No black-box composite — a transparent **4-lane signal** the user can decompose.
- Build on existing code: `features/options.py` already has `put_iv_25d_{h}d`, `call_iv_25d_{h}d`, `iv_skew_{h}d = put_IV − call_IV`, `iv_rv_ratio_{h}d`; reuse liquidity metrics (`hedge/options_liquidity.py`) and the run-stamped option-snapshot archive. Register new artifacts the same way as `contracts/option_artifacts.py`.

## 2. The signal model — 4 transparent lanes (no composite score)
Per ticker, persist four named lanes, each with a value, a label, and a one-line reason:

### Lane A — DIRECTION (headline): sector-relative 25Δ skew
- `name_skew_{h} = put_iv_25d_{h} − call_iv_25d_{h}` (already computed; positive = downside puts richer).
- `sector_skew_{h}` = the same for the ticker's benchmark (GDX or GDXJ — §3).
- **`skew_residual_{h} = name_skew_{h} − sector_skew_{h}`** ← the trusted headline. Isolates *idiosyncratic* downside fear from sector-wide hedging.
- Horizons: **60d and 90d** primary (120d shown). Persist absolute name skew, sector skew, and residual.
- `direction_label` ∈ {`DOWNSIDE`, `NEUTRAL`, `UPSIDE`} from the residual + thresholds; `direction_reason` blunt (see §8 wording).

### Lane B — ACTIVITY (confirmation only, not flow)
- `volume_to_oi_{side}` = today's volume ÷ prior OI, by side and moneyness band — the only *intraday* activity measure (unsigned).
- `oi_change_{side}` = **session-over-session** OI change, computed **only between distinct OI-as-of sessions** and **matched by stable contract identity** (not by "nearest-60d bucket" — rolling expiries create fake changes). `oi_change_valid` flag gates whether it's shown.
- `activity_label` ∈ {`CONFIRMS_DOWNSIDE`, `CONFIRMS_UPSIDE`, `QUIET`, `N/A`} — explicitly *confirmation* of the direction lane, never a standalone headline.

### Lane C — COST (is the option expensive?)
- `iv_rv_ratio` (ATM IV ÷ realized vol — already computed) and `iv_rank` (ATM IV percentile vs the name's **own history**).
- `cost_label` ∈ {`RICH`, `NORMAL`, `CHEAP`, `LIMITED_HISTORY`}. `iv_rank` only contributes once history is deep enough (§5); else `LIMITED_HISTORY`.

### Lane D — DATA QUALITY (can you trust the above?)
- `signal_area_quote_coverage` (the gate — §6), `raw_chain_quote_coverage` (context), `liquidity_tier`, `history_depth`.
- `data_quality_label` ∈ {`OK`, `LOW_LIQUIDITY`, `STALE_QUOTES`, `SPARSE`, `NO_BENCHMARK`}. When not `OK`, the other lanes are shown as **unavailable with the reason**, not guessed.

**Headline string** (one blunt sentence) is assembled from the lanes, e.g.: *"AEM: downside puts 6 vol-pts richer than calls and +4 vs GDX (idiosyncratic); put volume confirming; options rich (IV 1.4× realized)."*

## 3. Deterministic benchmark rule (no UI inference)
Add an explicit per-ticker config field `option_benchmark_symbol` (default `GDX`; junior/small-cap names mapped to `GDXJ`). Resolve it **at refresh**, store `benchmark_symbol` in the artifact. If the benchmark chain is missing/stale → `data_quality_label = NO_BENCHMARK` and the residual lane is unavailable (don't silently fall back to absolute skew). GDX/GDXJ themselves get absolute skew only (their residual vs self is 0 by definition; show them as the sector gauge).

## 4. Asymmetric interpretation (one data model, two reads)
Equity options carry **structural** downside skew (crash protection is always bid), so "puts richer" is partly normal; call richness has other causes (speculation, takeover/borrow/dividend, sparse calls). So:
- **Bearish/downside read** requires: positive `skew_residual` **plus** activity/liquidity confirmation in the signal area.
- **Bullish/upside read** requires: calls richer than puts vs the sector **plus** call volume/OI context.
- Do **not** emit a single symmetric DOWNSIDE/UPSIDE with equal confidence. The labels carry the evidence asymmetry.

## 5. History store + retention (for IV-rank & skew-trend)
- Add a **dedicated append-only history store** (`option_signal_history`), one clean market-hours snapshot per trading day per ticker (skew, atm IV, iv_rv, residual). **Protect it from pruning** — `run_pruning.py` must never delete it (it currently prunes unprotected run dirs / old option outputs).
- **Min-sample rule:** require ≥ N (e.g., 20) clean snapshots before emitting `iv_rank`/skew-trend labels; below that → `LIMITED_HISTORY`. At launch everything is `LIMITED_HISTORY` and strengthens over weeks.

## 6. Stale-quote handling — fail-closed (Codex-agreed)
- Measure quote freshness on the **signal area** (45–150 DTE, near-ATM + 10–35Δ wings, sane IV, nonzero underlying, contracts passing the existing liquidity fields) — **not** the whole chain (deep-OTM/far contracts have empty bids even mid-session). Persist **both** `raw_chain_quote_coverage` and `signal_area_quote_coverage`; **gate on signal-area coverage.**
- If signal-area coverage is below threshold (pre-market/closed/holiday): **do not publish new option-signal artifacts and do not advance the manifest's option leg** — keep the last complete model state, and report it plainly in CLI status + UI: *"Option quotes are stale/pre-market — showing the last live snapshot from [date]; refresh during US market hours."* (Uses the existing manifest INCOMPLETE/alignment machinery; same fail-closed spirit as the Tool B schema guard.)
- Per-ticker row-level carry-forward (mixing fresh + held rows with `quote_snapshot_run_id`/`quote_as_of`/`freshness_status` provenance) is a **later** milestone, only after the manifest/status contract is agreed.

## 7. Persisted artifact contracts (the part v1 was missing)
Register new artifacts alongside `OPTION_ARTIFACT_NAMES`; the Option Trading reader loops over registered artifacts (`serve/option_trading_data.py`), so each needs a schema, required/optional status, `schema_version`, the run-identity fields, migration behavior, and a **fail-loud stale-schema guard** + a calm "run refresh" notice when missing post-migration (mirror `screening/schema.py`). All artifacts carry: `schema_version, source_run_id, snapshot_refresh_run_id, quote_snapshot_run_id, options_as_of_date, ticker` (+ `benchmark_symbol` where relevant).

1. **`option_signal_summary`** (one row/ticker — the 4 lanes): `benchmark_symbol, name_skew_60d/90d, sector_skew_60d/90d, skew_residual_60d/90d, direction_label/reason, volume_to_oi_put/call, oi_change_put/call, oi_change_valid, activity_label, iv_rv_ratio, iv_rank, history_depth, cost_label, signal_area_quote_coverage, raw_chain_quote_coverage, liquidity_tier, data_quality_label, headline, freshness_status`. **Required**, with migration + stale guard.
2. **`option_skew_curve_points`** (normalized chart data): per `ticker|benchmark`, `horizon_days, delta_bucket (or moneyness_bucket), side(P/C), iv, liquidity_flag`. Bucketed by delta/moneyness — **not raw strikes** (sparse miners → jagged).
3. **`option_oi_strike_points`** (strike-ladder chart): `ticker, strike, side, open_interest, volume, is_spot, oi_change, oi_change_valid`.
4. **`option_signal_history_points`** (time-series for skew-trend/IV-rank, read from the §5 store): `ticker, as_of_date, skew_residual_60d, atm_iv, iv_rank, iv_rv_ratio`.

## 8. Wording — blunt **and** accurate
Blunt means clear, not over-certain. **Good:** *"AEM puts are 6 vol-pts richer than calls, +4 vs GDX — the market is pricing more single-name downside."* **Bad:** *"buyers are betting the stock will fall"* (unsigned; not supported). State what's priced; don't infer intent the data can't prove.

## 9. UI (Option Trading tab; read-only)
- **Per-name signal card (primary):** one row, four lanes — **Direction** (sector-relative skew), **Activity**, **Cost**, **Data Quality** — each one number + one label + one short reason. First thing on the ticker detail.
- **Name-vs-sector skew overlay:** AEM vs GDX vs GDXJ at 60/90/120, showing 25Δ skew and the residual.
- **Universe heatmap:** rows = tickers; columns = sector-relative skew, skew change, put activity, call activity, IV/RV, history depth, liquidity; sort by downside residual. Best for scanning.
- **OI/volume strike ladder** (mirrored puts/calls, spot marked, today's volume highlighted; OI change shown only when `oi_change_valid`).
- **Term-structure strip:** ATM IV + skew across 60/90/120 for name vs GDX/GDXJ.
- All chart data computed at refresh (normalized), UI only plots (reuse `serve/charts.py`). No request-path option math.

## 10. Scope / sequencing
- **Milestone 1 (this build):** the 4-lane signals + artifacts/schemas/migration + sector-relative skew + signal-area stale guard (fail-closed) + the signal card, overlay, and heatmap, against **manual** market-hours refresh.
- **Milestone 2 (later):** the auto-refresh scheduler (Windows Task Scheduler helper) with holiday/DST handling + Yahoo-tolerance validation, after one or two clean market-hours refreshes prove coverage. (Stock data is daily-close-based; option signals are market-hours-snapshot-based — make that explicit.)
- **Out of scope:** row-level stale carry-forward; volatility-surface/term-structure modeling (research: buys nothing OOS); pushing premium-selling strategies.

## 11. Tests (gates)
Sparse/empty chains; missing or stale GDX/GDXJ benchmark (`NO_BENCHMARK`); stale/pre-market quotes (fail-closed, last complete state retained); signal-area vs raw coverage; OI change only across valid distinct OI sessions + stable contract identity (no fake bucket-roll changes); `LIMITED_HISTORY` until min-sample; artifact schema-contract + migration + fail-loud-on-missing; **no request-path option math**; no silent missing signal fields; the asymmetric labels (bearish requires confirmation).

## 12. Self-review
This v2 directly answers every Codex blocker/major: sector-relative skew is the headline; OI is honest confirmation (post-clearing, session-matched, stable-contract); the artifacts have real schemas + manifest registration + migration + fail-loud guards; stale quotes are fail-closed on signal-area coverage; history has a retained store + min-sample; interpretation is asymmetric; charts are normalized + a signal card. It stays backend-only, transparent (4 lanes, no composite), and blunt-but-accurate. Remaining judgment calls for Codex/Emanuel: the exact thresholds (skew residual cut-offs, coverage %, min-sample N) — propose defaults, tune on real market-hours data. Ready for a final Codex confirm, then build Milestone 1.
