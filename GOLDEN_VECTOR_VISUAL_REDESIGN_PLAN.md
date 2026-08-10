# Golden Vector Full Visual and Usability Redesign Plan

**Status:** Corrected and approved for implementation. Claude Code's repository audit corrections and Codex's five decision answers (2026-08-10) are applied inline; the correction record and final verdict live in Section 27. Implementation of Phases 0-8 is authorized on `dev-vic` from base commit `6c5015d`.

**Primary reviewer:** Victor

**Requested second review:** Claude Code

**Source brief:** `GOLDEN_VECTOR_VISUAL_REDESIGN_GUIDE.md`

**Prepared from:** repository guidance, current route/rendering code, the existing UI test suite, and live desktop/mobile inspection of the local workspace on 2026-08-10.

---

## 1. Executive decision

Golden Vector should receive one coherent, product-wide redesign rather than a palette-only restyle of isolated pages.

The planned direction is:

- a professional dark analytical workspace built from layered charcoal surfaces;
- restrained brass/gold used for brand identity, active navigation, and primary actions;
- separate semantic colours for positive, negative, warning, stale, missing, estimated, verified, informational, and blocked states;
- a grouped left-hand application navigation on desktop and an accessible menu drawer on smaller screens;
- compact institutional information density, with readable spacing and strong numerical alignment;
- one shared page shell, token system, component vocabulary, table system, form system, chart theme, and responsive strategy;
- no changes to calculations, formulas, model outputs, rankings, thresholds, data contracts, refresh behaviour, routes, query parameters, form semantics, or persisted artifacts.

This is intentionally a usability redesign of the existing product, not a rebuild in React, a new backend, or a new analytics project.

---

## 2. Approved product decisions

Victor has approved these as the default product decisions. Implementation proceeds with them unless repository evidence reveals a genuine safety conflict:

| Decision | Planned choice | Why |
|---|---|---|
| Scope | Complete shared redesign across every workspace route | A partial theme would leave the product fragmented and would not solve navigation or responsive problems. |
| Character | Calm institutional research terminal | Golden Vector should feel serious and trustworthy rather than decorative or game-like. |
| Navigation | Grouped left sidebar on large screens; drawer below the desktop breakpoint | Nine equal top tabs no longer express the product hierarchy and consume excessive mobile space. |
| Density | Compact by default, with generous section spacing | Dense tables are central to the product, but page sections still need breathing room. |
| Theme | Dark only for this milestone | A light/dark toggle would double the test and maintenance surface before the new system is stable. |
| Fonts | Local system font stacks only | The local workspace must remain fast, private, offline-capable, and free of CDN dependencies. |
| Framework | Retain the existing Python-rendered HTML and small local JavaScript helpers | A frontend-framework migration would create unnecessary behavioural and deployment risk. |
| Content | Preserve current wording during the visual migration | Copy changes can alter financial interpretation and should be reviewed separately. |
| Results | Continue showing all result rows; no silent truncation or pagination | This is an existing product rule and a trust requirement. |
| Mobile tables | Internal horizontal table scrolling; never whole-page horizontal scrolling | Comparisons must remain intact without hiding rows or columns. |

If Claude Code believes one of these choices is unsafe, it must document the repository evidence and correct the plan explicitly rather than silently changing direction during implementation.

---

## 3. Why the redesign is needed: measured current baseline

The current interface is functionally strong but visually behaves like one long analytical document. Live inspection found the following:

| Surface | Observed at a 1,280px viewport | Main implication |
|---|---:|---|
| Candidate Finder | Dense builder and multiple result views; mobile navigation stacks vertically | Establish clearer control/result hierarchy and replace wrapping top navigation. |
| Gold Sensitivity | Body width about 1,299px | Small but real page-level horizontal overflow. |
| Corporate Finance | Body width about 2,436px | The wide table controls the entire document width. |
| Gold Downside | Body width about 1,480px | Table containment is incomplete. |
| Corporate Resilience | Body width about 3,212px | The stress table creates extreme document overflow. |
| Option Trading | Body width about 1,511px | Liquidity tables exceed the application frame. |
| Portfolio | Body width about 3,331px; 17 tables, 25 forms, 22 disclosures | This is the most complex responsive and interaction surface. |
| Ticker detail (`NEM`) | 37 panels and 14 forms in one page | Recolouring alone will not create a usable hierarchy. |
| Lab and Scorecard | Fit the viewport | Useful simpler surfaces for checking that the shared system is not overbuilt. |

At a 390px viewport:

- the existing navigation becomes a roughly 333px-tall stack before page content begins;
- Candidate Finder avoids document overflow but spends most of the first screen on navigation and controls;
- Corporate Finance remains roughly 2,436px wide because its table widens the page;
- some navigation labels are visibly clipped when the page has wide content.

The final acceptance matrix also includes a 320px stress check even though 390px is the primary narrow-phone target.

The styling baseline is also fragmented:

- `golden_vector/serve/static/workspace.css` is 868 lines;
- it contains 107 hex-colour occurrences and 55 unique hex colours;
- a non-vendor presentation scan found 192 colour-literal occurrences and 69 distinct colours;
- 24 Python files emit HTML, with about 33 source-level table render sites, 20 form render sites, and 13 inline-SVG render sites;
- only two table sites currently use the explicit `.table-scroll` wrapper;
- current tables emit no `<caption>` and no `scope=` attributes;
- there are no `@media` rules in the main stylesheet;
- `--border` and `--paper` are referenced but undefined, so the affected declarations are discarded by browsers;
- `.flash-warning` and several other emitted component classes have no canonical styling rule;
- colour literals also appear in chart and tooltip rendering code: 86 occurrences in serve Python (61 of them SVG `fill=`/`stroke=` paint attributes) and exactly one in first-party JavaScript (`overlay-crosshair.js:35`); the only colour-bearing inline `style=` attribute interpolates a server-chosen series-colour variable rather than a literal;
- the audited 192-occurrence/69-distinct figure counts `workspace.css` plus serve Python plus first-party JavaScript, minus two HTML-entity false positives;
- `--positive`, `--negative`, and `--neutral` are defined in `:root` but never referenced; their values are re-hardcoded in chart code (`charts.py:82`);
- the interactive help dialog (`.help-panel`, z-index 1000) currently paints beneath both decorative tooltips (`.rug-tooltip`/`.overlay-tooltip`, z-index 9999) — the only three z-index declarations in the stylesheet;
- exactly one inline `<script>` exists (the Portfolio ticker-to-currency synchronizer, `portfolio_page.py:653-668`);
- every error page currently renders with Candidate Finder marked as the active navigation item (`http_helpers.py:37-43`);
- the shared shell currently exposes nine equal-weight wrapping tabs.

The current accent also sits just below WCAG AA for normal text in common uses (approximately 4.35:1 for white on `#b26700`, where 4.5:1 is required). The redesign therefore needs verified token contrast rather than a visual guess.

The exact pre-implementation Python regression baseline is **1,555 collected tests**. An independent focused UI/route/Portfolio/model-state run completed with **371 passing tests**. Because this milestone is presentation-only and the complete suite is unusually slow, implementation uses the proportional testing policy in Section 18.6 rather than requiring a full-suite baseline.

---

## 4. Scope and change budget

### 4.1 Default implementation allowlist

The redesign should normally change only:

- `golden_vector/serve/**`;
- UI-specific tests under `tests/`;
- this plan, the starting guide, architecture documentation, and milestone handoffs;
- optional static CSS and JavaScript files served from `golden_vector/serve/static/`.

### 4.2 Explicitly out of scope

The redesign must not change:

- calculations, formulas, scoring, eligibility rules, rankings, thresholds, or classifications;
- currency conversion, horizon definitions, financial assumptions, or source selection logic;
- ingestion, normalization, feature, model, screening, hedge, portfolio-computation, or persistence pipelines;
- model-state manifest shape, current-state resolution, freshness calculation, alignment calculation, or refresh publishing;
- Parquet/CSV/SQLite schemas or persisted values;
- route paths, HTTP methods, status codes, redirect targets, download semantics, query parameter names, or form field names;
- current defaults for presets, windows, gold scenarios, financial sources, option horizons, calculator sizing, or table order;
- the rule that all matching rows remain available;
- Portfolio loopback/privacy protections;
- the removed Combined view: it must remain removed and continue returning 404.

### 4.3 Separate-decision rule

If a visual improvement appears to require any item outside the allowlist, implementation pauses that item and records it as a separate product decision. Examples include:

- changing the default selected tab, window, lens, preset, or source;
- hiding a column or result by default;
- adding pagination;
- rewriting financial explanations;
- changing a warning threshold;
- adding a new aggregate, score, or chart calculation;
- moving analytics into browser JavaScript;
- adding a new dependency or externally hosted font/icon package.

### 4.4 No new dependency by default

The plan requires no new Python or JavaScript dependency. Golden Vector should continue to work from the current requirements and vendored DataTables assets. If an accessibility or screenshot tool is later proposed as a dependency, Victor must approve it separately.

---

## 5. Non-negotiable safety invariants

Every implementation phase must preserve all of these:

1. **Backend computes, serve renders.** New UI helpers may format or arrange values but may not perform financial arithmetic, fallback resolution, source choice, eligibility decisions, or ranking logic.
2. **Compute once, persist, serve reads.** The redesign must not add raw scans, models, joins, or aggregations to request handlers.
3. **One data-state truth.** Existing freshness/alignment/model-state summaries are reused; CSS classes must not introduce a second interpretation of those states.
4. **No mixed-currency or horizon changes.** The visual project cannot touch those contracts.
5. **Degraded data stays visibly degraded and excluded where the backend excludes it.** Styling must never make withheld or stale values look confidently ranked.
6. **No status by colour alone.** Every semantic state includes visible wording and, where useful, a shape/icon in addition to colour.
7. **No hidden failures.** Missing, empty, corrupt, stale, misaligned, and previous-schema states remain clear.
8. **All rows remain accessible.** A table may scroll inside its region, but the redesign may not silently truncate it.
9. **No real-data mutation during visual QA.** Write-path tests use temporary fixture stores. Manual browser review of the real workspace remains read-only.
10. **No external refresh during visual QA without explicit authority.** The live `Refresh all model data` button must not be clicked merely to test styling, because it triggers network-backed work.
11. **No body-overflow masking.** `overflow-x: hidden` on the document is not an acceptable fix; the layout and table container must actually contain their widths.
12. **Local/private operation remains intact.** No telemetry, analytics beacon, external font request, CDN, or remote asset is added.
13. **Selector meaning remains exact.** Window/horizon selectors that currently only choose persisted columns must remain display selectors; scenario/source controls that currently invoke an existing sanctioned recomputation path must retain that behaviour. The redesign may not make the former recompute or turn the latter into cosmetic filtering.

---

## 6. Complete route and workflow preservation matrix

This matrix is a release checklist, not just documentation. Each entry must have a render/route test and a browser smoke check where applicable.

