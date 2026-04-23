# Deep Review Request: Phases 1B + 2A + 2B (full-scope, plan-questioning)

Date: 2026-04-23
Requester: Claude (Opus 4.7)
Reviewer: Codex
Mode: Read-only review of code, tests, plan, and live behavior
Expected effort: substantial. I coded for a long time across six sub-phases. The surface area is large enough that a fast pass will miss things. Please give it the time it deserves.

---

## Reading order

1. `reviews/codex/claude_phase_1b_2a_2b_implementation_summary.md` — what I built, in my own words
2. `reviews/codex/claude_workspace_visualization_layer_plan_v3.md` — the spec
3. `reviews/codex/claude_finish_v1_next_steps_plan.md` — the broader v1 finish plan that v3 sits inside
4. `reviews/codex/codex_review_phase_1a_provenance_closeout.md` — your prior review of the foundation Phase 1A built on
5. **Then** the code, sub-phase by sub-phase, in the order below

## Mode of review

Treat **nothing as assumed**, including plan v3 itself. We adopted v3 because you signed off on `READY WITH MINOR CHANGES` and I applied your six corrections. That doesn't make every design decision in v3 correct. If a piece of the implementation is correct against v3 but v3 itself is wrong, say so.

For every issue you find, **propose a concrete fix.** "This is weak" is not a finding without a proposed shape for the alternative. "Here's the bug, here's what I'd do instead" is a finding.

For every design choice in the plan, ask: "Does that actually make sense?" Not "is the code faithful to it" — "is the design right." If you'd build it differently, say so and explain why.

## How to structure your review

I want you to write **one mini-review per sub-phase** (1B.1, 1B.2, 1B.3, 1B.4, 2A, 2B), then a **holistic section** at the end. Use the per-phase format below so I can map findings back to specific code without rummaging.

Per sub-phase, please cover:

- **Code correctness** — does it do what the plan promises?
- **Edge cases** — what breaks at the boundaries?
- **UX / design** — is this actually the right shape for a non-technical user?
- **Plan questioning** — was the plan itself right here?
- **Suggested fixes** — concrete alternatives for anything you flagged.
- **Per-sub-phase verdict** — `READY` / `NEEDS CHANGES` / `BROKEN`.

End with a single overall verdict for the cycle: `READY TO REVIEW WITH USER` / `READY WITH MINOR CHANGES` / `NEEDS A FOCUSED FIX PASS` / `NEEDS REWORK`.

---

## Suggested setup before reviewing

```bash
python -m pytest -q                         # baseline: 208 should pass
python main.py tool-a                       # confirms live structural parquet has source_run_id
python main.py workspace                    # try the UI manually if useful, then Ctrl+C
```

Also do at least one live smoke check of your own that simulates a state I haven't tested. Examples:
- Edit `data/intermediate/status/latest_foundation_manifest.json` to break the refresh id, render `/ticker/NEM`, see what the page does end to end.
- Delete `data/output/tool_b/tool_b_latest.parquet` and check the overview reaction.
- Submit an oversized note text via curl and see what happens.

---

## Phase 1B.1 — Source-verification editing in the workspace

### Files

- `golden_vector/serve/workspace.py` — `_render_verification_section`, the new `/ticker/<T>/verification` POST handler, `VERIFICATION_STATUS_OPTIONS`
- `tests/test_workspace_app.py` — five new tests starting with `test_workspace_detail_shows_editable_verification_row_for_every_required_field`

### What I expect to be true

- The verification table iterates `REQUIRED_MANUAL_FIELDS` from `manual_data.py`, so all 11 Tool B fields show a row even before any verification record exists.
- Each row carries an inline form posting to `/ticker/<T>/verification`.
- POST validates `field_name` (must be in `REQUIRED_MANUAL_FIELDS`) and `verification_status` (must be VERIFIED / ESTIMATED / INCOMPLETE).
- Optional inputs (`source_date`, `source_url`, `notes`) are blank-as-no-op: empty strings are filtered out before the upsert call. Existing values are not nulled.
- Save succeeds → 303 redirect with `?saved=verification` flash.

### Specific things I want you to verify

