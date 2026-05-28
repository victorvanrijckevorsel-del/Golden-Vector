# Codex Self-Review: Workspace Split Implementation

Date: 2026-05-28

Grade: READY WITH MINOR FIXES

Scope reviewed: commits `4a99427` through `1c195d3`, compared against pre-split base `09aaad2`.

This is a read-only review of the code I changed in this session. I did not modify implementation code while writing this review.

## Review Method

- Read the full split diff from `09aaad2..HEAD`.
- Re-read the current router and the new serve modules.
- AST-compared moved functions/classes against pre-split `workspace.py`.
- AST-compared moved constants against pre-split `workspace.py`.
- Checked the new serve import graph for cycles.
- Checked remaining imports from `golden_vector.serve.workspace`.
- Checked CSS extraction for doubled f-string braces.
- Re-ran focused compile checks for the split modules.
- Re-ran the full test suite.

## Verification Results

| Check | Result |
| --- | --- |
| Full suite | `304 passed in 46.29s` |
| `py_compile` for split serve modules | Passed |
| `workspace.py` top-level defs | Only `create_workspace_app` and `run_workspace_server` |
| `workspace.py` line count | 406 |
| Moved function/class AST comparison | 85 checked, 0 unexpected diffs |
| Moved module constants comparison | 0 missing, 0 changed, 0 duplicate definitions |
| `workspace.css` doubled braces | 0 matches for `{{` or `}}` |
| Imports from `workspace.py` | Only CLI and tests import `create_workspace_app` / `run_workspace_server` |
| Serve-module import graph | No cycle found by inspection or AST import scan |

## Findings

### P3 - Static cache policy uses the raw URL path, not the resolved asset path

`golden_vector/serve/http_helpers.py:125-131` computes the served file from the resolved `candidate`, but passes the unresolved `relative` string into `_static_cache_control()`. Because `_static_cache_control()` only checks `normalized.startswith("vendor/")` at `golden_vector/serve/http_helpers.py:137-141`, a traversal-normalized path like `/static/vendor/../workspace.css` serves the repo-owned `workspace.css` with `Cache-Control: public, max-age=31536000, immutable` instead of `no-cache`. The ancestor check still blocks escaping `_STATIC_ROOT`, so this is not a file disclosure issue. It is a cache correctness edge case introduced by the review-fix cache split. The fix should derive cache policy from `candidate.relative_to(_STATIC_ROOT).as_posix()` after resolution, not from the raw request path, and add a regression test for the normalized path case.

### P3 - `Any` is used in two new overview modules without importing it

`golden_vector/serve/overview_tool_a.py:42` and `golden_vector/serve/overview_tool_b.py:70` annotate local `derived` lists as `list[dict[str, Any]]`, but neither module imports `Any`. This does not fail at runtime because these are local variable annotations and the files use `from __future__ import annotations`, and `py_compile` passes. It is still a static-analysis hygiene issue and will likely be flagged by pyright/mypy/ruff-style checks once those are installed or enabled. Add `from typing import Any` to both modules.

### P3 - The new detail `lens` fallback behavior is only covered by smoke checks

The implementation normalizes unknown detail lens IDs to `DETAIL_DEFAULT_LENS_ID` in `golden_vector/serve/workspace.py:181-183`, and the smoke check confirmed `/ticker/AEM?lens=banana` returns 200 with the same HTML as `/ticker/AEM`. However, there is no automated WSGI regression test for this new route contract. Because this is the only intentional tool-shaped behavior change in the split, it should have a small test asserting that `lens=tool-a` and an unknown lens both return 200 and match the default detail response.

## Non-Blocking Notes

- `golden_vector/serve/detail_page.py:37` accepts `lens` but does not use it yet. This matches the locked plan: only `tool-a` exists now, and the work was meant to shape the interface rather than build a registry. I would not change this until a second detail lens exists.
- `_render_provenance_warnings` and `_render_refresh_summary` live in `overview_combined.py`, not `detail_panels.py`. I still think this is the right destination because the current callers are overview pages, and it avoids making detail modules depend on overview behavior.
- `workspace.py` still has some excessive blank lines in the import area. This is cosmetic and does not affect behavior, but it is worth cleaning when implementation changes resume.
- The CSS extraction is behaviorally clean. The HTML change is the expected swap from inline style text to `/static/workspace.css`; the static CSS file has no doubled f-string braces.

## What Looks Strong

- The main split was highly mechanical. Excluding explicit behavior changes (`_page_shell`, `_serve_static_file`, and renamed/lens-aware detail page), every moved function/class AST-matches its pre-split body.
- Constants moved cleanly with no duplicate leftovers in `workspace.py`.
- `workspace.py` is now genuinely a router plus server entry point, not a mixed rendering module.
- The import graph points in the intended direction: leaf helpers -> panels/overviews/detail page -> router. No new module imports from `workspace.py`.
- Existing tests were mostly preserved with import-only updates. The one added test for repo-owned CSS cache behavior is appropriate, but it should be extended for the normalized-path edge case above.

## Suggested Fix Order After Claude Review

1. Fix cache-control path normalization in `http_helpers.py` and add a targeted test.
2. Add missing `Any` imports in `overview_tool_a.py` and `overview_tool_b.py`.
3. Add a small automated detail-lens fallback test.
4. Clean the cosmetic blank-line drift in `workspace.py` if the same commit is already touching that file.

## Review Conclusion

I do not see a blocking functional regression in the normal workspace routes. The only real code issue I found is the cache-control edge case for normalized static paths; the rest are test/static-analysis hygiene. My recommendation is to wait for Claude's review, merge the finding lists, then fix the overlapping items in one small follow-up commit.