| Route or route family | Method | Current purpose | Contract that must survive |
|---|---|---|---|
| `/` | GET | Candidate Finder home | Remains the home route and active discovery surface. |
| `/candidate-finder` | GET | Candidate Finder alias | Same capabilities as `/`, while generated links continue to respect the current base path. |
| `/tool-a` | GET | Gold Sensitivity overview | Search, structural-window selection, sorting/filtering, provenance, and benchmark rows remain intact. |
| `/tool-b` | GET | Corporate Finance overview | Search, source/rank basis, differences-only mode, scenario overrides, recomputation behaviour, target columns, and warnings remain intact. |
| `/tool-c` | GET | Gold Downside overview | Search, structural-window selection, table disclosures, sorting/filtering, and provenance remain intact. |
| `/tool-d` | GET | Corporate Resilience overview | Search, gold stress presets/custom price, financial source, scenario output, and flip table remain intact. |
| `/option-trading` | GET | Option Trading overview | Cached-snapshot language, horizon selection, liquidity tables, method disclosure, and candidate links remain intact. |
| `/portfolio` | GET | Portfolio workspace | Enabled and disabled states, summary, issues, analytics, positions, forms, and privacy boundary remain intact. |
| `/portfolio/reconciliation.csv` | GET | Reconciliation download | Content type, filename, no-cache behaviour, enabled/disabled response, and payload remain unchanged. Audit correction: a missing manifest entry raises `PortfolioStaleSchemaError` → `503`; the bodyless `404` occurs only when the manifest-named file itself is unreadable. Both outcomes remain as-is. |
| `/portfolio/lots` | POST | Add a position lot | All field names, validation, artifact rebuild, errors, and 303 redirect remain unchanged. |
| `/portfolio/lots/{id}/edit` | POST | Edit a position lot | Same validation, rebuild, and redirect behaviour. |
| `/portfolio/lots/{id}/delete` | POST | Delete a position lot | Same target semantics and rebuild behaviour; a visual danger style must not silently add or remove confirmation behaviour. |
| `/lab` | GET | Gold Scenario Analogs table | Bucket/horizon resolution, insufficient-data states, and drill-down links remain intact. |
| `/lab/dial/{ticker}` | GET | Lab curve detail | Scenario, benchmark, horizon, chart, diagnostics, and missing/stale states remain intact. |
| `/scorecard` | GET | Evidence Scorecard | Tested/accruing groups, verdict semantics, caveats, and compatibility states remain intact. |
| `/ticker/{ticker}` | GET | Ticker detail | Default lens, financial source, active/canonical window, explanations, charts, manual records, notes, and source verification remain intact. |
| `/ticker/{ticker}?lens=option-trading` | GET | Option Trading ticker lens | Option sizing state, benchmark-ETF vehicle exception, proxy fallbacks, and lighter non-miner page remain intact. |
| `/ticker/{ticker}/company` | POST | Manual company-input update | Blank-as-no-op, explicit clear checkboxes, numeric validation, return-state preservation, and 400/303 behaviour remain intact. |
| `/ticker/{ticker}/reporting` | POST | Reporting-calendar update | Date and note fields, blank-means-clear semantics, validation, and redirects remain intact. This deliberately differs from company-input blank-as-no-op behaviour. |
| `/ticker/{ticker}/verification` | POST | Source-verification update | Required-field allowlist, blank optional fields, clear semantics, placeholder status, validation, and redirects remain intact. |
| `/ticker/{ticker}/note` | POST | Add stock note | Text/tag/status limits, ordering, badges, errors, and redirects remain intact. |
| `/refresh` | POST | Start full model refresh from Candidate Finder | Safe `return_to`, status display, and asynchronous refresh behaviour remain intact. |
| `/option-trading/refresh` | POST | Start refresh (route currently unreferenced) | Audit correction: no form anywhere targets this route today (`render_option_refresh_control` is called only from Candidate Finder with `action="/refresh"`). Preserve the live route exactly and do not add a UI entry point for it. |
| `/hedge-readiness` | GET | Legacy compatibility route | Continues to redirect to `/option-trading`. |
| `/hedge-readiness/latest.md` | GET | Holdings-bearing report download | Continues to enforce Portfolio enablement and return the same download/403 behaviour; a missing report file returns the existing bodyless `404`. Audit note: neither `/hedge-readiness` route has any UI entry point — both are URL-only legacy contracts. |
| `/static/*` | GET | First-party and vendored assets | Path traversal protection, MIME allowlist, and cache policy remain intact. |
| `/favicon.ico` | GET | Empty favicon response | Continues to return 204 unless a separately reviewed asset change is approved. |
| unknown routes, unknown tickers/actions, and unsupported methods | mixed | Error handling | Audit correction: the app has no `405` and no `HEAD` support anywhere; every method mismatch (including `HEAD`) falls through to a `404` in one of two flavours — the generic `Page not found.` page or the scoped `Unsupported portfolio route.`/`Unsupported workspace route.` pages — and `/portfolio/lots*` checks the Portfolio-disabled `403` before the method check. The 400, 403, 404, 500, and 503 families remain understandable and status-correct; the route-matrix tests pin exactly this behaviour, and the redesign does not normalize status codes unless separately approved. |

### 6.1 Query-string contract inventory

The redesign must preserve query names, multiplicity, defaults, validation, and cross-control carry-forward behaviour.

| Surface | Parameters to preserve |
|---|---|
| Candidate Finder | `gold_price`, `fundamentals_source`, `beta_window`, `preset`, `custom`, `options_side`, `top_n`, repeated `criteria`, `direction_{criterion_id}`, `weight_{criterion_id}` |
| Gold Sensitivity | `search`, `window`, `saved` |
| Corporate Finance | `search`, `saved`, `rank_by`, `fundamentals_source`, `differences_only`, `gold_price`, `pe_target`, `fcf_yield_target`, `aisc_target`, `margin_target`, `reserve_life_target`, `leverage_target`, `tier1_discount`, `tier2_discount`, `tier3_discount` |
| Gold Downside | `search`, `window`, `saved` |
| Corporate Resilience | `search`, `saved`, `gold_price`, `fundamentals_source` |
| Option Trading overview | `option_horizon` |
| Portfolio | `saved` |
| Lab overview | `bucket`, `horizon` |
| Lab dial | `scenario`, `benchmark`, `horizon` |
| Ticker detail | `lens`, `window`, `fundamentals_source`, `saved`; option lens also preserves `side`, `horizon`, `bucket`, `size_mode`, `quantity`, and `budget` |

Critical state-carry tests must prove that changing one control does not erase unrelated active state. Existing hidden-input and URL-building helpers should be reused rather than reimplemented.

Audit corrections to this inventory (all current behaviour, to preserve exactly):

- Candidate Finder's three GET forms round-trip **every** unrecognised query parameter (repeated values included) via `_hidden_query_inputs`; preset links deliberately carry only `preset`/`gold_price`/`fundamentals_source`/`beta_window` and therefore reset custom Screen Builder state; `saved` is never read on Candidate Finder, so a ticker-save redirect that returns there shows no flash.
- Tool B reads `rank_by` only as a fallback when `fundamentals_source` is absent and never re-emits it, so legacy `rank_by` URLs survive exactly one round trip. `differences_only` is truthy only for `1/true/yes/on`.
- Tool D's form has **no hidden inputs**; its preset/reset links carry only `gold_price`, `search`, and `fundamentals_source`. On a Yahoo-source scenario failure it silently renders the `our`-source view while the URL still says `fundamentals_source=yahoo` (defect register D7 tracks the display mismatch).
- Ticker detail `return_to` carries **all** first-value query parameters except `lens` (kept only when it equals `option-trading`), with `saved` stripped on render; the option sizing form does **not** carry `window` (defect register D3).
- Invalid `beta_window` silently degrades to the cross-window blend; Lab `horizon`/`bucket` fall back silently (requested → default → first); `option_horizon` also accepts the configured most-liquid sentinel value.

---

## 7. Target experience principles

### 7.1 Decision first, methodology available

Each page should make the primary question clear within the first screen:

- what this tool answers;
- which data snapshot and scenario are active;
- whether the result is trustworthy/current;
- which action or comparison the user can make next.

Methodology remains available, but deep formula detail should not compete visually with the main decision. Critical caveats, active assumptions, missing-data messages, and stale/misaligned warnings remain visible and must not be buried in a disclosure.

### 7.2 Consistent page anatomy

Most overview pages should follow this sequence:

1. Page header: title, one-sentence purpose, and page-level actions.
2. Notice stack: only current actionable warnings/errors/success messages.
3. Compact data-status strip: snapshot date, refresh identity/status, and relevant source/scenario.
4. Scenario/control bar: filters, horizon, source, gold price, or presets.
5. Headline metrics where the page already has them.
6. Main comparison table or chart.
7. Secondary analysis.
8. Method/caveat disclosure.

This is a visual template, not permission to invent new metrics or reorder content whose current order is contractually tested without reviewing those tests.

### 7.3 Calm density

- Use compact controls and table rows on desktop.
- Use larger touch targets below the mobile breakpoint.
- Use section spacing to separate tasks rather than surrounding every sentence with a large card.
- Reserve elevated surfaces for meaningful grouping.
- Avoid gradients, glow effects, animated market-ticker treatments, neon colours, and decorative financial imagery.

### 7.4 Trust is visible

Freshness, source, verification, estimates, missing inputs, and withheld scores are first-class visual information. They must remain near the values or decisions they qualify.

---

## 8. Information architecture and application shell

### 8.1 Desktop navigation hierarchy

The left sidebar should use the existing route labels and active navigation IDs, grouped as follows:

**Discover**

- Candidate Finder

**Analyse**

- Gold Sensitivity
- Corporate Finance
- Gold Downside
- Corporate Resilience
- Option Trading

**Manage**

- Portfolio

**Research**

- Lab
- Scorecard

Grouping is presentational only. It must not change routes, route order semantics in tests without updating the intentional expectation, or Portfolio availability rules.

### 8.2 Shell structure

`golden_vector/serve/page_shell.py` should evolve from a wrapping tab bar into a semantic shell with:

- a keyboard-visible skip link to `#main-content`;
- a global `box-sizing: border-box` foundation inherited by all elements and pseudo-elements;
- a branded but restrained `Golden Vector` wordmark and `Gold-equities research` descriptor;
- an `<aside>` containing a labelled `<nav>`;
- `aria-current="page"` on the active route;
- an application header containing the current page label and the mobile menu button;
- `<main id="main-content" tabindex="-1">`;
- a content wrapper with `min-width: 0` so child tables cannot widen the application grid;
- an optional page/body identifier used only for layout modifiers and tests, not business logic.

The existing `_page_shell(title, body, active_nav=...)` signature should remain backward-compatible during migration. Optional presentation arguments may be added, but callers should not be forced into a simultaneous big-bang rewrite.

### 8.3 Responsive navigation behaviour

| Width | Navigation behaviour |
|---|---|
| `>= 64rem` (1,024px) | Persistent approximately 14-15rem sidebar. Main content occupies `minmax(0, 1fr)`. |
| `< 64rem` | Sidebar becomes a closed-by-default drawer launched from the app header. |
| `< 48rem` (768px) | Drawer uses most of the viewport width; content becomes single-column. |
| `< 30rem` (480px) | Page padding and gaps reduce, while controls retain at least a 44px touch target where practical. |

The drawer interaction must:

- use a real button with `aria-expanded` and `aria-controls`;
- move focus into the menu when opened;
- close on Escape and return focus to the trigger;
- close after navigation and when its backdrop is activated;
- prevent focus from becoming lost behind the open drawer;
- work with keyboard, mouse, and touch;
- honour `prefers-reduced-motion`.

No navigation label may become icon-only without an accessible and visible fallback. Icons, if used, are secondary cues rendered locally with `currentColor`.

### 8.4 Content widths

- The shell may support a wide analytical content maximum around 100-110rem.
- Text-heavy content should use narrower readable measures inside that frame.
- Tables may have an intrinsic minimum width, but that width belongs to an internal scroll region.
- No route may make `document.body.scrollWidth` exceed the viewport by more than rounding tolerance.
- Do not solve overflow by hiding the document overflow.

---

## 9. Design-token specification

`workspace.css` currently has a small root token set surrounded by many literals. The redesign should create one canonical token file and eliminate undocumented colour/spacing copies.

### 9.1 Proposed CSS structure

Keep `/static/workspace.css` as the stable public entrypoint so existing tests and page-shell loading remain simple. It may become an ordered import manifest for:

```text
golden_vector/serve/static/css/
  tokens.css       # canonical colour, type, spacing, shape, layer, motion tokens
  base.css         # reset, body, headings, links, focus, utilities
  shell.css        # app frame, sidebar, header, drawer, skip link
  components.css   # panels, cards, notices, badges, buttons, disclosures
  forms.css        # labels, inputs, selects, checkboxes, validation, action bars
  tables.css       # table regions, DataTables overrides, sticky behaviours
  charts.css       # inline SVG series, axes, legends, tooltips
  pages.css        # limited page-specific layout modifiers
  responsive.css   # consolidated content-driven breakpoints
```

No bundler or build step is introduced. Imports must appear before other rules, and all assets remain locally served through the existing static-file security boundary.

During migration, legacy selectors may temporarily remain in `workspace.css`, but every temporary selector must have a named consumer and removal phase. A permanent `legacy.css` dumping ground is not acceptable.

Audit findings that shape this migration (decided with Codex, 2026-08-10):

