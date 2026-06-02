# Codex M1.5 v6 Progress

- 2026-06-02 16:28:40 +01:00 — Pre-flight baseline on `dev-vic`: `python -m pytest -q` passed with 457 tests. Step-0 diff reviewed: exactly the expected 10 M1 punch-list files for H1/H2/H3/M4 plus tests.
- 2026-06-02 — Step 1: added `black_scholes_call_price()` plus call-price, spot-zero, degenerate-input, and 5-case put-call parity coverage. Focused `tests/test_black_scholes.py -q`: 33 passed. Full `python -m pytest -q`: 467 passed.
- 2026-06-02 — Step 2: added v6 non-proxy config fields for protection levels, ranking/speculation defaults, and configurable down-beta scenario threshold. Focused `tests/test_config_models.py -q`: 51 passed. Full `python -m pytest -q`: 473 passed.
- 2026-06-02 — Step 3: added `OptionStrategy`, `compute_strategy_pnl`, strategy-aware scenario P&L, and threaded `down_beta_min_for_scenario` into `_skip_reason`. Focused scenario/strategy tests: 19 passed. Full `python -m pytest -q`: 484 passed.
- 2026-06-02 — Batch 1 self-review: reviewed diff from `a37a013..HEAD`; no out-of-scope files, no comparison.py change, options status counting remains after successful try, and `_skip_reason` reads the threshold parameter. Full `python -m pytest -q`: 484 passed. No code fixes needed.
- 2026-06-02 — Step 4: added dependency-light `golden_vector/hedge/_helpers.py` and migrated report/speculation/header/proxy helper calls with no behavioral change. Focused hedge module tests: 24 passed. Full `python -m pytest -q`: 484 passed.
