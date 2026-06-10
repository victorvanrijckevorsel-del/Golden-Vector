# Handoff — M1 gold dial BUILT (branch `m1-gold-dial`) — Codex review requested

**Author:** Claude Code (Fable 5). **State:** M1 (Tier 1 of the gold-dial plan) is fully built, tested, and pushed on branch **`m1-gold-dial`** (PR1 `d4cc7ee`, PR2 `993f955`, branched from `39074f1`). **Full suite: 907 passed** (baseline was 896; +11 net new tests). Ruff clean.

**Why a separate branch:** `dev-vic`'s working tree holds the still-uncommitted Candidate Finder UX cleanup (your fixes to the merged findings list are in flight there). M1 was built in an isolated worktree so the two streams never entangle. **Merge order:** finish + commit the Finder cleanup on `dev-vic` first, then merge `m1-gold-dial` into `dev-vic` (expect small, mechanical conflicts in `tests/test_workspace_app.py` — my M1 edits to Tool B tests vs your Finder-test edits are in different test functions).

## What M1 does (spec: `claude_gold_dial_and_fundamentals_plan_v2.md`, PR1+PR2 — v2.1)

**PR1 `d4cc7ee` — canonical Tool B prices at dated spot, fails closed, scenarios isolated:**
- `run_tool_b`: foundation loads with gold history (+ `use_model_state`, matching Tool D); spot resolved AFTER the load via `_spot_gold_from_history`; **no override + no valid gold close → FAIL before any persistence** (prior state intact). The config `default_gold_price_assumption` is **no longer consulted** by the canonical run.
- `--gold-price X` = scenario run: persists **run-stamped artifacts only** (`publish_latest_aliases=False` — the seam already existed in `ingestion/persist.py:276`), stamped `gold_price_basis='custom_scenario'`; can never become the latest alias.
- `refresh --gold-price` now **refuses with guidance** (a scenario refresh would publish a manifest pinning scenario Tool B against fresh everything-else).
- Provenance columns on every row: `gold_price_used`, `spot_gold_usd`, `spot_gold_date`, `gold_price_basis` — in the row dict + `TOOL_B_OUTPUT_COLUMNS` + `REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS` (same commit), so pre-dial parquets trip the calm 503.

**PR2 `993f955` — the dial + honest failure on the Corporate Finance page:**
- One primary control: **gold dial** (dated Spot preset + config scenario ladder + custom box), mirroring the Tool D pattern. The page intro always states the basis: "All gold-dependent estimates are at spot gold $X/oz (close DATE)."
- Serve resolves **true spot** (`latest_gold_price_from_history`); `resolve_gold_price` is gone from serve — **locked by a new guardrail test** (the Tool B clone of your Tool D serve-arithmetic scan, extended with coalesce + config-gold tokens).
- **Fail-closed honesty fixes** (the old MEDIUM 3): on recompute failure the "Scenario active" banner is suppressed (it used to lie), the dial snaps back to the gold price of the frame actually shown, `ToolBStaleSchemaError` re-raises to the calm 503.
- Threshold/jurisdiction overrides → collapsed **"Advanced screening assumptions"** panel; dial links and both forms carry each other's state via one shared `_override_query_params` source (no duplicated param lists).
- Instrumented: "Scenario recomputed in X.XXs (inputs loaded in Y.YYs)."
- `_first_frame_number/_first_frame_text` moved to `format_helpers` and shared with Tool D (helper de-duplication).

## Deliberate deviations from the plan letter (documented, review them critically)
1. **No `ToolBScenarioBundle` in PR2.** After PR1 the frame itself carries every provenance field the bundle would wrap, and the Tool D dial works frame-direct. The bundle materializes in Tier 3 when Official/Our-view/trailing sections actually exist (the plan's own §9 simplest-thing guidance).
2. **Two behavior-pinned tests updated** (not deleted): the legacy "falls back to config default gold" CLI test now pins spot-or-fail; the corrupt-model-state workspace test now pins the honest contract (no lying banner; dial empty when no trusted basis exists). A new test pins the true snap-back (failed recompute + healthy persisted frame → dial shows the persisted spot 4000, never the requested price).

## Review asks (first-hand, please)
1. PR1's fail-closed ordering: confirm nothing persists before the spot check on every path (incl. the early-exit paths).
2. The scenario-isolation contract: any path I missed where a custom run could still touch latest/manifest?
3. The serve guardrail token list: tight enough? Anything that should be forbidden and isn't?
4. The advanced-panel form interplay (dial carries thresholds, forms carry gold/search): any state-loss combination left?
5. Fixture blast radius: `tests/helpers.py::tool_b_output_row` gained the 4 provenance fields with spot-run defaults — confirm no test now passes-for-the-wrong-reason because of those defaults.
6. Run the full suite yourself (use a generous timeout; ~3–6 min).