- The static server already serves nested paths with the correct `text/css` MIME and `no-cache` policy, so the `css/` module directory needs **zero** server changes.
- `tests/test_workspace_datatables.py:114-135` currently asserts that `:root` and `.top-nav` appear in the raw `/static/workspace.css` body; both tests are updated intentionally, in the same commit that moves those rules, to target the module files.
- Every consistency scan and CSS custom-property validator covers `golden_vector/serve/static/css/**` recursively, not just `workspace.css`.
- The server sends no `ETag`/`Last-Modified`, so the module files re-download serially behind the render-blocking `@import` chain on every navigation. Phase 8 measures real warm route timings against the Phase 0 baseline; only a measured material regression justifies falling back to multiple `<link>` elements emitted by the shell.

### 9.2 Candidate dark palette

These are implementation starting values. Before they are frozen, automated contrast checks and representative-page mockups must confirm them.

| Token role | Candidate value | Intended use |
|---|---:|---|
| `--color-canvas` | `#0B0D10` | Browser/page background |
| `--color-shell` | `#0E1116` | Sidebar and application header |
| `--color-surface-1` | `#141920` | Standard panels and table regions |
| `--color-surface-2` | `#1A2028` | Nested/alternating sections |
| `--color-surface-elevated` | `#202833` | Popovers, menus, selected elevated blocks |
| `--color-border-subtle` | `#2F3945` | Default divisions |
| `--color-border-strong` | `#465362` | Active/strong divisions |
| `--color-text-primary` | `#F4F6F8` | Main text and values |
| `--color-text-secondary` | `#B7C0CB` | Explanations and supporting labels |
| `--color-text-muted` | `#8D98A7` | Low-emphasis metadata only |
| `--color-brand-gold` | `#D8B45A` | Brand, active navigation, primary action |
| `--color-brand-gold-hover` | `#E7C66D` | Brand/action hover |
| `--color-brand-ink` | `#19150B` | Text on solid gold controls |
| `--color-focus` | `#78B7FF` | Keyboard focus ring |
| `--color-positive` | `#55C58A` | Genuine favourable/pass state |
| `--color-negative` | `#F0787F` | Genuine adverse/fail state |
| `--color-warning` | `#E2B65B` | Warning, stale, estimate, attention |
| `--color-info` | `#69A9E6` | Neutral information/model context |
| `--color-verified` | `#4DB6AC` | Verified provenance, not positive performance |
| `--color-missing` | `#8D98A7` | Missing/unavailable neutral state |
| `--color-blocked` | `#F0787F` | Failed/blocked/incomplete state |

Rules:

- Gold never automatically means a positive investment result.
- Positive green and negative red must never be used for branding/navigation.
- Buttons with a solid gold background use dark brand ink, not unverified white-on-gold contrast.
- Missing is usually neutral grey; incomplete/blocked may be red when action is required.
- Estimated and stale are amber, always with text labels.
- Verified is teal/blue-green so it cannot be mistaken for investment upside.

### 9.3 Chart palette

Charts require a separate semantic series set, still declared in the token source:

- gold commodity: brand gold;
- selected stock: warm orange distinct from gold;
- GDX: blue;
- GDXJ: violet;
- additional comparison series: a colour-blind-aware sequence with dash/marker differentiation;
- positive/up regime: green only when the meaning is explicitly positive/up;
- negative/down regime: red only when the meaning is explicitly negative/down;
- grid/axes: low-contrast border and muted text tokens.

Every multi-series chart must remain interpretable in grayscale or common colour-vision deficiencies by using line dashes, marker shapes, labels, or direct annotations in addition to colour.

### 9.4 Typography tokens

Use no remote font.

```css
--font-ui: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
--font-data: ui-monospace, "Cascadia Code", "SFMono-Regular", Consolas, monospace;
```

Proposed scale:

- 0.75rem: compact metadata only;
- 0.8125rem: table/supporting text;
- 0.875rem: default compact controls and table body;
- 1rem: body text;
- 1.125rem: card/section emphasis;
- 1.375rem: section heading;
- 1.75-2rem: page heading, responsive with `clamp()`.

All numeric tables and metric values use `font-variant-numeric: tabular-nums lining-nums`. Monospace should be reserved for identifiers, formulas, run IDs, and dense aligned values rather than all prose.

### 9.5 Spacing, shape, motion, and layer tokens

- spacing scale: 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, and 3rem;
- control heights: compact desktop approximately 2.25rem; touch layout at least 2.75rem where practical;
- radii: 0.375rem controls, 0.5rem nested surfaces, 0.75rem primary panels;
- shadows: subtle and sparse; borders carry most hierarchy in dark mode;
- z-index scale: base, sticky table/header, drawer/backdrop, popover, tooltip;
- transition durations: approximately 120-180ms for colour/transform/opacity only;
- all non-essential movement disabled under `prefers-reduced-motion: reduce`.

---

## 10. Shared rendering and component architecture

The redesign must reuse and extend existing primitives before adding new ones.

### 10.1 Target Python presentation layout

Use a small dependency-free presentation package only for genuinely shared HTML structure:

```text
golden_vector/serve/
  page_shell.py          # compatibility facade; retains _page_shell signature
  ui/
    shell.py             # grouped navigation and application frame
    components.py        # page header, panel, metric, disclosure, empty state
    status.py            # notice and domain-specific badge markup only
    tables.py            # table region, caption, toolbar wrappers
```

Existing data-aware helpers stay where they are. For example, `overview_helpers.py` continues deciding which already-resolved provenance messages to show, and `model_state_banner.py` continues using the backend's model-state summaries; those modules call the pure UI helpers for markup. `page_shell.py` remains the stable import facade so migration is incremental.

Do not create generic form or chart abstractions merely to fill out this directory. Domain-specific forms remain in their current modules, and chart coordinate/data logic remains in the existing chart renderers.

### 10.2 Existing primitives to preserve and generalize

| Existing primitive | Planned treatment |
|---|---|
| `page_shell._page_shell` | Evolve into the semantic application shell while retaining the current signature during migration. |
| `format_helpers._metric_card` | Make this the one shared metric-card renderer. Reconcile Portfolio's duplicate `_metric_card`, including its help support, before migrating pages. |
| `overview_helpers._render_refresh_summary` | Restyle/generalize into one compact data-status strip without changing manifest interpretation. |
| `overview_helpers._render_filter_bar` | Preserve its DataTables contract and make it the shared visual filter bar. |
| `overview_helpers._render_provenance_warnings` | Preserve warning decisions; only feed its output into the shared notice style. |
| `model_state_banner.render_model_state_banner` | Preserve backend summary semantics; map emitted markup to the shared notice component. |
| `model_state_banner.render_option_freshness_box` | Preserve the single option-freshness wording source. |
| `windows.render_window_selector` and detail window helpers | Preserve the central window registry and query carry-forward; restyle as a shared segmented control. |
| `column_help` and `metric_formula` | Preserve the single click-to-explain content and formula contract. |
| `workspace-tables.js` | Preserve server order, full rows, live search, and named-column filters. |
| `url_helpers.build_page_url` and existing hidden-query helpers | Reuse for all reorganized controls so active state is not lost. |

### 10.3 New pure-presentation primitives

Only after the reuse audit, add small escaped-HTML helpers for concepts that genuinely do not exist:

- page header;
- semantic notice/banner shell;
- action/scenario toolbar shell;
- section header with optional action/disclosure;
- accessible table-scroll region;
- empty-state shell;
- in-page section navigation;
- button/link visual variants.

These helpers may accept already-resolved text, state names, and HTML fragments. They may not inspect DataFrames, calculate thresholds, choose a financial source, or infer whether a number is good/bad.

### 10.4 Semantic component inventory

The design system must define and document:

- application shell and navigation;
- page header and breadcrumb/back link;
- data-status strip;
- notice types: success, information, warning, danger, degraded, neutral;
- panel, nested panel, and section container;
- metric card;
- badge/chip types: brand-neutral, verified, estimated, missing, incomplete, stale, aligned, withheld;
- primary, secondary, tertiary, danger, and icon buttons;
- input, select, textarea, checkbox, radio, field hint, validation message, and grouped actions;
- segmented control and preset control;
- disclosure/`details` treatment;
- filter bar;
- table region and DataTables table;
- help icon and persistent explanation popover;
- hover/focus/touch chart tooltip;
- empty, unavailable, refresh-status, error, and disabled states. `Refresh-status` means only the existing idle/running/succeeded/failed/unknown states; it does not authorize a new skeleton screen, invented progress percentage, or polling protocol.

Each component needs normal, hover, active, focus-visible, disabled, invalid, and high-contrast behaviour where applicable.

### 10.5 Semantic notice mapping

| Backend/user state | Visual tone | Required visible wording |
|---|---|---|
| Saved successfully | Success | What was saved |
| Current/aligned/verified | Verified or neutral success | Explicit state label |
| Informational method/source | Information | Source or meaning |
| Estimated | Warning | `Estimated` |
| Stale/carried forward/misaligned | Warning | Exact freshness state and action |
| Missing/unavailable | Neutral unless action-blocking | `Missing` or `Unavailable` |
| Incomplete/blocked/failed/schema stale | Danger | Exact failure and recovery action |
| Score withheld/degraded | Warning or danger based on backend status | `Withheld`/`Degraded`; never a confident rank style |

The renderer maps already-resolved backend states to styles. It must not create new state thresholds.

---

## 11. Table system

Tables are the highest-risk visual subsystem because they currently create most document overflow and also carry ranking, source, help, filtering, and sorting behaviour.

### 11.1 Required table-container contract

Every analytical table should be inside a shared region with:

- `max-width: 100%` and `min-width: 0` on every grid ancestor;
- `overflow-x: auto` on the table region, not the page;
- a clear accessible name or caption;
- correct column/row header `scope` where the table structure uses semantic headers;
- keyboard focus when horizontal scrolling is necessary;
- visible edge/shadow affordance indicating more columns off-screen;
- touch momentum scrolling;
- no clipped focus outlines, help popovers, or sticky-cell borders;
- a table-specific intrinsic/minimum width chosen from its real columns;
- optional sticky header and opt-in sticky ticker/key column where it does not break semantics.

### 11.2 Data presentation rules

- Tickers and text identifiers align left.
- Numeric values align right and use tabular numerals.
- Status/verdict cells align left and show wording.
- Units remain in headers/help or value formatting exactly as today.
- Missing sort sentinels and `data-order` values remain unchanged.
- Server-emitted initial row order remains unchanged; DataTables still starts with `order: []`.
- Help-icon clicks must not trigger column sorting.
- Footer/benchmark rows remain distinct and do not enter normal body filtering/sorting incorrectly.
- No default pagination and no hidden `+X more` treatment.
- No column is removed or hidden by default during this milestone without separate Victor approval.

### 11.3 Mobile policy

Dense comparison tables remain tables and scroll horizontally inside their regions. Automatic card conversion is allowed only for small, non-comparative tables after a route-specific review. It must never make values or rows disappear.

Sticky first columns should be opt-in because Portfolio correlation tables, form-heavy tables, and tables with nested disclosures have different needs. The background of a sticky cell must use an opaque surface token so scrolled values do not bleed through.

### 11.4 DataTables compatibility

The redesign must preserve:

- graceful no-JavaScript fallback;
- live global search;
- per-column categorical filters;
- click sorting and numeric sort types;
- full-row display with paging disabled;
- current `data-col-name`, `data-sort-numeric`, `data-order`, and `data-search` contracts;
- local vendored assets and static cache tests.

New visual sort indicators must not misstate the current sort. Prefer DataTables' own `aria-sort` state rather than duplicating it.

---

## 12. Forms and control safety

### 12.1 Preserve form contracts byte-for-byte where practical

Moving a form into a toolbar or disclosure does not authorize changing:

- `method`, `action`, control `name`, control `value`, required state, min/max/step, or hidden inputs;
- blank-as-no-op behaviour;
- explicit clear-checkbox precedence;
- current source/window/lens/override state carried by hidden inputs;
- GET versus POST semantics;
- validation and redirect behaviour.

Tests should compare extracted form contracts before and after the move, not only look for a button label somewhere in the page.

The current forms intentionally do not all treat blank values alike. Preserve these distinctions explicitly:

- company numeric inputs: blank is no-op; an explicit clear control clears;
- reporting fields: blank clears the stored value;
- verification optional fields: blank is no-op unless the corresponding clear control is active, and clear wins;
- note and Portfolio lot fields: keep their current required/optional validation and coercion rules;
- validation failures: retain current status code, message, entered values, and redirect/render target. Audit correction: the four ticker-detail validation branches (`workspace.py:615/652/703/735`) currently re-render with **no** lens/window/source/calculator/query context, a hardcoded `12M` canonical anchor, the success-styled `flash` class for the error, and `app_config=None` (which strips column help); an all-blank company POST also redirects to a `Company inputs saved.` flash without saving anything. All of this is defect register D1/D2 — pre-existing behaviour to characterize and preserve during the redesign, then fix in the post-Phase-8 defect follow-up, never opportunistically during markup migration.

### 12.2 Visual hierarchy

- Primary buttons are reserved for the main action in a control group.
- Apply/reset pairs use primary plus tertiary styling rather than two competing buttons.
- Delete is visually dangerous but does not gain a new confirmation workflow without separate approval.
- Advanced assumptions use an explicit disclosure; currently active advanced values remain visible and the disclosure stays open where current logic opens it.
- Field hints and units sit next to the relevant input.
- Invalid submissions return the same entered context where the current renderer supports it and show an associated error notice.
- Native controls use `color-scheme: dark` and must be legible in Windows browsers.

### 12.3 Accessibility

- Every control retains a programmatic label.
- Grouped radio/checkbox controls use a fieldset/legend where appropriate.
- Error text is linked with `aria-describedby` when feasible.
- Focus order follows the visual order.
- Icon-only buttons require accessible names.
- Placeholder text is never the sole label.
- Source-verification rows with no current status keep the disabled `Choose status` placeholder; the redesign must not visually default them to `VERIFIED`.

---

## 13. Charts, SVG, help, and floating interactions

### 13.1 Styling without changing meaning

- Preserve data points, scales, baselines, series order, labels, and explanatory text.
- Replace raw Python/JavaScript colour literals with semantic SVG classes or CSS custom properties where possible.
- Dynamic data-driven geometry may remain inline; raw colour literals may not.
- Legends use the same series classes as the chart rather than duplicate hardcoded colours.
- Dark-mode axes and gridlines must be visible but subordinate to data.
- Existing no-data/suppressed/alignment states remain in place.

### 13.2 Unified floating-layer behaviour

The current help panel, rug tooltip, and overlay crosshair use separate floating-layer logic, with measured divergence: the interactive help dialog sits at z-index 1000 beneath both decorative tooltips at 9999, the rug tooltip has no viewport clamping and no Escape/scroll/resize dismissal, and only the overlay crosshair clamps all four edges. Introduce one small presentation-only positioning/dismissal primitive, or clearly share equivalent utilities, so all floating elements:

- clamp to every viewport edge;
- use one documented z-index scale;
- dismiss on Escape, blur, scroll, resize, and relevant pointer-leave events;
- do not cover an open higher-priority dialog without coordination;
- remain readable on narrow screens;
- do not use unescaped data in HTML sinks;
- have an accessible non-hover path.

No third-party floating-positioning package is required.

### 13.3 Touch and keyboard fallbacks

Hover-only rug and crosshair content is currently weak on touch devices. The redesign should add a presentation-only tap/focus route while preserving the same server-supplied values. If that interaction proves too risky for the main migration, the chart must at minimum retain an accessible text/table summary and the gap must block claims of complete mobile accessibility.

### 13.4 Motion

Charts should not animate data values. Any hover transition is subtle and disabled by reduced-motion preferences.

---

## 14. Accessibility acceptance standard

Target WCAG 2.2 AA for the workspace presentation, within the practical limits of a local analytical tool.

Required checks:

- text and interactive-control contrast meet AA;
- focus indicators are clearly visible against every surface;
- keyboard-only navigation reaches every route, control, disclosure, help icon, and form action;
- skip link works;
- navigation exposes `aria-current`;
- the mobile drawer has correct focus and dismissal behaviour;
- heading order is logical and each page has one clear H1;
- landmarks are present and uniquely labelled where necessary;
- badges and chart series do not rely on colour alone;
- all form controls have labels;
- all images/SVGs are decorative-hidden or have useful roles/labels;
- data tables have contextual labels/captions and retain header associations;
- popovers/dialog-like help content has a predictable focus path;
- 200% browser zoom does not hide actions or create page-level horizontal overflow;
- Windows high-contrast/forced-colours mode retains focus and state boundaries where practical;
- reduced-motion settings are honoured;
- touch targets are at least approximately 44px on narrow/touch layouts where controls are not dense table internals.

Accessibility is an exit gate, not final polish.

---

## 15. Page-specific redesign plan

### 15.1 Candidate Finder (`/` and `/candidate-finder`)

**Goal:** make screening intent, active assumptions, selected criteria, and resulting candidates understandable without wading through one continuous form.

Planned structure:

1. Page header with purpose and existing refresh action/status.
2. Always-visible warning stack for incomplete/null source fields.
3. Compact scenario bar for gold price, financial source, and beta window; preserve independent GET forms and carry-forward state.
4. Bull/Bear preset segmented control and its current description.
5. Summary metrics.
6. Screen Builder in a strong section with universe/top-N controls, criterion-group disclosures, selection counts, direction, weight, meaning, Apply, and Reset.
7. Results views in their existing order: per-criterion top lists and ranking tables.

Safety checks:

- default Bull semantics do not change;
- retired preset mappings continue to resolve;
- repeated `criteria` fields still submit correctly;
- custom direction/weight state survives scenario/source/window changes;
- no criterion or result row is hidden;
- ticker links retain the existing option-trading lens/anchors;
- scenario failures keep their current two-path behaviour: a *runtime* scenario failure falls back to the persisted screen with a visible warning, while a *parse* failure (`gold_price` non-numeric, zero, negative, or non-finite) returns the current bare 400 error page with no screen (defect register D6 tracks the harshness inconsistency; do not change it in this milestone);
- the current refresh form returns to the Candidate Finder base path rather than preserving the custom query; do not change that workflow incidentally during a visual refactor.

### 15.2 Gold Sensitivity (`/tool-a`)

**Goal:** make the selected beta window, confidence context, and ranking table the main visual story.

Planned structure:

1. Header and concise existing explanation.
2. Provenance/model notices.
3. Compact refresh/snapshot/foundation strip.
4. Shared window segmented control.
5. Search/filter bar.
6. Internally scrolling ranked table with sticky ticker column if verified safe.
7. Method/explanation content after the primary table, without changing wording.

Preserve selected-window query, canonical labels (`1Y`, not raw `12M`), benchmark footer rows, weak-link styling, sort sentinels, withheld names, and all help content.

### 15.3 Corporate Finance (`/tool-b`)

**Goal:** separate the active gold scenario from advanced assumptions and make the very wide valuation table usable without widening the page.

Planned structure:

1. Header with active spot/scenario wording.
2. Notices and compact data-status strip.
3. Gold-price action bar with spot and existing preset links.
4. Advanced screening assumptions disclosure; it remains open when non-gold overrides are active or invalid.
5. Search/source/differences controls with all active override hidden inputs preserved.
6. Table region with visually grouped column headers for operating checks, valuation, target scenarios, source/quality, and actions, but no changed values or columns.

Safety checks:

- in-memory scenario recomputation remains exactly where it is today;
- no persisted file is written by GET;
- percent-versus-fraction parsing remains unchanged;
- invalid inputs keep 400 status and visible messages;
- `fundamentals_source` and legacy `rank_by` compatibility remains;
- target scenarios are not collapsed into a misleading single best target;
- all rows and target columns remain available.

### 15.4 Gold Downside (`/tool-c`)

**Goal:** make downside sensitivity and selected lookback readable while containing the table.

Use the same header/status/window/filter/table template as Gold Sensitivity. Preserve per-cell disclosures, search, window reliability, benchmark/context rows, and all ranking exclusions.

### 15.5 Corporate Resilience (`/tool-d`)

**Goal:** make the active stress scenario and firms that cross survival lines easy to compare.

Planned structure:

1. Header and existing transparent-model caveat.
2. Data-status strip.
3. Scenario toolbar containing search, custom gold price, source, existing stress presets, Apply, and Reset.
4. Main resilience table in a contained scroll region.
5. `Who Flips Under This Stress` section in its current semantic relationship to the scenario.

Preserve all scenario computation calls, configured thresholds, source materialization, help formulas, and fail/withheld treatment. No serve-side stress arithmetic may be introduced.

Current contract note: an invalid/non-finite Tool D gold price renders the persisted view with a warning and HTTP 200, unlike Candidate Finder/Tool B validation paths. Preserve that distinction unless Victor separately approves a behaviour fix.

### 15.6 Option Trading (`/option-trading`)

**Goal:** clearly distinguish cached informational liquidity, selected candidate horizon, and ticker-level trade analysis.

Planned structure:

1. Header with cached snapshot/freshness notice.
2. Horizon action bar.
3. Liquidity summary table.
4. Candidate table.
5. Existing method disclosure and risk-free-rate/fallback wording.

Preserve cached-versus-live wording, selected-side persistence, configured horizons, empty/no-option states, proxy rules, candidate links, and the refresh route. The Option Trading overview currently has no visible refresh button; the redesign must not add one accidentally merely because the POST route exists.

### 15.7 Portfolio (`/portfolio`)

**Goal:** make portfolio health and data issues understandable before the user reaches detailed analytics and lot management.

Planned structure:

1. Header and Portfolio-disabled/privacy state.
2. Summary KPI grid with one shared metric-card implementation.
3. `Data issues to fix` as a prominent actionable section showing all issues.
4. In-page section navigation for Composition, Gold-beta exposure, Currency, Hedge sizing, Correlations, History, Reconciliation, Positions, and Lot management.
5. Analytical sections with each table contained independently.
6. Positions and reconciliation download.
7. Add Position Lot and Edit Lots grouped under a clear `Position management` region; current disclosures and every edit/delete form remain available.

Safety checks:

- Portfolio-enabled and disabled 403 boundaries remain;
- no private data is added to logs, screenshots committed to Git, or shared assets;
- add/edit/delete tests operate in temporary stores;
- no forms submit merely because a disclosure opens;
- all 7+ data issues remain visible, never truncated;
- correlation and history no-data states remain explicit;
- every Portfolio table, form, and disclosure is accounted for in the coverage checklist — audit correction: the "17 tables / 25 forms / 22 disclosures" figures are data-dependent (lot forms are 1 add + 2 per lot), so the checklist enumerates render sites in `portfolio_page.py`, not fixed counts;
- reconciliation CSV remains byte/contract compatible.

### 15.8 Lab overview and dial (`/lab`, `/lab/dial/{ticker}`)

**Goal:** give scenario selection, evidence sufficiency, and relative-performance visuals a research-workbench character.

Preserve configured default horizon, bucket resolution, insufficient rows, stale schema handling, scenario/benchmark toggles, curve values, distributions, behaviour panel, and text caveats. Dark chart restyling must not alter scale or counted-week interpretation.

### 15.9 Evidence Scorecard (`/scorecard`)

**Goal:** make evidence status and maturity immediately scannable.

Use the shared page header and verdict-card component. Keep `Tested today` and `Accruing` distinct. Verdict colours must describe evidence state, not investment quality. Preserve legacy-schema compatibility and diagnostic blank formatting.

### 15.10 Ticker detail (`/ticker/{ticker}`)

**Goal:** turn the current 37-panel page into a navigable research dossier without removing content.

Planned structure:

1. Breadcrumb/back link and ticker page header.
2. Window/lens/source controls with all query state preserved.
3. Flash/error/alignment notices.
4. Sticky in-page section navigation using anchors, not new routes: Gold Sensitivity, Charts, Corporate Finance, Option Trading, Inputs, Reporting, Verification, Notes. Only include anchors that exist for the current lens/vehicle.
5. Current headline metrics and explanations.
6. Primary charts near the metrics they explain.
7. Supporting structural-window, volatility, exploratory, and comparison tables.
8. Option Trading link or full option lens, unchanged.
9. Manual research-record sections grouped with existing disclosures.

Important limits:

- do not create new analytical tabs that change what is loaded or default-visible;
- in-page anchors may improve movement while all content stays in the document;
- canonical anchor/window logic remains centralized;
- option-vehicle tickers continue to show only the appropriate lens;
- post-redirect `return_to` continues preserving Yahoo source, window, lens, and calculator state;
- alignment suppression and corrupt/missing metric distinctions remain exact;
- chart order covered by existing tests remains intentional unless a separate reviewed change updates that expectation.

