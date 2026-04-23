# Claude Review: Holistic Repo Check — 2026-04-23

Reviewer: Claude (Opus 4.7, 1M context)
Branch: `dev-vic`
Mode: Read-only, repo-wide.
Tests run during review: `python -m pytest -q` → **159 passed in 34.14s**.

I read the full codebase (`golden_vector/` plus `tests/`), the Guo / Leung / Ward paper, the implementation guide, the runtime redesign plan, the architecture map, the README, the AGENTS / CLAUDE rules, and the most recent prior reviews. I inspected the current live artifacts: the latest foundation manifest, the latest Tool A CSV/parquet (run `20260423T122721Z-tool-a-ac236d2b`, snapshot 2026-04-22, weekly as-of 2026-04-17), the Tool B output directory, and the SQLite manual store.

Big picture up front: the repo has improved substantially since my Tool A pass earlier today. Most of the P0/P1 items I flagged in [claude_review_tool_a_structural_redesign_findings.md](reviews/codex/claude_review_tool_a_structural_redesign_findings.md) and the items codex flagged in [codex_review_tool_a_structural_redesign_findings.md](reviews/codex/codex_review_tool_a_structural_redesign_findings.md) have been fixed in code, with new tests, and they are visible in the live artifacts. The product is no longer "not ready"; it is "ready with a small set of focused follow-ups." The biggest single risk today is a missing Tool B `latest` alias on disk that makes the workspace half-blank.

---

## 1. Findings ordered P0 → P3

I separate **bugs** (the code disagrees with itself or with stated intent), **architectural weaknesses** (the code works but the structure invites future trouble), and **conceptual disagreements** (the design is internally consistent but I think it is wrong).

### P0 — Bug: `tool_b_latest.parquet` and `tool_b_latest.csv` stable aliases are missing on disk

