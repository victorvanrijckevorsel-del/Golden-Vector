# Codex review request — Tool A "Gold Sensitivity" 2Y/5Y display-window feature (Phase 2)

Hi Codex. Please do a deep, adversarial review of the just-finished Phase 2 work on `dev-vic`.
Claude already ran an 8-dimension agent-fleet review (41 agents, 29 confirmed findings) and
fixed everything below; your job is to independently verify the fixes hold and hunt for
anything the fleet and Claude missed. **Trust the tree, not this summary** — read the code.

## What Phase 2 does
The Gold Sensitivity overview (`/tool-a`) beta-window selector previously offered the 3
SCORING windows **6M / 12M(=1Y) / 3Y**. Phase 2 adds two **DISPLAY-ONLY** windows **2Y** and
**5Y** so a trader can see how a miner's up/down gold beta changes over longer lookbacks.

## THE LOAD-BEARING INVARIANT (Option B) — attack this first
2Y/5Y are computed + persisted but must **NEVER** influence any scoring/ranking/eligibility/
confidence/profile/anchor output. These fields must be byte-identical regardless of whether
2Y/5Y rows exist or how extreme their values are:
`tool_a_score, tool_a_rank, confidence_score, confidence_label, profile_label, score_eligible,
score_eligibility_reason, eligible_structural_window_count, positive_delta_window_count,
structural_delta_core, structural_gamma_core, up_beta_core, down_beta_core, asymmetry_ratio_core,
anchor_window_id, volatility_anchor_window_id, delta_stability_score, normalization_issue_summary`.
Scoring windows stay exactly {6M, 12M, 3Y}; `eligible_structural_window_count` counts only those (max 3).

## How the invariant is enforced (verify these are sufficient + non-bypassable)
- `golden_vector/model/pipeline.py` `_build_tool_a_outputs`: a `scoring_frame` filter restricts
  every scoring/anchor/eligibility/normalization consumer to `app_config.scoring.structural_windows`;
  the full `frame` (incl. 2Y/5Y) only populates the new `*_2y`/`*_5y` display columns.
- `_window_value_map` iterates `weight_map` (StructuralWindowWeights, locked to {6M,12M,3Y}).
- `choose_structural_anchor_window` / volatility anchor only use `anchor_window_preference()` = [12M,3Y,6M].
- Config `ScoringConfig.display_windows_disjoint_from_scoring` (model_validator) rejects any overlap
  between `structural_display_windows` and `structural_windows`, so the model can never emit a
  duplicate window row that would inflate the count.

## Files changed (review all)
Model/config: `golden_vector/contracts/config_models.py`, `golden_vector/contracts/data_models.py`,
`golden_vector/model/pipeline.py`, `golden_vector/model/structural.py`, `golden_vector/lab/validation.py`,
`golden_vector/model/benchmark_comparison.py`, `golden_vector/portfolio/benchmark_betas.py`.
Serve: `golden_vector/serve/windows.py`, `golden_vector/serve/overview_tool_a.py`,
`golden_vector/serve/workspace_state.py`, `golden_vector/serve/detail_panels.py`.
Tests: `tests/test_config_models.py`, `tests/test_structural.py`, `tests/test_tool_a_pipeline.py`,
`tests/test_windows.py`, `tests/test_lab_validation.py`, `tests/test_persist_tool_a.py`,
`tests/test_workspace_datatables.py`.

## The one LIVE correctness bug the fleet found (please re-verify the fix)
`golden_vector/lab/validation.py::reconstruct_cores_at` rebuilt the PIT core from the structural
panel, which now carries ELIGIBLE 2Y/5Y rows. `model/structural.weighted_median` defaults an
**unmapped** window's weight to **1.0**, so the display rows leaked into the reconstructed core and
broke `test_reconstruction_parity_against_live_artifact` (the no-forked-math contract). Fix: the
reconstruction now restricts `values` to the `weight_map` (scoring) windows, mirroring the pipeline.
New test `test_reconstruct_cores_ignores_display_windows` pins it. **Please check whether the same
"weight defaults to 1.0 for unmapped keys" footgun lurks in any OTHER caller of `weighted_median`.**

## Other confirmed fixes (P2/nit) — verify each is correct and complete
1. Config positivity guard `ConfidenceThresholds.ordered_thresholds` now includes
   `minimum_observations_2y/5y` (was silently accepting 0/negative display floors).
2. `structural_display_windows` `max_length` tightened 4 -> 2 (only 2Y/5Y are legitimate).
3. `serve/windows.py::window_is_reliable` — dropped the hardcoded `min_weeks=20.0` (a config twin
   of `minimum_observations_6m` and wrong per-window). Reliability now = status_ok AND fit_ok; the
   per-window sample floor lives once in config and is enforced upstream via LOW_OBSERVATION status.
4. One-copy: added `SCORING_WINDOWS`/`DISPLAY_WINDOWS` to `serve/windows.py`; `workspace_state._STRUCTURAL_WINDOWS`
   now imports `SCORING_WINDOWS`; `detail_panels.py` inline `("6M","12M","3Y")` literal replaced with
   the imported constant; benchmark `_win_num_td` suffix now uses `window_suffix()`.
5. Overview ticker link carries `?window=<suffix>` so the selection survives click-through.
6. Stale docstrings in `windows.py` + `overview_tool_a.py` updated to the 5-window set.
7. Benchmark betas now carry 2Y/5Y columns (`benchmark_betas.py`) + `_WINDOW_COLUMN_SUFFIX`/`_WINDOW_COLORS`
   gained 2Y/5Y. Until the next refresh rebuilds the benchmark artifact, the overview shows an explicit
   "GDX/GDXJ benchmark · n/a for the {window} window yet" footer instead of a vanishing footer.
8. Tests: rank-parity guard hardened with a decision-boundary subject (BRD: 2 eligible scoring windows),
   a deliberate score tie (TIA/TIB), a STALE_FX normalization-leak probe, and `normalization_issue_summary`
   + `delta_stability_score` added to the protected list. New config/persist/window/render-level tests added.

## Known-deferred (NOT regressions — confirm they degrade gracefully, don't re-file)
- **Benchmark artifact rebuild**: the 2Y/5Y benchmark code is in place but the live benchmark_betas
  parquet won't have the columns until the next portfolio/refresh run; the n/a footer covers the gap.
- **Detail page (`/ticker`)**: intentionally stays at the 3 scoring windows (2Y/5Y are overview-only).
  This is a documented scope decision (Victor asked for the selector on Tool A overview + Tool C, not
  the detail page); `_STRUCTURAL_WINDOWS = SCORING_WINDOWS` makes it one deliberate definition.

## What to return
File-by-file findings with file:line, severity (P0/P1/P2/nit), evidence, and a concrete fix.
Especially: any path where a 2Y/5Y window can still reach a scoring/rank/anchor output; any other
`weighted_median` unmapped-key leak; any test that passes by accident; any house-rule violation
(serve arithmetic, config twins, duplicated window logic) the fleet missed.
