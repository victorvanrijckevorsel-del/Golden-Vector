
# Codex Review: Phase 1A Provenance Closeout

Date: 2026-04-23  
Reviewer: Codex  
Mode: Read-only review of code + plan v3  
Review brief: [claude_review_request_phase_1a_provenance_closeout.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_review_request_phase_1a_provenance_closeout.md)

## Verdict

**READY WITH MINOR CHANGES**

Phase 1A is mostly correct and the scope discipline is good, but one real plan-vs-code mismatch remains in the `FOUNDATION_MISSING` path, and one of the fallback-card test claims is stronger than the tests actually prove.

---

## Findings First

### `P1` `FOUNDATION_MISSING` does not currently honor the v3 suppressed-panel contract

Where in plan:
- [claude_workspace_visualization_layer_plan_v3.md:65](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:65)
- [claude_workspace_visualization_layer_plan_v3.md:80](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:80)

Where in code:
- [latest_data.py:86](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app/latest_data.py:86)
- [workspace.py:344](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:344)
- [workspace.py:563](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:563)
- [workspace.py:785](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:785)

Problem:
- v3 says the `FOUNDATION_MISSING` state should suppress the foundation-backed panels and replace them with visible fallback cards.
- In the actual code, missing foundation manifest causes `load_latest_foundation_snapshot(...)` to raise first. That sets `tool_a_detail.foundation_error`, and `_render_visual_panels(...)` returns one generic `Tool A Detail` error panel before it reaches the per-panel suppression branch.

Why it matters:
- This is exactly one of the four documented alignment states.
- Right now only `FOUNDATION_AHEAD` gets the full ?three named suppressed panels + volatility still visible? behavior that v3 promises.

Required correction:
- Make the `FOUNDATION_MISSING` path render the same per-panel suppressed-card treatment as the other non-aligned states, or narrow the plan so it no longer claims that behavior.
- Add a direct workspace test for `FOUNDATION_MISSING`.

### `P2` The new tests do not fully prove the fallback-card bar claimed in v3 and the review brief

Where in plan / brief:
- [claude_workspace_visualization_layer_plan_v3.md:83](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:83)
- [claude_review_request_phase_1a_provenance_closeout.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_review_request_phase_1a_provenance_closeout.md)

Where in tests:
- [test_workspace_app.py:418](C:/Users/Emanuel/code/Golden-Vector/tests/test_workspace_app.py:418)
- [test_workspace_app.py:479](C:/Users/Emanuel/code/Golden-Vector/tests/test_workspace_app.py:479)

Problem:
- `T14` proves the three suppressed-card titles are present, the page-level alignment notice is present, the CLI suggestion appears at least three times, and the volatility panel remains visible.
- But it does **not** explicitly assert that each suppressed card contains its own reason sentence, which is part of the claimed `T23` fallback standard.
- The four documented alignment states are also not all tested. `ALIGNED` and `FOUNDATION_AHEAD` are covered. `FOUNDATION_MISSING` and `TOOL_A_MISSING_REFRESH` are not.

Required correction:
- Add one explicit assertion that a suppressed-card reason string appears in the panel body, not just the page-level notice.
- Add tests for at least:
  - `FOUNDATION_MISSING`
  - `TOOL_A_MISSING_REFRESH`

### `P3` The live repo structural latest parquet is stale relative to the new Phase 1A schema

Where:
- [data/intermediate/tool_a_structural/tool_a_structural_latest.parquet](C:/Users/Emanuel/code/Golden-Vector/data/intermediate/tool_a_structural/tool_a_structural_latest.parquet)

Observation:
- The current live `tool_a_structural_latest.parquet` in the repo does **not** carry `source_run_id` yet.
- The code and temp-path persistence test are correct, so this looks like a stale artifact, not a code bug.

Why it matters:
- The implementation is code-correct, but the live latest structural artifact has not yet been regenerated under the new schema.

Required correction:
- Re-run `python main.py tool-a` before relying on the live latest structural parquet for any provenance-aware UI work.

---

## A. Plan v3 fidelity to the v2 review

### Correction 1: commit to suppress (not banner) live-recompute panels on foundation-ahead
- v3 status: **fully addressed**
- Evidence:
  - [claude_workspace_visualization_layer_plan_v3.md:49](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:49)
  - [claude_workspace_visualization_layer_plan_v3.md:65](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:65)

### Correction 2: provenance rule explicitly covers scatter, up-down beta, exploratory ladder, gold overlay
- v3 status: **fully addressed**
- Evidence:
  - [claude_workspace_visualization_layer_plan_v3.md:41](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:41)