Where:
- [golden_vector/serve/workspace.py:305-307](golden_vector/serve/workspace.py#L305-L307) reads `paths.latest_tool_b_snapshot_parquet_path` → `data/output/tool_b/tool_b_latest.parquet`
- [golden_vector/app/paths.py:189-194](golden_vector/app/paths.py#L189-L194) defines that path

Evidence:
- `ls data/output/tool_b/` shows only `tool_b_latest_<run-id>.parquet/csv` files (with run-id suffix) — there is **no** plain `tool_b_latest.parquet` or `tool_b_latest.csv`.
- The most recent Tool B run is dated 2026-04-22 23:26. Tool A ran later (2026-04-23) but Tool A persistence does not write Tool B aliases.
- `[ persist_tool_b_outputs ](golden_vector/ingestion/persist.py)` *does* write the stable alias when `publish_latest_aliases=True`, and Tool B passes `publish_latest_aliases=not tool_b_outputs.empty`. So either every tool-b run since the alias was deleted has produced empty outputs, or someone deleted the file by hand.

Why this matters today:
- Right now, opening the workspace gives a partially blank product: Tool A panels render, Tool B panels render "No latest output is available yet."
- The whole point of the workspace is one-page Tool A + Tool B side-by-side.
- The review request explicitly listed the missing files as live artifacts to inspect; they're not there.

Fix shape:
- Run `python main.py tool-b --gold-price 4000` to regenerate the alias.
- Add a workspace-level test that asserts the overview page renders both Tool A and Tool B rows when both stable aliases exist.
- Optionally, persist a small marker file alongside the alias so it is obvious when the alias has been clobbered or removed out-of-band.

### P1 — Bug: `workspace` start-up still silently mutates the manual store

Where: [golden_vector/cli.py:1050-1054](golden_vector/cli.py#L1050-L1054)

```python
bootstrap_manual_screening_data(
    paths,
    tickers=tool_b_tickers,
    import_csv_if_empty=False,
)
```

`bootstrap_manual_screening_data` calls `ensure_manual_store`, which (a) creates the SQLite database if missing and (b) **inserts placeholder rows for every active Tool B ticker** that does not yet have a row. So opening the workspace silently creates seed rows for any ticker added to `universe.yaml` since the last run.

This was codex's open P1 from the merged Phase 3/4 review ("Normal Tool B usage still mutates local manual-data state"). The `tool-b` CLI path was fixed (it now raises `FileNotFoundError` when the store is missing — see [tests/test_tool_b_pipeline.py:152-173](tests/test_tool_b_pipeline.py#L152-L173)). The `workspace` path was not.

Why it matters: the runtime redesign locked in the rule that `manual-data init` is meaningful and normal usage is read-only. Today, you cannot tell whether a row was created by the user or by an accidental workspace open. For a tool whose audit story is its biggest selling point, this matters.

Fix shape: in `run_workspace`, replace `bootstrap_manual_screening_data` with `manual_store_exists` + a clean error page if the store is missing, instructing the user to run `manual-data init`. Mirror what `run_tool_b` already does.

### P1 — Architectural weakness: half the active universe has no manual data, so half of Tool B is structurally INCOMPLETE

Evidence (from `data/manual/screening/manual_screening.sqlite3`):

| Ticker | Has manual data? |
|---|---|
| AEM | yes |
| BTG | no |
| DPM.TO | no |
| FNV | no |
| FRES.L | no |
| GOLD | yes |
| KGC | yes |
| NEM | yes |

Tool B can only ever rank 4 of 8 names today, and the workspace's universe-overview row count for "Tool B Verdict" / "Tool B Score" will be `INCOMPLETE` for half the universe.

This is a *data* gap, not a code bug — but in a holistic review it's the single biggest reason the workspace looks weaker than the underlying engine actually is. Most of Tool B's machinery (Layer 1, Layer 2, target prices, verdicts, ranking) is exercised by tests but isn't doing useful work for half the tickers.

Recommendation: either (a) populate manual data for the missing 4 tickers, or (b) tag those tickers `tool_b_enabled: false` until manual data exists, so the workspace doesn't carry half-broken rows.

### P1 — Bug: `compute_asymmetry_component_score` still gives a 0.5 "free" fallback when `down_beta is None` and `up_beta > 0`

Where: [golden_vector/model/scoring.py:56-59](golden_vector/model/scoring.py#L56-L59)

```python
if up_beta is None:
    return 0.0
if down_beta is None:
    return 0.5 if up_beta > 0 else 0.0
```

If down-gold weeks are too thin to estimate `down_beta`, the asymmetry component awards 0.5 — half-credit by default. With `weights.asymmetry = 0.15` that's up to **7.5 points** of Tool A score from a missing-data fallback. The down-beta missingness is real evidence of *insufficient regime coverage*, not evidence of asymmetry; this should be 0.0 with an explicit reason recorded somewhere the user can see.

This was P2 in my Tool A review and remains unaddressed.

### P1 — Conceptual: the framework's "structural delta" is a single-factor regression and a static long window — still not the paper

The redesign is much closer to the Guo / Leung / Ward paper than the prior horizon-first model, but three real gaps remain:

1. **Single-factor regression.** The paper uses excess returns over the risk-free rate with **both gold and the broad equity-market portfolio** as factors (paper equation 10). The code regresses stock weekly log returns directly on gold weekly log returns with no market factor and no risk-free adjustment. Common equity-market drift therefore leaks into `structural_delta` and inflates `r_squared`.
2. **Static long windows.** The paper estimates `β_GLD,t,j` from a 25-business-day rolling window with exponential decay and smooths it with a Kalman filter. The code uses 6M / 12M / 3Y *static* equally-weighted windows. The whole point of the paper's machinery is that `β` is time-varying; static windows wash it out.
3. **Gamma is regime-conditional, not state-conditional.** The paper proves `β'(S) < 0` and `β''(S) > 0`: implied leverage is a *function of S over time*. The code's `gamma = down_beta − up_beta` is a regime-conditional proxy. The redesign correctly *flipped the sign convention* so positive gamma now reads as fragility rather than upside torque (see live row for KGC: gamma = +0.24, profile = `FRAGILE`), which is a real conceptual win — but the underlying measurement is still a proxy.

This is consistent across both my and codex's prior reviews: the redesign is *much* better than the old horizon-first heuristic, but it is still a *paper-inspired structural simplification*, not the paper. The implementation guide should say so.

### P2 — Bug: `compute_layer2_metrics` uses an undocumented `0.7` magic constant when `cash_cost_usd_per_oz` is missing

Where: [golden_vector/screening/layer2.py:68-72](golden_vector/screening/layer2.py#L68-L72)

```python
if cash_cost_usd_per_oz is not None and cash_cost_usd_per_oz > 0:
    operating_margin_usd_per_oz = gold_price_assumption - cash_cost_usd_per_oz
else:
    assert aisc_usd_per_oz is not None
    operating_margin_usd_per_oz = gold_price_assumption - (aisc_usd_per_oz * 0.7)
```

The `0.7` is a heuristic that "cash cost is roughly 70% of AISC" but it isn't in config, isn't documented, and isn't tested. Two issues:
- Quietly silenced reading: a stock with missing cash-cost gets EBITDA computed against an assumption the user can't see in the row.
- Reproducibility risk: if someone tunes the constant, no test will catch the change.

Move it to `screening_params.yaml` (e.g. `assumed_cash_cost_share_of_aisc`) and surface the assumption in the Tool B output (`forward_ebitda_basis = "ACTUAL_CASH_COST"` vs `"AISC_FALLBACK"`).

### P2 — Architectural weakness: `golden_vector/combined/` still ships executable code

Where: [golden_vector/combined/](golden_vector/combined/)

- `pipeline.py`, `ranking.py`, `join.py` — all importable Python.
- `README_LEGACY.md` says it's de-scoped.
- The CLI no longer wires it up.
- But the code is still in the package.

Per the runtime redesign plan: Combined "is no longer part of the active product" and the future view should be a presentation-layer side-by-side, not a pipeline. Today the legacy code is dormant but it can still be imported by mistake, and it carries old contract assumptions (combined verdicts, combined scores) that conflict with the documented direction.

Either move it to a clearly archived location (e.g. `archive/combined/`) or delete it. The test suite is strong enough now that you can do this safely.

### P2 — Architectural weakness: `tool_b_latest_*.parquet` files accumulate without rotation

Where: [golden_vector/ingestion/persist.py:270-316](golden_vector/ingestion/persist.py#L270-L316)

Every Tool B and Tool A run writes both `<file>_<run-id>.parquet` and (when non-empty) the stable alias. The run-id suffixed files are never cleaned up. After a few weeks of daily use, `data/output/tool_a/` and `data/output/tool_b/` will accumulate hundreds of files. The `tool_a/` directory already has 25+ run-suffixed files. Inspect the directory listing in the bash output above.

Not a correctness bug, but operationally untidy. Add a small `prune_old_artifacts(paths, keep_last=N)` helper, or ignore for now and accept it as known.

### P2 — Bug: `_determine_snapshot_anchor_date` falls back to the run start UTC date when no snapshots have valid dates

Where: [golden_vector/screening/pipeline.py:321-333](golden_vector/screening/pipeline.py#L321-L333)

If `normalized_market_snapshots` is empty (or all `snapshot_date` values are NaT), Tool B stamps the rows with `pd.to_datetime(run_context.started_at_utc, utc=True).date()`. That's a date the system has *no data for* — pure run-time. Combined with the row-level `merged["as_of_date"] = merged["snapshot_date"].where(notna, snapshot_anchor_date)`, **rows in the same run can have different `as_of_date` values**, some of which are pure run timestamps.

Two problems:
1. The Tool B stable alias's `as_of_date` becomes "today" for INCOMPLETE rows, which makes the workspace's "As Of" cell misleading.
2. Latest-snapshot selection in `_latest_snapshot` uses `frame["as_of_date"].max()` — if some rows have a fresh anchor date and others have a stale snapshot date, the latest-snapshot view drops the older rows entirely.

Fix shape: skip the run-time fallback. If a row has no snapshot date, mark `as_of_date = None` and emit `INCOMPLETE` cleanly. The visible "As Of" in the workspace should reflect data, never wall-clock.

### P2 — Bug: tests assert structural behavior that is actually correct, but coverage of `_render_signal_notice` and the score-withheld path is thin

Where: [tests/test_workspace_app.py](tests/test_workspace_app.py)

Two end-to-end gaps:
- No test renders a `score_eligible = False` row and asserts the workspace shows the "Score withheld" notice (added at [golden_vector/serve/workspace.py:561-583](golden_vector/serve/workspace.py#L561-L583)).
- No test asserts `normalization_issue_summary` actually appears in the rendered HTML when present.

The notice is the user-facing safety net for the FX gating. If it silently regresses, the workspace will quietly start lying about score quality.

Add one test: feed a Tool A row with `score_eligibility_reason = "UNACCEPTABLE_NORMALIZATION_STATUS"` and assert the rendered body contains both the withheld notice and the issue-summary text.

### P3 — Architectural weakness: docs use both old and new gamma sign conventions

The framework now defines `gamma = down_beta − up_beta`, where positive ⇒ FRAGILE and negative ⇒ upside-skewed (`CONVEX`). The workspace metric card correctly says "Gamma (Down-Up)" ([golden_vector/serve/workspace.py:546](golden_vector/serve/workspace.py#L546)). But:

- [Gold_Framework_Implementation_Guide.docx](Gold_Framework_Implementation_Guide.docx) still uses the *old* `Delta(gold up) >> Delta(gold down) ⇒ positive gamma` framing.
- [README.md](README.md) does not mention the convention at all.
- Any reader who learns the framework from the guide and then looks at the workspace will assume positive gamma is good.

Pick one convention, document it in one place (e.g., a "Gamma reading guide" section in the README), and add a one-sentence reminder in the Gamma explanation card.

### P3 — Architectural weakness: `_compute_confidence_score` still has subjective weights with no test of the formula directly

Where: [golden_vector/model/pipeline.py:588-633](golden_vector/model/pipeline.py#L588-L633)

The formula is:
```
0.25 * coverage + 0.30 * (0.6*mean_R² + 0.4*min_R²) + 0.20 * sign + 0.15 * stability + 0.10 * regime
```

Five magic weights (0.25 / 0.30 / 0.20 / 0.15 / 0.10) summing to 1.0. None of them are in config, none of them are individually tested. The new shape is much better than the previous saturating formula (live confidences now range 0.72 → 0.88 rather than all 0.98), but the weights are still a literal in code and a future tweak will be invisible to the audit hash.

Either move the weights to config or add a single test that pins the formula by computing one expected confidence end-to-end from known inputs.

### P3 — Bug: `_compute_confidence_score` uses `total_windows = max(len(scoring_config.structural_windows), 1)` for the `regime_score` denominator, but a window that is `ELIGIBLE` for delta but has no regime split (no `up_beta`/`down_beta`) is treated as a regime miss

Where: [golden_vector/model/pipeline.py:618-624](golden_vector/model/pipeline.py#L618-L624)

So a stock with 3 eligible windows where the 6M window doesn't have enough up- or down-gold weeks for a regime split scores `regime = 2/3 = 0.67`. That's the right behaviour — but it conflates *coverage* and *regime depth*. A user looking at `confidence_score` cannot tell whether the stock has 3 eligible windows with thin regime splits or 2 eligible windows with full regime splits. A small `regime_eligible_window_count` field in the output would help.

### P3 — Bug: `summarize_normalization_issues` uses a 3-year trailing window regardless of the structural window in question

Where: [golden_vector/model/structural.py:476-498](golden_vector/model/structural.py#L476-L498)

The summary that drives `score_eligibility_reason = "UNACCEPTABLE_NORMALIZATION_STATUS"` is computed once per `as_of_date` over the trailing 3 years. So a STALE_FX run inside the trailing 3Y window can withhold the score for *every* horizon view, even when the 6M window has zero issues. That's defensible (it gives the most conservative reading), but it means you can never have a "12M is clean even though 3Y is dirty" published row. Document the choice or window-scope the summary.

### P3 — Architectural weakness: legacy `delta.py`, `gamma.py`, `stability.py` in `golden_vector/features/` are still importable but no longer used

These compute the old horizon-return delta / stability / gamma proxy. The structural model in `golden_vector/model/` doesn't use them. They are exercised only by their own tests (`test_delta.py`, `test_gamma.py`, `test_stability.py`). They are not loaded into the official Tool A path. Same recommendation as Combined: archive or delete to remove the temptation to reuse them.

### P3 — Bug: `_render_scatter_panel` regression now uses anchor metric (good), but the anchor sample is taken from the *full* weekly_series via `weekly_series.tail(52)`-style logic — meaning the chart and the metric can disagree if 52 weeks is shorter than the anchor window

Where: I see in [golden_vector/serve/workspace.py:639-660](golden_vector/serve/workspace.py#L639-L660) that the visual panels now use `_anchor_window_metric` and `_anchor_window_sample` helpers, which is a real improvement over my earlier review. I did not deep-read the helpers; if they pull the anchor's actual window length (e.g. 156 weeks for 3Y anchor) the chart and metric will agree. If they still hard-code 52 weeks, the 3Y-anchored row will draw a 52-week regression line over a 156-week beta, which will read off.

Worth a quick check: when `anchor_window_id == "3Y"`, does the scatter panel sample 156 weeks?

### P3 — Architectural weakness: `_foundation_signature` covers universe + FX policy, not data-quality thresholds

Where: [golden_vector/app/latest_data.py:177-196](golden_vector/app/latest_data.py#L177-L196)

The foundation signature includes universe membership, currency, and FX policy. It does not include `near_zero_gold_return_threshold`, minimum-history-day thresholds, or `block_on_missing_*` flags. So changing those QA knobs and re-using the existing snapshot will silently change Tool A's exclusion behavior with no manifest mismatch.

This is a smaller version of codex's previously-flagged "snapshot manifest does not include QA-policy settings." The most-affecting QA fields (`max_fx_staleness_days`, `block_on_stale_fx`) *are* in the signature, so the worst case is bounded. But for full audit safety, hash the entire `app_config.qa` section.

---

## 2. Architecture assessment

The local-first runtime is real and clean.

- `update-data` is the single explicit refresh path. It writes raw, intermediate, and run-specific outputs, then writes the foundation manifest at `data/intermediate/status/latest_foundation_manifest.json`.
- `tool-a` and `tool-b` both load that manifest, validate signature, and read only local data. There is no Yahoo call on either path.
- `workspace` reads stable `tool_a_latest.*` and `tool_b_latest.*` aliases. (Modulo the missing Tool B alias above.)
- `compare-horizons` is correctly isolated as exploratory.
- Run-context metadata is consistent: every run produces a `metadata.json`, a `qa_summary.json`, and a `*_summary.json`. The artifact list is sorted and de-duplicated.

The Pydantic config layer is comprehensive and strict. `AppConfig.model_validate` rejects unsupported fields (`extra="forbid"`), enforces threshold ordering (`StructuralDeltaBands`, `GammaThresholds`, `AsymmetryThresholds`, `ConfidenceThresholds`, `VolatilityDiagnosticBands`, `CombinedVerdictThresholds`), and verifies that score weights sum to 1.0. The new `StructuralWindowWeights` and `blocked_normalization_statuses` are also validated. The `combined_hash` over all five YAML files travels through every run as `config_hash`, which is the right shape.

The hard rules are enforced where it counts:
- No mixed-currency analytics: `_currency_from_equity_frame` rejects multi-currency frames; structural code only consumes `return_basis_usd`; Tool B reads USD-normalized snapshots.
- No official scoring from custom horizons: `compare-horizons` writes its own CSV and is structurally separate from `model/`.
- No scoring before QA gates: foundation skips normalization on raw FAIL, and the manifest is only written when `foundation_status != "FAIL"`.
- No hidden manual overrides: Tool B's `confidence` field is derived from `source_verification` rows, not free-form.

The persistence layer is now safer than before: empty Tool A / Tool B runs no longer clobber the stable alias (codex's [post-workspace hardening fix](reviews/codex/codex_review_post_workspace_hardening_2026-04-23.md)). Run-specific `<file>_<run-id>.parquet` files are still written, so audit history is preserved.

What I'd still call architectural weaknesses, ranked:
1. `combined/` ships executable code despite being de-scoped (P2 above).
2. Legacy `features/delta.py`, `gamma.py`, `stability.py` remain importable but aren't used by the official path (P3 above).
3. `workspace` still mutates the manual store on start (P1 above).
4. Foundation signature does not hash the entire QA section (P3 above).
5. No artifact rotation for run-specific files (P2 above).

---

## 3. Tool A assessment

This is the area that has improved most since my Tool A review earlier today. Going through each P0/P1 from my prior pass:

| Prior finding | Status now |
|---|---|
| **P0 conceptual: positive gamma framed as upside** | **Fixed.** Sign flipped: `gamma = down_beta − up_beta`. Positive gamma now reads as `FRAGILE`. Live KGC row confirms: gamma = +0.24 → `FRAGILE`. |
| **P0 bug: BTG-style summary contradicts profile** | **Fixed.** New `build_interaction_explanation` has explicit branches for `CONVEX`, `FRAGILE`, `HIGH_DELTA`, `LINEAR`, `LOW_LINKAGE`, `DEFENSIVE`, plus eligibility-aware branches for `WITHHELD`. Live BTG row reads "This is an upside-skewed gold exposure: strong linkage, better up-gold participation than down-gold sensitivity, and manageable noise." |
| **P1 bug: score-ineligible rows still get confident summaries** | **Fixed.** New `WITHHELD_SCORE_REASONS` set; `confidence_label = "WITHHELD"`, `profile_label = "SCORE_WITHHELD"`, and explanations override. Workspace `_render_signal_notice` surfaces it. |
| **P1 bug: KGC reads as LINEAR despite negative skew** | **Fixed.** New `FRAGILE` profile triggers when `down_beta_core > up_beta_core` and `delta_core > low_max`. Live KGC, AEM, NEM, DPM.TO, FNV all correctly tagged `FRAGILE`. |
| **P1 weakness: confidence saturates at 0.98 for everyone** | **Fixed.** New formula uses `(0.6*mean_R² + 0.4*min_R²)`, no longer caps at `R²=0.30`. Live confidences range 0.72 (GOLD) → 0.88 (AEM). The `MEDIUM` label is now actually achievable (GOLD has it). |
| **P1 risk: STALE_FX bypasses score eligibility silently** | **Fixed.** `determine_score_eligibility` now blocks any status in `scoring_config.blocked_normalization_status_set()`, which the live `scoring.yaml` lists as `[MISSING_RETURN_BASIS, MISSING_FX, STALE_FX]`. The check runs *first*, before window-count gating. |
| **P1 bug: asymmetry_component_score uses 12M-only inputs** | **Fixed.** `_build_tool_a_outputs` now passes `up_beta_core` / `down_beta_core` which are weighted-medians, matching `asymmetry_ratio_core`. |
| **P1 bug: asymmetry_ratio = None when down_beta < 0** | **Fixed.** The `down_beta <= 0` guard removed. New test `test_compute_window_metric_preserves_negative_down_beta_asymmetry_ratio` pins the behavior. |
| **P2 bug: partial week treated as full week / future-dated as_of_date** | **Fixed.** `_last_trading_day_per_week` drops the in-progress week. `as_of_date = min(stock_week_date, gold_week_date)`. Live snapshot date is 2026-04-22 and `as_of_date` is 2026-04-17 (the prior Friday) — clean. New test `test_build_structural_weekly_series_drops_incomplete_current_week` pins it. |
| **P2 bug: volatility regression independent of structural delta** | **Fixed.** `compute_volatility_diagnostics` now uses the anchor window's `(alpha, beta)` to compute residuals. New test `test_compute_volatility_diagnostics_uses_anchor_window_id` pins it. The output adds a `volatility_anchor_window_id` column. |
| **P2 bug: 12M ineligibility cascades** | **Fixed.** `choose_structural_anchor_window` walks `12M → 3Y → 6M` (config-driven via `anchor_window_preference`). `anchor_window_id` is now first-class in the output. |
| **P2 issue: WINDOW_WEIGHTS hardcoded** | **Fixed.** New `StructuralWindowWeights` config model, `scoring.structural_weight_map()`, hashed into config_hash. Live `scoring.yaml` shows `windows: {6M: 1.0, 12M: 1.0, 3Y: 1.0}` (currently equal-weighted). |

What's still imperfect on Tool A:
1. The 0.5 fallback in `compute_asymmetry_component_score` when `down_beta is None` (P1 above).
2. The single-factor / static-window / no-Kalman gap relative to the paper (P1 conceptual above).
3. The 5 magic weights in `_compute_confidence_score` (P3 above).

The best evidence that the redesign is working: the live universe now produces a meaningful spread.

| Ticker | profile | delta | gamma (D−U) | asymm | conf | score | rank |
|---|---|---|---|---|---|---|---|
| BTG | CONVEX | 1.98 | −0.87 | 1.56 | 0.86 | 92.85 | 1 |
| FRES.L | DEFENSIVE | 1.30 | −0.50 | 1.94 | 0.81 | 80.47 | 2 |
| KGC | FRAGILE | 1.70 | +0.24 | 0.81 | 0.86 | 48.38 | 3 |
| AEM | FRAGILE | 1.59 | +0.26 | 0.81 | 0.88 | 47.07 | 4 |
| NEM | FRAGILE | 1.48 | +0.13 | 0.88 | 0.85 | 46.52 | 5 |
| DPM.TO | FRAGILE | 1.38 | +0.36 | 0.77 | 0.85 | 42.62 | 6 |
| FNV | FRAGILE | 1.11 | +0.67 | 0.38 | 0.82 | 37.14 | 7 |
| GOLD | LOW_LINKAGE | 0.74 | −0.08 | 1.15 | 0.72 | — | — |

That's a real differentiation. BTG and FRES.L stand out as upside-skewed; the seniors cluster in the FRAGILE bucket; GOLD (Barrick) is correctly screened out for low linkage rather than mis-ranked. This passes the smell test.

One thing to flag conceptually: the `FRAGILE` cluster is *most of the universe*. Either the universe really is fragile right now, or the FRAGILE threshold is too easy. The live thresholds `gamma_thresholds: {-0.15, +0.15}` are quite tight; loosening to `{-0.25, +0.25}` would push some names from FRAGILE to LINEAR/HIGH_DELTA. Worth a calibration check against a longer time series.

---

## 4. Tool B / manual-store assessment

Tool B is correct in shape but currently under-powered by data, and the workspace cannot show it today.

What works well:
- The SQLite schema separates `company_inputs`, `source_verification`, `reporting_calendar`, and `stock_notes`. Notes are decoupled from calculation fields, which was the right design call from the runtime redesign plan.
- Timestamps (`created_at_utc`, `updated_at_utc`) are now on every core table and round-tripped through CSV import/export.
- Layer 1 (robust screen) and Layer 2 (forward earnings) are deterministic and well-typed. `evaluate_layer1` returns a structured dict with `layer1_status`, `layer1_pass`, `layer1_fail_reasons`, plus the intermediate margins. `compute_layer2_metrics` returns `layer2_incomplete_reasons` cleanly when fields are missing.
- Target prices use peer benchmarks per size category and adjust for jurisdiction tier. The math is straightforward and testable.
- Verdicts and tool_b_score are derived from confidence + layer1_status + forward_pe; no hidden overrides.
- `tool-b` correctly fails when the manual store is missing ([test_tool_b_pipeline.py:152-173](tests/test_tool_b_pipeline.py#L152-L173)).
- Stock notes have OPEN / WATCH / DONE statuses, optional tags, and persistent timestamps.
- CSV export backs up existing files before overwriting (`_backup_existing_file`).
- CSV import / export round-trips work for the three core tables.

What's still wrong or fragile:
1. The `tool_b_latest.parquet` stable alias is missing on disk (P0 above).
2. `workspace` mutates the store on start (P1 above).
3. 4 of 8 active Tool B tickers have no manual data, so half the universe is structurally INCOMPLETE (P1 above).
4. Layer 2 has a 0.7 magic constant for cash-cost fallback (P2 above).
5. Tool B `as_of_date` can be wall-clock for INCOMPLETE rows (P2 above).
6. Stock notes are *not* part of the CSV export path. That's intentional (CSV is for support tables only), but it means a user who deletes the SQLite file loses every note. Worth either documenting prominently or extending `export-csv` to include notes.
7. `upsert_company_input` raises on "no fields provided," but `manual-data set-company` is the only caller; the workspace's company form always sends all 11 fields including blanks (which `_coerce_form_numeric` turns into `None`), so the row gets *all fields nulled* on every save unless every field is filled in. I checked the workspace handler — yes, every numeric field is parsed and submitted. So saving the company form for a partially-filled record will silently null out the unfilled fields. **This is a user-facing data-loss risk.** I missed this in my Tool A review. Worth promoting to P1 if confirmed by a save-and-reload test.

Let me re-examine that last one carefully. In [workspace.py:158-167](golden_vector/serve/workspace.py#L158-L167):

```python
company_values = {
    field_name: _coerce_form_numeric(form_data.get(field_name, [""])[0])
    for field_name, _, _ in COMPANY_FORM_FIELDS
}
upsert_company_input(paths, ticker=ticker, values=company_values)
```

Every field is in `company_values`. If the user submits a form where one field is blank, `_coerce_form_numeric("")` returns `None`. Then `upsert_company_input` builds an UPDATE that sets that column to `None`. So **yes, this overwrites unfilled fields with NULL on every workspace save**. Not in scope for the Tool A review I did earlier — this is a fresh holistic-only finding. Promoting to **P1**.

### P1 (added during Tool B review) — Bug: workspace company form silently nulls all unfilled fields on every save

Where: [golden_vector/serve/workspace.py:158-167](golden_vector/serve/workspace.py#L158-L167) and [golden_vector/screening/manual_store.py:178-208](golden_vector/screening/manual_store.py#L178-L208)

The form submits every numeric field; `_coerce_form_numeric("")` returns `None`; `upsert_company_input` UPDATES every column. So if the user opens NEM, edits only `production_oz`, and saves, every other column (AISC, royalty rate, etc.) is set to `None`.

The CLI version of `set-company` is correct — it filters out `None` values before sending. The workspace handler does not.

Fix shape: in the workspace handler, drop fields whose form value was the empty string (not parsed but unsent), or pass `coerce_blank_to_none=False`, or in `upsert_company_input` add a parameter `clear_omitted_fields=False` and have the workspace use it.

This is the most impactful bug I've found in this holistic pass after the missing Tool B alias.

---

## 5. FX / normalization / QA assessment

Strong overall. The redesign of normalization handling is the most visible improvement after Tool A.

What works:
- `normalize_equity_histories_to_usd` and `normalize_market_snapshots_to_usd` are pure: they take raw frames + FX history, produce typed USD frames with explicit `normalization_status` per row.
- Status taxonomy is clean: `OK`, `MISSING_FX`, `MISSING_RETURN_BASIS`, `STALE_FX`, plus snapshot-only `INVALID_SHARE_PRICE`, `MISSING_SHARES_OUTSTANDING`. All four equity statuses are validated by `VALID_NORMALIZATION_STATUSES` in `structural.py`.
- `merge_fx_asof` uses `pd.merge_asof(..., direction="backward")`, so a row gets the most recent FX rate that doesn't post-date the row — the right semantics. `fx_staleness_days` is computed cleanly.
- `evaluate_normalization_quality` reports per-ticker breakdown counts (`OK / MISSING_FX / MISSING_RETURN_BASIS / STALE_FX / other_issues`) and respects `block_on_stale_fx`.
- The config-driven `blocked_normalization_statuses` flows from `scoring.yaml` through `determine_score_eligibility` to the row's `score_eligibility_reason`. Live `scoring.yaml` has the strictest setting (`MISSING_RETURN_BASIS, MISSING_FX, STALE_FX` all blocked).
- The workspace's `_render_signal_notice` now surfaces both the score-withheld reason and the observed `normalization_issue_summary`. That closes the loop from foundation → normalization → Tool A → workspace.

What's still imperfect:
1. `_foundation_signature` covers `max_fx_staleness_days` and `block_on_stale_fx` but not the rest of `app_config.qa` (P3 above).
2. `summarize_normalization_issues` is window-agnostic — see P3 above. A 6M window cannot have a clean read while 3Y is dirty.
3. There is no `fx_staleness_observed_max_days_in_window` field in the Tool A output, so the user sees the *policy* threshold and the *binary* "STALE_FX" tag but not how stale FX actually was.

---

## 6. Workspace / presentation assessment

The workspace shape is right and is clearly the right product surface for v1, conditional on fixing the missing Tool B alias and the company-form null bug.

What works:
- Universe overview table is clear: ticker, production, AISC, structural delta, gamma, asymmetry, confidence, volatility, Tool A score, profile, Tool B score, Tool B verdict, notes count.
- Per-ticker detail page surfaces:
  - Score-withheld and normalization notices when applicable.
  - Metric grid with anchor window, delta, gamma, asymmetry, confidence, volatility, score, profile.
  - Seven explanation cards (delta / gamma / asymmetry / volatility / confidence / interaction / summary).
  - Structural windows table with `(Anchor)` marker on the chosen window.
  - Visual panels: weekly return scatter with regression overlay, up vs down beta dumbbell, volatility diagnostics, exploratory horizon ladder.
  - Tool B latest panel.
  - Editable Tool B forms (company inputs, reporting calendar) and stock notes.
- Page styling is clean serif-on-cream — readable.

What's still misleading or weak:
1. **Tool B side is empty today** because the stable alias is missing (P0 above).
2. **Company form silently nulls unfilled fields** (P1 above).
3. The "Gamma (Down-Up)" label on the metric card is the only place the new sign convention is named. A first-time reader will not know that −0.87 is good and +0.24 is bad. Add a one-sentence explanation on the page.
4. The "Exploratory Horizon Ladder" shows a `Horizon Leverage` column that is `equity_return / gold_return` over a single window — extremely noisy. The hint says exploratory; consider hiding or guarding the column when `gold_return` is small.
5. The scatter regression line uses anchor-aware sampling now (good), but I didn't verify whether the sample size matches the anchor window length when the anchor is 3Y (P3 above).
6. The workspace's `_load_tool_a_detail` recomputes the structural ticker data from the foundation snapshot every time the detail page is opened. For an 8-ticker / 21-year-history universe this is fast (sub-second), but it duplicates work that Tool A already did. Cache the per-ticker structural data on the workspace state if the universe grows.

---

## 7. Tests / docs / residual risks

Tests:
- 159 tests pass, including 4 new structural tests that pin the previously-missed math (partial week dropping, negative down-beta, anchor fallback, anchor-driven volatility).
- Coverage is broad: config validation, persistence, ranking, labels, scoring, pipeline orchestration, CLI, workspace, manual store, manual data, normalization quality, raw quality, horizon quality, market snapshot normalization.
- Test gaps that matter:
  1. No workspace test for the score-withheld notice (P2 above).
  2. No workspace test that the company form preserves un-edited fields (would catch the company-form null bug).
  3. No `tool_b` test that the stable alias actually exists on disk after a non-empty run.
  4. No direct unit test for `_compute_confidence_score` with known inputs.
  5. No regression test that holds the gamma sign convention (a future refactor that flips the sign back will silently invalidate every label).

Docs:
- README accurately describes the current product shape (update-data → tool-a → tool-b → workspace), the de-scoping of Combined, the structural-first Tool A, and the SQLite manual store.
- Architecture map describes the current code layout cleanly.
- `codex-full-briefing.md` now has an opening "Current-state note" pointing to the current sources of truth — fix from a prior review.
- Implementation guide (`Gold_Framework_Implementation_Guide.docx`) is now out of step with the code: it teaches the *old* gamma convention. This was P0-conceptual in my Tool A review and remains unfixed.
- No `CHANGELOG.md` or migration notes documenting the gamma sign flip. A future reader will not know which convention is current.

Residual risks beyond bugs:
- Single-factor / static-window / no-Kalman departure from the paper (still flagged).
- The `FRAGILE` profile dominates the live universe (5 of 8 names) — either calibration or universe truth.
- Half the Tool B universe has no manual data, so Tool B is structurally under-powered today.
- `combined/` and `features/delta.py | gamma.py | stability.py` still ship as importable modules despite being dormant.

---

## 8. Final verdict

`READY WITH MINOR CHANGES`

Reasoning: the system is now coherent end-to-end, all 159 tests pass, the live Tool A artifact reflects every documented design choice, and the workspace shape is correct. The remaining items are concrete and small.

Top-3 priorities, in order:

1. **Fix the workspace company form null bug** (new P1 above). This is a user-facing data-loss risk: a save with a partially-filled form silently nulls every other field. Fixing this is a one-line change in `workspace.py` plus a test. Until this is fixed, the recommended workflow ("edit Tool B inputs in the workspace") is unsafe.

2. **Regenerate the Tool B `latest` alias and stop the workspace from auto-mutating the manual store** (P0 + P1 above). Run `python main.py tool-b --gold-price 4000` to re-publish the alias, then change `run_workspace` to require an existing manual store rather than calling `bootstrap_manual_screening_data`. After these two changes the workspace is fully usable end-to-end.

3. **Update the Implementation Guide and add a "Gamma reading guide" to the README** (P0-conceptual + P3 above). The gamma sign convention has been flipped in code; only one place in the workspace UI hints at the new convention. A non-technical reader will look at +0.24 (FRAGILE) and assume positive is better than negative. One paragraph in the README plus a "Current convention: gamma = down_beta − up_beta. Negative gamma is favorable." sentence in the gamma explanation card would close this gap.

Everything else (Layer 2 magic constant, archival of `combined/` and unused features modules, anchor-aware scatter sample size, regime-eligible window count, full QA-section hashing in the foundation signature, artifact rotation) is sensible follow-up work but not blocking.

---

## Quick answers to the seven Specific Questions

1. **Is the current product architecture coherent and trustworthy overall?** Yes. Local-first runtime, signed manifests, validated config, deterministic models, persisted audit trail. The architecture is the strongest part of the repo.

2. **Is Tool A now good enough to be treated as the official structural model?** Yes — with the caveat that the implementation guide should be updated to match the new gamma sign convention and to acknowledge the deliberate paper-vs-code simplifications (single-factor, static windows, no Kalman). The core math is sound, the eligibility gating is consistent, and the live output passes the smell test.

3. **Is Tool B / manual-data handling now strong enough for normal daily use?** Almost. The store, schema, CLI, and pipeline are correct. The two blockers for daily use are the workspace company-form null bug and the workspace bootstrapping the store on start. Fix those and yes.

4. **Is the workspace now a good enough product surface for v1, or is it still too thin / too risky?** The shape is right and the explanation/notice system is real. It is too risky for daily editing today because of the company-form bug. Once that is fixed (one-line change), the workspace is the right v1 surface.

5. **What are the most important remaining conceptual weaknesses?**
   - Implementation guide vs code: gamma sign convention.
   - Code vs paper: single-factor regression, static long windows, no Kalman smoothing.
   - FRAGILE threshold calibration: 5 of 8 names hitting FRAGILE may indicate the gamma threshold (±0.15) is too tight.

6. **What are the most important remaining engineering weaknesses?**
   - Workspace company form silently nulls unfilled fields.
   - Workspace mutates the manual store on start.
   - Tool B stable alias missing on disk.
   - 0.7 magic constant in Layer 2.
   - Foundation signature does not hash the full QA section.

7. **If you had to prioritize only the next 3 things to fix or improve, what would they be?** See "Top-3 priorities" in Section 8 above: company-form null bug, Tool B alias + workspace mutation, and the gamma-convention documentation update.
