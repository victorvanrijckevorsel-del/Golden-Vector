# Ticker page redesign — full implementation plan

- **Date:** 2026-08-11 · **Author:** Claude · **Status:** for Codex review, then build on `dev-vic`.
- **Requirements (authoritative, LOCKED):** `reviews/codex/claude_ticker_page_requirements.md`.
  This plan implements that file; where the two disagree, the requirements file wins.
- **Approved mock (v3):** https://claude.ai/code/artifact/1059868b-3d00-42ab-96ff-9a2cfbdd179a
  (source `.playwright-mcp/mock3.html`, built on real NEM data).
- **Grounding:** every file/line reference below was read from the tree at `a18839f` during
  planning (three read-only mapping passes over model, serve, and options/Lab layers).

---

## 1. Goal, scope, non-goals

**Goal.** Rebuild `/ticker/<T>` into the company's full profile — performance chart, corporate
finance moved by a gold dial, market behaviour (Tool A + Tool C + Lab), options with history and
tools, an opt-in score builder, and the four maintenance forms — ordered and disclosed exactly as
§2/§4 of the requirements file.

**Scope.** The ticker page only, plus:
- the backend artifacts it needs (gold response pack, universe percentiles, published options
  history, contract greeks);
- the six known data bugs (requirements §6), because they corrupt numbers this page shows;
- other pages touched **only** where shared data changes reach them (listed in §9 below).

**Non-goals.** Everything in requirements §7 (S&P/Nasdaq lines, peer-percentile bars beside
financials, ticker-to-ticker navigation, native-currency display, chart event markers, portfolio
block). No composite-score changes on any other page.

---

## 2. Current state (what we build on)

### 2.1 The page today
`render_detail_page` (`golden_vector/serve/detail_page.py:44`) composes ~20 panels from
`detail_panels.py` (2,478 lines): window switcher → gold-sensitivity block (metric grids,
explanations, structural-windows table, 6 SVG chart panels) → corporate-finance snapshot table →
option-trading **link card** (full options panel only under `?lens=option-trading`,
`detail_page.py:178-193`) → four manual forms. Sections the requirements demand that are absent
today: performance chart with price view and horizons, gold dial, Tool C block, Tool D resilience
block, Lab block, inline options with history, score builder.

### 2.2 Assets we reuse (no new plumbing needed)
| Need | Already exists |
|---|---|
| "?" explainer registry | `COLUMN_HELP`/`VALUE_HELP` (`serve/column_help.py:330`/`:180`) + `_METRIC_FORMULAS` (`serve/metric_formula.py:47`), rendered by `help_icon`/`help_term`/`help_th`/`help_value`, one shared popover (`static/help-popover.js`). Site-wide already. |
| Disclosure / section scaffold | `disclosure()`, `section_nav()`, `section_heading()`, `empty_state()` (`serve/ui/components.py`), `notice()`/`status_strip()` (`serve/ui/status.py`), `table_region()` (`serve/ui/tables.py`) |
| Chart primitives | Server-side SVG in `serve/charts.py` (scatter `:15`, dual bar `:62`, grouped beta bar `:253`, percentile rug `:153`, rebased multiline overlay `:363`) each with an accessible data-table twin (`_chart_data_disclosure`, `charts.py:133`); hover JS reads JSON from `data-*` attributes (`overlay-crosshair.js`, `rug-tooltip.js`) |
| Exact "financials as a line in gold price" | Tool D already builds it from two Tool B evaluations: `_ebitda_line_from_tool_b` (`model/tool_d.py:618-633`), inverted for threshold golds (`:636`, `:647`, `:658`) |
| Percentile ranking | `oriented_percentile` (`features/percentile_ranks.py:8-17`), already used by Tool C/D, Candidate Finder, options features |
| Lab per-ticker history | `dial_cells` (ticker × bucket × horizon, beat rates + Wilson CIs + median/q10/q90 alpha; 1,188 rows live) and `dial_episodes` (ticker × horizon × benchmark × week, alpha/beat/bucket/anchor flags; 415,386 rows live), loaded by `serve/lab_curve_data.py::load_ticker_curve` (`:472-619`) for the existing `/lab/dial/<T>` page |
| Most-liquid contract selection | Build-time: `hedge/option_horizon_selection.py` (expiry ranking `:106-158`) + `hedge/candidate_puts.py` (delta-targeted strike), stamped onto `option_trading_overview` / `option_candidate_slots`; serve reads stamped fields only (`serve/option_trading_data.py:141-175`) |
| Artifact publish pattern | `persist_*` (run-stamped + latest alias + `record_artifact`) e.g. `ingestion/persist.py:272`; manifest registration `app/model_state.py:118` (`_artifact_map` `:519`, `REQUIRED_ARTIFACTS` `:48`); options set published atomically (`ingestion/persist_option_artifacts.py:101-149`) |
| Request-path caching | Stat-keyed memo caches in `serve/workspace_state.py:79-189` (`_loader_inputs_signature` over artifact paths; degraded loads never cached) |

