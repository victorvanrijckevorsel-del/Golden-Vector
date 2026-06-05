# I4 Gate Review — Resilience, Schema, Provenance, Retention

**Reviewer:** Claude Code (Opus 4.8)
**HEAD:** `6d90944` (clean tree). Reviewed the two formerly-in-flight files first-hand (`app/run_pruning.py`, `ingestion/collection_resilience.py`) plus the schema/provenance commits; ran the destructive-command safety adversarially; executed the full suite.
**Grade: PASS.** The one thing I most wanted to verify — that the file-deleting `prune-runs` can't delete anything a current or retained build needs — holds up under adversarial probing. Resilience preserves the per-ticker isolation, schema validation is hardened, **744 tests pass (0 fail/skip)**, no weakened assertions. Two non-blocking follow-ups (throttling not actually active; numeric-coercion duplication grew) go to I5.

---

## `prune-runs` — the destructive command — SAFE (verified adversarially)
I read `run_pruning.py` in full and tried to construct a "delete a needed file" scenario. I couldn't. Each safety property verified:

| Property | Verdict | Evidence |
|---|---|---|
| **Dry-run is the default** | PASS | `--apply` is `store_true`; `prune_runs(apply=False)` default; deletion only inside `if apply:` (`run_pruning.py:99-102`). Tested. |
| **R1 — protects ALL retained states, not just current** | PASS | `_retained_model_state_paths` seeds with `latest_model_state.json` **plus every kept snapshot** (`:150-152`); `_protection_sets` protects each manifest's artifact `path` + `source_alias_path` + every run-id + derived run_dir (`:166-197`). I traced every file a retained build reads back to a protected anchor. |
| **Corrupt-manifest → no-op** | PASS | If no retained manifest is readable/has an artifact map, it returns zero candidates and deletes nothing (`:76-90`). Can't under-protect into a deletion. The edge Codex fixed in `6d90944`, with a test. |
| **Candidates never sourced from manifest strings** | PASS | Targets come only from fixed dir globs + `runs_dir.iterdir()`; manifest strings are used **only to protect**, never to target — so no path-traversal via a crafted manifest. `_delete_candidate` also refuses anything outside `runs_dir`/`repo_root` (`:318-325`). |
| **Only run-stamped files targeted** | PASS | `_has_retention_stamp` requires the `_<timestamp>-` pattern, so the mutable `*_latest.parquet` aliases are never candidates. |
| **Run-dirs (replay snapshots) protected by run-id** | PASS | Every run-id owning a retained build's snapshots is in `protected_run_ids`; the owning `data/runs/<id>/` survives. |
| **No-delete test is real (not vacuous)** | PASS | `test_prune_runs_dry_run_default_preserves_all_retained_manifest_artifacts` builds 3 states, keeps 2, asserts (dry-run AND `--apply`) every retained artifact + run_dir survives while the pruned oldest are gone. Would fail if protection were removed. |

**One intentional behavior to know (not a bug):** prune deletes the bulky `*_output_{runid}.parquet` *archives* even for retained builds, because the manifest references only `*_latest_{runid}`. I grepped the whole repo — **nothing reads `*_output_*`** (readers use `_latest`; `verify_manifest` reads the protected run-dir snapshots). So it's a safe archive-trim. Worth a one-line comment in `_artifact_file_candidates` noting `_output_` is deliberately unprotected, so a future feature that reads it wouldn't be silently surprised.

## `collection_resilience` — CORRECT, isolation preserved
- **Per-ticker best-effort isolation preserved (the key concern):** `call_with_retries` wraps each *entity's* fetch inside the existing per-ticker `try/except` in all six fetchers (equities, fx, gold, market-snapshot, options-phase, fetch-options). Exhausting retries re-raises → the per-ticker handler records FAIL → the loop continues. One bad ticker still can't abort the run. ✓
- **Bounded, no storm:** 3 attempts, exponential 0.5→1.0s backoff, validated config; worst-case ~1.5s added sleep per failing ticker. ✓
- **No second vendor / scheduler / request-cache** introduced. ✓
- **Stats ride the existing manifest (R3):** collection stats land on the foundation/options manifest summaries and on `stage_timings["update_data"]`, which flows into the model-state manifest — no separate stats file. ✓
- **The `6d90944` malformed-status-table fix** (status column missing → "UNKNOWN" fallback) is present and tested. ✓

## Schema validation hardening — PASS
`6d90944` made `validate_parquet_schema` **reject mixed `schema_version` values** (`_schema_versions` collects all distinct values; raises on >1) instead of accepting whichever appears first. Tested (`test_read_required_parquet_rejects_mixed_schema_versions`). Good — closes a real silent-acceptance hole.

## Suite + regressions — clean
**744 passed, 0 failed, 0 skipped, 0 xfail** (verified, not just trusted). The previously-excluded `test_run_pruning.py` + `test_collection_resilience.py` now run and pass. The whole I4 test diff is **pure additions — zero deletions, zero weakened assertions** across all six changed test files; the 3 lines added to `test_model_state.py` *strengthen* coverage (retention snapshot round-trips equal). No skipped/xfail tests anywhere.

---

## Follow-ups (non-blocking → I5)
1. **(Most worth doing) Throttling exists but is effectively OFF, and the retry policy isn't config-driven.** `RetryPolicy` is parameterizable and `YahooClient` accepts it, but the real call sites use `YahooClient()` with defaults, `throttle_seconds` defaults to `0.0`, and there's no `retry:`/`throttle:` block in `config/`. So **retry-on-failure is delivered, but the "light throttling" Phase 4 intended is not active**, and you can't slow the run to be gentler on Yahoo without a code edit. For a 60-name + option-chain live refresh, a small default throttle (e.g. 0.1-0.3s) + a config block is the cheap way to actually reduce soft-ban risk. Wire this in I5 (or a quick add before your first big refresh).
2. **Numeric-coercion duplication grew.** I4 added `_int_value`/`_float_value`/`_string_value` (collection_resilience) and `_event_int`/`_event_float` (options_phase), on top of the ~7 existing `_optional_float` copies. This reinforces the foundation review's finding #2: add `common/numeric.py` and route them through it. I5.
3. **`prune-runs` comment** noting `_output_` is deliberately unprotected. Trivial.

## Verdict
**I4 passes the gate.** The destructive retention command is genuinely safe (dry-run default, protects all retained states, no-ops on corruption, can't traverse, real no-delete test), resilience preserves isolation and is bounded, schema validation is hardened, and the full suite is green with no regressions. The data architecture (I1-I4) is now complete and solid.

**Next:** I5 cleanup — and it now carries three things: (a) **consolidate the 6 freshness/alignment verdicts onto the manifest's `_alignment`** (the top user-visible consistency item, from the foundation review), (b) **wire retry/throttle to config + activate a small default throttle** (follow-up #1), and (c) the **`common/numeric.py`** consolidation + the inline-ticker-normalize tidy-up. That closes out the plan.
