# Codex Deep Review: Phases 1B + 2A + 2B

Date: 2026-04-23  
Reviewer: Codex  
Mode: Read-only review of code, tests, plan, and live behavior

## Findings first

| Priority | Area | Finding | Why it matters | Concrete fix |
|---|---|---|---|---|
| `P1` | Phase 1B.1 | New verification rows visually default to `VERIFIED` | On a row with no existing verification record, the `<select>` renders only `VERIFIED / ESTIMATED / INCOMPLETE` and no placeholder. Browsers will show the first option as selected, which biases a non-technical user toward accidentally saving `VERIFIED`. That is a trust bug. | Add a disabled placeholder option for new rows: `Choose status`. Keep `required`. Preserve existing pre-selection only when a real status exists. Add a test for “new row renders blank placeholder, not VERIFIED by default.” |
| `P2` | Phases 1B.1 + 1B.2 | The workspace still forces CLI usage to clear manual values | The app now presents the workspace as the daily-use surface, but clearing company fields or verification metadata still requires `--clear-fields` in the CLI. That breaks the product direction and will confuse exactly the user this UI is meant for. | Add explicit clear controls in the workspace: either per-field `[Clear]` buttons or checkboxes like “clear source URL / notes / date” and “clear company field.” Remove the “use CLI to clear” dependency for normal workflows. |
| `P2` | Phase 2B | Corrupted structural-history parquet is silently treated as “Not Available Yet” | `_safe_load_structural_history()` swallows every exception and returns an empty frame. A genuinely broken parquet file gets presented as “missing or empty,” hiding a real artifact failure and sending the user to the wrong fix. | Return a structured load result (`ok`, `missing`, `no_rows`, `corrupt`) or attach an error string to `ToolADetailState`. Render a distinct “Could not read structural history file” fallback for corruption. |
| `P2` | Phase 2B | The rebased gold overlay is the weakest visualization choice in the cycle | The dashed gold line is rebased onto the beta y-axis, so the vertical relationship is not numerically interpretable. It shows co-movement only, but a non-technical user can easily read it as comparable magnitude. I do not think this improves understanding enough to justify the ambiguity. | For v1, remove the overlay from the same panel. If gold context is wanted, put it in a thin separate sparkline or secondary mini-panel beneath the beta chart. |
| `P3` | Phases 1B.1 + 1B.3 | No input length caps on verification text fields or notes | I live-tested a 50,000-character note. It saved and the page rendered a ~78 KB response. That is not catastrophic in a localhost app, but it is an unnecessary unbounded-input risk and will degrade page usability fast. | Add conservative server-side limits with friendly 400s, e.g. note text 4,000-8,000 chars, source URL 2,048 chars, verification notes 2,000-4,000 chars. Add tests. |

## Checks I ran

- `python -m pytest -q` → **208 passed**
- `python -m pytest tests/test_workspace_app.py tests/test_persist_tool_a.py` → passed
- Custom WSGI smoke checks in a temp workspace:
  - `verification_status=` → **400** with a clean message
  - invalid `source_date=2026-13-99` → **400** with a visible error on the page
  - whitespace-only `notes=   ` on verification POST → **303**, notes omitted as intended
  - `royalty_rate=0` remains present, not mistaken for missing
  - 50,000-character note saves and renders, proving the lack of input caps is real
- Live lens ordering from the real `tool_a_latest.csv`:
  - `upside_torque`: `BTG` #1, `FRES.L` #2, the rest zero or withheld
  - `fragility`: `FNV` highest negative-skew gap
  - `cleanliness`: `AEM` highest clean-signal score

---

## Phase 1B.1 — Source-verification editing in the workspace

### Code correctness

- The implementation does the core job it claims:
  - it iterates exactly `REQUIRED_MANUAL_FIELDS`
  - the hidden `field_name` is server-validated unconditionally before upsert
  - invalid `verification_status` produces a clean `400`
  - blank optional fields are filtered out before `upsert_source_verification()`, so existing `source_date / source_url / notes` values are preserved
  - whitespace-only notes are stripped to blank and therefore omitted, which is correct under the null-on-blank rule
- The “preserve unfilled optional fields” test is tight enough for the intended regression. It changes only `verification_status`, then asserts that all three optional fields remain exactly intact.

