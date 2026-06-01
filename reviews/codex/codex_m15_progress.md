# M1.5 Put Scenarios Progress

Baseline: last clean full suite before M1.5 implementation was `python -m pytest -q` -> 391 passed in 84.11s. A fresh baseline rerun at session start timed out after 304s before producing a pass/fail summary.

Step 1 (Black-Scholes put price): committed 3ba8a52. Tests: 400 passed in 298.26s. Notes: Added European put pricing with spot-zero limit, parity/reference tests, and degenerate-input coverage.

Step 2 (hedge-readiness scenario config): committed a2b1931. Tests: 406 passed in 241.52s. Notes: Added scenario quantity, scenario ladder, speculation ticker cap, and optionability-tier minimum config with schema validation.

Step 3 (scenario math): committed 9ee0ddc. Tests: 414 passed in 153.33s. Notes: Added put P&L scenario rows, breakeven handling, low-down-beta skips, and stock-price clamp coverage.

Step 4 (comparison table): committed in this step. Tests: 421 passed in 146.97s. Notes: Added cross-ticker comparison rows, sortable columns, missing-value handling, and skipped-bundle filtering.
