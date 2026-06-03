Grade: NEEDS CHANGES

## Summary

v4 has the right user-value direction: dropping binary decision triggers is architecturally correct for Emanuel's stated workflow, and the Sensitivity Ranking section is a useful entry point. But the plan is no longer internally tight enough to implement safely. The v2 fixes are mostly still present in acceptance criteria, but several have drifted in module summaries or pseudocode. The v3/v4 additions also create contradictions around call support, CLI sorting, report section integration, and milestone scale.

I would not start implementation from this plan as-is. Clean the inconsistencies below first, then either split the milestone or explicitly choose which expansions stay in M1.5.

## v2 Finding Regression Check

| Finding | v4 status |
|---|---|
| R1 Linear stock + BS combo | Mostly intact. The honesty note is still present at `reviews/codex/claude_m15_put_scenarios_plan.md:619`, and const-IV labeling is required at `reviews/codex/claude_m15_put_scenarios_plan.md:644`. |
| R2 Constant IV explicit | Intact in acceptance at `reviews/codex/claude_m15_put_scenarios_plan.md:865`, but some examples still say only "Current value" without the required label. Fix report examples before implementation. |
| R3 Spot-clamp vs BS spot=0 | Regressed in §3. The black-scholes module summary still shows `if spot <= 0 ... return None` and says the put returns None for the same degenerate inputs as delta at `reviews/codex/claude_m15_put_scenarios_plan.md:310-326`. §4b and step 1 say the opposite at `reviews/codex/claude_m15_put_scenarios_plan.md:634-640` and `reviews/codex/claude_m15_put_scenarios_plan.md:840`. This needs correction. |
| R4 Low/negative down-beta | Mostly intact at `reviews/codex/claude_m15_put_scenarios_plan.md:680-697`, but line 685 says `DOWN_BETA_MIN_FOR_SCENARIO = 0.10 # configurable` while config additions do not include this field. Either make it config or remove "configurable." |
| R5 100-share multiplier visibility | Intact in acceptance at `reviews/codex/claude_m15_put_scenarios_plan.md:867`. |
| R6 CLI flags in scope | Partially regressed. `cli.py` remains in the file tree at `reviews/codex/claude_m15_put_scenarios_plan.md:134`, but the CLI summary lists only comparison sort choices at `reviews/codex/claude_m15_put_scenarios_plan.md:572-580` while v4 says `--sort-by` also controls sensitivity ranking fields at `reviews/codex/claude_m15_put_scenarios_plan.md:277` and step 9 at `reviews/codex/claude_m15_put_scenarios_plan.md:848`. |
| R7 Header heuristic labels | Partially regressed. Acceptance still requires heuristic labels at `reviews/codex/claude_m15_put_scenarios_plan.md:875`, but the header schema and math examples use plain labels without the word "heuristic" at `reviews/codex/claude_m15_put_scenarios_plan.md:297` and `reviews/codex/claude_m15_put_scenarios_plan.md:518`. |
| AF1 No-holdings speculation section | Intact. The universe-level section remains explicit at `reviews/codex/claude_m15_put_scenarios_plan.md:187-207`, and §2j keeps it always rendered at `reviews/codex/claude_m15_put_scenarios_plan.md:244`. |
| AF2 Selection rule undefined | Intact, but now competing with v4's sensitivity-first entry point. Speculation remains cheap-IV-first at `reviews/codex/claude_m15_put_scenarios_plan.md:193-199`; ranking is down-beta-first at `reviews/codex/claude_m15_put_scenarios_plan.md:253-279`. That can work, but the plan should explain that these are two different sections with two different sorts. |
| AF3 Use CandidatePut type | Intact at `reviews/codex/claude_m15_put_scenarios_plan.md:359`. |
| AF4 Header paths via manifest | Partially regressed. The v2 changelog and step 5 say header context reads `latest_options_manifest.refresh_run_id` and `benchmark_snapshot_paths`, but the module summary signature accepts `gold_history` and `gdx_history` as direct inputs at `reviews/codex/claude_m15_put_scenarios_plan.md:520-523`. Make the module summary match AF4. |

## Findings

### 1. P1 - CLI `--sort-by` is now overloaded and contradictory

v4 says `--sort-by` should accept `down_beta_12m` and `up_beta_12m` for Sensitivity Ranking (`reviews/codex/claude_m15_put_scenarios_plan.md:277`, `reviews/codex/claude_m15_put_scenarios_plan.md:848`). The CLI pseudocode still restricts choices to comparison columns and describes the flag as "Comparison view sort column" (`reviews/codex/claude_m15_put_scenarios_plan.md:572-580`). Acceptance only tests `--sort-by pnl_per_dollar_premium_minus10` for comparison (`reviews/codex/claude_m15_put_scenarios_plan.md:868`) and never tests ranking sort behavior.

