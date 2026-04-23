# Codex Review: Post-Workspace Hardening

Date: 2026-04-23

## Scope reviewed

This review focused on the newest high-risk paths in the current local-first product shape:

- `golden_vector/app/latest_data.py`
- `golden_vector/ingestion/persist.py`
- `golden_vector/model/pipeline.py`
- `golden_vector/screening/manual_store.py`
- `golden_vector/screening/manual_data.py`
- `golden_vector/screening/pipeline.py`
- `golden_vector/serve/workspace.py`
- `golden_vector/cli.py`

I also re-ran the full automated suite after the review and after the fix below.

## Findings

### Fixed during review

#### [P1] Empty failed Tool A / Tool B runs could wipe the stable latest aliases

Where:
- `golden_vector/ingestion/persist.py`
- `golden_vector/model/pipeline.py`
- `golden_vector/screening/pipeline.py`

What was wrong:
- the workspace reads the stable latest Tool A / Tool B parquet/csv aliases
- those aliases were being overwritten even when a run produced an empty result
- that meant one empty failed run could erase the last useful workspace view

Why it mattered:
- this is a real trust issue in the local-first product model
- the user expects the workspace to keep showing the last useful local result until a new usable result replaces it

What I changed:
- `persist_tool_a_outputs()` and `persist_tool_b_outputs()` now support `publish_latest_aliases=False`
- Tool A and Tool B pipelines now skip stable alias publication when the output is empty
- run-specific audit artifacts are still written, so auditability is preserved

Protection added:
- `tests/test_persist_tool_a.py`
- `tests/test_persist_tool_b.py`

### Minor user-facing cleanup

#### [P3] Workspace placeholder text contained mojibake / broken dash rendering

Where:
- `golden_vector/serve/workspace.py`

What was wrong:
- empty-display placeholders in the workspace were stored with broken text encoding

What I changed:
- rewrote the module cleanly and normalized empty-display placeholders to plain ASCII `-`
- also tightened missing-value handling in the formatting helpers

## What I checked holistically

- local snapshot manifest integrity and invalidation behavior
- latest output publication rules
- manual store create/load/update behavior
- workspace form submission and validation behavior
- Tool A / Tool B pipeline interactions with latest aliases
- CLI entrypoints around manual data and workspace usage

## Verification

Full suite result after fixes:

- `154 passed`

Command run:

```powershell
& 'C:\Users\Emanuel\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest
```

## Current verdict

`READY`

No open P0 or P1 issues remain from this review pass.

## Residual risks

- The workspace is intentionally thin and still does not support direct source-verification editing; that is a product gap, not a correctness bug.
- Latest Tool A / Tool B aliases are still simple stable files rather than manifest-backed versioned pointers. That is acceptable for now because empty-run alias clobbering has been fixed.
- The workspace is covered by WSGI-level tests rather than a browser automation layer. That is fine for this stage, but later UI growth may justify browser tests.
