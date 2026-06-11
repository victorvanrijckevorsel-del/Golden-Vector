# Codex Holistic Review - Gold Dial + Dual-Source Fundamentals Milestones

**Verdict: NEEDS CHANGES before I would call this merge-perfect.**

The overall architecture is much stronger than the old setup: spot is now the canonical Tool B basis, scenario runs are isolated, official fundamentals are stored as durable artifacts, the UI mostly renders backend-computed fields, and the Candidate Finder scenario path does not write artifacts. I would not call it "perfect" yet. There is one high-severity official-fundamentals mapper bug, plus several medium infrastructure gaps that should be fixed or consciously accepted before we build more on top.

Focused checks run during this review:

```text
python -m pytest tests/test_fundamentals_fetch.py tests/test_fundamentals_artifact_contract.py tests/test_tool_b_pipeline.py tests/test_cli_tool_b.py tests/test_candidate_finder_data.py tests/test_candidate_finder_page.py tests/test_workspace_app.py -k "fundamental or tool_b or candidate_finder or gold_price or scenario" -q
97 passed, 51 deselected in 125.38s
```

## Executive Assessment

I would rate the milestone as **architecturally sound but not finished to the bar I want**.

The good part: the data spine now has the right pattern. Raw Yahoo statements are persisted first, mapped official fundamentals are persisted separately, the current model-state manifest references the official artifact as optional, Tool B spot runs are canonical, scenario runs are not published, and the serve layer mostly reads backend-computed fields.

The not-good-enough part: the raw-to-official mapper can fabricate net debt when Yahoo has debt but no cash line. That is exactly the kind of plausible-looking wrong number that this project is trying to avoid. I also found a scenario/fundamentals integration gap in Candidate Finder, and the operational story for keeping official fundamentals fresh is still manual and easy for a user to miss.

## What Is Strong

**1. Canonical spot vs scenario isolation is correct.**

`run_tool_b` now resolves spot from gold history after loading the foundation and fails before persistence when spot cannot be resolved ([golden_vector/cli.py:1835](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\cli.py:1835)). Scenario Tool B runs set `publish_latest_aliases=False` and are run-stamped only ([golden_vector/cli.py:1943](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\cli.py:1943)). `refresh --gold-price` is refused rather than allowed to publish an incoherent current state ([golden_vector/cli.py:3014](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\cli.py:3014)); the test exists at [tests/test_cli_tool_b.py:352](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_cli_tool_b.py:352).

**2. Official fundamentals are stored in a buildable data-center shape.**

The artifact contract separates raw statements from mapped official fields ([golden_vector/contracts/fundamentals.py:1](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\contracts\fundamentals.py:1)). Raw statements are written as run-stamped Parquet plus a latest alias, and a fetch manifest records raw paths, hashes, timings, statuses, and the official artifact pointer ([golden_vector/fundamentals/raw_store.py:86](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\fundamentals\raw_store.py:86), [golden_vector/fundamentals/raw_store.py:126](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\fundamentals\raw_store.py:126)). The mapped official artifact is also run-stamped plus latest alias ([golden_vector/fundamentals/artifacts.py:28](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\fundamentals\artifacts.py:28)).

**3. Model-state integration is mostly right.**

The official fundamentals artifact is in the model-state artifact map and marked optional (`required_for_complete=False`) ([golden_vector/app/model_state.py:391](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\app\model_state.py:391)). The reader resolves through the model-state manifest first and falls back only if no manifest artifact exists ([golden_vector/fundamentals/artifacts.py:52](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\fundamentals\artifacts.py:52)). Stale official statement fields surface as model-state warnings ([golden_vector/app/model_state.py:893](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\app\model_state.py:893)).

**4. The backend owns the Tool B math and comparison logic.**

The Tool B pipeline resolves Official vs Our-view layers, computes both, emits backend comparison columns, and keeps existing `ev_ebitda` / `leverage` aliases as Our-view for downstream consumers ([golden_vector/screening/pipeline.py:275](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\screening\pipeline.py:275), [golden_vector/screening/pipeline.py:362](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\screening\pipeline.py:362)). The UI uses backend-provided values and flags (`*_differs`, `divergent_field_count`, `max_divergence_pct`) for display/sort/filter ([golden_vector/serve/overview_tool_b.py:64](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\serve\overview_tool_b.py:64), [golden_vector/serve/overview_tool_b.py:106](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\serve\overview_tool_b.py:106)). The serve-arithmetic guard exists at [tests/test_workspace_app.py:1987](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_workspace_app.py:1987).

**5. Candidate Finder scenario runs are side-effect free.**