Pre-existing behaviour issue to keep separate: the four ticker-form validation-error branches re-render the default detail state without carrying any active lens/window/source/calculator argument, mark the wrong canonical anchor (`12M` hardcoded), present the error in the success flash style, and drop column help (`app_config=None`). A 400 response therefore visually falls back from the submitted state, and the collapsed `return_to` compounds the loss on the next successful save. This is defect register D1: characterized during the redesign, fixed in the post-Phase-8 defect follow-up, never silently changed inside markup migration.

### 15.11 Errors, disabled, empty, and stale states

The shared error presentation must cover and visually distinguish:

- 400 invalid scenario/override/form input;
- 403 Portfolio page/report/download disabled;
- 404 unknown route, unsupported route, inactive ticker, unavailable file;
- 500 unexpected workspace failure;
- 503 stale Tool B schema, stale Option Trading schema, stale Portfolio schema, or missing/rebuild-required artifacts;
- missing current snapshot;
- empty universe or no rows;
- low coverage;
- stale/carried-forward option snapshot;
- model-state degraded/misaligned;
- score/result withheld;
- successful save/refresh status.

The recovery action must be visible when the backend already supplies one. Do not convert a failure into a reassuring empty card.

Deliberate presentational correction: error pages currently render with Candidate Finder highlighted as the active navigation item. The redesigned error shell renders **no** active navigation item (and no `aria-current`) — a documented, intentional markup-only change.

---

## 16. Planned source-code touch map

| File/area | Planned responsibility | Change restriction |
|---|---|---|
| `serve/page_shell.py` | Structured navigation data, semantic shell, asset includes, active page | Routes/labels remain the same; no data loading. |
| `serve/static/workspace.css` | Stable stylesheet entrypoint/migration compatibility | Eventually contains no undocumented raw theme decisions. |
| `serve/static/css/*` | Canonical tokens and shared style modules | No page/business logic. |
| `serve/static/workspace-shell.js` | Accessible drawer only | No route selection, analytics, fetch, or storage. |
| `serve/static/workspace-tables.js` | Existing DataTables activation | Behaviour preserved; only accessibility/visual hooks added. |
| `serve/static/help-popover.js` | Existing explanation panel | Content contract preserved; shared positioning/accessibility improved. |
| `serve/static/rug-tooltip.js` | Rug interaction | Same server data; touch/edge handling only. |
| `serve/static/overlay-crosshair.js` | Overlay interaction | Same server data and values; shared theme/positioning only. |
| `serve/static/portfolio-forms.js` | Extract the current inline ticker-to-buy-currency synchronizer | Preserve `.portfolio-lot-form`, ticker/currency names, and `data-currency` contract exactly; no new business behaviour. |
| `serve/format_helpers.py` | Shared formatting/metric card | Consolidate duplicate card rendering; no thresholds or data decisions. |
| `serve/overview_helpers.py` | Shared status/filter/table presentation | Reuse current provenance logic unchanged. |
| `serve/model_state_banner.py` | Existing model/freshness wording | Only semantic markup/classes change. |
| `serve/windows.py` | Existing central window selector | Only markup/classes/ARIA change. |
| `serve/column_help.py`, `serve/metric_formula.py` | Existing help content | No formula or meaning changes. |
| page renderer modules | Page-specific arrangement and class migration | Values, controls, fields, links, and status decisions preserved. |
| `serve/http_helpers.py` | Shared error shell/static delivery | Status codes/security/cache rules preserved. |
| UI tests | Behaviour, route, semantic, asset, and consistency guardrails | Avoid brittle full-document snapshots. |

Any proposed change outside this map requires a written reason and explicit review.

---

## 17. Implementation sequence and gates

Implementation should be incremental and reversible. A development checkpoint is not automatically a shippable milestone; `main` should not receive a visibly half-migrated product.

### Phase 0 - Approval, baseline, and integration audit

Tasks:

1. Claude Code reviews this plan against the repository and corrects it directly.
2. Treat the approved decisions in Sections 2 and 23 as resolved unless a safety conflict is supported by repository evidence.
3. Confirm branch is `dev-vic` and working-tree changes belong to the expected owners.
4. Inventory all local/remote branches not merged to `origin/main` and all worktrees.
5. Compare touched files on any branch that changes `serve/`, Candidate Finder, Option Trading, Portfolio, model-state, schemas, or manifests.
6. Use a temporary integration branch if another unmerged branch touches the same presentation/data spine.
7. Run and record test collection plus the focused UI/route/form/Portfolio/model-state-rendering baseline defined in Section 18.6; do not run the complete repository suite by default.
8. Save read-only baseline evidence for the route/viewport matrix: automated DOM, overflow, and interaction measurements for the complete matrix, plus roughly 10-15 representative sanitized screenshots. No mass screenshot matrix is created or committed; extra debugging screenshots stay untracked.
9. Record warm real-route response timings for representative routes.
10. Record current HTML contracts for forms, query carry-forward, table IDs/classes, status codes, and navigation links.
11. Generate a machine-readable baseline contract matrix covering every route/method, query parameter, form action/control, table header/key, link target, warning/state label, redirect, and download response.
12. Hash representative persisted artifacts before and after ordinary GET-route smoke checks to prove rendering is read-only.
13. Add missing pre-migration route coverage for `/scorecard`, reporting POST, Portfolio edit/delete, unknown ticker/action, and unsupported methods before shared markup is extracted — pinning the current no-405/no-HEAD, two-flavour-404 behaviour exactly, with clearly labelled characterization tests wherever current behaviour is a registered defect.
14. Create the milestone evidence directory `reviews/codex/milestones/visual_redesign/` and the defect register (`defect_register.md`) seeded with audit defects D1-D8; every later phase appends new defects to the register rather than losing findings in commentary.
15. Pin the exact file-path-based focused release selection command (no pytest markers or config file exist) and record that all guardrail scans are CWD-dependent (run everything from the repository root).
16. Consolidate the five near-duplicate WSGI test helpers into `tests/helpers.py` while building the route-matrix tests, instead of adding a sixth copy.

Exit gate:

- plan approved;
- branch/worktree situation understood;
- focused baseline green or existing failures explicitly documented;
- baseline artifacts stored under a milestone/review directory without private Portfolio screenshots or data;
- machine-readable contracts and representative artifact hashes recorded;
- no implementation conflict with other active work.

### Phase 1 - Token extraction and consistency foundation

Tasks:

1. Create the CSS module structure.
2. Move existing visual values into named tokens first, aiming for mechanical parity.
3. Add semantic colour, type, spacing, radius, motion, and z-index tokens.
4. Reconcile the duplicate metric-card renderers by extending the existing shared primitive.
5. Convert duplicated chart/legend colour literals to semantic classes/tokens.
6. Add consistency tests that scan first-party CSS/Python/JS for raw colours outside the token source and an explicit narrow allowlist.
7. Document allowed data-driven inline styles; raw inline colours are not allowed.

Exit gate:

- no behavioural/render-content change beyond expected class/style wiring;
- existing focused UI tests green;
- raw-colour inventory is reduced to the token file, vendor code, and documented exceptions;
- no new dependency or build step.

### Phase 2 - New shell and navigation

Tasks:

1. Convert `_NAV_LINKS` to a structured grouped navigation definition without changing nav IDs, labels, or hrefs.
2. Implement the semantic shell and skip link.
3. Add desktop sidebar and mobile header/drawer styling.
4. Add the small drawer script and load it locally.
5. Preserve existing stylesheet/JavaScript ordering and DataTables loading.
6. Make every existing page render safely inside the new shell before restructuring page content.

Exit gate:

- every GET page and error page has working navigation;
- correct `aria-current` on each surface;
- drawer passes keyboard/touch review;
- no route has body-level horizontal overflow caused by the shell;
- active navigation for default ticker and option lens remains correct;
- all static-file/cache/security tests green.

### Phase 3 - Shared components and representative pilots

Pilot pages deliberately span all high-risk UI patterns:

1. Candidate Finder: home-page identity, warnings, presets, multiple GET forms, disclosures, summary cards, and several result tables.
2. Corporate Finance: scenario controls, advanced form, source state, and the widest standard comparison table.
3. `NEM` ticker detail: dense metrics, charts, help, disclosures, multiple forms, and query-preserving actions.
4. Portfolio: private data, disabled state, dense forms/tables, downloads, and state-changing actions using fixtures only.
5. Option Trading: cached-state/freshness language, horizon and sizing query state, proxy/benchmark exceptions, and persisted-read semantics.
6. Lab: SVG interaction, dense data semantics, insufficient-data states, and table/chart consistency.

Tasks:

- implement shared page header, notice, status strip, toolbar, metric card, table region, and disclosure styles;
- migrate pilots without changing copy or form/query contracts;
- compare a machine-readable semantic DOM contract before and after each pilot;
- exercise healthy, empty, missing, stale, corrupt, misaligned, scenario-active, disabled, and write-validation fixture states applicable to each pilot;
- prove GET requests leave representative persisted-artifact hashes unchanged;
- validate desktop, tablet, mobile, 200% zoom, keyboard, and no-JavaScript table fallback;
- review screenshots with Victor before mass migration.

Exit gate:

- pilots establish the final reusable patterns;
- no body overflow at target widths;
- targeted route/form/query/DataTables/chart tests green;
- sanitized pilot evidence is captured and a serious self-review is recorded; per the approved autonomy decision (2026-08-10), implementation continues automatically when the result matches the approved guide and plan, pausing only for a genuine product ambiguity — Victor reviews the complete product before any `main` merge;
- any component exception is documented before other pages copy it.

### Phase 4 - Remaining analysis overviews

Migrate:

- Gold Sensitivity;
- Gold Downside;
- Corporate Resilience.

Tasks:

- reuse pilot patterns;
- contain all tables;
- preserve builder/scenario/horizon/source state;
- validate all warnings, empty states, and details/disclosures;
- add no new local palette or one-off button/card style.

Exit gate:

- all discovery/analysis routes use the shared system;
- all query combinations in the contract matrix remain covered;
- no hidden rows/columns;
- relevant serve-no-arithmetic guardrails remain green.

### Phase 5 - Scorecard and completion of deep-route variants

Tasks:

- migrate Evidence Scorecard;
- complete every ticker-detail lens/section beyond the `NEM` pilot, including manual records and benchmark-ETF option vehicles;
- complete all Portfolio, Option Trading, and Lab variants/states that were not exercised by their pilots;
- add in-page section navigation where planned;
- test all write paths against temporary stores only.

Exit gate:

- every route and special surface is visually migrated;
- all 17 Portfolio tables, 25 forms, and 22 disclosures are accounted for;
- all 37 representative ticker-detail panels/sections and 14 forms remain reachable;
- Portfolio disabled/download/privacy tests green;
- Lab/Scorecard stale/insufficient/compatibility states green.

### Phase 6 - Interaction, accessibility, and responsive hardening

Tasks:

- unify floating-layer positioning and z-index behaviour;
- add touch/keyboard access for chart tooltip information or document an explicit blocking gap;
- finish focus, forced-colours, reduced-motion, and contrast work;
- test long labels, long run IDs, missing values, large warnings, and validation errors;
- remove any CSS workaround that masks overflow;
- test at all target viewports and zoom levels.

Exit gate:

- accessibility checklist passes;
- zero known page-level overflow;
- zero unexplained console errors;
- no colour-only status or chart distinction;
- no clipped popover/tooltip at viewport edges.

### Phase 7 - Legacy removal and consistency enforcement

Tasks:

- identify every remaining legacy selector and consumer;
- delete unused selectors and obsolete hardcoded literals;
- ensure one shared renderer exists for repeated patterns;
- expand static consistency scans;
- verify vendor files are excluded from first-party lint rules;
- update architecture map and UI documentation.

Exit gate:

- no undocumented visual exceptions;
- no duplicate token names or metric-card/notice/table patterns;
- no dead first-party selectors detectable by the agreed audit;
- stylesheet/module ownership is documented.

### Phase 8 - Proportional regression, real-workspace smoke, and release

Tasks:

