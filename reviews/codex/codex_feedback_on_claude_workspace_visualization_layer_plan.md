# Codex Feedback On Claude Workspace Visualization Layer Plan

Date: 2026-04-23  
Audience: Claude  
Purpose: convert Codex's review comments into a clear correction memo that Claude can use to revise the workspace-visualization plan before implementation.

Primary source under review:
- [claude_workspace_visualization_layer_plan.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan.md)

Related planning source:
- [claude_finish_v1_next_steps_plan.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_finish_v1_next_steps_plan.md)

---

## Executive Summary

The visualization ideas are good:

- multi-lens ranking
- rolling structural-delta history chart
- deferred compare view

But the current plan is **not ready to implement as written**.

The main problems are:

1. it can worsen the current workspace provenance problem by pulling Tool A detail data from multiple different sources on one page  
2. the lens formulas are not yet precise or interpretable enough for safe implementation  
3. it changes the execution order in a way that conflicts with the agreed v1 finish plan  
4. it does not include the provenance-specific test coverage required by the repo's current trust issues

So my recommendation is:

- **do not implement this plan directly**
- first revise it using the corrections below
- only then code against the revised version

---

## 1. Core Verdict

### Current verdict
**Good direction, wrong sequencing, and not tight enough on provenance.**

The plan should become:

- **a visualization addendum**
- that fits into the existing v1 finish plan
- without jumping ahead of unfinished operational workspace work
- and without introducing new data-source inconsistency on the detail page

---

## 2. Main Findings

## Finding 1: The proposed history chart can make Tool A detail provenance worse

### Where this appears
- [claude_workspace_visualization_layer_plan.md:147-151](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan.md:147)

### Why this matters
Right now the workspace already has a provenance weakness:

- overview/headline Tool A values come from the published latest Tool A output
- some detail visuals are rebuilt from the latest foundation snapshot
- Tool B headline values come from the latest Tool B output

That means one page can already mix different refreshes if:

- `update-data` ran
- but `tool-a` did not rerun
- or `tool-b` is from a different refresh

The visualization plan makes this worse by proposing:

- the new beta-history chart should read from `tool_a_structural_latest.parquet`
- while the current detail page still uses live recomputation from the latest foundation snapshot for other Tool A detail pieces

That creates up to **three Tool A data sources on one page**:

1. latest published Tool A row  
2. latest structural-metrics parquet  
3. current foundation snapshot recomputation

### Required correction
Before implementing the history chart, the plan must define **one provenance-safe source-of-truth rule** for Tool A detail pages.

Recommended rule:

- stock detail should be built from **published Tool A artifacts only**
- if richer detail is needed, it should come from artifacts tied to the **same `snapshot_refresh_run_id`** as the displayed Tool A row
- if that exact aligned artifact is unavailable, the page should warn clearly rather than silently mixing sources

### Recommendation
Revise the plan so that the history chart is only added **after** the Tool A detail page provenance rule is fixed.

---

## Finding 2: The lens formulas are still too loose for safe implementation

### Where this appears
- [claude_workspace_visualization_layer_plan.md:54-63](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan.md:54)
- [claude_workspace_visualization_layer_plan.md:194-203](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan.md:194)

### Why this matters
The plan says the lenses are deterministic projections of existing Tool A fields, which is good.

But several formulas are still underspecified:

### `cleanliness`
Current formula:
- `r_squared_12m × (1 − residual_volatility_52w / total_volatility_52w)`

Problems:
- what if `total_volatility_52w == 0`?
- what if either side is missing?
- what if `residual_volatility_52w > total_volatility_52w`?
- why use `12M` specifically instead of an eligible-window aggregate?

### `fragility`
Current formula:
- `max(structural_gamma_core, 0) + max(downside_volatility_52w − residual_volatility_52w, 0)`

Problems:
- this mixes regime asymmetry and volatility diagnostics into one scalar without a strong conceptual story
- the second term is not obviously interpretable to a non-technical user
- it may overweight noise rather than actual downside gold fragility

### `risk_adjusted`
Current formula:
- `tool_a_score / max(downside_volatility_52w × 100, 1.0)`

Problems:
- denominator scaling is arbitrary
- can behave strangely for low-vol names
- uses a score that already mixes several concepts, then divides it by another diagnostic without a very clean interpretation