The scenario path injects in-memory Tool B and Tool D frames into the join and preserves persisted artifacts; the no-write behavior is tested at [tests/test_candidate_finder_data.py:430](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_candidate_finder_data.py:430). The cache is bounded at 32 entries ([golden_vector/serve/candidate_finder_data.py:60](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\serve\candidate_finder_data.py:60), [golden_vector/serve/candidate_finder_data.py:1196](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\serve\candidate_finder_data.py:1196)).

## Findings

### HIGH 1 - Official net debt can be fabricated when cash is missing

In `_map_net_debt`, debt is required, but cash is silently defaulted to zero:

```python
cash = _find_value(balance, CASH_ALIASES) or 0.0
converted = _convert_money(total_debt - cash, ...)
```

See [golden_vector/fundamentals/mapper.py:159](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\fundamentals\mapper.py:159) and [golden_vector/fundamentals/mapper.py:175](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\fundamentals\mapper.py:175).

This violates the plan's own rule that a missing leg of net debt must be `MISSING`, never coerced to zero. It can create a plausible but wrong official Net Debt/EBITDA and EV/EBITDA. The existing test only covers "cash present, debt missing" ([tests/test_fundamentals_fetch.py:96](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_fundamentals_fetch.py:96)); it does not cover "debt present, cash missing."

Concrete fix:

- If no cash alias is present, return `_missing_field("net_debt_musd", ...)`.
- Add `test_mapper_missing_cash_leg_is_missing_not_zero_debt`.
- Keep the existing debt-missing test.

This is the only finding that makes me say **NEEDS CHANGES** rather than approve.

### MEDIUM 1 - Candidate Finder scenario Tool B recompute drops official fundamentals

The Tool B page passes `official_fundamentals` into `compute_tool_b_in_memory` ([golden_vector/serve/overview_tool_b.py:430](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\serve\overview_tool_b.py:430)). Candidate Finder scenario recompute does not; it calls `compute_tool_b_in_memory` without `official_fundamentals` ([golden_vector/serve/candidate_finder_data.py:982](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\serve\candidate_finder_data.py:982)).

Current impact is limited because the configured Finder scenario fields are the Our-view gold-sensitive fields, not official comparison columns. But as infrastructure, this is not ideal: the same Tool B model seam behaves differently depending on caller, and future official-rank criteria would silently degrade in the Finder scenario path.

Concrete fix:

- Load `official_fundamentals = load_official_fundamentals(paths)` inside `_compute_scenario_sources`.
- Pass it into `compute_tool_b_in_memory`.
- Include the official artifact hash in the scenario cache key when scenario mode is active.
- Add a scenario test where an official value differs and the scenario frame still carries the official comparison columns.

### MEDIUM 2 - "Refresh all model data" still does not refresh official fundamentals

The plan deliberately keeps fundamentals as a separate command: `python main.py fetch-fundamentals` ([reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:370](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\reviews\codex\claude_gold_dial_and_fundamentals_plan_v2.md:370)). The implementation follows that: `run_fetch_fundamentals` is its own command ([golden_vector/cli.py:744](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\cli.py:744)) and can republish the model-state manifest ([golden_vector/cli.py:780](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\cli.py:780)), but `refresh` does not call it.

That is defensible technically because statements move quarterly and Yahoo load is real. Product-wise, it is easy for Emanuel to click "Refresh all model data" and assume official fundamentals were refreshed when they were not.

Concrete fix:

- At minimum, surface official-fundamentals age and a "run `python main.py fetch-fundamentals`" note on status/Tool B.
- Better: add an explicit separate button/command label, e.g. "Refresh official financial statements", not hidden behind "all model data."
- Later: config-driven cadence, not every refresh.

This is not a code correctness blocker, but it is an infrastructure/UX honesty gap.

### MEDIUM 3 - Raw fundamentals retention is safe but unbounded

Pruning protects raw fundamentals manifests and the raw statements they reference ([golden_vector/app/run_pruning.py:268](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\app\run_pruning.py:268), [golden_vector/app/run_pruning.py:355](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\app\run_pruning.py:355)). This is good for auditability and matches Emanuel's desire to keep data.

But the current design effectively protects every run-stamped raw fundamentals fetch manifest forever. That may be fine because fundamentals statements are small and infrequent, but it should be an explicit product decision. If this later gets scheduled weekly across 60+ tickers, the raw archive should have a retention/archive policy rather than being accidentally infinite.

Concrete fix:

- Add a short docs note: raw fundamentals are append-only for now.
- Add retention config later: keep all quarterly snapshots, or keep N years, but never delete a raw artifact referenced by a retained official artifact/model state.

### MEDIUM 4 - "Market rank" still depends on manual tax rate

