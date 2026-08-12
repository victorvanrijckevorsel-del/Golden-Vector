# Golden Vector professional platform redesign — FINAL implementation plan

- **Decision-maker:** Claude Code (per Victor's 2026-08-12 instruction: Claude owns the final technical plan)
- **Based on:** Codex proposal `codex_professional_platform_redesign_plan_2026-08-12.md` (now superseded by this file)
- **Date:** 2026-08-12
- **Repository base verified:** `f45560a` (dev-vic == origin/main, no unmerged branches, single worktree)
- **Status:** FINAL — authorized for implementation, Phase 1 first
- **Product scope (approved by Victor):** platform-wide professional/institutional visual system with `/ticker/<T>` as the reference implementation
- **Correctness scope:** fractional gold-dial false scenario, repeated basis dates, Share-price chart units, ticker navigation identity, and truthful dual-source Corporate Resilience

Every code claim in this plan was verified first-hand against the tree at `f45560a` on
2026-08-12 (three independent file-level verification sweeps: serve/UI layer, Tool D data spine,
tests + locked requirements). Where this plan disagrees with the Codex proposal, the disagreement
is recorded in §1 with the evidence.

---

## 1. What changed from the Codex proposal (decision log)

The Codex proposal was structurally sound: its §3 evidence claims all verified TRUE, its behavior
contracts are mostly adopted unchanged, and its milestone spine (correctness → data spine →
primitives → ticker → rollout → hardening) survives. The following decisions change it:

| # | Change | Why |
|---|---|---|
| D1 | **Removed the review-protocol machinery** (old §20, §21, Milestone 0 tasks 1–2, "Claude should review" framing). | Obsolete: Victor made Claude the decision-maker. This is the final plan; the next action is implementation. |
| D2 | **Folded Milestone 0 into Phase 1** as its first task group. The branch/worktree integration audit is already done and recorded here: `dev-vic` is identical to `origin/main`, `origin/codex-source-mode` is fully merged, one worktree. A fresh audit is still required at each merge gate (AGENTS.md rule), but there is no standing overlap to reconcile. | A whole milestone for baseline capture + an audit that is already clean is ceremony. |
| D3 | **Merged Milestones 5 and 6 into one platform-rollout phase (Phase 5) with a single migration pass per page.** Codex had source-control migration (M5) and density/table migration (M6) touching Tool B, Tool D, and Candidate Finder **twice each**. | One pass per page = fewer commits per surface, one review per surface, no interim half-migrated states. |
| D4 | **Corrected the Tool D reader map.** Codex listed `serve/ticker_page/data.py` as a Tool D reader — it is not; it loads only the five ticker-page artifacts. The real path is `serve/workspace_state.py:254-264` (loads `tool_d_spot` → `WorkspaceState.latest_tool_d`) → `serve/detail_page.py:120` (ticker-only, last-row-wins index). §6.6 has the corrected consumer table. | Editing the wrong file map wastes a lane and misses the real collapse point. |
| D5 | **Added a missed, destructive Tool D consumer: the Lab vintage store.** `lab/vintages.py:127-134` snapshots `tool_d`/`tool_d_spot` into an append-only store whose dedupe (`:104-124`) does not dedupe within a batch. Dual-source rows would permanently double-write the pinned `tool_d_quality_score` accrual series (`lab/scorecard.py:73-74`, first verdict ~2031). Phase 2 filters the Lab snapshot to Our View and adds an in-batch duplicate-key fail-loud guard. | This is the one consumer where the bug is irreversible (append-only history), so it is now a named task + test, not a footnote. |
| D6 | **Corrected the Tool B readiness assumption.** Codex implied Tool B is dual-source-ready end-to-end. In fact persisted Tool B is a single Our View decision artifact with `_official` sidecar columns; the Yahoo view is produced by in-memory column swapping (`screening/pipeline.py:51-76`, `materialize_tool_b_finance_source`). The genuinely dual-source persisted precedent is the **`gold_response` ticker-page artifact** — contract-owned, `(ticker, finance_source)`-keyed, duplicate-validated (`contracts/ticker_page.py:91, 489`). Phase 2 copies that pattern, not "Tool B's". | Building on a wrong precedent invites the wrong shape. `compute_tool_d_outputs()` already threads `finance_source` into all three internal Tool B evaluations (`model/tool_d.py:120,134,146`), so the CLI-side change is still just a second call — but the persistence/contract side follows `gold_response`. |
| D7 | **Created a Tool D contract module.** No Tool D schema authority exists today — `TOOL_D_OUTPUT_COLUMNS` lives in `model/tool_d.py:20-75` and *nothing validates a Tool D frame on read or write anywhere*. Phase 2 adds `golden_vector/contracts/tool_d.py` (schema version, columns, key columns, frame validator), mirroring `contracts/ticker_page.py`; the model imports from it. Codex left ownership as "reconcile first"; this is the reconciliation. | Declaring `(ticker, finance_source)` as the key requires a place where keys are declared and enforced. |
| D8 | **No new per-source filenames.** Both sources live as rows in the existing `tool_d_latest_*` artifacts, same aliases, same run-stamped names. A name like `tool_d_latest_yahoo_<runid>.parquet` would fail the immutable-resolution regex `model_state.py:1817-1819` and the pruning globs `run_pruning.py:256-259`, silently degrading the artifact to STALE. | Keeps model-state, pruning, and replay-manifest untouched at the filename layer. |
| D9 | **The dial fix is server + JS, not JS-only.** The server emits `value="{spot:g}"` (fractional) against `step="1"` (`corporate.py:431, 453`; `config/ticker_page.yaml step_usd: 1`), so browsers snap the position before JS runs. Phase 1 fixes both sides: the server emits a step-aligned slider `value` while the payload keeps exact spot, AND `gold-dial.js` captures the browser-normalized boot position as its clean-state baseline. Codex specified only the JS side plus a reset rule. | Belt-and-braces across UA behaviors, and the no-JS HTML stops lying about the slider position. |
| D10 | **The overlay-chart generalization also fixes a third caller.** `options.py:558` (open-interest trend) passes `base=0.0` but inherits the hard-coded "Rebased price comparison" aria-label and "indexed value" table caption from `_build_multiline_overlay_svg()` (`charts.py:515, 543`). The display-mode parameter fixes Share-price AND gives the OI trend an honest count-mode caption. | Same root cause, same fix, zero extra architecture. |
| D11 | **The data-card primitive must reconcile an existing class collision.** `format_helpers._metric_card` emits `<article class="panel metric-card"><h3>…` (styled by `components.css:31-42`, ~30 call sites in options/behaviour/portfolio/candidate-finder), while `corporate._headline_cards` emits a *different* `<div class="metric-card">` with `.metric-card-label/-value/-basis` children (styled by `pages.css:205-213`). Phase 3 defines the shared card with a **new class name**, migrates the ticker headline cards in Phase 4, migrates remaining `_metric_card` callers during Phase 5, and only then retires the double-booked name. | A "shared card" that reuses the colliding class would silently restyle 30 call sites. |
| D12 | **The shell `page_id` extension must untangle a triple-purpose parameter.** `_page_shell(title, body, *, active_nav="")` uses `active_nav` for `aria-current`, for the header label via `_PAGE_LABELS`, and for `<body data-page>` (`ui/shell.py:52, 74, 75`) — which is why the ticker page's header chrome literally reads "Candidate Finder" today. The extension separates the three roles behind the existing signature as a compatibility contract. | Codex's recommendation was right but under-specified; tests assert on `_NAV_LINKS`/`_PAGE_LABELS`/`data-page` and must keep passing for unmigrated pages. |
| D13 | **The real-JS dial test uses the repo's existing node-shim pattern, and node failures stay hard.** The repo already runs real JS under node three ways (module drivers in `test_ticker_page_js_parity.py:1040`, `node --check` in `test_workspace_shell.py:94`, a `vm.runInNewContext` DOM shim in `test_rebased_overlay_panel.py:272`); Node v24 is a recorded environment fact, and Codex's earlier locked decision (visual-plan §27.2 Q2) is that missing node is a hard failure, not a skip. `gold-dial.js` has no export and touches `document` at load, so the test ships a small DOM shim (~100–200 lines, modeled on the drawer shim). The ARCHITECTURE_FOUNDATIONS Playwright behavioural lock is satisfied at the Phase 4 batched browser gate. | "New real-JS test using existing dependencies" is feasible but only via this specific pattern; naming it prevents an accidental jsdom/npm dependency. |
| D14 | **CSS ownership table corrected: there are nine modules, not eight.** `css/forms.css` was missing from Codex's list. `workspace.css` imports: tokens, base, shell, components, **forms**, tables, charts, pages, responsive. | Form-control restyling (density, compact controls) belongs in `forms.css`; without the row it would have landed in `components.css`. |
| D15 | **Scoped the request-time recompute cleanup precisely.** `/tool-d` (`overview_tool_d.py:104-123`) and Candidate Finder (`candidate_finder_data.py:424-445, 1347-1390`) recompute Tool D (and Tool B) in-process for Yahoo mode and for gold scenarios. Phase 2 replaces the **at-spot Yahoo** recompute with persisted dual-source reads on both pages. The **non-spot gold-scenario** recompute path remains as existing legacy debt, explicitly out of scope (recorded in §10 non-goals). | Killing the scenario recompute is a separate architecture project; conflating it with this one risks the Finder's scenario feature. |
| D16 | **FCF-vocabulary claim precision.** The ban (`tests/test_screening_layer1.py:148-164`) covers identifier tokens (`fcf_yield`, `sustainable_fcf_musd`, `fcf_breakeven`, `FCF_FAIL`) in `golden_vector/**/*.py` + `config/**/*.yaml` — not prose. The rule stands: no removed-FCF *fields* return as a styling task. | Plans should cite tests as they are. |
| D17 | **Two Codex deltas confirmed as genuine deviations from the locked requirements doc, kept with eyes open** — see §2.3. The locked doc says headline shows BOTH spot and scenario values (`claude_ticker_page_requirements.md:46`) and defers jump-to-ticker (Q17, §7). Victor's approval of the full Codex scope sanctions both deltas; spot remains visible in the dial-control context line and in expanded tables, so no information is lost. | The supersession is deliberate and traceable, not silent drift. |

Simplifications: milestone count 8 → 6; two-pass page migration → one pass; review-protocol
sections deleted; Milestone 0 reduced to a task group. New work: Lab vintage guard (D5), Tool D
contract module (D7), server-side dial value alignment (D9), OI-trend caption fix (D10),
metric-card reconciliation (D11), forms.css row (D14).

---

## 2. Authority, supersession, and locked behavior

### 2.1 Authority order

1. Victor's explicit decisions recorded in this plan.
2. `AGENTS.md`, `CLAUDE.md`, `ARCHITECTURE_FOUNDATIONS.md`, `soul.md`.
3. `reviews/codex/claude_ticker_page_requirements.md` (locked), except the explicit deltas in §2.3.
4. Current contracts, code, and tests at the verified base.
5. Historical plans, reviews, screenshots, mocks — evidence, not authority.

### 2.2 Supersession

This plan supersedes:
- `codex_professional_platform_redesign_plan_2026-08-12.md` (the proposal this finalizes);
- the presentation direction and remaining phases of `GOLDEN_VECTOR_VISUAL_REDESIGN_PLAN.md`
  (its Phases 0–2 outputs — tokens, shell, guardrail tests — are shipped and are the foundation
  this plan extends; its locked toolchain decisions §27.2 remain in force, notably Q2 node-hard-fail
  and Q5 CSS import manifest);
- the ticker plan's Yahoo-resilience deferral (C6).

Old files remain unchanged as audit history.

### 2.3 Explicit decision deltas (vs locked requirements)

| Locked text | New decision | Sanction |
|---|---|---|
| Ticker redesign scoped to `/ticker/<T>` only | Ticker stays the pilot; the visual system rolls out platform-wide | Victor approved platform scope 2026-08-12 |
| "Show BOTH values: reported at spot AND at the scenario" on headline cards (`requirements:46`) | One active headline value per card; exact spot stays visible in the dial-control context line and in expanded Spot/Scenario table columns | Victor's duplicate-number feedback; approved via Codex plan scope |
| Jump-to-ticker deferred (Q17 unanswered, requirements §7) | Configured-universe jump ships in the command bar | Visible in the approved mock; approved via Codex plan scope |
| Corporate Resilience deliberately disabled in Yahoo mode (C6) | Healthy Yahoo mode gets its own persisted Tool D rows and source-isolated percentiles | Core approved correctness scope |
| Request-time source recomputation tolerated | Ticker + at-spot Tool D surfaces read persisted dual-source artifacts | ARCHITECTURE_FOUNDATIONS Foundation 1 |

### 2.4 Locked behavior that remains (verbatim from the proposal, all verified)

- Section order: Performance → Corporate Finance → Market Behaviour → Options (only when options
  exist) → Compare → Your Inputs and Notes. Currency Attribution stays a conditional subsection of
  Performance, not a primary nav anchor.
- No compiled/blended score returns to the ticker page. Failing screening checks remain at-spot
  sentences, shown only on failure. "Target window" naming stays.
- Gold scenario evaluation stays inside the sanctioned three-module browser exception
  (`ARCHITECTURE_FOUNDATIONS.md:40-56`); no financial modeling in request handlers.
- Every chart keeps an accessible data-table equivalent. Source/basis/dates/missingness stay
  truthful and inspectable. No mixed currencies without explicit normalization.
- Dial range stays $2,000–$6,000 from `config/ticker_page.yaml`; every threshold lives once, in config.
- No removed-FCF identifiers return (D16). No new external data source; no live API calls.

---

## 3. Verified defects being fixed (evidence)

All verified first-hand at `f45560a`:

1. **Gold-dial false scenario.** Server emits `step="1" value="4477.4"` (`corporate.py:431, 451-454`);
   the browser snaps the position to 4477; `gold-dial.js:319` compares against exact spot with
   `SPOT_EPSILON = 1e-9`; `paint()` runs unconditionally at boot (`:368`), so the scenario column
   un-hides and the `role="status"` live region announces — with zero user interaction. Reset
   (`:363`) writes the fractional spot back into the snapped control: an infinite loop into the
   false state. There is no touched-flag and no fractional handling anywhere. Spot **cells** are
   correctly evaluated at exact spot (`:328`) — only the moved-predicate, Reset, and announcements
   are wrong.
2. **Basis text repeated eight times.** `spot_label` ("fwd @ spot $4,477/oz as of 2026-08-11") is
   printed in the section intro (`corporate.py:1086`) and under each of the six headline cards
   (`:718`); the dial control adds an eighth, differently-worded copy (`:436-441`).
3. **Performance controls parsed but invisible.** `chart_h` (1Y/3Y/5Y, default 1Y) and `chart_view`
   (`rebased`/`price`, default rebased) are parsed in `workspace.py:613-616, 1093-1102` — and no
   emitter exists anywhere in serve. The state is reachable only by hand-editing the URL.
4. **Share-price view rendered by a rebased-only formatter.** `_build_multiline_overlay_svg()`
   bakes in base-100 gridlines, `% ` crosshair values, `aria-label="Rebased price comparison"`, and
   an "indexed value" table caption (`charts.py:472, 505, 515, 543`); `sections.py:156` calls it
   unconditionally for both views. The OI-trend caller (`options.py:558`) inherits the same wrong
   caption. The persisted rebased series itself is correct and untouched — this is a rendering-mode
   bug only. `charts.py` has no price-level line builder; the generalization is the fix.
5. **Yahoo resilience disabled downstream of a capable model.** `model/tool_d.py` threads
   `finance_source` through all three Tool B evaluations and blocks Yahoo debt/interest borrowing
   (`:304-310`); but `cli.py:1734-1744` never passes it, `build_score_percentiles()` empties Tool D
   records in Yahoo mode (`model/ticker_page.py:577-582, 599-603`), and `_resilience_group()` renders
   a disabled message (`corporate.py:891-896`). The reason string is duplicated in two modules
   (`corporate.py:50`, `ticker_page.py:431`) — consolidate during Phase 2.
6. **Navigation identity is false.** `detail_page.py:359` sets `active_nav="candidate_finder"` for
   every non-option-lens ticker view; via the triple-purpose shell parameter the header chrome reads
   "Candidate Finder" (D12).
7. **`.button-like` has no stylesheet definition.** Emitted at 7 sites in 5 files (incl. the dial
   Reset button); zero matches in all nine CSS modules — these controls render as UA defaults.
8. **Consumer-grade looseness.** 1240px cap on bare `main` (`base.css:14-20`, app-wide); pill
   controls; unframed headline cards; inconsistent numeric alignment; no shared segmented control,
   command bar, basis strip, or data card in `ui/components.py` (it has exactly: page_header,
   section_heading, section_nav, toolbar, empty_state, disclosure).
9. **Inputs area is four always-open panels** (`detail_forms.py:132, 182, 297, 372`; anchors
   `inputs`/`reporting`/`verification`/`notes`), with only `inputs` in the section nav.

---

## 4. User-visible behavior contracts

These are adopted from the Codex proposal with the corrections noted; they are the acceptance
authority for Phases 1 and 4.

### 4.1 Financial-source control

Labels exactly: `Financials source [Our View] [Yahoo Fundamentals]`. Default Our View; unknown
values normalize via `screening.pipeline.normalize_finance_source` (canonical `our`/`yahoo`,
`contracts/ticker_page.py:55`). Exactly one selected link, `aria-current="true"` + non-color
indicator; ordinary links (not ARIA tabs) built with `url_helpers.build_page_url` — which returns
**raw unescaped URLs by design**, so every emitter must `escape(..., quote=True)` as
`detail_page.py:167` does. Links preserve unrelated query state (chart_h, chart_view, behaviour
window, compare state, options target window, lens). Switching source resets the temporary gold
scenario; updates Corporate Finance values, checks/fail notice, gold-response payload, Corporate
Resilience, and Compare finance metrics as one server-rendered state; leaves Performance, Currency
Attribution, and Market Behaviour untouched. Missing active-source values stay missing — never
promote the alternate source.

### 4.2 Corporate Finance basis strip

One visible strip per section, e.g. `Our View · spot gold $4,477.40/oz as of 12 Aug 2026`. Shared
dates appear once in open content; no date-bearing element inside individual cards. Never present
Tool B's model/run `as_of_date` as a financial-statement period; omit a single "financials date"
from the open strip entirely (no authoritative shared period exists — Yahoo field-level
`period_end` and Our View verification dates differ). Hypothetical scenario prices carry no "as
of". Full provenance (field-level statement periods, market snapshot date, gold source date, FX
status, refresh identity, data-quality reasons) stays in "Data quality and sources". Stale /
missing / misaligned families get one compact visible status with a plain reason.