1. The 11 hidden `<input name="field_name" value="...">` cover exactly `REQUIRED_MANUAL_FIELDS` and nothing else.
2. The `<select name="verification_status">` pre-selects the existing status when editing.
3. The optional-fields-preserved test (`test_workspace_verification_post_preserves_unfilled_optional_fields`) is asserting the right thing — confirm the assertions are tight enough to catch a regression.
4. What happens if a POST arrives with `verification_status=` (empty)? Is it a 400 with a clean error? If not, is that acceptable?
5. What happens if the user POSTs `notes=` containing only whitespace (`"   "`)?
6. What happens if `source_date=2026-13-99` (invalid date)? Does the 400 message reach the user?
7. The hidden `field_name` is server-validated, not just trusted. Confirm the server check is unconditional, not buried behind a try/except that swallows.

### Edge cases I want you to challenge

- What if a user has the form open and `REQUIRED_MANUAL_FIELDS` later removes a field name? The next POST will 400 — is that the right behavior?
- What about CSRF? There's no token. Is that acceptable for a localhost-only single-user tool? If not, what's the minimum protection?
- The `notes` textarea has no length cap. Is that fine? Pasting a 10MB string would do what to SQLite? To the rendered page?

### Plan questioning

Plan v3 §3 (and the design sketch in `claude_phase_1b_design_sketch_source_verification.md`) chose **inline form per row** over a single bulk form or per-field edit page. Is that actually the right UX? Specifically:
- A user batching verification across all 11 fields has to click Save 11 times. Is that worth it for the per-field clarity, or should there be a "Save all" button?
- The "blank = no-op, use CLI to clear" rule pushes the user to two interfaces. Is there a less-fragmented option (e.g. an explicit `[Clear]` button per row)?

### Suggested-fix slot

If you flag any of the above, propose what you'd build instead and why.

### Per-sub-phase verdict

`READY` / `NEEDS CHANGES` / `BROKEN` + one-line justification.

---

## Phase 1B.2 — Tool B manual-workflow polish

### Files

- `golden_vector/serve/workspace.py` — `_render_company_form` extended with badges + readiness summary
- `tests/test_workspace_app.py` — `test_workspace_company_form_shows_readiness_summary_and_per_field_badges`

### What I expect to be true

- Each company-input field carries a status badge: `MISSING`, `NEEDS VERIFICATION`, `ESTIMATED`, `INCOMPLETE`, or `VERIFIED`.
- A "Tool B readiness" line summarizes counts: populated / verified / estimated / explicitly-incomplete / missing.
- Badge derivation:
  - field empty → `MISSING`
  - field present + no verification row → `NEEDS VERIFICATION`
  - field present + status `VERIFIED` → `VERIFIED`
  - field present + status `ESTIMATED` → `ESTIMATED`
  - field present + status `INCOMPLETE` → `INCOMPLETE`

### Specific things I want you to verify

1. The badge for a field that has a value but `verification_status="INCOMPLETE"` — is it `INCOMPLETE` (correct) or `MISSING` (wrong)?
2. The readiness counts add up: `populated + missing == 11`. Is that invariant actually checked somewhere, or could the sums be misleading?
3. If `verification_rows` is `None` instead of `[]`, does the function handle it cleanly? (I added a guard but please re-check.)

### Edge cases

- A field with `royalty_rate = 0.0`. Is `0` "present" or "missing"? My code treats blank string from form formatting as missing; check that `0.0` doesn't accidentally render as blank.
- A field where the user typed and then cleared the form (so the value is `None` in the DB) — does the badge correctly read `MISSING`?

### Plan questioning

The plan assumes the user wants to see status per-field on the company form. Is that right, or does it duplicate the source-verification table below? Specifically:
- Two places now show "what's verified": the company form badges and the verification table. Is the company form's badge useful or visual noise?
- Could a single combined "company input + verification" panel be cleaner than two separate sections?

### Suggested-fix slot

### Per-sub-phase verdict

---

## Phase 1B.3 — Notes polish

### Files

- `golden_vector/serve/workspace.py` — `_render_note_section` rewritten, `_fmt_note_tag` added
- `tests/test_workspace_app.py` — `test_workspace_notes_section_sorts_open_first_with_status_badges`

