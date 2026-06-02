# Codex M1.5 v6 Progress

- 2026-06-02 16:28:40 +01:00 — Pre-flight baseline on `dev-vic`: `python -m pytest -q` passed with 457 tests. Step-0 diff reviewed: exactly the expected 10 M1 punch-list files for H1/H2/H3/M4 plus tests.
- 2026-06-02 — Step 1: added `black_scholes_call_price()` plus call-price, spot-zero, degenerate-input, and 5-case put-call parity coverage. Focused `tests/test_black_scholes.py -q`: 33 passed. Full `python -m pytest -q`: 467 passed.