### 4.3 Gold-dial state machine

**State A — unavailable** (missing/non-finite spot, spot outside configured range, missing
source-specific response pack, degraded/nonlinear response): spot KPIs stay readable when
trustworthy; slider disabled with one visible reason, `aria-describedby` pointing at it, truthful
`aria-valuetext`; no opposite-source fallback; no scenario slots. Never silently clamp an
out-of-range spot.

**State B — untouched spot:** the server emits a **step-aligned slider `value`** while the JSON
payload keeps exact fractional spot (`spot_gold_usd`) for all evaluation/display/provenance; at
boot, JS captures the browser-normalized `input.value` as the clean-state baseline. One spot value
per card; `Spot gold $4,477.40/oz` in the control context; Reset rendered but disabled (skipped in
tab order); `data-scenario-active="0"`; **no announcement on load** (the current always-announce
`paint()` behavior is a bug); `aria-valuetext` reports exact semantics (`$4,477.40 per ounce,
spot`) even though the native position is 4477.

**State C — active scenario:** entered only by genuine user interaction moving off the baseline.
Control shows `Scenario $4,200/oz · baseline spot $4,477.40/oz`; Reset enabled; each card replaces
its headline with one scenario value; expanded tables show labelled Spot and Scenario columns;
debounced live-region update (`Scenario $4,200 per ounce. Corporate finance values updated.`);
`aria-valuetext` carries both. Nothing persists; nothing enters the URL.

