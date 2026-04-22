# Codex Review: Phase 2 Normalization

Date: 2026-04-22
Scope: `golden_vector/normalize`, the related contracts, and the new normalization tests.
Review mode: static review of the current normalization layer, followed by immediate fixes for any concrete issues.

## Findings

### P1. Equity normalization could silently apply the wrong FX rate to a mixed-currency frame
- Files: `golden_vector/normalize/prices_usd.py`
- Why it mattered: the first implementation picked the currency from the first row in the equity frame. If a malformed frame ever contained more than one currency, the whole ticker history would be normalized using the first currency without any warning. That breaks the repo’s hard rule against hidden mixed-currency math.
- Fix applied:
  - the normalization path now validates that each equity frame contains exactly one currency
  - mixed-currency frames now fail fast with a clear `ValueError`
  - added a regression test for this case

### P2. Rows without a usable return basis could still be marked `OK`
- Files: `golden_vector/normalize/prices_usd.py`
- Why it mattered: Tool A will build returns from the adjusted-close basis. A row with missing `adj_close_local` and missing `close_local` would produce no usable USD return basis, but the first implementation still marked the row `OK` as long as FX existed.
- Fix applied:
  - added `MISSING_RETURN_BASIS` as an explicit normalization status
  - added a regression test covering the missing-basis case

### P2. Market snapshots with zero or negative share prices could still be marked `OK`
- Files: `golden_vector/normalize/market_snapshot.py`
- Why it mattered: Tool B depends on a sensible market snapshot. A zero-price or negative-price row is not usable, but the first implementation only checked FX and shares outstanding before returning `OK`.
- Fix applied:
  - added `INVALID_SHARE_PRICE` as an explicit normalization status
  - added a regression test for invalid share prices

## Result After Fixes

The normalization layer is stricter now in the places that matter most:
- no silent mixed-currency normalization
- no false `OK` status on rows that cannot support return math
- no false `OK` status on invalid Tool B prices

## Residual Risks

- I still could not execute `pytest` in this shell because there is no visible Python launcher here.
- The FX alignment rule currently forward-fills with no explicit staleness threshold. That matches the current plan, but Claude should still check whether a stale-FX safeguard belongs in normalization or later QA.
- The normalization layer is not wired into persisted pipeline outputs yet, so the next implementation step still needs integration work.

## Verdict

No new open blocking findings remain from my static review of the normalization slice. It is reasonable to hand this to Claude for an independent review before wiring it into the pipeline.
