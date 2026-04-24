# Codex Review: Tool B Parity + Parameters Milestone

Date: 2026-04-24  
Reviewer: Codex  
Mode: Read-only implementation review

## Summary Verdict

**READY WITH MINOR CHANGES**

The milestone mostly landed well.

What is clearly working:

- `ARMN -> ARIS.TO` is now clean in the universe
- per-ticker jurisdiction tiers are centralized and synced
- the `/tool-b` workspace now shows the four scenario columns clearly
- the live parameter panel works and the in-memory Tool B math matches the persistent pipeline
- the suite is green at **251 passed**

The main issue I would not wave away is this:

- Step 4 kept `compute_tool_b_score(...)` textually unchanged, but it still changed the **meaning** of `best_upside_pct` by shrinking the `max(...)` pool from 6 scenarios to 4

That is not a runtime break, but it **is** a product-level ranking change. It should be either:

- explicitly accepted and documented, or
- fixed before the Step 3 backfill makes the ranking shifts much more visible

---

## Step Verdicts

| Step | Verdict | Notes |
|---|---|---|
| Step 1 (`f5c32f7`) | `LANDED CORRECTLY` | `ARIS.TO` is now the active canonical symbol and the universe comments explain why |
| Step 2 (`464106b`) | `LANDED WITH MINOR ISSUES` | Centralized mapping and tier ownership landed well; sync script is good for the current file shape but not very defensive against future YAML layout drift |
| Step 4 (`3405aa1`) | `LANDED WITH MINOR ISSUES` | Four-scenario parity work landed, but the score semantics still changed indirectly through `best_upside_pct` |
| Step 5 (`06c1c80`) | `LANDED WITH MINOR ISSUES` | Override panel and shared math seam are good; one validation edge and one missing regression test remain |
| Self-review (`b7194d2`) | `LANDED WITH MINOR ISSUES` | Claude fixed real things, but missed the hidden score drift and did not add a regression test for the hidden-override carry-through fix |

---

## Findings

### `P1` Step 4 only partially honored the “ranking unchanged” correction

**Where**

- [golden_vector/screening/targets.py:86](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/targets.py:86)
- [golden_vector/screening/targets.py:91](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/targets.py:91)
- [golden_vector/screening/verdicts.py:26](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/verdicts.py:26)

**What happened**

Claude kept `compute_tool_b_score(...)` calling `best_upside_pct`, which is what the prior plan correction asked for.

But `best_upside_pct` is now:

- max of **4** scenarios
- not max of the old **6** scenarios

because EV/EBITDA-derived targets were removed from the pool in [targets.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/targets.py:91).

So the score formula is unchanged only **syntactically**.  
Its input semantics changed.

**Why it matters**

This means Step 4 is still making a ranking decision, just indirectly.

That may be the right product move. But it is **not** the same as “no ranking change this milestone.”

**My view**

This is not severe enough to call the milestone broken, but it should be resolved before Step 3 backfill, otherwise the ranking shifts after 50+ new populated rows will be harder to interpret.

**Fix shape**

Pick one explicitly:

1. accept the new “max of four” score semantics and document it as a real product change, or
2. keep a legacy six-scenario helper alive for score purposes until ranking philosophy is redesigned properly

Right now the code is between those two positions.

---

### `P2` Override validation still accepts a 100% jurisdiction discount

**Where**

- [golden_vector/serve/screening_overrides.py:114](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/screening_overrides.py:114)
- [golden_vector/serve/screening_overrides.py:115](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/screening_overrides.py:115)
- [golden_vector/serve/screening_overrides.py:183](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/screening_overrides.py:183)

**What happens**

The parser rejects discounts `> 100%`, but it still accepts exactly `100%`:

- `tier2_discount=100` -> `1.0`

That then flows into:

- zero target P/E multiple
- zero scenario target prices

which is not a realistic Tool B parameter choice.

**Why it matters**

This is a small but real validation gap.  
The UI says these are screening parameters, not “destroy the model” knobs.

**Fix shape**

Reject jurisdiction discounts `>= 1.0` after percent normalization.

Also add one test for:

- `tier2_discount=100` -> `400 Bad Request`