### Edge cases

- `verification_status=` currently returns a good `400` with a visible message. That part is fine.
- `source_date=2026-13-99` also returns a visible `400`. The error text is raw Python date-validation text (`month must be in 1..12, not 13`), which is understandable but not especially polished.
- If `REQUIRED_MANUAL_FIELDS` changes while a user has a stale form open, the next POST will `400`. That is acceptable.
- CSRF is absent. For a localhost-only single-user tool, I do **not** consider that a blocker for v1.
- The real problem is the default state for new rows:
  - on a row with no existing verification record, the `<select>` renders no blank/placeholder option
  - the browser will visually show `VERIFIED` as the first option
  - that creates accidental-trust bias

### UX / design

- Inline row editing is defensible. For this kind of slow-moving, per-field verification, I think the “one row, one save” shape is acceptable.
- What is **not** acceptable is telling the user “blank is no-op, use CLI to clear.” That splits one workflow across two interfaces and breaks the point of the workspace.

### Plan questioning

- Plan v3 was right to choose inline row editing over a separate per-field page.
- Plan v3 was **wrong** to accept “use CLI to clear” as a normal-state UX. The workspace is supposed to be the daily-use tool now.

### Suggested fixes

1. Add a placeholder option for new verification rows:
   - `Choose status`
   - `disabled selected hidden`
   - keep `required`
2. Keep the current pre-selection behavior only when a real row already exists.
3. Add explicit clear controls for `source_date`, `source_url`, and `notes`.
4. Wrap date-validation errors in a friendlier message such as `Source date must be a real YYYY-MM-DD date.`
5. Add server-side length caps for `source_url` and verification `notes`.

### Per-sub-phase verdict

**`NEEDS CHANGES`** — the workflow mostly works, but defaulting new verification rows visually to `VERIFIED` is a real trust bug.

---

## Phase 1B.2 — Tool B manual-workflow polish

### Code correctness

- Badge derivation is correct.
  - present + `INCOMPLETE` shows `INCOMPLETE`, not `MISSING`
  - `verification_rows=None` is safely handled
  - `royalty_rate=0` is correctly treated as present
- `COMPANY_FORM_FIELDS` matches `REQUIRED_MANUAL_FIELDS` exactly today, so the readiness summary is using the same 11-field basis as the verification section.
- The invariant `populated + missing == 11` is true by construction in the current loop, even though there is no explicit assertion test for it.

### Edge cases

- A cleared DB value (`None`) becomes `""` via `_format_form_value()` and correctly renders `MISSING`.
- The current implementation treats “field present but unverified” as `NEEDS VERIFICATION`, which is good.

### UX / design

- The per-field badges are helpful. They make the company form scannable without forcing the user down to the verification table immediately.
- The two-section split is slightly duplicative, but I think it is still acceptable:
  - company form answers “what is missing / ready?”
  - verification table answers “why do we trust this field?”
- The real UX gap is still clearing values from the workspace.

### Plan questioning

- I do **not** think the badges are visual noise. They earn their keep.
- I would not merge company inputs and verification into one giant form yet. That would likely become harder to scan, not easier.

### Suggested fixes

1. Add a small test that explicitly asserts `populated + missing == len(COMPANY_FORM_FIELDS)` so the summary can’t drift silently later.
2. Add clear controls to the company form so users are not sent back to CLI.

### Per-sub-phase verdict

**`READY`** — the core shape is good and useful. The remaining gap is mostly the broader clear-values UX problem, not badge logic.

---

## Phase 1B.3 — Notes polish

### Code correctness

- The two-pass sort works.
  - For `[(OPEN,1), (DONE,2), (OPEN,3), (WATCH,4)]`, the final order is `OPEN(3), OPEN(1), WATCH(4), DONE(2)`, which is correct.
- Unknown statuses fall to bucket `3` and do not crash.
- Note text is escaped via `_fmt_text()`, so a payload like `<script>alert(1)</script>` renders safely as text, not HTML.
- Empty note text is rejected at insert time by `add_stock_note()`.

### Edge cases

- A very long note is accepted and rendered in full. I confirmed this with a 50,000-character note.
- With many notes, the page will still render, but there is no guardrail or pagination.

