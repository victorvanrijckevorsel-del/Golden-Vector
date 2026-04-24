# Plan: Tool B Parity with Friend's Excel + Configurable Parameters

Date: 2026-04-24
Author: Claude (Opus 4.7)
Status: PROPOSED — awaiting Emanuel's approval before any code is written
For review by: Codex

## Background

After the cross-check review ([merged_tool_b_friend_excel_crosscheck_comparison.md](merged_tool_b_friend_excel_crosscheck_comparison.md)), Emanuel and I agreed on a focused milestone to:

1. Bring our Tool B closer to the friend's Excel (`Gold_Mining_Screening_v10226_EVEB.xlsx`) where the friend has done canonical work
2. Backfill the 56 active tickers that have no manual data in our SQLite store
3. Stop the misleading `best_target = max(of 6 scenarios)` headline; show the four scenarios separately like the Excel
4. Add a UI panel on `/tool-b` that lets the user change all the screening parameters (gold price, P/E target, AISC target, etc.) on the fly without touching YAML or running CLI

This plan stages the work in five steps, each independently shippable, with explicit checkpoints where I pause for Emanuel's eyeball before persisting changes.

After this milestone the workspace becomes the canonical operating surface for Tool B — Emanuel will rarely need the CLI for normal scenario work.

## Goal — what's true after this milestone

- All 59 active Tool B tickers have manual data (was: 3 of 59)
- Per-ticker jurisdiction tiers match the friend's research (he has explicit per-ticker calls; we currently default everyone to tier 2)
- ARMN's broken Yahoo symbol is replaced with `ARIS.TO` (Aris Mining Corporation's actual current symbol)
- The Tool B view shows four target-price scenarios as separate columns (Peer P/E, Peak 2011 P/E, Peer FCF Yield, Peak 2011 FCF Yield) — matching Excel `Top performers` columns AA / AC / AI / AK
- A "Screening Parameters" panel at the top of `/tool-b` lets the user change 10 parameters (gold price + 6 thresholds + 3 tier discounts) live, with URL-parameter overrides that don't overwrite YAML
- Test suite stays green at every checkpoint (currently 235 passing)

## Out of scope (deliberately)

- Changing verdict thresholds (already match Excel: 8 / 10)
- Changing peer benchmarks (already match exactly)
- Supporting fractional jurisdiction tiers like KGC's 1.5 — Excel itself rounds up so this would be precision the Excel doesn't actually use
- Fixing the friend's Excel data quality issues (royalty/tax decimal-vs-percent for ~6 tickers, leverage edge case when EBITDA ≤ 0, AISC label vs cell mismatch). These are flagged in the merged comparison for the friend to address on his side. Our auto-correction in Step 3 normalizes the bad rows on import.
- Replacing NGD's broken Yahoo data feed (Yahoo recognizes the symbol but `history()` returns 0 rows; the friend's Excel uses Google Finance which still works). NGD stays inactive in our universe.
- Adding the Screening Parameters panel to the Combined view (deferred — `/tool-b` is the primary parameter-tuning surface; Combined remains a quick reference)

## Step 0 — Safety preamble (5 min)

- Back up `data/manual/screening/manual_screening.sqlite3` to `data/manual/screening/manual_screening.sqlite3.bak.2026-04-24` so a bad backfill is recoverable
- Commit current state to `dev-vic` so the working tree is clean before the first edit
- No code change

## Step 1 — Fix ARMN → ARIS.TO (15 min)

**What changes:**
- `config/universe.yaml`: change the `ARMN` entry's `ticker` to `ARIS.TO`, `exchange` to `TSX`, `currency` to `CAD`, `active: true`. Keep `jurisdiction_tier` as 2 for now (Step 2 will set the friend's value).

**Friend-ticker mapping note:**
The friend's spreadsheet still uses "ARMN" as the ticker label. When we import his data in Step 3, the import script maps `ARMN → ARIS.TO`. This mapping lives in the import script only, not in production code.

