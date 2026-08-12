# Phase 1 Baseline — Platform Redesign

- Date: 2026-08-12
- HEAD commit: c7e90db (dev-vic)
- Purpose: freeze CURRENT behavior as committed evidence before any Phase 1 code changes, per
  the "Phase 1 — Baseline" paragraph in
  `reviews/codex/claude_platform_redesign_plan_final_2026-08-12.md`.

## 1. Evidence captured

- Mock reference: `.playwright-mcp/mock3.html` copied to
  `reviews/codex/milestones/platform_redesign/mock3_reference.html`.
- `.playwright-mcp/` was listed for annotated target/mock PNG/JPG images. None exist in that
  directory (only console-*.log files, mock2.html, mock3.html, and a couple of check_mock*.js
  scripts). Nothing else was copied.
- HTML payload size + server render timing for `/ticker/NEM`, in-process (no browser), via a
  scratch script that reuses the `_call_wsgi_app` WSGI-environ pattern from
  `tests/test_workspace_app.py` but against the REAL repo data (`ProjectPaths.discover()`,
  `load_app_config`, `_active_tool_b_tickers` from `golden_vector/cli.py`, and
  `create_workspace_app`) rather than a tmp_path fixture. NEM was renderable directly (confirmed
  present in the real active Tool B ticker universe — 61 active tickers).
- Query parameter for financial source, found at `golden_vector/serve/workspace.py:558-560`:
  `fundamentals_source` (values `our` default / `yahoo`), normalized via
  `normalize_finance_source`.
- Full pytest baseline (focused selection + full suite) run from repo root, unmodified tree.
- Playwright screenshot capture: SKIPPED. `venv\Scripts\python.exe -c "import playwright.sync_api"`
  raised `ModuleNotFoundError: No module named 'playwright'`. Per instructions, nothing was
  installed; the visual baseline defers to the Phase 4 batched browser gate. No local workspace
  server was started for this task, so there is nothing to stop.

## 2. Payload size + render timing — `/ticker/NEM`

In-process WSGI calls against the real app built from `ProjectPaths.discover()` +
`create_workspace_app(paths, app_config=..., tool_b_tickers=<61 active tickers>)`. 5 timed
renders per mode after one untimed status/size check.

| Mode | Query | Status | Response bytes | Timings (s) | Median (s) | Min (s) |
|---|---|---|---|---|---|---|
| Our View | `/ticker/NEM` | 200 OK | 448,715 | 0.5196, 0.4921, 0.3919, 0.3896, 0.3861 | 0.3919 | 0.3861 |
| Yahoo | `/ticker/NEM?fundamentals_source=yahoo` | 200 OK | 440,411 | 0.7643, 0.5854, 0.6127, 1.1529, 1.2174 | 0.7643 | 0.5854 |

Notes: Yahoo-mode is slower and more variable than Our View, consistent with the plan's D15 note
that Yahoo mode still recomputes Tool B/Tool D in-process at request time rather than reading a
persisted dual-source artifact (Phase 2 scope). Script:
`C:\Users\Emanuel\AppData\Local\Temp\claude\c--Users-Emanuel-code-Golden-Vector\aae8377a-d658-4673-af67-443047a5c776\scratchpad\baseline_render.py`
(scratch only, not committed).

## 3. Test baseline

- Focused selection (`tests/tools/run_focused_selection.py -q`):
  **915 passed in 1076.55s (0:17:56)**.
- Full suite (`python -m pytest tests -q`):
  **2182 passed in 1417.42s (0:23:37)**.
- No failures in either run; nothing to list.

## 4. Screenshot inventory

Deferred — see §1. No PNGs captured or copied. The visual baseline (1440/1024/390px, Our View
and Yahoo mode) will be captured at the Phase 4 batched browser gate per
`feedback_token_efficiency.md` (browser checks reserved for major gates).

Decision record (2026-08-12, after Codex's Phase 1 review flagged the missing pixels): Victor
approved installing Playwright (python package, script-driven — PNGs to disk, no MCP context
cost) but directed it be used only when genuinely necessary. Since commit `c7e90db` is
immutable, the "before" pixels are reproducible at any time; capture is therefore deferred to
the one batched Phase 4 pass, where before and after ship together. Recipe for the "before"
side: `git worktree add <dir> --detach c7e90db`; the worktree checks out tracked
`data/manual`, and the untracked read-only inputs (`data/intermediate`, `lab`, `output`,
`raw`, `runs`) are junctioned from the main tree (`New-Item -ItemType Junction`); serve from
the worktree; capture; unlink junctions with plain `rmdir` (never a recursive delete through
a junction); remove the worktree.

## 5. Anomalies

- The full test-suite runtime here (23:37) is noticeably longer than the "~14 min" estimate in
  the task brief; the focused-selection runtime (17:56) is also longer than its usual quick-gate
  expectation. Both runs were green (0 failures), so this is a timing anomaly only, not a
  correctness one. Orchestrator annotation: the cause is known — these runs shared the machine
  with the two Phase 1 implementation lanes' own pytest runs (and, at the tail, the combined
  integration gate), so the wall-clock numbers here are contention-inflated and are NOT the
  timing baseline; the uncontended reference remains `1555 passed in 835.65s` at the 2026-08-10
  baseline plus growth since. The pass/fail counts are the baseline facts.
- Orchestrator annotation (integration overlap disclosure): the final minutes of the full-suite
  run overlapped the Phase 1 lane merges into `dev-vic` (the payload/timing capture in §2 and
  the focused-selection run fully preceded any main-tree change). Static-scan guardrail tests
  read source at test runtime, so late-running tests may have read merged code. Outcome risk is
  nil in practice — the run finished 2182/2182 green, and the merged code independently passes
  every guardrail in the 364-test combined gate — but the overlap is recorded here rather than
  hidden.
- Two earlier background invocations of the same commands (via `... | tail -N`) produced empty
  output files due to a piping/backgrounding quirk in this environment; they were superseded by
  direct (unpiped) background re-runs, which produced the numbers recorded above. No source or
  test files were touched by any of these runs.