1. Run focused UI tests.
2. Run all new route/semantic/accessibility/JavaScript consistency tests.
3. Run `pytest --collect-only -q` and record the repository-wide collection result.
4. Start the real local workspace and perform read-only route smoke checks, comparing persisted-artifact hashes.
5. Re-run responsive DOM measurements and compare with baseline.
6. Re-run real route timing measurements and explain material differences.
7. Verify no external requests and no unapproved data writes.
8. Produce before/after route screenshots excluding private Portfolio data.
9. Inspect the complete changed-file inventory and prove the work remained inside the approved presentation/test/documentation boundary.
10. Write a milestone handoff listing files, tests, known limitations, route coverage, and why the selected test scope is sufficient.
11. Run the mandatory branch/worktree integration audit before merge.
12. Run the complete focused release selection again on the final integration commit; an earlier green run does not validate the integrated tree.
13. Run the complete repository suite only if a trigger in Section 18.6 applies.
14. Follow the repository's `dev-vic` to `main` shipping workflow only when the whole milestone is coherent and approved.

Exit gate:

- Definition of Done in Section 22 is fully satisfied;
- Victor approves the final result;
- Claude Code or Codex completes an independent final review;
- no pending overlapping branch changes are silently lost.

### Post-Phase-8 defect follow-up (required before release)

After Phase 8 and before final integration:

1. Resolve every actionable entry in the defect register in separate, clearly labelled behavioural follow-up commits — never mixed into visual-refactoring commits.
2. Add regression tests for every fix and re-run the affected focused selections.
3. Apply the Section 18.6 complete-suite triggers if any fix touches analytics, pipelines, loaders, schemas, contracts, manifests, artifacts, or shared data logic.
4. Leave a defect unresolved only when it genuinely requires Victor's product decision or external information, documenting the exact blocker, impact, and recommended decision.
5. Then perform the independent final review, fix all high/medium findings, and only afterwards run the `dev-vic` to `main` integration.

### Phase rollback design

Keep the work code-only and independently revertible at these boundaries:

1. tokens/foundations;
2. application shell/navigation;
3. shared semantic components and interaction helpers;
4. each approved route batch;
5. final cleanup/guardrails.

No data migration, persisted-artifact schema change, or manifest change is permitted, so rollback must remain a normal code revert. If a release gate fails, revert the latest UI milestone and retain the last approved shell/page batch. Never repair a visual rollback by changing analytical outputs, schemas, or user data.

---

## 18. Verification strategy

### 18.1 Existing regression suites that must remain green

Audit evidence: collection found **1,555 tests**, and a focused UI/route/Portfolio/model-state selection passed **371/371**. This establishes the proportional Phase 0 baseline; the complete suite is conditional under Section 18.6.

At minimum, preserve and extend coverage in:

- `tests/test_workspace_app.py`;
- `tests/test_workspace_datatables.py`;
- `tests/test_candidate_finder_page.py`;
- `tests/test_workspace_horizon_switcher.py`;
- `tests/test_option_trading_routes.py`;
- `tests/test_option_trading_overview.py`;
- `tests/test_lab_page.py`;
- `tests/test_lab_curve.py` and related Lab UI tests;
- `tests/test_lab_scorecard.py`;
- Portfolio route/store/privacy/render tests;
- `tests/test_column_help.py` and `tests/test_metric_formula.py`;
- serve-layer no-arithmetic/static-scan tests.

The most important existing protections and review anchors are:

| Contract | Existing evidence to retain |
|---|---|
| Route/navigation rendering | `tests/test_workspace_app.py`, `tests/test_candidate_finder_page.py`, `tests/test_option_trading_routes.py`, `tests/test_lab_page.py`, `tests/test_portfolio_m1.py` |
| URL/query preservation | `tests/test_url_helpers.py`, `tests/test_workspace_horizon_switcher.py`, Candidate Finder state tests, Option sizing/lens tests |
| Ticker/manual forms | Company, note, reporting-adjacent, and verification cases in `tests/test_workspace_app.py`; refresh return safety in `tests/test_option_refresh.py` |
| Table sort/filter metadata | `tests/test_workspace_datatables.py`, Candidate ranking tests, and Lab row/header/missing-sort tests |
| Persisted-read/data semantics | Candidate alignment tests, horizon-switch tests, `tests/test_option_trading_overview.py`, Lab curve invariants, and Portfolio degraded/empty-state tests |
| Explanations/help/provenance | `tests/test_explanations.py`, `tests/test_column_help.py`, `tests/test_metric_formula.py`, `tests/test_fundamentals_provenance.py`, and Scorecard caveat tests |
| No serve-side analytics | The Tool B/D, charts, Candidate Finder, Lab, Scorecard, and global serve scans in `tests/test_workspace_app.py`, `tests/test_lab_page.py`, and `tests/test_lab_scorecard.py`, plus (audit addition) the chart/beta-strip scans in `tests/test_benchmark_comparison.py` and the `overlay-crosshair.js` scan and Node runtime test in `tests/test_rebased_overlay_panel.py` |
| Privacy/security | Portfolio loopback/disabled/private-input scans, static path-traversal tests, safe-return tests, and raw-exception suppression tests |
| Model-state/freshness | `tests/test_model_state.py`, Candidate mixed-refresh warnings, and Option carry-forward/freshness tests |
| JavaScript/static assets | Static MIME/asset tests and the existing real Node runtime test for `overlay-crosshair.js`/rebased overlay behaviour |

Known pre-redesign test gaps are themselves Phase 0 work: no exhaustive WSGI route/method matrix; no WSGI integration coverage for `/scorecard`, reporting POST, and Portfolio edit/delete; no whole-page accessibility or responsive suite; no design-token consistency guard; and no real runtime test for DataTables, help popovers, or rug tooltips.

Additional audit facts the verification work must absorb:

- The global serve no-analytics sweep (`tests/test_workspace_app.py:2978`) globs `serve/*.py` **non-recursively**; it must become a recursive scan in the same commit that creates any `serve/` subpackage, or new presentation modules silently escape it.
- `tests/test_lab_curve.py:624` asserts a hardcoded chart colour (`stroke="#2f6f6d"`); it is updated intentionally when chart colours become semantic tokens/classes.
- The Node runtime test hard-fails when `node` is unavailable, and per Codex's decision that stays a hard failure: required JavaScript coverage must not silently skip.
- The focused selection is file-path-based (no pytest markers or config file exist), and every guardrail scan resolves `golden_vector/...` relative to the working directory — all commands run from the repository root.

### 18.2 New automated contract tests

Add focused tests for:

1. An exhaustive WSGI route/method matrix: every GET/POST/download/redirect/static route, `/scorecard`, reporting POST, Portfolio edit/delete, unknown ticker/action, and every supported/unsupported-method outcome.
2. Shell landmarks, skip link, main ID, grouped nav, every nav href/active mapping, and exactly one `aria-current="page"` where applicable.
3. Mobile drawer asset presence and runtime behaviour: open/close, Escape, outside click, focus trap/order, focus return, and no-JavaScript access to navigation.
4. All first-party assets served with correct MIME/cache policy, no path traversal, and no external asset/network request.
5. A CSS custom-property validator that proves every `var(--name)` resolves, catching the current undefined `--border` and `--paper` debt before it can survive migration.
6. No raw first-party colour literals outside the canonical token source/allowlist, and no raw inline colour styles in Python or JavaScript renderers.
7. One shared metric-card renderer after consolidation; no duplicated notice/table/control vocabulary.
8. Table-region wrappers on every wide analytical table, with labelled scroll regions, captions/header associations, and no body-level overflow.
9. Table IDs, `js-datatable`, named columns, numeric sorting markers, `data-order`, `data-search`, initial order, row identifiers, and footer rows unchanged.
10. A semantic DOM contract extractor comparing form action/method/name/value/selected/checked state, links/query strings, table headers/keys, warnings, provenance, and missing/stale/estimated/verified labels before versus after.
11. Form/query carry-forward assertions across every multi-control surface, including repeated query parameters and validation-error states.
12. A complete status-code/body/header/recovery-message matrix for 204/303/400/403/404/current unsupported-method behaviour/500/503 and downloads.
13. Basic HTML parsing/valid nesting checks, duplicate-ID detection, heading hierarchy, named landmarks, table header relationships, and control accessible names.
14. Empty, missing, stale, corrupt, misaligned, withheld, disabled, refreshing, failed, and success markup/tone labels, with no colour-only communication.
15. Help-popover runtime tests for click, keyboard activation, Escape, focus return, outside click, scroll/resize dismissal, viewport clamping, read-more behaviour, and no sort-trigger conflict.
16. Rug-tooltip and chart runtime tests for mouse, keyboard focus, touch/pointer dismissal, clamping, semantic series classes, and non-colour differentiation.
17. Real DataTables verification (decided with Codex, 2026-08-10): ascending/descending numeric sort, missing-value placement, global search, exact dropdown filters, filter clearing, combined filters, regex-special values, preserved initial order, and graceful no-JavaScript fallback are proven in the scripted real-browser matrix with recorded evidence, because the vendored DataTables build requires jQuery, which the zero-dependency Node shim cannot host. No `jsdom`, `package.json`, or any other new dependency is added; static/semantic DataTables contracts remain pytest-enforced.
18. `node --check` for every first-party JavaScript file plus zero-dependency Node shim runtime coverage where feasible — `help-popover.js`, `rug-tooltip.js`, `overlay-crosshair.js` (existing), the new navigation-drawer helper, and the extracted Portfolio form helper; `workspace-tables.js` gets `node --check`, its guard-branch test, and the browser evidence above. Missing Node remains a hard failure.
19. New serve presentation modules contain no forbidden analytics tokens; existing global no-arithmetic scans are expanded rather than bypassed by file moves.
20. The Combined route remains removed, persisted-artifact hashes remain unchanged after GET smoke tests, and readers continue resolving existing state.
21. Portfolio remains loopback/private, disabled/download states fail closed, safe return paths reject external targets, and error redaction remains intact.

The audit also found no current browser-level CSRF/Origin or security-header baseline for state-changing local forms. Phase 0 should record current behaviour and open a separate security decision if protection is desired; a visual redesign must neither silently weaken nor silently change that contract.

Tests should assert important semantic fragments rather than snapshotting entire HTML pages, which would make every harmless layout edit brittle.

### 18.3 Browser route matrix

Run the full matrix at 1,440px, 1,280px, 1,024px, 768px, and 390px widths, plus a 320px narrow stress pass on the shell, forms, popovers, and widest table regions. The complete matrix is verified with automated DOM/overflow/accessibility/interaction measurements; only the curated 10-15 image set from Section 18.5 is committed, and any extra debugging screenshots stay untracked:

- `/`;
- `/tool-a?window=12M` and a non-default window;
- `/tool-b` at spot and with representative overrides;
- `/tool-c`;
- `/tool-d` at spot and a stress scenario;
- `/option-trading`;
- `/portfolio` when enabled, plus a fixture-based disabled state;
- `/lab` and one `/lab/dial/{ticker}`;
- `/scorecard`;
- `/ticker/NEM` default lens;
- `/ticker/NEM?lens=option-trading`;
- one benchmark-ETF option-vehicle detail;
- representative 400, 403, 404, and 503 pages.

For every entry verify:

- correct H1/title/active nav;
- no body-level horizontal overflow;
- all primary actions visible and reachable;
- internal table scrolling works;
- all rows and columns remain reachable, and important column context remains understandable while scrolling;
- focus remains visible;
- keyboard traversal/focus order works and touch targets are operable;
- notices are not clipped;
- help/popovers remain on screen;
- charts do not clip labels or lose keyboard/touch access;
- browser back/forward restores the same query-controlled state;
- 200% zoom remains fully usable on every route and a 400% zoom stress pass remains operable on representative shell/form/table/error pages;
- warnings remain explicit without colour and reduced-motion preferences are respected;
- no first-party console errors, asset `404`s, or malformed-HTML findings;
- no external requests.

### 18.4 Write-path verification

Use temporary project paths/manual stores to test:

- company update, blank-as-no-op, and clear;
- reporting update with its distinct blank-means-clear behaviour;
- verification status/optional clear/validation;
- stock note limits/status;
- Portfolio add/edit/delete and rebuild;
- redirect state preservation;
- invalid input returns the expected 400 page.

Never use Victor's real Portfolio or manual input store for automated redesign tests.

### 18.5 Visual review set

Capture before/after images for:

- Candidate Finder above the fold and results;
- Corporate Finance wide table;
- Corporate Resilience stress table;
- Option Trading overview;
- NEM detail metrics/charts/forms;
- Portfolio using sanitized fixture data only;
- Lab chart;
- Scorecard;
- mobile navigation and one mobile wide table;
- warning, error, missing, estimated, verified, and stale states.

Screenshots support review; they do not replace DOM/behaviour tests. Per the evidence decision (2026-08-10), this curated sanitized set (roughly 10-15 images) is the only screenshot collection committed to the repository; the full route/viewport matrix is recorded as measurements, and debugging screenshots remain untracked. No real Portfolio or other private data ever appears in committed images.

### 18.6 Proportional test-scope policy

The complete 1,555-test repository suite is unusually slow and is not a routine phase or release gate for this presentation-only milestone. Repeated full runs would spend substantial time revalidating analytical and pipeline code that the change budget forbids touching.

Required verification is:

1. Run page/component-specific tests after individual changes.
2. Run the complete focused UI/route/form/JavaScript/Portfolio/model-state-rendering selection after every implementation batch.
3. Run every new route-contract, semantic DOM, accessibility, responsive, and design-system consistency test.
4. Run `pytest --collect-only -q` at the final gate to detect repository-wide import or collection failures.
5. Run the browser route/viewport matrix, real-workspace read-only smoke test, artifact-hash comparison, console/network inspection, and changed-file audit.
6. Re-run the focused release selection on the final integration commit and after any final-review fix.

The complete repository suite becomes mandatory only when at least one of these triggers applies:

- analytical logic, pipelines, loaders, contracts, schemas, manifests, artifact production, or shared data utilities are changed;
- implementation escapes the approved `golden_vector/serve/**`, UI-test, and documentation boundary without a narrowly justified presentation reason;
- a targeted failure suggests a cross-layer regression;
- repository-wide collection fails;
- the final diff cannot prove that the milestone remained presentation-only.

If no trigger applies, the final handoff must list the changed files, focused commands/results, collection result, browser evidence, and a short explanation of why omitting the complete suite was proportionate. `No business logic was intended to change` is not sufficient by itself; the diff and tests must demonstrate containment.

---

## 19. Performance, security, and local-first checks

### 19.1 Performance

- Do not add a template engine, frontend framework, remote font, or icon library.
- Do not add server-side data reads to `_page_shell`.
- Do not compute route-level summary values for visual decoration.
- Keep assets cacheable under the existing first-party revalidation rules.
- Measure warm real requests for `/`, `/tool-b`, `/tool-d`, `/portfolio`, `/ticker/NEM`, and `/ticker/NEM?lens=option-trading` before and after.
- Treat a material slowdown as a finding; trace it to the real route rather than a synthetic rendering harness.
- Compare HTML/CSS/JS payload sizes and document intentional growth.
- Keep JavaScript enhancement optional: plain server HTML remains usable if a script fails.

### 19.2 Security and privacy

- Preserve static path traversal and extension allowlist tests.
- Preserve HTML escaping at every renderer boundary.
- Do not introduce unsafe `innerHTML`; where current code uses it, keep escaping and prefer DOM/text APIs for new work.
- Preserve `_safe_return_to` and URL encoding.
- Preserve Portfolio loopback enforcement and disabled-report boundaries.
- Record the current Origin/CSRF and security-header behaviour for all state-changing local forms. Treat any new protection as a separate security change with its own compatibility review; do not weaken the current boundary during visual work.
- Do not commit real holdings screenshots, exports, account information, notes, or manual-data files.
- Do not add browser storage for financial/Portfolio state.
- Do not add third-party requests or telemetry.

### 19.3 Architecture checkpoint

At each phase, confirm:

- request handlers still only read prepared state and invoke existing sanctioned scenario paths;
- the model-state manifest and artifact resolution are untouched;
- no required-data error was converted into an empty UI;
- no shared helper was duplicated;
- no new serve-side arithmetic appeared;
- presentation state does not become a second source of truth.

---

## 20. Consistency guardrails

Add lightweight automated scans with narrow documented exceptions:

- raw hex/rgb/hsl colours may appear only in `tokens.css`, vendored files, or a documented unavoidable fallback;
- Python/JavaScript may not emit raw inline colours;
- spacing/radius/shadow values should use tokens except for documented data geometry;
- page renderers should not create new button, badge, notice, panel, filter, or table vocabularies when a shared component exists;
- all new page styles use a documented page modifier rather than deep brittle selectors;
- no `!important` outside a reviewed vendor-override allowlist;
- no broad `overflow-x: hidden` on `html`, `body`, shell, or main;
- all `help_th`/help-value calls continue using the one click-to-explain pattern;
- new serve modules are added to the analytics-token scan;
- every new route-facing control includes a state-preservation test.

The scan should report a precise filename/line and allow intentional exceptions in one small documented map. It should not become an unmaintainable false-positive regex wall.

---

## 21. Risk register

| Risk | Consequence | Prevention/detection |
|---|---|---|
| Wide tables still widen the document | Broken desktop/mobile layout | Shared table region, `min-width: 0`, DOM overflow assertions at every target viewport. |
| `overflow-x: hidden` masks inaccessible columns | Data silently becomes unreachable | Explicit ban and scroll-region tests. |
| Reorganized forms drop hidden parameters | Scenario/source/window state resets | Extracted form-contract and query carry-forward tests. |
| Shared component accidentally interprets a number | Serve/model boundary violated | Pure text/state APIs and static no-arithmetic scans. |
| Gold styling is mistaken for a positive verdict | Misleading investment meaning | Brand/semantic token separation and label-plus-colour rules. |
| Dark mode reduces contrast | Fatigue or inaccessible controls | Token contrast tests, browser review, forced-colours/focus checks. |
| Navigation drawer is inaccessible | Keyboard/touch users become blocked | Focus/dismissal specification and browser keyboard matrix. |
| DataTables styling breaks sort/filter | Wrong view or unusable table | Existing DataTables tests plus real interactions. |
| Help icon click sorts a column | Confusing side effect | Preserve capture/stop-propagation tests. |
| Sticky columns obscure cells/help | Hidden information | Opt-in sticky classes and per-table visual review. |
| Chart palette changes perceived meaning | Misinterpretation | Preserve scales/data/order; use semantic classes, dashes, labels, and screenshot review. |
| Hover-only charts remain unusable on touch | Incomplete mobile redesign | Add touch/focus access or keep issue blocking final accessibility claim. |
| Portfolio UI tests mutate private data | User-data risk | Temporary fixture paths only; read-only live smoke. |
| Refresh button is clicked during styling QA | Unwanted external/network work | Do not click live; use mocked route tests/status fixtures. |
| CSS migration leaves two competing systems | Specificity bugs and drift | Consumer inventory, phase-7 removal gate, raw-token/selector audits. |
| New helper duplicates an existing renderer | Divergent appearance/meaning | Grep-first rule and explicit primitive reuse list. |
| Half-migrated product reaches `main` | Inconsistent user experience | Development checkpoints stay on `dev-vic`; ship only coherent reviewed milestone. |
| Parallel branch changes overlap serve/data spine | Logical integration failure | Mandatory branch/worktree/file-overlap audit and temporary integration branch. |
| External assets break offline use | Missing fonts/icons or privacy leak | System fonts, local assets, no CDN. |
| Error/empty states are forgotten | Tool appears fine when data is broken | State matrix and 400/403/404/500/503 browser/render tests. |
| Test snapshots become too brittle | Future harmless edits become costly | Assert semantic contracts, not entire HTML blobs. |
| Missing pre-existing Origin/CSRF/security-header baseline is confused with redesign scope | Accidental security regression or unreviewed behavioural change | Record current behaviour in Phase 0; preserve it during redesign; handle improvements as a separate reviewed security milestone. |

---

## 22. Definition of Done

The redesign is complete only when all statements below are true.

### Visual system

- one canonical token source controls colour, typography, spacing, shape, elevation, layers, motion, status, and chart colours;
- every user-facing route uses the shared shell and component vocabulary;
- no undocumented local palette or duplicate metric-card/notice/table system remains;
- Golden Vector has a distinct dark-charcoal and restrained-gold identity.

### Functionality

- every route, query parameter, form action/name/value/default, redirect, status code, download, sort, filter, and workflow in Section 6 is preserved;
- all rows remain accessible;
- calculations, rankings, thresholds, data states, and persisted artifacts are unchanged;
- no new serve-side analytics or request-path computation exists.

### Responsive behaviour

- no tested route has page-level horizontal overflow at 1,440, 1,280, 1,024, 768, or 390px, and the selected 320px stress routes remain usable;
- wide tables scroll inside labelled regions;
- navigation is compact and fully usable at every width;
- content and actions remain usable at 200% zoom.

### Accessibility

- WCAG AA colour/focus targets pass;
- keyboard and touch workflows pass;
- state and charts are not colour-only;
- help/popovers/tooltips are clamped, dismissible, and accessible;
- reduced-motion and high-contrast basics work.

### Reliability

- focused UI tests pass;
- the proportional release selection in Section 18.6 passes with no unexplained failures;
- repository-wide test collection succeeds;
- the complete suite passes when any Section 18.6 trigger requires it;
- route/status/state matrix passes;
- browser console is clean;
- real route timings show no unexplained material regression;
- no external requests or private-data leaks occur.

### Delivery

- baseline and final review evidence exists;
- the defect register is complete and every actionable entry is resolved in separate labelled follow-up commits (or explicitly blocked on a documented Victor decision);
- Claude Code/Codex independent review findings are resolved or explicitly accepted;
- branch/worktree integration audit is documented;
- architecture map and UI documentation describe the new system;
- milestone handoff states what changed, what did not change, tests run, and any residual limitations;
- Victor approves the finished result before merge to `main`.

---

## 23. Approved implementation choices

Victor has approved the following choices. Claude Code should proceed without asking again unless repository evidence reveals a genuine safety conflict:

1. **Sidebar:** grouped desktop sidebar plus mobile drawer.
2. **Density:** compact institutional tables/controls as the default.
3. **Theme:** dark-only for this milestone; no light-theme toggle.
4. **Typography:** system sans-serif UI and tabular/monospace treatment for numbers/IDs.
5. **Ticker detail:** sticky in-page anchor navigation while keeping all content on the same route/document.
6. **Methodology:** visually subordinate deep methodology while keeping critical caveats visible and wording unchanged.
7. **Columns:** no columns are hidden by default during this milestone.
8. **Chart touch access:** part of the redesign rather than deferred polish.
9. **Brand assets:** no new logo/illustration/favicon is required for the first milestone.
10. **Release shape:** ship only after all routes are coherently migrated; do not expose a mixed old/new UI on `main`.

---

## 24. Claude Code review checklist

Claude Code should review this plan against the live repository and answer each item with `Agree`, `Change`, or `Missing`:

### Coverage

- Does the route matrix include every GET, POST, redirect, download, disabled state, and error family?
- Are all query and form state contracts represented?
- Are Candidate Finder, Option Trading, Portfolio, Lab, Scorecard, ticker detail, and benchmark-ETF exception flows covered?

### Architecture

- Does any proposed helper duplicate an existing primitive?
- Does any phase risk adding analytics or data-state logic to `serve/`?
- Does the CSS module structure work with the current static-file server and cache rules?
- Is the proposed no-framework/no-dependency approach still the safest option?

### UX

- Is grouped sidebar navigation the right hierarchy?
- Are page templates consistent without flattening important differences?
- Are tables, controls, warnings, and source/freshness states given correct priority?
- Does any proposed disclosure hide information that must remain immediately visible?

### Testing and release

- Are existing test files/guardrails correctly identified?
- Which missing regression tests should be added before markup migration?
- Are viewport, keyboard, touch, empty/error, and query-state matrices sufficient?
- Are branch integration, rollback, and milestone gates safe for concurrent Claude/Codex work?

### Required review output

Claude Code should correct this plan directly and record:

1. a findings table with severity and exact plan section;
2. any missing routes/states/files/tests;
3. the wording/sequence changes applied to this file;
4. a final `APPROVE` or `NEEDS CHANGES` verdict.

After reconciling all high/medium findings, Claude Code should begin implementation immediately. The product choices are already approved in Sections 2 and 23.

This review was completed on 2026-08-10; the findings, applied corrections, Codex decisions, and final verdict are recorded in Section 27.

---

