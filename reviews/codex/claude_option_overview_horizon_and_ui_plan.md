# Plan — Option Trading Overview: Horizon Selector + UI Completion

For review by: Codex, then Emanuel approval before any code.
Author: Claude. Status: PLAN ONLY (no code changed yet).

## Why this exists
Three things were **planned and documented but never built** on the Option Trading
**overview** (`/option-trading`, also the `/` overview when the option lens is active):

1. A **horizon selector on the main page** with a default pre-picked — planned as
   Milestone **C4** in `reviews/codex/codex_option_snapshot_fallback_plan.md`:
   > "page-wide horizon control threaded through the `/option-trading` overview and
   > `/ticker` detail … Default to the backend 'Most liquid' … Overview stays
   > readable: one row per ticker for the selected horizon."
   What shipped instead (commit `ab48c9e`, "Milestone C complete"): only a **read-only
   indicator** (`_render_most_liquid_indicator`: "puts ~230d · calls ~180d"). The
   interactive selector + per-horizon rows on the overview were silently dropped. The
   **detail** page got the full control; the overview did not.
2. **Concise notes** — `claude_ui_inventory_and_plan.md:228` (MED, "text-wall") +
   `codex_option_trading_clarity_plan_v2.md` §4j ("Notes | concise warnings"). The
   Notes cell still joins every note with "; " into a tall, uneven tower.
3. **Missing ⓘ help headers** — `claude_ui_inventory_and_plan.md:223` (HIGH,
   "explain-header"): Ticker, Stock Price, Down Beta, Up Beta, Gold Sensitivity
   Confidence, Signal, Activity, Put Status, Call Status, Notes are plain `<th>` with
   no click-to-explain affordance, while the other columns have one.

These are independent and can ship in any order. Recommended order: A → C → B.

## Current state (verified against the tree)
- Backend already stamps, per ticker, the side-aware most-liquid horizon + expiry
  (`most_liquid_put/call_horizon_days`, `most_liquid_put/call_expiration`) and the
  group defaults (`group_default_put/call_horizon_days`) onto the persisted
  `option_trading_overview` artifact (`option_artifact_frames._stamp_most_liquid_defaults`).
  After audit M2, the most-liquid window is guaranteed to be candidate-backed.
- The **candidate slots** artifact (`option_candidate_slots`) already holds, per
  (ticker × side × horizon), the slot status (`accepted` / `no_tradable` / `watch` …),
  expiration, and liquidity tier. The **detail** page already SELECTS the slot for the
  chosen horizon and renders it (no recompute) — so the per-horizon data exists.
- The **overview** render (`serve/overview_option_trading.py`) currently shows ONE
  `put_status` / `call_status` per row (from `OptionTradingRow`), not per-horizon, and
  does not load the slots. There is no `?horizon=` control on the overview.
- The published **Signal / skew / IV** columns are on the global signal horizon and
  must stay there (comparable across rows) — the selector must NOT change those.

---

## Part A — Overview horizon selector (the C4 piece) — PRIMARY

### Goal (plain English)
On the option main page, let the user pick which option horizon the candidate columns
reflect, with the backend "most liquid" already chosen for you, and show clearly which
horizon you're looking at.

### Simplest design that is correct
Selection, not recomputation — mirror what the detail page already does.

1. **Control:** add an `option_horizon` GET param to the overview route, surviving the
   existing structural 6M/12M/3Y window switcher and the `lens`. Allowed values:
   - `most_liquid` (DEFAULT) — each row shows its own per-side stamped most-liquid
     status + expiry (this is the "one already picked for you").
   - each configured display horizon (`90`, `180`, `230`, `550` from
     `hedge_readiness.display_horizons_days`) — every row shows that horizon's status.
   Render it as a labeled `<select>` in the existing filter bar, plus a one-line caption
   ("Showing candidates at: Most liquid per side" or "230d · target ~230d").
