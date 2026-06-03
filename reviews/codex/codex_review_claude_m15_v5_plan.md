Grade: NEEDS CHANGES

## Summary

v5 is a major improvement over v4: the calls/report scope is now mostly clear, the CLI sort flags are separated, the Black-Scholes spot=0 fix is intact, and the plan now has a useful M2-ready section-builder direction. I would not start implementation yet because four remaining contradictions are load-bearing: the section dataclasses omit report sections, the plan alternates between 8 and 9 sections, portfolio dollar-exposure hedge-cost logic contradicts itself, and the `breakeven_gold_pct` sort rule is still backwards for a put-buying workflow.

This should be a short plan cleanup, not another full redesign. After the required edits below, this can probably be implemented as one milestone.

## v4 Finding Regression Check

| # | v4 finding | v5 status |
|---|---|---|
| 1 | CLI `--sort-by` overloaded | Fixed. `--comparison-sort-by` and `--ranking-sort-by` are separate at `reviews/codex/claude_m15_v5_plan.md:146-166`, with non-overlapping choices. |
| 2 | Calls both in scope and out of scope | Fixed in intent. Lines `90`, `312-340`, `789`, and `858-861` consistently say call/short math is in scope, report surfacing is out of scope. |
| 3 | Report module summary stale vs section order | Mostly fixed. The report summary at `523-551` now lists the desired order, but the plan still says "8 sections" while listing 9 at `231-243`; see Finding 2. |
| 4 | Black-Scholes put spot=0 regression | Fixed. `black_scholes_put_price` now says spot=0 returns the discounted strike at `374-378`, matching pseudocode at `617-624`. |
| 5 | Down-beta min called configurable without config | Fixed. `down_beta_min_for_scenario` is in the file tree at `122-129`, config step at `742`, and scenario signature at `412-414`. |
| 6 | CLI choices incomplete | Fixed by separate flags. Comparison choices are at `152-157`; ranking choices are at `158-159`. |
| 7 | Header labels missing "heuristic" | Fixed. Header labels include "heuristic" at `658-668`, and existing `header_context.py` already matches. |
| 8 | Header context signature mismatch | Fixed. The current implementation takes `paths`, and v5 describes manifest-based loading at `553-555`. |
| 9 | `--max-tickers` overloaded | Fixed. `--ranking-max-tickers` and `--speculation-max-tickers` are separate at `160-163`. |
| 10 | `up_beta_12m` sort option | Fixed. `up_beta_12m` is context only at `247-264`; ranking sort choices are `down_beta_12m` only. |
| 11 | Portfolio totals dollar_exposure | Partially fixed. The schema now mentions both modes at `266-310`, but hedge-cost logic conflicts with the risk section at `804`; see Finding 3. |
| 12 | File tree stale | Partially fixed. The tree lists the right files, but counts are stale: it says "4 flags" while listing 5 at `78` and `575-598`, and "7 new fields" while listing 10 at `122-132`; see Finding 6. |
| 13 | Implementation guidance says seven steps | Mostly fixed. `13 steps -> 13 commits` is correct at `813-819`, but several internal step references are wrong; see Finding 5. |
| 14 | Duplicate changelog headings | Fixed enough. v5 has one active changelog and a placeholder history appendix at `906-912`. |

## New Findings

### 1. P1 - `HedgeReadinessSections` omits the Header and Sources sections

The plan promises a section-builder to emitter refactor for all report sections, but the central dataclass at `reviews/codex/claude_m15_v5_plan.md:219-227` has no `header` field and no `sources` / `run_summary` field. This conflicts with the report order at `231-243`, the report module summary at `537-551`, and acceptance at `763` and `776`. It also undercuts the M2 reuse goal because an HTML emitter would not be able to render the header context or provenance from the shared `HedgeReadinessSections` object.

This is the highest-priority structural fix. Add explicit fields, for example `header: HeaderContext` and `sources: SourcesData` / `RunSummaryData`, or explain why those two sections are intentionally emitted outside the section data layer. Without that, step 11 will either balloon or silently recreate markdown-only logic.

### 2. P1 - The plan says "8 sections" but lists 9 sections

