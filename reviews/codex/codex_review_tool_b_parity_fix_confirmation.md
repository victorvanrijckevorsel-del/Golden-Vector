# Codex Review: Tool B Parity Fix Confirmation

Date: 2026-04-24  
Reviewer: Codex  
Mode: Read-only confirmation review

## Summary Verdict

**READY WITH MINOR CHANGES**

The five requested fixes mostly landed cleanly.

What matters most is now true:

- the `best_upside_pct` semantic change is explicit and tested
- `100%` jurisdiction discounts are rejected
- the in-memory Tool B path is now locked against the persistent path by a real equality test
- the hidden-override carry-through bug now has a regression test

I did find one small net-new issue:

- the tier-sync script still advertises a `--dry-run` flag in its top-level usage text, but the parser only supports bare invocation for dry-run and `--apply` for write mode

That is a documentation mismatch, not a blocker.

---

## Layer 1: Did Each Fix Actually Land?

| Finding | Status | Verdict |
|---|---|---|
| 1. `best_upside_pct` semantic shift must be accepted + documented or otherwise fixed | Doc + test both landed | **LANDED CORRECTLY** |
| 2. Reject `100%` jurisdiction discount | Guard + boundary tests landed | **LANDED CORRECTLY** |
| 3. Add repo test locking `compute_tool_b_in_memory == execute_tool_b_pipeline` | Equality test landed | **LANDED CORRECTLY** |
| 4. Sync-script brittleness should at least be documented honestly | Mostly landed, but one doc mismatch remains | **LANDED WITH MINOR ISSUES** |
| 5. Hidden-override carry-through needs a regression test | Test landed | **LANDED CORRECTLY** |
| Self-review catch: clearer 100%-discount error message | Message + tests landed | **LANDED CORRECTLY** |

---

## Findings

### `P3` The sync script still documents a `--dry-run` flag that does not exist

**Where**

- [scripts/sync_universe_tiers_from_excel.py:14](C:/Users/Emanuel/code/Golden-Vector/scripts/sync_universe_tiers_from_excel.py:14)

**What I checked**

I ran:

- `python -m scripts.sync_universe_tiers_from_excel`

and confirmed that is the real dry-run path.

The script parser only supports:

- no args -> dry-run
- `--apply` -> write

But the usage text still says:

- `python -m scripts.sync_universe_tiers_from_excel --dry-run`

and that command is not recognized.

**Why it matters**

This is small, but it is exactly the sort of operator confusion that shows up later as:

- “the script is broken”

when the implementation is actually fine.

**Fix shape**

Update the usage text at the top of the file so it matches the real CLI:

- `python -m scripts.sync_universe_tiers_from_excel`
- `python -m scripts.sync_universe_tiers_from_excel --apply`

---

## Direct Answers To The Requested Checks

### Finding 1: `best_upside_pct` semantics

**Cleanly resolved.**

I verified the code and tests now say the same thing:

- [golden_vector/screening/targets.py:86](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/targets.py:86)
- [golden_vector/screening/targets.py:91](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/targets.py:91)
- [golden_vector/screening/verdicts.py:35](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/verdicts.py:35)
- [tests/test_screening_targets.py:75](C:/Users/Emanuel/code/Golden-Vector/tests/test_screening_targets.py:75)

The current behavior is explicit:

- `best_target_price_usd` = max of the four canonical scenarios
- `best_upside_pct` = upside from that max-of-four target
- `tool_b_score` still consumes that value

I also checked for other active callers. In the live Tool B path, the only score consumer is still:

- [golden_vector/screening/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/pipeline.py)

There are still legacy references in `golden_vector/combined/*`, but that backend is already de-scoped, so I do **not** treat those as an active contradiction.

### Finding 2: `100%` discount rejection

**Cleanly resolved.**

I directly checked:

- `tier2_discount=100` -> rejected
- `tier2_discount=1.0` -> rejected
- `tier2_discount=99` -> accepted as `0.99`

The current guard in:

- [golden_vector/serve/screening_overrides.py:125](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/screening_overrides.py:125)

is correct for v1.

I do **not** see a legitimate Tool B use case where a `100%` jurisdiction discount should be allowed. That would collapse target P/E multiples to zero and make the scenario mathematically meaningless.

### Finding 3: equivalence regression test

**Cleanly resolved.**

The new equality test is the right shape:

- [tests/test_tool_b_pipeline.py:414](C:/Users/Emanuel/code/Golden-Vector/tests/test_tool_b_pipeline.py:414)

It compares sorted DataFrames from:

- `execute_tool_b_pipeline(...)`
- `compute_tool_b_in_memory(...)`

with aligned metadata, including `source_run_id`.

The full suite passed at **257**, so the equality holds on this machine too.

I do not see a false-positive problem from persistence side effects here, because the comparison is on the returned DataFrames, not on re-read artifacts.

### Finding 4: sync script docstring / assumptions

**Mostly resolved, but not perfectly.**

Good part:

- the layout-assumptions block is much better now:
  - [scripts/sync_universe_tiers_from_excel.py:108](C:/Users/Emanuel/code/Golden-Vector/scripts/sync_universe_tiers_from_excel.py:108)

Remaining issue:

- the usage text still mentions the nonexistent `--dry-run` flag

One more subtle point:

the docstring says malformed future layouts will “silently skip” rows, but if a `jurisdiction_tier:` line were moved before its own `- ticker:` line **after a previous ticker block**, the state machine could still be holding the previous ticker in memory. So the real failure mode is not always a clean skip; it can be misassociation.

That is not a current repo bug because the file shape is controlled and I confirmed the current dry-run is sane. But the docstring is still slightly cleaner than the actual state machine.

So this area is:

- acceptable for now
- not blocking
- but not fully perfect

### Finding 5: hidden-override carry-through test

**Resolved.**

The new test:

- [tests/test_workspace_app.py:2060](C:/Users/Emanuel/code/Golden-Vector/tests/test_workspace_app.py:2060)

is good enough for this UI layer.

It isolates the filter form and checks that active overrides appear as hidden inputs.

Would an HTML parser be more robust than regex? Yes, in theory.  
Do I think that matters here? No. The form shape is simple and the current test is good enough.

### Self-review catch: clearer error message

**Resolved.**

The new message in:

- [golden_vector/serve/screening_overrides.py:125](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/screening_overrides.py:125)

is much clearer.

Direct check results:

- `100` -> `got 100.0, interpreted as 100%`
- `1.0` -> `got 1.0, interpreted as 100%`

That is clear enough for users.

I do not think the `0.995` rounding point is worth solving now. That would be over-engineering for this surface.

---

## Layer 2: Did Claude Miss Anything Else?

### 1. Is the “max-of-4 is more faithful to the friend’s Excel” argument airtight?

**Strong enough, yes.**

Not mathematically “airtight” in the abstract, but strong enough for the product decision.

Reason:

- the friend’s workbook exposes the four canonical scenarios
- the EV/EBITDA-derived targets were Python-only additions

So narrowing the score input to the same visible scenario family is more honest than keeping invisible Python-only EV/EBITDA scenarios in the max pool.

Could there be a ticker where EV/EBITDA was the “right” anchor? Yes, analytically.  
But that would be a **different product choice**, not an Excel-parity one.

### 2. Is Step 3 now ready?

**Yes.**

This is the main answer:

- **Step 3 is now ready to execute**

The only thing I found in this confirmation pass is a small doc mismatch in the tier-sync script. That does not block the backfill milestone.

### 3. What about the backup SQLite file?

**Keep it until Step 3 lands cleanly.**

That is the right tradeoff.

Once:

- Step 3 import is done
- smoke checks pass
- and Emanuel is happy with the resulting Tool B outputs

then clean it up.

### 4. README / docs cleanup now or later?

**Later.**

I would defer the broader docs sweep until after Step 3, so you only do one cleanup pass instead of two.

---

## What I Verified Directly

- `python -m pytest -q` -> **257 passed**
- `parse_query_overrides({"tier2_discount": ["100"]})` -> rejected with clear “interpreted as 100%” message
- `parse_query_overrides({"tier2_discount": ["1.0"]})` -> same
- `parse_query_overrides({"tier2_discount": ["99"]})` -> accepted as `0.99`
- `python -m scripts.sync_universe_tiers_from_excel` -> dry-run works and reports `0 ticker(s) will change`

---

## Bottom Line

This fix pass did what it needed to do.

The only thing I would still correct is:

- the stale `--dry-run` usage text in the sync script

Everything else I checked is in good shape, and **yes, Step 3 is now ready to execute**.
