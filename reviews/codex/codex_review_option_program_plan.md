# Codex Review - Option Trading Program Plan

Reviewed:
- `reviews/codex/codex_option_snapshot_fallback_plan.md`
- `reviews/codex/claude_review_option_snapshot_fallback_plan.md`

Verdict: **READY WITH CHANGES overall**

Milestone verdicts:

| Milestone | Verdict | Reason |
|---|---|---|
| A - Carry-forward fallback | **READY WITH MINOR CHANGES** | The carry-forward architecture is sound and the prior Claude review covers the important alignment issue. Keep A independent and ship it first. |
| B - Cached Liquidity Check clarity | **READY WITH MINOR CHANGES** | The backend change is small and correct. It should reuse the same tradable-only aggregation helper that C's most-liquid selector will need. |
| C - Horizon redesign | **NEEDS CHANGES BEFORE BUILD** | The plan correctly sees that this is not a default switch, but it still conflates candidate horizons with signal horizons, misses several 60d consumers, understates the history migration, and leaves the most-liquid selector too open. |
| D - Site-wide explanations | **READY WITH CHANGES** | The metadata registry is the right direction. Native `title=` is not enough for the multi-line calculation and threshold explanations Emanuel is asking for. |

## Severity-Ranked Findings

### HIGH - Separate option-candidate horizons from option-signal horizons before building C

The plan says the new 180d / 230d / LEAPS horizons sit outside today's signal band, so the feature/signal layer must be generalized to long-dated expiries first. That is too strong and probably the wrong product coupling. The signal model is currently a short/medium-dated market-read model: signal-area contracts are hard-filtered to `45 <= DTE <= 150` in `golden_vector/hedge/option_signals.py:23-24` and `golden_vector/hedge/option_signals.py:369-390`; direction/cost/headline then read 60d fields at `golden_vector/hedge/option_signals.py:206`, `golden_vector/hedge/option_signals.py:232`, and `golden_vector/hedge/option_signals.py:246-250`. Long-dated LEAPS can be useful for trade candidates, but 18-month skew/IV rank is not the same signal as a 60-120d risk-reversal: it is more sparse, rolls slowly, and will have weaker history. Fix: C should explicitly split `candidate_horizon_policy` from `signal_horizon_policy`. Let the option page select 90/180/230/LEAPS candidates, but keep Signal / Activity / Cost on a configured short/medium signal horizon, probably 90d initially, until there is enough evidence to trust long-dated signals.

### HIGH - The plan misses live 60d consumers outside the Option Trading web page

The blast radius is broader than the plan's section #1-#5. It correctly lists the main option artifact and serve paths, but omits several production modules that still encode 60d semantics and would either break on a rename or keep showing stale/misleading 60d language:

- `golden_vector/hedge/sensitivity_ranking.py:20-22`, `golden_vector/hedge/sensitivity_ranking.py:34-36`, `golden_vector/hedge/sensitivity_ranking.py:140-143`, `golden_vector/hedge/sensitivity_ranking.py:173-181`
- `golden_vector/hedge/portfolio_totals.py:32`, `golden_vector/hedge/portfolio_totals.py:158-159`, `golden_vector/hedge/portfolio_totals.py:259-265`, `golden_vector/hedge/portfolio_totals.py:311-319`
- `golden_vector/hedge/header_context.py:35-40`, `golden_vector/hedge/header_context.py:178-188`, `golden_vector/hedge/header_context.py:227-244`
- `golden_vector/hedge/report.py:507-517`, `golden_vector/hedge/report.py:580-599`, `golden_vector/hedge/report.py:733-737`
- `golden_vector/hedge/speculation_section.py:22`, `golden_vector/hedge/speculation_section.py:31-32`, `golden_vector/hedge/speculation_section.py:174-179`
- `golden_vector/features/options.py:22`, `golden_vector/features/options.py:143`, `golden_vector/features/options.py:155`

Fix: C's blast radius must either migrate these modules or explicitly declare them retired/out of scope. The dedicated `/hedge-readiness` web page may be retired, but the markdown report and CLI paths are still real unless removed elsewhere. Do not rename `OptionTradingRow.*_60d` without updating these consumers or preserving compatibility.

### HIGH - Changing target horizons can silently degrade optionability tiers

