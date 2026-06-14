# Claude Full Review - Lab Relative-Performance Curve (held for reconciliation)

**Date:** 2026-06-14 - **Base:** main b742be9 (but reviewed working tree INCLUDED
Codex's uncommitted refactor, so line numbers in Codex-zone files are approximate).
**Status:** findings are REFERENCE ONLY. Per Emanuel's decision, Codex commits its
episode-spine refactor first; then these get re-checked against the clean base and
applied. NOTHING applied yet.

A 5-lens adversarial panel (correctness / leakage / serve-arch / ux-honesty /
edge-tests) ran read-only. Overall: one ship-blocking bug + real one-copy /
sort-correctness / honest-degradation gaps. No live crashes.

## Which files are mine vs Codex's refactor zone
- **Mine, NOT in Codex's diff** (fix directly after Codex commits): `overview_lab.py`,
  `lab_curve_page.py`.
- **Codex's refactor zone** (reconcile with what Codex already changed):
  `conditional_dial.py`, `forward_returns.py`, `lab_curve_data.py`, `workspace.py`,
  `scorecard*`, the test files.

## MUST-FIX
1. **Banner two-truths (SHIP-BLOCKING, my code, latent).** `overview_lab.py` sources
   the banner's `usable` count from META (`bucket_availability`) while the table
   renders from `data.rows`. If they diverge (stale/partial meta) the page can show
   "No miner has countable history" ABOVE ranked, clickable rows. Fix: derive
   `usable`/`total` from `data.rows` (`sum(not r['gdx_insufficient_history'])`), keep
   meta only for selector-label hints. NOT firing on the current healthy artifact
   (meta == rows), so latent, not a hotfix.
2. **Greyed rows don't sort last (MED, my code).** Insufficient-row numeric cells emit
   bare `<td>—</td>` (no data-order) -> DataTables interleaves them on re-sort. Render
   the 4 numeric stat cells via `_fmt_numeric_td(None, ...)` so they carry the
   sort-last sentinel.
3. **Episodes column sort broken (MED, my code).** "Weeks (effective)" header is
   `sort_numeric` but the cell `150 (11.5)` has no data-order -> NaN -> caret no-ops.
   Add `data-order=<eff_n>`.
4. **config_hash order-sensitive (MED, Codex zone).** `dial_config_hash` hashes ordered
   lists, so reorder/subset false-flags STALE. Canonicalize to sorted SET.
5. **No live horizon-set coverage (MED, tests).** Tests never build 8w/26w nor pin
   `DIAL_HORIZONS_WEEKS`. Add a pin test (`== [4,8,13,26]`, `52 not in`) + an e2e
   fixture across all four horizons.

## SHOULD-FIX
- **Chart B bridges interior gaps (MED, Codex zone):** `cumulative_rebased` cumsum
  skips interior NaN (bridges a gap as a zero week). Fail loud on interior NaN or
  `cumsum(skipna=False)`.
- **Missing/corrupt meta misdiagnosed as STALE (LOW, lab_curve_data):** `_read_meta`
  returns `{}` for both absent and corrupt -> wrong "missing columns" banner.
  Distinguish CORRUPT/metadata-missing.
- **All-insufficient banner says "switch to 13w" while you're ON 13w (MED, my code):**
  make horizon-aware; reference the default-horizon constant, not the literal.
- **Forked bucket resolution (MED, one-copy):** `workspace.py` re-implements the
  loader's bucket precedence. Expose `selected_bucket` on `LabCellsData`, delete the
  fork.
- **Headline denominator can drift from Chart A (LOW, lab_curve_page):** filter
  scenario_points to alpha-present before counting (match the SVG filter).
- **Anchor-cadence docstring overclaims (LOW, docs):** "every h-th surviving episode
  (>= h calendar weeks apart)".
- **Consistency-invariant tests only horizon 13 (LOW):** parametrize over the set.
- **Dead `selected_horizon` param (LOW, my code):** unused; drop it.
- **Greyed ticker relies on colour (LOW, a11y):** add a non-colour "(no data)" marker.
- **Banner omits GDX basis (LOW):** add "against GDX".
- **Empty-but-valid cells -> "not built" (LOW, lab_curve_data):** distinguish EMPTY
  from MISSING.

## DISMISSED (verified not worth doing)
- Chart A/B positional x-axis: faithful on contiguous weekly data (0 interior gaps);
  the only teeth is the Chart B gap-bridge, covered above.
- Unreachable STALE branch in relstrength path: harmless defense-in-depth.
- Horizon-999 substitution / zero-episode ticker vanishing: defensible as designed.

## Reconciliation note
Several MUST/SHOULD items (config_hash, cumsum, meta-stale, forked-bucket, horizon
tests) sit in files Codex is refactoring — check whether Codex already fixed them
before re-applying. The `overview_lab.py` / `lab_curve_page.py` items are clean to
apply (Codex didn't touch those files).
