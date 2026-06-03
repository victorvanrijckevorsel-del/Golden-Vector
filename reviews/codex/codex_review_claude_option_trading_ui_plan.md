Grade: NEEDS CHANGES

## Summary

The product direction is right: the option work should become a native workspace surface, not a markdown file in a browser box. The plan also makes the right high-level calls on structured data, ticker-level drilldown, and keeping Python as the source of truth for option math.

I would not start implementation yet. The plan still leaves core data and UX decisions open while asking for a fairly complex UI: cached structured option data, a new optionable overview, a ticker detail panel, call-side candidate selection, and an interactive sizing calculator. The biggest risk is not syntax or math; it is that implementation will invent the missing product contracts on the fly.

## Scope Reviewed

- Plan: `reviews/codex/claude_option_trading_ui_plan.md`
- Relevant current code paths: `golden_vector/hedge/candidate_puts.py`, `golden_vector/hedge/scenarios.py`, `golden_vector/hedge/report.py`, `golden_vector/features/options.py`, `golden_vector/serve/workspace_state.py`, `golden_vector/serve/detail_page.py`
- Local data sanity check: latest options features show 60 rows, 22 optionable rows, 21 directly hedgeable, 1 thin.
- No tests were run for this plan review, and no source code was changed.

## Findings

### 1. P1 - The live-compute/cache contract is too vague and currently keyed too narrowly

The plan recommends live computation with a per-process cache keyed on the options manifest `refresh_run_id` (`reviews/codex/claude_option_trading_ui_plan.md:92-96`) and calls that cache "load-bearing" (`reviews/codex/claude_option_trading_ui_plan.md:158-159`). That is not specific enough to implement safely. The UI rows combine options features, raw chains, Tool A betas, and Tool B context; `build_hedge_readiness_sections()` currently loads all report data and builds put-only candidate grids (`golden_vector/hedge/report.py:243`, `golden_vector/hedge/report.py:276`, `golden_vector/hedge/report.py:1064-1107`). A cache keyed only on the options refresh can go stale when Tool A/B outputs change, and calling the full report builder from the workspace would compute portfolio, proxy, speculation, and comparison sections the UI does not need. Define a dedicated option-trading data loader/cache before implementation: exact module, cache key, invalidation inputs, missing-manifest behavior, and whether it builds overview rows, per-ticker details, or both.

### 2. P1 - The call side needs a generic option candidate model, not just `build_candidate_call_grid`

The plan says to add `build_candidate_call_grid` symmetrically to the put grid (`reviews/codex/claude_option_trading_ui_plan.md:82-84`), but the current action layer is typed around puts: `CandidatePut` lives in `candidate_puts.py` (`golden_vector/hedge/candidate_puts.py:22`), candidate selection filters `option_type == "P"` (`golden_vector/hedge/candidate_puts.py:67`), and `CandidateScenarioBundle.candidate` is also a `CandidatePut` (`golden_vector/hedge/scenarios.py:46-53`). The plan notices the misleading `down_beta_core` parameter name, but it does not fully address the model shape: candidate type, module name, scenario field names (`down_beta_used`), skip messages, and breakeven behavior are all put/downside-shaped. Before coding calls, specify whether this becomes `OptionCandidate` with `option_type`, or separate `CandidatePut` / `CandidateCall` classes behind a shared protocol. Without that, the code will technically support calls while reading like puts everywhere.

### 3. P1 - OD-1 is not deferrable; it determines the first tab

The plan marks optionable strictness as an open decision (`reviews/codex/claude_option_trading_ui_plan.md:66`, `reviews/codex/claude_option_trading_ui_plan.md:164`), but Phase P0 already builds the optionable list (`reviews/codex/claude_option_trading_ui_plan.md:134`) and acceptance requires that list to show only optionable tickers (`reviews/codex/claude_option_trading_ui_plan.md:143`). Current `optionability_tier` is put-driven: directly hedgeable requires all target put IVs, not both put and call candidates (`golden_vector/features/options.py:214-225`). In latest local data, there are 22 optionable rows, and the one thin row has a 60d call IV but no 60d put IV. Decide before P0 whether the tab means "has any listed options," "has usable put candidate," "has usable call candidate," or "has both," and make empty-side statuses explicit in the row model.

### 4. P1 - The interactive sizing form is under-specified and may be the wrong HTTP shape

The plan proposes `POST /ticker/<T>/option` for a compute-only form with both quantity and dollar amount inputs (`reviews/codex/claude_option_trading_ui_plan.md:88-89`). Existing ticker POST routes mutate manual data and redirect; this form does not save anything. The plan needs to define precedence if both quantity and dollars are entered, validation for zero/negative/non-numeric inputs, how dollar sizing maps to contracts for puts vs calls, which candidate/horizon is selected, and how the recomputed state survives refresh/back navigation. A GET query on `/ticker/<T>?option_strategy=...&quantity=...` may be a cleaner fit because this is a calculator, not a write. If POST stays, specify direct render vs redirect and add no-mutation tests.