---

### `P2` The shared-math seam is good, but the repo still lacks a direct equivalence regression test

**Where**

- [golden_vector/screening/pipeline.py:167](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/pipeline.py:167)
- [tests/test_screening_overrides.py:179](C:/Users/Emanuel/code/Golden-Vector/tests/test_screening_overrides.py:179)
- [tests/test_screening_overrides.py:217](C:/Users/Emanuel/code/Golden-Vector/tests/test_screening_overrides.py:217)

**What I verified manually**

I ran a live equivalence check against the current repo state:

- `compute_tool_b_in_memory(...)`
- `execute_tool_b_pipeline(...)`

with the same inputs, same snapshot, same source run id

Result:

- **equal True**
- **60 rows vs 60 rows**

So the seam itself is good.

**What is missing**

There is still no repo test that locks this equality.  
The new tests check:

- blank manual-data behavior
- gold-price sensitivity

but not:

- identical outputs for identical inputs across persistent vs in-memory paths

**Why it matters**

This is the exact seam most likely to drift later.

**Fix shape**

Add one focused regression test:

- same app config
- same manual data
- same normalized market snapshot
- same gold price
- same snapshot metadata
- compare the resulting DataFrames after sorting

This should live in `tests/test_screening_overrides.py` or a dedicated screening-pipeline test.

---

### `P3` Step 2 sync script is correct for the current file, but still brittle as a general YAML rewriter

**Where**

- [scripts/sync_universe_tiers_from_excel.py:102](C:/Users/Emanuel/code/Golden-Vector/scripts/sync_universe_tiers_from_excel.py:102)
- [scripts/sync_universe_tiers_from_excel.py:115](C:/Users/Emanuel/code/Golden-Vector/scripts/sync_universe_tiers_from_excel.py:115)
- [scripts/sync_universe_tiers_from_excel.py:124](C:/Users/Emanuel/code/Golden-Vector/scripts/sync_universe_tiers_from_excel.py:124)

**What is good**

- canonical ownership is now stated clearly in the docstring
- centralized friend ticker mapping is in place
- dry-run output is readable
- current `universe.yaml` shape is handled correctly

I confirmed the script now reports `0 ticker(s) will change`, which is what we want after the apply.

**What is still fragile**

The line-based state machine:

- replaces existing `jurisdiction_tier` keys
- but does not insert one if missing
- and assumes `ticker:` appears before `jurisdiction_tier:` in each block

That is acceptable for the current controlled file, but it is not a general-purpose YAML updater.

**Fix shape**

No urgent rewrite needed.

I would only:

- tighten the docstring to say it assumes the current repo layout, or
- add one narrow test fixture for “missing jurisdiction_tier key” so future users know the limitation

---

### `P3` The self-review fix for carried override params is not regression-tested

**Where**

- [golden_vector/serve/workspace.py:1114](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:1114)
- [golden_vector/serve/workspace.py:1297](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:1297)

**What happened**

Claude said he fixed the bug where:

- `/tool-b?gold_price=4500`
- then typing a search like `NEM`
- would silently drop the active override

The code fix is there:

- hidden inputs are rendered into the filter form

But I could not find a test that locks this behavior.

**Why it matters**

This is exactly the kind of small UX regression that comes back later.

**Fix shape**

Add one workspace test:

- request `/tool-b?gold_price=4500`
- inspect rendered search form
- assert hidden `gold_price=4500` input is present

That is enough.

---

## Layer 1: Did The Earlier Plan Corrections Land?

| Prior correction | Status | Verdict |
|---|---|---|
| `P1.3` ranking unchanged | `best_upside_pct` still feeds score, but its meaning changed because EV/EBITDA left the max pool | **Landed with minor issues** |
| `P2.1` centralized ticker mapping | `FRIEND_TICKER_MAP` is centralized in [scripts/friend_excel_import.py](C:/Users/Emanuel/code/Golden-Vector/scripts/friend_excel_import.py) | **Landed correctly** |
| `P2.2` jurisdiction ownership explicit | script docstring now clearly says `config/universe.yaml` is the canonical Tool B tier source | **Landed correctly** |
| `P2.3` named-scenario verification | scenario columns/tests exist, but repo tests still do formula checks more than workbook-row parity locks | **Landed with minor issues** |
| `P3` fewer pauses | current implementation cadence is consistent with the repo’s low-interruption style | **Landed correctly** |

