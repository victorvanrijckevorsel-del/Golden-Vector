# Claude Self-Review: Phases 1B + 2A + 2B (deep)

Date: 2026-04-23
Reviewer: Claude (Opus 4.7) — same author as the implementation. This is an honest self-critique.
Mode: Read-only review of the same scope I asked codex to review in `claude_review_request_phase_1b_2a_2b_deep.md`.
Purpose: produce a finding set that can be compared against codex's independent review.

To stay honest, I:
- Re-ran the full suite (208 passed) and a focused suite per phase.
- Wrote and ran fresh smoke checks in scenarios the unit tests don't exercise.
- Tried to question the plan, not just the code.
- Proposed concrete fixes for every issue, even small ones.

**One headline finding from the smoke check:** `/ticker/NEM` takes **27.8 seconds** to render on real data. The unit tests use small synthetic equity histories (~70 weeks); the real NEM history is ~6,000 daily rows × 25+ years. That's a real workspace usability failure that exists in the live product right now and that I didn't catch in any of the 208 tests. It's listed in detail in the holistic section.

---

## Phase 1B.1 — Source-verification editing in the workspace

### Code correctness

- The 11 hidden `field_name` inputs match `REQUIRED_MANUAL_FIELDS`. Confirmed by the existing `test_workspace_detail_shows_editable_verification_row_for_every_required_field`.
- POST validates `field_name` server-side against `REQUIRED_MANUAL_FIELDS`.
- `verification_status=` (empty) → the upsert API rejects with `ValueError("verification_status must be VERIFIED, ESTIMATED, or INCOMPLETE.")` → 400 with clean message. Confirmed by tracing the path.
- Pure-whitespace optional fields (`notes="   "`) are stripped to `""` and not included in the upsert. Round-trip is safe.
- Invalid date `2026-13-99` → `_normalize_date_value` calls `pd.to_datetime(..., errors="raise")` → `ValueError` → 400 reaches the user as a flash message via the existing error path.

### Edge cases

