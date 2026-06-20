# Codex review request — auto-fresh fundamentals in `refresh` (commit 83ba2ae, on main)

Please deep-review the change that makes `refresh` keep the official Yahoo fundamentals fresh
automatically. Claude already ran a 19-agent read-only fleet (code confirmed correct; 5
test-hardening findings, all corrected). Your job: independently verify the load-bearing
properties and hunt for anything missed. **Trust the tree, not this summary.** Diff: `git show 83ba2ae`.

## What it does
`refresh` now runs a GUARDED fetch-fundamentals step before Tool B, so the auto-pulled
fundamentals (and the Market-vs-Ours view on `/tool-b`) never silently go stale.

## Files
- `golden_vector/contracts/config_models.py` — `FundamentalsConfig.refresh_fetch_max_age_days`
  (default 7) + positivity validator.
- `golden_vector/cli.py` — `_fundamentals_due_for_refresh(paths, app_config)` (due when the
  `fetched_fundamentals` latest alias is missing/unreadable/older than the threshold, reading
  only the `fetched_at_utc` column); `run_fetch_fundamentals(..., publish_model_state=False)`
  (writes the latest alias but does NOT promote the manifest); the refresh step in
  `_run_refresh_unlocked` (only the not-skip_tool_b branch, before tool-b; a non-zero exit warns
  and CONTINUES); `run_tool_b` passes `prefer_latest_fundamentals_alias=not _use_model_state_inputs`.
- `golden_vector/screening/pipeline.py` — `execute_tool_b_pipeline(prefer_latest_fundamentals_alias=...)`
  threaded to `load_official_fundamentals`.
- `golden_vector/fundamentals/artifacts.py` — `load_official_fundamentals(prefer_latest_alias=False)`;
  when True reads the fetched_fundamentals latest alias directly (else manifest-resolved).
- Tests: `test_cli_refresh_and_status.py` (autouse stub + due-guard incl. config-value + integration
  fetch/skip/failure), `test_cli_tool_b.py` (run_tool_b alias-wiring both directions),
  `test_config_models.py` (validator), `test_fundamentals_artifact_contract.py` (alias loader),
  `test_lab_validation.py` (parity tests hardened — see below), `test_option_carry_forward.py` (stub).

## The load-bearing properties to ATTACK
1. **All-or-nothing publish preserved.** The fetch must write the alias but NEVER call
   `write_current_model_state_manifest` mid-refresh (refresh promotes ONCE at the end). Confirm
   `run_fetch_fundamentals(publish_model_state=False)` defers the promote, and that no mid-refresh
   promote re-introduces the prior HIGH-2 carried-forward-option-window bug. Confirm a fetch failure
   leaves the published state intact and the refresh still completes.
2. **In-refresh Tool B reads FRESH fundamentals, standalone/serve read the MANIFEST.** Trace
   run_tool_b(_use_model_state_inputs=False) → prefer_latest_fundamentals_alias=True →
   load_official_fundamentals reads the fresh alias (the not-yet-promoted manifest still points at
   the prior run). Confirm standalone tool-b + serve (overview_tool_b, candidate_finder_data) still
   read via the manifest (prefer_latest_alias defaults False). Any leak of the alias mode into serve?
3. **Freshness guard.** Edge cases: missing/unreadable alias → due; parquet lacking `fetched_at_utc`
   → due (graceful, not crash); all-NaT → due; tz handling (pd.Timestamp.now(tz=UTC) vs parsed
   `fetched_at_utc`); the threshold is read from config (not hardcoded). Skips when fresh.

## Parity-test fixes (review for correctness, not just that they pass)
Running refreshes over a weekend split the universe across two adjacent W-FRI weeks (31/31). That
broke two LIVE-artifact parity tests in `test_lab_validation.py`. Claude verified parity itself was
EXACT (0.0 diff) — only coverage broke — and fixed: `test_reconstruction_parity_against_live_artifact`
(Tool A) now reconstructs each ticker at the week of ITS OWN live as-of (Tool A cores are per-ticker,
no cross-section); `test_tool_c_reconstruction_parity_against_live_artifact` SKIPS when the live
universe spans >1 as-of week (Tool C scores are cross-sectional percentiles — a single-week PIT
reconstruction can't reproduce a mixed-week ranking). **Is the Tool C skip the right call, or should
the reconstruction reproduce the mixed-week cross-section?** Is the Tool A per-ticker-week recon sound?

## Already found + fixed by the fleet (verify, don't re-file)
run_tool_b alias-wiring now asserted both directions (a dropped kwarg would fail the test);
config threshold proven honored (14-day config keeps a 9-day fetch fresh); alias-loader contract tested.

## Known-deferred (not regressions)
GBp "pence trap" for fundamentals statements (London names); rank-determinism test with ties+NA;
TSX/ASX mapper fixtures; TTM/quarterly statements (annual-only today). The "stale statement fields"
warning is benign (annual statements are months old by nature; the fetch is fresh).

## Return
File:line findings, severity (P0/P1/P2/nit), evidence, concrete fix. Especially: any mid-refresh
promote / stale-fundamentals-in-Tool-B / refresh-aborts-on-optional-failure, and whether the Tool C
parity skip is acceptable.