## 25. Handoff summary

The safest path is to build the visual system first, validate it on six deliberately different pilot surfaces, and only then migrate the rest of the product. The core protection is not the colour palette; it is the combination of a strict presentation-only change budget, complete machine-readable route/form/query inventory, reusable components, contained tables, explicit state semantics, runtime-tested interactions, responsive/accessibility gates, artifact-write detection, proportional regression testing, code-only rollback boundaries, and a final integration audit.

This document is the implementation blueprint. It is not permission to alter Golden Vector's analytical behaviour.

---

## 26. Claude Code execution directive

This section makes the document self-contained as an implementation assignment. Claude Code is the primary implementation owner and should perform the following without requiring a separate long prompt.

### 26.1 Required reading and plan correction

Before editing code, read completely:

- `AGENTS.md`;
- `CLAUDE.md`;
- `ARCHITECTURE_FOUNDATIONS.md`;
- `GOLDEN_VECTOR_VISUAL_REDESIGN_GUIDE.md`;
- this plan;
- `claude-python-rebuild-spec-gold-v1.md`;
- `codex-full-briefing.md`.

Audit this plan against the live repository. Verify routes, methods, aliases, queries, forms, redirects, downloads, errors, renderers, JavaScript contracts, tests, privacy boundaries, data-state displays, file ownership, and sequencing. Correct this file directly; do not substitute a separate review document. Reconcile all high/medium findings, record the applied corrections and verdict, and then begin implementation immediately.

### 26.2 Complete implementation mandate

Implement Phase 0 through Phase 8 sequentially using these working batches:

1. Phase 0 alone;
2. Phases 1-2 together;
3. Phase 3 alone;
4. Phases 4-5 together;
5. Phases 6-7 together;
6. Phase 8 alone.

Treat the redesign as one coherent shippable product milestone. Use small reversible checkpoints on `dev-vic`, validate every batch before continuing, and do not merge a visibly partial old/new product into `main`. After Phase 8, complete the post-Phase-8 defect follow-up (Section 17) and the independent final review before final integration.

### 26.3 Autonomy and stop conditions

Work autonomously and continuously. Do not request routine file-by-file approval or pause between safe implementation steps. The decisions in Sections 2 and 23 are approved.

Stop only for:

- a genuine product decision absent from this plan;
- a destructive or security-sensitive action requiring authority;
- an unrelated-user-change conflict that cannot be safely isolated;
- a repeated blocker that cannot be resolved from repository evidence;
- discovery that completion requires changing analytical behaviour, schemas, artifacts, or another out-of-scope contract.

At the Phase 3 pilot gate, capture sanitized desktop/tablet/mobile evidence and perform a serious self-review. Continue automatically when the result matches the approved guide and plan; pause only for a major unresolved visual/product ambiguity.

### 26.4 Scope discipline

Preserve every route, query, form, redirect, status, download, table row/column/order, filter/sort behavior, warning, explanation, freshness state, and data meaning defined in this plan. Do not change calculations, rankings, thresholds, eligibility, loaders, pipelines, schemas, manifests, artifact production, or source resolution for visual convenience.

Keep the implementation server-rendered, local, offline-capable, dependency-light, and auditable. Add no framework, template engine, external font/CDN, telemetry, remote asset, or new dependency. Do not hide rows/columns or add pagination. Do not trigger live refresh/paid data calls during visual QA. Use temporary fixtures for write tests and sanitized fixtures for Portfolio screenshots. Preserve unrelated working-tree changes, including `naukri.md`.

Search before adding helpers. Reuse the primitives in Section 10 and expand existing no-analytics scans whenever presentation code moves into new files.

### 26.5 Testing and evidence

Follow Section 18.6 exactly. The complete repository suite is not run by default. Use page-specific checks, the focused release selection, new semantic/accessibility/responsive/JavaScript tests, repository-wide collection, the browser matrix, real-workspace read-only smoke checks, artifact hashes, and changed-file proof. Run the complete suite only when a stated conditional trigger applies.

Every batch must leave an auditable record of commands, results, screenshots/measurements where relevant, and unresolved findings. Do not treat screenshots as a substitute for route, DOM, behavior, or accessibility tests.

### 26.6 Agent coordination

Read-only agents may audit routes, tests, accessibility, responsive behavior, or final changes. Do not let multiple coding agents concurrently edit the shared shell, token/CSS system, common components, or overlapping renderers. One implementation owner maintains the shared presentation spine. The final review may use focused independent agents; all high/medium findings must be fixed and affected checks rerun.

### 26.7 Git, integration, and delivery

Follow `AGENTS.md`, including the mandatory branch/worktree/file-overlap integration audit. Treat phase commits as development checkpoints, not separately shippable partial redesigns. Perform final `dev-vic` to `main` integration only after the complete Definition of Done passes and the final review is resolved.

The final handoff must report:

- corrections applied to this plan;
- implementation and final component architecture;
- routes, states, and viewports verified;
- exact focused test commands/results and collection result;
- accessibility and JavaScript runtime evidence;
- artifact-write and external-request checks;
- performance comparison;
- complete changed-file inventory and presentation-scope justification;
- independent-review findings and fixes;
- Git/branch/integration status;
- any residual limitations.

---

## 27. Audit correction record and verdict (Claude Code, 2026-08-10)

Claude Code audited this plan against the live repository at commit `6c5015d` (all seven required documents read completely; three read-only repository sweeps covering routes/forms/queries, CSS/JS/static contracts, and the test suite). Every measurable Section 3 claim verified exactly (868 CSS lines; 107/55 hex occurrences/unique; 192/69 non-vendor colour literals; 24 HTML-emitting files; 33/20/13 table/form/SVG sites; 0 captions/`scope=`/`@media`; undefined `--border`/`--paper`; 2 `.table-scroll` sites; unstyled `.flash-warning`; 1,555 collected tests). Branch state was clean: `dev-vic` == `origin/dev-vic`, `origin/main` synchronized, `origin/codex-source-mode` fully merged, one worktree, no overlapping in-flight work, `naukri.md` intentionally untracked.

### 27.1 Findings and applied corrections

| # | Severity | Plan section | Finding | Correction applied |
|---|---|---|---|---|
| H1 | High | 18.2, 10.1 | Global serve no-analytics sweep globs `serve/*.py` non-recursively; the planned `serve/ui/` package would escape it | Recursive-scan requirement recorded in 18.1; bound to the commit that creates any `serve/` subpackage |
| H2 | High | 6 | App has no `405` and no `HEAD` handling; method mismatches produce two 404 flavours; `/portfolio/lots*` checks 403 before method | Error-handling row rewritten; route-matrix tests pin actual behaviour |
| H3 | High | 9.1 | CSS split breaks `tests/test_workspace_datatables.py:114-135` (`:root`/`.top-nav` asserted in raw `workspace.css`); server has no `ETag`, so `@import` chain serializes re-downloads | Migration notes added to 9.1: intentional test updates, recursive `css/**` scans, Phase 8 timing gate with `<link>` fallback rule |
| H4 | High | 12.1, 15.10 | Ticker validation branches worse than described (hardcoded `12M` anchor, success-styled error flash, `app_config=None` strips help); empty company POST reports a save that never happened | Sections corrected; defects D1/D2 registered; characterize-then-fix-post-Phase-8 policy recorded |
| H5 | High | 18.2.17 | Real DataTables runtime tests infeasible without a new dependency (vendored build requires jQuery; only a 20-line Node DOM shim exists) | Item 17 rewritten per Codex decision: real-browser evidence + pytest static contracts; no jsdom |
| M1 | Medium | 6 | Reconciliation CSV: missing manifest entry → 503, not the bodyless 404 (unreadable file only) | Row corrected |
| M2 | Medium | 6, 15.6 | `POST /option-trading/refresh` is live but unreferenced by any form | Row corrected; preserve without adding UI |
| M3 | Medium | 6.1 | Missing contracts: CF arbitrary-param round-trip and `saved` dead-end; preset links reset builder state; Tool B `rank_by` one-round-trip degrade; `differences_only` truthy set; Tool D formless hidden-input situation and silent source reset; ticker `return_to` all-params rule; sizing form drops `window`; silent `beta_window`/Lab/option-horizon fallbacks | Addendum block added to 6.1 |
| M4 | Medium | 15.1 | Scenario-failure wording conflated runtime fallback (warm warning) with parse failure (bare 400) | Safety check split into the two real paths; D6 registered |
| M5 | Medium | 15.11 | Every error page highlights Candidate Finder as active navigation | Documented intentional presentational correction: error shell renders no active navigation item |
| M6 | Medium | 13.2 | Floating layers measurably diverge: help dialog z-index 1000 under tooltips 9999; rug tooltip unclamped, no Escape/scroll/resize dismissal | Evidence recorded in 13.2 |
| M7 | Medium | 18.1 | Guardrail inventory missing `tests/test_benchmark_comparison.py` and `tests/test_rebased_overlay_panel.py`; `tests/test_lab_curve.py:624` asserts a hardcoded chart colour; Node test hard-fails without node; scans CWD-dependent; no pytest markers | 18.1 table and gap notes extended |
| M8 | Medium | 15.7 | Portfolio "17 tables / 25 forms / 22 disclosures" are data-dependent (1 + 2×lots) | Coverage checklist keyed to render sites, not counts |
| M9 | Medium | 18.2 | Five near-duplicate WSGI helpers across test files | Phase 0 task 16: consolidate into `tests/helpers.py` |
| L1 | Low | 3, 9.2 | `--positive`/`--negative`/`--neutral` defined but never referenced; values re-hardcoded in `charts.py` | Baseline bullet added |
| L2 | Low | 3 | 192/69 scope includes `workspace.css`; no colour-bearing inline `style=` literal exists in Python | Baseline bullets corrected |
| L3 | Low | 3 | Single inline script; z-index inventory; error-nav fact | Baseline bullets added |

Defects D3-D8 (option sizing form drops `window`; `_safe_return_to` accepts CR/LF; unknown ticker + option lens can 503 before 404; CF parse failure renders bare 400; Tool D silent source reset display mismatch; `/lab/dial` double-decodes PATH_INFO) are recorded in the defect register with full detail, per the register requirement below.

### 27.2 Codex decisions adopted (2026-08-10)

| Q | Decision |
|---|---|
| Q1 Evidence | Commit text/JSON matrices, DOM/overflow measurements, artifact hashes, route timings, and ~10-15 representative sanitized screenshots under `reviews/codex/milestones/visual_redesign/`. No full screenshot matrix; automated measurements cover the complete route/viewport matrix; debug screenshots stay untracked; never commit private data. |
| Q2 JS testing | Option (b): no jsdom/`package.json`/new dependency. Scripted real-browser DataTables verification with recorded evidence; `node --check` on every first-party file; zero-dependency Node shim harnesses where feasible; pytest static/semantic contracts. Missing Node stays a hard failure — required JS coverage must not silently skip. |
| Q3 Defects | Option (a): Phases 0-8 stay presentation-only. Defects are documented in one maintained register (identifier, severity, route/files, observable behaviour, likely cause, discovery date, deferral reason, proposed fix, required regression tests, security/data/analytics impact), characterized where needed without describing broken behaviour as the desired contract, and resolved in separate labelled follow-up commits after Phase 8 and before final release. |
| Q4 Phase 3 gate | Option (b): capture sanitized pilot evidence, serious self-review, continue autonomously when the result matches the approved guide/plan; pause only for genuine product ambiguity; no `main` merge before final approval and all gates. |
| Q5 CSS | Option (a): `workspace.css` stays the stable `@import` entry point over modular `css/` files; tests and consistency scans cover `css/**` recursively; measure real local route performance; fall back to multiple `<link>` elements only on a measured material regression. |

### 27.3 Verdict

**APPROVE (with the corrections above applied).** Coverage: the route matrix, query inventory, and test inventory are correct after the listed corrections; no missing route was found beyond the documented nuances. Architecture: no proposed helper duplicates an existing primitive; the CSS module structure works with the current static server unchanged; the no-framework/no-dependency approach is confirmed as the safest option. UX: the grouped sidebar hierarchy, page templates, and state-visibility priorities are sound. Testing/release: gaps and guardrails are correctly identified after the 18.1/18.2 extensions; the branch/rollback/integration gates are safe for the current single-owner implementation. Implementation begins immediately per Section 26.
