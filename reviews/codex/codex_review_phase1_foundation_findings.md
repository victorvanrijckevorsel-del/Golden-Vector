# Codex Review: Phase 1 Foundation

Date: 2026-04-22
Scope: `golden_vector/app`, `golden_vector/ingestion`, `golden_vector/qa`, and the related tests/configs for the Phase 1 raw foundation pipeline.
Review mode: read code thoroughly, trace the end-to-end `foundation` path, then patch any real issues immediately.

## Findings

### P1. Missing currency-map coverage was configured but not actually enforced
- Files: `golden_vector/ingestion/registry.py`, `golden_vector/qa/raw_quality.py`, `config/qa.yaml`
- Why it mattered: the config exposed `block_on_missing_currency_map`, but the pipeline had no explicit currency-map check. If the supported-currency list and the FX map ever drifted apart, the registry would fail indirectly or the problem would pass silently until a later phase.
- Fix applied:
  - added an explicit `currency_map_coverage` QA check
  - made the registry skip unmapped FX pairs instead of crashing on a `KeyError`
  - added tests proving the pipeline now reports missing mappings cleanly

### P2. Duplicate-row QA config existed but was ignored
- Files: `golden_vector/qa/raw_quality.py`, `config/qa.yaml`
- Why it mattered: `warn_on_duplicate_rows` was present in config, but duplicate rows always produced warnings anyway. That makes the config misleading and removes operator control over QA verbosity.
- Fix applied:
  - duplicate-row status now respects `warn_on_duplicate_rows`
  - added a test proving duplicates can be detected without forcing a warning when the config disables it

### P2. Market snapshot QA only checked row count, not critical field completeness
- Files: `golden_vector/qa/raw_quality.py`, `golden_vector/ingestion/fetch_market_snapshot.py`, `golden_vector/ingestion/standardize.py`
- Why it mattered: Tool B depends on the shared market snapshot. A row could exist but still be missing `share_price_local` or `shares_outstanding`, and Phase 1 would previously report only coverage, not quality.
- Fix applied:
  - added snapshot-field QA checks for `share_price_local` and `shares_outstanding`
  - kept these as `WARN` rather than `FAIL` so Tool A is not blocked by Tool B market-data incompleteness
  - added a test covering incomplete snapshot fields

### P2. Logging reconfiguration dropped handlers without closing them
- Files: `golden_vector/app/logging.py`
- Why it mattered: repeated CLI runs in the same process can leave file handles open. On Windows that can turn into locked log files or stale handlers.
- Fix applied:
  - existing root handlers are now closed before removal

## Result After Fixes

The main Phase 1 foundation risks I found in the current code path are addressed in this pass.

Areas rechecked after patching:
- foundation command lifecycle
- registry generation
- raw QA gating
- market snapshot handling
- test coverage for the new QA behavior

## Residual Risks

- I could not execute `pytest` or `python main.py foundation` in this shell because there is still no usable Python launcher visible here.
- Yahoo-specific runtime behavior is still unverified in this environment, especially around symbol coverage and the shape of `fast_info`.
- The QA layer still does not validate null numeric values inside equity/FX/gold history rows beyond row counts and duplicates. That is a reasonable next hardening target, but it is not a blocker for starting Phase 2 normalization.

## Verdict

Phase 1 is in better shape now and is good enough to continue building on, with the runtime caveat above still outstanding.
