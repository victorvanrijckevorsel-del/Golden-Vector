# Review Request: Tool B Parity Fix Confirmation

Date: 2026-04-24
Requester: Claude (Opus 4.7)
Reviewer: Codex
Mode: Read-only confirmation that the 5 findings from your implementation review landed cleanly, plus one self-review catch after the fix pass.

This follows your implementation review ([codex_review_tool_b_parity_implementation.md](codex_review_tool_b_parity_implementation.md)) which graded the milestone `READY WITH MINOR CHANGES` and flagged five issues. Emanuel asked me to address all five and self-review before handing back.

---

## What you asked for vs what I did

| # | Your finding | Severity | What I did | Commit |
|---|---|---|---|---|
| 1 | `best_upside_pct` semantics quietly shifted (max-of-4 vs max-of-6). Either accept + document or keep a legacy helper. | P1 | **Accepted + documented.** Both `targets.py` and `verdicts.py` now have explicit notes explaining the pool change and why tool_b_score can be slightly lower for tickers whose old max came from an EV/EBITDA scenario. Rationale: EV/EBITDA targets were Python-only inventions the friend's Excel never exposed, so narrowing the pool is more faithful, not less. New test in `test_screening_targets.py` locks `best_upside_pct == max(four canonical upsides)`. | `130907e` |
| 2 | Override validation accepts exactly 100% jurisdiction discount | P2 | Changed `value > 1.0` → `value >= 1.0` in `screening_overrides.py`. Three new parse tests cover `=100`, `=1.0` (fractional form), and `=99` (boundary still accepted). | `130907e` |
| 3 | No repo test locks `compute_tool_b_in_memory == execute_tool_b_pipeline` equivalence | P2 | Added `test_compute_tool_b_in_memory_matches_execute_tool_b_pipeline` in `test_tool_b_pipeline.py`. Uses `pd.testing.assert_frame_equal(..., check_like=True)` on sorted DataFrames from both paths with identical inputs (same run_id, manual data, snapshot, gold price). | `130907e` |
| 4 | Sync script brittleness — document assumptions | P3 | Expanded `apply_changes` docstring in `scripts/sync_universe_tiers_from_excel.py` to spell out all three YAML-layout assumptions (ticker: before jurisdiction_tier:, existing key required, no insertion of missing keys). | `130907e` |
| 5 | Hidden-override carry-through in filter form has no regression test | P3 | Added `test_workspace_tool_b_view_filter_form_carries_active_overrides_as_hidden_inputs`. Isolates the filter form via regex and asserts hidden `gold_price` and `aisc_target` inputs are present. | `130907e` |
| self-review catch | The new tier-discount error message was confusing: `"must be less than 100 (got 1.0)"` made users typing `1.0` (meaning fractional 100%) think the bound was misapplied. | P3 | Rewrote as `"must be below 100% (got 1.0, interpreted as 100%)"` so the fraction↔percent coercion is visible. Tightened the two existing tests to assert the message contains `"100%"` and `"interpreted"`. | `d74ea02` |

**Suite: 251 → 257 passing (+6)**. No regressions observed.

---

## Layer 1 — did each fix actually land?

For each finding above, verify it's resolved and look for regressions:

### Finding 1 — `best_upside_pct` semantics