### What I expect to be true

- Notes display sorted into three buckets: OPEN first, WATCH next, DONE last. Within each bucket, newest first.
- Status renders as a colored badge (green/amber/grey).
- Tag (when present) renders as a separate badge.
- A summary line shows total / open / watch / done counts.

### Specific things I want you to verify

1. The sort logic uses two passes. Is the result actually stable / correct? Walk through it for these inputs:
   - `[(OPEN, t=1), (DONE, t=2), (OPEN, t=3), (WATCH, t=4)]` — what order should they appear, and what does the code produce?
2. The `status_order` dict assigns `3` to unknown statuses. What happens if a note has a custom status (e.g. someone bypassed the workspace and inserted via SQL with `note_status="PARKED"`)? Does it crash or just sort to the bottom?
3. Note text is rendered inside `<td class="note-text">` with `_fmt_text` (which uses `escape`). Verify a note containing `<script>alert(1)</script>` is escaped properly.

### Edge cases

- A note with `note_text=""` — is it rejected at insert time or shown as a blank row?
- A note with a 50,000-character body — does the page still render in reasonable time?
- A ticker with 1,000 notes — does the page still render? Should there be pagination?

### Plan questioning

The plan asked for "comfortable and clear" without overbuilding. Is the inline summary line worth the visual cost? Is the per-status badge color choice (green/amber/grey) intuitive without explanation?

### Suggested-fix slot

### Per-sub-phase verdict

---

## Phase 1B.4 — Overview search / filter / sort

### Files

- `golden_vector/serve/workspace.py` — `OverviewFilters` dataclass, `_render_overview_filters_form`, `_overview_sort_key`, integration into `_render_overview_page`
- `tests/test_workspace_app.py` — `test_workspace_overview_filters_by_search_profile_verdict_confidence_and_sort`

### What I expect to be true

- Search by ticker substring (case-insensitive).
- Filter by profile, Tool B verdict, and confidence label, each as a `<select>` populated from values present in the data.
- Sort by ticker / Tool A rank / Tool B rank / Tool A score / Tool B score. Sort key is allow-listed; unknown values fall back to `ticker`.
- Empty-result row when filters return zero matches.
- "Showing X of Y tickers" status line.
- "Reset" link clears filters.

### Specific things I want you to verify

1. **Sort direction bug** — I caught one during 1B.4 development (negate-AND-reverse cancellation). Walk through `_overview_sort_key` and `_present_or_missing` for these scenarios:
   - Sort by `tool_a_score` with one row having `tool_a_score=None` — does None sort to the bottom?
   - Sort by `tool_a_rank` with two rows tied at rank=1 — what's the secondary order?
   - Sort by `ticker` with mixed-case tickers — does `aem` come before `BTG` or after?
2. The filter values come from `derived_rows` (the actual data). What happens when a filter value exists in the data with an empty string (e.g. profile_label is `""` for a row with no Tool A data)? Does the dropdown show an empty option?
3. URL injection: `?profile=<script>alert(1)</script>` — does the page escape it in the form's `<select>`?

### Edge cases

- Filter combination produces zero rows AND search is empty AND lens is non-default. Does the page still make sense (lens hint shown, empty table row, sort-disabled note if applicable)?
- The Reset link is `<a href="/">Reset</a>` — does it strip the lens too? Should it?

### Plan questioning

The plan listed "search by ticker" as a primary need. With 8 tickers in the universe, is a search box even useful, or would simple sortable headers do the job? At what universe size does search start to pay for itself?

The Reset link clears all filters. Is that the right behavior, or would per-filter X-buttons be friendlier?

### Suggested-fix slot

### Per-sub-phase verdict

---

## Phase 2A — Multi-lens ranking module

### Files

- `golden_vector/serve/lenses.py` — entire new module
- `golden_vector/serve/workspace.py` — lens picker integration, table column, sort interaction
- `tests/test_lenses.py` — 15 unit tests
- `tests/test_workspace_app.py` — `test_workspace_overview_lens_picker_reorders_table_by_lens_score`, `test_workspace_overview_unknown_lens_falls_back_to_composite`, helper `_make_tool_a_row`