**State D — returned/reset:** manual return to the baseline position clears scenario state; Reset
assigns the saved baseline (never the fractional exact spot) to the range; restores spot values,
hides scenario columns, disables Reset; announces only after a user action. Spot evaluation always
uses exact `payload.spot_gold_usd` — do not round the payload value itself.

Edge conditions: tiny genuine movements may round to identical KPIs — one value still shows and the
state label stays explicit; invalid ratios render exact guards (`Not meaningful — EBITDA ≤ 0`),
never zero/blank/infinity; without JavaScript the persisted spot page stays complete and honest
(ARCHITECTURE_FOUNDATIONS `:56`).

### 4.4 Corporate Finance headline metrics

The six current cards stay (cash margin/oz, margin %, AISC margin yield, EV/EBITDA fwd, forward
P/E, stressed forward leverage) — they have persisted display-ready spot values and work without
JS. Revenue and Forward EBITDA have line coefficients but **no persisted display-ready spot
columns**: promoting them requires a separately reviewed, versioned gold-response schema change
(both sources, artifact/model-state/no-JS tests). Not in this project; do not derive spot headlines
in serve code. Card contract: one framed compact card; one primary value; tabular numerics; help
from the existing `COLUMN_HELP` registry; compact SPOT/SCENARIO state tag only where surrounding
basis is insufficient; no repeated dates; no unlabeled second value; missing/invalid values carry a
reason.