This is a real implementation hazard because one flag is being asked to control two unrelated sections with different sort domains. Either split it into `--comparison-sort-by` and `--ranking-sort-by`, or define a single global `--sort-by` contract that says exactly which section it affects and how invalid choices are handled.

### 2. P1 - Calls are both in scope and out of scope

v3 adds `black_scholes_call_price`, `OptionStrategy.LONG_CALL`, and `OptionStrategy.SHORT_CALL` (`reviews/codex/claude_m15_put_scenarios_plan.md:29`, `reviews/codex/claude_m15_put_scenarios_plan.md:334-341`, `reviews/codex/claude_m15_put_scenarios_plan.md:646-678`). Acceptance requires all four strategies to be implemented and tested (`reviews/codex/claude_m15_put_scenarios_plan.md:877-878`). But §8 says "Calls" are out of scope and "defer until requested" (`reviews/codex/claude_m15_put_scenarios_plan.md:894`), and implementation guidance says "Calls (only puts)" at `reviews/codex/claude_m15_put_scenarios_plan.md:965`.

The likely intended meaning is "call math exists but calls are not surfaced in the report." The plan must say that consistently. As written, one implementer could skip call strategy support while another implements it, and both could point to the plan.

### 3. P1 - Report integration summary is stale and no longer matches §2j

§2j says the final report order is header, sensitivity ranking, portfolio totals, per-position scenarios, speculation, comparison, proxies, run summary (`reviews/codex/claude_m15_put_scenarios_plan.md:236-247`). But the `hedge/report.py` module summary still says "Inject four new sections" and lists only header, per-holding scenarios, speculation, and comparison (`reviews/codex/claude_m15_put_scenarios_plan.md:595-603`). It omits Sensitivity Ranking, Portfolio Totals, and the explicit proxy/run-summary ordering.

Step 10 points back to §2j and is correct at a high level (`reviews/codex/claude_m15_put_scenarios_plan.md:849`), but module summaries are where implementation details usually get copied from. Update the report module summary to match the v4 section order.

### 4. P1 - Black-Scholes module summary still violates the spot=0 blocker fix

The plan's top changelog and acceptance say the put spot-zero limit is mandatory (`reviews/codex/claude_m15_put_scenarios_plan.md:46`, `reviews/codex/claude_m15_put_scenarios_plan.md:872-873`). §4b also describes the correct limit behavior (`reviews/codex/claude_m15_put_scenarios_plan.md:634-640`). But the §3 `black_scholes_put_price` pseudocode still rejects `spot <= 0` (`reviews/codex/claude_m15_put_scenarios_plan.md:310-326`).

This was tolerable as a stale note in v2 because §4b was clearly authoritative. In v4 fresh-review mode, it is now a blocking inconsistency: fix the pseudocode and the "Returns None for same degenerate inputs as delta" sentence.

### 5. P2 - Sensitivity Ranking sort/cap behavior needs a cleaner contract

The v4 selection rule says the section sorts by `down_beta_12m` descending and renders all 60 tickers by default (`reviews/codex/claude_m15_put_scenarios_plan.md:253-279`). It also says the existing `--max-tickers` flag caps the section (`reviews/codex/claude_m15_put_scenarios_plan.md:279`), while the CLI help says `--max-tickers` caps the speculation section (`reviews/codex/claude_m15_put_scenarios_plan.md:586-590`). This is another overloaded flag.

Also, `sort_by="up_beta_12m"` is allowed in the module summary (`reviews/codex/claude_m15_put_scenarios_plan.md:401-412`) and step 9 (`reviews/codex/claude_m15_put_scenarios_plan.md:848`), but the section is specifically "gold-downside sensitivity." If `up_beta_12m` sorting is kept, define whether it sorts ascending or descending and why that is useful for a put workflow.

### 6. P2 - Portfolio Totals assumes share-count holdings and misses dollar-exposure behavior

The portfolio totals description computes `shares × implied_stock_price` and hedge costs from shares (`reviews/codex/claude_m15_put_scenarios_plan.md:215`, `reviews/codex/claude_m15_put_scenarios_plan.md:459-466`). M1 holdings support either `shares` or `dollar_exposure`; dollar-exposure holdings do not have a natural share count unless converted using `share_price_usd`. The plan should specify how portfolio totals handles dollar-exposure holdings, missing share price, missing 60d candidate, missing candidate mid, low down-beta, and non-optionable names.

The step 7 tests mention empty holdings, single-position correctness, hedge-cost summing, and ceil rounding (`reviews/codex/claude_m15_put_scenarios_plan.md:846`), but not these mixed-holding and missing-data cases. Add them or scope portfolio totals down.

### 7. P2 - File tree and config scope are stale after v3/v4

