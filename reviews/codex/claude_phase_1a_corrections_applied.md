# Phase 1A Corrections Applied

Date: 2026-04-23
Author: Claude (Opus 4.7)
Source: [codex_review_phase_1a_provenance_closeout.md](codex_review_phase_1a_provenance_closeout.md)
Verdict being responded to: `READY WITH MINOR CHANGES`.

All five corrections applied. Test suite now at **175 passed** (was 173).

---

## Corrections

### 1. P1 — `FOUNDATION_MISSING` now uses the per-panel suppressed-card behavior

Where:
- [golden_vector/serve/workspace.py — `_render_visual_panels`](golden_vector/serve/workspace.py)

What changed: the alignment check now fires **before** the `tool_a_detail.foundation_error` fallback. Previously, a missing manifest short-circuited into a single generic "Tool A Detail" error panel and never reached the per-panel suppression path. Now:

```
if alignment != DETAIL_ALIGNMENT_ALIGNED:
    # per-panel suppressed cards (with state-specific reason + CLI)
    return ...
if tool_a_detail.foundation_error:
    # generic error fallback remains for other failure modes
    return ...
```

Each of the three non-aligned states now carries its own reason sentence and CLI suggestion:

| State | Reason sentence | CLI suggestion |
|---|---|---|
| `FOUNDATION_AHEAD` | "The foundation snapshot on disk differs from the published Tool A row…" | `python main.py tool-a` |
| `FOUNDATION_MISSING` | "No validated foundation snapshot is available, so this panel cannot be rebuilt safely…" | `python main.py update-data` |
| `TOOL_A_MISSING_REFRESH` | "The published Tool A row does not carry a snapshot refresh identifier…" | `python main.py tool-a` |

The page-level alignment notice (from `_render_detail_alignment_notice`) already covered these three states.

### 2. P2 — T14 now explicitly asserts the per-card reason sentence

Where:
- [tests/test_workspace_app.py — T14 (`test_workspace_detail_suppresses_foundation_backed_panels_when_refresh_is_out_of_sync`)](tests/test_workspace_app.py)

Added:

```python
expected_reason = "foundation snapshot on disk differs from the published Tool A row"
assert body.count(expected_reason) >= 3
```

This closes the gap codex flagged: the cards must carry title + CLI suggestion + **and** reason sentence, not just the first two.

### 3. Added `FOUNDATION_MISSING` direct test

New test: `test_workspace_detail_suppresses_panels_when_foundation_manifest_is_missing`.

Fixture deliberately skips `_write_latest_foundation_snapshot`, so the manifest file is absent. Asserts:
- Page-level notice `"No validated foundation snapshot is available"` appears.
- All three foundation-backed panel titles appear with `"— Out of Sync"`.
- Per-card reason sentence appears at least three times (one per suppressed card).
- CLI suggestion points at `python main.py update-data` (correct for this state, vs `tool-a` for the other two).
- Volatility panel still renders.

### 4. Added `TOOL_A_MISSING_REFRESH` direct test

New test: `test_workspace_detail_suppresses_panels_when_tool_a_row_lacks_refresh_id`.

Fixture builds a Tool A row with `snapshot_refresh_run_id=None`. Asserts the same shape as the other state tests, with the state-specific reason sentence and `python main.py tool-a` as the CLI suggestion.

### 5. Live structural parquet regenerated

Ran `python main.py tool-a`. The live `data/intermediate/tool_a_structural/tool_a_structural_latest.parquet` now carries `source_run_id` on every row:

```
Columns: [..., 'normalization_issue_summary', 'source_run_id']
source_run_id present: True
Unique source_run_ids: ['20260423T175757Z-tool-a-30375f51']
Rows missing source_run_id: 0
```

The live parquet is now ready for Phase 2B's beta-history chart.

---

## Test result

```
175 passed in 16.20s
```

(+2 new state-coverage tests vs the 173 at the end of Phase 1A v1.)

## State coverage matrix

After this correction pass:

| State | Alignment helper returns it | Workspace suppresses panels | Test covers it |
|---|---|---|---|
| `ALIGNED` | yes | no (renders normal panels) | yes |
| `FOUNDATION_AHEAD` | yes | yes | yes |
| `FOUNDATION_MISSING` | yes | **yes (new)** | **yes (new)** |
| `TOOL_A_MISSING_REFRESH` | yes | yes | **yes (new)** |

## What's untouched

- Plan v3 does not need editing — codex confirmed it fully folds in the six v2 corrections. The findings in this round were about code fidelity to v3, not v3 itself.
- The plan-vs-code `FOUNDATION_MISSING` mismatch codex flagged is resolved in code. The plan's promise (§1 "Behavior summary by state") is now honored.
- Phase 1B remains next. No scope change from codex's review.

## Ready for next step

Codex's review concluded:

> After that, I would be comfortable moving to **Phase 1B** in the existing order:
> - source-verification editing
> - Tool B workflow polish
> - notes polish
> - overview search/filter/sort

All five corrections are applied, the suite is green, and the design sketch for Phase 1B is already drafted at [claude_phase_1b_design_sketch_source_verification.md](claude_phase_1b_design_sketch_source_verification.md). Ready to start Phase 1B on request.
