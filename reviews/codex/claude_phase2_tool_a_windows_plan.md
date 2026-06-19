# Phase 2 build plan — add 2Y / 5Y beta windows to Tool A (Gold Sensitivity)

Status: **PLAN for Codex review** (Claude). Model-layer change → goes through plan → review → build
(not a quick serve edit). Phase 1 (serve refocus: selector 6M/1Y/3Y, direction betas, Gold-link,
value tooltips, GDX/GDXJ rows) is shipped. This adds the **2Y / 5Y** windows Victor asked for, so the
selector becomes the full **6M · 1Y · 2Y · 3Y · 5Y**.

## The design fork (the key decision)

The per-window beta math is driven by `ScoringConfig.structural_windows`, which is the SAME list the
**score/rank** consumes (it also keys `minimum_observations_<w>`, `StructuralWindowWeights`, the
`structural_anchor_window`, and confidence). So:

- **Option A — make 2Y/5Y full scoring windows.** Ripples through min-observations, weights, anchor,
  confidence, AND **changes the validated rank**. High risk; re-opens a validated surface for a purely
  presentational ask.
- **Option B — decouple "display windows" from "scoring windows" (RECOMMENDED).** Keep
  `structural_windows = [6M,12M,3Y]` exactly (scoring/rank **untouched**); add a separate
  `structural_display_windows = [2Y,5Y]` whose betas / R² / weeks / window_status / gamma / asymmetry /
  delta are **computed + persisted for display only** and never enter scoring/weights/anchor/confidence.

**Recommendation: Option B.** It honours "extra viewing windows" without disturbing the validated
ranking (which already passed the scorecard), matching Phase 1's principle that the rank is
cross-window and unchanged by the selector.

## Scope (Option B) — the touch list

1. **Config (`config_models.ScoringConfig`):** add `structural_display_windows: list[str]` (default
   `["2Y","5Y"]`), validated against a known set; **leave `structural_windows` (and its strict 3-window
   validator) unchanged.** Map each window id → months once, centrally (6M=6, 1Y/12M=12, 2Y=24, 3Y=36,
   5Y=60) so there is no scattered suffix/month math.
2. **`structural.py`:** compute window metrics for `structural_windows ∪ structural_display_windows`
   (same `_build_vectorized_window_data` / `_compute_vectorized_window_metric`; just the extra
   lookbacks). Display windows get the SAME `window_status` thin/unavailable handling — **5Y is not
   universal** (e.g. AAUC.TO ≈2.8y, THX.L ≈5.0y), so short-history names get `window_status_5y` =
   thin/unavailable and the serve layer already mutes those.