`compute_options_features` marks a stock as `directly_hedgeable` only if it has all configured target horizons: `has_all_horizons = all(row.get(f"put_iv_25d_{horizon}d") is not None for horizon in target_horizons_days)` at `golden_vector/features/options.py:223-228`. If C changes `target_horizons_days` to `[90, 180, 230, LEAPS]`, many names could be downgraded to `thin` just because a LEAPS 25-delta estimate is missing, even if the stock is perfectly optionable in the practical 90/180/230 windows. Fix: C1 must decide what optionability means after long horizons are added. Recommended: keep optionability tied to a configured "core optionability horizons" subset or a minimum coverage count, not "all selectable horizons".

### HIGH - The history migration cannot rely on `OPTION_ARTIFACT_SCHEMA_VERSION` alone

The plan says C2 can choose generic columns or an `OPTION_ARTIFACT_SCHEMA_VERSION` bump + history reset, and later says the schema bump composes with carry-forward. The artifact schema bump protects the ten manifest-resolved frames (`OPTION_ARTIFACT_SCHEMA_VERSION = 2` in `golden_vector/contracts/option_artifacts.py:10`; read guard at `golden_vector/serve/option_trading_data.py:522-549`). But the append-only source history is a separate local file: `HISTORY_FILE_NAME = "option_signal_history.parquet"` at `golden_vector/hedge/option_signals.py:29`, loaded by `load_option_signal_history` at `golden_vector/hedge/option_signals.py:145-148`, persisted by `persist_option_signal_history` at `golden_vector/hedge/option_signals.py:150-156`, and normalized by hardcoded 60d/90d columns at `golden_vector/hedge/option_signals.py:718-736`. Fix: the migration must cover both the published artifact and the local history store. My recommendation is a long-form history schema (`ticker`, `as_of_date`, `signal_horizon_days`, `skew_residual`, `atm_iv`, `iv_rv_ratio`, `benchmark_symbol`, `quote_snapshot_run_id`) with a one-time backfill from existing `skew_residual_60d`, `skew_residual_90d`, and `atm_iv_60d`. If you choose reset instead, say plainly that IV-rank/history starts over and add a calm `LIMITED_HISTORY` state.

### MEDIUM - The "Most liquid" selector needs a concrete backend contract before C3

The plan correctly says all inputs already persist in `option_contract_metrics`; confirmed columns include `ticker`, `option_type`, `expiration`, `days_to_expiry`, `liquidity_score`, `rel_spread`, `open_interest`, `volume`, `near_spot_depth_count`, and `liquidity_tier` in `data/output/options/option_contract_metrics_latest.parquet`. But C3 leaves core policy open: sum vs median score, per-ticker vs per-group, whole-chain vs DTE-window. This is load-bearing enough to settle now.

Concrete recommendation:

1. Implement in backend, e.g. `golden_vector/hedge/option_horizon_selection.py`, called during option artifact build after `option_contract_metrics` exists. Serve reads the selected horizon/expiry from an artifact or stamped columns.
2. Evaluate only configured horizon windows, not the whole chain. For each ticker, side, horizon-window, and expiry, filter to `liquidity_tier == "tradable"` with valid `mid` and `rel_spread`.
3. Score an expiry using robust aggregates, not a raw sum that rewards one ticker with many contracts:
   - unique tradable contract count,
   - median tradable relative spread, lower better,
   - median open interest,
   - median volume,
   - median near-spot depth,
   - standard monthly flag as a small tie-breaker,
   - DTE distance only as a tie-breaker inside the configured window.
4. For the overview default, choose a group-level default from **single-stock miners**, using per-ticker normalized expiry scores so GDX/GDXJ do not dominate. For a ticker detail page, choose that ticker's best expiry. For side-specific views, choose side-specific defaults; otherwise a put-heavy expiry can become the default for calls.
5. Tie-break deterministically: higher ticker coverage, lower median spread, higher median OI, higher median volume, closer target DTE, earlier expiration, then lexical expiration.

### MEDIUM - C should not drive the published signal from "most liquid" by default

Decision 1 asks whether the signal should use an explicit knob or the per-ticker most-liquid horizon. Use the explicit knob. Per-ticker most-liquid would make rows less comparable: AEM might show a 230d residual while NEM shows 90d, and the table label "Signal" would no longer mean one thing. Fix: add `option_signal_horizon_days` and keep the overview signal comparable across tickers. Candidate/default expiry can be per-ticker; signal horizon should be global unless deliberately building a separate "selected expiry signal" lane.

### MEDIUM - Candidate Finder should prefer benchmark-relative residual for directional option screens

