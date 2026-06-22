# Review request for Codex — options-UI review FIXES (re-review)

Branch: `dev-vic` (pushed). You wrote the original review
(`codex_review_options_ui_and_completion.md`, verdict **READY WITH CHANGES**). This is
the fix pass for all 7 findings. Please re-verify **first-hand** against the tree and
write findings to `reviews/codex/codex_rereview_options_ui_fixes.md`. Agent fan-out
welcome. Full suite: **1259 passed**, ruff clean.

## Commits to review (against `main`)
- `a113c36` — MED accuracy (status/delta ⓘ) + null notes + M7 + LOW
- `ba936ce` — HIGH atomic option publish (`atomic_write_many`)
- `6e0e001` — M1 Tool A/B refresh provenance stamping

## What changed, per your finding
- **HIGH (publish not atomic):** new `atomic_write_many()` in `common/files.py` —
  stage every file to a temp, then swap all onto targets with prior-bytes backup +
  rollback. Split the history shrink guard into `prepare_option_signal_history()` so it
  runs while staging. New `publish_option_artifacts_and_history_atomically()` advances
  the signal history AND flips every `*_latest` alias as ONE transaction; `cli.py`
  refresh uses it. `write_parquet_into()` added for direct staging writes.
- **MED (`option_candidate_status` ⓘ wrong rule):** rewritten in `column_help.py` to the
  real slot rule — `_passes_slot_liquidity` (spread + open interest + minimum mid +
  usable IV), strict (Tradable) vs watch tiers; the threshold sentence now resolves the
  bucket-specific spread caps (`option_near_atm_strict_max_spread_pct` …).
- **MED (`option_candidate_delta` ⓘ wrong):** delta is now described as a fit/shape
  signal WITHIN an OTM-chosen bucket, not the bucket selector (`_bucket_fit` = OTM range;
  delta only feeds `delta_gap`).
- **MED (M7 Tool A/C/D):** `_read_optional_parquet` now validates required ranking
  columns for manifest-resolved current Tool A/C/D sources and raises
  `CandidateFinderSourceError` → friendly 503 (not just Tool B). Anchors:
  Tool A = down/up_beta_core + structural_delta_core; Tool C = downside/upside ranks;
  Tool D = quality_rank.
- **MED (null notes):** `collapsible_text_td()` + the on-disk note-tuple loader
  (`_tuple_value`/`_clean_members`) drop `None`/`pd.NA`/JSON-`null` members.
- **LOW (dropped thresholds):** `app_config` threaded through the two threshold-backed
  help calls in `detail_panels.py`; added a **self-discovering** guard test in
  `test_workspace_app.py` that fails if any threshold-backed `help_th/help_icon/help_term`
  call omits `app_config`.
- **M1 (mixed-refresh provenance):** `_stamp_frame` now writes
  `built_from_tool_a_refresh_id` / `built_from_tool_b_refresh_id` on every option
  artifact (additive columns, **no schema bump**), wired from the Tool A/B frames the
  build read via `tool_refresh_run_id()`.

## What to scrutinize (highest value first)
1. **HIGH correctness — be adversarial.** Is `atomic_write_many` genuinely
   all-or-nothing? Check: the copy2-backup → restore-on-failure rollback; stage-then-swap
   ordering; the Windows `_replace_with_retry` interaction; that the shrink guard fires
   during staging before ANY swap. Can any interleaving still leave history advanced with
   a half-flipped alias set? What residual crash window remains, and is it acceptable for
   a local single-user tool?
2. **ⓘ accuracy RE-VERIFY (your cardinal concern).** Independently confirm the
   `option_candidate_status` text matches `_passes_slot_liquidity`/`_slot_thresholds` and
   the threshold sentence quotes the right config fields; confirm `option_candidate_delta`
   matches `_bucket_fit` vs `delta_gap`. Flag any remaining inverted/over-stated claim.
3. **M7 column choice.** Are the required-column anchors correct AND minimal? Could a
   healthy artifact ever legitimately miss one and wrongly 503? Should the set be broader
   or config-derived?
4. **M1 scope.** Is `snapshot_refresh_run_id` (fallback `source_run_id`) the right
   "built-from" id? Is NOT bumping the schema version correct (additive columns)? Is it
   acceptable to defer wiring `_refresh_alignment` to CONSUME the stamped ids, or should
   that be in scope now?
5. **LOW guard test.** Does it actually catch a threshold-backed call missing
   `app_config`? Any threshold key still unrouted on any page?
6. **Null notes.** Any other path that stringifies null members before
   `collapsible_text_td` sees them?

## Deferred / opinions wanted
- **M1 alignment-engine:** provenance is stamped but `_refresh_alignment` still compares
  live latest inputs rather than reading the stamped ids. Defer, or pull in now?
- **M5/M6** (pre-compute candidate-finder scenarios / persist scenario ladders): still
  deferred as milestone-sized; bounded request-time compute is acceptable for a local
  single-user tool — agree?