- **No length cap on `notes`.** A user could paste a 10MB note. SQLite would store it; the page render time would balloon (and the SQLite blob would inflate the workspace's snapshot). Not a security concern, but a stability concern.
- **No CSRF token.** Localhost-only is the rationale, but if anyone ever runs `python main.py workspace --host 0.0.0.0` (which the CLI allows), the workspace is exposed without protection. Worth a deliberate decision.
- **Field-name churn.** If `REQUIRED_MANUAL_FIELDS` is later trimmed and the user has the form open, the next POST will 400. That's the right behavior, but a quiet 400 with no recovery hint is rough.

### UX / design

- **The 11-click problem is real.** A user batching verification across all 11 fields has to scroll 11 forms and click Save 11 times. For initial onboarding of a new ticker, that's painful.
- **The hint about "use the CLI for clear-fields" pushes the user to two interfaces.** Many users will never use the CLI and will instead overwrite blank values with placeholders.
- **The `<select>` for status doesn't tell the user what the three options mean.** A new user sees `VERIFIED / ESTIMATED / INCOMPLETE` with no inline definition.

### Plan questioning

The design sketch I wrote (and v3 implicitly endorsed) chose **inline form per row**. I now think that was wrong for two reasons:

1. The 11-click cost is high enough that I expect users to either skip the workspace and use the CLI, or skip verification entirely.
2. The duplication with the company form (which also shows per-field status badges) creates two places for the user to look. They will not consistently know which one is the "source of truth" for a given field.

A more honest design: a single combined "Tool B inputs + verification" panel where each field row carries the input, the status select, the date, the URL, and notes — saved together. Fewer clicks, single source of truth, no duplication.

### Suggested fixes

1. **Add a "Save all verification rows" button** that bulk-submits the 11 forms. One POST per field still, but a single user click.
2. **Inline definitions for the three statuses** as a small `<details>` block above the table.
3. **A real length cap on `notes`** (and `source_url`) — say 10,000 chars. Reject with 400.
4. **Document the localhost-only assumption** in the README and consider adding a CSRF token if `--host` is non-loopback.

### Per-sub-phase verdict

**`READY WITH MINOR CHANGES`.** Functional. The 11-click UX issue is the biggest weakness. Not a bug.

---

## Phase 1B.2 — Tool B manual-workflow polish

### Code correctness

- Badge derivation is correct for all five states (`MISSING`, `NEEDS VERIFICATION`, `ESTIMATED`, `INCOMPLETE`, `VERIFIED`). Walked the logic; confirmed `INCOMPLETE` correctly fires when the field has a value AND the verification_status is `INCOMPLETE`.
- `populated + missing == 11` by construction (the loop iterates exactly `COMPANY_FORM_FIELDS`).
- `verification_rows=None` defaulting to `[]` works.

### Edge cases

- **`royalty_rate = 0.0` is treated as "present".** `_format_form_value` for rate fields returns `f"{0.0 * 100:g}"` = `"0"`. Then `value.strip() = "0"` is truthy. So `0.0` rate counts as present → `NEEDS VERIFICATION` badge. That's semantically correct (zero royalty is a real value), just worth confirming.
- **A field cleared via `--clear-fields` then re-populated to `0.0`** behaves as expected: `MISSING` → `NEEDS VERIFICATION`.
- **Tax rate of 0% is treated as present**, same logic. Correct.

### UX / design

- The badge color palette I chose (green / amber / red / grey / red) is loosely intuitive but not labeled. A new user has to learn it.
- The readiness summary line is dense: "2/11 fields populated · 1 verified · 0 estimated · 0 explicitly incomplete · 9 missing." Five numbers in one line. Could be a small grid instead.
- "Explicitly incomplete" reads weird. The word "incomplete" is doing two jobs (the verification status + the natural-language meaning of "not done"). Maybe rename to "marked incomplete" or "flagged-incomplete."

### Plan questioning

Codex's first review flagged that "the company form badges + the verification table both show status." I shipped them both anyway. **Re-examining now, this is a real product flaw.** A user looking at a row sees a badge in the company form ("VERIFIED") and the same status echoed in the verification table below. That's not a "two views, one truth" pattern — it's just visual repetition. The user has to think twice about which one to update.

The right answer is probably the consolidation I proposed in 1B.1: merge the company form and the verification table into one editable row per field with all six columns (value, status, date, URL, notes, save).

### Suggested fixes

1. **Add a tiny inline legend** ("● Verified  ● Estimated  ● Incomplete  ● Missing") so the user doesn't have to memorize colors.
2. **Rename "explicitly incomplete" to "marked incomplete"** to reduce overload.
3. **Consolidate the company form and verification table** in a future pass.

### Per-sub-phase verdict

**`READY WITH MINOR CHANGES`.** Functionality is correct. The duplication-with-verification-section issue is real but isn't blocking — it's a refactor opportunity.

---

## Phase 1B.3 — Notes polish

### Code correctness

I traced the two-pass sort on the test fixture `[(OPEN,t=1), (DONE,t=2), (OPEN,t=3), (WATCH,t=4)]`:
- Pass 1, ascending by `(status_order, updated_at)`: `(OPEN,1), (OPEN,3), (WATCH,4), (DONE,2)`.
- Reverse: `(DONE,2), (WATCH,4), (OPEN,3), (OPEN,1)`.
- Pass 2, stable sort by status only: `(OPEN,3), (OPEN,1), (WATCH,4), (DONE,2)`.

Result: OPEN bucket newest-first, then WATCH, then DONE. ✓

But this is **overengineered.** A single sort with a key like `(status_order, -updated_at_int)` would do it in one pass. The two-pass approach works because Python's sort is stable, but it requires the reader to think carefully. I should refactor this.

### Edge cases

- A note with `note_status="PARKED"` (not in `status_order`): `status_order.get(...)` returns 3 → sorts to bottom. ✓
- A note with `note_text=""`: blocked at `add_stock_note` insert time. ✓
- A note containing `<script>alert(1)</script>`: rendered through `_fmt_text` which uses `escape()`. Safe.
- **A note with a 50,000-character body**: would render as one giant `<td>`, breaking the table layout. No length cap.
- **A ticker with 1,000 notes**: would render all 1,000 inline. The page would be enormous. No pagination. Real issue.

### UX / design

- The status badge color choice (green/amber/grey) is fine for OPEN/WATCH/DONE, but again no inline legend.
- The summary line "3 note(s) total · 1 open · 1 watch · 1 done" duplicates information the table already shows at a glance for small N. For large N it becomes useful. Acceptable.
- The hint pointing to `manual-note list --ticker NEM` for the "full history" implies the workspace doesn't show all notes. But it actually does. Misleading.

### Plan questioning

Plan v3 said "do not overbuild this. Just make it comfortable and clear." I think I went a touch beyond that — the two-pass sort and the colored badges are nice but not strictly necessary. A simple `ORDER BY note_status, updated_at DESC` rendered as a plain table would have shipped faster and been just as usable for 8 tickers × ~5 notes each.

### Suggested fixes

1. **Refactor the two-pass sort** into a single-pass sort with a tuple key. Drop ~10 lines.
2. **Add a soft length cap** on `note_text` — say 5,000 chars — server-side rejection at `add_stock_note`.
3. **Drop the misleading `manual-note list --ticker` hint** or rephrase it as "exportable via CLI" since workspace already shows all notes.
4. **Add note pagination** if any ticker actually accumulates >50 notes. Defer until that happens in practice.

### Per-sub-phase verdict

**`READY WITH MINOR CHANGES`.** Works correctly. The two-pass sort is overengineered. No length cap is the only real risk, and only at extreme sizes.

---

## Phase 1B.4 — Overview search / filter / sort

### Code correctness

- Sort direction bug from the development cycle has been fixed. Confirmed: `_present_or_missing` bakes direction into the key; no `reverse=True`. Sort by `tool_a_score` puts NEM (92) before AEM (70) before GOLD (50). ✓
- Mixed-case ticker sort: not applicable (all live tickers are uppercase). Test fixture is also uppercase. Acceptable.
- Empty filter values: `if r["profile_label"]` excludes empty strings from the dropdown. ✓
- URL injection in search: confirmed via smoke check 2 — `<script>alert(1)</script>` is rendered as `&lt;script&gt;alert(1)&lt;/script&gt;`. Safe.
- URL injection in profile/verdict/confidence filter: confirmed via smoke check 3 — bogus values supplied via query string don't appear in the dropdown because the dropdown only renders values present in the actual data. Safe.

### Edge cases

- **Filter producing zero rows + non-default lens active**: smoke check 1 confirms the page renders the empty-state row, the lens hint, and the sort-disabled hint. Looks coherent.
- **Reset link** strips the lens too (`<a href="/">Reset</a>`). I think that's right but worth confirming this is the desired behavior.

### UX / design

- **Search box at 8 tickers is overkill.** The user can scan 8 rows visually. Search becomes valuable around 50+ tickers. For now it's harmless but adds visual weight to the filter form.
- **The five-control filter bar (lens / search / profile / verdict / confidence / sort) is a lot of widgets** for an 8-row table. The form takes more vertical space than the table.
- **Sort dropdown shown but ignored** when a non-default lens is active. The hint is below the form. A user who doesn't read the hint will be confused why "Sort by: Tool A Score" doesn't take effect. Better: visually disable (gray out) or hide the dropdown when non-default lens is selected.

### Plan questioning

Plan v3 §1B.4 said "search by ticker, filter by Tool A profile if useful, filter by Tool B verdict, filter by confidence if useful, sort by ticker / Tool A rank / Tool B rank." I implemented all of it. **For 8 tickers, this is overkill.** A simpler design: just sortable column headers on the existing table. The filter form's value-add at 8 tickers is near zero.

I built it because the plan asked, not because the universe needs it. The right judgment call would have been to ship the simpler version and add filters when the universe grows.

### Suggested fixes

1. **Visually disable the sort dropdown** when `lens != composite`. Add `disabled` attribute. The hint becomes redundant but the affordance is correct.
2. **Hide the search box until the universe has more than ~20 tickers.** Or move it to a `<details>` block.
3. **Consider replacing the filter form with sortable column headers** for the v1 universe size.

### Per-sub-phase verdict

**`READY WITH MINOR CHANGES`.** Works. The visual weight vs. value-add is poor at 8 tickers. Sort-dropdown-not-disabled is a minor UX trap.

---

## Phase 2A — Multi-lens ranking

### Code correctness

Walked the live universe under `upside_torque`:

| Ticker | delta | up | down | up−down | upside_torque |
|---|---|---|---|---|---|
| BTG | 1.98 | 2.33 | 1.52 | 0.81 | **1.60** |
| FRES.L | 1.30 | 1.02 | 0.53 | 0.49 | **0.64** |
| KGC | 1.70 | 1.10 | 1.28 | -0.18 | 0 |
| AEM | 1.59 | 1.16 | 1.30 | -0.14 | 0 |
| NEM | 1.48 | 1.16 | 1.29 | -0.13 | 0 |
| DPM.TO | 1.38 | 1.20 | 1.50 | -0.30 | 0 |
| FNV | 1.11 | 0.41 | 1.01 | -0.60 | 0 |
| GOLD | – | – | – | – | None (score-ineligible) |

Smoke check confirms BTG appears before FRES.L in `/?lens=upside_torque`. ✓

`cleanliness` correctly uses only ELIGIBLE windows. Verified by walking `_compute_cleanliness` — it iterates `(6m, 12m, 3y)` and skips windows where `window_status_<x> != "ELIGIBLE"`. If all three are LOW_OBSERVATION, returns None.

`_finite_float` handles `numpy.nan` (via `pd.isna`) and `pd.NA` (via `pd.isna`). Safe.

Mutation risk: `apply_lens` calls `result.to_dict(orient="records")` which creates new dicts. Lens compute reads but doesn't write to them. The original DataFrame is also copied via `.copy()` first. No mutation. ✓

### Edge cases

- `up_beta_core == down_beta_core` exactly: `upside_torque` = 0, `fragility` = 0. Both correct.
- `total_volatility_52w = 0.001`: `signal_ratio = 1 - residual/0.001` could go negative for any residual > 0.001. Clamped to 0. Lens = `mean_r2 × 0`. The clamp catches it but the result is semantically meaningless. Worth a min-vol floor (e.g. exclude when `total_vol < 0.05`).
- All `r_squared` columns are exactly 0.0: `cleanliness = 0 × signal_ratio = 0`. Right answer? A ticker with R²=0 has no explanatory power; treating it as "perfectly unclean" (0 score) is correct, but maybe it should be `None` ("can't be evaluated") instead.

### UX / design

- **Tool A Score column AND Lens Score column both visible always**: when `lens=composite`, the values are identical. That's redundant. Should hide the Lens Score column when `lens=composite`, OR rename the Tool A Score column to "Composite Score" and keep one column.
- **The lens picker is a `<select>` with five options** (composite + four lenses). For a beginner founder, that's five things to learn. A "Default" / "Show me upside" / "Show me fragility" / "Show me clean signals" labeling would be more intuitive than the technical lens IDs.
- **Lens hint text appears below the filter form**, well below the table. A user picks a lens, scrolls down to see the new ranking, and may never read the hint above the table. Consider moving the hint inline with the column header or above the table.

### Plan questioning

Plan v3 picked four lenses. **`cleanliness` is the most abstract one.** "How much of weekly movement is explained by gold" is a concept a beginner founder would need explaining every time. I'm not sure it earns its place. Alternatives that would have been more useful:

- **`reliability`** (deferred per v3) — confidence_score directly. "Show me the most trusted signals." Very intuitive.
- **`risk_adjusted`** (deferred) — "Tool A score per unit of downside vol." Sharpe-like, intuitive.

I'd consider dropping `cleanliness` and shipping `reliability` instead.

The auto-sort UX (lens != composite ⇒ sort by lens, ignore user's sort dropdown) is **subtle in a bad way**. Plan v3 endorsed it. I'd push back: either (a) make sort always primary and lens always secondary, OR (b) hide the sort dropdown entirely when a non-default lens is active. The current half-state is the worst.

### Suggested fixes

1. **Hide the Lens Score column when `lens=composite`**, or rename the Tool A Score column to "Composite" and keep one column.
2. **Replace `cleanliness` with `reliability`** in the v1 lens set. Document the swap in the plan.
3. **Add a min-vol floor** to `cleanliness` (or `reliability` if I swap) — return None when `total_vol < 0.05`.
4. **Move the lens hint inline with the column header** as a tooltip / `<small>` text. Or above the table, not below the filter form.
5. **Visually disable the sort dropdown** when non-default lens is active (matches 1B.4 finding).

### Per-sub-phase verdict

**`READY WITH MINOR CHANGES`.** Math is correct. UX is subtle-bad. The choice of `cleanliness` over `reliability` is a real plan decision worth revisiting.

---

## Phase 2B — Rolling 12M structural-delta chart

### Code correctness

The chart has its own provenance gate (`source_run_id`) separate from foundation alignment. Walked the path:
- `_render_visual_panels` aligned branch → calls `_render_beta_history_panel(foundation_aligned=True)` → if structural file matches, render with overlay.
- `_render_visual_panels` non-aligned branch → calls `_render_beta_history_panel(foundation_aligned=False)` → if structural file matches, render beta line, suppress overlay with note.

Confirmed by tests T15, T22 and by reading the code. ✓

Empty-state language is split:
- "Out of Sync" reserved for `source_run_id` mismatch (provenance failure)
- "Not Available Yet" for missing file or no eligible 12M rows

### Edge cases

- **2 ELIGIBLE rows**: `_build_beta_history_svg` would render a 2-point polyline. Looks fine but minimum-viable.
- **All ELIGIBLE rows have the same `structural_delta`**: my code does `if delta_hi == delta_lo: delta_hi = delta_lo + 1.0` to avoid divide-by-zero. ✓
- **Corrupted parquet**: `_safe_load_structural_history` catches exceptions and returns empty DataFrame. The empty triggers "Not Available Yet" panel. **Silent failure** — no log, no surface.
- **Ticker in structural file but not `tool_a_latest.parquet`**: handled at `_render_tool_a_panel` (returns "no Tool A output" message before reaching the chart). ✓

### UX / design

- **`_align_gold_to_history_dates` is O(N×M).** Documented in the implementation summary. With 1,300 history dates and 6,500 gold dates, that's ~8.4M numpy comparisons. Smoke check shows /ticker/NEM took **27.8 seconds** end to end. Most of that is `build_structural_ticker_data` (which iterates every weekly date and computes regressions for the entire 25-year history per page hit), but the gold alignment is also a contributor. **`np.searchsorted` would reduce the gold alignment to milliseconds.**
- **Gold-overlay rebasing is genuinely confusing.** I rebase gold onto the same y-axis as the beta line, scaled to the chart's beta range. The result is visually a second line, but its values are gibberish — the y-axis labels apply to beta, not gold. A user looking at the chart sees two lines but cannot read the gold value. **This is bad UX I shipped against my own plan-v3 better judgment.**
- **Date labels at first/last only.** For a 25-year series this is severely insufficient. The user has no orientation as to where, say, 2008, 2013, or 2020 fell. Year ticks would be a substantial improvement.
- **Watermark above chart works** (verified by reading the code: `watermark + overlay_note + svg`).

### Plan questioning

Plan v3 promised "single line is enough for v1; gold overlay is fine if provenance-safe." I shipped the overlay because the plan allowed it. **Looking at the result, I should have stuck with just the beta line.** The overlay rebasing is a worse-of-both-worlds compromise: it doesn't show real gold values, and it adds visual clutter that the user can't decode.

The two-language empty-state distinction ("Out of Sync" vs "Not Available Yet") is a plan-v3 choice. **I think it's wrong.** A non-technical user does not distinguish "stale" from "not yet generated." Both mean "no chart." A single fallback shape with a state-specific reason sentence would be clearer.

The chart's placement at the bottom of `_render_visual_panels` means it appears below volatility and exploratory ladder. Given the chart is the most paper-aligned visual on the entire detail page, **it deserves higher placement** — probably right after the structural windows table.

### Suggested fixes

1. **Drop the gold overlay entirely.** Replace it with a small inset showing the gold price chart over the same period as a separate panel below. Or just remove it and add it in a future visual pass with proper twin-axis support.
2. **Replace `_align_gold_to_history_dates` with `np.searchsorted`.** ~10-line change.
3. **Add year-tick labels** to the chart's x-axis. Compute year boundaries from the date range, render a small text label at each year that's a multiple of 5 (so you don't get 25 labels for a 25-year series).
4. **Unify the empty-state language.** Pick one shape (say "12M Rolling Structural Delta — Not Available") and put the specific reason sentence inside. Drop the "Out of Sync" wording.
5. **Move the chart panel above the volatility and exploratory panels.** It's the highest-value visual; it should appear near the top of the visual section.
6. **Cache the foundation snapshot loading** (or pass it through ticker-page rendering) so the detail page doesn't reload it every hit. See holistic section.

### Per-sub-phase verdict

**`NEEDS CHANGES`.** The chart math and provenance work. The gold overlay rebasing is genuinely bad UX. The chart placement is suboptimal. Performance (via the surrounding render path) is unacceptable on real data.

---

## Holistic review

### Critical: detail page render time on real data

The biggest single finding from my smoke check: **`/ticker/NEM` rendered in 27,806ms.** The unit tests use small synthetic equity histories (~70 weeks) so this never surfaced. On real data:

- `_load_tool_a_detail` calls `load_latest_foundation_snapshot(include_equity_histories=True)` which loads ~60K equity rows.
- Then `build_structural_ticker_data` iterates every weekly bar across NEM's 25-year history, computing per-window structural metrics for every weekly date (so ~1,337 weeks × 3 windows = ~4,000 regressions per page hit).
- Then `compute_horizon_returns_for_ticker` does another large pass.
- Then the chart loads `tool_a_structural_latest.parquet` and aligns gold via O(N×M).

**Each detail page hit recomputes structural data that `tool-a` already computed and persisted.** The published `tool_a_structural_latest.parquet` is exactly the answer; the workspace re-derives it from source instead of reading it.

**Fix**: change `_load_tool_a_detail` to read from published artifacts (`tool_a_structural_latest.parquet`) rather than recompute from `load_latest_foundation_snapshot`. The scatter and exploratory panels need the underlying weekly returns, but those can be loaded from `data/runs/<refresh_run_id>/snapshots/usd_equities.parquet` (filtered to one ticker) without reloading the entire foundation snapshot or recomputing structural metrics.

This is a blocking issue for daily workspace use. 27 seconds per page click is unacceptable.

### Plan v3 conformance

Walked plan v3 §6 (T1–T23) and §7 (acceptance criteria). Every test exists, every criterion is met. The implementation is faithful to the plan. The issues I'm flagging are with the **plan**, not with the conformance.

### Provenance integration across phases

The two-channel system (`source_run_id` for structural, `snapshot_refresh_run_id` for foundation) **works as designed**. Smoke check confirms `FOUNDATION_AHEAD` correctly suppresses scatter/up-down-beta/exploratory while still rendering the chart (because chart provenance is independent).

But the abstraction is **sneaky**. A reader of the workspace code has to internalize that there are two separate provenance systems for two different kinds of artifacts. A unified "alignment context" object that carries both ids and answers questions like `is_chart_safe_to_render()` and `is_scatter_safe_to_render()` would be cleaner.

### Lens module purity

Searched for `lens_score` references: only in `golden_vector/serve/lenses.py`, `golden_vector/serve/workspace.py`, and `tests/test_lenses.py`. No persistence, no model code, no CLI. ✓

### Test fixture sprawl

`tests/test_workspace_app.py` is 1,467 lines with 30 tests and 5 helpers (`_write_latest_foundation_snapshot`, `_write_latest_outputs`, `_write_structural_history_file`, `_make_tool_a_row`, `_call_wsgi_app`). The helpers couple in subtle ways — `_make_tool_a_row` and `_write_latest_outputs` both produce Tool A rows but with different default fields. A future test author has to read both to know which to use.

**Fix**: split into `tests/test_workspace_overview.py`, `tests/test_workspace_detail.py`, `tests/test_workspace_forms.py`. Move the helpers into a shared `tests/workspace_helpers.py`.

### Workspace state model

`WorkspaceState` is now 10 fields; `ToolADetailState` is 6. They're getting wide. Both are still cohesive (state is grouped by who reads it), but `ToolADetailState` mixes derived data (weekly_series, structural_window_metrics) with raw inputs (gold_history) and provenance (structural_history_12m). A future split into `ToolARawState` + `ToolADerivedState` might help, especially after the recompute-vs-read refactor above.

### Performance and scaling

1. **Detail page recomputation** (above) — blocking.
2. Lens computation: `frame.to_dict(orient="records")` on 8 tickers, fine. At 800 tickers, ~50ms. Acceptable for v2; would need vectorization at v3.
3. SVG polyline with 1,300 points: rendered fine in browsers I checked. Beyond ~10,000 points, native SVG starts to choke.

### Trust / safety

- **CSRF**: no token. Localhost-only single-user. Acceptable for v1, but the CLI accepts `--host 0.0.0.0` which would expose the workspace. Need either a host check or a CSRF token. **Concrete fix**: refuse to start if `host != 127.0.0.1` and `--allow-non-loopback` is not also passed.
- **Input length caps**: none anywhere. Stability concern, not security.
- **HTML escaping**: walked through `_render_verification_section`, `_render_note_section`, `_render_overview_filters_form`. All user input goes through `escape()`. ✓
- **SQL**: `upsert_source_verification` builds `SET column = ?` with column names from a fixed allow-list. No injection path. ✓

### Architectural questions (challenging the plan)

1. **Workspace too monolithic**: 2,438 lines in one file. Should split — at minimum into `overview.py`, `detail.py`, `forms.py`, `panels.py` under `golden_vector/serve/workspace/`. The current single-file design was a habit, not a deliberate choice.

2. **Server-rendered SVG is fine for now** but won't scale beyond the current chart count. At v2 with multi-ticker compare + per-ticker beta + maybe a regime overlay, a client-side library (Chart.js or similar) is probably needed. Plan v3's "no JavaScript build step" rule was right for v1; need a path forward.

3. **Lens module placement**: `golden_vector/serve/lenses.py` is right for now. When the future compare view needs lens scoring (per v3 §4), move to `golden_vector/lenses.py` (top-level under the package, accessible from `serve/` and a future `compare/`).

4. **Dual-channel provenance** (`source_run_id` + `snapshot_refresh_run_id`) is the right model — they answer different questions. But the workspace code threads them as bare strings. Wrapping in a `RefreshContext` value object would clarify.

5. **Verification section duplicates state with the company form**: yes, real issue (already flagged in 1B.2).

6. **"Out of Sync" / "Not Available Yet" wording distinction**: I don't think it's worth the cognitive overhead. Already flagged in 2B.

### Things I think I'm wrong about

The five things I flagged as "least confident" in the review request, with my honest re-judgment:

1. **Chart's gold-overlay rebasing**: confirmed wrong. Drop it.
2. **Five-state badge taxonomy** on the company form: defensible but unlabeled. Adding a legend would justify it.
3. **Lens auto-sort when non-default**: subtle-bad UX. Either commit to disabling the sort dropdown or to making sort primary.
4. **Two-path empty-state wording for the chart**: I think it's wrong. Single path, state-specific reason inside.
5. **Chart placement inside `_render_visual_panels`**: too low. Move up.

### Test-coverage gaps that span phases

I don't have tests for:
- Verification editing + active non-default lens (state combination)
- A ticker that has a structural file mismatch AND a foundation mismatch simultaneously
- Detail page for a ticker with `score_eligibility_reason` other than `OK` or `UNACCEPTABLE_NORMALIZATION_STATUS` (e.g., `LOW_LINKAGE_STRUCTURAL_SIGNAL`, `INSUFFICIENT_ELIGIBLE_STRUCTURAL_WINDOWS`)
- A ticker that exists in the structural file but not in `tool_a_latest.parquet`
- Beta-history chart's behavior when `current_delta_core` is far outside the data range (gridline at, say, delta=10 when data is 1.5±0.3)

**Fix**: add five small tests covering these cases. Each is a 20-line test using existing helpers.

### Summary of severity

| Class | Count | Examples |
|---|---|---|
| Blocking | 1 | Detail page 27s render |
| Real bugs | 0 | (None found that aren't UX or perf.) |
| Concrete UX problems | 5 | Gold-overlay rebasing, lens auto-sort UX, chart placement, verification/company form duplication, two-path empty-state wording |
| Performance issues | 2 | Detail page recompute, gold-alignment O(N×M) |
| Plan-design concerns | 3 | `cleanliness` lens choice, search box at 8 tickers, 11-click verification |
| Stability concerns | 2 | No length caps, no CSRF on non-loopback |
| Architectural concerns | 3 | 2,438-line workspace.py, dual-channel provenance abstraction, future client-side chart need |

---

## Per-sub-phase verdicts

| Phase | Verdict | One-line justification |
|---|---|---|
| 1B.1 | `READY WITH MINOR CHANGES` | Functional. 11-click UX is the biggest weakness; not a bug. |
| 1B.2 | `READY WITH MINOR CHANGES` | Logic is correct. Duplication with verification table is real; not blocking. |
| 1B.3 | `READY WITH MINOR CHANGES` | Two-pass sort is overengineered. No length cap. Otherwise correct. |
| 1B.4 | `READY WITH MINOR CHANGES` | Sort/filter/search work. Visual weight vs. value-add is poor at 8 tickers. |
| 2A | `READY WITH MINOR CHANGES` | Math is correct. `cleanliness` choice and auto-sort UX are real plan concerns. |
| 2B | `NEEDS CHANGES` | Gold-overlay rebasing is bad UX I should not have shipped. Chart placement is wrong. Performance contributor. |

## Overall cycle verdict

**`NEEDS A FOCUSED FIX PASS`** — driven by:

1. **The 27-second detail page render is unacceptable for daily use.** This is the single most consequential finding and a real product-trust issue.
2. **The gold-overlay rebasing on the beta-history chart should be removed**, not just polished.
3. The 11-click verification UX should at minimum get a "Save all" affordance.
4. The lens auto-sort UX should commit one way (disable the sort dropdown) rather than half-measure.

Everything else is polish that can wait for a follow-up review cycle.

The implementation is **faithful to plan v3**. But plan v3 itself has weaknesses I should have flagged earlier — particularly the gold overlay, the cleanliness lens, the two-path empty-state wording, and the lens auto-sort UX. Those are mine to own.

---

## What this self-review is for

When codex finishes their independent review, place the two findings side by side:

- Where we agree: real issues, prioritize fixing.
- Where I found something codex missed: probable real issues that need confirmation.
- Where codex found something I missed: probably the highest-value findings; act on them.
- Where we disagree: discuss before coding.

I expect codex to find at least one issue I didn't, and to push back on at least one of my plan-questioning verdicts. If our reviews are identical, one of us was being lazy.
