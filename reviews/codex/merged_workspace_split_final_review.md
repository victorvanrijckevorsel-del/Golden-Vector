# Merged Workspace Split Final Review

Date: 2026-05-28

Grade before fixes: READY WITH MINOR FIXES

Sources merged:

- `reviews/codex/claude_review_codex_steps8to12_final.md`
- `reviews/codex/codex_self_review_workspace_split_2026-05-28.md`

## Combined Findings

| Priority | Source | Finding | Action |
| --- | --- | --- | --- |
| P3 | Codex | Static cache policy uses the raw `/static/*` URL path instead of the resolved asset path, so `/static/vendor/../workspace.css` can serve repo-owned CSS with immutable cache headers. | Fix cache policy to use the resolved path relative to `_STATIC_ROOT`; add regression test. |
| P3 | Codex | `overview_tool_a.py` and `overview_tool_b.py` use `Any` in local annotations without importing it. | Add `from typing import Any` to both modules. |
| P3 | Codex | Detail `lens` fallback behavior was smoke-tested but not covered by automated tests. | Add WSGI regression test for default, `tool-a`, and unknown detail lens URLs. |
| P3 | Claude | `_fmt_numeric_td` is imported but unused in `detail_panels.py`. | Remove unused import. |
| P3 | Claude | Several files have excessive blank-line stretches from the mechanical move. | Reduce highlighted stretches to normal top-level spacing. |
| Process | Claude | Commit `76ee786` contained both the Unicode fix and cache behavior change under a narrow commit message. | No code fix possible after the fact; keep as process note. |
| Process | Claude | Progress log did not include the intermediate `76ee786` fix/deviation commit. | Add a progress-log line for that commit. |

## Agreed Fix Set

Implement the five P3 code/test fixes plus the progress-log audit fix. Do not refactor beyond those items.

## Notes

Both reviews agree the split itself is structurally sound: `workspace.py` had already reached 406 lines at review time and is 397 lines after whitespace cleanup, has only router/server entry functions, the moved function bodies are mechanically preserved, tests are green, and the serve-module import graph has no cycles.

## Fix Result

Applied after merging both reviews:

- Static cache policy now uses the resolved asset path relative to `_STATIC_ROOT`.
- Added regression coverage for `/static/vendor/../workspace.css` cache headers.
- Added regression coverage for detail `lens=tool-a` and unknown lens fallback.
- Added missing `Any` imports.
- Removed the unused `_fmt_numeric_td` import from `detail_panels.py`.
- Reduced the reviewed blank-line stretches.
- Added the missing progress-log entry for commit `76ee786`.

Verification after fixes: `306 passed in 82.88s`.