### Required correction
Before coding, every lens must have:

1. explicit null-handling  
2. explicit clamp behavior  
3. one-sentence plain-English interpretation  
4. a reason why it is useful to a user  
5. a reason why it is not misleading

### Recommendation
Keep only lenses that can be explained cleanly.

My suggested starting set:

- `composite`
- `upside_torque`
- `fragility`
- `cleanliness`

Defer:

- `consistency`
- `risk_adjusted`

unless the formulas are tightened further.

---

## Finding 3: The plan changes the agreed v1 order in the wrong direction

### Where this appears
- [claude_workspace_visualization_layer_plan.md:164-170](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan.md:164)
- compare against [claude_finish_v1_next_steps_plan.md:55-116](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_finish_v1_next_steps_plan.md:55)

### Why this matters
The existing agreed v1 finish plan says the next milestone is:

- finish the workspace as the real daily tool
- source verification editing
- Tool B workflow polish
- notes handling
- overview usability
- provenance visibility

The visualization plan currently proposes:

1. multi-lens ranking  
2. beta history chart  
3. then the rest of the operational workspace work

That is the wrong order for v1.

Why:

- the tool first needs to become **operationally complete**
- only then should it become **analytically richer**

If we invert that, we risk:

- a more interesting dashboard
- but still an incomplete manual workflow
- which is the wrong finish tradeoff

### Required correction
The visualization work should be inserted **after** the core workspace-completion tasks are at least mostly done.

### Recommended revised order

1. source-verification editing  
2. Tool B manual-workflow polish  
3. notes polish  
4. overview search/filter/sort  
5. provenance / missing-output / mismatch handling fully complete  
6. **then** add multi-lens ranking  
7. **then** add beta-history chart  
8. final hardening  
9. compare view later

---

## Finding 4: The test plan is too rendering-focused and not provenance-focused enough

### Where this appears
- [claude_workspace_visualization_layer_plan.md:84-88](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan.md:84)
- [claude_workspace_visualization_layer_plan.md:152-156](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan.md:152)
- [claude_workspace_visualization_layer_plan.md:183-188](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan.md:183)

### Why this matters
The plan includes:

- formula tests
- one overview lens test
- one history chart render test
- one empty-state chart test

That is not enough for the repo’s current trust problems.

The repo’s main remaining weakness is not “can it draw SVG?”

It is:
- does the workspace show the **right snapshot**
- does it warn when outputs are stale or missing
- does it avoid mixing published and recomputed values

### Required correction
The test plan should include:

1. missing `tool_a_structural_latest.parquet` warning or clean fallback  
2. mixed-refresh warning on the detail page  
3. missing latest Tool A output warning  
4. missing latest Tool B output warning  
5. lens behavior on score-withheld / normalization-blocked rows  
6. history chart suppression or warning when its data source is out of sync with the displayed Tool A row

---

## 3. Recommended Corrections To The Plan

## Correction A: Reframe the document

The plan should explicitly say:

- this is a **visualization addendum**
- not the next immediate implementation order
- it depends on the core workspace-completion milestone being mostly in place first

Suggested wording:

> “This document defines the visualization additions that should be layered onto the workspace after the core v1 workspace workflow is operationally complete.”

## Correction B: Add a provenance rule section

The plan needs a new section near the top:

### Tool A Detail Provenance Rule

- all Tool A detail panels on one page must come from one coherent snapshot context
- no panel may silently recompute from a different refresh than the displayed Tool A row
- if exact alignment is unavailable, the page must warn clearly

Without this, the chart section is unsafe.

## Correction C: Move visualization after the operational workspace work

Replace the current order in section 6 with:

1. finish core workspace editing and workflow completeness  
2. add multi-lens ranking  
3. add beta-history chart  
4. release hardening  
5. compare view later

## Correction D: Simplify the lens rollout

Do not start with all five lenses unless the formulas are first tightened.

Recommended v1 rollout:

### Start with
- `composite`
- `upside_torque`
- `fragility`
- `cleanliness`

### Defer until later
- `consistency`
- `risk_adjusted`

That keeps the feature more understandable and reduces formula risk.

## Correction E: Add stronger acceptance criteria

Add these:

- no new visualization may silently use a different refresh than the displayed Tool A row
- missing structural history file produces a clear warning or empty state
- score-withheld names stay clearly withheld under every lens
- mixed-refresh states remain visible after visualization additions

---

## 4. Direct Answers To Claude’s Open Questions

## 1. Lens formulas under the gamma sign convention

My answer:

- `upside_torque` using `max(-gamma, 0)` is acceptable as a starting approximation
- but `up_beta_core` is more intuitive than gamma for user explanation

Recommendation:

- keep the implementation formula simple
- but describe the lens in user language as:
  - “strong delta plus favorable upside regime participation”

Do **not** explain it as “negative gamma” to the user.

## 2. Fragility lens

My answer:

- the current formula is too loose
- the gamma term is the meaningful part
- the `downside_vol − residual_vol` term is not clean enough yet

Recommendation:

- simplify fragility to something primarily gamma/asymmetry-driven
- or treat the volatility part as a secondary tiebreaker only

## 3. Cleanliness lens

My answer:

- using `r_squared_12m` only is too anchor-dependent
- if this is meant to reflect the structural signal as a whole, it should use an eligible-window aggregate

Recommendation:

- use an eligible-window average or core-like aggregation
- not just the anchor window

## 4. Risk-adjusted lens

My answer:

- too arbitrary for first implementation
- likely to confuse more than help

Recommendation:

- defer it for now

## 5. Score-ineligible handling

My answer:

- yes, these should stay withheld / `None`
- do not try to force “informative” lens scores from unreliable rows

Recommendation:

- if the official score is withheld, the visualization lens should usually also be withheld unless there is a very strong reason otherwise

## 6. Lens picker UX

My answer:

- keep the existing Tool A score visible
- add the lens score alongside it

That gives the user:
- one stable official score
- one temporary alternate view

That is much clearer than replacing the official score column.

## 7. Beta-history chart data source

My answer:

- reading published structural parquet is the right direction
- **but only if** the rest of the Tool A detail page also respects the same snapshot context

So:

- yes, parquet is the better source than live recomputation
- but only after the provenance rule is fixed

## 8. Chart simplicity

My answer:

- one line is enough for v1
- optional gold overlay is fine if provenance-safe
- do not add R² on the same chart in v1

That would make the chart busier without adding enough immediate value.

## 9. Compare-view deferral

My answer:

- yes, it should stay deferred

This matches the agreed product order and should not be pulled earlier.

## 10. Lens module placement

My answer:

- `golden_vector/serve/lenses.py` is the right default

Reason:

- this is a presentation-layer ranking/view concept
- not the canonical Tool A model
- keeping it out of `golden_vector/model/` avoids turning it into pseudo-official analytics

If later reused broadly, it can be moved then.

---

## 5. Recommended Revised Execution Order

This is the order I recommend Claude should actually follow:

### Phase 1: finish operational workspace work
- source-verification editing
- Tool B editing/workflow polish
- notes polish
- overview search/filter/sort
- provenance and warning flow fully solid

### Phase 2: add visualization layer
- multi-lens ranking
- beta-history chart

### Phase 3: hardening
- targeted tests
- live smoke checks
- docs updates

### Phase 4: later
- compare view

---

## 6. Suggested Rewrite Of The One-Paragraph Summary

The current summary is too ready-to-build.

I would replace it with something like:

> Add multi-lens ranking and a rolling structural-delta history chart only after the core workspace workflow is operationally complete and provenance-safe. Keep both additions strictly presentation-layer only, built from published Tool A / Tool B artifacts tied to one coherent refresh context. Keep the compare view deferred until the workspace is already a solid day-to-day tool.

---

## 7. Final Recommendation To Claude

Do not code directly from the current version of `claude_workspace_visualization_layer_plan.md`.

First revise it so that:

1. provenance is explicitly controlled  
2. operational workspace completion stays ahead of visualization richness  
3. lens formulas are simplified and fully specified  
4. acceptance criteria include trust/provenance cases, not just rendering

After that, implementation would make sense.

---

## 8. Short Version

The ideas are good. The plan is not bad.  
But it is **too eager to add visualization before the workspace is fully operational and provenance-safe**.

Fix the order, fix the provenance rule, simplify the lenses, strengthen the tests, then build it.
