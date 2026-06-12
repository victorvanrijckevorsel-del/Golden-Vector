# Codex Status - Tooltip / Explanation Decisions

Purpose: capture the user decisions around hover explanations, what has actually shipped, and what is still missing so Claude can act without re-reading the whole chat.

Current verdict: **PARTIALLY IMPLEMENTED**

The work was not forgotten entirely. It was split into two phases in `reviews/codex/codex_option_snapshot_fallback_plan.md`:

- **D1** = shared mechanism + Option Trading first adopter.
- **D2** = true site-wide rollout to Tool A/B/C/D, Candidate Finder, detail tables, and richer explanations.

D1 appears to be implemented. D2 is not complete, which is why Emanuel can still find many titles/columns across the website with no hover explanation.

## What Happened

The plan explicitly split "hover explanation everywhere" into a small first pass and a later rollout:

- `reviews/codex/codex_option_snapshot_fallback_plan.md:720` defines the goal as site-wide hover explanations.
- `reviews/codex/codex_option_snapshot_fallback_plan.md:740` scopes **D1** to the mechanism plus Option Trading.
- `reviews/codex/codex_option_snapshot_fallback_plan.md:768` leaves **D2** as the rollout to Tool D, remaining overview tables, and Candidate Finder.

The current code has the D1 mechanism:

- `golden_vector/serve/column_help.py:1` defines a shared column-help registry.
- `golden_vector/serve/column_help.py:23` stores `meaning`, `calculation`, `thresholds`, and `direction`.
- `golden_vector/serve/column_help.py:52` renders a `<th title="...">` through `help_th`.
- `golden_vector/serve/overview_option_trading.py:129` uses the registry for `Skew vs Benchmark`.
- `golden_vector/serve/overview_option_trading.py:210` uses the registry for the Cached Liquidity Check table.
- `golden_vector/serve/option_signal_render.py:68` renders row-level skew hover text from persisted signal fields.

The current code does **not** have the site-wide D2 rollout:

- `golden_vector/serve/overview_tool_a.py:120` still has plain hard-coded `<th>` headers.
- `golden_vector/serve/overview_tool_b.py:336` still has plain hard-coded `<th>` headers.
- `golden_vector/serve/overview_tool_c.py:87` still has plain hard-coded `<th>` headers.
- `golden_vector/serve/overview_tool_d.py:293` has some hard-coded `title=` strings, but they are not registry/config-driven.
- `golden_vector/serve/candidate_finder_page.py:360` renders the builder table with `Meaning`, but no hover on the headers or criterion names.
- `golden_vector/serve/candidate_finder_page.py:469` renders selected criterion headers without tooltip text.
- Many detail-page tables in `golden_vector/serve/detail_panels.py` still use plain `<th>`.

Also, D1 currently uses native browser `title=` tooltips. That is a cheap MVP, but it is easy for users to miss because there is no visible help icon and native browser tooltips are limited for multi-line formulas, mobile/touch, and keyboard users.

## Decision / Status Table

