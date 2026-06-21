# Fleet review — Claude's horizon + Finder fixes (`bf9324b` + `15ec0a5`)

**Scope:** `git diff ec6359f..15ec0a5` — the detail-page live-verify fixes (narrative split, 12M→1Y
labels, option-link window) and the Candidate Finder gold-beta horizon picker + cross-surface blend
basis labels.
**Method:** 7 specialist review lenses (read-only, first-hand) → each finding re-verified by an
independent skeptic (code + targeted tests) before counting. **13 confirmed, 0 refuted.**
**Outcome:** all 13 fixed in commit `<this commit>`; 11 new regression/quality tests added; full gate green.

## HIGH (2) — real bugs I introduced

### H1 — Window remap re-admitted score-ineligible (degraded) tickers into the ranking
`model/candidate_finder.py` gated the `score_eligible` exclusion ONLY when `criterion.source_field in
TOOL_A_SCORE_ELIGIBLE_FIELDS = {down_beta_core, up_beta_core, structural_delta_core,
downside_volatility_52w}`. The horizon picker's remap rewrites `down_beta_core → down_beta_6m`, which
was NOT in that set, so the mask was skipped and degraded tickers (blocked normalization, <2 eligible
windows, low confidence) re-entered the ranking the moment a window was picked. Reproduced end-to-end:
DEGRADED row ranked #1 under `?beta_window=6m`. Violates the flagship "degraded EXCLUDED from rankings,
not just flagged" rule.
**Fix:** derive `TOOL_A_SCORE_ELIGIBLE_FIELDS` from the window registry — the `_core` blend AND every
per-window variant of the beta/delta fields — so the gate applies identically for blend and any window.
**Tests:** `test_score_eligible_gate_covers_per_window_beta_variants` (gated set),
`test_candidate_finder_per_window_beta_still_excludes_score_ineligible` (degraded+healthy control through
`rank_candidates` on a per-window column).

### H2 — Preset bar links dropped `beta_window`
`_preset_href` built links from a manual allowlist (preset, gold_price, fundamentals_source) and omitted
`beta_window`, so clicking any preset silently reverted a window-specific screen back to the blend.
**Fix:** carry `beta_window` through `_preset_href` like the other params.
**Test:** `test_preset_links_preserve_beta_window`.

## MEDIUM (5)

- **Interaction/Summary cards flipped per window under the "does not change" banner.** They consumed the
  ACTIVE-window `volatility_context`; for CONVEX tickers whose band crosses HIGH they changed across
  windows while rendered as cross-window. **Fix:** feed them the PUBLISHED cross-window
  `volatility_context`; the per-window Volatility card keeps the active-window value. Fixed the false code
  comment too. **Test:** `test_interaction_summary_use_cross_window_volatility_not_active_window` (unit;
  fails on the old wiring).
- **Explanation partition had no guardrail** — a future title rename/addition would silently drop a card
  from both grids. **Test:** `test_explanation_card_partition_is_exhaustive_and_disjoint`.
- **Option-link Fix-D branch had no test** (only the canonical/omit path). **Test:**
  `test_workspace_default_detail_option_link_preserves_selected_window`.
- **Portfolio hedge-sizing "Down beta"** (GDX/GDXJ proxy = `benchmark_down_beta` = `down_beta_core` blend)
  kept the plain per-window help key. **Fix:** point it at `tool_c_down_beta_blend`.
- **Hardcoded `("6M","12M","3Y")`** in the Finder selector duplicated `SCORING_WINDOWS`. **Fix:** import
  and use the registry tuple.

## LOW (4)

- **Canonical Anchor card forked `window_label` inline.** **Fix:** made `window_label` falsy-safe (returns
  '' for blank) and reused it. **Test:** the Canonical Anchor card assertion in the 1Y-label test.
- **Degrade test only hit the all-absent shortcut** (never the per-item branch). **Test:**
  `test_criteria_config_for_beta_window_degrades_per_item_in_mixed_frame`.
- **1Y-label test didn't lock the Canonical Anchor card.** **Fix:** added `assert "<h3>Canonical
  Anchor</h3><p>1Y</p>" in body`.
- **New `_blend` help keys + route threading + cache-key isolation untested.** **Tests:**
  `test_blend_beta_help_keys_state_cross_window_basis`, `test_candidate_finder_route_threads_beta_window_to_loader`,
  `test_candidate_finder_cache_key_isolates_beta_window`.

## Notes
- 0 findings refuted — the fleet's verify pass held up to first-hand re-checking.
- H1 is the highest-value catch: it's the exact "degraded data leaks into rankings" class CLAUDE.md flags
  as never-again, and it had no test guarding the per-window path.