**NGD decision:**
Leave inactive. Yahoo's `history()` endpoint returns 0 rows for both `NGD` and `NGD.TO` even though the symbol is recognized as "New Gold Inc." The friend's Excel uses GOOGLEFINANCE which still works for it. Revisit later (try the `yahooquery` library, or accept that this single ticker is unavailable).

**Tests touched:** none expected. Run the full suite to confirm.

**Verification:**
- `python -c "...print active tickers..."` → ARIS.TO present, ARMN absent
- `python -m pytest -q` → 235 passing
- `python main.py update-data` → ARIS.TO fetches successfully (5 rows confirmed via direct Yahoo test)

**Checkpoint with Emanuel:** none. Mechanical change.

## Step 2 — Sync jurisdiction tiers from friend's Excel (45 min)

**Goal:** copy the friend's per-ticker jurisdiction values from Excel `Screening Data!U:U` (column 21) into our `config/universe.yaml`, applying `math.ceil()` to match Excel's `ROUNDUP(VLOOKUP(...,21))` rule used in `Layer 2!C5`.

**New file:** `scripts/sync_universe_tiers_from_excel.py`

**Behavior:**
1. `--dry-run` (default): reads the Excel, applies `ceil`, prints a 3-column diff table:
   ```
   Ticker     Excel raw   Excel rounded   universe.yaml current   Discount change
   AEM        1.0         1               2                       15% → 0%
   AAUC.TO    3.0         3               2                       15% → 30%
   BTG        2.5         3               2                       15% → 30%
   KGC        1.5         2               2                       no change
   ...
   ```
2. `--apply`: rewrites `config/universe.yaml` in place, preserving comments and the GOLD/FNV/FRES.L legacy entries.

**Friend-ticker mapping in script:**
- `ARMN` (friend) → `ARIS.TO` (us)
- `RMS` (friend) → `RMS.AX` (us)
- Everyone else: same ticker

**Tests touched:**
- `test_registry.py` and `test_tool_b_pipeline.py` may shift if any test asserts a specific tier value. The current tests don't assert anything per-ticker beyond tier presence; they should still pass. I'll re-run after the apply.

**Verification:**
- After apply, the diff between old and new `universe.yaml` should be in the 33 ticker rows the merged review identified
- `python -m pytest -q` → 235 passing

**Checkpoint with Emanuel:** **YES.** I run `--dry-run`, paste the diff in chat, Emanuel approves, then I run `--apply`.

## Step 3 — Bulk-import manual mining data from Excel (1-1.5 hours)

**Goal:** populate the SQLite store with the friend's verified per-ticker mining inputs (production, AISC, cash cost, royalty rate, sustaining capex, D&A, interest, tax rate, reserve life, net debt, EBITDA) for the 56 active tickers that are currently blank.

**New file:** `scripts/backfill_manual_data_from_excel.py`

