# Option Trading UI Completion Report

## Status

Complete through Checkpoint D.

## What Shipped

- Native `/option-trading` workspace tab built from structured option-trading data, not markdown.
- `/ticker/<T>?lens=option-trading` detail panel with downside puts, upside calls, and the GET-only sizing calculator.
- `/hedge-readiness` redirects to `/option-trading`; `/hedge-readiness/latest.md` remains the raw markdown download.
- Candidate model generalized from `CandidatePut` to backwards-compatible `OptionCandidate`.
- Call candidates and call scenarios use `up_beta_core`; put scenarios continue to use `down_beta_core`.
- Sizing calculator supports:
  - `size_mode=contracts&quantity=N`
  - `size_mode=budget&budget=...`
  - safe fallback notes for invalid side, horizon, quantity, or budget
  - no persistence or file mutation
- Risk-free-rate fallback is now disclosed in both overview and detail UI.
- Detail window switcher preserves `lens=option-trading#option-trading`.

## Review Fixes Applied First

- M1: detail data now reuses the cached overview row instead of rebuilding the full overview for one ticker.
- M2: risk-free-rate `0%` fallback is threaded through data shapes and rendered visibly.
- Low test gaps closed where cheap:
  - malformed manifest
  - invalid detail lens fallback
  - overview/detail P&L consistency
  - fallback-rate disclosure

## Checks

- Focused route/data checks after calculator: `42 passed`.
- Full suite after step 5: `540 passed`.
- Full suite after step 6: `542 passed`.
- Full suite after step 7: `546 passed`.
- Full suite after step 8: `546 passed`.
- Browser verification on fresh server `127.0.0.1:8766`:
  - `/option-trading` loaded with 22 rows and call P&L context column.
  - `/ticker/AEM?lens=option-trading&side=call&horizon=60&size_mode=contracts&quantity=3#option-trading` loaded with active Option Trading nav, put/call sections, and calculator.
  - `/ticker/AEM?lens=option-trading&side=put&horizon=60&size_mode=budget&budget=5000#option-trading` loaded and showed contracts plus leftover cash.
  - current page console: 0 warnings/errors.

Could not run:

- `python -m ruff --version` failed: `No module named ruff`.
- `python -m mypy --version` failed: `No module named mypy`.
- No `pyproject.toml`, `.ruff.toml`, `mypy.ini`, or `pyrightconfig.json` is present.

## Final Notes

- No custom frontend financial math was added; JavaScript remains DataTables/display behavior.
- The calculator is GET-only and recomputes in Python from cached per-contract bundles.
- Budget mode means premium spend, not portfolio exposure hedging.
- Calls are labelled as bullish-gold speculation, not a hedge.
- Existing unrelated workspace noise remains untouched.