Candidate Finder currently scores `iv_skew_60d` from `config/candidate_finder.yaml:149-152`, which comes from the name's own put IV minus call IV in `golden_vector/features/options.py:138`. The Option Trading UI shows sector-relative residuals from `golden_vector/hedge/option_signals.py:202-206` and `golden_vector/serve/option_signal_render.py:26`. Those are different signals. For Bear/Bull screens, residual is the better default because it asks "is this name unusually tilted versus GDX/GDXJ?", not just "do equity puts normally cost more than calls?" Fix: add generic signal fields into `candidate_finder_inputs` from `option_signal_summary`, e.g. `skew_residual_signal`, `name_iv_skew_signal`, `benchmark_symbol`, and `signal_horizon_days`. Use residual in Bull/Bear presets; keep raw name skew as an optional criterion for users who want it.

### MEDIUM - C5 request-time scenarios do not have to block C, but they must stay bounded

The plan flags request-time scenario recompute in `build_option_trading_detail`: put bundles at `golden_vector/hedge/option_trading.py:242-255`, call bundles at `golden_vector/hedge/option_trading.py:256-270`, and context P&L at `golden_vector/hedge/option_trading.py:535-545`. This is not ideal, but it is backend Python operating on persisted selected candidates, not a raw chain scan in templates. Fixing it should not block C unless C starts rendering scenario bundles for many horizons at once. For C, acceptable compromise: keep request-time scenario compute for the single selected candidate/horizon, add timing/logging and a guardrail test proving no raw chain scan. If detail pages render all horizons' scenarios, persist scenario bundles per horizon instead.

### MEDIUM - D1's native `title=` is insufficient for the requested site-wide explanations

The CSS currently only underlines headers with a native title (`golden_vector/serve/static/workspace.css:612-617`). Native browser tooltips are not reliable for multi-line calculations, thresholds, keyboard use, or mobile/touch. The user specifically asked to hover and see how values are calculated, including thresholds and "higher/lower is better." Fix: D1 can use native `title=` for the smallest first pass, but the plan should call it a temporary transport. The real D mechanism should produce reusable metadata and render accessible hover/focus popovers (`aria-describedby`, CSS-only if possible; JS only if needed). Row-level skew calculations should definitely not rely on a cramped native title.

### MEDIUM - Tooltip metadata should be backend-resolved, not template-resolved from config paths

D1 says threshold fields reference config attributes by name and are resolved at render from `AppConfig`. That can be okay if the registry is server-side, but it should not become "HTML templates know which config fields define tradable." Evidence: the chain-level tradable rule lives in `golden_vector/hedge/options_liquidity.py:892-909`, while slot-level candidate tradability uses stricter rules at `golden_vector/hedge/options_liquidity.py:638-657`. Fix: expose explanation payloads from a backend explanation registry that calls/reuses option policy objects. Serve should receive already-built text/parts. Tests should change a fixture threshold and assert tooltip text changes without duplicating thresholds in serve.

### MEDIUM - B should produce a reusable tradable-liquidity aggregation primitive

B is small, but C3 needs the same "tradable-only medians/counts by group/expiry" logic. Today `build_option_liquidity_measurements` accumulates row dicts and computes all-row medians at `golden_vector/hedge/option_artifact_builder.py:301-357`. Fix: when B changes medians to tradable-only, extract a small backend helper for summarizing tradable contract rows. That helper should be reused by C3's most-liquid selector. Otherwise B and C will immediately grow divergent liquidity summaries.

### MEDIUM - Term slope is already broken and should be explicitly handled in C2

The plan notes `term_slope_30_90` reads `atm_iv_30d` while live config produces `[60,90,120]`; the code is at `golden_vector/features/options.py:143`. This should not be a side note. C2 should either remove it from persisted features if unused, or redefine it as a configured term-structure pair such as `term_slope_signal_long` with both horizons present. Silent `None` columns are exactly the kind of data-quality drift this plan is trying to stop.

### NIT - Some line references are slightly off or incomplete

Most of the plan's line references are real. Minor corrections: `option_dte_bands` starts at `golden_vector/contracts/config_models.py:154` rather than `:155`; default horizon fallback is at `golden_vector/serve/option_trading_data.py:311`; the cross-sectional IV hardcoding is defined in `golden_vector/features/options.py:152-162` and called from `golden_vector/ingestion/options_phase.py:219-221`. These are small, but the final implementation brief should use current line refs after the plan is reconciled.

## Answers to the Six Open Decisions