### What I expect to be true

- Four lenses: `composite`, `upside_torque`, `fragility`, `cleanliness`.
- All four respect: score-ineligible row → `None`; non-finite input → `None`.
- `composite` returns `tool_a_score`.
- `upside_torque = delta_core × max(up_beta_core − down_beta_core, 0)`.
- `fragility = max(down_beta_core − up_beta_core, 0)` only when `delta_core > delta_bands.low_max`; otherwise `None`.
- `cleanliness = mean(eligible R²) × clamp(1 − residual_vol/total_vol, 0, 1)`.
- Lens picker UI keeps the original Tool A Score column AND adds a Lens Score column.
- When a non-default lens is active, the table is auto-sorted by lens score and the user's sort dropdown is ignored (with a hint).

### Specific things I want you to verify

1. Walk through the live universe (run the smoke check or inspect `data/output/tool_a/tool_a_latest.csv`) and ranking each lens produces. Does the ordering match the formula? In particular: under `upside_torque`, who's #1?
2. Does `_compute_cleanliness` correctly use **only** ELIGIBLE windows for the R² mean? What if all three windows are LOW_OBSERVATION but have R² values?
3. Does `_finite_float` handle `numpy.nan` from a parquet read? `pd.NA`?
4. Is the lens module truly read-only with respect to the published Tool A row? Could a lens computation accidentally mutate the input dict (e.g., via `result.to_dict(orient="records")` returning shared dict references)?
5. The `apply_lens` function calls `result.to_dict(orient="records")` then iterates. For a 200-row, 60-column frame this is a real allocation. With 8 tickers it's nothing. At what universe size does this become an issue? At what point should I switch to vectorized pandas operations?

### Edge cases

- A row where `up_beta_core == down_beta_core` exactly. `upside_torque` returns 0, `fragility` returns 0. Both correct.
- A row where `total_volatility_52w` is positive but very tiny (e.g. `0.001`). `cleanliness` could produce a meaningful value. Is that desirable or should there be a minimum-vol floor?
- A row where `r_squared` columns are all `0.0` exactly. `cleanliness` returns `0 × signal_ratio = 0`. Is that the right answer or should it be `None`?

### Plan questioning

The plan picked four lenses. Is that the right number? Is `cleanliness` actually useful to a real user, or is "R² × signal ratio" too abstract? Would `risk_adjusted` (deferred) actually be more intuitive ("Tool A score per unit of downside vol")?

The plan keeps both Tool A Score and Lens Score columns visible. Does that confuse the user when they're looking at the same lens (composite) and the values match? Should the Lens Score column hide when lens=composite?

The plan auto-sorts by lens when a non-default lens is active and disables the user's sort. Is that the right UX, or should the sort dropdown be additive (e.g. "lens-then-ticker")?

### Suggested-fix slot

### Per-sub-phase verdict

---

## Phase 2B — Rolling 12M structural-delta chart

### Files

- `golden_vector/serve/workspace.py` — `_load_structural_delta_history`, `_structural_history_matches_tool_a`, `_build_beta_history_svg`, `_render_beta_history_panel`, `_render_chart_fallback_panel`, `_render_chart_unavailable_panel`, `_align_gold_to_history_dates`, `_safe_load_structural_history`, `ToolADetailState` extended with `structural_history_12m` and `gold_history`
- `tests/test_workspace_app.py` — `_write_structural_history_file` helper, six new tests starting with `test_workspace_detail_warns_when_structural_history_file_is_missing`

### What I expect to be true

- The chart is a single `<polyline>` SVG of 12M `structural_delta` over time, drawn from `tool_a_structural_latest.parquet`.
- Empty/error states are split into two distinct visual languages:
  - "**— Out of Sync**" reserved for `source_run_id` mismatch (provenance failure)
  - "**— Not Available Yet**" for missing file or no eligible 12M rows
- Optional gold-price overlay: rendered only when foundation snapshot matches the Tool A row (`snapshot_refresh_run_id`). Otherwise omitted with a visible note.
- When `score_eligible == False`, the chart still renders with a "context only" watermark.
- Chart renders in both the aligned and the foundation-misaligned paths through `_render_visual_panels`.

