# Visual redesign Phases 3–4 — Codex review

**Review date:** 2026-08-10  
**Branch:** `dev-vic`  
**Commits reviewed:** `26640b7`, `05d439f`, `15497d2`, `51f643c`  
**Mode:** Read-only review; no implementation changes and no full-suite run  
**Pre-existing untracked file:** `naukri.md` — not touched

## Summary

The new `golden_vector/serve/ui/` package is pure presentation in the current tree: its modules import only `__future__` and `html.escape`; they do not import pandas, model state, workspace state, application data, or analytics code. The pilot and Phase 4 migrations preserve route statuses, content types, deterministic form controls/actions, table contracts, and query URLs in the reviewed fixture matrix.

Six findings remain. Two affect the approved semantic/accessibility contract directly; three are shared-component or test-hardening problems; one is a small undocumented copy regression.

## Findings

### 1. P1 — The containment fallback creates inaccessible scroll containers and can clip the real table-region focus indicator

**Evidence**

- `golden_vector/serve/static/css/tables.css:63-72` applies `overflow-x: auto` to every `section.panel`, `section.nested-panel`, `article.nested-panel`, and `.two-column > div`.
- Legacy bare tables in ticker detail/forms rely on those ancestors for horizontal scrolling, but those ancestors have no accessible name, region role, or `tabindex`. A keyboard user therefore cannot reliably focus the element that owns the horizontal scroll.
- Migrated tables are wrapped by a focusable `.table-region`, but many of those wrappers are themselves inside the fallback overflow ancestors. Examples include Candidate Finder nested panels, the Option Trading liquidity nested panel, and Portfolio's `.two-column > div` cells.
- `.table-region:focus-visible` draws its outline two pixels outside the wrapper (`tables.css:56-58`). An overflow ancestor can clip that descendant outline, contrary to plan §11.1's explicit “no clipped focus outlines” requirement.
- `table_region()` always adds `tabindex="0"` (`golden_vector/serve/ui/tables.py:13-20`), even when a small table does not overflow. Candidate Finder's three-column top-list tables and several small Portfolio tables therefore add unnecessary tab stops at widths where no scrolling exists.
- The browser evidence proves zero **body** overflow and proves one Tool B region can be focused and scrolled. It does not exercise the legacy fallback with a keyboard, focus-outline clipping inside an outer overflow ancestor, or non-overflowing regions.

**Impact**

The implementation has the inverse accessibility behavior in two cases: some tables that need scrolling do not expose a focusable scroll owner, while some tables that do not need scrolling are always inserted into the tab order. Nested overflow also risks hiding the shared focus indicator.

**Required correction**

- Do not use the entire panel/cell as an anonymous scroll fallback.
- Give each genuinely scrollable legacy table a dedicated, labelled, keyboard-focusable scroll wrapper, or finish migrating those bare tables to `table_region()`.
- Ensure a migrated `.table-region` is not nested inside another horizontal overflow owner that can clip its outline.
- Make keyboard focus conditional on actual overflow, or otherwise avoid adding non-scrollable small tables to the tab order.

**Focused regression checks**

- Keyboard-only horizontal scrolling of at least one legacy ticker-detail table.
- Visible, unclipped focus outline for nested Candidate Finder, Option Trading, and Portfolio regions.
- A non-overflowing table must not create a redundant tab stop.
- An overflowing table must remain focusable, labelled, and horizontally keyboard-scrollable.

### 2. P1 — Lab `STALE` states use danger, contradicting the mandatory §10.5 warning mapping

**Evidence**

- Plan §10.5 (`GOLDEN_VECTOR_VISUAL_REDESIGN_PLAN.md:544-557`) maps **Stale / carried forward / misaligned** to **Warning**.
- `golden_vector/serve/overview_lab.py:71-78` includes `STALE` in the statuses rendered with `notice("danger", ...)`.
- `golden_vector/serve/lab_curve_page.py:279-284` renders both `STALE` and `CELLS_STALE` as danger because only `UNKNOWN_SCENARIO` and `EMPTY` select warning.
- The comments and `pilot_self_review.md` explicitly describe stale artifacts as danger, so this is not an accidental typo in one call site; the implementation and self-review both diverge from the approved mapping.

**Impact**

The same freshness meaning receives a different severity from the approved product-wide rule. This weakens the design system's central promise that color/tone carries one consistent meaning.

**Required correction**

Map `STALE` and `CELLS_STALE` to warning. Keep corrupt, unreadable, failed, blocked, and schema-invalid states on danger as specified. Do not change backend states or invent a new threshold.

**Focused regression checks**

Add a parameterized state-to-tone test at the actual Lab render call sites. It should cover at least `STALE`, `CELLS_STALE`, `CORRUPT`, metadata failures, `EMPTY`, and `UNKNOWN_SCENARIO`.

### 3. P2 — Migrated tables do not complete the header-association part of the table accessibility contract

**Evidence**

- Plan §11.1 requires correct column/row header `scope` where tables use semantic headers.
- `golden_vector/serve/column_help.py:155-167` emits `<th>` without `scope="col"`; most migrated analytical tables use this helper.
- Several hand-written headers also omit scope, including Tool D's ticker header, Option Trading's Group/Tickers headers, Candidate Finder's builder headers, and Portfolio headers.
- Portfolio's correlation matrix emits header cells in both the header row and each body row (`golden_vector/serve/portfolio_page.py:294-324`) without distinguishing `scope="col"` and `scope="row"`.
- `table_region()` gives the surrounding region a name, but that does not establish every cell-to-header relationship inside a two-dimensional matrix.