### 2.3 Facts that shaped decisions below
- Tool B computes financials **algebraically at one gold price** (`screening/layer1.py:13`,
  `layer2.py:11`); there is no historical financials-vs-gold regression anywhere. Revenue/EBITDA/
  NI/FCF are linear in the gold assumption, which is exactly why Tool D's 2-point line is exact.
- Spot gold is derived, not stored: `latest_gold_price_from_history` (`model/tool_d.py:175-204`);
  Tool B carries it as provenance columns `spot_gold_usd`/`spot_gold_date`.
- `options_features` (`data/intermediate/options_features/{T}.parquet`, written by
  `ingestion/options_phase.py::_append_feature_rows` `:476-499`) is **not** manifest-registered,
  dedupes on run_id only, and **discards the put/call OI sums** (`features/options.py:269-285`
  keeps only ratios). Verified live: 2026-08-10 has 3 same-day rows for NEM, one a partial capture
  (354,079 total OI vs the true 534,406).
- The IV/RV bug's root cause is deeper than the requirements file records: `_realized_vol`
  (`features/options.py:221-244`) uses `return_basis_usd` **as-is** (line 224-225), but that
  column is a **USD price level** (`normalize/prices_usd.py:115-118`), not a return series — the
  stored "realised vol" is the stdev of raw dollar prices × √252. Fix and history recompute in §7.
- Only **delta** exists per contract (`features/black_scholes.py`); gamma/vega/theta do not.
- Lab bucket edges and horizons are hardcoded (`DEFAULT_BUCKETS` `lab/conditional_dial.py:41-47`,
  `DIAL_HORIZONS_WEEKS = [4, 8, 13, 26]` `:82`).
- Price histories: gold `data/raw/gold/GC-F.parquet` (daily, 2000→today), USD equities
  `data/intermediate/usd_equities/{T}.parquet`, GDX/GDXJ `data/intermediate/benchmarks/`.
- Confirmed bug sites: Tool D `fcf_yield` read from the spot row unconditionally
  (`model/tool_d.py:387`, the only assignment); Tool C tag thresholds hardcoded
  (`model/tool_c.py:292,294,300,302` down / `:324,326,332,334` up); put/call status dead branches
  (`hedge/option_trading.py:539-547` — three branches all return `"none"`).

---

## 3. Architecture decisions

### D1 — Gold dial: exact response lines, not a grid, not live recompute
A live Tool B run is 3.2–6.5 s — unusable. A dense value grid either snaps the slider (rejected in
mock v1: landed on $4,400 instead of spot $4,422) or balloons the payload.

> **Deliberate refinement of the requirements wording.** The requirements file says "precomputed
> grid"; this plan precomputes exact **lines** instead. Same intent (nothing computes in the
> request path), strictly better execution: exact at every dollar including spot, ~50× smaller
> payload, and it is what the approved mock v3 actually did. Codex: treat "grid" as satisfied by
> this.

Mechanism:

- **Backend** (new `golden_vector/model/ticker_page.py`): evaluate `compute_tool_b_in_memory`
  (`screening/pipeline.py:200`) at **two gold prices** (spot and spot×0.90 — the same pair Tool D
  uses) and derive slope+intercept per gold-dependent metric per ticker with the **extracted**
  shared helper (Tool D's `_ebitda_line_from_tool_b` moves to `model/gold_lines.py`; Tool D
  imports it from there — one implementation, both consumers).
- **Linearity guard:** a third full evaluation at the far grid edge ($2,000). Assert
  |line(2000) − actual| ≤ tolerance per metric per ticker; violation **fails the stage loud**
  (it would mean Tool B gained a kink and the pack must move to dense sampling — designed as the
  fallback but not built unless this guard ever fires). Max residual recorded in the artifact.
- **Pack contents** per ticker (and per finance source where `_our_view`/`_official` pairs exist):
  lines for `forward_revenue_musd`, `forward_ebitda_musd`, `forward_net_income_musd`,
  `forward_eps`, `sustainable_fcf_musd`; constants `market_cap_musd`, `enterprise_value_musd`,
  `net_debt_musd`, `interest_expense_musd`, `share_price_usd`, `aisc_usd_per_oz`,
  `cash_cost_usd_per_oz`, `production_oz`; provenance `spot_gold_usd`, `spot_gold_date`,
  `gold_price_basis`, `source_run_id`.
