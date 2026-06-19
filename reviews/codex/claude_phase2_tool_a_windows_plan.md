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

## Open question for Codex
Is **Option B (decoupled display windows)** the right architecture, or is there a reason to make 2Y/5Y
full scoring windows? And: should the **canonical anchor** stay 12M, or is there value in offering a
longer anchor now that 2Y/5Y exist? (No anchor change planned unless advised.)