This was a locked decision: `tax_rate` stays manual ([reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:425](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\reviews\codex\claude_gold_dial_and_fundamentals_plan_v2.md:425)). The implementation encodes this with `MANUAL_ONLY_FINANCIAL_FIELDS = {"tax_rate"}` ([golden_vector/fundamentals/resolution.py:13](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\fundamentals\resolution.py:13)). Official rank eligibility then requires the whole financial layer to be `OK` ([golden_vector/screening/pipeline.py:519](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\screening\pipeline.py:519)).

This is logical, but the label "Market" can be slightly misleading: it means "market/Yahoo financial statements where available, with manual tax rate because we deliberately do not trust pulled tax rates." A beginner user may interpret "Market" as 100% market-sourced.

Concrete fix:

- Add a short UI hint or backend note: "Market rank uses Yahoo statement fields; tax rate remains your manual input."
- Do not auto-pull tax rate unless the loss-year guard is implemented.

### LOW 1 - Difference-only sort is implemented in serve, but only from backend columns

The plan allows serve to filter/sort using backend-emitted columns. The current implementation sorts `differences_only` by `max_divergence_pct` and ticker in `overview_tool_b.py` ([golden_vector/serve/overview_tool_b.py:164](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\serve\overview_tool_b.py:164)). This is acceptable because the UI does not compute divergence itself.

I would keep this as-is for now. If the same view appears in CLI/export later, move the sort into a shared backend function to avoid drift.

### LOW 2 - Official artifact publish is optional, not all-or-nothing with main refresh

Official fundamentals are deliberately optional (`required_for_complete=False`) in model state ([golden_vector/app/model_state.py:391](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\app\model_state.py:391)). The fetch stage writes raw/official aliases before republishing model state ([golden_vector/fundamentals/fetch.py:75](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\fundamentals\fetch.py:75), [golden_vector/fundamentals/fetch.py:102](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\fundamentals\fetch.py:102), [golden_vector/cli.py:780](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\golden_vector\cli.py:780)).

Because readers resolve through model state first, the current app remains coherent when a model-state exists. But the latest aliases can advance independently from the manifest if model-state publish fails after artifact writes. That is acceptable only because official fundamentals are optional and not part of the all-or-nothing core model publish. This should remain documented; do not copy this pattern for required artifacts.

## Test Coverage Assessment

Strong coverage exists for:

- Raw statement round-trip and storage: [tests/test_fundamentals_fetch.py:30](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_fundamentals_fetch.py:30)
- Currency conversion before `/1e6`: [tests/test_fundamentals_fetch.py:56](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_fundamentals_fetch.py:56)
- Missing debt leg: [tests/test_fundamentals_fetch.py:96](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_fundamentals_fetch.py:96)
- Per-ticker fetch failure isolation: [tests/test_fundamentals_fetch.py:183](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_fundamentals_fetch.py:183)
- Partial fetch writes run-stamped-only artifacts: [tests/test_fundamentals_fetch.py:221](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_fundamentals_fetch.py:221)
- Tool B Market-vs-Ours backend output: [tests/test_tool_b_pipeline.py:467](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_tool_b_pipeline.py:467)
- Workspace Tool B serve arithmetic guard: [tests/test_workspace_app.py:1987](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_workspace_app.py:1987)
- Candidate Finder scenario no-write injection: [tests/test_candidate_finder_data.py:430](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_candidate_finder_data.py:430)
- Scenario cache keying: [tests/test_candidate_finder_data.py:572](C:\Users\Emanuel\code\Golden-Vector\.claude\worktrees\m1-gold-dial\tests\test_candidate_finder_data.py:572)

Missing tests I would add:

- Missing cash leg -> `net_debt_musd` is `MISSING`.
- Candidate Finder scenario with official fundamentals injected.
- Official-fundamentals age/status rendered in a user-facing status page.
- If retention remains append-only, an explicit test or doc lock that raw fundamentals are intentionally preserved outside normal pruning.

## Architecture Judgment

**Did we build this as best as we could?**

Not quite. The broad architecture is the right one, but the net-debt missing-cash bug means the official fundamentals mapper is not yet as safe as it should be. For a financial tool, a plausible wrong leverage number is worse than a blank one.

**Is it infrastructure we can build on?**

Yes, after the high-severity mapper fix. The foundations are correct:

- Compute in backend, serve reads/formats.
- Scenario runs do not become current state.
- Canonical runs are spot-priced and dated.
- Official pulled data is not mixed into manual inputs.
- Raw vendor data is retained.
- Mapped official data is versioned and schema-checked.
- Model-state reads resolve through the manifest.
- Candidate Finder scenario path is side-effect free.

**What I would fix before merging onward:**

1. Fix missing-cash net debt handling.
2. Pass official fundamentals into Candidate Finder scenario Tool B recomputes.
3. Add a clear official-fundamentals freshness/status surface for the user.
4. Decide/document raw fundamentals retention.

After those, I would be comfortable calling this a strong foundation for the next predictive/backtesting work.