### Correction 3: `source_run_id` and `snapshot_refresh_run_id` named separately
- v3 status: **fully addressed**
- Evidence:
  - [claude_workspace_visualization_layer_plan_v3.md:31](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:31)

### Correction 4: lens wording tightened
- v3 status: **fully addressed in the document**
- Evidence:
  - [claude_workspace_visualization_layer_plan_v3.md:103](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:103)
  - [claude_workspace_visualization_layer_plan_v3.md:115](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:115)
  - [claude_workspace_visualization_layer_plan_v3.md:126](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:126)

### Correction 5: add T21 / T22 / T23
- v3 status: **fully addressed in the document**
- Evidence:
  - [claude_workspace_visualization_layer_plan_v3.md:213](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:213)
- Note:
  - Those are Phase 2 tests, so they are correctly not part of the current Phase 1A code yet.

### Correction 6: Phase 1 of broader finish plan must complete before visualization counts toward v1
- v3 status: **fully addressed**
- Evidence:
  - [claude_workspace_visualization_layer_plan_v3.md:231](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_workspace_visualization_layer_plan_v3.md:231)

Conclusion on v3 fidelity:
- **v3 correctly folds in all six corrections from the v2 review.**

---

## B. Phase 1A code vs plan v3

### 1. Schema column populated correctly
- Code status: **correct**
- Evidence:
  - [data_models.py:126](C:/Users/Emanuel/code/Golden-Vector/golden_vector/contracts/data_models.py:126)
  - [structural.py:25](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/structural.py:25)
  - [pipeline.py:147](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:147)
  - [pipeline.py:153](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:153)
  - [test_persist_tool_a.py:88](C:/Users/Emanuel/code/Golden-Vector/tests/test_persist_tool_a.py:88)
- Verified:
  - the pipeline adds `source_run_id = run_context.run_id`
  - the temp-path persisted parquet test passes
- Operational note:
  - the **live** repo latest structural parquet is stale and still lacks `source_run_id`; rerun `tool-a` to regenerate it

### 2. Alignment helper covers four documented states
- Code status: **yes, functionally**
- Evidence:
  - [workspace.py:557](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:557)
  - [workspace.py:563](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:563)
- States present:
  - `ALIGNED`
  - `FOUNDATION_AHEAD`
  - `FOUNDATION_MISSING`
  - `TOOL_A_MISSING_REFRESH`
- Reachability:
  - all four are reachable by branch logic
- Test coverage:
  - only `ALIGNED` and `FOUNDATION_AHEAD` are currently covered directly

### 3. Suppression is real, not banner
- Code status: **yes for the non-error alignment path**
- Evidence:
  - [workspace.py:799](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:799)
- Verified:
  - when `alignment != ALIGNED`, `_render_visual_panels(...)` returns suppressed cards and does not call the scatter / up-down / exploratory renderers
- Limitation:
  - `FOUNDATION_MISSING` currently short-circuits earlier via `foundation_error` and does not get the same per-panel suppression treatment

### 4. Fallback cards meet the bar
- Code status: **mostly yes**
- Evidence:
  - [workspace.py:607](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:607)
- Verified:
  - title includes `? Out of Sync`
  - reason sentence is present in the card
  - CLI suggestion is present
  - visible content exists
- Test gap:
  - current tests do not explicitly assert the per-card reason sentence

### 5. Volatility panel correctly excluded from suppression
- Code status: **yes**
- Evidence:
  - [workspace.py:818](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:818)
- Verdict:
  - this is the right choice
  - it reads only from the published Tool A row, so it remains trustworthy even when foundation-backed panels are suppressed

### 6. Page-level alignment notice appears at top of Tool A panel
- Code status: **yes**
- Evidence:
  - [workspace.py:586](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:586)
  - [workspace.py:682](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:682)

### 7. Threading is consistent
- Code status: **yes**
- Evidence:
  - [workspace.py:481](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:481)
  - [workspace.py:637](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:637)
  - [workspace.py:658](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:658)
  - [workspace.py:785](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:785)

---

## C. Tests cover the right failure modes

### T14
- Status: **exists and mostly checks the right thing**
- Evidence:
  - [test_workspace_app.py:418](C:/Users/Emanuel/code/Golden-Vector/tests/test_workspace_app.py:418)
- It correctly asserts:
  - page-level alignment notice
  - all three out-of-sync panel titles
  - CLI suggestion appears
  - volatility panel still renders
- Missing assertion:
  - per-card reason sentence