3. **`scoring.py`:** unchanged — it consumes only `structural_windows`. (A test asserts the rank is
   byte-identical before/after, proving display windows don't leak into scoring.)
4. **Output schema (`ToolAOutputRow` / `TOOL_A_OUTPUT_COLUMNS`):** add `up_beta_2y/5y`,
   `down_beta_2y/5y`, `r_squared_2y/5y`, `weeks_2y/5y`, `window_status_2y/5y`, `gamma_2y/5y`,
   `asymmetry_ratio_2y/5y`, `structural_delta_2y/5y`.
5. **Benchmark betas builder:** compute + persist GDX/GDXJ `up_beta_2y/5y` + `down_beta_2y/5y` so the
   Phase 1 reference rows work at the new windows.
6. **Serve (`serve/windows.py`):** extend `STRUCTURAL_WINDOWS` → `("6M","12M","2Y","3Y","5Y")` and the
   selector. The resolver already reads `up_beta_<suffix>` generically, so 2y/5y "just work" once
   persisted. Reconcile labels: show 12M as "1Y" everywhere (overview + detail).
7. **Detail page switcher (`detail_panels._render_window_switcher` + `_STRUCTURAL_WINDOWS`):** add the
   2Y/5Y tabs (it reads `up_beta_<win>` generically). Decide: keep `12M` as the canonical anchor tab.
8. **Tests:** schema has the new columns; structural computes 2Y/5Y; **rank-unchanged** parity test;
   5Y thin-handling on a short-history fixture; selector renders 5 windows; benchmark rows at 2Y/5Y.
9. **Rebuild artifacts** (tool_a + benchmark_betas) so the live page shows the new windows; verify.

## Risks / guardrails
- **Don't touch the rank.** The parity test (step 8) is the load-bearing guard.
- **Compute-once → persist → serve reads** — no regression in the request path (serve only reads the
  new persisted columns).
- **5Y data scarcity** — surfaced honestly via `window_status_5y` + the existing Gold-link/mute logic.
- One-copy: the window→months map lives once; reuse the existing per-window machinery, don't fork it.

## Codex review applied (2026-06-19) — corrections folded in (verdict was NEEDS CHANGES)
Codex confirmed Option B but found the plan unsafe-to-build as written. Build-ready scope now:

- **P0 — scoring-frame hard boundary (the critical guard).** `model/pipeline.py` builds
  `eligible_frame` from EVERY eligible window in the group and feeds it into `confidence_score`,
  `eligible_structural_window_count`, `positive_delta_window_count`, `determine_score_eligibility`,
  the anchor, explanations, and normalization blockers (`pipeline.py:382-438, 771-793`). Weighted
  medians are weight-protected but these are NOT — so appended 2Y/5Y rows WOULD corrupt confidence/
  eligibility/rank. **Fix:** filter to `scoring_window_ids = set(scoring_config.structural_windows)`
  in output assembly; compute ALL core/confidence/eligibility/count/anchor/explanation/blocker values
  from the scoring-only frame; use display rows ONLY to populate the new `*_2y`/`*_5y` columns.
- **P1 — 2Y/5Y observation policy.** `ConfidenceThresholds.minimum_observations_for_window()` only
  supports 6M/12M/3Y and RAISES otherwise; `structural.py` calls it for every computed window. Add
  central minimum-observation + regime-observation thresholds for 2Y/5Y (config_models + scoring.yaml)
  WITHOUT scoring weights — this is what makes `window_status_5y` honest (a ~2.8y name must NOT be
  marked eligible at 5Y by reusing the 3Y threshold).
- **P1 — expanded touch list:** the pipeline scoring-frame filter; benchmark `PORTFOLIO_SCHEMA_VERSION`
  bump + `BENCHMARK_BETA_COLUMNS` + reader tests; a model-state manifest current-state contract proving
  the new columns resolve through the manifest path (Tool A has no schema version → column-contract
  tests are the guard); `model/benchmark_comparison.py` 2Y/5Y suffix+label maps; `serve/workspace_state.py`
  `_STRUCTURAL_WINDOWS` + `_WINDOW_WEEKS` (must NOT fall back to 52w for 2Y/5Y vol) + `_WINDOW_COLORS`
  + chart/detail consumers; `detail_panels.py:1306` hardcoded window loop; `serve/format_helpers.py`
  numeric field sets; `serve/column_help.py` text; Candidate Finder + Tool C **no-change regression
  tests** (they read core fields only); a **live-column parity** check (old/rank columns identical,
  new columns additive).
- **P1 — rank-parity guard** in `tests/test_tool_a_pipeline.py`: build outputs from the same synthetic
  structural metrics twice (6M/12M/3Y only vs +2Y/5Y appended); assert EXACT equality on
  `tool_a_score, tool_a_rank, confidence_score, confidence_label, profile_label, score_eligible,
  score_eligibility_reason, eligible_structural_window_count, positive_delta_window_count,
  structural_delta_core, structural_gamma_core, up_beta_core, down_beta_core, asymmetry_ratio_core,
  anchor_window_id, volatility_anchor_window_id`; separately assert the new display columns exist.
- **P2 — overview status alignment: DONE** (`window_is_reliable` now treats `ELIGIBLE`/`OK` as usable;
  weak-R²/`LOW_OBSERVATION`/`INELIGIBLE`/thin stay muted). Committed `d8d4325` + `tests/test_windows.py`.
- **Labels/anchor (confirmed):** keep `12M` as the canonical internal id, persisted `*_12m`, and the
  `structural_anchor_window`; show "1Y" only as a display label (URL alias `1Y→12M`). Do NOT rename
  columns to `*_1y` and do NOT change the anchor.

**Build order (each gated):** (1) write the rank-parity test; (2) config 2Y/5Y thresholds +
`structural_display_windows`; (3) `structural.py` computes display windows; (4) **pipeline scoring-frame
filter (P0)** — parity test must stay green; (5) output columns + benchmark schema bump; (6) serve/
detail window registries + labels; (7) Candidate Finder / Tool C no-change tests; (8) rebuild artifacts
+ live-verify.

## Open question for Codex
Is **Option B (decoupled display windows)** the right architecture, or is there a reason to make 2Y/5Y
full scoring windows? And: should the **canonical anchor** stay 12M, or is there value in offering a
longer anchor now that 2Y/5Y exist? (No anchor change planned unless advised.)
