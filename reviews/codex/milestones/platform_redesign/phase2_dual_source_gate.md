# Platform redesign Phase 2 gate — persisted dual-source resilience

Date: 2026-08-12  
Branch: `dev-vic`  
Authority: `reviews/codex/claude_platform_redesign_plan_final_2026-08-12.md`, §6 and Phase 2

## Outcome

Phase 2 is complete and ready for integration. Tool D now publishes one coherent schema-v4
generation keyed by `(ticker, finance_source)`. Our View and Yahoo are computed and ranked
independently, published atomically, resolved through the current model-state manifest, and read
without source fallback by the ticker page, `/tool-d`, and Candidate Finder. Lab and Portfolio
remain deliberately Our-View-only at their read boundaries.

## Commits

- `cb2810d` — Tool D v4 contract, composite persistence, Lab/Portfolio source guards.
- `9109c8b` — coherent dual-source producer, atomic publication, timings, model-state/stage gates,
  source-isolated percentile construction.
- `037e2d0` — exact-source ticker, `/tool-d`, and Candidate Finder consumers.
- `27ad511` — independent-review fixes for generation coherence, replay safety, immutable Yahoo
  provenance, canonical keys, degraded-rank exclusion, and fail-loud source labels.

## Independent review closure

The read-only review pinned `9109c8b` and found seven actionable defects. All were fixed before the
gate:

1. mixed Tool D row-generation IDs and anchors were accepted;
2. a final replay-manifest write failure could still allow live publication;
3. case/whitespace aliases could bypass composite duplicate detection;
4. degraded rows could retain score/rank/component outputs;
5. Yahoo replay provenance could capture a changed mutable fundamentals alias;
6. malformed stored finance-source labels could silently select an empty frame;
7. standalone Tool D nonzero returns lost their shared-lock completion detail.

Additional integration checks preserved honest pre-v4 Our View rendering, while Yahoo receives the
central rebuild-required reason until a v4 refresh exists. Mixed/fractional schema generations are
not served.

## Verification

### Focused tests

- Foundation and safety lanes: 118 tests passed.
- Producer and state lanes: 137 tests passed.
- Consumer lanes: ticker 41, Candidate Finder 40, workspace 100, Tool D 23 tests passed.
- Review-fix suites: contract/persistence 30, producer/provenance 57, source guards 36 tests passed.
- Consolidated Phase 2 gate: 482 tests passed; its only failure was an obsolete test fixture missing
  the new generation IDs. The corrected test passed separately, for 483/483 effective focused
  coverage.
- Ruff passed on every changed Python file; `git diff --check` passed.

### Mandatory full suite

`python -m pytest -n 8 --dist loadscope -q --disable-warnings`

- **2,291 passed**
- Duration: **332.42 seconds (5:32)**

### Real refresh and manifest proof

Command: `python main.py refresh`  
Exit code: `0`  
Parent refresh: `20260812T182356Z-refresh-26b476a3`  
Foundation refresh: `20260812T182356Z-update-data-d7e80db2`  
Tool D run: `20260812T182614Z-tool-d-9b0bb86e`

The final model-state manifest is `COMPLETE` with alignment `OK`. Both `tool_d` and `tool_d_spot`
resolve to the same immutable artifact:

`data/output/tool_d/tool_d_latest_20260812T182614Z-tool-d-9b0bb86e.parquet`

Manifest and contract verification:

| Check | Result |
|---|---:|
| Active Tool B tickers | 61 |
| Tool D rows | 122 |
| Our View rows | 61 |
| Yahoo rows | 61 |
| Duplicate `(ticker, finance_source)` keys | 0 |
| Tool D schema | 4 |
| Contract violations | 0 |

NEM sentinel values prove the persisted sources are genuinely distinct rather than duplicated:

| Source | Status | Interest expense (USDm) | Net debt (USDm) | Interest-cover gold | Quality score | Quality rank |
|---|---|---:|---:|---:|---:|---:|
| Our View | OK | 200 | 500 | 1,251.44 | 50.56 | 53.33 |
| Yahoo | OK | 229 | -2,058 | 1,256.51 | 53.26 | 52.17 |

The refresh retained truthful non-blocking warnings: one partially populated manual-data ticker
(`CLA.AX`) and stale official statement fields. These warnings pre-existed the dual-source change;
the generation itself published coherently and the ticker-page stage passed.

## Gate decision

**PASS.** The Phase 2 contract, migration, atomicity, source-isolation, consumer, full-suite, and
real-refresh requirements are satisfied. Phase 3 may begin after the normal branch integration
audit and milestone merge workflow.

## Pre-merge integration audit

Remote refs were fetched immediately before integration.

- Unmerged local branches: `dev-vic` only.
- Unmerged remote branches: none.
- Active worktrees: one — this repository on `dev-vic` at `c81a04c`.
- `dev-vic` vs `origin/main`: 0 behind, 5 ahead.
- No second branch or worktree touches Tool D contracts, persistence, model state, refresh
  publication, Lab, Portfolio, or serve consumers; no logical cross-branch reconciliation is
  pending.
- The personal untracked file `naukri.md` was excluded from every commit and integration action.