| Decision | Recommendation |
|---|---|
| 1. Signal horizon after redesign | Add explicit `option_signal_horizon_days`, default 90d. Keep signal lanes short/medium and comparable. Do not drive the published signal off per-ticker most-liquid or LEAPS in v1. |
| 2. History-schema migration | Prefer generic/long-form history with `signal_horizon_days` and backfill old 60/90 where possible. Also bump `OPTION_ARTIFACT_SCHEMA_VERSION`. If reset is chosen, document that IV-rank/history starts over and make the UI say `LIMITED_HISTORY`, not fail. |
| 3. Most-liquid aggregation policy | Use backend per-window expiry scoring from tradable contracts only. Overview default should be group-level for single-stock miners; detail default should be per-ticker and side-aware. Use robust aggregates and deterministic tie-breaks, not raw sums. |
| 4. LEAPS band | Define it in config as a named long-dated band, not an open-ended `>365`. Based on the current cached data, start around 450-650 DTE for "Long-dated / LEAPS (~18mo)". Keep a separate 1y band only if later data shows coverage; current 1y single-stock coverage looked weak. |
| 5. `OptionTradingRow.*_60d` rename appetite | Rename to generic names during the schema bump rather than adding parallel old/new forever. Suggested fields: `signal_horizon_days`, `iv_skew_signal`, `iv_rv_ratio_signal`, `pnl_put_at_context`, `pnl_call_at_context`, plus context horizon/expiry metadata. Keep backwards compatibility only in reader tests or migration helpers. |
| 6. Candidate Finder skew field | Switch default Bear/Bull option criteria to benchmark-relative `skew_residual_signal`. Also preserve raw `name_iv_skew_signal` as an optional criterion because it answers a different question. |

Additional decisions I would add before C:

| Added Decision | Why it matters |
|---|---|
| What counts as optionable after adding LEAPS? | `features/options.py:223-228` currently requires all target horizons for `directly_hedgeable`; that will become too strict if LEAPS is selectable. |
| Is "Most liquid" side-specific? | Put and call liquidity can differ. A single default expiry may be good for puts but poor for calls. |
| Should long-dated candidate horizons influence signal data quality? | If signal stays 90d, a stock can have a valid LEAPS candidate but `SPARSE` signal; the UI needs to explain that these are different lanes. |
| Are old Hedge Readiness markdown outputs still supported? | If yes, migrate the 60d text there; if no, retire or freeze them explicitly. |

## Milestone Split and Ordering

Recommended order is mostly sound: **A -> D1 -> B -> C -> D2**.

Adjustments:

- A is genuinely independent of C. In fact A should ship before C because carry-forward must know how to treat stale-schema option artifacts once C bumps schema.
- D1 before B is not required for B's backend math, but it is useful if B's header labels/tooltips should land together. If speed matters, B backend can ship first and D1 can add tooltips later.
- B before C is more important than the plan states: C3 should reuse B's tradable-only aggregation primitive. Without B first, C will likely implement a second liquidity summary.
- C should be split into at least two reviewable chunks:
  1. C1/C2: config consolidation + generic signal/history schema with no long horizons yet.
  2. C3/C4: add long candidate horizons + most-liquid selector + UI switcher.
  3. C5: decide/persist scenarios only if the UI starts rendering more than the selected candidate.
- D2 should stay after C because explanations need the final column names and horizon model.

## Disagreement Table

| Plan claim | My assessment | Proposed reconciliation |
|---|---|---|
| Long horizons require generalizing the signal layer to long-dated expiries first. | Candidate horizons and signal horizons should be decoupled. Long-dated candidates are useful; long-dated signals are a separate research question. | Add `signal_horizon_days` and keep Signal/Activity/Cost short/medium in v1. |
| `OPTION_ARTIFACT_SCHEMA_VERSION` bump composes with carry-forward and handles schema interaction. | True for manifest artifacts only; not enough for `option_signal_history.parquet`. | Add explicit history migration/reset path. |
| Native `title=` is enough for D1. | Fine for a tiny MVP header hint, not enough for formulas/thresholds/site-wide education. | D1 may use title as transport only if the registry shape supports upgrading to accessible popovers. |
| Blast radius captures the 60d-centered page. | It captures the web page, but misses CLI/report/portfolio/sensitivity/speculation consumers. | Add those modules to C scope or declare them frozen/retired. |

## Final Recommendation

Proceed with **A** and probably **D1/B** after small wording/aggregation refinements. Do **not** start **C** until the plan is amended with:

1. separate candidate-vs-signal horizon policies;
2. explicit optionability-tier semantics after long horizons;
3. a real history migration/reset decision covering the append-only history file;
4. the full 60d blast radius, including markdown/CLI/portfolio/sensitivity modules;
5. a concrete backend most-liquid selector algorithm;
6. a decision to use benchmark-relative residuals in Candidate Finder's directional option criteria.

Once those are settled, C is buildable, but it is large enough to deserve its own implementation brief and checkpointed review.