- **Client** (`static/gold-dial.js`, the ONE place these formulas exist in JS): evaluates lines at
  the dial's g; assembles ratios from parts exactly as the backend does — margin/oz = g − AISC,
  margin % = (g − AISC)/g, FCF yield = fcf(g)/mcap, EV/EBITDA = EV/ebitda(g) **only when
  ebitda(g) > 0** (else blank), P/E = price/eps(g) **only when eps(g) > 0**, leverage =
  net_debt/ebitda(g) when positive. The worker implementing this must read `layer1.py`/`layer2.py`
  first and mirror the guard semantics exactly.
- **Both values shown:** the spot column is server-rendered from the real Tool B row (never JS);
  the scenario column exists only in JS and only once the dial leaves spot (clean by default,
  Q43). No-JS/print degrades to today's spot-only view.
- **Drift lock:** parity is enforced twice — a pytest that runs the Python line evaluation against
  a real `compute_tool_b_in_memory` at probe prices on fixtures, and the single end-of-project
  Playwright gate asserting the rendered scenario numbers equal server-computed references
  (§10.4). The client-side-what-if boundary gets a short section in
  `ARCHITECTURE_FOUNDATIONS.md`: *interactive JS may only combine backend-resolved inputs; every
  formula lives in exactly one JS module and is pinned by a parity gate.*

### D2 — Score builder: backend percentiles, client weighted sum
- **Backend** (same `model/ticker_page.py`): a metric catalog (config, §5) of ~20 metrics in the
  two locked categories (Trading behaviour: Tool A betas/r², Tool C capture/hit rates, realised
  vol…; Corporate finance: margin, FCF yield, EV/EBITDA, P/E, leverage, AISC, reserve life…).
  For each metric compute **both orientations** with the existing `oriented_percentile`
  (`features/percentile_ranks.py:8`) — `pct_high_good` and `pct_low_good` as separate columns,
  because with ties `100 − p` is not exact and the user can flip direction (Q: each metric
  user-directed). Store raw value + both percentiles per ticker per metric.
- **Client** (`static/score-builder.js`): 100-point budget that rebalances as allocated (the
  ×1/×2/×3 bars are gone), per-metric direction toggle, metrics missing for the company disabled
  and not counted (Q24), weighted sum over the embedded universe rows → score, rank, contribution
  bars, clickable ranked list of all miners (link to each `/ticker/<T>`), and the stability
  warning: re-run the sum with each active weight shifted ±10 points (rebalanced); if any shift
  moves the subject's rank by more than `rank_stability_alert_positions` (config), show it.
- Nothing scored until the user allocates (opt-in, Q26 no presets); page-only, influences no other
  surface (Q25). Parity pinned like D1.

### D3 — Options history becomes a published, gated artifact
- **Stop discarding the split:** `compute_options_features` gains persisted columns
  `put_oi_total`, `call_oi_total`, `put_oi_otm`, `call_oi_otm`, `put_volume`, `call_volume`
  (sums already computed inside `_put_call_oi_ratio`, `features/options.py:269-285`).
- **New artifact `option_history_daily`** added to `OPTION_ARTIFACT_NAMES`
  (`contracts/option_artifacts.py:16-27`) so it inherits run-stamping, the atomic all-or-nothing
  options publish, and manifest registration. Built each refresh as a **cleaned projection** of
  the per-ticker `options_features` intermediates (which stay as the raw audit trail):
  1. per (ticker, day) keep one row — the complete capture with the highest total OI (latest run
     as tie-break);
  2. exclude partial captures: a same-day row whose total OI < `partial_capture_min_ratio`
     (config, default 0.70) of that day's max is dropped; a single-row day is compared against the
     trailing median contract/expiry count;
  3. field-level validity gates (degrade per item, never drop the row): IV within
     `[iv_min, iv_max]` (defaults 0.01–3.0 — kills the live 0.0 and 111.87 outliers), skew and
     implied-move bounds; gated values become NA with a count recorded in artifact metadata;
  4. `iv_rv_ratio` recomputed correctly for **all** history rows (the RV fix, §7.1 — realised vol
     is recomputable exactly from stored daily price history for any as-of date).
- **Backfill** of the put/call split: walk surviving `data/runs/*/snapshots/options/{T}.parquet`
  raw chains and recompute sums where they exist; where runs were pruned, the split series simply
  starts later than the ratio/total series and the chart labels the start honestly. No guessing.