### T17
- Status: **exists and checks the right thing**
- Evidence:
  - [test_persist_tool_a.py:88](C:/Users/Emanuel/code/Golden-Vector/tests/test_persist_tool_a.py:88)
- It correctly asserts:
  - in-memory `result.structural_window_metrics` carries `source_run_id`
  - persisted parquet carries `source_run_id`
  - values match `run_context.run_id`

### Aligned baseline test
- Status: **exists and checks the right thing**
- Evidence:
  - [test_workspace_app.py:487](C:/Users/Emanuel/code/Golden-Vector/tests/test_workspace_app.py:487)
- It correctly asserts:
  - no `Out of Sync`
  - no foundation-ahead message
  - normal panel titles render

### Additional test recommendation
Add:
- direct `FOUNDATION_MISSING` test
- direct `TOOL_A_MISSING_REFRESH` test
- explicit per-card reason assertion in `T14`

---

## D. Scope discipline

### Phase 1A scope delivery
- **Mostly delivered, with one gap**
- Delivered:
  - schema extension
  - alignment helper
  - suppression for the main non-aligned path
  - visible fallback cards
  - page-level notice
  - T14
  - T17
- Gap:
  - `FOUNDATION_MISSING` does not currently use the same per-panel suppressed-card behavior promised by v3

### Phase 2 scope leakage
- **No leakage found**
- Verified:
  - no `golden_vector/serve/lenses.py`
  - no beta-history helpers yet
  - no lens picker in workspace

### Phase 1B?1E scope leakage
- **No leakage found**
- Verified:
  - source verification is still read-only table output, not editable UI
  - no overview search/filter/sort feature landed in this phase
  - no broader Tool B workflow polish appears bundled into Phase 1A

---

## Specific pushback answers

### 1. Is the alignment decision mechanism strong enough?
- **Yes, for Phase 1A**
- `snapshot_refresh_run_id` vs `foundation_manifest.refresh_run_id` is the right key for foundation-backed live panels.
- `source_run_id` is the wrong key for those panels; it is for structural-history artifacts.
- I would not require both for Phase 1A.

### 2. Is the volatility panel safe to keep rendered when alignment fails?
- **Yes**
- It is rendered from the published Tool A row, not from the foundation snapshot.
- Keeping it visible is the right tradeoff as long as the alignment notice is prominent, which it is.

### 3. Is `Out of Sync` the right wording?
- **Yes, acceptable for v1**
- It is blunt and understandable.
- I would not block on alternative wording.

### 4. Are there detail-page panels missed that read from foundation or another non-aligned source?
- I did not find additional foundation-backed Tool A panels beyond:
  - scatter
  - up/down beta
  - exploratory ladder
- Those are the right ones to suppress in Phase 1A.

### 5. Is `source_run_id: str | None = None` too quiet?
- **No, not for this phase**
- Optional is the right compatibility choice while older fixtures and stale artifacts still exist.
- Once the repo artifacts are fully refreshed, it could be tightened later if desired.

### 6. Is the suggested order for Phase 1B onward still right?
- **Yes**
- My recommendation remains:
  1. source-verification editing
  2. Tool B workflow polish
  3. notes polish
  4. overview search/filter/sort
- Then Phase 2 visualization work.

---

## Test Runs Performed In This Review

Focused checks run read-only during this review:
- `python -m pytest tests/test_workspace_app.py -k "suppresses_foundation_backed_panels_when_refresh_is_out_of_sync or renders_foundation_backed_panels_when_refresh_is_aligned"` ? passed
- `python -m pytest tests/test_persist_tool_a.py -k "source_run_id"` ? passed
- `python -m pytest tests/test_workspace_app.py tests/test_persist_tool_a.py` ? passed

---

## Final Verdict

**READY WITH MINOR CHANGES**

Phase 1A is functionally close and the main implementation choices are correct. I would make these exact corrections before calling it closed and moving on:

1. Make `FOUNDATION_MISSING` use the same per-panel suppressed fallback behavior promised by v3, or narrow the plan so it no longer promises that.
2. Add a direct test for `FOUNDATION_MISSING`.
3. Add a direct test for `TOOL_A_MISSING_REFRESH`.
4. Tighten `T14` so it explicitly proves the suppressed cards contain a reason sentence, not just title + CLI suggestion.
5. Re-run `python main.py tool-a` once before Phase 2 so the live latest structural parquet is regenerated with `source_run_id`.

After that, I would be comfortable moving to **Phase 1B** in the existing order:
- source-verification editing
- Tool B workflow polish
- notes polish
- overview search/filter/sort