---

## Layer 2: Independent Code Review Answers

### 1. Is `compute_tool_b_in_memory` truly identical math to the persistent path?

**Yes.**

I verified this manually on the live repo state by running both paths with identical inputs.  
They produced identical sorted DataFrames across **60 rows**.

The implementation shape is clean:

- shared `_merge_inputs_for_tool_b(...)`
- shared `_build_tool_b_rows(...)`
- shared `_frame_from_rows(...)`

That is the right seam.

### 2. Override parsing edge cases

- `_percent_to_fraction` is safe for the current parameter space
- blank params are ignored correctly
- duplicate query keys using the first value is acceptable here
- **100% tier discounts should be rejected**, not accepted

So this area is mostly good, with one small fix.

### 3. Is the broad fallback catch in `_resolve_tool_b_frame` too broad?

**No, not for this workspace surface.**

Why I think it is acceptable:

- the page does **not** silently swallow the error
- it falls back to persisted parquet
- and it shows a visible banner:
  - “Could not recompute with overrides … showing the last persisted Tool B snapshot.”

That is an acceptable tradeoff for a user-facing scenario page.

### 4. Performance of loading the latest foundation snapshot on every override request

**Acceptable for v1.**

At current scale:

- 60 tickers
- simple math
- no frontend framework

this is fine.

I would not add caching yet.

### 5. Is the sync script state machine correct?

**Correct for the current file.**

But not robust enough to call general-purpose.

So:

- fine to ship
- not worth rewriting now
- but document the assumption or add one small shape test

### 6. CSS collision?

I did not find an actual conflict.

This part looks fine.

---

## Layer 3: Missed Parity Issues

### Did Step 4 regress anything obvious from the friend Excel?

I did **not** find a new arithmetic regression in the four published scenario columns.

### Is the scenario banner truthful?

**Yes.**

It really is recomputing from:

- local manual data
- latest foundation market snapshot

without writing YAML or parquet.

### Did shrinking the `best_upside_pct` pool from 6 to 4 matter?

**Yes, conceptually.**

That is the one parity-adjacent issue I think still matters.

Even though `compute_tool_b_score(...)` was left alone, the score input changed in meaning.

This should be made explicit before Step 3 backfill.

### 35 tier changes vs the earlier 33

No anomaly jumps out now.

The current dry-run returns:

- `0 ticker(s) will change`

which is what we want after the sync.

The count difference is plausibly explained by:

- `ARMN -> ARIS.TO`
- and a slightly broader final sync pass than the earlier review counted

I do not see evidence of a bad mapping here.

---

## Self-Review Assessment

Claude’s self-review caught useful things:

1. dead helper cleanup
2. hidden-input carry-through bug
3. stale `ToolBOutput` contract

Those were worth fixing.

But the self-review missed the one thing I think matters more:

- the hidden semantic change in `best_upside_pct` feeding the score

So my answer is:

- Claude did **not** miss a runtime bug of the first order
- but he **did** miss the most important product-semantics issue from this cycle

---

## Should Step 3 Happen Now?

**Not quite yet.**

I would do one small decision/fix first:

- either explicitly accept that `best_upside_pct` is now “max of four”
- or freeze score semantics another way before the big backfill

Why:

once Step 3 imports 50+ more populated rows, any ranking shifts become much harder to disentangle from:

- backfilled data
- new tiers
- and changed scenario max logic

So my recommendation is:

1. settle the score-semantics issue
2. add the direct in-memory-vs-persistent regression test
3. then do Step 3

That is a small delay, not a big rework.

---

## Bottom Line

This milestone is in good shape.

The code works, the math seam is clean, and the workspace parameter panel is a real improvement.

The one thing I would not gloss over is:

- the score formula did not stay as unchanged as the milestone narrative implies

Resolve that explicitly, add one or two tight regression tests, and then the Step 3 backfill is ready to do safely.
