# Ticker page redesign — implementation plan (v2, post-review)

- **Date:** 2026-08-11 · **Author:** Claude · **Status:** v2 — revised for
  `codex_review_claude_ticker_page_plan.md` (verdict CHANGES REQUIRED); Victor resolved the four
  gating product decisions on 2026-08-11 (see §1). v1 is preserved in git at `bd67f96`.
- **Requirements (authoritative):** `reviews/codex/claude_ticker_page_requirements.md`
  **including its 2026-08-11 addendum**, which records the resolved decisions. Where plan and
  requirements disagree, the requirements file wins.
- **Approved mock (v3):** https://claude.ai/code/artifact/1059868b-3d00-42ab-96ff-9a2cfbdd179a
- **M0 status:** SHIPPED (commits `ce2583a`, `a6e8bb1`, `8b9db26`, `3f86c3d`) — isolated
  correctness fixes, separately testable, per the review's decision gate.

---

## 1. Resolved decisions (closes review B1)

The review correctly held that a plan cannot approve its own exceptions to locked requirements.
Victor resolved each deviation explicitly on 2026-08-11; the requirements addendum records them.

| # | Locked text | Resolution (Victor, 2026-08-11) |
|---|---|---|
| D-1 | "Precomputed grid" + "backend computes, serve renders" vs the approved mock's in-browser line math | **Instant in browser.** Backend computes all inputs (exact gold-response lines, percentiles); a narrow, documented client-side layer combines them. The requirements text and the approved mock contradicted each other; Victor chose the mock's behaviour. Exception scope in §3.1. |
| D-2 | Same, for the score builder and sizing tool | **Instant in browser**, same exception, same tests. |
| D-3 | "Expiry selector" wording | **"Target window" + real dates.** Keep horizon-bucket selection; every contract row shows its actual expiry date + DTE; put and call rows may show different expiries, plainly labelled. |
| D-4 | Failing-check sentences under a moving dial | **Fixed, labelled "at spot gold".** Scenario-aware sentences are deferred, not implied. |
| D-5 | Lab 8-week default scope | **Ticker page only.** `/lab` pages keep today's 13w default. No shared-Lab behaviour changes in this project (review H4). |
| D-6 | Dial placement | Not a decision — v1 plan drift. Restored to the **global control bar** per requirements §3 and the approved mock. |

## 2. Review disposition

| Finding | Disposition |
|---|---|
| B1 locked-requirement deviations | **Accepted process-wise**; decisions resolved above; requirements amended; exception defined narrowly (§3.1) with real-JS gates |
| B2 artifact contract incomplete | **Accepted** — exact contract table §5, implementation inventory §5.4 |
| B3 second option-history authority, shrink/look-ahead | **Accepted, redesigned** — extend the canonical history; new artifact carries only chain-level fields with no existing authority (§6) |
| B4 score eligibility undefined, duplicate engine | **Accepted** — reuse Finder eligibility/ranking primitive; exact catalog §7 |
| B5 lens route breaks GDX/GDXJ | **Accepted** — benchmark ETFs keep the lens route; corporate links only; route tests §11 |
| B6 availability + selector semantics | **Accepted** — state matrix §8; D-3 naming |
| B7 spot vs configured scenario; leverage label; probes; sentences | **Accepted** — §4 pack contract; D-4 |
| B8 request-time performance; rebase basis; benchmark freshness | **Accepted** — persisted performance artifact §5; calendar policy §4.4. **Modified** on retained Full-Research compute: existing (pre-project) loader computations stay as a bounded, documented exception (§9.3) rather than blocking the redesign on a Tool A internals retrofit |
| B9 target_delta, greeks on chain, schema migration | **Accepted** — no config-delta change (near_atm bucket already exists); greeks stamped on candidate rows only; deliberate schema bump + migration §6.4 |
| H1–H9 | **Accepted** — folded into §§4–13 (H2 spot-labelling, H3 gate definitions §6.3, H5 navigation §9.4, H6 composite-prose sweep §9.2, H9 payload spike moved to M0.5) |
| I1–I4 | **Accepted** — contract-first sequence §13, atomic publish + fault injection §5.3, stage identity §5.5, safe embed primitive §9.5 |

### 2.1 Pre-fixes from Codex's round-two in-flight observations (2026-08-11)