| Decision | Status | Evidence | Gap / Action |
|---|---:|---|---|
| Any non-obvious title/header should explain what it means. | Partial | `golden_vector/serve/column_help.py` exists. | Roll out to Tool A/B/C/D, Candidate Finder, portfolio, and detail tables. |
| Tooltip text should include meaning, formula/calculation, thresholds, and whether higher/lower is better. | Partial | `ColumnHelp` has `meaning`, `calculation`, `thresholds`, `direction` at `golden_vector/serve/column_help.py:23`. | Most registered entries are option-specific only. Need registry coverage for all important metrics. |
| Thresholds must come from backend/config, not copied literals in templates. | Partial | `_tradable_thresholds` reads `AppConfig` at `golden_vector/serve/column_help.py:77`. | Tool D still has hard-coded `title=` strings in `overview_tool_d.py`; Candidate Finder criterion descriptions do not carry threshold references. |
| Native `title=` is acceptable for first pass, but richer popovers may be needed later. | Partial | `help_th` emits native `title=` at `golden_vector/serve/column_help.py:67`. | Needs a visible/accessible help affordance if Emanuel wants explanations to be discoverable everywhere. |
| Cached Liquidity Check medians should be clearly tradable-only. | Implemented | `overview_option_trading.py:202` says medians cover tradable contracts only; headers say `Median Tradable ...` at `overview_option_trading.py:214`. | Good. Keep Watch/No-trade counts visible as context. |
| Keep Watch and No-trade counts, but medians should be tradable-only. | Implemented | Rows render `tradable_count`, `watch_count`, `no_trade_count` at `overview_option_trading.py:190`. | Good. |
| Hover on `Tradable` should explain how it is calculated and show thresholds. | Implemented for Cached Liquidity Check | `COLUMN_HELP["tradable_count"]` at `column_help.py:133`; thresholds from config at `column_help.py:77`. | Not implemented on every `Tradable candidate` badge in detail tables. |
| Explain that chain-level Tradable and candidate-level Tradable are not exactly the same gate. | Implemented in header tooltip | `column_help.py:138` explains chain-level vs stricter candidate bucket rule. | Candidate row badges could also expose this when hovered. |
| `Skew Read` should be renamed because it actually means benchmark-relative skew for stocks. | Implemented on Option Trading overview | Header is `Skew vs Benchmark` at `overview_option_trading.py:129`. | Detail charts/tables should use the same wording consistently. |
| Hovering a stock skew value should show the actual calculation: stock skew, benchmark, benchmark skew, difference. | Implemented on Option Trading overview rows | `option_signal_skew_hover` at `option_signal_render.py:68`; used at `overview_option_trading.py:276`. | Not obviously available everywhere skew appears, especially detail charts/tables. |
| Benchmark ETF rows should show absolute benchmark skew, not residual. | Implemented in helper | `option_signal_render.py:90` has benchmark-specific hover branch. | Good. |
| Rename vague option labels: `Cost` -> `Option Cost Signal`, `Data Quality` -> `Option Signal Quality`, `Snapshot Date` -> `Option Snapshot Date`. | Mostly implemented on Option Trading overview | `overview_option_trading.py:108-112`, `overview_option_trading.py:137`, `overview_option_trading.py:143`, `overview_option_trading.py:158`. | Verify all detail-panel labels match; some lanes may still use shorter internal wording. |
| Candidate Finder `Field` column should be replaced with short plain-English meaning. | Implemented | Builder header is `Meaning` at `candidate_finder_page.py:366`; cell uses `criterion.description` at `candidate_finder_page.py:398`. | Some descriptions remain too vague, e.g. `Advanced survival blend`, `Advanced selloff behavior score`. |
| Candidate Finder should explain higher/lower direction. | Partial | Top-list card says `{High/Low} values rank higher` at `candidate_finder_page.py:438`; builder has Direction dropdown. | Builder row itself does not combine meaning + direction in one hover/help text; no formula/thresholds. |
| User can scan all stocks or only optionable names. | Implemented | Universe selector at `candidate_finder_page.py:275-278`. | Good. |
| Replace old `Strong Corporate Finance`, `Bearish put`, `Bullish call` with simpler Bull/Bear presets. | Implemented | `config/candidate_finder.yaml:190` defines `Bull`; `config/candidate_finder.yaml:216` defines `Bear`. | Good, though copy can still be simplified. |
| Avoid opaque composite ranks where simple raw numbers are better. | Partial / not fully resolved | Advanced composites still exist in config: `tool_c_downside_rank`, `tool_c_upside_rank`, `tool_d_quality_rank` at `config/candidate_finder.yaml:165-186`. | Decide whether to hide these from the default builder or move them under an "Advanced" collapsed group with stronger explanation. |
| Tool D tooltips should come from the same registry and config thresholds. | Not implemented | `overview_tool_d.py:293-311` has hard-coded `title=` strings. | Move Tool D explanations into `column_help.py` or backend metadata; include debt-stress threshold meaning. |
| Tool A/B/C overview tables should have metric explanations. | Not implemented | Plain headers in `overview_tool_a.py`, `overview_tool_b.py`, `overview_tool_c.py`. | Add registry-backed headers for key metrics. |
| Detail pages should also explain table titles/metrics. | Not implemented broadly | Many plain `<th>` blocks in `detail_panels.py`. | Add help for option candidates, scenario tables, Tool A structural table, resilience panels, and portfolio metrics. |

## What Claude Should Do Next

Recommended build plan:

1. **Do not create a second tooltip system.** Extend `golden_vector/serve/column_help.py` and `help_th`.
2. Add registry coverage for the highest-visibility pages first:
   - Candidate Finder builder and ranking tables.
   - Tool B Corporate Finance overview.
   - Tool C Gold Downside overview.
   - Tool D Corporate Resilience overview.
   - Option Trading detail candidate/scenario tables.
3. Replace hard-coded `title=` strings in Tool D with registry-backed help.
4. Add richer Candidate Finder metadata rather than stuffing all text into `description`:
   - `meaning`
   - `calculation`
   - `threshold_ref` or explicit backend-provided threshold text
   - `direction_explanation`
   - `source`
5. Keep thresholds single-source:
   - If a tooltip mentions a threshold, read it from `AppConfig` or from the backend model metadata.
   - Do not hard-code threshold numbers inside templates.
6. Add tests:
   - Each major page renders at least one registry-backed `title=`.
   - Changing a config threshold changes the tooltip text.
   - Tool D no longer has hard-coded `title=` formulas outside the registry.
   - Candidate Finder criterion headers/cells expose meaning + direction in the UI.
7. Decide whether native `title=` is enough. If Emanuel still cannot see the help clearly, implement a small accessible popover:
   - visible `?` or dotted-underlined label
   - hover + keyboard focus
   - multi-line content
   - no analytics or formula math in JavaScript

## Plain-English Product Recommendation

The current D1 implementation is useful but too hidden. Native browser hover is not obvious enough for a beginner user. The right end state is:

- short table labels stay clean,
- every unclear label has a visible help affordance,
- the help text says what the number means, how it is calculated, the real threshold if any, and which direction is good,
- the backend/config owns the meaning and thresholds,
- serve only renders that explanation.

That is the standard to use for D2.