The §2b file tree says `hedge_readiness.yaml` adds only four fields: `default_scenario_quantity`, `default_scenarios`, `optionability_tier_min`, and `max_tickers_speculation_section` (`reviews/codex/claude_m15_put_scenarios_plan.md:135-136`). Step 2 adds `protection_levels` too (`reviews/codex/claude_m15_put_scenarios_plan.md:841`). The module tree also opens `golden_vector/hedge/` twice (`reviews/codex/claude_m15_put_scenarios_plan.md:123`, `reviews/codex/claude_m15_put_scenarios_plan.md:131`), which is harmless but confusing.

Update §2b so the file list, config additions, and v3/v4 module additions are one coherent source of truth.

### 8. P2 - Implementation guidance is stale for a 12-step plan

The plan correctly says v4 has 12 steps at `reviews/codex/claude_m15_put_scenarios_plan.md:836`, but implementation guidance still says "Seven steps → seven commits" (`reviews/codex/claude_m15_put_scenarios_plan.md:916`). It also says files outside §2b are out of scope except docs per step 7 (`reviews/codex/claude_m15_put_scenarios_plan.md:969`), but docs are step 12 (`reviews/codex/claude_m15_put_scenarios_plan.md:851`). These instructions need updating before implementation.

### 9. P2 - v4 dropped decision triggers for the right reason

The deliberate removal of binary triggers and threshold logic is the right architectural call. Emanuel wants to read the data himself, there is no active portfolio yet, and threshold overlays would make the report feel more opinionated than the model supports. Keeping header verdicts as "heuristic" and ranking/sensitivity data as sortable facts is better than adding "FIRING/OK" logic now.

One caveat: "opinion-free" should not mean "no warnings." Data-quality warnings, stale context, quote-quality failures, missing candidates, low confidence, and stock-clamp annotations should remain. Those are not decision triggers; they are guardrails.

### 10. P3 - Changelogs are informative but internally messy

The v3 and v2 changelog headings are duplicated (`reviews/codex/claude_m15_put_scenarios_plan.md:21-23`, `reviews/codex/claude_m15_put_scenarios_plan.md:34-40`). This is not a product blocker, but in a 1008-line plan it contributes to reviewer/implementer fatigue. Clean the headings and keep one changelog block per version.

## Plan Scale

This is now too large for one focused milestone unless the inconsistencies are cleaned and the team is comfortable with a long review cycle. The plan has grown from a put-scenario report extension into:

- option pricing functions,
- strategy-generic long/short put/call math,
- scenario tables,
- comparison table,
- header context,
- speculation section,
- portfolio totals,
- sensitivity ranking,
- CLI flags,
- report integration,
- manual smoke with two holdings states,
- docs.

Given M1 is still in flight, I recommend splitting. The cleanest split:

- **M1.5:** LONG_PUT scenario calculator, header context, speculation candidates, comparison view, CLI/report integration, and Sensitivity Ranking if Emanuel wants that as the entry point.
- **M1.6:** Portfolio Totals and strategy-generic non-report math for long/short put/call, after the core report is stable.

If Sensitivity Ranking is the primary user entry point, keep it in M1.5 and defer Portfolio Totals because the plan itself says Emanuel has no portfolio yet. If the team wants the smallest risk slice, ship M1.5 as scenarios + comparison + header + speculation only, then do Sensitivity Ranking in M1.6.

## Additional Risks To Add

- **Tradability vs optionability:** The plan still leans on `optionability_tier` and IV percentile. It should explicitly include quote-quality gates for action candidates: non-null mid, positive bid/ask, spread threshold, OI/volume, and plausible IV. Otherwise "directly hedgeable" can look more actionable than the data supports.
- **Stale feature files:** If candidate gates or feature logic change, current `options_features/*.parquet` will remain stale until `update-data --options` is rerun. Report output should surface source run ids and context freshness.
- **Short strategy risk:** If short call/put math is implemented in public APIs, tests should cover sign rules and max-loss/unbounded-loss annotations should stay out of report until short strategies are surfaced.
- **Shared CLI flags:** `--max-tickers` and `--sort-by` now touch multiple sections conceptually. Shared flags need explicit semantics or separate names.

## Required Edits Before Re-Review

1. Fix the black-scholes pseudocode and call/put scope language.
2. Decide whether calls/short strategies are in M1.5 or deferred; make §8 and §10 match.
3. Define CLI sort/cap semantics cleanly, preferably with separate flags for comparison and ranking.
4. Update the report module summary to match §2j.
5. Update §2b file/config tree for `protection_levels` and v4 modules.
6. Add portfolio totals behavior for dollar-exposure holdings and missing candidate data, or defer portfolio totals.
7. Fix stale implementation guidance: 12 steps, docs step 12, checkpoint wording.