Applied before the round-two file landed: (a) §5.5 stage identity corrected — the in-refresh
path takes identity from the live refresh context, never the previous manifest; (b)
`confidence_score` removed from the score-builder catalog (§7) — the locked requirements ban
confidence on this page; (c) **M0.3 migration lesson recorded:** renaming a column on a
persisted artifact leaves the manifest-resolved generation stale until the next publish — the
Tool D overview shows an honest blank in "FCF Yield @ G" until a refresh republishes.
Standalone `tool-d` cannot heal it (the manifest is only rewritten at refresh end), so the fix
is the next full refresh. Rule adopted for every schema change in this project (§6.4 already
demands it for options): the same change must state the serving impact between commit and next
publish, and regenerate in-commit when the interim state would be wrong rather than blank.

---

## 3. Architecture

### 3.1 The client-side interactivity exception (narrow, by Victor's D-1/D-2)

Everything analytical is computed and persisted by the backend. The **only** client-side
computation permitted on this page:

- **Modules:** exactly three first-party files — `static/gold-dial.js`, `static/score-builder.js`,
  `static/option-sizing.js` — plus visibility-only toggles elsewhere.
- **Inputs:** only backend-resolved values embedded in the page (line coefficients, constants,
  percentiles, contract fields). No fetches, no derived state reused across modules.
- **Formulas:** each exists once, in its module, mirroring a named backend function
  (`gold_lines.evaluate`, the score combine rule, intrinsic value). Guard semantics (EBITDA > 0,
  EPS > 0) mirror `screening/layer1.py`/`layer2.py` exactly.
- **Locks:** (a) pytest parity — backend reference values at probe inputs are embedded as fixtures
  and asserted; (b) **real-JS behavioural tests** — Playwright drives the actual modules (drag,
  allocate, reset, keyboard) in each M3 lane's exit gate, not only at M4; (c) the serve token
  sweep still bans analytics in all serve *Python*.
- **Docs:** `ARCHITECTURE_FOUNDATIONS.md` gains this exception verbatim in M0.5 (with the
  requirements addendum already in place).

Anything not in this list that wants client math is a new decision for Victor.

### 3.2 Corrected load-bearing decisions (v1 → v2 deltas)

- **True spot, never the Tool B default scenario** (B7): Tool B's configured
  `default_gold_price_assumption` is $4,000 — not spot. The pack build derives spot via
  `latest_gold_price_from_history` (`model/tool_d.py:175`) and persists **explicit spot display
  values** as their own evaluated row. The page's spot column renders only those.
- **One line implementation** (unchanged): Tool D's `_ebitda_line_from_tool_b`
  (`model/tool_d.py:618`) moves to `model/gold_lines.py`; Tool D and the pack builder both import
  it. The pack does not re-derive concepts Tool D already owns — threshold golds render from the
  Tool D artifact.
- **Leverage naming** (B7): the dial's moving leverage is **stressed forward leverage**
  (net_debt / forward EBITDA at g) and is labelled exactly that, reusing Tool D's
  `leverage_stressed_at_g` concept. Tool B's trailing `leverage` (net_debt / EBITDA LTM) keeps its
  own row and label. Two concepts, two labels, no silent redefinition.
- **Linearity probes** (B7): evaluate at both dial bounds ($2,000, $6,000) + one interior point
  ($4,000) + spot. Tolerance is `max(abs_tol, rel_tol × |value|)` with `abs_tol` covering the
  near-zero case; both in config. A **systemic** violation (≥ `systemic_min_tickers` failing)
  fails the stage loud; a single ticker's violation degrades that ticker
  (`gold_response_status != OK`, dial disabled for it, reason shown) — degrade per item.
- **Finance source is a first-class key** (B7/H1): the pack persists per-source rows
  (`finance_source ∈ {our, official}`); percentiles are computed per source for Tool B metrics;
  the serve state carries both and the renderer picks one source consistently across corporate
  cards, sentences, and score builder. Cache identity is unchanged (stat-keyed artifacts; source
  chosen at render from cached both-source state).
- **Performance is a persisted artifact** (B8): no chart series are computed in the request path.
  See §5 (`ticker_page_performance`) and §4.4 for the calendar policy.
