# Merged Review Decision: Option Trading UI

Inputs reviewed:

- Claude review: `reviews/codex/claude_review_codex_option_trading_ui_full.md`
- Codex self-review: `reviews/codex/codex_self_review_option_trading_ui_full.md`

Merged grade: READY WITH MINOR CHANGES

## Decision Summary

The milestone is structurally sound and worth keeping. Claude and Codex both found the financial math, candidate generalization, cache shape, GET-only sizing calculator, stale-data guard, and tests to be strong enough to build on.

The changes I would make are small and targeted. I would not rewrite the architecture, rename modules now, or expand scope into spreads/Greeks/decision triggers.

## Changes To Make Now

### 1. Avoid option-data cold load on normal ticker pages

Codex found this as the only meaningful operational issue. `GET /ticker/<T>` currently loads and builds the full option-trading data path even when the user did not ask for `lens=option-trading`. Claude also noted first-request latency from building put and call grids.

Decision: fix now.

Preferred behavior:

- `/ticker/<T>` should stay fast and focused on the normal combined detail page.
- `/ticker/<T>?lens=option-trading#option-trading` should load the full Option Trading panel.
- If the normal detail page still mentions options, it should be a lightweight link to the option lens, not a full data build.

### 2. Strengthen the option-pricing assumption labels

Codex found that the UI labels `Value Now`, `P&L/share Now`, and `Net P&L Now` without clearly saying this is an instant Black-Scholes reprice using unchanged days-to-expiry and constant IV.

Decision: fix now.

Add concise visible copy near both the scenario tables and sizing calculator. The wording should be plain English: this is model output, not a live quote.

### 3. Remove noisy quantity validation in valid budget mode

Codex found that budget mode can still report an invalid quantity note even though quantity does not drive budget sizing.

Decision: fix now.

Validate quantity only when contracts mode is active, or suppress the quantity note when budget mode is valid.

### 4. Clarify call universe wording

Codex found that call discovery is still gated by Hedge Readiness optionability, which is put/downside-shaped. Claude judged this acceptable because calls are context, not ranking basis.

Decision: do a copy-only clarification now, not a data-model change.

The UI should say this is the Hedge Readiness optionable subset with call context where usable. Do not add side-specific optionability in this pass.

## Changes To Defer

### 1. Rename `candidate_puts.py`

Claude and Codex both agree the module name is now misleading, but renaming it would add churn and compatibility work.

Decision: defer.

Queue a later cleanup to move generic exports to `option_candidates.py` with a compatibility shim.

### 2. Split put/call beta thresholds

Claude noted that `down_beta_min_for_scenario` gates call up-beta too. The behavior is correct today, but the name is not ideal.

Decision: defer.

Keep the shared 0.10 sensitivity floor for now. Rename or split the config only if future call workflows need different threshold behavior.

### 3. Remove `raw_options_by_ticker` from the option-trading cache

Codex found this field is currently unused in the workspace option-trading path.

Decision: defer unless touched nearby.

It is minor memory/contract noise, not a user-facing issue.

### 4. Zero-contract budget table behavior

Codex raised whether budget mode should show a scenario table when the budget buys zero contracts.

Decision: defer unless it looks bad in browser after the other calculator cleanup.

The existing visible note is acceptable for now.

## Checks Already Run

Codex:

- `python -m pytest tests/test_option_trading_data.py tests/test_option_trading_routes.py tests/test_option_trading_overview.py tests/test_hedge_modules.py tests/test_scenarios.py tests/test_strategy_generic_math.py -q` -> `55 passed`
- `python -m pytest -q` -> `548 passed`
- `git diff --check` -> passed, only existing CRLF warning
- `python -m ruff --version` -> unavailable
- `python -m mypy --version` -> unavailable

Claude:

- In-scope option suite -> `55 passed`
- Confirmed full suite result from Codex

## Implementation Rule

When coding resumes, keep the fix set narrow:

1. Route/detail loading gate.
2. Copy/assumption labels.
3. Budget quantity parser cleanup.
4. Tests for the route gate and parser cleanup.

Do not broaden into module renames, new abstractions, side-specific optionability, or additional trading strategies in this pass.
