# Claude Review Request: Full Option Trading UI + Put/Call Workflow

## Role

You are reviewing Codex's full Option Trading UI milestone as a senior engineer.

This is a READ-ONLY review request.

Do not modify code. Do not create commits. Do not apply fixes yourself. Write a thorough review document only.

You may inspect files, inspect diffs, and run read-only checks/tests if useful. If you run checks, report the exact commands and results. If a check cannot run, explain why.

## Output

Write your findings to:

`reviews/codex/claude_review_codex_option_trading_ui_full.md`

Use the usual review format:

- Grade: READY / READY WITH MINOR CHANGES / NEEDS CHANGES
- Findings first, ordered by severity
- Each finding should include concrete file:line references where possible
- Include open questions or assumptions
- Include a short summary of what was reviewed
- Do not rewrite the implementation plan
- Do not implement fixes

## Context

Golden Vector is a local-first Python gold-stock screening workspace. The new work exposes the Hedge Readiness / M1.5 options workflow inside the local WSGI UI.

The product goal is practical: Emanuel should be able to open the local workspace, click **Option Trading**, see optionable gold stocks, and drill into a ticker to compare downside puts, upside calls, and sizing scenarios without reading the raw markdown report.

This is not meant to be a brokerage interface or a recommendation engine. It is a local decision-support screen built from already persisted options data, Tool A beta data, and Tool B context.

## Commit Range To Review

Review the full Codex Option Trading UI range:

`ba41896^..0377cef`

Useful command:

```bash
git diff ba41896^..0377cef
```

Recent relevant commits:

- `ba41896` option-trading step 1: add structured data cache
- `a87a505` option-trading step 2: add workspace tab
- `d5d1a9f` option-trading batch 1 self-review fixes
- `a3fef6d` option-trading review fixes stale feature guard
- `bd01fbf` option-trading step 3: add ticker detail panel
- `e668183` option-trading step 4: retire hedge markdown page
- `041ea50` option-trading batch 2 self-review
- `d4f4f0a` option-trading review fixes detail lens switcher
- `84fb395` option-trading review fix cached detail row
- `de8090c` option-trading review fix risk-free disclosure
- `e7da0cd` option-trading step 5: generalize option candidates
- `ac0bc1e` option-trading step 6: add upside call context
- `a6d9eba` option-trading batch 3 self-review
- `b21fac9` option-trading step 7: add sizing calculator
- `8143728` option-trading step 8: polish calculator UI docs
- `80ad55f` option-trading checkpoint d completion report
- `0377cef` option-trading post-completion review fixes

## Main Files In Scope

Primary implementation files:

- `golden_vector/hedge/candidate_puts.py`
- `golden_vector/hedge/option_trading.py`
- `golden_vector/hedge/scenarios.py`
- `golden_vector/serve/option_trading_data.py`
- `golden_vector/serve/overview_option_trading.py`
- `golden_vector/serve/detail_page.py`
- `golden_vector/serve/detail_panels.py`
- `golden_vector/serve/http_helpers.py`
- `golden_vector/serve/page_shell.py`
- `golden_vector/serve/workspace.py`
- `golden_vector/serve/static/workspace.css`
- `docs/hedge_readiness.md`

Primary test files:

- `tests/test_option_trading_data.py`
- `tests/test_option_trading_overview.py`
- `tests/test_option_trading_routes.py`
- `tests/test_hedge_modules.py`
- `tests/test_scenarios.py`
- `tests/test_strategy_generic_math.py`
- related existing workspace tests if touched by route/detail behavior

Progress/completion docs:

- `reviews/codex/codex_option_trading_progress.md`
- `reviews/codex/codex_option_trading_completion_report.md`

## What Codex Built

1. Added a structured Option Trading data/cache layer at `serve/option_trading_data.py`.

2. Added a workspace tab at:

   `/option-trading`

   This renders a DataTable of optionable tickers from structured data, not markdown parsing.

