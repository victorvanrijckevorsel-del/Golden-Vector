# Codex Review: Phase 4 Reliability Hardening

Date: 2026-04-22

## Scope

Review of the reliability hardening pass after the Tool B manual-data redesign:
- FX staleness controls in normalization
- market-snapshot parsing robustness
- JSON artifact/output sanitization for manual-data inspection commands

## Findings Fixed During Review

### 1. FX freshness was still too permissive
- Issue: normalization could silently reuse old FX rates forever through backward as-of matching.
- Risk: historical rows could look valid even when the FX rate was stale enough to be misleading.
- Fix:
  - added `max_fx_staleness_days` and `block_on_stale_fx` to [qa.yaml](C:/Users/Emanuel/code/Golden-Vector/config/qa.yaml)
  - carried `fx_staleness_days` into normalized equity and market-snapshot outputs
  - introduced `STALE_FX` as an explicit normalization status
  - made normalization QA warn or fail based on config

### 2. Market-snapshot parsing was too brittle
- Issue: snapshot standardization still relied on direct `float(last_row["Close"])` style assumptions.
- Risk: malformed or partial Yahoo payloads could fail with noisy low-level errors instead of clear data-quality failures.
- Fix:
  - added explicit snapshot-date extraction
  - added layered price fallback using recent history and fast-info keys
  - rejected invalid or non-positive share prices with clear errors

### 3. Manual-data inspection still emitted ugly JSON
- Issue: store-backed inspect commands had started surfacing Python/Pandas missing-value behavior (`NaN`) in user-facing JSON.
- Risk: confusing output and inconsistent audit artifacts.
- Fix:
  - introduced centralized JSON sanitization in [run_context.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app/run_context.py)
  - made CLI JSON printing use the same sanitizer
  - confirmed live `manual-data show --ticker NEM` now emits `null` instead of `NaN`

## Verification

- Focused normalization/snapshot tests: passed
- Full suite: **140 passed**
- Live smoke:
  - `manual-data import-csv`
  - `manual-data show --ticker NEM`
  - `update-data`
  - `tool-b --gold-price 4000`

## Final Verdict

No open blockers remain in this hardening slice.

The code is now materially safer in three ways:
- stale FX is visible and configurable instead of silent
- fragile Yahoo snapshot payloads fail more cleanly
- manual-data inspection outputs are now clean enough to trust as operator-facing artifacts