Section ordering says "The 8 sections" at `reviews/codex/claude_m15_v5_plan.md:231-233`, then lists 9 numbered sections at `235-243`: Header, Snapshot Summary, Sensitivity Ranking, Portfolio Totals, Held Positions, Speculation Candidates, Cross-ticker Comparison, Proxy Hedges, Sources / Run summary. Acceptance repeats "all 8 sections" at `763`, and step 11 says tests assert "8-section ordering" at `751`.

This is not cosmetic because tests and emitter code will copy this language. Decide whether the report has 8 or 9 sections. My recommendation: call it 9 sections and keep both Header and Sources / Run summary explicit. If you want "8 analytical sections plus Sources," say that consistently and make tests assert the exact heading order.

### 3. P1 - Portfolio dollar-exposure hedge-cost logic contradicts itself

The portfolio schema says dollar-exposure mode is "always resolvable" and "doesn't need price" at `reviews/codex/claude_m15_v5_plan.md:299-304`, and the aggregate hedge-cost formula uses `target_notional / (strike * 100)` at `305-310`. But the risks section says dollar-exposure hedge cost needs `target_shares = dollar_exposure x X% / current_stock_price`, and if `current_stock_price` is missing "we can't compute hedge cost" at `804`.

Those are different contracts. The implementation needs one rule:

- If hedge cost is based on notional divided by put strike, dollar-exposure holdings can compute hedge cost without current stock price, as long as a 60d candidate with strike and mid exists.
- If hedge cost is based on converting exposure to target shares using current stock price, dollar-exposure holdings need current stock price and must skip hedge-cost calculation when price is missing.

Pick one and update `2g`, step 7 tests, and risk #4 to match. I lean toward the current-stock-price rule because it mirrors "how many shares am I economically hedging?", while strike-based notional is an approximation that will drift for out-of-the-money puts.

### 4. P1 - `breakeven_gold_pct` sort direction is still wrong for the user workflow

The comparison module summary says `breakeven_gold_pct` should sort ascending because "smaller (more negative) is better" at `reviews/codex/claude_m15_v5_plan.md:504-520`, and acceptance requires ascending / "most-negative-first" at `766`. I disagree with the CODE_REVIEW.md M2 framing here. For a long put, a breakeven of `-1%` is better than `-9%` because gold needs to fall less before the trade breaks even. More negative means the put needs a larger gold drop to work.

If `breakeven_gold_pct` remains a comparison sort choice, sort it closest-to-zero-first among negative values, with nulls last and positive/invalid breakevens annotated. The separate P&L columns already answer "which option wins more if gold drops hard"; breakeven should answer "how much gold downside do I need before this trade starts working?"

### 5. P2 - Step references for folded-in M1 cleanups drifted

The top changelog says H2 proxy 3-tier is step 12 and H3 options isolation is step 13 at `reviews/codex/claude_m15_v5_plan.md:31-33`. Section `2i` repeats that at `342-346`. But the actual order of operations puts proxy 3-tier at step 8, options isolation at step 9, manual smoke at step 12, and docs at step 13 (`748-753`). Similarly, `2a` says the section-builder refactor is "DONE in step 9" at `100`, while the actual report refactor is step 11 at `751`.

This is easy to fix, but it matters because checkpoint A is after step 9. If H2/H3 are step 8/9, checkpoint A includes those cleanups; if they are step 12/13, it does not. Make all references use the step table as the source of truth.

### 6. P2 - File tree and CLI summaries have stale counts

The file tree says `config/hedge_readiness.yaml` adds "7 new fields" at `reviews/codex/claude_m15_v5_plan.md:122`, then lists 10 fields at `123-132`. The "what needs to be built" list says `cli.py` adds "4 new flags" at `78`, and the module summary says "4 new flags" at `575`, but the plan lists 5 flags: `--comparison-sort-by`, `--ranking-sort-by`, `--ranking-max-tickers`, `--speculation-max-tickers`, and `--quantity` at `151-165` and `579-598`.

This is not a product blocker, but it is exactly the kind of stale-count issue that causes implementation checklists and completion reports to disagree. Fix the counts before implementation.