3. Added ticker detail support at:

   `/ticker/<TICKER>?lens=option-trading#option-trading`

   This keeps the normal ticker detail page but marks the Option Trading nav active and anchors the user to the new panel.

4. Retired the old rendered Hedge Readiness markdown page:

   - `/hedge-readiness` redirects to `/option-trading`
   - `/hedge-readiness/latest.md` remains a raw markdown download

5. Generalized the put-only action layer:

   - `CandidatePut` is now a backward-compatible alias of `OptionCandidate`
   - `build_candidate_grid(option_type="P" | "C")` supports puts and calls
   - `build_candidate_put_grid(...)` remains for the shipped CLI report
   - Scenario beta naming moved toward `gold_beta`, with backward-compatible aliases for put-only callers

6. Added call-side context:

   - Calls use `up_beta_core`
   - Gold scenarios are 0%, +5%, +10%, +15%, +20%
   - UI labels calls as bullish-gold speculation, not hedging

7. Added a GET-only sizing calculator on ticker detail pages:

   - Side: put or call
   - Horizon: available candidate horizon
   - Size mode: fixed contract count or premium budget
   - Budget mode buys `floor(budget / (mid * 100))` standard contracts and shows leftover cash
   - No writes or saved trades

8. Fixed post-review issues already caught by Codex:

   - Detail window switcher preserves `lens=option-trading#option-trading`
   - Detail builder reuses the cached overview row
   - Missing risk-free rate is disclosed as a 0% fallback
   - Stale options feature rows whose `run_id` does not match the latest manifest are ignored
   - Skipped sizing scenarios now render the skip reason instead of an empty table
   - Calculator radio CSS no longer depends on `:has()`

## Checks Codex Reported Passing

Most recent checks after the final post-completion fix:

```bash
python -m pytest tests/test_option_trading_data.py tests/test_option_trading_routes.py tests/test_option_trading_overview.py tests/test_hedge_modules.py tests/test_scenarios.py tests/test_strategy_generic_math.py -q
```

Result: `55 passed`

```bash
python -m pytest -q
```

Result: `548 passed`

```bash
git diff --check
```

Result: passed, with only CRLF warnings.

```bash
python main.py hedge-readiness
```

Result: passed. It wrote a fresh markdown report and printed a context-alignment warning because local Tool A/B outputs do not match the latest options source run.

Codex could not run `ruff` or `mypy` because neither is installed and the repo has no config for them.

Browser verification on `http://127.0.0.1:8766`:

- `/option-trading` loads with Option Trading active nav and table rows.
- `/ticker/AEM?lens=option-trading&side=call&horizon=60&size_mode=contracts&quantity=3#option-trading` loads with put/call sections and calculator.
- `/ticker/AEM?lens=option-trading&side=put&horizon=60&size_mode=budget&budget=5000#option-trading` loads with budget sizing and leftover cash.
- `/ticker/CG?lens=option-trading&side=call&horizon=90&size_mode=contracts&quantity=3#option-trading` shows the skipped up-beta reason and no empty sizing table.
- Browser console had no warnings/errors on the checked page.

## Review Priorities

Please be very thorough. Review as if this were about to ship.

Focus especially on:

1. Architecture and boundaries
   - Is `hedge.option_trading` the right place for UI-facing structured option rows?
   - Is `serve.option_trading_data` a clean cache/data-loading boundary?
   - Is the workspace route layer still thin enough?
   - Did the put-to-option generalization create a clean base for future call/put strategy additions?

2. Data correctness and stale-data safety
   - Is the composite cache key sufficient: options manifest refresh id + Tool A/B snapshot refresh ids?
   - Does stale feature-row filtering fail closed enough?
   - Is legacy feature fallback without `run_id` acceptable, or too permissive?
   - Are missing/malformed manifests, missing parquet files, and partial chains handled honestly?
   - Does the UI ever mix options data and Tool A/B betas in a misleading way?

