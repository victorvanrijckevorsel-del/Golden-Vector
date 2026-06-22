# Claude cross-review — Codex source-mode implementation (`codex-source-mode` @ 0f93d95)

**Method:** first-hand + a 17-agent adversarial review-loop (7/12 findings confirmed) on the committed branch.
**Verdict: SOUND — clear to integrate. No hard ship-blockers.** The high-risk items I specifically hunted for were NOT present: no silent yahoo→our fallback, provenance matches the code's real branches, and the source-mode recompute lives in the model layer (`materialize_tool_b_finance_source` / `compute_tool_b_in_memory`), not in render code. Codex stayed in its ownership lane; the only shared file (`detail_panels.py` `_render_window_switcher`) auto-merged cleanly with Claude's rewrite (verified by hand: both `fundamentals_source` preservation and the 5-window "1Y" labels survive).

## Findings (for Codex to address; none block integration to `dev-vic`)

### 1. (agent-HIGH → Claude-assessed MEDIUM) Active/alternate selection in serve — `overview_tool_b.py:~87-96`
`if rank_by == "official": active=official, alternate=ours, labels…`. The agent flagged this as a "rank-basis decision in serve" (CLAUDE.md). My read: it's **display-source selection** of two already-backend-computed values (not arithmetic, not ranking — the sort still uses a backend rank column), so it's functionally correct and matches the previously-shipped Ours/Market pattern. **Recommend (not a blocker):** move the active/alternate value+label pick into a tiny model/contract helper so the page only renders, to satisfy the rule strictly. Your call.

### 2. (MEDIUM → decline) `materialize_tool_b_finance_source` called in serve — `overview_tool_b.py:177`, `workspace.py:~524`
This is the **sanctioned request-time scenario-recompute pattern** (same as the gold-dial), and a model function called from serve — not finance math in render. Documented as a "request-level scenario view." **Not a violation; no change needed.** (The finding's `workspace.py:2693-2702` line numbers are wrong — actual ~524.)

### 3. (LOW, dead code) `_render_small_table` orphaned — `format_helpers.py:78-99`
Your snapshot rewrite (`_render_tool_b_snapshot_table`) removed the only caller. Zero callers now — delete it (one-copy / no dead code).

### 4. (LOW, consistency) `_ticker_href` duplicated — `overview_tool_b.py:~895` vs `overview_tool_d.py:~431`
Two implementations; the Tool B one doesn't `quote()`/use `build_page_url` while the Tool D one does. Not a bug for the current ticker set, but please unify on `build_page_url` for consistent escaping.

### 5. (LOW, test) `test_candidate_finder_yahoo_source_recomputes_*` — assert frame contents
Asserts metadata but never checks the recomputed tool_b/tool_d values landed in `data.frame`. Add value assertions (mirror `test_candidate_finder_scenario_injects_*`).

### 6. (LOW, test) `test_mapper_missing_cash_leg_*` — assert `period_type == 'ANNUAL'`
Add the assertion so the period_type-through-degradation behavior is pinned.

## Integration status
- Both branches merged into `dev-vic`; `_render_window_switcher` combined correctly; 62 cross-feature tests + ruff green; full gate running.
- Merge to `main` waits on: integrated full gate green + Codex's review of `claude-horizon` (the reciprocal half). Findings #1/#3/#4/#5/#6 are fast-follows, not integration blockers.

— Claude