### 4.5 Corporate Resilience under both sources

Yahoo-mode basis label: `Yahoo financials · Our View mining assumptions`. This is the truthful
hybrid: statement-derived debt/interest/finance fields are Yahoo; manual mining assumptions (AISC,
production, sustaining capex, cash cost, reserve life) remain Our View by design
(`model/tool_d.py:301-307, 389-393`) — the label must say so, and the "?" help text explains it.
Full contract in §6.

### 4.6 Performance section

Visible controls: View (`Compare` / `Share price`), Horizon (`1Y`/`3Y`/`5Y`), and Compare-mode
series visibility (Stock, Gold, GDX, GDXJ). Initial state Compare + 1Y. Both views are required
product surface — Share price supplements Compare, never replaces it. Horizon is independent of the
beta window. Compare draws the persisted common-anchor series (every line = 100 on the shared
rebase date) with percentage semantics; the producer is untouched. Share price draws the subject
stock alone at persisted USD-normalized price levels (adjusted basis where available; disclosed
close-price fallback), with currency axis/tooltip/caption/ARIA/table language and zero
indexed-to-100 wording; if a future artifact carries another currency, formatting follows its
explicit `currency_basis`. One generalized `_build_multiline_overlay_svg()` with an explicit
display mode — no second overlay builder; the OI-trend caller adopts an honest count mode (D10).
Series-visibility checkboxes are progressive enhancement in a small presentation-only module:
server HTML renders all Compare series; JS reveals labelled native checkboxes (`aria-controls`);
Share-price mode hides them; the accessible table is never filtered. Missing/late/stale benchmark
rules stay unchanged.

Wide canvas: opt-in page token, validated at 1280/1440/ultrawide; pick the smallest measured width
that keeps the four-series chart and six-card grid legible (expected 1440–1600px); other routes
keep 1240px until they migrate.

### 4.7 Company command bar

Contents: identity (ticker, company, currency, jurisdiction from `config/universe.yaml` — missing
fields omitted, no guessed prose), quote (share price + market date from the resolved snapshot, no
browser fetch), jump-to-ticker (configured active tickers only, normalized via the existing ticker
helper, plain GET to `/ticker/<T>`, Enter submits, keyboard-accessible suggestions, honest
unknown-ticker behavior), source control, gold dial + Reset. Source survives a ticker jump; the
gold scenario never survives navigation or a source switch. Not sticky in the first release.
Responsive: ≥1280px two compact rows; 768–1279px three-row grid; 320–767px one semantic column with
a full-width slider; no meaning-bearing label ellipsized at 1024/768/390/320; section nav keeps its
tested wrapping and stops sticking at the current narrow breakpoint.