### UX / design

- The summary line is worth it. It gives immediate workflow context without needing to parse the whole table.
- The `OPEN / WATCH / DONE` colors are intuitive enough.

### Plan questioning

- The plan was right not to overbuild this section.
- Pagination is not necessary for v1, but input caps are.

### Suggested fixes

1. Add a server-side note length cap.
2. If note volume actually grows later, paginate or collapse older `DONE` notes. Not needed yet.

### Per-sub-phase verdict

**`READY`** — the sorting and rendering logic are sound. I would tighten input caps, but I would not hold the note workflow itself as broken.

---

## Phase 1B.4 — Overview search / filter / sort

### Code correctness

- The earlier sort-direction bug is fixed.
- Missing numeric values sort to the bottom correctly.
- Unknown sort keys fall back safely to ticker.
- Empty-string profile/verdict/confidence values do **not** create blank dropdown options because the options are derived from truthy values only.
- Query-string values are escaped in the form rendering, so `?profile=<script>...` is safe.
- I also checked the combined empty-state path with a non-default lens: the page still renders the lens hint, the “sort ignored” hint, and the empty-table message cleanly.

### Edge cases

- Mixed-case ticker ordering would be Python’s default string ordering, but the actual ticker set is normalized uppercase in practice, so this is not a live issue.
- Reset currently clears the lens as well because it links to `/`. That is consistent with “reset everything.”

### UX / design

- Search is mildly overpowered for 8 tickers, but harmless.
- The form is understandable.

### Plan questioning

- For today’s universe size, sortable headers alone would probably have been enough.
- But the current form is still reasonable and future-safe if the universe expands.

### Suggested fixes

1. None required.
2. Optional later polish: hide the search box until the universe grows, or collapse filters behind a “Filter” button.

### Per-sub-phase verdict

**`READY`** — no meaningful correctness issue found here.

---

## Phase 2A — Multi-lens ranking module

### Code correctness

- The module is cleanly read-only. `lens_score` does not leak into persisted artifacts or model code.
- `_finite_float()` handles `NaN`, `pd.NA`, and non-finite values correctly.
- `cleanliness` uses only `ELIGIBLE` windows for its `R²` average.
- On the live universe, the lens orderings match the formulas.

### Edge cases

- `upside_torque` and `fragility` clamp at zero correctly when the regime gap goes the other way.
- `cleanliness` returning `0.0` when all eligible `R²` values are `0.0` is reasonable; I would keep that as `0`, not `None`.
- `apply_lens()` is fine at the current scale. I would not vectorize this for an 8-name universe.

### UX / design

- `fragility` and `cleanliness` are explained clearly enough in code and hints.
- The weakest UX choice here is the duplicate score columns when `lens=composite`. It is not wrong, but it is redundant.

### Plan questioning

- Four lenses is the right number for v1.
- I would still defer `risk_adjusted`.
- If I were simplifying one thing, I would hide `Lens Score` when the active lens is `composite`, because it duplicates `Tool A Score` exactly.

### Suggested fixes

1. Optional UX cleanup: hide the `Lens Score` column when `lens=composite`, or relabel it more explicitly as “Same as Tool A Score” if you want to keep the invariant visible.
2. No formula changes needed.

### Per-sub-phase verdict

**`READY`** — the code is correct, the formulas are bounded properly, and the module stays in the presentation layer.

---

## Phase 2B — Rolling 12M structural-delta chart

### Code correctness

- The core provenance split is correct now:
  - `source_run_id` gates the structural-history line
  - `snapshot_refresh_run_id` gates the foundation-backed overlay/panels
- The chart renders in the aligned case and still renders in the `FOUNDATION_AHEAD` case when structural provenance is okay.
- The current core-delta reference line is included in the visible y-range even when it lies outside the natural series min/max.
- The watermark is rendered before the SVG, so the disclaimer is seen before the chart.

### Edge cases

- Constant-delta history is handled by widening the y-range. Good.
- The chart will render with only two points. That is acceptable.
- The big problem is corrupted parquet handling:
  - `_safe_load_structural_history()` swallows every exception
  - `_render_beta_history_panel()` then treats that as “missing or empty”
  - the user gets the wrong message and the wrong fix
