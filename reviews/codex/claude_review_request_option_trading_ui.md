# Claude Review Request: Option Trading UI Milestone

## Role

You are reviewing Codex's Option Trading UI milestone as a senior engineer.

This is a READ-ONLY review request.

Do not modify code. Do not create commits. Do not apply fixes yourself. Write a thorough review document only.

You may inspect files, inspect diffs, and run read-only checks/tests if useful. If you run checks, report the exact commands and results. If a check cannot run, explain why.

## Output

Write your findings to:

`reviews/codex/claude_review_codex_option_trading_ui.md`

Use the usual review format:

- Grade: READY / READY WITH MINOR CHANGES / NEEDS CHANGES
- Findings first, ordered by severity
- Each finding should include concrete file:line references where possible
- Include open questions or assumptions
- Include a short summary of what was reviewed
- Do not rewrite the implementation plan
- Do not implement fixes

## Context

Golden Vector is a local-first Python gold-stock screening workspace. The new work exposes the downside/options workflow inside the local WSGI UI.

This milestone is specifically the Option Trading UI layer built on top of the Hedge Readiness / M1.5 structured data. It is not meant to change the financial math layer except where needed to read structured outputs for display.

The goal is practical user value: Emanuel should be able to open the workspace, click Option Trading, see useful put/call/speculation information, and drill into ticker detail pages without reading raw markdown reports.

## Commit Range To Review

Review the full option-trading UI range:

`ba41896^..d4f4f0a`

Recent commits:

- `ba41896` option-trading step 1: add structured data cache
- `a87a505` option-trading step 2: add workspace tab
- `d5d1a9f` option-trading batch 1 self-review fixes
- `a3fef6d` option-trading review fixes stale feature guard
- `bd01fbf` option-trading step 3: add ticker detail panel
- `e668183` option-trading step 4: retire hedge markdown page
- `041ea50` option-trading batch 2 self-review
- `d4f4f0a` option-trading review fixes detail lens switcher

Useful command:

```bash
git diff ba41896^..d4f4f0a
```

## Main Files In Scope

Primary implementation files:

- `golden_vector/hedge/option_trading.py`
- `golden_vector/serve/option_trading_data.py`
- `golden_vector/serve/overview_option_trading.py`
- `golden_vector/serve/detail_page.py`
- `golden_vector/serve/detail_panels.py`
- `golden_vector/serve/http_helpers.py`
- `golden_vector/serve/page_shell.py`
- `golden_vector/serve/workspace.py`

Primary test files:

- `tests/test_option_trading_data.py`
- `tests/test_option_trading_overview.py`
- `tests/test_option_trading_routes.py`

Progress log:

- `reviews/codex/codex_option_trading_progress.md`

## What Codex Built

1. Added a structured Option Trading cache layer that reads the latest Hedge Readiness / M1.5 structured outputs for the workspace UI.

2. Added a new workspace navigation tab: `/option-trading`.

3. Added an Option Trading ticker detail lens:

   `/ticker/<T>?lens=option-trading`

   This renders an anchored ticker-specific Option Trading panel inside the existing ticker detail page.

4. Retired the old rendered Hedge Readiness markdown page:

   - `/hedge-readiness` redirects to `/option-trading`
   - `/hedge-readiness/latest.md` remains available as the raw markdown download

5. Fixed a post-review detail-page bug where the `6M / 12M / 3Y` switcher dropped `lens=option-trading` and `#option-trading`.

## Checks Codex Reported Passing

- `python -m pytest tests/test_option_trading_routes.py tests/test_workspace_horizon_switcher.py -q`
  - `26 passed`
- `python -m pytest -q`
  - `533 passed`
- `python -m py_compile ...`
  - passed for changed Python files
- `git diff --check`
  - passed, with only CRLF warnings
- Browser verification:
  - `/option-trading`
  - `/ticker/AEM?lens=option-trading`
  - `/ticker/AEM?window=6m&lens=option-trading#option-trading`
  - no browser warnings/errors reported

Codex could not run `ruff` or `mypy` because they are not installed/configured in this repo.

## Review Priorities

Please be very thorough. Review as if this were about to ship.

Focus especially on:

1. Architecture and separation of concerns
   - Is the structured cache layer the right boundary?
   - Does route logic leak into data loading?
   - Does display code know too much about report/schema internals?
   - Is this easy to extend for future Tool C / Tool D / put-call workflow additions?

2. Data correctness and stale-data behavior
   - Does the cache pick the right latest outputs?
   - Are missing, stale, malformed, or partial structured files handled safely?
   - Are empty states honest and useful?
   - Is the stale feature guard correct, or can stale option data appear valid?

3. UI behavior and routing
   - Does `/option-trading` fit cleanly into existing workspace navigation?
   - Does `/ticker/<T>?lens=option-trading` preserve the user's context correctly?
   - Are query parameters, anchors, escaping, and redirects robust?
   - Is retiring `/hedge-readiness` to a redirect the right compatibility move?

4. Practical user value
   - Is the Option Trading tab decision-useful for Emanuel?
   - Does it surface the right put/call/speculation information, or is it still too much infrastructure exposed as UI?
   - Are the labels, table columns, and empty states understandable to a non-expert user?

5. Tests
   - Are the tests checking behavior rather than implementation details?
   - Are there missing tests for malformed structured data, stale data, redirects, ticker lens fallback, or URL escaping?
   - Are there brittle assertions that will block future UI improvements?

6. Maintainability
   - Any duplicated code that should be consolidated now?
   - Any dead code or unused imports?
   - Any overly broad helper APIs?
   - Any inconsistent naming between hedge readiness, option trading, put scenarios, calls, and speculation candidates?

## Specific Things To Pry At

Please specifically challenge these:

1. `golden_vector/hedge/option_trading.py`
   - Is this correctly placed under `hedge`, or should it live closer to report/scenario generation?
   - Are strategy names and schema fields clear enough for future calls/puts/portfolio sections?

2. `golden_vector/serve/option_trading_data.py`
   - Does the cache invalidation behavior make sense?
   - Is the stale detection strict enough?
   - Does it fail closed when data is missing or inconsistent?

3. `golden_vector/serve/overview_option_trading.py`
   - Is this mostly presentation, or is it doing data normalization/ranking that belongs elsewhere?
   - Does it create a useful first screen, or should the ordering/summary cards change?

4. `golden_vector/serve/detail_panels.py`
   - Is the new Option Trading detail panel too coupled to the existing structural sensitivity page?
   - Did the lens/window switcher fix create any regressions for normal combined detail pages?

5. `golden_vector/serve/workspace.py`
   - Are the new routes integrated cleanly?
   - Does the `/hedge-readiness` redirect preserve enough legacy behavior?

## Known Workspace Noise

At the time this request was written, the working tree had unrelated existing noise:

- Modified but not part of this milestone:
  - `golden_vector/serve/static/workspace.css`
  - `tests/test_workspace_app.py`
- Many untracked planning/review/data files

Do not treat unrelated pre-existing workspace noise as Codex option-trading changes unless it directly affects the reviewed code.

## Desired Outcome

The review should tell Emanuel whether this UI milestone is genuinely ready, or whether Codex should fix issues before continuing.

Please be direct. If the feature is conceptually overbuilt, under-tested, too hard to extend, or not useful enough for the intended decision workflow, say so clearly.