**Impact**

Simple tables may be inferred correctly by browsers, but the correlation matrix and other richer tables do not satisfy the explicit contract and can be announced ambiguously by assistive technology.

**Required correction**

- Make the shared `help_th()` output a column header scope where appropriate.
- Add `scope="col"` to hand-written column headers.
- Add `scope="row"` to genuine row headers, especially the Portfolio correlation matrix.
- If any `help_th()` caller is not a column header, make scope an explicit helper argument rather than applying the wrong scope globally.

**Focused regression checks**

Assert scope relationships on one standard analytical table and on the Portfolio correlation matrix's row and column headers.

### 4. P2 — Two shared presentation APIs can emit unescaped attribute/content data despite the package's escaping contract

**Evidence**

- `golden_vector/serve/ui/status.py:28-31` inserts `extra_classes.strip()` directly into the `class` attribute. A quote in the supplied value can break out of that attribute. Current callers pass constants, but the shared helper itself is unsafe.
- `status_strip()` at `golden_vector/serve/ui/status.py:35-49` escapes labels but inserts each `value` directly as HTML.
- The package contract says trusted HTML fragments are identified through `*_html` parameters. `status_strip()` calls this raw field simply `value`, so its safety boundary is easy to misuse.
- The current Phase 4 caller happens to pass `_fmt_text()` output, which is escaped, so no current route injection was found.

**Impact**

The new reusable layer does not consistently enforce or clearly name its trust boundary. A later migration can introduce attribute or HTML injection while appearing to use the safe shared component system correctly.

**Required correction**

- Validate `extra_classes` as CSS class tokens or escape it for an attribute before interpolation.
- Either make status-strip values plain text and escape them inside the component, or explicitly name/type them as trusted HTML fragments.
- Preserve the intentional trusted-fragment behavior of parameters already named `lead_html`, `actions_html`, `body_html`, and similar.

**Focused regression checks**

Add hostile quote/markup inputs for `extra_classes`, status labels, status values, region ids, and region labels.

### 5. P2 — `tests/test_ui_components.py` is too shallow to protect the Phase 3–4 contracts

**Evidence**

- The file has no test for the Phase 4 `status_strip()` component at all.
- It tests the set of allowed notice-tone names but not the plan's backend-state-to-tone mapping. This is why the stale/danger mismatch remains green.
- It does not test `notice(extra_classes=...)`, escaping of that attribute, or the status-strip value trust boundary.
- The `table_region()` test only checks that four strings appear. It does not test empty/duplicate ids, a missing accessible name, header scope, conditional focusability, nested overflow, or actual keyboard scrolling.
- It does not lock the stronger `ui/` purity boundary. The existing all-serve static scan catches a limited list of arithmetic tokens and correctly includes subpackages, but it would not stop `ui/` from importing workspace/model/data modules and making state decisions through ordinary conditionals.

**Impact**

The suite proves basic markup shape, not the important architectural, semantic, and accessibility promises of the new component system. All focused suites can remain green while the approved tone mapping or presentation-only boundary regresses.

**Required correction**

Extend the focused tests with:

- `status_strip()` output, escaping, and accessible label coverage;
- state-to-tone tests at real render call sites;
- `extra_classes` safety;
- table-region accessibility and overflow behavior;
- a narrow import/AST boundary test ensuring `serve/ui/` cannot depend on app/model/workspace/data modules.

Do not replace current render-level route tests with component-only tests; both layers are needed.

### 6. P3 — The missing-snapshot branch silently drops visible copy

**Evidence**

- Before Phase 4, `_render_refresh_summary(None)` rendered a visible `Latest Market Snapshot` heading followed by `No validated local market-data snapshot is available yet.`
- `golden_vector/serve/overview_helpers.py:82-85` now renders only the neutral notice body. `Latest market snapshot status` survives only as the populated strip's ARIA label, not as visible copy in the missing-manifest branch.
- The saved contract fixture always has a foundation manifest, so `pilot_contract_diff.md` and the current contract matrix do not exercise this branch.

**Impact**

This is a small but real copy-contract change outside the documented Phase 3 exceptions. On Tool A/B/C/D with no foundation manifest, the message loses its visible section context.

**Required correction**

Restore equivalent visible context in the neutral notice or document and approve the copy deletion as an explicit exception. Add a direct missing-manifest render assertion.

## Contract verification performed

I built the current fixture-backed contract matrix in memory and compared it with `contracts_after_phase3.json`; no repository output was written. The 33 leaf differences were fully accounted for by:

- shared notice-class/tone migrations in Phase 4;
- Refresh Run / Snapshot As Of / Foundation Status moving from `h3` metric-card headings to visible status-strip labels;
- fixture-generated Portfolio lot ids;
- the intended Tool C/D warning class migration.

No unexpected route status, content type, table definition, deterministic form-control/action, or query-path difference was found. `git diff --check 26640b7^..51f643c` was also clean.

## Tests deliberately not rerun

Per review scope, I did not rerun the full suite or repeat the already-green focused suites. I relied on the recorded green suites and used source inspection plus one in-memory fixture contract comparison to cover gaps those suites do not test.

## Overall verdict

**Changes requested before treating Phases 3–4 as closed.** The architecture is moving in the right direction and the current `ui/` implementation is data-agnostic, but the containment fallback and stale-tone mismatch violate explicit approved requirements. Correct Findings 1–2 before further rollout; Findings 3–6 should be resolved in the same correction pass because they are small, shared-system fixes and will otherwise propagate into later migrations.
