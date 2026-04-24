# Review Request: Tool B Parity + Parameters Milestone — Implementation Review

Date: 2026-04-24
Requester: Claude (Opus 4.7)
Reviewer: Codex
Mode: Read-only implementation review of the five steps landed after your plan review

This review follows your earlier review of the plan ([codex_review_claude_tool_b_parity_and_parameters_plan.md](codex_review_claude_tool_b_parity_and_parameters_plan.md)). I accepted all your P1/P2 corrections and adjusted the plan accordingly before coding. Emanuel asked me to execute everything except Step 3 (manual-data backfill — deferred), and to self-review before handing off. I've self-reviewed and fixed three bugs I caught. Now I want your independent pass.

---

## Context refresher

Starting point: the merged cross-check review ([merged_tool_b_friend_excel_crosscheck_comparison.md](merged_tool_b_friend_excel_crosscheck_comparison.md)) identified drift between our Python Tool B and the friend's Excel. The plan ([claude_tool_b_parity_and_parameters_plan.md](claude_tool_b_parity_and_parameters_plan.md)) proposed 5 steps. You reviewed the plan and flagged three P1 corrections:

- **P1.1** — Step 3 must import `source_verification` alongside `company_inputs` or imported rows would silently remain `ESTIMATED`
- **P1.2** — Remove the blanket `if rate < 1 then * 100` rule; it's unsafe and the existing `_rate()` helper already handles both conventions
- **P1.3** — Step 4's `tool_b_score` formula change (to use `upside_peer_pe_pct`) is a product decision, not parity work. Keep the score formula unchanged this milestone.

Plus P2 corrections: centralize friend-ticker mapping, lock the jurisdiction-tier ownership decision in `universe.yaml`, use named-scenario checks for Step 4 verification, reduce approval checkpoints.

**What I implemented** (Steps 1, 2, 4, 5 — Step 3 deferred per Emanuel):

| Commit | Step | Summary |
|---|---|---|
| `f5c32f7` | 1 | ARMN → ARIS.TO in `config/universe.yaml` |
| `464106b` | 2 | 35 jurisdiction tiers synced from workbook via `scripts/sync_universe_tiers_from_excel.py`; centralized `FRIEND_TICKER_MAP` in `scripts/friend_excel_import.py` |
| `3405aa1` | 4 | 4 target-price scenarios + 4 upside %s surfaced in parquet and `/tool-b` view; EV/EBITDA-derived targets dropped; `best_target_price_usd` / `best_upside_pct` retained under the hood so `tool_b_score` formula is unchanged |
| `06c1c80` | 5 | Screening Parameters panel on `/tool-b`; `compute_tool_b_in_memory` extracted; URL-parameter overrides via `golden_vector/serve/screening_overrides.py`; live-recompute with `apply_overrides` layering onto `AppConfig` |
| `b7194d2` | self-review | Three bugs I found and fixed before handing off |

**Test suite:** 235 → **251 passing** (+16 new tests in `tests/test_screening_overrides.py` and `tests/test_workspace_app.py`).

---

## Reading order

1. Start with the plan + your review of it (context) — [claude_tool_b_parity_and_parameters_plan.md](claude_tool_b_parity_and_parameters_plan.md), [codex_review_claude_tool_b_parity_and_parameters_plan.md](codex_review_claude_tool_b_parity_and_parameters_plan.md)
2. Walk the commits in order: `f5c32f7` → `464106b` → `3405aa1` → `06c1c80` → `b7194d2` (`git show <sha>`)
3. Then the code per the sections below

---

## Mode of review

Three layers:

### Layer 1 — Did each plan correction actually land?

For each correction from your plan review, verify the implementation reflects it:

- **P1.3 (ranking unchanged)**: `golden_vector/screening/verdicts.py:compute_tool_b_score` still uses `best_upside_pct`. The parquet still publishes `best_target_price_usd` and `best_upside_pct` as derived "max of the four" columns, so nothing about scoring moved. Verify that the four new `upside_*_pct` columns are additions, not replacements.
- **P2.1 (centralized ticker mapping)**: only one `FRIEND_TICKER_MAP` dict, in `scripts/friend_excel_import.py`. Any other duplication?
- **P2.2 (jurisdiction tier ownership locked)**: `scripts/sync_universe_tiers_from_excel.py` docstring states `config/universe.yaml` is the canonical Tool B jurisdiction source. Is that stated clearly enough, and is the choice defensible in the code's comments?
- **P2.3 (named-scenario verification)**: Step 4 tests should verify per-scenario target values, not top-10 ordering.
- **P3 (fewer pauses)**: I still paused on the Step 2 `--dry-run`/`--apply` flow, but didn't pause for Steps 4 or 5. Right tradeoff?

For each landing, say "landed correctly" / "landed with minor issues" / "missed" and propose the fix shape if it's the latter two.

### Layer 2 — Independent code review of the new/changed code

No assumptions from the plan. Just look at the code and ask:

1. **Is `compute_tool_b_in_memory` truly identical math to the persistent path?** The refactor extracted `_build_tool_b_rows` / `_merge_inputs_for_tool_b` / `_frame_from_rows` from `execute_tool_b_pipeline`. `compute_tool_b_in_memory` re-uses the same helpers. Verify they produce identical output for identical input.

2. **Override parsing edge cases** (`golden_vector/serve/screening_overrides.py`):
   - The `_percent_to_fraction` heuristic (values > 1 → divide by 100; values ≤ 1 → keep as-is). Safe for the parameter space we have? Any field where a sub-1 fractional input would be legitimate for a user to type?
   - `tier_*` fields reject `value > 1.0` after `_percent_to_fraction`. What about `value == 1.0` (i.e., 100% discount)? Currently accepted. Intended?
   - Empty/missing params are skipped. Blank explicit param (`?gold_price=`) correctly ignored?
   - What happens if a hidden input on the filter form gets mangled (duplicate `gold_price` in the query string)? `urllib.parse.parse_qs` returns a list; we take `[0]`. Is that the right choice, or should we error?

3. **Live-recompute fallback** (`_resolve_tool_b_frame` in `workspace.py`): the broad `except Exception` falls back to the persisted parquet and surfaces the error message to the user. Is the catch too broad? Is there a case where silently falling back would hide a real bug?

4. **Foundation snapshot load in the override path**: the workspace calls `load_latest_foundation_snapshot(..., include_market_snapshots=True)` on every page render when overrides are present. Performance concern? For 59 tickers it's ~200ms on my box. Is that acceptable, or should we cache?

5. **Sync script YAML rewrite** (`scripts/sync_universe_tiers_from_excel.py:apply_changes`): the rewrite is line-based so it preserves comments. Is the state machine correct? Does it handle edge cases like a ticker without a `jurisdiction_tier` key, or a ticker whose `jurisdiction_tier` appears before the `ticker:` line?

6. **CSS collision**: I added `.screening-params-grid`, `.screening-params-form`, `.screening-params-actions`, `.flash-error` to `_page_shell`. Conflict with anything existing?

### Layer 3 — Missed parity issues

Look for things the plan/implementation missed that still leave drift from the friend's Excel:

- Are there Excel formulas I didn't cross-check in my earlier parity review that Step 4 might have regressed?
- When the user activates a scenario and the workspace recomputes, does the banner truthfully describe what changed? ("Recomputing live from manual data + latest snapshot" — accurate?)
- The `tool_b_score` stays max-of-4-based. After Step 4 dropped the 2 EV/EBITDA targets, the `max()` pool shrank from 6 to 4, so `best_upside_pct` changed for every ticker. Did this shift ranks in a way that needs explaining, or is it neutral?
- Step 2's tier sync produced 35 changes (your earlier count was 33). Any of the delta worth scrutinizing as a data anomaly?

---

## Setup

```bash
python -m pytest -q                            # baseline: 251 should pass
python main.py update-data                     # optional; the foundation is current on my machine
python main.py tool-b                          # produces parquet with new 4-scenario schema
python main.py workspace                       # http://127.0.0.1:8765/tool-b
```

Live smoke checks worth running:

- Open `/tool-b` — you should see 17 columns, including 4 target/upside pairs
- Visit `/tool-b?gold_price=4500` — "Scenario active" banner, KGC verdict becomes WATCHLIST (was SCREEN_OUT at $4000)
- Visit `/tool-b?gold_price=4500&aisc_target=1600` — two overrides active; the "Reset all" link returns to bare `/tool-b`
- Visit `/tool-b?gold_price=-5` — should 400 with a friendly "Invalid override" banner
- On `/tool-b?gold_price=4500`, type `NEM` in the search box and submit — verify the resulting URL keeps `gold_price=4500` (the hidden-input fix from the self-review)

---

## Files most worth a close read

- [golden_vector/screening/pipeline.py](golden_vector/screening/pipeline.py) — the refactor + new `compute_tool_b_in_memory`
- [golden_vector/screening/targets.py](golden_vector/screening/targets.py) — the four-scenario split and `_upside_pct` helper
- [golden_vector/serve/screening_overrides.py](golden_vector/serve/screening_overrides.py) — URL parsing, percent coercion, `apply_overrides`
- [golden_vector/serve/workspace.py](golden_vector/serve/workspace.py) — the new `_render_tool_b_overview_page` signature, `_resolve_tool_b_frame`, `_render_screening_params_form`, `_render_overrides_as_hidden_inputs`, and the `/tool-b` route wiring
- [scripts/sync_universe_tiers_from_excel.py](scripts/sync_universe_tiers_from_excel.py) — state-machine YAML rewrite
- [scripts/friend_excel_import.py](scripts/friend_excel_import.py) — centralized `FRIEND_TICKER_MAP`
- [tests/test_screening_overrides.py](tests/test_screening_overrides.py) — 12 new tests for the override plumbing
- [tests/test_workspace_app.py](tests/test_workspace_app.py) — 4 new Tool B view tests (form renders, 400 on invalid, baseline vs override banner, combined alias)
- [tests/test_screening_targets.py](tests/test_screening_targets.py) — updated for the four-scenario schema

---

## Self-review I already did (for you to second-guess)

Three bugs I found in my own code before handing off (committed in `b7194d2`):

1. **Dead `_value()` helper** inside `_render_screening_params_form`. Declared but never called. Removed.
2. **Search form silently dropped overrides**. If `gold_price=4500` was active and the user typed `NEM` in the search box, the resulting URL lost `gold_price`. Fixed by adding `_render_overrides_as_hidden_inputs` to carry active overrides as hidden inputs in the filter form.
3. **`ToolBOutput` pydantic model** in `contracts/data_models.py` still had `target_price_peer_evebitda` / `target_price_peak_evebitda` fields. The model is documentation-only (never imported) but I updated it to match the current schema: dropped the two EV/EBITDA fields, added the four `upside_*_pct` fields.

Things I deliberately did NOT do that you might flag:
- Did not add the Screening Parameters panel to the Combined view (`/`). The plan deferred it, you agreed in your review. If you now think it belongs on Combined too, say so.
- Did not change `tool_b_score` formula. Kept `best_upside_pct` as input (parity-first option, per your P1.3 recommendation).
- Did not rename existing test fixtures or clean up the `ARMN` SQLite row (there wasn't one — bootstrap only seeds active+tool_b_enabled).

---

## Output format

Write `reviews/codex/codex_review_tool_b_parity_implementation.md` using the same severity convention as prior reviews (P0/P1/P2/P3). I'd particularly value:

1. Verdict per step (Step 1, 2, 4, 5, self-review): `LANDED CORRECTLY` / `LANDED WITH MINOR ISSUES` / `NEEDS A FIX`
2. Any net-new findings (things I didn't already call out)
3. Specific challenge on the self-review — did I catch what matters, or did I gold-plate while missing something real?
4. Your call on the deferred Step 3 — ready to do it now, or should something from this cycle land first?

---

## Ground rules

- Read-only. Don't change code.
- If you find something that reads like a bug but you're unsure, propose the fix shape and let Emanuel decide.
- When citing files, use `path.py:line` so the workspace links work.
- Be honest about what you couldn't verify cleanly.

Thanks.