- **Scenario-vs-spot labelling rule** (H2): the dial moves **only** the corporate-finance values
  wired to it. The score builder, Lab section, performance chart and failing-check notice are
  labelled "at spot" / "as of {date}" and visibly do not react to the dial.

### 3.3 What stays from v1 (review-endorsed)

Section decomposition and page order; reuse of `COLUMN_HELP` + help popover, `serve/ui`
primitives, `charts.py` SVG builders + accessible table twins; Lab reuse of `dial_cells`/
`dial_episodes`/`load_ticker_curve`; composite scores removed from this page but kept elsewhere;
progressive disclosure per requirements §4; M0 bug fixes.

---

## 4. Gold response pack — exact semantics

### 4.1 Build
New stage `ticker-page` (§5.5). For each finance source: run `compute_tool_b_in_memory` at
{$2,000, $4,000, $6,000, spot}; derive per-metric lines via `gold_lines`; verify linearity
(§3.2); persist lines + constants + **spot display values** + per-ticker `gold_response_status`.

### 4.2 Metrics carried
Lines: `forward_revenue_musd`, `forward_ebitda_musd`, `forward_net_income_musd`, `forward_eps`,
`sustainable_fcf_musd`. Constants: `market_cap_musd`, `enterprise_value_musd`, `net_debt_musd`,
`interest_expense_musd`, `share_price_usd`, `aisc_usd_per_oz`, `cash_cost_usd_per_oz`,
`production_oz`, `ebitda_ltm_musd`. Client-assembled ratios (guards mirrored from layer1/layer2):
margin $/oz, margin %, FCF yield, EV/EBITDA(g), forward P/E(g), stressed forward leverage(g).
Invalid ratio at some g renders a short reason ("EBITDA ≤ 0 here"), never a silent blank (B7).

### 4.3 Display contract
Spot column server-rendered from persisted spot values; scenario column exists only when the
dial (global control bar, D-6) leaves spot; every moved number's "?" names its basis; failing
sentences fixed + "at spot gold" (D-4).

### 4.4 Performance series policy (B8)
`ticker_page_performance` rows are precomputed per (ticker, series, view, horizon): common
comparison calendar per horizon; **one shared rebase date** = the latest first-observation among
the series in that window, disclosed on the chart ("indexed to 100 at {date}"); a series starting
after the window start is labelled late-start; missing spans render as visible gaps (the SVG
builder gains explicit gap segments — no bridging, B8). Benchmark rows carry their own source
run identity; a benchmark older than the equity data renders "benchmark as of {date}" — never
silently mixed. Horizons are calendar-anchored (1Y/3Y/5Y back from as-of, first trading
observation on/after the cutoff; H7).

---

## 5. Artifact contracts (closes B2)

Common to every new artifact: immutable run-stamped parquet + mutable latest alias, atomically
published (§5.3); sha256 + row count recorded in the model-state manifest; resolved by readers
**only** through the manifest pointer; schema name + version columns embedded; a dedicated
validated reader per artifact that classifies MISSING / STALE / CORRUPT / MISALIGNED and returns
an explicit state object — a bad artifact renders a degraded section with a reason, **never** a
valid-looking empty section (B2).

| | `ticker_page_gold_response` | `ticker_page_percentiles` | `ticker_page_performance` | `option_chain_history_daily` |
|---|---|---|---|---|
| Producer stage | `ticker-page` (after tool-d) | `ticker-page` | `ticker-page` | option-artifacts |
| Directory | `data/output/ticker_page/` | same | same | `data/output/options/` |
| Files | `gold_response_output_{run}.parquet`, `gold_response_latest_{run}.parquet`, `gold_response_latest.parquet` (same triple pattern for all) | 〃 | 〃 | 〃 |
| Key / uniqueness | (ticker, finance_source) | (ticker, finance_source, metric_key) | (ticker, series, view, horizon, date) | (ticker, as_of_date) |
| Required columns | key + line slope/intercept per metric + constants + spot values + `spot_gold_usd/date` + `gold_response_status` + `linearity_max_residual` | key + raw value + `pct_high_good` + `pct_low_good` + `rank_eligible` + `rank_exclusion_reason` + cohort size | key + value + `rebase_date` + `series_source_run_id` + `late_start` | §6.2 |
| Provenance | `schema_version`, `source_run_id`, `snapshot_refresh_run_id`, `parent_refresh_id`, `config_hash`, upstream tool run ids | 〃 + all four tool run ids | 〃 + foundation + benchmark run ids | §6.2 |
| Required? | required once the stage ships (manifest `state=complete` demands it) | required | required | required within the options publish block |
| Reader | `load_gold_response(paths)` | `load_score_percentiles(paths)` | `load_performance_series(paths, ticker)` | dedicated `load_option_chain_history(paths, ticker)` — **not** added to the Option Trading overview loader's read set (B9) |
| Failure state | per-ticker `gold_response_status` degrades the dial only | page shows "score builder unavailable: {reason}" | chart shows degraded notice | trend charts show degraded notice |
| Pruning | `run_pruning.py` gains both output dirs; current-generation immutables always retained | 〃 | 〃 | canonical history is **never** reconstructible-from-runs-only (§6.1) and pruning must not touch it |