3. Financial/model correctness
   - Puts use `down_beta_core`; calls use `up_beta_core`.
   - Long puts and long calls are priced through the shared scenario engine.
   - Scenario result tables show both mark-to-market "now" P&L and expiry P&L.
   - Budget sizing uses mid premium times 100 shares per contract.
   - Low-beta skips should prevent fake scenarios.
   - Review whether call selection around +0.25 delta is practical and consistently implemented.

4. UI and user value
   - Is `/option-trading` obvious enough for Emanuel to find and use?
   - Are labels understandable for a non-expert user?
   - Is the overview table too dense, or does it show the right decision information?
   - Does the detail page make put vs call roles clear enough?
   - Are empty/thin/skipped states clear without sounding like errors?
   - Does redirecting `/hedge-readiness` to `/option-trading` preserve enough legacy behavior?

5. Query parsing and routing
   - Invalid lens falls back correctly.
   - Invalid calculator inputs fall back with visible notes.
   - GET-only calculator does not mutate files.
   - URLs/anchors/window switcher preserve the option-trading context.
   - Escaping is correct for ticker, query, text, and HTML attributes.

6. Tests and maintainability
   - Are tests behavior-focused rather than brittle HTML snapshots?
   - Are there missing tests for malformed data, bad chains, missing Tool A fields, low-beta scenarios, URL escaping, or stale caches?
   - Any unused imports, dead code, duplicated logic, or naming drift between Hedge Readiness, Option Trading, puts, calls, and speculation?
   - Any parts that should be simpler before this becomes the pattern for future tools?

## Specific Things To Pry At

Please challenge these areas directly:

1. `golden_vector/hedge/candidate_puts.py`
   - The module name remains put-shaped even though it now exports `OptionCandidate` and call grids. Is the backward-compatible naming acceptable for now, or should this be renamed later?
   - Does `CandidatePut = OptionCandidate` preserve enough compatibility without hiding call/put mistakes?

2. `golden_vector/hedge/scenarios.py`
   - Are the generic strategy abstractions clean, or did they make the simple put workflow harder to reason about?
   - Does the skip logic handle low or negative up-beta/down-beta correctly for both sides?

3. `golden_vector/hedge/option_trading.py`
   - Is this builder layer too UI-specific for `hedge/`?
   - Is `OptionTradingRow` the right contract between model/data loading and rendering?
   - Should sizing be part of this module or closer to `serve/`?

4. `golden_vector/serve/option_trading_data.py`
   - Does cache invalidation behave correctly across options refreshes and Tool A/B refreshes?
   - Does it load only the data needed for this UI?
   - Does it fail closed enough when input snapshots are inconsistent?

5. `golden_vector/serve/detail_panels.py`
   - Is the Option Trading panel too long for the existing ticker detail page?
   - Is the calculator form simple enough?
   - Are hidden assumptions like 100-share contract multiplier visible enough to the user?

6. `golden_vector/serve/overview_option_trading.py`
   - Does sorting primarily by downside beta still make sense now that calls are also visible?
   - Are call columns clearly "context" rather than ranking basis?

7. `golden_vector/serve/workspace.py`
   - Did adding option data loading to every ticker detail render create any performance or failure-mode problem?
   - Should option-trading detail data be loaded only when `lens=option-trading`, or is always loading it acceptable because the panel is always present?

## Known Workspace Noise

At the time this request was written, the working tree had unrelated existing noise:

- Modified but not part of this review request:
  - `tests/test_workspace_app.py`
- Many untracked planning/review/data files, including `.claude/`, roadmap/review markdown files, local spreadsheet/PDF artifacts, and `data/manual/holdings/`.

Do not treat unrelated pre-existing workspace noise as Codex option-trading changes unless it directly affects reviewed behavior.

## Desired Outcome

Tell Emanuel whether the full Option Trading UI milestone is ready to keep, needs small fixes, or needs structural changes before more options tooling is built on top.

Be direct. If this is too complex, not decision-useful enough, weakly tested, or likely to make future put/call tools harder to extend, say so clearly.