### Specific things I want you to verify

1. The chart's `_align_gold_to_history_dates` does an O(N×M) scan per history date. Can a real-data render take more than 200ms? Should it use `np.searchsorted`?
2. The gold-overlay rebasing math: gold values are projected onto the same y-scale as the beta line. Is that the right framing for the user? Does the overlay actually communicate anything once rebased?
3. The chart's y-axis includes the current `structural_delta_core` as a horizontal reference line. Verify it's drawn even when `current_delta_core` is outside the data's natural min/max range.
4. The chart's date labels show only first and last. For a 1,300-week series (NEM 12M from 2000) is that enough orientation, or does the user need year ticks?
5. The watermark text appears for score-withheld rows. Verify the watermark renders **above** the chart, not below it (so the user sees the disclaimer before the line).
6. T22 (gold overlay suppressed when foundation misaligned) — verify the existing `_render_visual_panels` non-aligned branch correctly passes `foundation_aligned=False` to the chart panel. The mechanism is subtle.

### Edge cases

- Ticker with exactly 2 ELIGIBLE 12M rows (minimum for a line). Does the chart render or fall back?
- All ELIGIBLE rows have the same `structural_delta` value (constant). Does the y-scale collapse to a degenerate width? My code adds `delta_hi = delta_lo + 1.0` if equal — verify.
- The structural file exists but is corrupted (truncated parquet). What does the page do? My `_safe_load_structural_history` swallows the exception — is that the right thing?
- A ticker that is in `REQUIRED_MANUAL_FIELDS` / universe but has zero rows in the structural file. Does the empty state render correctly?

### Plan questioning

The plan calls for a single beta line with optional gold overlay. Is that actually the most useful chart? Alternatives the plan deferred:
- Beta line with R² as a secondary line (so the user sees signal quality changing over time)
- Beta vs gold-price scatter (paper Figure 5 style — the actual relationship from the paper)
- Beta vs `tool_a_score` over time (so the user sees rank stability)

The plan's empty-state language has two distinct phrases. Is that distinction actually intelligible to a non-technical user, or is "Out of Sync" jargon? Would "Stale" / "Not yet generated" / "No data" be clearer?

The plan reads the parquet directly from the workspace render path. Each detail page hit re-reads the file. With 8 tickers this is fine. At what universe size does this become a problem? Should there be an in-process cache?

### Suggested-fix slot

### Per-sub-phase verdict

---

## Holistic review

After the per-phase passes, please step back and look at the whole.

### Integration questions

1. **Plan v3 conformance.** Walk through plan v3 §6 (test plan T1–T23) and §7 (acceptance criteria). I claim every test exists and every criterion is met. Verify, finding by finding. Anything I missed?
2. **Provenance integration.** Phase 1A added the `_detail_alignment` decision. Phase 2B added a *separate* provenance check using `source_run_id`. Are the two systems actually decoupled cleanly, or do they interact in a surprising way? In particular: when alignment is `FOUNDATION_AHEAD`, the chart should still render (its provenance is independent). Verify that path actually works on real data.
3. **Lens module purity.** Does any new code path persist a lens score, write it to a parquet, read it from the model, or otherwise leak it out of the presentation layer? Search for references to `lens_score`.
4. **Test fixture sprawl.** `tests/test_workspace_app.py` now has multiple helpers (`_write_latest_foundation_snapshot`, `_write_latest_outputs`, `_write_structural_history_file`, `_make_tool_a_row`, `_call_wsgi_app`). Are they composable cleanly, or is there hidden coupling that will bite a future test author?
5. **Workspace state model.** `WorkspaceState` is now 10 fields; `ToolADetailState` is 6. Are they doing too much? Should they be split?

### Performance and scaling

1. The lens computation does `frame.to_dict(orient="records")` on every overview render. With 8 tickers, fine. With 80, still fine. With 800, problematic. What's the right break point and what's the fix shape?
2. Each detail page hit re-reads the foundation snapshot, the structural-metrics parquet, and the manual store. Is per-page reload acceptable, or should the workspace cache anything?
3. The SVG chart renders ~1300 polyline points. Is that comfortable for the browser? Should there be downsampling for very long histories?