### 7. P2 - `PortfolioTotalsData` is defined twice with different fields

The section data dataclass at `reviews/codex/claude_m15_v5_plan.md:192-198` defines `PortfolioTotalsData` with `holdings_count`, `current_total_value`, `scenario_rows`, and `interpretive_notes`. The fuller schema at `289-297` adds `holdings_resolved_count` and `holdings_skipped`. The module summary at `461-466` points to `2g`, but step 11 will likely copy the shorter `2d` version.

Use one definition. The richer `2g` shape is better because markdown and HTML both need skipped-holding explanations.

### 8. P2 - Options isolation pseudocode can double-count a failed ticker

The `options_phase.py` pseudocode increments `status_counts[result.status]` before `persist_options_snapshot()` and `_compute_feature_row()` at `reviews/codex/claude_m15_v5_plan.md:560-568`. If persist or feature computation fails, the `except` increments `OPTIONS_STATUS_ERROR` at `569-572`, so the same ticker can be counted as both success and error.

Move the status-count increment after the per-ticker try block succeeds, or track `fetch_status` separately from `pipeline_status`. The test in step 9 should assert summary counts, not only that the command does not crash.

### 9. P2 - `_helpers.py` migration conflicts with the header-context module summary

Step 5 says to add `_helpers.py` and migrate all four hedge modules with private helper copies at `reviews/codex/claude_m15_v5_plan.md:745`. One of those is `header_context.py` in the current codebase. But the header-context module summary says "v5 step 5 has no changes to this module" at `553-555`. The likely intended meaning is "no behavioral changes," but the plan should say that explicitly because step 5 will still edit imports/helper calls.

## Plan Scale

I would keep v5 as one milestone after the above edits. It is big, but it is now coherent enough in shape: several modules already exist, the new pieces are narrow, and the section-builder refactor is a real dependency for M2. Splitting before the section-builder refactor would likely create duplicated markdown/UI logic later.

The only split I would consider is deferring Portfolio Totals to M1.6 if the dollar-exposure hedge-cost rule takes another review cycle. Everything else belongs together: scenario math, sensitivity ranking, speculation, comparison, CLI flags, and the report emitter are one user-facing workflow.

## Implementation Risk Areas

- **Step 11 report refactor:** This is the largest step. It should start by defining the complete `HedgeReadinessSections` object, including Header and Sources, before moving renderer code. If the dataclass shape changes mid-step, the diff will become hard to review.
- **Step 5 helper consolidation:** Low risk if `_helpers.py` stays dependency-light. Do not import `AppConfig`, `ProjectPaths`, or hedge modules from `_helpers.py`; otherwise import cycles become likely.
- **Step 6 sensitivity ranking:** Skip paths need real tests: no candidate, no options, null down-beta, score-ineligible, low down-beta, missing risk-free-rate if that can reach the builder.
- **Step 7 portfolio totals:** The hardest part is not the math; it is producing honest skipped-holding notes while still counting portfolio notional where possible.
- **Step 9 options isolation:** Mock a failure after fetch succeeds, ideally in persist or feature compute, and assert both continuation and correct summary counts.

## Required Edits Before Implementation

1. Add `header` and `sources` / `run_summary` to `HedgeReadinessSections`, or explicitly mark them as emitted outside the section data layer and explain how M2 will reuse them.
2. Resolve the section count: 8 vs 9. Update `2e`, acceptance criteria, step 11 tests, and the worked mock to use the same heading count.
3. Choose one dollar-exposure hedge-cost rule and make `2g`, risk #4, and step 7 tests agree.
4. Fix `breakeven_gold_pct` sorting. I recommend closest-to-zero-first for valid negative breakevens, not most-negative-first.
5. Correct all stale step references for H1/H2/H3 and the section-builder refactor.
6. Fix stale counts: 5 CLI flags, not 4; 10 config fields, not 7.
7. Collapse the two `PortfolioTotalsData` definitions into one complete schema.
8. Adjust options isolation pseudocode so a ticker that fails after fetch is not counted as both success and error.
9. Clarify that `header_context.py` has no behavioral changes but may still be touched by `_helpers.py` migration.