### 4.8 Inputs and notes

One closed top-level disclosure `Your inputs and notes` owning `id="inputs"`, containing the four
existing forms (Company Inputs, Reporting Calendar `#reporting`, Source Verification
`#verification`, Stock Notes `#notes`) with all field names, endpoints, redirects, `return_to`,
flash/error handling, and query state intact. Validation failure opens the parent and the relevant
child, then focuses the error summary. Existing anchors keep working. Presentation-only; no
persistence change.

---

## 5. Visual system specification

### 5.1 Design language

Dark neutral analytical canvas; density from borders + alignment, not shadows; rectangular/
segmented controls; gold reserved for active source/scenario/primary emphasis (never decorating
every box, never meaning "positive return" — green/red keep genuine semantics); numbers align
(data font + `font-variant-numeric: tabular-nums`), labels recede; short sentences replace
repeated micro-copy.

### 5.2 Extend the existing system — nine CSS modules, one manifest

`static/workspace.css` stays the sole `@import` manifest (locked decision Q5). Ownership:

| File | Allowed additions |
|---|---|
| `tokens.css` | raw colors, spacing/density vars, dimensions, radii, z-index, motion (sole color-literal file — `test_design_tokens.py` enforces) |
| `base.css` | true global foundations, typography, focus, forced-colors |
| `shell.css` | app frame, sidebar, header, drawer, page-context shell |
| `components.css` | command bar, segmented control, data card, basis strip, disclosure/control variants |
| **`forms.css`** | form-control presentation and density (was missing from the proposal — D14) |
| `tables.css` | table + labelled scroll-region behavior |
| `charts.css` | semantic chart/legend/control presentation |
| `pages.css` | ticker composition under a ticker-page root; page-local modifiers |
| `responsive.css` | breakpoint/coarse-pointer/reflow overrides only |

No new stylesheet bundle, no component library, no broad raw-element or `.terminal-density button`
descendants in Phases 3–4; components get explicit classes. Do not globally change raw `button` or
`.panel` during the pilot — add opt-in variants, migrate consumers, and only reconsider defaults
after Phase 5 (this includes the `main` 1240px cap).

### 5.3 Tokens and density targets

Semantic density tokens (compact control height, desktop panel/card padding, compact/standard gaps,
data-label/data-value sizes, command-bar wrap gap, content max width, terminal-density radius) —
values validated visually, not hard-coded up front. Targets: base content 14–15px (15–16px where
mobile forms need it); data labels 11–12px uppercase/letter-spaced; KPI values 18–22px data font;
compact controls 30–34px visual height with 44px touch targets; radii 4–8px; grid gaps 8–12px
desktop / 10–14px collapsed.

### 5.4 Shared primitives (Phase 3 builds; consumers migrate later)

| Primitive | Responsibility | Constraint |
|---|---|---|
| `command_bar` | pure shell for identity/nav/source/scenario groups | receives resolved text/HTML; no data lookups in `serve/ui` (AST guard `test_ui_components.py:184-208` enforces) |
| `segmented_control` | selected-link group for source, chart view, horizon | labelled group; exactly one `aria-current`; preserves caller-built URLs; caller escapes |
| `data_card` | successor to both `metric-card` structures (D11) | **new class name**; compatibility wrapper for `_metric_card` callers; retire the old name only after a zero-consumer dead-selector audit |
| `basis_strip` | one compact source/date/basis statement per data family | caller resolves semantics; component renders |
| `section_tabs` variant | compact rectangular restyle of existing anchor nav | anchors remain anchors |
| `terminal-density` modifier | opt-in tighter spacing for panels/tables/forms | pilot first; nothing global |

`.button-like` gets a canonical defined control class; a temporary compatibility mapping covers the
7 existing emitters; ticker consumers migrate in Phase 4, the rest in Phase 5; the legacy name is
removed only after a dead-selector audit.

### 5.5 Shell and navigation identity

Extend `_page_shell` with independent page context (`page_id`, `header_label`) vs `active_nav`,
honoring the documented compatibility contract (`ui/shell.py:69-70`) and the triple use (D12):
unmigrated callers keep identical output; the ticker profile gets `page_id="ticker_detail"`, an
honest header label, and **no** primary `aria-current`; the Option Trading lens keeps its genuine
current state. Sidebar-width reduction is deferred until after the pilot proves no label clipping.

### 5.6 Tables, charts, accessibility

Tables: `.table-region` stays the only horizontal-scroll owner; numeric columns right-aligned in
the data font; sticky headers only inside the labelled scroll region; thin separators; restrained
hover/focus; no page-level overflow workarounds; no provenance column silently hidden. Charts:
semantic SVG classes + centralized paint tokens; subject stock solid and modestly heavier;
benchmarks distinct dash patterns (non-color distinction); thin grids; explicit units; compact
legend; pointer detail keyboard/touch-reachable via the table. Accessibility: keep skip link,
landmarks, heading order, `main` focus target, `:focus-visible`, forced-colors, reduced-motion;
WCAG 2.2 AA contrast, 3:1 focus indicators and meaningful chart strokes; 44px touch targets
(including the small "?" help affordances via coarse-pointer hit-area, without growing the icon);
200%/400% zoom and 320px reflow; cards collapse 4/2/1 rather than shrinking indefinitely; any new
sticky geometry uses tokens.

---

## 6. Dual-source Corporate Resilience architecture (Phase 2)

### 6.1 Shape

Both sources are computed independently in the Tool D build and published as rows of the **same**
artifacts (same filenames/aliases — D8), keyed `(ticker, finance_source)`. Precedent: the
`gold_response` ticker-page artifact (D6). Readers select their source row; cohorts, ranks, and
percentiles are source-isolated; one source's failure or missingness cannot contaminate the other.

### 6.2 Contract (new module — D7)