Also versioned (existing artifacts, deliberate bumps — §6.4): `option_signal_history`
(+`implied_move`), `option_selected_candidates` / `option_candidate_slots` (+greeks columns).

### 5.3 Atomic publication + fault injection (I2)
Use the shared atomic multi-file publish (as `publish_option_artifacts_and_history_atomically`
does): write all immutables, then aliases, then the manifest pointer **last**. A kill between any
two steps leaves the previous complete generation current. Fault-injection tests interrupt each
boundary and assert the prior state still serves.

### 5.4 Implementation inventory (B2)
`_artifact_map()` + `REQUIRED_ARTIFACTS` + `_tool_latest_directory_and_prefix()`
(model_state.py:519/48/1668) learn the two ticker-page artifacts; `_alignment()`
(model_state.py:973) learns the `ticker-page` stage and asserts its
`snapshot_refresh_run_id` matches the tool generation; immutable metadata assembly
(model_state.py:741) covers them; `ProjectPaths` gains the latest-alias properties;
`run_pruning.py` gains the directories; `_loader_inputs_signature` (workspace_state.py:121)
gains every new artifact path; interruption/rollback tests per §5.3.

### 5.5 Stage identity (I3; corrected per Codex round-two in-flight note)
`ticker-page` runs inside refresh after tool-d (record_step + total_steps bump, cli.py:3402+)
and as a standalone subcommand. The two paths take identity differently — reading the manifest
mid-refresh would read the **previous** generation (the manifest is only published at refresh
end, cli.py:3638):
- **In-refresh:** the stage receives `parent_refresh_id` and the upstream tool run ids from the
  live refresh context (the same values the manifest publisher will later write) — it never
  reads the previous manifest.
- **Standalone:** reads the current manifest, asserts the tool generation it names is aligned
  and fresh, inherits identity from it, and aborts with a named error on any mismatch.
Both paths self-report per-substep seconds + rows_built + rows_persisted (clone
`_record_step_timing`, model/pipeline.py:721).

---

## 6. Options history (closes B3, B9, H3)

### 6.1 One authority per field
- **Horizon-keyed signals** (`atm_iv`, `skew_residual`, `iv_rv_ratio`, iv_rank) stay solely in
  the canonical `option_signal_history` (ticker, as_of_date, signal_horizon_days) with its
  existing merge + no-shrink machinery. It is **extended** with `implied_move` (same key; schema
  bump). The page's IV / IV-vs-realised / implied-move trends read this history at the signal
  horizon, with the tenor named in chart title + tooltip (B6/H7).
- **Chain-level daily quantities** — fields with **no existing authority** — go to the new
  `option_chain_history_daily`: `put_oi_total`, `call_oi_total`, `total_open_interest`,
  `put_oi_otm`, `call_oi_otm`, `put_call_oi_ratio_total`, `put_call_oi_ratio_otm`, `put_volume`,
  `call_volume`, `total_volume`, capture diagnostics (`n_contracts`, `n_expirations`,
  `capture_quality`, `row_status`).
- The M0.1 fix already persists the split sums into `options_features` going forward; the
  history artifact is built **merge-forward**: prior immutable history + today's capture. Run
  directories are best-effort enrichment for the split backfill only — never the authority; a
  pruned run can never shrink the history (no-shrink gate cloned from
  `prepare_option_signal_history`).

