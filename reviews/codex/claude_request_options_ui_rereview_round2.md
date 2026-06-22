# Review request for Codex — options-UI fixes ROUND 2 (final re-check)

Branch: `dev-vic` (pushed). You re-reviewed the first fix pass
(`codex_rereview_options_ui_fixes.md`, verdict **NEEDS CHANGES**) and raised 1 HIGH +
6 MED/LOW. This commit closes all of them. Please verify first-hand and write findings
to `reviews/codex/codex_rereview_options_ui_fixes_round2.md`. Full suite: **1266 passed**,
ruff clean.

## Commit to review (against `main`)
- `ed73380` — round-2 fixes for every finding in `codex_rereview_options_ui_fixes.md`

## What changed, per your round-2 finding
- **HIGH (no publish lock):** `run_option_artifacts_outcome` now acquires the
  single-writer refresh lock; the refresh passes `lock_held=True` (it already holds it)
  so the in-process step does not deadlock. A standalone/concurrent publish that can't
  get the lock returns FAILED and publishes nothing. New test
  `test_option_artifact_publish_refuses_while_refresh_lock_held` proves a held lock makes
  the publish refuse and republish nothing, then succeed once released. (Self-caught: the
  release call needed `return_code`; fixed.)
- **MED (M7 missing `ticker`):** `ticker` is now in `_FINDER_REQUIRED_SOURCE_COLUMNS`
  for every manifest-resolved Tool A/C/D source; a ranks-but-no-ticker artifact 503s
  instead of collapsing to empty. New test `..._missing_ticker`.
- **MED (guard accepts `app_config=None`):** the guard test now rejects
  `app_config=None` (regex requires a real value); the live offender — Tool D's flip
  table `_render_flip_section` — now receives and passes real `app_config`.
- **MED (M1 provenance imprecise):** `tool_refresh_run_id` uses ONLY
  `snapshot_refresh_run_id` (no `source_run_id` fallback), and surfaces multiple distinct
  ids as `"mixed:<id1>,<id2>"` rather than the first value. Test updated accordingly.
- **MED (status help conflates strict pass with Tradable):** reworded — slot checks are
  candidate-SELECTION gates; the badge reports the SELECTED candidate's overall global
  liquidity tier. Threshold sentence now resolves the global tradable/watch spreads and
  notes a contract can clear a wider bucket cap yet still show Watch.
- **MED (atomic_write_many overstated guarantee):** docstring is now honest — an OS-kill
  during the forward swap loop can leave a partial set; history swaps LAST so the worst
  tear is old-history + mixed-aliases, not advanced-history + stale-aliases; rollback
  restore failures are now logged, not silently swallowed.
- **LOW:** detail Watch text → "passed the relaxed checks"; Candidate Finder config
  labels/descriptions for the 0-100 composites renamed rank → score.

## What to scrutinise
1. **HIGH re-entrancy:** confirm the refresh path (`_run_refresh_unlocked` step 6 →
   `lock_held=True`) never double-acquires, and the standalone path always releases
   (finally, with the right `return_code`). Any path that still publishes without the lock?
2. **M1 mixed marker:** is `"mixed:<ids>"` the right contract, or do you want separate
   per-input columns? (Alignment-engine consumption still deferred — agree?)
3. **Status help:** is the selection-gate vs global-tier wording now accurate against
   `_candidate_side_status` + `candidate.liquidity_tier`?
4. Anything in the round-2 diff that regressed the round-1 fixes.

Deferred (unchanged, your prior OK): M1 alignment-engine consumption; M5/M6.
