# M1.5 Put Scenarios Progress

Baseline: last clean full suite before M1.5 implementation was `python -m pytest -q` -> 391 passed in 84.11s. A fresh baseline rerun at session start timed out after 304s before producing a pass/fail summary.

Step 1 (Black-Scholes put price): committed pending. Tests: 400 passed in 298.26s. Notes: Added European put pricing with spot-zero limit, parity/reference tests, and degenerate-input coverage.