### 6.2 Row provenance + no-lookahead
Every row: `row_status ∈ {observed, carried_forward, backfilled}`, `capture_run_id` (original)
distinct from `published_run_id` (current publisher), `schema_version`. Any recomputed derived
value (including the one-time iv_rv correction migration in the canonical history, §6.4) uses
only prices with `price_date <= row.as_of_date` — pinned by a test that plants a future price
and asserts it is never read.

### 6.3 The daily gate, exactly (H3)
Capture unit = one refresh run's chain snapshot. Duplicate contracts within a capture are
identified by (expiration, option_type, strike) — last quote wins. Quote validity reuses
`option_quote_is_tradable` bounds; IV validity `[0.01, 3.0]` (config). Same-day captures: keep
the **complete** capture with the highest `total_open_interest` (ties → latest run); a capture
is partial when `total_open_interest < partial_capture_min_ratio × same-day max`, or (lone rows)
when `n_expirations` < `expiry_floor_ratio` × trailing 20-day median. Intraday re-runs
**replace** the day's row only by winning that rule. No synthetic rows on holidays/weekends —
absent days stay absent. Chain-level series roll expiries naturally; diagnostics columns let the
UI explain poor coverage without recomputing (H3). Field-level outliers (IV 0.0 / 111.87, skew
72.8) are gated to NA per item with `capture_quality` noting it. Every threshold in
`hedge_readiness.yaml` under `history_quality:`.

