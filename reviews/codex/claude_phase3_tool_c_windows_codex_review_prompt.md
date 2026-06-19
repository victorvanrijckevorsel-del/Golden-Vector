# Codex review request — Tool C "Gold Downside" per-window beta selector (Phase 3)

Hi Codex. Please deep-review the Phase 3 work on `dev-vic`. Claude already ran a read-only
agent-fleet review (18 agents, 5 confirmed findings — all test-coverage gaps, no runtime bugs)
and corrected them. Your job: independently verify the load-bearing invariant + the fixes, and
hunt for anything missed. **Trust the tree, not this summary.**

## What Phase 3 does
The Gold Downside page (`/tool-c`) gains the same beta-window selector as Tool A:
6M / 12M(=1Y) / 2Y / 3Y / 5Y. It **surfaces Tool A's already-computed per-window up/down gold
betas** so a trader sees how downside (and upside) gold sensitivity changes over lookbacks.
**No new model math** — Tool C carries Tool A's per-window betas through (Option A). The windowed
down-beta is Tool A's regime down-beta (beta conditional on weeks gold fell) — the validated,
drift-clean number; a gold-crash-conditional beta was intentionally NOT used.

## THE LOAD-BEARING INVARIANT (Option B, same as Tool A) — attack this first
The 25 per-window columns (`down_beta/up_beta/r_squared/weeks/window_status` × `6m/12m/2y/3y/5y`)
are **DISPLAY-ONLY**. They must NEVER influence Tool C's ranks/scores:
`tool_c_downside_score/rank, tool_c_upside_score/rank, score_eligible, the *_core betas, tags,
explanations`. The downside/upside RANK stays on the validated cross-window `*_core` betas. The
per-window columns are absent from `DOWNSIDE_COMPONENTS` / `UPSIDE_COMPONENTS` (the scoring inputs).
Live proof: on `/tool-c`, switching the window changes the displayed betas but the rank columns
stay constant.

## Files changed
Model: `golden_vector/model/tool_c.py` (TOOL_C_WINDOW_DISPLAY_COLUMNS spliced into
TOOL_C_OUTPUT_COLUMNS but NOT the COMPONENTS; `_prepare_tool_a` extracts them; missing columns
backfilled NA).
Serve: `golden_vector/serve/windows.py` (NEW shared `win_num_td`/`gold_link_td` cell renderers —
MOVED here from overview_tool_a.py so both A and C overviews share ONE copy);
`golden_vector/serve/overview_tool_c.py` (window selector, windowed up/down beta + muting + a
Gold-link column, hidden window input, window-aware reset, ticker link carries `?window`,
colspan 9→10); `golden_vector/serve/overview_tool_a.py` (win_num_td/gold_link_td removed → imported
from windows; dropped now-unused r2_band import — Tool A output must be byte-identical);
`golden_vector/serve/workspace.py` (`/tool-c` passes `window`).
Tests: `tests/test_tool_c.py` (rank-parity guard), `tests/test_persist_tool_c.py` (25-column
round-trip), `tests/test_workspace_app.py` (render + old-artifact degradation + completed fixture).

## What the agent fleet confirmed + Claude fixed (verify these)
1. Old-artifact degradation: a pre-Phase-3 Tool C artifact lacks the per-window columns. The page
   must render muted "—" cells + keep the core-based ranks, never crash. The code already handled
   this (window_metrics `.get()` → None → muted cell; build backfills NA). Added a serve-layer test
   `test_workspace_tool_c_view_degrades_gracefully_for_old_artifact`.
2. Render fixture completed to all 25 per-window columns + a `?window=2Y` render assertion.
3. Persist round-trip test for the 25 display columns (weeks_* stay integer).
4. Docstring clarity on the rank-parity guard (6M/12M/3Y scoring vs 2Y/5Y display).

## What to return
File-by-file findings with file:line, severity (P0/P1/P2/nit), evidence, concrete fix. Especially:
- ANY path where a per-window display column reaches a Tool C score/rank/eligibility/tag.
- The `win_num_td`/`gold_link_td` move: did it change Tool A's rendered output at all (must be
  byte-identical)? Any leftover `_win_num_td`/`_gold_link_td` reference or dead import?
- Old-artifact / partial-window degradation gaps; any reader strictness issue (cf. the Phase-2
  benchmark-betas P1 where a required-column change broke `/portfolio`).
- Test quality (does the rank-parity guard prove the invariant? ties/NA/boundary).
- Any serve-arithmetic, duplicated window logic, mislabeled basis, or house-rule violation.