- **Serve:** trend charts read only this artifact. Put line + call line + total line (Q: "show the
  two lines and the sum"), ratio trend with the meaning sentence ("0.66 → more calls than puts —
  positioning leans bullish"), whole-chain vs OTM side by side (the disagreement is the insight),
  ATM IV vs its own history, implied move, volume.

### D4 — Options section: inline, reusing the build-time selection; absent when no options
- The `?lens=option-trading` split dies on this page: the options section always renders inline
  when the ticker has options (`options_available` from the options manifest), and the whole
  section — including its nav anchor — is **absent** when it doesn't (Q38: no empty tables, no
  proxy suggestion, no fallback message). `lens` URLs keep working (ignored → full page renders;
  in-repo links re-pointed at `#options`, sweep in §9). The separate `/option-trading` overview
  page is untouched.
- **Contracts block:** driven entirely by existing stamped artifacts — `option_candidate_slots`
  rows per (side, horizon, target delta) with `option_contract_metrics` for depth. Expiry
  selector = the configured horizons; all horizons are **pre-rendered server-side and toggled by
  JS** (3–4 horizons × 2 sides — cheap; no new routes, no client selection logic). ATM +
  directional per side: `hedge_readiness.yaml` target-delta list gains 0.50 alongside the existing
  0.25 if absent, so both rows come from the normal build. Everything else behind the existing
  chain disclosure.
- **Sizing tool** ("Work out a position", closed by default): budget → contracts (floor of
  budget / contract ask×100, mirroring the existing server calculator's convention) → **value at
  expiry** (intrinsic only — Q34 "simple and honest") across a **share-price slider** (Q40; never
  gold-derived — the "very bogus" veto) plus a break-even/outcome ladder. One `option-sizing.js`,
  parity-pinned; the server still renders the default scenario so no-JS shows a complete example.
- **Greeks** (closed): extend `features/black_scholes.py` with gamma/vega/theta (standard closed
  forms; inputs — r from the options manifest `risk_free_rate`, q=0 documented), new columns on
  `option_contract_metrics`, unit tests against known reference values. Displayed in the
  chain disclosure.
- **Disposition of every existing options sub-panel** (nothing dropped silently):
  | Today (`detail_panels.py`) | On the new page |
  |---|---|
  | freshness box (`:441`) + context warnings (`:467`) | kept, top of section (data-quality statuses stay) |
  | option signal card (`:532`) | absorbed into the open market-context block (ratios/IV/implied move with the new history charts) |
  | candidate matrix (`:809`) | becomes the contracts block with the expiry selector |
  | sizing calculator (`:1077`) | rebuilt as the share-price-slider tool ("Work out a position", closed) |
  | **ETF proxy fallback (`:647`)** | **removed from the ticker page** (not in the locked content list; Q38 bans proxy suggestions here) — stays on `/option-trading` |
  | skew overlay (`:604`) + signal charts + OI-by-strike | "Where the crowd is positioned" (closed) |
  | context table (`:732`) + liquidity summary (`:782`) | greeks-and-full-chain disclosure (closed) |
  | method/glossary details | replaced by "?" explainer keys (D9) |

### D5 — Performance chart: pre-rendered variants, zero client math
- **Model:** `build_performance_series(...)` in `model/ticker_page.py` — stock/gold/GDX/GDXJ, three
  horizons (1Y daily; 3Y/5Y weekly), two views: rebased-to-100 ("Compare") and raw dollars
  ("Share price", stock only). Sources: `load_latest_foundation_snapshot`
  (`app/latest_data.py:91`) + benchmark histories, resolved inside the memoized detail loader —
  same pattern as today's `_build_rebased_overlay_by_window` (`serve/workspace_state.py:408`).
- **Serve:** all 2×3 variants pre-rendered as SVG via the existing overlay builder
  (`charts.py:363`, extended with a raw-dollar axis mode); JS only toggles visibility; the
  existing crosshair attaches to whichever is visible. Legend toggles per series (JS
  visibility only). Each variant keeps its accessible data table.

### D6 — Market behaviour: reorganise Tool A, add Tool C, embed the Lab
- **Open:** up/down beta bars (`detail_panels.py:1951`) + percentile rugs (`:2029`) with their
  window switcher. **"Full research detail" (closed):** metric grids, explanation cards,
  structural-windows table, scatter, volatility diagnostics, exploratory ladder — nothing deleted,
  everything demoted (the v1 mistake, not repeated).
- **Tool C block — "How often it beat gold and the ETFs" (closed):** rel strength/weakness vs
  gold/GDX/GDXJ with observation counts, 10% hit rates, tail averages — from `latest_tool_c`
  already in `WorkspaceState`. No Tool C scores/ranks (verdict rule).
- **Lab — "How it behaved in past gold moves" (closed):** reuse `load_ticker_curve`
  (`serve/lab_curve_data.py:472`) and the existing `/lab/dial/<T>` chart builders — extracted into
  a shared `serve/lab_curve_charts.py` consumed by both pages (move, not copy). Three charts as
  locked: beat-rate by scenario with Wilson bars (`dial_cells`), spread-of-outcomes ticks and
  when-did-it-happen timeline (`dial_episodes`, `is_nonoverlap_anchor` marked, scatter trimmed to
  2016+ per Q44). Controls: look-ahead 4/8/13/26 (default **8** from config — the measured
  choice: 17.8 independent obs and CI 0.317 at 8w vs 12.5 and 0.373 at 13w), benchmark GDX/GDXJ,
  bucket down>15% … up>15%. Control changes are **server round-trips via query params**
  (`lab_h`/`lab_b`/`lab_s`) — 40 combinations are too many to pre-render, the memoized loader
  makes reloads ~50 ms warm, and the window switcher already set this interaction precedent.
  Survivor-only caveat rendered from `dial_meta.json`'s `retired_tickers_excluded`; thin buckets
  render empty with a reason, never guessed.

### D7 — Corporate finance: headline cards open, four groups closed, everything dial-aware
- **Open:** as-of/basis line, share price, market cap, margin $/oz, margin %, FCF yield,
  EV/EBITDA, forward P/E — plus the failing-checks notice (only when a check fails, Q22).
- **Closed groups (§4):** "Earnings and cash at this gold price" (revenue, EBITDA, NI, EPS, FCF);
  "Valuation" (EV, trailing multiples, both-source rows); "Balance sheet, cost and scale"
  (net debt, interest, leverage, AISC, cash cost, ounces, reserve life); "Resilience — at what
  gold price does this break?" (Tool D: `breaks_even_at_gold_usd`, `fcf_breakeven_gold_usd`,
  `interest_cover_gold_usd`, `debt_stress_gold_usd`, survival ladder, fragility — no quality
  rank); "Data quality and sources" (provenance, FX staleness, normalization status,
  verification).
