# M1.5 Put Scenarios Progress

Baseline: last clean full suite before M1.5 implementation was `python -m pytest -q` -> 391 passed in 84.11s. A fresh baseline rerun at session start timed out after 304s before producing a pass/fail summary.

Step 1 (Black-Scholes put price): committed 3ba8a52. Tests: 400 passed in 298.26s. Notes: Added European put pricing with spot-zero limit, parity/reference tests, and degenerate-input coverage.

Step 2 (hedge-readiness scenario config): committed a2b1931. Tests: 406 passed in 241.52s. Notes: Added scenario quantity, scenario ladder, speculation ticker cap, and optionability-tier minimum config with schema validation.

Step 3 (scenario math): committed 9ee0ddc. Tests: 414 passed in 153.33s. Notes: Added put P&L scenario rows, breakeven handling, low-down-beta skips, and stock-price clamp coverage.

Step 4 (comparison table): committed eb50582. Tests: 421 passed in 146.97s. Notes: Added cross-ticker comparison rows, sortable columns, missing-value handling, and skipped-bundle filtering.

Step 5 (header context): committed 6954ba1. Tests: 426 passed in 151.47s. Notes: Added manifest-based gold/GDX context, implied-vs-modeled heuristic labels, and graceful missing-data notes.

Step 6 (speculation section): committed b8020e6. Tests: 434 passed in 148.84s. Notes: Added holdings-independent universe blocks, optionability filtering, cheap-IV sorting, quantity/max-ticker overrides, and per-block annotations. Static check note: `python -m ruff check ...` could not run because ruff is not installed in this environment.

Checkpoint A self-review fixes: committed in this step. Tests: 438 passed in 150.85s. Notes: Treated negative Tool A down-beta as zero modeled downside instead of unavailable data, made header context degrade on malformed manifests and corrupt history files, and added a risk-free-rate annotation for speculation candidate selection.

Put/call holistic review fixes: committed in this step. Tests: 446 passed in 194.21s. Notes: Added configurable candidate quote-quality and IV sanity gates, applied them to options features and candidate put selection, kept speculation sorting cheap-IV-only by removing the unused comparison sort hook, and aligned scenario pricing day-count with the shared Black-Scholes constant. Static check note: `ruff`, `mypy`, and `pyright` are not installed in this environment.