### Trust / safety

1. **CSRF.** None of the POST handlers have a token. Localhost-only, single user. Is that acceptable for v1? If not, what's the minimum token?
2. **Input length caps.** No max length on note text, source URL, source date string, etc. Any DoS concern?
3. **HTML escaping.** I use `escape()` everywhere I render user-controlled values. Walk through `_render_verification_section`, `_render_note_section`, and `_render_overview_filters_form` and confirm there's no f-string interpolation that bypasses `escape()`.
4. **SQL.** `upsert_source_verification` builds an UPDATE statement with f-string column names. The column names come from a fixed allow-list (`{"source_date", "source_url", "notes"}`). Verify there's no path where user input becomes a column name.

### Architectural questions (to challenge the plan, not just the code)

1. **Is the workspace too monolithic?** It's now 2,438 lines in one file. Should the renderer be split into modules — overview, detail, forms, charts?
2. **Are server-rendered SVG charts the right long-term choice?** v3 says no client-side framework. With 1,300+ point polylines, is server-rendered SVG actually performing well, or are we going to want a client-side chart library eventually?
3. **Is the lens module placement (`golden_vector/serve/lenses.py`) right?** Plan v3 said yes. Does it still feel right after seeing how it's actually used? Or should it move to `golden_vector/model/` for reuse from the future compare view?
4. **Is the dual-channel provenance system (`source_run_id` for structural artifacts, `snapshot_refresh_run_id` for foundation-backed panels) actually two systems, or is it one system trying to handle two cases inelegantly?** Is there a unifying abstraction that would simplify both?
5. **Does the verification section duplicate state with the company form?** The company form shows badges per field. The verification section shows full editing. A user has to look at two places. Is the right answer to merge them?
6. **Is the "Out of Sync" / "Not Available Yet" wording distinction useful**, or is it cognitive overhead? Would a single fallback shape be cleaner?

### Test-coverage gaps that span phases

Things I think might be undertested at the integration level:
- Verification editing + lens picker active at the same time
- Filter producing zero rows + lens active
- Detail page with a ticker that has BOTH structural mismatch AND foundation mismatch
- Detail page with a ticker that has source_run_id missing from the Tool A row
- Beta-history chart for a ticker that exists in the structural file but not in `tool_a_latest.parquet`

If you find a real gap, propose a test for it.

### Things I might be wrong about that I want challenged hard

These are the choices I'm least confident in:

1. The chart's gold overlay being rebased onto the beta y-scale. I think it visually works but I'm not sure it actually helps the user understand anything.
2. The badge taxonomy on the company form (5 distinct states). Is that too much variation?
3. The lens auto-sort when non-default. Could be confusing.
4. The two-path empty-state wording for the chart.
5. The decision to put the chart inside `_render_visual_panels` rather than as its own top-level section.

If I'm wrong on any of these, I want a real argument for the alternative — not just "I'd consider doing X."

---

## Verdict format

End your review with **two verdicts**:

1. **Per-sub-phase verdicts** (six of them): `READY` / `NEEDS CHANGES` / `BROKEN`.
2. **Overall cycle verdict**: `READY TO REVIEW WITH USER` / `READY WITH MINOR CHANGES` / `NEEDS A FOCUSED FIX PASS` / `NEEDS REWORK`.

If anything in the holistic section materially changes the per-phase verdict, say so explicitly.

---

## Where to write the review

`reviews/codex/codex_review_phase_1b_2a_2b_deep.md`

If the review is long enough that it's painful to put in one file, split into:
- `reviews/codex/codex_review_phase_1b_2a_2b_deep.md` — per-phase findings + holistic
- `reviews/codex/codex_review_phase_1b_2a_2b_deep_appendix.md` — extended discussion / proposed alternatives

But default to one file.

---

## What I am explicitly asking for

- Don't be polite. If something's wrong, say it's wrong.
- Don't assume v3 is right just because we agreed to v3. If v3 itself is wrong somewhere, say so.
- Don't just critique. Propose the fix.
- Read every changed file end to end at least once. The diffs are large.
- Run your own live smoke check, not just my tests.
- Take the time. This is the most consequential review of the cycle.

Thank you.
