# Phase 1 (M0 blockers + M1) — self-review record, 2026-08-11

- **Scope:** every Phase-1 code commit on `dev-vic`, `ce2583a..4bbd671` (M0 round-two blocker
  fixes, M1a contracts, M1b producers + stage + wiring, M1c options machinery + v4 switch,
  refresh policy fixes, and the self-review fix round).
- **Method (per the repo's review canon):** green full-suite baseline first → two independent
  adversarial reviewers (one per lane, briefed to break the code, findings ranked and
  confidence-tagged) → every finding verified first-hand before fixing → fixes in two lane
  commits + one orchestrator commit → final full suite. Both reviewer reports are reproduced in
  the finding tables below; nothing was summarised away.

## 1. Verification evidence

| Gate | Result |
|---|---|
| Full suite BEFORE the fix round (deterministic order) | green, exit 0 |
| Options-lane fix suites | 159 passed, ruff clean |
| Ticker-lane fix suites | 117 passed (23 new tests), ruff clean |
| Refresh-order suites after the step swap | 46 passed |
| Full suite AFTER the fix round | 6 failed / 1,899 passed — all six were ONE root cause: `tests/test_latest_data.py` hand-builds `AppConfig` directly and lacked the now-required `ticker_page` field (no lane's focused selection includes that file — exactly what the phase-gate full run exists to catch). Fixed by loading the real `config/ticker_page.yaml` (one copy, no duplicated catalog); the file is green (7 passed) and a grep proves it is the ONLY test constructing `AppConfig` directly, so no other file can hide the same failure. No third full run — the second run already proved the rest of the tree, and a test-file-only fix cannot change other suites' results (blast-radius rule). |
| Real-workspace proof | standalone `ticker-page` stage: 12 files, 395,338 rows, ~2.6 min, zero warnings; IV/RV migration dry-rerun: 0 changed values (idempotent under the shared implementation) |

## 2. Options-lane findings and dispositions (fix commit `cded31d`)

| # | Finding (reviewer, confidence) | Disposition |
|---|---|---|
| P0-1 | Migration computed benchmark (GDX/GDXJ) IV/RV through a forked basis production could never reproduce — all 206 backfills would cliff to NULL next refresh (CONFIRMED, measured) | **Fixed at the root**: `realized_vol_price_basis` is THE basis resolution incl. the documented USD-ETF `*_local` fallback; production now emits benchmark iv_rv; the migration deletes its forked math and calls production's `_realized_vol` date-sliced. Dry comparison vs the live store: **0 changed values** — the store already holds exactly what production now produces. |
| P0-2 | No loss guard; benchmark branch untested; no parity test (CONFIRMED) | **Fixed**: migration aborts naming tickers before any write if non-nulls would shrink; exact parity test vs production; benchmark-branch test; missing-price-file abort test. |
| P1-3 | Corrupt previous chain history silently became "first run" — no-shrink guard vacuous (CONFIRMED) | **Fixed**: previous history is a required read; corrupt aborts the stage, last good state stays current. |
| P1-4 | Same-day best-complete selection dead in production; a 19:30 partial capture overwrote the 16:00 complete row (CONFIRMED) | **Fixed**: the contest runs cross-run in `_merge_forward` (complete > total OI > run id); losing observations preserve the previous row verbatim incl. `capture_run_id`. The 534,406-vs-354,079 case is the test. |
| P2-5 | `int(inf)` OverflowError aborts the whole publish (CONFIRMED) | **Fixed**: per-field finite gates; row survives; reason in `capture_quality`. |
| P2-6 | Mixed 3/4 manifests passed freshness while carry-forward rejected them (CONFIRMED asymmetry) | **Fixed**: freshness requires one version across required artifacts. |
| P2-7 | Serve schema gate lost the parquet-metadata reconciliation (CONFIRMED) | **Fixed**: column vs file metadata must agree before the supported-versions check. |
| P2-8 | `feature_status` casing divergence (CONFIRMED, low) | **Fixed**: normalized like `option_artifact_sources`. |
| P2-9 | Dead row-status constants imply unimplemented behaviour | **Fixed as documentation**: v1 emits only `observed`; the other two are reserved for the deferred runs-backfill. |
| P2-10 | String date comparison latent bug in the migration | **Fixed**: `pd.to_datetime` both sides. |

## 3. Ticker-lane findings and dispositions (fix commits `4bbd671`, `f65ed3c`)

| # | Finding (reviewer, confidence) | Disposition |
|---|---|---|
| P1-1 | Forced max-favourable percentile leaked onto a `rank_eligible=False` row (CONFIRMED) | **Fixed**: max-favourable rows stay available+eligible (ratio legitimately undefined); hard post-loop invariant nulls both percentiles on any unavailable/ineligible row. |
| P1-2 | Publish not atomic across the four artifacts; fault test asserted the wrong object (CONFIRMED) | **Fixed**: two-pass publish (all immutables, then all aliases) with fault injection at both seams asserting all four aliases. **Known residual bound, documented:** a crash *inside* pass 2 can mix aliases; loaders are manifest-first and the pointer publishes last, so mixed aliases never reach a served page. A directory/pointer-level swap would remove even that; deferred. |
| P1-3 | Benchmarks structurally one generation stale — step 6 read the options manifest step 7 rewrites (CONFIRMED) | **Fixed** (`f65ed3c`): step order is now tool-d → option-artifacts (6) → ticker-page (7) → portfolio (8); a BLOCKED options publish leaves the previous manifest current and the staleness rule marks those series honestly. Failure-path truth pinned: FAILED options aborts before ticker-page runs. |
| P1-4 | Loaders never validated `schema_version` (CONFIRMED) | **Fixed**: missing/unparsable → CORRUPT; different → STALE naming both versions. |
| P1-5 | Per-row coalescing spliced dividend-adjusted and raw price bases into one series (PLAUSIBLE→confirmed mechanism) | **Fixed**: one basis column per whole series; gaps stay visible. |
| P2 batch (13 items) | zero-in-window vanishing series; calendar-vs-trading staleness days; silently skipped interior probes; PENDING misclassification on corrupt manifest; vacuous flat-slope guard; missing margin basis label; untyped empty frames (incl. a real `datetime64[s]`-vs-`[ns]` parquet round-trip find); yahoo-only tickers dropped; silent weekly-reshape no-op; float `weeks`; forced-pct tie documentation; provenance drift; identity-passing wording | **All fixed** except two, deliberately deferred with reasons below. |

## 4. Deliberate deferrals (for Codex's next pass — flagged, not hidden)

1. **`upstream_run_ids` remain `{}` in-refresh and snapshot identity is derived from the
   same-lock foundation alias** (reviewer P2-6/P2-7): passing them explicitly requires
   re-plumbing every tool step's return values through the refresh scope. The alignment
   machinery already rejects mismatched generations on the artifacts themselves, so the gap is
   observability, not correctness. Planned with M2's run-id plumbing.
2. **Alias-flip residual** (P1-2 above): mixed aliases are unreachable from served pages;
   removing the residual needs a pointer-level swap mechanism shared with the options publisher.
3. **Forced max-favourable percentile ties the pool ceiling at 100** rather than exceeding it —
   percentiles cap at 100 by definition; documented in the metric reason and asserted `>=` pool
   max in tests.

## 5. Process defects found in my own gates (recorded so they stay fixed)

- A commit gate piped pytest through `tail`, masking a red test's exit code — one broken test
  reached `dev-vic` (`941db0a`) and was fixed forward (`8d8ea58`). All gates now check exit
  codes directly.
- The worst finding of the round (P0-1) was caused by **my own worker brief** instructing a
  benchmark basis fork instead of demanding the shared implementation. The standing worker rule
  is amended: any brief that needs a numeric quantity computed must name the existing function
  to call, never describe the formula.
- I queued a redundant third full-suite run after the one-file test fix; Victor stopped it. The
  standing rule reasserted: the full suite runs exactly ONCE per phase gate; after a fix whose
  blast radius is one file, verification is that file plus proof of uniqueness (here: the grep
  showing no other direct `AppConfig` constructor), never a rerun that cannot change the
  decision.

## 6. Known environmental notes

- `tests/test_workspace_app.py` shows rare order-dependent failures under `pytest-randomly`
  (green deterministically and in both full-suite runs). Pre-existing; not addressed in this
  phase.
- The live workspace heals on the next scheduled refresh: Tool D "pending rebuild" column,
  ticker-page loaders flipping PENDING_FIRST_PUBLISH → OK, and the first v4 options generation.