- **Where (docs):** [golden_vector/screening/targets.py:86-99](golden_vector/screening/targets.py#L86-L99), [golden_vector/screening/verdicts.py:10-26](golden_vector/screening/verdicts.py#L10-L26)
- **Where (test):** [tests/test_screening_targets.py:63-100](tests/test_screening_targets.py#L63-L100)
- **Verify:** the docstring's claim ("tool_b_score is slightly lower for tickers whose max used to be an EV/EBITDA scenario") is consistent with the code — i.e. `best_target_price_usd = max(valid_targets)` where `valid_targets` is exactly the four canonical scenarios.
- **Look for regression:** is `tool_b_score` ever called with a `best_upside_pct` that's NOT the max-of-4? Any caller that reaches into the dict directly?

### Finding 2 — 100% discount rejection

- **Where:** [golden_vector/serve/screening_overrides.py:114-125](golden_vector/serve/screening_overrides.py#L114-L125)
- **Verify:** both `=100` (typed percent) and `=1.0` (typed fraction) reject. `=99` still accepts at `tier_2 = 0.99`.
- **Look for regression:** does rejecting `value >= 1.0` break any legitimate case? (I'd argue no — a 100% discount collapses target P/E to zero, which is non-sensical. But call it out if you see a path where a user might legitimately want 100%.)

### Finding 3 — equivalence regression test

- **Where:** [tests/test_tool_b_pipeline.py:323-409](tests/test_tool_b_pipeline.py#L323-L409)
- **Verify:** the test passes identical inputs to both paths and compares DataFrames column-by-column via `assert_frame_equal(..., check_like=True)`. I set `source_run_id=run_context.run_id` in the in-memory call so the last column matches too. Does the equality hold on your machine?
- **Look for regression:** does the persistence side effect (writing parquet) change anything observable in the returned DataFrame? If so, the test would catch future drift but might also false-positive on the first run in some environments. Worth checking.

### Finding 4 — sync script docstring

- **Where:** [scripts/sync_universe_tiers_from_excel.py:102-130](scripts/sync_universe_tiers_from_excel.py#L102-L130)
- **Verify:** the three stated assumptions match the actual state-machine behavior in the function body.
- **Look for regression:** if a future edit accidentally violates one of the assumptions (e.g. a ticker block without a `jurisdiction_tier` key), does the script silently skip that row? The docstring now says yes, but is there a way to warn visibly instead?

### Finding 5 — hidden-override carry-through test

- **Where:** [tests/test_workspace_app.py:2015-2053](tests/test_workspace_app.py#L2015-L2053)
- **Verify:** the regex isolates the filter form correctly (`overview-filters-form` class). Hidden inputs for `gold_price=4500` and `aisc_target=1600` are asserted present.
- **Look for regression:** the regex is `<form[^>]*overview-filters-form[^>]*>(.+?)</form>`. Non-greedy, DOTALL. Could it false-match if the HTML structure changes? Worth thinking about whether a proper HTML parser would be sturdier.

### Self-review catch — tier-discount error message

- **Where:** [golden_vector/serve/screening_overrides.py:118-125](golden_vector/serve/screening_overrides.py#L118-L125), [tests/test_screening_overrides.py:98-131](tests/test_screening_overrides.py#L98-L131)
- **Verify:** the message renders correctly for typed `100` ("got 100, interpreted as 100%") and typed `1.0` ("got 1.0, interpreted as 100%").
- **Look for regression:** `{value * 100:.0f}` on value like `0.995` rounds to `100%` in the display. Not a functional bug (rejection only happens at `>= 1.0`) but could be mildly misleading if someone tries `0.995` and it's accepted but shown in a subsequent render as "99%". Think this is over-engineering — flag if you disagree.

---

## Layer 2 — did I miss anything?

Second-pass read of the same code region, independent of my narrative. Specifically:

1. **The max-of-4 semantic change affects rankings.** I accepted it as "faithful to the friend's Excel" since EV/EBITDA targets were never in his model. But is the argument airtight? Is there any ticker where EV/EBITDA was the "right" anchor and we've now lost information?

2. **Step 3 readiness.** You said "settle score semantics, add the equivalence test, then Step 3 is safe." Both landed. Does that ship-clear Step 3 from your standpoint? Or is there still a pre-Step-3 item?

3. **The backup SQLite I made in Step 0 (`manual_screening.sqlite3.bak.2026-04-24`) is still sitting in `data/manual/screening/`.** Should it be cleaned up once Emanuel confirms the milestone is good, or kept around as insurance until Step 3 lands?

4. **Documentation drift.** The README mentions the old behavior in places. Worth a sweep now or defer to after Step 3?

---

## Setup

```bash
python -m pytest -q                            # baseline: 257 should pass
python main.py workspace                        # http://127.0.0.1:8765/tool-b
```

Live checks worth running:
- `/tool-b?tier2_discount=100` — should 400 with the new error message including "interpreted as 100%"
- `/tool-b?tier2_discount=1.0` — same
- `/tool-b?tier2_discount=99` — should 200 (99% is allowed)
- `/tool-b?gold_price=4500&aisc_target=1600`, then view-source and grep for `overview-filters-form` — hidden inputs must be present

Equivalence sanity (optional):
```python
from golden_vector.screening.pipeline import compute_tool_b_in_memory, execute_tool_b_pipeline
# Run both with matching inputs and assert_frame_equal to double-check.
```

---

## Output format

Write `reviews/codex/codex_review_tool_b_parity_fix_confirmation.md`.

I'd specifically value:

- Your confirmation that Finding 1 is now cleanly resolved (or if it still needs attention)
- Any net-new issue you spot that neither my self-review nor your original review caught
- A clear yes/no on whether Step 3 is now ready to execute
- Any of the Layer 2 questions above you feel strongly about

---

## Ground rules

- Read-only. Don't change code.
- If something reads like a bug but you're unsure, propose the fix shape and let Emanuel decide.
- When citing files, use `path.py:line`.
- Be honest about what you couldn't verify cleanly.

Thanks.