### 6.4 Schema migrations (B9, review checklist 15)
Option artifact contract bumps v3 → v4: `option_signal_history` gains `implied_move`;
candidate/slot artifacts gain greek columns; `option_chain_history_daily` joins the atomic
publish set (but not the overview loader's reads). First refresh after upgrade: readers accept
v3 rows (missing new columns → NA) and the publisher writes v4; carry-forward of a v3 generation
stays valid; rollback = previous manifest still points at v3 immutables, which still validate.
One-time value-correction migration for historical `iv_rv_ratio` (wrong by ~100x pre-M0.1):
recompute per row date-bounded (§6.2), row count must not change, migration run id recorded in
the artifact metadata. Greeks: computed on **selected candidate/slot rows only** (never the full
chain in the page path); units fixed as gamma per $1 underlying, vega per 1.00 vol (displayed
per point), theta per calendar day; inputs = quote IV, actual DTE, manifest `risk_free_rate`,
q = 0 — all stamped, model version column included. Shared contract multiplier and
intrinsic-value helpers reused (B9). No change to `hedge_readiness.target_delta` — the existing
`near_atm` + directional buckets already provide the ATM and directional rows (B9).

---

## 7. Score builder — engine and exact catalog (closes B4, H1)

**Engine:** generalize the Candidate Finder's eligibility + ranking primitive
(`common/eligibility.py`, `model/candidate_finder.py` ranking path) — one engine, two consumers.
Percentiles via `oriented_percentile`, computed both orientations (ties make 100−p inexact).
Degraded subjects are excluded, not down-weighted: Tool A/C metrics require `score_eligible`;
Tool D metrics require `resilience_data_status == "OK"`; Tool B metrics require the row's
normalization/staleness gates. Excluded rows persist `rank_eligible=false` +
`rank_exclusion_reason` and can never receive a percentile (B4).

**Deterministic semantics:** pandas `rank(pct=True)` average-tie policy, documented; minimum
cohort `min_eligible_peers` (config, default 10) below which the builder shows "not enough
comparable miners" instead of ranks; zero active metrics → no score (opt-in, Q24); one active
metric → that metric's percentile with a breadth notice; per-metric NA → metric disabled for the
company and excluded from its budget; weight shifts of ±10 renormalize across active metrics;
stability warning when any shift moves rank ≥ `rank_stability_alert_positions` (config, 3).
Everything the client combines is persisted; the combine rule is the §3.1 exception.

**Catalog (exact, 20 metrics — the contract test asserts every source column exists).**
`confidence_score` was removed from the catalog (Codex round-two in-flight note): the locked
requirements remove confidence from this page entirely, and letting users rank on it would
reintroduce it through the side door. Confidence still gates eligibility (a low-confidence
subject is excluded by `score_eligible`), it just isn't a rankable metric.

| Key | Category | Source · column | Default direction | Spot/scenario |
|---|---|---|---|---|
| down_beta_core | Trading | tool_a · down_beta_core | lower | n/a |
| up_beta_core | Trading | tool_a · up_beta_core | higher | n/a |
| asymmetry_ratio_core | Trading | tool_a · asymmetry_ratio_core | lower | n/a |
| downside_volatility_52w | Trading | tool_a · downside_volatility_52w | lower | n/a |
| rel_strength_vs_gdx | Trading | tool_c · rel_strength_vs_gdx_pct | higher | n/a |
| rel_weakness_vs_gdx | Trading | tool_c · rel_weakness_vs_gdx_pct | lower | n/a |
| downside_hit_rate | Trading | tool_c · downside_hit_rate_10pct | lower | n/a |
| upside_hit_rate | Trading | tool_c · upside_hit_rate_10pct | higher | n/a |
| tail_worst10 | Trading | tool_c · tail_avg_return_worst10pct | higher | n/a |
| tail_best10 | Trading | tool_c · tail_avg_return_best10pct | higher | n/a |
| margin_pct | Corporate | tool_b · margin_pct (per source) | higher | spot |
| fcf_yield | Corporate | tool_b · fcf_yield (per source) | higher | spot |
| ev_ebitda | Corporate | tool_b · ev_ebitda (per source) | lower | spot |
| forward_pe | Corporate | tool_b · forward_pe (per source) | lower | spot |
| leverage_trailing | Corporate | tool_b · leverage (per source) | lower | spot |
| aisc | Corporate | tool_b · aisc_usd_per_oz | lower | spot |
| reserve_life | Corporate | tool_b · reserve_life_years | higher | spot |
| survival_distance | Corporate | tool_d · survival_distance_to_interest_cover_pct | higher | spot |
| fragility | Corporate | tool_d · fragility_ebitda_pct_per_10pct_gold | lower | spot |
| cost_curve_pctile | Corporate | tool_d · cost_curve_aisc_percentile | per tool_d.yaml orientation | spot |

Tool B metrics persist per finance source; the builder follows the page's source toggle
coherently (H1). The whole section is labelled **"at spot, as of {date} — the gold dial does not
move these ranks"** (H2). Scenario-aware ranking is deferred, not implied.

---

## 8. Options availability + routes (closes B5, B6)

**State matrix** (resolved from model-state-selected artifacts, never the raw manifest):

| State | Page behaviour |
|---|---|
| Genuinely no listed options (current artifact says so) | Section + nav anchor absent |
| Current coherent data | Full section, as-of date shown |
| Valid carried-forward generation | Section visible + explicit "carried forward from {date}" label |
| Artifact missing / corrupt / stale / misaligned | Degraded section with reason — **never** "no options" |
| Contracts exist, no eligible candidates | Market context visible + a plain candidate-selection reason |

Render tests cover all five with control fixtures.

**Routes** (B5): benchmark ETFs (GDX/GDXJ) keep the working `?lens=option-trading` route
untouched — they are not Tool B tickers and have no corporate page. Only corporate-company links
are re-pointed to `#options` on the canonical page; the lens parameter stays accepted for
corporate tickers (renders the full page). Route tests: AEM from Candidate Finder, AEM from
Option Trading, GDX and GDXJ from Option Trading, direct canonical URLs, back/forward
restoration of query-param state.

---

## 9. Serve layer

### 9.1 Composition (unchanged order)
Header + **global control bar (dial)** + nav → performance chart → corporate finance → market
behaviour → options (conditional per §8) → compare on your own terms → inputs/notes. Open/closed
exactly per requirements §4. New package `serve/ticker_page/` with one module per section;
renderers **moved** from `detail_panels.py`; repo-wide token sweep auto-covers the package;
per-module companion scans added; one formatting implementation (`format_helpers` + one shared
JS formatter pinned by parity).

### 9.2 Verdict removal is a content edit, not a relocation (H6)
The exact surviving raw panels are enumerated in the M2 spec; composite-score labels and prose
(Gold Sensitivity Score, confidence labels, rank prose) are **rewritten or removed** — a sweep
asserts the §8-removed strings appear nowhere on the page, including inside disclosures.

### 9.3 Retained request-time computation — bounded, documented (B8 modification)
Unchanged pre-existing behaviour retained in the memoized loader, listed exhaustively:
`build_structural_weekly_series`, `compute_horizon_returns_for_ticker`, the sanctioned
non-canonical-window recompute in the behaviour section. Nothing new joins this list; the
performance chart does NOT (it is §5-persisted). Recorded in `ARCHITECTURE_FOUNDATIONS.md` as
existing debt with a follow-up entry in §14. If Codex still rejects this at re-review, the
fallback is persisting these too in the `ticker-page` stage — the section interfaces don't
change either way.

### 9.4 Navigation + state semantics (H5)
Query-param state (source, window, `lab_h/lab_b/lab_s`) is canonical: a valid Lab query reopens
the Lab disclosure, anchors and focuses it; back/forward restore it. Form POST outcomes reopen
the owning panel, anchor, and move focus to the flash/error. Client-only state (dial position,
score weights, chart series toggles) resets on navigation **by design**, and each control's "?"
says so; reset buttons exist on dial and score builder. Lab results get their own bounded cache
(keyed ticker+h+b+s, size ~32) so 40 combinations can't evict the small detail cache (H9).

### 9.5 Safe embedding (I4)
One `embed_json_payload(id, obj)` helper (escapes `</script`, U+2028/9, ampersands; tested with
hostile strings); every page JS module no-ops when its markup is absent.

### 9.6 Accessibility (H8)
Interactive chart controls are real `<button>`s with `aria-pressed`; sliders have labels +
`<output>`; scenario/rank changes announce via one polite live region; inactive SVG variants are
`display:none` + `aria-hidden`; keyboard focus visible everywhere; reduced-motion honoured;
degraded states carry text explanations. M3 lane gates include keyboard-only and
assistive-state assertions, not only screenshots; responsive checks assert controls and tables
remain operable at 640/320px.

---

## 10. Config additions

| File | Keys |
|---|---|
| new `config/ticker_page.yaml` → `TickerPageConfig` (+ `EXPECTED_CONFIG_FILES`, `AppConfig`) | `dial: {min_gold_usd: 2000, max_gold_usd: 6000, step_usd: 1, probe_gold_usd: [2000, 4000, 6000], linearity_abs_tol_musd: 0.5, linearity_rel_tol: 0.001, systemic_min_tickers: 5}` · `chart: {horizons: [1Y, 3Y, 5Y]}` · `lab: {default_horizon_weeks: 8, scatter_from_year: 2016}` (ticker page only, D-5) · `score_builder: {budget_points: 100, min_eligible_peers: 10, rank_stability_shift_points: 10, rank_stability_alert_positions: 3, metrics: [...§7 catalog...]}` |
| `config/hedge_readiness.yaml` | `history_quality: {partial_capture_min_ratio: 0.70, iv_valid_range: [0.01, 3.0], skew_valid_range: [-1.0, 1.0], implied_move_valid_range: [0.0, 1.0], expiry_floor_ratio: 0.5, trailing_median_days: 20}`. **No target_delta change** (B9). |
| `config/tool_c.yaml` | shipped in M0 (`a6e8bb1`) |
| `config/lab_dial.yaml` | still deferred to M3c (import-time constant web; unchanged from v1 amendment). Shared-Lab keys stay out of `ticker_page.yaml` (H4). |

---

## 11. Test strategy + acceptance gates

Everything from v1 §10 plus the review's gates, verbatim adopted:

- **Artifact/state:** immutable + schema-validated + checksummed; mismatched refresh identities
  → degraded, never mixed; stale/corrupt/wrong-schema fail explicitly; interrupted build serves
  the prior generation (fault injection per publish boundary); pruning never touches current
  immutables or canonical history; the five §8 option states render distinctly.
- **History/model:** no-shrink after rerun; deterministic dedupe; horizon + actual expiry/DTE
  survive rebuilds; no RV/lookahead leak (future-price plant test); degraded subjects never
  ranked; tie/NA/one-peer/all-missing/finance-source cases deterministic; lines pass at both
  bounds + interior + spot; near-zero tolerance tested; spot ≠ configured scenario proven by a
  fixture whose Tool B default differs from spot; D-4 label present while the dial moves.
- **Routes/interaction:** the six §8 route tests; back/forward; Lab query reopen+focus; form
  outcome visibility; "no options" never used for pipeline failure.
- **Charts/payload:** shared rebase date or disclosed late start; visible gaps; twin tables
  match SVG values; payload budgets measured on an option-heavy ticker AND NEM; real-JS tests
  for dial/score/sizing/reset/accessibility per M3 lane.
- **Integration (M4):** focused ticker/Tool B/D/Option Trading/Finder/Lab/model-state/schema/
  carry-forward/pruning/route suites → full suite → real-workspace smoke loading a normal miner,
  a weak-inputs ticker, a no-options company, an option-heavy company, GDX, GDXJ → the
  unmerged-branch/worktree audit before merge.

---

## 12. Payload + cache spike (M0.5, moved ahead of M2 per H9) — **MEASURED 2026-08-11**

Full numbers in `ticker_page_payload_spike_2026-08-11.md` (real artifacts, NEM + the heaviest
chain GDX at 2.43M OI). Worst-case embed-everything = 317 KB raw JSON; three binding rules bring
the realistic total to ≈120–140 KB embedded on a ~150–250 KB page — inside the ≤300 KB budget:

1. **Never embed raw Lab episodes** (one chart's rows were 131 KB / 41% of the total): Lab
   charts are server-side SVG embedding only per-tick display attributes; scatter trimmed 2016+.
2. **Round embedded floats** (4 significant figures; percentiles to 0.1).
3. Producer note: benchmark parquets carry only `*_local` columns — the performance producer
   resolves USD explicitly through the one normalize boundary, never by silently reading
   `close_local`.

Warm-load and cache-memory measurements repeat on the real page at M2 exit and M4 (target warm
≤ 100 ms; Lab side-cache keyed ticker+h+b+s, size 32).

---

## 13. Build sequence (revised per I1 — contract-first, single owner)

Contract owner: Claude (orchestrator) owns every schema/config contract; lanes consume, never
edit, contracts.

| Milestone | Contents | Exit gate |
|---|---|---|
| **M0** ✅ | Isolated correctness fixes (`ce2583a`…`3f86c3d`) | shipped; Codex may review commits separately |
| **M0.5** | Requirements addendum ✅ (this revision) · `ARCHITECTURE_FOUNDATIONS.md` exception text · exact contracts (§§4–7 refined into code-level stubs: schema modules + config models + empty readers) · payload spike (§12) | Codex re-review of plan v2 closes B1–B9; budgets recorded |
| **M1a** | Shared plumbing: `gold_lines.py` extraction (Tool D consumes it), eligibility-engine generalization, schema/reader modules, model-state + pruning + paths wiring, atomic publish + fault tests | contract, alignment, migration, fault suites green |
| **M1b** | Producers: gold response pack, percentiles, performance series (one stage, sequential substeps) | immutable coherent artifacts; stage timings; no request-path analytics |
| **M1c** | Canonical option-history extension + chain history + greeks on candidates + v4 migration | no-shrink/no-lookahead/schema/carry-forward suites |
| **M1 int.** | Integration branch if lanes touched shared spine files; touched-file + semantic comparison; focused suites → full suite → real workspace smoke | all green on one branch |
| **M2** | Read-only serve spine: `ticker_page/` package, state objects + validated readers, route compatibility (incl. benchmark lens), state matrix wiring — page still looks unchanged | reader/cache/route suites; §8 matrix render tests |
| **M3** | Visible sections, sequential: a chart · b corporate+dial (+gold-dial.js) · c behaviour+Lab (+`lab_dial.yaml` move) · d options · e score builder (+score-builder.js) · f explainers+composite-prose sweep | per-lane: render + real-JS + a11y behavioural tests |
| **M4** | Budgets re-measured, provenance audit, docs, full integration gate (§11) | Victor review → Codex review → merge workflow |

Worker rules unchanged: written specs quoting this plan; no git state commands; I verify diffs
and commit checkpoints.

---

## 14. Risks + deferred

Risks: linearity guard trips (fallback: dense sampling mode, designed not built); JS/backend
drift (contained per §3.1); payload beyond budget (spike catches it pre-M1); schema-bump ripple
(migration §6.4 + carry-forward tests); `detail_panels.py` unpick merge risk (spine-first M2).

Deferred (explicit): requirements §7 items; scenario-aware failing sentences (D-4) and
scenario-aware rankings (H2); `/lab` default alignment (D-5); persisting the §9.3 retained
computations; percentile-implementation merge (`benchmark_comparison._percentile` vs
`oriented_percentile` — different tie semantics, would move rug markers); richer put/call
status vocabulary.