- **Failing checks as sentences:** Tool B emits a display-ready `screening_fail_sentences` column
  in the model layer (one sentence builder, built from `layer1_fail_reasons` + the verdict P/E
  thresholds in `screening_params.yaml`, naming measured value and the user's threshold — "FCF
  yield 12.6% vs your 15% floor"). Serve renders strings verbatim. No verdict labels, no
  confidence scores anywhere on the page (they stay on other pages, Q20); untrusted numbers are
  hidden with a short reason, not shown (Q21).
- Every gold-dependent cell carries a `data-metric` key for `gold-dial.js`; static cells don't.
  P/E and EV/EBITDA "?" text explains the inversion (they **rise** as gold falls).

### D8 — Serve assembly: a section package, spine first
- New package `golden_vector/serve/ticker_page/` — `assembly.py` (order + nav + state plumbing)
  and one module per section (`chart.py`, `corporate.py`, `behaviour.py`, `options_section.py`,
  `score.py`, `inputs.py`). Existing renderers are **moved** out of `detail_panels.py` as each
  section adopts them; `detail_page.py` becomes a thin shim calling the package. The repo-wide
  serve token sweep (`tests/test_workspace_app.py:2984`) covers the new package automatically
  (rglob); its two sanctioned exceptions follow the moved code; per-module companion scans are
  added for each new module (clone the Tool-D pattern, `:2354`).
- `ToolADetailState` gains fields: `performance_chart_by_horizon`, `gold_response_pack_row`,
  `score_percentiles` (+ universe frame), `option_history`, `lab_curve` (per selected controls),
  `tool_c_row`, `tool_d_row`. All loaded in `_load_tool_a_detail_uncached` through model-layer
  functions; **every new artifact path joins `_loader_inputs_signature`**
  (`serve/workspace_state.py:121-136`) — including the gold/GDX/GDXJ history paths the overlay
  currently only tracks indirectly — so the stat cache invalidates correctly. Lab control params
  join the detail-cache key the same way the ticker does (`:306`).
- Forms are untouched behaviourally (raw_overrides flow intact) and live under "Your inputs and
  notes" (closed); `return_to` round-trips the new query params. The dial is client-state only
  (resets to spot on reload — deliberate; documented in its "?").
- **One formatting implementation:** every number renders through the existing
  `format_helpers.py` helpers (`_fmt_number`, `_metric_card`, …); section modules never carry
  their own number-to-string logic. The dial's JS formats scenario values with one shared
  formatter in `gold-dial.js` whose output is pinned against the Python formatting in the
  parity gate.

### D9 — Explainers: extend the existing registry, generously
New `COLUMN_HELP` keys (~30) written during each section's lane, covering at minimum: every
headline card, margin vs AISC distinction, FCF yield basis, EV/EBITDA + P/E inversion under the
dial, net debt/leverage, reserve life, all four break-even golds and the survival ladder, up vs
down beta and why they differ, r² bands, percentile rugs, each Lab chart + Wilson interval +
survivor-only caveat + independent-observations note, both put/call ratios and their
disagreement, IV vs realised, implied move, OI vs volume, contract liquidity tiers, greeks,
sizing assumptions (intrinsic-at-expiry), score-builder percentiles/budget/stability warning, and
every dial-moved number's basis. Direction-of-good stated wherever it isn't obvious. Content
lives only in the registry; `metric_formula` "This stock" values stay spot-labelled.

---

## 4. New artifacts and pipeline wiring

| Artifact | Producer | Where | Contents (compressed) |
|---|---|---|---|
| `ticker_page_gold_response` | new stage `ticker-page` → `model/ticker_page.py::build_gold_response_pack` | `data/output/ticker_page/` via a new `persist_ticker_page_artifacts` (clone of `persist_tool_c.py` pattern) | per ticker (× finance source): metric lines (slope, intercept), constants, spot provenance, linearity residual |
| `ticker_page_percentiles` | same stage → `build_score_percentiles` | same | per ticker × metric: raw value, `pct_high_good`, `pct_low_good`, category, availability; source run ids of all four tools |
| `option_history_daily` | option-artifacts stage → new builder in `hedge/option_artifact_frames.py` | `data/output/options/` via the existing atomic options publish | per ticker × day: put/call/total OI (+OTM), put/call/total volume, both ratios, ATM IV, skew, implied move, realised vol, corrected `iv_rv_ratio`, gate flags |
| `option_contract_metrics` (extended) | existing | existing | + `gamma`, `vega`, `theta` columns |

**Stage wiring:** one new stage `ticker-page` inserted in `_run_refresh_unlocked` after tool-d,
before option-artifacts (`cli.py:3402+`): `record_step("ticker-page", ...)`, `total_steps` bump
(`cli.py:3418`), standalone subcommand for reruns, per-step seconds+rows self-reported (clone the
Tool A `_record_step_timing` pattern, `model/pipeline.py:721`). Cost: three in-memory Tool B
evaluations ≈ 10–20 s — measured and recorded, per the measure-the-real-run rule.
**Manifest:** both ticker_page artifacts join `_artifact_map()` (`model_state.py:519`),
`REQUIRED_ARTIFACTS` (`:48`), and get `ProjectPaths` latest-alias properties;
`option_history_daily` rides the existing options publish block. A refresh that fails the stage
leaves the last good state intact (existing all-or-nothing behaviour).

---

## 5. Config additions (every threshold once)

| File | Keys (defaults) |
|---|---|
| **new `config/ticker_page.yaml`** → `TickerPageConfig` in `contracts/config_models.py`, added to `EXPECTED_CONFIG_FILES` (`app/config.py:17-30`) and `AppConfig` | `dial: {min_gold_usd: 2000, max_gold_usd: 6000, step_usd: 1, linearity_probe_gold_usd: 2000, linearity_tolerance_pct: 0.1}`; `chart: {horizons: [1Y, 3Y, 5Y], weekly_resolution_from: 3Y}`; `lab: {default_horizon_weeks: 8, scatter_from_year: 2016}`; `score_builder: {budget_points: 100, rank_stability_shift_points: 10, rank_stability_alert_positions: 3, metrics: [{key, label, category, source, column, default_high_good, format}, …]}` |
| **new `config/lab_dial.yaml`** → `LabDialConfig`, loaded uncached by `lab/conditional_dial.py` (same deliberate pattern as `lab_gold_profile.yaml`) | `horizons_weeks: [4, 8, 13, 26]`; `buckets:` the five edges currently in `DEFAULT_BUCKETS` (`conditional_dial.py:41-47`). Build defaults unchanged — this moves literals, not behaviour; satisfies hard rule 2 (horizons only via config) |
| `config/tool_c.yaml` → `ToolCConfig` (`config_models.py:579`) | `tags: {low_confidence_below: 0.5, steep_beta_at_least: 1.5, persistent_relative_at_least: 0.6, frequent_tail_at_least: 0.25}` — replaces the eight inline literals (bug §7.5) |
| `config/hedge_readiness.yaml` | new `history_quality:` block — `partial_capture_min_ratio: 0.70`, `iv_valid_range: [0.01, 3.0]`, skew/implied-move bounds; target-delta list gains `0.50` if absent (ATM row) |

---

## 6. Serve layer — final page composition

Order per requirements §2; open/closed per §4. All new serve Python formats only (guardrail-scanned);
all interactive math lives in the three parity-pinned JS modules (`gold-dial.js`,
`score-builder.js`, `option-sizing.js`) plus visibility-only toggles.

1. Header + section nav (options anchor conditional).
2. **Performance chart** (open) — D5.
3. **Corporate finance** (headline open; 4 groups + data-quality closed) — D7, dial in the
   section toolbar.
4. **Market behaviour** (bars + rugs open; research detail, Tool C, Lab closed) — D6.
5. **Options** (context + contracts open; crowd/OI-by-strike, sizing, greeks+chain closed;
   whole section absent without options) — D3/D4.
6. **Compare on your own terms** (controls open, opt-in output) — D2.
7. **Your inputs and notes** (closed) — the four existing forms.

---

## 7. The six data-bug fixes (all in scope, each with its test)

1. **IV/RV 100x** — fix `_realized_vol` (`features/options.py:224-227`) to `pct_change()` the
   `return_basis_usd` **price level** before stdev (matching the fallback branch's semantics);
   recompute `iv_rv_ratio` for all history rows in `option_history_daily` (realised vol is exactly
   recomputable from stored daily prices). Test: fixture where price-level stdev and return stdev
   differ wildly; assert ratio ≈ IV/true-RV (~0.45 for the NEM case, not 0.0045).
2. **IV/skew outliers** — field-level gates in the history builder (§D3); test: 0.0 and 111.87 IV
   rows gated NA, healthy 0.49 row untouched (control row proves the gate doesn't over-fire).
3. **History publish** — `option_history_daily` with same-day dedupe + partial-capture exclusion
   (§D3); test: three same-day rows (354,079 / 534,406 / 534,406 shaped) → one survivor with max
   OI; a lone genuine row survives (control).
4. **Tool D fcf_yield** — replace the single `fcf_yield` (spot-copied, `tool_d.py:387`) with
   `fcf_yield_at_g` (stressed row) + `fcf_yield_at_spot`, following the section's existing
   `_at_g`/`_at_spot` convention; consumer sweep before the schema change (§9). Test: stressed
   run's `fcf_yield_at_g` ≠ spot value on a fixture where they must differ.
5. **Tool C thresholds → config** (§5); behaviour-preserving; test pins tags at the boundary
   values from config, and a changed config moves the tag.
6. **Dead branches** — collapse `_candidate_side_status` (`hedge/option_trading.py:539-547`) to
   the two live branches + one `"none"` return; render-level behaviour unchanged (test asserts
   identical statuses on the existing fixtures).

---

## 8. What leaves the page (and where it still lives)

Removed here, kept elsewhere (display decision only, Q20): Gold Sensitivity Score, tool_a_rank,
confidence score/label, fundamental check score/rank, screening verdict label, Tool C
downside/upside scores+ranks, Tool D quality score/rank. Statuses stay (eligibility/data-quality:
`resilience_data_status`, `score_eligible`, put/call status, optionability tier, FX staleness).
Render tests assert the absence of each removed string on the new page **and** its continued
presence on its home overview page.

---

## 9. Cross-page effects (flagged, deliberate)

- **`iv_rv_ratio` correction** changes `iv_rv_ratio_signal` on the Option Trading overview and
  anywhere Candidate Finder consumes it — values become *correct*; expect visible diffs. Called
  out to Victor at review.
- **Tool D schema** (`fcf_yield` → `_at_g`/`_at_spot`): sweep consumers (`serve/overview_tool_d.py`,
  portfolio, finder, tests) and update in the same commit.
- **`lens=option-trading` links**: sweep in-repo links (finder, overview pages) → `#options`
  anchor; param itself stays accepted (no broken bookmarks).
- **Lab serve default horizon** becomes the config default (8) on both `/lab/dial/<T>` and the
  ticker page — one threshold, one home; build-time classification defaults untouched. Flagged
  for Victor/Codex veto.
- **Target-delta 0.50 addition** enlarges candidate-slot artifacts (more rows, same schema).
- The duplicate percentile implementation (`benchmark_comparison.py:106` vs
  `features/percentile_ranks.py:8`) is **noted, not merged** — different tie semantics would
  silently move the rug markers; deferred with a comment-free tracking entry in §13 deferred list.

---

## 10. Test and verification strategy

1. **Model unit tests** — linearity guard (synthetic kink must fail loud); pack values equal a
   real in-memory Tool B at probe prices; percentile orientation incl. deliberate ties and NA;
   history gates per §7 (each with a healthy control row); greeks vs published reference values;
   sentence builder wording at render level.
2. **Serve render tests** — section order and §4 open/closed defaults (assert `<details open>`
   presence/absence); options section + nav anchor absent for an optionless fixture ticker while
   the control ticker keeps both; verdict-string absence (§8); failing-check sentences verbatim;
   dial spot column server-rendered with scenario cells carrying `data-metric`; Lab controls
   round-trip in `return_to`; forms regression (raw_overrides).
3. **Guardrails** — repo-wide serve token sweep auto-covers `serve/ticker_page/`; per-module
   companion scans added; `serve/ui` purity untouched; new JS modules listed in the shell test.
4. **One Playwright gate** (end of M4, batched script from `.playwright-mcp/`, server launched via
   `serve_with_socket_timeout.py`): dial parity at canonical prices vs server-computed references,
   score-builder parity on a fixed weight set, sizing parity, disclosure toggles, options absence,
   640px/320px reflow screenshots. Evidence written to files; one script, one run.
5. **Perf** — real-run measurements before/after: warm `/ticker/NEM` (budget: ≤ 100 ms warm,
   currently ~45 ms), page payload (budget: ≤ 300 KB), `ticker-page` stage seconds in the
   manifest. `run_focused_selection.py` gains the new test files; full suite only at the
   ship gate.

---

## 11. Build sequence (each milestone commits green on `dev-vic`)

| Milestone | Contents | Depends on |
|---|---|---|
| **M0 — Bug fixes + config homes** | §7.1 RV fix, §7.4 Tool D pair (+consumer sweep), §7.5 Tool C config, §7.6 dead branches; persist put/call OI+volume splits forward; `lab_dial.yaml` + `ticker_page.yaml` skeletons | — |
| **M1 — Backend artifacts** (parallel worker lanes) | a: `gold_lines.py` extraction + response pack + stage wiring; b: percentiles + metric catalog; c: `option_history_daily` + gates + backfill; d: greeks columns | M0 |
| **M2 — Serve spine** | `serve/ticker_page/` package, state/loader/signature extensions, section scaffold with existing content re-homed (page reads the same, structure new), nav, guardrail extensions | M1a minimum |
| **M3 — Sections** (sequential commits: a chart, b corporate+dial, c behaviour+Lab, d options, e score builder, f explainer sweep) | the visible rebuild | M2 + matching M1 lane |
| **M4 — Hardening + ship** | focused selection green, a11y pass, the one Playwright gate, perf measurements, `ARCHITECTURE_FOUNDATIONS.md` client-what-if note, requirements walk-through (§12), memory update → Victor review → Codex review → merge workflow | M3 |

**Delegation (token discipline):** Fable organises and reviews every diff; opus workers take the
specified lanes (M1a–d, M3a–e) with written specs quoting this plan; sonnet handles mechanical
sweeps (lens links, fcf_yield consumers, explainer key scaffolding). Worker briefs carry the
standing bans: **no git state commands of any kind**, no dependency installs, no paid API calls.
I commit each finished lane immediately as a checkpoint. Browser use only at the M4 gate.

---

## 12. Acceptance checklist (requirements → plan)

| Requirement | Where satisfied |
|---|---|
| §2 order chart → corporate → behaviour → options → compare → inputs | §6 |
| §3 no composite scores; statuses stay; failing checks as sentences; hide untrusted | §8, D7 |
| §3 dial 2000–6000, spot default, both values, clean-by-default, precomputed, inversion explained | D1, §5, D9 |
| §3 chart two views, three horizons, four series, legend toggles; beta bars + rugs kept | D5, D6 |
| §3 Lab three charts, controls, 8w default (measured), 2016+ scatter, survivor caveat, empty-with-reason | D6, §5 |
| §3 options always-visible context, self-explanatory ratios (two lines + total, both ratios), liquid contracts per expiry + selector, share-price-slider sizing (value at expiry), greeks behind disclosure, absent when none | D3, D4 |
| §3 score builder: opt-in, no presets, two categories, 100-point budget, direction toggles, disabled missing metrics, contribution bars, ranked list, stability warning, percentile mechanism, page-only | D2 |
| §4 open/closed inventory | §6, tested in §10.2 |
| §5 centralisation, backend-computes, nothing-in-request-path, thresholds-once, basis labels, degraded-excluded, registry-driven "?" | D1–D9, §4–§5, §10.3 |
| §6 six data bugs | §7 |
| §7 deferred stays deferred | §1 non-goals; plus (new) percentile-implementation merge, dense-grid fallback mode, richer put/call statuses |

---

## 13. Risks

- **Linearity assumption** — guarded at build time with a loud failure; dense-grid fallback is
  designed (§D1) but unbuilt until needed.
- **JS/backend drift** — the standing risk of the what-if boundary; contained by single-module
  formulas + pytest parity + the Playwright gate.
- **Backfill depth** — put/call split history limited by pruned runs; charts label series starts.
- **Schema ripple** (Tool D pair, delta 0.50, corrected iv_rv) — consumer sweeps first, one
  commit per change, cross-page diffs flagged to Victor.
- **Payload growth** — measured against the 300 KB budget in M4; Lab pre-render avoided by
  round-tripping.
- **detail_panels.py unpicking** — mitigated by the spine-first M2 (the merge-spine lesson):
  section lanes never edit the same file.