`golden_vector/contracts/tool_d.py`:
- `TOOL_D_SCHEMA_VERSION = 4` (bump: authoritative row identity/cardinality changes);
- `TOOL_D_OUTPUT_COLUMNS` (moved from `model/tool_d.py`; the model imports it);
- `TOOL_D_KEY_COLUMNS = ("ticker", "finance_source")`;
- `validate_tool_d_output_frame()`: schema, canonical source values (`FINANCE_SOURCES` from
  `contracts/ticker_page.py:55`), duplicate composite keys rejected, one explicit row per active
  ticker/source in a healthy build (missing input data ⇒ a degraded status/reason row, never a
  silently absent key).
- Consolidate the duplicated Yahoo-reason constant (evidence §3.5) into one importable location.

### 6.3 Producer (`cli.py::run_tool_d` + refresh)

Resolve the coherent upstream generation once; run `compute_tool_d_outputs()` twice
(`finance_source="our"`, `"yahoo"`), each ranking only its own completed cohort; concatenate the
schema-identical frames; validate via the contract; publish immutable run-stamped artifact + spot
snapshot in one atomic generation (aliases as convenience, manifest pointer last — use the
`write_run_stamped_set` / `publish_option_artifacts_and_history_atomically` grouped pattern, with
`atomic_write_many`'s most-destructive-last rule). No live fetch: tests use committed fixtures; a
real refresh uses the existing configured flow. Stage timings self-report seconds + rows per source.

### 6.4 Persistence

Generalize `ingestion/persist.py::_latest_snapshot(frame)` → explicit `key_columns=("ticker",)`
default, preserving Tool A/B/C behavior (callers: `persist.py:230, 279`, `persist_tool_c.py:25`,
`persist_tool_d.py:27`, `app/perf_profile.py:121`). This is the single hardest blocker: today it
would silently drop one source per ticker from every published latest/spot file. Tool D passes
`TOOL_D_KEY_COLUMNS`. Behavior: latest row per composite key; validate requested key columns; fail
on duplicate composite keys at the same authoritative date.

### 6.5 Model state and migration

`tool_d` / `tool_d_spot` registrations, filename regex, prefix map, pruning globs, and
replay-manifest all stay valid because filenames don't change (D8). Additions: schema version 4 in
artifact metadata; `app/ticker_page_stage.py::_assert_tool_d_is_spot` (`:664-691`) gains a
source-completeness assertion (both canonical sources present or explicitly degraded) alongside the
spot assertion. Migration: v3 artifacts already carry `finance_source` ("our"); post-migration,
readers select by composite key, so an old generation keeps serving Our View honestly while Yahoo
shows a truthful "rebuild required" degraded state until the next successful refresh — never
reinterpret a one-row-per-ticker artifact as dual-source, never fall back across sources. Cache
identity continues through manifest-resolved immutable path/hash where already implemented
(`app/ticker_page_state.py:171-189`); the stat-based caches (`workspace_state.py:128-143`,
`candidate_finder_data.py:261-283`) pick up the new generation as today.

### 6.6 Consumers (corrected map — D4/D5)

| Consumer | Today | Phase 2 change |
|---|---|---|
| `serve/workspace_state.py:254-264` → `detail_page.py:120` (ticker page resilience) | ticker-only, last-row-wins | select exact `(ticker, selected source)`; absent row ⇒ source-specific reason |
| `corporate.py::_resilience_group` (`:891-896`) | hard-disabled Yahoo branch | remove branch; render selected row + `Yahoo financials · Our View mining assumptions` basis |
| `model/ticker_page.py::build_score_percentiles` (`:534, 577-582, 599-603`) | single ticker-indexed frame; Yahoo emptied | index by composite key; source-isolated percentile cohorts via `oriented_percentile`; delete the C6 branch |
| `serve/ticker_page/compare.py` | already reads `(ticker, finance_source, metric_key)` percentiles | inherits the fix; no structural change |
| `serve/overview_tool_d.py` (`:101, 104-123, 141-166`) | ticker-only + request-time Yahoo recompute | filter persisted frame by selected source (one row per ticker); at-spot Yahoo recompute replaced by persisted reads; scenario recompute untouched (D15) |
| `serve/candidate_finder_data.py` (`:424-445, 794, 1347-1390, 1464-1503`) | ticker-only dedupe would silently halve; separate at-spot Yahoo recompute | select matching source rows before `_prepare_source`; at-spot Yahoo path reads persisted rows; scenario path untouched (D15) |
| `portfolio/pipeline.py:269-274` + `portfolio/analytics.py:47` | ticker-keyed `latest_records_by_key` — would nondeterministically pick a source | explicit `finance_source == "our"` filter at the read boundary, labelled; source-aware portfolio resilience stays a separate product decision |
| **`lab/vintages.py:127-134` (D5 — destructive)** | append-only store, no in-batch dedupe | filter Tool D snapshots to Our View before melt; add in-batch duplicate-key fail-loud guard in `_append_vintage`; regression test |
| `app/ticker_page_stage.py:199-218, 664-691` | spot assertion only | source-completeness assertion (§6.5) |

### 6.7 Failure semantics

Missing Yahoo fields ⇒ a Yahoo row with non-OK status and exact reasons (degraded, excluded from
ranks — excluded, not merely flagged). Invalid build (missing expected key) ⇒ publication fails;
no half-keyed set. Unexpected exception in either source ⇒ abort the generation; previous current
stays active (fault-injection test). Our View upstream failure ⇒ required stage fails. Read-time
hash/schema/alignment failure ⇒ degraded state, never numbers from another source. Definition of
done for this feature: computed once, persisted composite-keyed, manifest-resolved, source-isolated,
fail-loud, zero duplicate helpers — not "a Yahoo card renders".

---

## 7. Implementation phases

Six phases. Each is independently reviewable and reversible; the Tool D schema migration is never
mixed into a CSS commit. Merge cadence (standing CLAUDE.md milestone workflow): Phases 1 and 2
merge to `main` on green gates; Phases 3+4 merge together after Victor's visual approval; Phase 5
merges per completed page batch; Phase 6 closes with final sign-off before the merge workflow.
A branch/worktree integration audit runs at every merge gate (currently clean — D2).

### Phase 1 — Baseline + ticker correctness (no data-model change)

Baseline task group (formerly Milestone 0): route screenshots at 1440/1024/390 for the required
data states; HTML payload size + server render timing for NEM Our/Yahoo; current focused + full
test baseline; evidence committed under `reviews/codex/milestones/platform_redesign/` (tracked, not
`.playwright-mcp`, not an external artifact link — copy the mock HTML + annotated target there too).

Correctness tasks:
1. **Dial**: server emits step-aligned slider `value` (payload keeps exact spot; per-source too);
   JS captures the boot-normalized baseline as clean state, tracks genuine interaction, suppresses
   boot announcements, Reset/manual-return restore the untouched state per §4.3.
2. **One headline value** per card; Spot/Scenario stay in expanded tables (existing markup, minimal
   scoped styling — full restyle waits for Phase 4).
3. **Overlay chart display modes**: indexed (default, back-compatible), price (currency formatter,
   honest captions/ARIA/table), count (OI trend — D10). `sections.py` passes the mode for
   `chart_view=price`; accessible tables match units.
4. New **real-JS dial test** via the node DOM-shim pattern (D13) covering: fractional boot, no-op
   input, genuine movement, manual return, reset, keyboard, both sources, missing payload,
   out-of-range, `aria-valuetext`, no boot announcement. Node missing = hard failure (locked Q2).

Primary tests: `test_ticker_page_corporate.py` (incl. the Python mirror + fixture regeneration),
`test_ticker_page_sections.py`, `test_rebased_overlay_panel.py`, `test_ticker_page_options.py`
(OI caption), `test_workspace_app.py`, `test_redesign_routes.py`, the new node dial test.

Gate: no duplicate headline values at untouched fractional spot; Reset clean for `$4,477.40` with
step 1; price view currency-true end to end (SVG, crosshair, caption, ARIA, table); OI trend no
longer claims to be a rebased price comparison; no boot announcement; focused suites green;
self-review (review-loop) before merge.

### Phase 2 — Persisted dual-source resilience (the data-spine phase)

Tasks, in dependency order:
1. `contracts/tool_d.py` (§6.2); model imports; schema v4.
2. `_latest_snapshot` generalization with explicit keys + tests for the A/B/C default path (§6.4).
3. Dual-source producer + atomic publication + stage timings (§6.3).
4. Model-state/stage assertions + migration semantics (§6.5).
5. Consumer updates in §6.6 order — Lab vintage guard (D5) and Portfolio filter land **before**
   the first dual-source artifact can be built locally, so no store ever sees unguarded rows.
6. Remove the Yahoo-disabled branches (`corporate.py:891-896`, `ticker_page.py:577-582/599-603`)
   and the at-spot Yahoo recomputes (D15) only after all readers are source-aware.
7. Consolidate the duplicated Yahoo-reason constant.

Primary tests: `test_tool_d.py`, `test_persist_tool_d.py`, `test_cli_tool_d.py`,
`test_model_state.py`, `test_ticker_page_stage.py`, `test_ticker_page_producers.py`,
`test_ticker_page_corporate.py`, `test_ticker_page_compare.py`, `test_candidate_finder_data.py`,
`test_workspace_app.py`, portfolio analytics suites, new Lab vintage regression test, plus a new
contract-module suite. Sentinel fixtures make the two sources deliberately differ; exclusion tests
use an otherwise-healthy subject + healthy control row (repo test canon).

Gate: `(NEM, our)` and `(NEM, yahoo)` both survive full/latest/spot persistence; different
fixtures ⇒ different values; Yahoo never borrows Our View debt/interest; ranks/percentiles
source-isolated; fault injection proves interrupted publication leaves prior current active;
`/tool-d` shows one row per ticker for the selected source; Lab store provably single-source;
Portfolio provably Our View; **full suite green (contracts changed — mandatory per the
proportional-scope policy)**; then one real local refresh producing a coherent dual-source
generation, verified through the manifest. Independent implementation review (Codex or fleet)
before merge — this is the highest-risk phase.

### Phase 3 — Shared professional UI primitives

Tasks: density/content tokens; `command_bar`, `segmented_control`, `data_card` (with the D11
reconciliation + compatibility wrapper), `basis_strip`, `section_tabs` variant, `terminal-density`
modifier; canonical control class + `.button-like` compatibility mapping (no non-ticker migration
yet); numeric typography/alignment utilities; shell `page_id`/`header_label` extension (D12);
component contract + dead-selector tests before any consumer migrates.

Gate: no duplicate component implementation; no raw colors outside `tokens.css`; `serve/ui` stays
presentation-pure (AST guard); unmigrated pages render byte-identical unless opted in; design-token,
UI-component, shell, and route guardrails green.

### Phase 4 — Ticker-page reference implementation

Tasks: command bar with configured identity + jump-to-ticker; source control + dial moved into it;
visible Performance view/horizon controls + series-visibility module; dense chart panel + correct
captions; one basis strip + data cards for Corporate Finance (repeated dates removed; field-level
dates stay in provenance); shell page-context fix (no false Candidate Finder state); ticker
`.button-like` consumers migrated; fail notice + disclosures restyled semantics-intact; compact
tables/headings through Market Behaviour, Options, Compare; four forms consolidated per §4.8;
Currency Attribution + all later additions preserved; every degraded/missing/empty state validated,
not just the NEM happy path.

Gate: full §8 acceptance checklist; one batched Playwright pass (file-loaded script, evidence to
files — token rule) covering the §9 data states and the dial behavioural lock; screenshots to
`reviews/codex/milestones/platform_redesign/`; no page-level overflow; all source/scenario/query
state works; no runtime regression. **Victor visual-approval checkpoint on the screenshots before
Phases 3+4 merge.** Independent review of the phase diff before merge.

### Phase 5 — Platform rollout (one pass per page — D3)

Per page, in order: Corporate Finance `/tool-b` → Corporate Resilience `/tool-d` → Candidate
Finder → Tool A → Tool C → Option Trading → Portfolio → Lab → Scorecard.

Each page's single pass: inventory components/states; same segmented source control + exact labels
where finance state repeats; replace duplicate presentation with shared primitives (including its
`.button-like` and `_metric_card` consumers); density modifier + numeric alignment; verify tables,
forms, charts, empty/degraded states, query-state links; run that page's focused suites; capture
before/after evidence. Must-not-change column per surface: rankings, eligibility, option/beta
signals, formulas, source resolvers, availability/liquidity/staleness safeguards, persisted
contracts, survivor-only Lab methodology, scorecard verdict semantics.

Only after all pages migrate: propose global defaults (bare `main` width, raw `button`, sidebar
width) as a separate reviewed commit; then the `.button-like`/legacy `metric-card` dead-selector
audit and removal.

Gate: shared visual grammar everywhere; no page-specific design system; same metric/source ⇒ same
name/unit/basis/selected-state everywhere; no request-time analytics introduced; focused suites
green per page; one batched browser pass at the end of the rollout, not per page.

### Phase 6 — Hardening and release

Tasks: add ticker + Tool D suites to `tests/tools/run_focused_selection.py` (they are absent
today) and extend the required-subset assertion in `test_workspace_shell.py:506-522`; run static/
design guardrails → focused suites → full suite; real coherent local refresh + manifest generation
check; verify request paths are read/render-only; compare HTML payload + render timing to the
Phase 1 baseline (investigate >10% regressions — "more UI" is not a waiver); execute the §9
browser/accessibility matrix (batched, file-loaded); final branch/worktree integration audit;
**final visual + product sign-off from Victor**; then the standing `dev-vic` → `main` merge
workflow.

Gate: Definition of Done (§11) fully satisfied.

---

## 8. Ticker-page acceptance checklist (Phase 4 gate)

Identity/navigation: truthful ticker/company/currency/jurisdiction/quote/date; missing fields
omitted; jump-to-ticker keyboard-complete, configured tickers only; source survives jump; no false
Candidate Finder `aria-current`; skip link + drawer usable.

Performance: view + horizon controls visible and semantically selected; both charts available —
fixing Share price has not touched the rebased comparison; Compare draws all four series from one
common 100 anchor with percent semantics; Share price draws the stock alone at price levels with
currency semantics; series distinguishable by color AND pattern; accessible table matches units;
visibility toggles never filter the table.

Corporate Finance: one basis strip, zero repeated card dates; one active value per card; exact spot
visible as context during scenarios; expanded tables keep labelled Spot/Scenario; fractional boot,
Reset, and manual return clean; only failing checks appear, labelled at-spot; missing/invalid
metrics carry reasons; both sources render source-correct resilience or source-correct degradation.

Later additions preserved: Currency Attribution (non-USD correct, USD compact); five behaviour
windows; cost/downside + volatility; option safeguards + conditional section; opt-in source-aware
Compare builder; full provenance; accessible chart tables.

Inputs/responsive: one closed parent workspace, four forms intact, validation reopens + echoes; no
page-level horizontal overflow at 1440/1280/1024/768/390/320; touch targets, focus, reduced motion,
forced colors, 200%/400% zoom pass.

## 9. Browser and visual acceptance matrix (Phases 4 and 6 — one batched pass each)

Data states: NEM Our View untouched fractional spot; active lower + higher scenario; after Reset;
NEM Yahoo healthy dual-source resilience; a ticker with degraded Yahoo inputs; a non-USD ticker
with Currency Attribution; a ticker with options; a ticker with confirmed no options; stale/missing/
corrupt artifact states via fixtures; a form validation error with echoed inputs.

Viewports/inputs: 1440, 1280, 1024, 768, 390, 320px; 200% zoom at desktop; keyboard-only; touch
target sizes; reduced motion; forced colors.

Visual questions: company/source/scenario context obvious before the chart; active source/mode/
horizon distinguishable without color alone; one dominant number per card; gold guides attention
rather than decorating; numbers comparable at a glance; dense tables readable; secondary detail
quiet but reachable; degraded states as intentional as the happy path; Currency Attribution
visibly part of Performance; mobile preserves meaning without page scroll; the wide canvas buys
comparison, not stretched prose.

## 10. Non-goals and deferrals

- No new external market/fundamental source; no live API calls from this work.
- No composite ticker-page score; no removed-FCF identifiers (D16); no S&P/Nasdaq series.
- No portfolio-wide source toggle; no historical Yahoo trend analytics.
- No single open-strip "financials date" until a backend contract resolves mixed field-level
  periods truthfully.
- No Revenue/Forward-EBITDA headline promotion without the separate gold-response schema project (§4.4).
- **No removal of the non-spot gold-scenario recompute paths in `/tool-d` and Candidate Finder
  (D15)** — recorded as standing architecture debt for a separate project.
- No sidebar-width or global-default changes before the Phase 5 closing commit.
- No literal Bloomberg clone; no one-shot CSS rewrite; no removal of audit documents.
- No mock-only content: MOCK banner, frozen values, old expiry wording, unsupported KPIs, static
  fake-interactive controls.

## 11. Definition of Done

1. Every phase has its handoff, tests, and before/after evidence under
   `reviews/codex/milestones/platform_redesign/`.
2. Fractional dial boot/movement/return/reset proven by real JavaScript execution (node shim) and
   the Phase 4 Playwright behavioural pass.
3. Corporate Finance headline values and basis dates unambiguous; one strip, no repeats.
4. Share price and Compare units correct everywhere including accessible tables; OI trend honest.
5. Tool D publishes and serves coherent `(ticker, finance_source)` rows for both sources through
   the contract module; no silent fallback, mixing, collapse, or Lab-store contamination possible.
6. The ticker page is the approved reference implementation (Victor's visual sign-off recorded).
7. Shared primitives — not page-local copies — power the rollout; `.button-like` and the
   double-booked `metric-card` are retired after dead-selector audits.
8. Currency Attribution and every listed later addition remain.
9. Accessibility, responsive, empty/degraded, and no-JS states pass.
10. Focused selection includes ticker + Tool D coverage; full suite green after the contract change.
11. A real refresh produces one coherent dual-source generation verified through the manifest.
12. Performance/payload deltas measured against the Phase 1 baseline and explained.
13. Final integration audit recorded; merge workflow executed after Victor's sign-off.