**Behavior per row in Excel `Screening Data` (rows 2-62, 61 tickers):**
1. Extract: ticker, then columns 9-19 (production_oz, AISC, cash_cost, royalty_rate, sustaining_capex, da, interest, tax_rate, reserve_life, net_debt, ebitda_ltm)
2. Map friend's ticker → our universe ticker (ARMN → ARIS.TO, RMS → RMS.AX)
3. Skip if our ticker is inactive (NGD)
4. Skip GOLD / FNV / FRES.L (not in friend's universe; legacy test fixtures)
5. **Auto-correct royalty/tax convention bug**: if value < 1, multiply by 100. Log the correction. Affects ~6 tickers based on my read of the screenshot (AGI, BGL.AX, DRD, EMR.AX, HOC.L, OBM.AX) — script auto-detects.
6. Validate: skip individual cells with `#REF!`, `#N/A`, blanks, or values that fail Pydantic. Log skipped cells.
7. Call `upsert_company_input(paths, ticker=our_ticker, values={...})` for each row's importable fields

**Output (`--dry-run`):**
```
Backfill summary
================
Tickers to import: 57 (of 59 active)
Skipped: NGD (inactive)
Royalty/tax auto-corrected: AGI, BGL.AX, DRD, EMR.AX, HOC.L, OBM.AX
Existing rows that will be overwritten: AEM (already updated AISC=1275, will be re-overwritten), KGC (no change), NEM (no change)
Cell errors / skips: PAF.L royalty=#REF! (skipped, other fields imported)

Per-ticker preview (first 5):
AAUC.TO: prod 575,000 / AISC 1,790 / cash 1,200 / royalty 0.06 / sus_cap 80 / da 90 / int 30 / tax 0.30 / RL 8 / nd 50 / EBITDA 1500
AAZ.L:   prod  30,000 / AISC 1,500 / cash   900 / royalty 0.03 / ...
...
```

**Behavior under `--apply`:**
- Calls `upsert_company_input` for each row
- Logs every successful upsert
- Logs every skipped cell with reason
- Final report: X tickers fully populated, Y partial (had cell errors), Z skipped

**Tests touched:**
- None directly (data, not code)
- After the run, full pytest re-run

**Verification after apply:**
- `python main.py status` should show `57/59 tickers fully populated; 0-2 partial; 0-2 blank`
- `python main.py tool-b` (uses YAML default 4000) should produce a parquet with most rows scored, not INCOMPLETE
- Open `/tool-b` and confirm the table shows numbers for ~57 tickers
- Compare top-10 with Excel `Top performers` top-10 — should be similar order

**Risks:**
- The friend's Excel might have data anomalies I haven't seen (negative production, zero shares, garbled cells). Script logs and continues per-cell rather than abort.
- If the import overwrites the manually-corrected AEM AISC (1275), it should still get $1275 because the Excel `AISC Verification!D5` is also $1275. I'll assert this in the dry-run output.

**Checkpoint with Emanuel:** **YES.** I run `--dry-run`, paste the per-ticker preview, Emanuel spot-checks 3-5 names against his Excel, approves, then I run `--apply`.

After Step 3, between commits: re-run `python main.py refresh` (foundation + tool-a + tool-b) so the published parquet reflects the new data.

## Step 4 — Split `best_target` into 4 scenario columns (2-3 hours)

**Goal:** stop emitting a misleading single "best target." Show the four scenarios separately, matching Excel `Top performers` columns AA (Peer P/E target), AC (Peak P/E target), AI (Peer FCF target), AK (Peak FCF target).

**Why now:** with most tickers having manual data after Step 3, the inflated "300%+ upside" headlines will be everywhere. Splitting into the four scenarios makes the workspace honest about which scenario the high upside comes from.

**Code changes:**

### `golden_vector/screening/targets.py`
- Keep computing `target_price_peer_pe`, `target_price_peak_pe`, `target_price_peer_fcf`, `target_price_peak_fcf` ✓ (already there)
- **Stop computing** `best_target_price_usd` and `best_upside_pct`
- **Drop** `target_price_peer_evebitda` and `target_price_peak_evebitda` — Excel doesn't compute target prices from EV/EBITDA at all. Keep `ev_ebitda` itself (the multiple) for context, drop the derived target prices.
- **Add four upside %** fields: `upside_peer_pe_pct`, `upside_peak_pe_pct`, `upside_peer_fcf_pct`, `upside_peak_fcf_pct`. Each = `(target - share_price) / share_price`.

### `golden_vector/screening/verdicts.py`
- `compute_tool_b_score` currently uses `best_upside_pct`. **Change to use `upside_peer_pe_pct`** — the most conservative scenario, also the friend's first headline column AB.
- Same formula shape: `100 * (0.7 * verdict_base + 0.3 * normalize(upside_peer_pe_pct))`. Just a different upside input.
- Rationale: Peer P/E re-rate is the "catch up to today's peers" scenario — least mania-baked, most defensible as a base case.

### `golden_vector/screening/pipeline.py`
- Update `TOOL_B_OUTPUT_COLUMNS`:
  - **Remove**: `target_price_peer_evebitda`, `target_price_peak_evebitda`, `best_target_price_usd`, `best_upside_pct`
  - **Add**: `upside_peer_pe_pct`, `upside_peak_pe_pct`, `upside_peer_fcf_pct`, `upside_peak_fcf_pct`
  - Keep: the four `target_price_*_pe` and `target_price_*_fcf` columns

### `golden_vector/serve/workspace.py` Tool B view
- Replace current "Best Target ($)" + "Upside %" columns with **four pairs**:
  - Peer P/E Target ($) | Peer Up %
  - Peak P/E Target ($) | Peak Up %
  - Peer FCF Target ($) | Peer FCF Up %
  - Peak FCF Target ($) | Peak FCF Up %
- 8 new columns instead of 2 — Tool B view becomes wider. Should still fit on a 1240px-wide layout (max-width of `main`).
- **Combined view**: keep simple — show only "Peer P/E Target" + "Peer Up %" (one scenario), with a hint linking to `/tool-b` for the full 4-scenario picture.

### Tests
- `tests/test_tool_b_pipeline.py`: update column-presence assertions
- `tests/test_persist_tool_b.py`: update parquet schema expectations
- `tests/test_workspace_app.py::test_workspace_tool_b_view_renders_only_tool_b_columns`: update column list expectations

**Verification:**
- `python -m pytest -q` → 235 passing (some test deltas expected to net to zero or +/- 1)
- Open `/tool-b` after running `tool-b` again — see 8 target/upside columns. Top 3 (KGC/AEM/NEM after backfill) should show realistic upsides like 11% / 80% / 14% / 100% instead of headline "618%."
- Compare new top-10 ordering with Excel `Top performers` top-10 — should be similar (won't be identical because we use Yahoo prices, friend uses GOOGLEFINANCE-cached prices)

**Risks:**
- Ranking will reshuffle because `tool_b_score`'s input changes from `best_upside_pct` (the max scenario) to `upside_peer_pe_pct` (the most conservative). This is the intent but worth a side-by-side check.
- Workspace tests for the Combined view may need a small update if the test expects "Best Target" string.

**Checkpoint with Emanuel:** **YES.** Before merging, paste a side-by-side: Excel top-10 vs new Python top-10. If something is wildly off, discuss before commit.

## Step 5 — Screening Parameters panel on `/tool-b` (2-3 hours)

**Goal:** a form at the top of `/tool-b` that lets Emanuel change 10 parameters with one click and instantly re-render the ranking. URL-parameter overrides — does NOT overwrite YAML or parquet. Lets him bookmark scenarios.

### How it works under the hood

When Emanuel submits the form (or visits `/tool-b?gold_price=4500&aisc_target=1600`):
1. Workspace reads URL params
2. Builds a temporary `ScreeningParamsConfig` overlaying the YAML defaults with overrides
3. Calls a new pure function `compute_tool_b_in_memory(...)` that does the Tool B math without persistence (no parquet write, no run_context, no manifest)
4. Renders the table from that in-memory DataFrame instead of from `state.latest_tool_b`
5. Shows a "Showing scenario: gold $4500, AISC <$1600..." caption when overrides are active
6. Provides a "Reset to defaults" link that strips all params

**Crucial property:** YAML stays as the user's house default. Parquet stays as the canonical snapshot. URL params are scenario tools, like changing the yellow cells in the Excel.

### Code changes

**Refactor (likely new file `golden_vector/screening/in_memory.py` OR extend `pipeline.py`)**:
- Extract the row-building loop from `execute_tool_b_pipeline` into a shared helper:
  - `_build_tool_b_rows(merged: DataFrame, app_config, gold_price, ...) -> list[dict]`
- Add `compute_tool_b_in_memory(app_config, manual_data, market_snapshots, gold_price) -> DataFrame` that:
  - Merges snapshots + manual data + reporting calendar (same as pipeline)
  - Calls `_build_tool_b_rows`
  - Calls `rank_tool_b_outputs`
  - Returns the DataFrame
  - Does NOT persist
- Refactor `execute_tool_b_pipeline` to call the new helper for the math, then add persistence on top

### `golden_vector/serve/workspace.py`
- New helper `_render_screening_params_form(current: ScreeningParamsConfig, overrides: dict) -> str` rendering 10 inputs
- New helper `_parse_screening_params_overrides(query: dict) -> dict` that pulls the 10 keys, validates ranges (e.g., gold_price > 0, percent fields ≤ 100), returns sanitized overrides dict
- Update `_render_tool_b_overview_page` to:
  - Parse URL params
  - If any overrides present, build a copy of `app_config` with `screening_params` overlaid, call `compute_tool_b_in_memory(...)`, use that DataFrame
  - If no overrides, use `state.latest_tool_b` (current behavior)
  - Render the form at the top
  - Render an "Active overrides" banner when params present
  - "Reset" link → bare `/tool-b`

### Form layout (matching the yellow cells in the friend's Summary & Parameters)

| Field | URL param | Type | Default source |
|---|---|---|---|
| Gold price ($/oz) | `gold_price` | number > 0 | YAML `default_gold_price_assumption` |
| Forward P/E target | `pe_target` | number > 0 | YAML `verdict_thresholds.strong_candidate_forward_pe_max` (8) |
| FCF Yield target (%) | `fcf_yield_target` | percent 0-100 | YAML `layer1_thresholds.fcf_yield_min` (15) |
| AISC target ($/oz) | `aisc_target` | number > 0 | YAML `layer1_thresholds.aisc_max` (1850) |
| Margin target (%) | `margin_target` | percent 0-100 | YAML `layer1_thresholds.margin_min` (50) |
| Reserve Life target (yrs) | `reserve_life_target` | number > 0 | YAML `layer1_thresholds.reserve_life_min` (6) |
| Net Debt/EBITDA target | `leverage_target` | number > 0 | YAML `layer1_thresholds.leverage_max` (2.5) |
| Tier 1 discount (%) | `tier1_discount` | percent 0-50 | YAML `jurisdiction_discounts.tier_1` (0) |
| Tier 2 discount (%) | `tier2_discount` | percent 0-50 | YAML `jurisdiction_discounts.tier_2` (15) |
| Tier 3 discount (%) | `tier3_discount` | percent 0-50 | YAML `jurisdiction_discounts.tier_3` (30) |

### Tests

**New tests in `test_workspace_app.py`:**
- `test_tool_b_view_with_no_overrides_uses_latest_parquet` — bare `/tool-b` matches existing behavior
- `test_tool_b_view_with_gold_price_override_recomputes` — `?gold_price=4500` produces different `forward_pe` for KGC than the parquet's 4000 baseline
- `test_tool_b_view_rejects_invalid_overrides` — `?gold_price=-5` returns 400 with friendly message
- `test_tool_b_view_renders_screening_parameters_form` — confirms 10 inputs render

**New tests in `test_screening_in_memory.py`** (new file):
- `test_compute_tool_b_in_memory_matches_persistent_pipeline` — same inputs to both produce identical DataFrames (modulo `source_run_id` and timestamps)
- `test_compute_tool_b_in_memory_respects_threshold_overrides` — overriding `aisc_max` to 1500 changes layer1_pass for tickers with AISC between 1500 and 1850

**Verification:**
- `python -m pytest -q` → 235 + new tests passing
- Open `/tool-b?gold_price=4500&aisc_target=1600` — see different ranking than `/tool-b`
- Click "Reset" → returns to baseline

**Performance**: in-memory recompute on each page hit. Target <500ms for 59 tickers (simple math, ~3-4ms per ticker). Will measure and report.

**Risks:**
- The refactor of `execute_tool_b_pipeline` to extract `_build_tool_b_rows` could break pipeline tests if the extraction misses a side effect. Low risk because the pipeline is already mostly pure.
- 10 inputs visible at once may feel busy. Acceptable for v1; can add a "show advanced" collapse later.

**Checkpoint with Emanuel:** none mid-step. After Step 5 ships, ask whether the Combined view should also get the panel (deferred per "out of scope" — but trivial to add if requested).

## Cross-cutting concerns

### Documentation
After Step 5, update `README.md`:
- New Tool B view's 8 target/upside columns
- Screening Parameters panel and how URL params work
- The friend's Excel as the canonical "operating manual" reference

### Commit cadence (one per step)
- `Step 1: Fix ARMN -> ARIS.TO Yahoo symbol`
- `Step 2: Sync per-ticker jurisdiction tiers from friend's Excel`
- `Step 3: Backfill manual mining data for ~57 tickers from Excel`
- `Step 4: Split best_target into 4 scenario columns matching friend's Excel`
- `Step 5: Add Screening Parameters panel to Tool B view`

After Step 5, full milestone merge `dev-vic` → `main` per CLAUDE.md workflow.

### Test count expectations
- Start: 235 passing
- After Step 1-3: 235 (no test changes)
- After Step 4: 235 ± 0-3 (column-list assertions update; net should be flat)
- After Step 5: ~242 passing (4 new workspace tests + 2 in-memory pipeline tests)

## Decision points where I will pause for Emanuel

1. **End of Step 2 dry-run**: I show the 33-row tier diff. Emanuel approves before I write `universe.yaml`.
2. **End of Step 3 dry-run**: I show the 56-ticker import preview. Emanuel spot-checks 3-5 names against his Excel, approves before I write SQLite.
3. **After Step 4 code-complete**: I show side-by-side of new top-10 ranking vs Excel `Top performers` top-10. If something is wildly off, we discuss before commit.

## Estimated total time

| Step | Time | Type |
|---|---|---|
| 0 — Safety | 5 min | git/backup |
| 1 — ARIS.TO | 15 min | config edit |
| 2 — Tier sync | 45 min | script + checkpoint |
| 3 — Manual data backfill | 1-1.5 hr | script + checkpoint |
| 4 — 4-scenario split | 2-3 hr | code + tests |
| 5 — Parameters panel | 2-3 hr | code + tests |
| **Total** | **6-8 hours** | |

Steps 1-3 can ship in one sitting (~2.5 hrs total) with a pause for Emanuel's eyeball mid-flight. Steps 4-5 are the substantial code work and would naturally land in a second sitting.

## What Codex should review

I'd specifically value Codex's challenge on:

1. **Is the Step 4 ranking change defensible?** Switching `tool_b_score` from `best_upside_pct` (max of 6) to `upside_peer_pe_pct` (single conservative scenario) is a directional choice. Should it instead be the average of the 4 scenarios, or the median? Or weighted by verdict?
2. **Is the in-memory recompute in Step 5 clean enough?** The refactor extracts `_build_tool_b_rows` from `execute_tool_b_pipeline`. Is the seam in the right place, or should the in-memory computation be a separate parallel implementation rather than a shared helper?
3. **Should the Combined view also get the Screening Parameters panel?** I deferred it. If users will mostly live on Combined, deferring is wrong.
4. **Does the friend-ticker mapping (ARMN → ARIS.TO, RMS → RMS.AX) belong in the import script only, or should there be a permanent mapping table somewhere?** Right now if the friend ever sends an updated Excel with the same ARMN/RMS labels, we'd have to remember to apply the mapping again.
5. **Step 3 auto-correction for the royalty/tax decimal-vs-percent bug**: should we silently fix on import, or surface a warning that requires confirmation per ticker? Silent fix is what I proposed but a strict reviewer might prefer the explicit confirmation.
6. **Anything I missed in scoping** — the merged review identified items I may have rolled together in Step 4 that should be separate steps.