- `_align_gold_to_history_dates()` is O(N×M), but at this scale that is not a blocker.

### UX / design

- The beta line itself is good.
- The gold overlay is not. Rebased onto the same axis, it is visually suggestive but not quantitatively meaningful. I do not think that tradeoff is worth it for a non-technical user.
- The two empty-state labels (`Out of Sync` vs `Not Available Yet`) are fine and clearer than one generic fallback, provided the underlying states are classified honestly.

### Plan questioning

- Plan v3 was right to add the chart.
- Plan v3 was too optimistic about the gold overlay. I would not ship that exact overlay as the main comparison device.
- Reading the structural parquet on each request is acceptable for v1.

### Suggested fixes

1. Replace `_safe_load_structural_history()` with a structured load result that distinguishes:
   - missing file
   - no eligible rows
   - corrupt/unreadable file
2. Render a distinct corruption fallback with the right action.
3. Remove the rebased overlay from the main beta chart for v1, or move it into a separate mini-panel/sparkline.
4. Optional later cleanup: use `np.searchsorted()` in `_align_gold_to_history_dates()`.

### Per-sub-phase verdict

**`NEEDS CHANGES`** — the provenance work is strong, but the broken-file handling and the rebased overlay are still not the right final shape.

---

## Holistic review

### Plan v3 conformance

- Functionally, most of plan v3 landed correctly.
- The test matrix is in place and green.
- The acceptance criteria are **not fully complete** if read literally, because the summary itself still leaves README / architecture-map updates deferred.

### Provenance integration

- The dual provenance system is now decoupled cleanly enough.
  - foundation-backed panels use `snapshot_refresh_run_id`
  - the beta-history panel uses `source_run_id`
- That split makes sense because the artifacts are genuinely different.
- I do **not** think a unifying abstraction is necessary yet.

### Lens purity

- Confirmed: `lens_score` appears only in the serve layer and tests. It is not persisted.

### Test fixture sprawl

- `tests/test_workspace_app.py` is getting large, but the helpers are still understandable.
- I would split it later by concern (`overview`, `detail`, `forms`, `charts`) once this cycle stabilizes.

### Workspace state model

- `WorkspaceState` and `ToolADetailState` are getting fat, but still manageable.
- The real architectural pressure point is `workspace.py`, not the state dataclasses.

### Performance and scaling

- The current implementation is fine for the actual universe size.
- I would not optimize lens computation or per-request file reads yet.

### Trust / safety

- CSRF: acceptable risk for localhost v1.
- HTML escaping: good in the paths I checked.
- SQL column-name interpolation: safe because the allowed-field set is fixed in code.
- Input-size limits: still worth adding.

### Architectural questions

- `workspace.py` is now too monolithic for comfort, but I would not split it before the product shape settles.
- Server-rendered SVG remains a valid v1 choice.
- `golden_vector/serve/lenses.py` is the right location for now.
- Verification section + company badges are slightly duplicative but not wrong.

### Real integration gaps / undertested areas

I would add tests for:

1. New verification row renders a blank placeholder status instead of defaulting visually to `VERIFIED`.
2. Oversized note / verification text returns a friendly `400` once caps are added.
3. Corrupted structural parquet produces a distinct chart fallback, not “Not Available Yet.”

---

## Per-sub-phase verdicts

| Sub-phase | Verdict |
|---|---|
| 1B.1 | `NEEDS CHANGES` |
| 1B.2 | `READY` |
| 1B.3 | `READY` |
| 1B.4 | `READY` |
| 2A | `READY` |
| 2B | `NEEDS CHANGES` |

## Overall cycle verdict

**`NEEDS A FOCUSED FIX PASS`**

Why:

- The cycle is close.
- Most of the code works and the tests are strong.
- But there are still two product-level issues I would not wave through:
  1. new verification rows visually defaulting to `VERIFIED`
  2. the chart layer hiding corrupted structural artifacts and shipping a misleading rebased gold overlay

If those are corrected, I would expect this cycle to move to **`READY WITH MINOR CHANGES`** or possibly **`READY TO REVIEW WITH USER`** depending on the final UX choices.
