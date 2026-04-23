# Phase 1B Design Sketch — Source-Verification Editing in the Workspace

Date: 2026-04-23
Author: Claude (Opus 4.7)
Status: Internal design note. Not for codex review (yet). Written while Phase 1A is in codex's queue, to enable a fast start once Phase 1A clears.
Scope: Implements the existing v1 finish plan §5.1 "source-verification editing in the workspace."

---

## What exists today

| Surface | Behavior |
|---|---|
| **SQLite store** (`source_verification` table) | (`ticker`, `field_name`) primary key; columns `verification_status`, `source_date`, `source_url`, `notes`, `created_at_utc`, `updated_at_utc` |
| **CLI** (`manual-data set-verification`) | Writes one (ticker, field_name, status) row at a time, with optional source_date / source_url / notes / `--clear-fields` |
| **Workspace render** ([workspace.py:1029](golden_vector/serve/workspace.py#L1029)) | Read-only table with columns: Field, Status, Source Date, Source URL, Updated. Empty-state copy says "The CLI can still be used for detailed verification updates." |
| **Backing API** (`upsert_source_verification`) | Validates status ∈ {VERIFIED, ESTIMATED, INCOMPLETE}; INSERTs if no row, UPDATEs otherwise; null-on-blank for optional values (matches the company-form bug pattern from the holistic-fix pass — must be guarded against here) |
| **Canonical field list** | `REQUIRED_MANUAL_FIELDS` in `manual_data.py` — 11 fields: production_oz, aisc_usd_per_oz, cash_cost_usd_per_oz, royalty_rate, sustaining_capex_musd, da_musd, interest_expense_musd, tax_rate, reserve_life_years, net_debt_musd, ebitda_ltm_musd |

## Goal

A user opens the workspace, navigates to a stock, sees one editable row per Tool B numeric field with the current verification state pre-filled, edits the row inline, and saves — without dropping to the CLI.

## Design decisions

### Form shape: one inline form per field row

Rejected alternatives:
- *One bulk form for all 11 fields* — too big visually, error-prone, hard to give per-row feedback.
- *Edit-page-per-field* — too many clicks for a "maintain" workflow.

Chosen: **one row per Tool B field, each row carrying a small inline edit form**. Mirrors the existing company form's "many fields visible, edit + save" pattern.

### Field iteration source

Iterate `REQUIRED_MANUAL_FIELDS` from `manual_data.py`, not the rows already present in the store. This makes the table show all 11 fields whether or not the verification row exists yet — so the user can fill in a missing one without first running the CLI. Empty fields render with status `"–"` and a blank form pre-fill.

### Save semantics

Same null-on-blank fix used for the company form:
- `verification_status` is required (it is the primary state being recorded).
- `source_date`, `source_url`, `notes`: blank in the form → field is **not** included in the `values` dict passed to `upsert_source_verification`. Existing values are preserved. To clear a field, the user uses the CLI's `--clear-fields`. Document that limitation in the README, same as for the company form.

### Routes

- **GET `/ticker/<T>`** — already exists. The new editable verification table replaces the current read-only `_render_verification_table`.
- **POST `/ticker/<T>/verification`** — new. Body:
  - `field_name` (hidden, one of `REQUIRED_MANUAL_FIELDS`)
  - `verification_status` (required, ∈ {VERIFIED, ESTIMATED, INCOMPLETE})
  - `source_date` (optional, blank = no-op)
  - `source_url` (optional, blank = no-op)
  - `notes` (optional, blank = no-op)
- On success: 303 redirect to `/ticker/<T>?saved=verification` with a flash.
- On invalid status or unknown `field_name`: 400 with the existing error-page pattern.

## Code changes

| File | Change |
|---|---|
| `golden_vector/serve/workspace.py` | Replace `_render_verification_table` with `_render_verification_section(ticker, verification_rows)`. New POST handler in the WSGI app for `/ticker/<T>/verification`. New constant `VERIFICATION_STATUS_OPTIONS = ("VERIFIED", "ESTIMATED", "INCOMPLETE")`. New flash key `"verification"`. |
| `tests/test_workspace_app.py` | New tests (see test plan below). |
| `README.md` | One sentence under the Tool B notes: source-verification editing now lives in the workspace; the CLI remains available for `--clear-fields`. |

No changes to the SQLite schema, the CLI, the data contract, or the upsert API.

## Render shape

For each `field_name` in `REQUIRED_MANUAL_FIELDS`:

```
| Field name (humanized) | Status | Source Date | Source URL | Notes | Updated | Save |
| production_oz          | <select pre-selected> | <date input> | <text input> | <textarea> | <ts> | [Save] |
| aisc_usd_per_oz        | ...                  | ...          | ...          | ...        | ... | [Save] |
| ...                    |                      |              |              |            |      |        |
```

Each row is a tiny `<form method="post" action="/ticker/<T>/verification">` with a single Save button. Stylistically a compact horizontal form per row.

Page-section title stays "Source Verification" so the existing test's substring assertions are unaffected.

## Test plan

| # | Test | What it covers |
|---|---|---|
| V1 | GET `/ticker/NEM` shows 11 verification rows with current state pre-filled | Table covers full canonical field list |
| V2 | GET shows status `–` and blank fields for a field with no existing verification row | Empty-state pre-fill |
| V3 | POST with full payload writes the row and 303-redirects with `saved=verification` | Happy path |
| V4 | POST with only `verification_status` preserves the existing `source_date`, `source_url`, `notes` | Null-on-blank fix (matches the company-form regression pattern) |
| V5 | POST with `verification_status=BOGUS` returns 400 and the error message | Status validation |
| V6 | POST with `field_name=not_a_real_field` returns 400 | Field-name validation against `REQUIRED_MANUAL_FIELDS` |
| V7 | The existing detail-page rendering tests still pass | No regression on aligned/out-of-sync detail behavior |

Total: **6 new tests** + 1 retained.

## Watch-outs (codex-style risk list)

1. **Null-on-blank repeat.** The exact bug the holistic-fix pass closed for the company form will recur here unless the POST handler filters empty strings before calling `upsert_source_verification`. Same fix shape, same test pattern (V4).
2. **Unknown field_name from a stale form.** If a user has a form open and `REQUIRED_MANUAL_FIELDS` is later trimmed in code, the form would POST a now-unknown `field_name`. Validate server-side and 400.
3. **Source-date free text.** The form sends a `<input type="date">` value (`YYYY-MM-DD`). `_normalize_date_value` will parse it. If the user pastes garbage somehow, return 400 with a clean message.
4. **Verification status casing.** `upsert_source_verification` upper-cases internally. The form's `<select>` already submits canonical casing. Don't lower-case anywhere on the way through.
5. **Provenance interaction.** Source-verification editing does **not** depend on the foundation snapshot or the Tool A row. The Phase 1A `_detail_alignment` decision should not gate this section. Verify in tests (the verification section must still render even when Tool A is suppressed).
6. **Concurrency.** Same as the existing company form — single local user, single process. Not a concern for v1.

## Estimated effort

- Code: ~120 lines in `workspace.py` (new render + POST handler).
- Tests: ~150 lines.
- Total: 3–4 hours including running the suite and a quick smoke check.

## What I will not do in Phase 1B

- No bulk edit (one form for all 11 fields).
- No verification audit history / change log.
- No verification-status-driven UI styling beyond reusing existing flash classes.
- No re-architecture of the upsert API.

---

## Phase 1B implementation order (when Phase 1A clears)

1. Refactor `_render_verification_table` → `_render_verification_section` rendering 11 rows with inline forms.
2. Add the POST handler with null-on-blank guard.
3. Add `VERIFICATION_STATUS_OPTIONS` and `_render_verification_row` helper.
4. Add the six new tests.
5. Run focused tests (`tests/test_workspace_app.py`).
6. Run full suite.
7. README one-liner.
8. Done — proceed to Phase 1C (Tool B workflow polish).