### 5. P2 - Detail navigation and active UI state are not designed yet

The plan says clicking a row opens the existing `/ticker/<T>` page and appends an Option Trading panel (`reviews/codex/claude_option_trading_ui_plan.md:22`, `reviews/codex/claude_option_trading_ui_plan.md:75`, `reviews/codex/claude_option_trading_ui_plan.md:145`). Today the ticker detail page returns with `active_nav="combined"` (`golden_vector/serve/detail_page.py:78`), and the current detail lens is effectively Tool-A-only. If a user clicks from the Option Trading tab, they should land on the option panel, not hunt for it below Tool A/B/forms. The plan should define the URL and behavior: for example `/ticker/NEM?lens=option-trading#option-trading`, the active nav state, whether the panel is always visible or lens-selected, and how invalid lens/query inputs fall back.

### 6. P2 - Markdown-page retirement is inconsistent with the proposed nav

The plan correctly says the regex markdown renderer should be retired as the primary surface (`reviews/codex/claude_option_trading_ui_plan.md:26-31`), but the mock nav still shows both `Option Trading` and `Hedge Report` (`reviews/codex/claude_option_trading_ui_plan.md:106`). The route inventory also lists `/hedge-readiness` (`reviews/codex/claude_option_trading_ui_plan.md:36`), and risk #4 says to ensure nothing links to the old page or keep it as a raw report link (`reviews/codex/claude_option_trading_ui_plan.md:161`). Pick one. My recommendation: keep `/hedge-readiness` as "Raw Hedge Report" only if it is clearly secondary and tested; otherwise redirect it to `/option-trading` or remove it. This matters because the current user confusion came from not knowing where the put/call tool lives.

### 7. P2 - The screen mixes downside puts and upside calls without a strong enough information design

OD-2 is resolved as "long calls = leveraged bullish bet on gold" (`reviews/codex/claude_option_trading_ui_plan.md:77`, `reviews/codex/claude_option_trading_ui_plan.md:165`), while the default overview sort is downside beta descending (`reviews/codex/claude_option_trading_ui_plan.md:22`, `reviews/codex/claude_option_trading_ui_plan.md:143`). That is coherent for put hedging/speculation, but it is not necessarily a good call-opportunity ranking. A single row with "60d Put @ gold -10%" and "60d Call @ gold +10%" can be useful, but the UI must prevent users from reading the call column as sorted by call attractiveness. Consider two detail subpanels or segmented controls: "Downside puts" and "Upside calls," with the overview default still locked to downside sensitivity but an explicit up-beta context column for calls.

### 8. P2 - The milestone is probably too broad unless it is split by shippable value

The plan includes a new overview, structured data cache, put detail panel, call candidate engine, call scenarios, and an interactive calculator in one v1 (`reviews/codex/claude_option_trading_ui_plan.md:130-140`). That is implementable, but it is exactly the sort of milestone where product decisions get buried in code. I would split it into two reviewable deliveries: v1a = native Option Trading tab + optionable overview + put-side detail from structured data, replacing the markdown page; v1b = call candidate abstraction + call UI + sizing calculator. If you keep one milestone, the plan needs checkpoint-level acceptance criteria and review stops after P0/P1/P2, not only "one commit per step."

## Additional Notes

- The plan is directionally correct to reject markdown re-parsing. That should stay locked.
- The call use case should remain framed as speculation, not hedge protection. The plan says this; the UI must say it at the point of decision, especially near P&L tables.
- The local options data has many usable-looking rows, but also thin/empty-side cases. The UI needs honest row notes rather than hiding those cases silently.
- Do not start from the rushed `serve/hedge_readiness_page.py` approach. If any of that remains, it should be treated as temporary or removed in the same milestone.

## Required Plan Edits Before Implementation

1. Define the option-trading data/cache module, cache key, invalidation inputs, and exact builder outputs.
2. Resolve OD-1 before P0: what qualifies for the tab, and how put/call missing sides display.
3. Replace the put-shaped call plan with an explicit generic candidate model or a clearly typed put/call pair model.
4. Specify the detail URL, active nav/lens behavior, anchor behavior, and invalid-query fallback.
5. Decide the fate of `/hedge-readiness`: raw report, redirect, or removal, with tests.
6. Redesign the compute-only form contract: GET vs POST, validation, quantity vs dollars precedence, sizing math, and no-persistence guarantees.
7. Split v1 into v1a/v1b, or add hard checkpoints and acceptance criteria per phase.
