# Merged Review: Phase 2 Normalization

Date: 2026-04-22
Review sources:
- `reviews/codex/codex_review_phase2_normalization_findings.md`
- `reviews/codex/claude_review_phase2_normalization_findings.md`

## Applied Fixes

### P0. Non-USD market snapshot normalization crashed because of FX column collisions
- Source: Claude
- Files updated:
  - `golden_vector/normalize/market_snapshot.py`
  - `tests/test_market_snapshot_normalization.py`
- Change made:
  - dropped pre-existing FX/USD output columns before calling `merge_fx_asof`
  - made normalized USD fields canonical outputs rather than reusing partially populated inputs
  - added a regression test proving prefilled USD values are ignored and recomputed

### P1. Run-context artifact assertion was out of sync with actual stored paths
- Source: Claude
- Files updated:
  - `tests/test_run_context.py`
- Change made:
  - aligned the test with the real artifact behavior, which stores repo-relative run artifact paths

### P1. Mixed-currency equity frames could previously normalize silently
- Source: Codex
- Files updated:
  - `golden_vector/normalize/prices_usd.py`
  - `tests/test_prices_usd.py`
- Change made:
  - kept the fail-fast mixed-currency protection
  - ensured empty frames do not use a misleading `"USD"` fallback on the batch path

### P2. Missing return basis and invalid snapshot prices were under-signaled
- Source: Codex
- Files updated:
  - `golden_vector/normalize/prices_usd.py`
  - `golden_vector/normalize/market_snapshot.py`
  - `tests/test_prices_usd.py`
  - `tests/test_market_snapshot_normalization.py`
- Change made:
  - rows with no usable return basis now get `MISSING_RETURN_BASIS`
  - zero or negative snapshot prices now get `INVALID_SHARE_PRICE`

### P2. Normalization regression coverage was too thin
- Source: Claude + Codex
- Files updated:
  - `tests/test_prices_usd.py`
  - `tests/test_market_snapshot_normalization.py`
- Change made:
  - added a fallback test for `adj_close_local -> close_local`
  - added a multi-row equity test with partial FX coverage and per-row statuses
  - added a recomputation test for snapshot USD fields

## Deferred Items

### P2. FX staleness threshold
- Source: Claude
- Reason deferred:
  - this is a real risk, but it is a policy choice as much as an implementation detail
  - adding it cleanly should happen with normalization QA wiring and config expansion, not as an isolated patch

### P2. Shared helper deduplication
- Source: Claude
- Reason deferred:
  - low risk
  - worth doing when the normalization/QA helper surface stabilizes a bit more

### P3. Explicit warning when a currency has no FX history in the provided dict
- Source: Claude
- Reason deferred:
  - useful observability improvement, but not a correctness blocker

## Current Read

The normalization slice is materially stronger after the merged review pass:
- Tool A normalization now guards against hidden mixed-currency input.
- Tool B normalization no longer crashes on non-USD snapshots.
- Canonical USD outputs are recalculated consistently instead of trusting partially filled inputs.
- Test coverage is better around fallback logic and per-row status behavior.

## Residual Risk

- I still could not re-run `pytest` in this shell because there is no visible Python launcher here, even though Claude was able to run the suite in his environment.
- The stale-FX question remains open and should be addressed before depending on normalization statuses as final QA truth.

## Verdict

Blocking review findings from Claude are patched in code. The next sensible step is to wire normalization into the pipeline and add normalization-stage QA and persistence.