2. **Per-horizon status source (backend computes / serve renders):** stamp a compact
   per-horizon candidate-status map onto the `option_trading_overview` artifact at build
   time — for each ticker × side × configured horizon: `{status, expiration, dte}`. This
   reuses the already-built `candidate_slots` (no new selection engine; one copy). Serve
   then READS the map for the selected horizon and renders Put/Call status + expiry.
   - Rationale: keeps logic in the backend; serve only selects + formats. Matches the
     existing most-liquid stamping pattern and the "compute once → persist → serve reads"
     rule. (Alternative considered: pass `candidate_slots` into the overview render and
     select in serve — rejected; it pushes selection logic into serve and needs the
     serve-arithmetic guardrail to be re-reasoned. Stamping is cleaner.)
3. **What changes with the selector:** only the Put Status / Call Status columns + a
   shown expiry/DTE. Signal, Skew vs Benchmark, IV %ile, Option Cost Signal, Activity
   stay on the signal horizon (they are not horizon-selectable) — label them so it's
   clear they are signal-horizon, not the selected horizon.
4. **Default = most-liquid:** when `option_horizon` is absent or `most_liquid`, each row
   uses its stamped per-side most-liquid status (today's behaviour, now per-row visible
   instead of only a group hint). The "Most liquid windows" indicator line stays as a
   summary caption.

### Files
- `golden_vector/hedge/option_artifact_frames.py` — stamp `overview_candidate_status_json`
  (or per-horizon columns) on the overview artifact from `candidate_slots` /
  `call_candidate_slots`. Bump `OPTION_ARTIFACT_SCHEMA_VERSION` (forces one refresh;
  old artifacts fail loud, which is the established pattern).
- `golden_vector/hedge/option_trading.py` — `OptionTradingRow` gains the per-horizon
  status map field; `overview_rows_from_frame` populates it.
- `golden_vector/serve/overview_option_trading.py` — parse `option_horizon`, render the
  selector + caption, render Put/Call status + expiry for the selected horizon.
- `golden_vector/serve/workspace.py` — thread `option_horizon` from the querystring.
- Add the **serve-arithmetic static-scan guardrail test** for this new surface (per
  CLAUDE.md: clone the Tool-D guardrail) proving serve does no candidate selection math.

### Tests
- Default (`option_horizon` absent) → each row shows its stamped most-liquid status.
- `option_horizon=230` → every row shows the 230d slot status + expiry; a ticker with no
  230d candidate reads "No liquid candidate" honestly.
- Signal / IV / skew columns are unchanged by the selector.
- The control survives the 6M/12M/3Y window switcher and the option lens (query state).
- Guardrail: serve picks persisted per-horizon status, never recomputes from chains.

### Decisions for Emanuel (please pick)
- **A1.** Selector default: `most_liquid` per side (recommended) — agree?
- **A2.** Selector values: `most_liquid` + the four configured horizons (90/180/230/550) —
  agree, or a shorter list?
- **A3.** OK to bump the option-artifact schema version (requires one refresh after ship;
  old artifacts show a loud "run refresh" notice until then)?

---

## Part B — Concise notes (overview, then Tool C + portfolio)
Replace the "; "-joined notes tower with a short in-cell summary (e.g. a small badge:
note count, or the first/most-severe note) and the full text on hover/click-expand,
reusing the existing note-tag badge style. Scope this PR to the option overview
(`overview_option_trading.py:284`); follow-on PRs apply the same treatment to the Tool C
tag wall (`overview_tool_c.py:55`) and the portfolio hedge Note (`portfolio_page.py:207`)
per `claude_ui_inventory_and_plan.md`. Tests assert the cell shows a short summary and
the full text is reachable.

## Part C — Wire the missing ⓘ help headers
Wrap the plain headers (Down Beta, Up Beta, Gold Sensitivity Confidence, Signal,
Activity, Ticker, Stock Price, Put Status, Call Status, Notes) with `help_th` + registered
`ColumnHelp` keys in `column_help.py`, reusing existing beta/signal help text where it
already exists. Tests assert each header resolves a help entry (mirror the existing
column-help tests). Low risk, no schema change.

## Risk / sequencing
- Part A is the only one touching the artifact schema (a version bump + one refresh).
- Parts B and C are serve/render-only, no schema change, low risk.
- All three are additive UX; none change the signal math or rankings.
