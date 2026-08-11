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

### 2.0 Round-two review disposition (v3, 2026-08-11 — `codex_review_claude_ticker_page_plan_v2_and_m0.md`)

| Finding | Disposition |
|---|---|
| M0-1 Tool D release blocker | **Accepted with one modification.** Fix in code: `TOOL_D_SCHEMA_VERSION = 2` column + a truthful "pending rebuild" legacy render (notice + labelled cells, never a silent "–") + a regression loading a legacy-shaped artifact through the real render path. **Modification:** the rename stays instead of Codex's additive `fcf_yield`-becomes-stressed alias — reusing the old name with new semantics would silently change its meaning and concatenate spot history with stressed values under one Lab-vintage series name; the rename ends the old series cleanly and starts honest new ones. The artifact itself is rebuilt by the next scheduled refresh. |
| M0-2 IV/RV history blocker | **Accepted, pulled forward.** Date-bounded value-correction migration implemented and RUN now (before the next refresh appends new-scale rows): per-row recompute with prices ≤ as_of_date, keys+row-count preserved, migration provenance columns, backup + atomic write, idempotent, future-price-plant test. |
| M0-3 RV determinism | **Accepted** — sort by date, duplicate-dates keep-last, `pct_change(fill_method=None)`, tests for reversed/duplicate/internal-NaN inputs. |
| M0-4 unknown vs zero | **Accepted** — per-side sums are None when a non-empty chain has no observed values (or the column is missing/empty chain); ratios None when either side unknown; observed zero stays 0. |
| M0-5 finite validators | **Accepted** — non-finite rejected on all tag thresholds via the shared finite boundary; YAML-load test. |
| P1 stage identity | **Accepted** — §5.5 (already corrected) extended: `--skip-tool-b` semantics, standalone runs are non-authoritative, timing helper reused not cloned. |
| P2 request-path exception | **Accepted** — §9.3 exception deleted; retained Tool A detail series become a fourth persisted artifact (`ticker_page_research_series`) produced by the stage. |
| P3 v3/v4 migration | **Accepted** — versioned artifact-name sets + a legacy-v3 reader window (his option 1), rollback matrix in §6.4; read-set vs publish-set split so the overview loader never reads page-only artifacts. |
| P4 exact schemas | **Accepted** — §5.6 exact column tables, status/reason enums, per-metric-family tolerances, residual diagnostics; cache identity from the manifest pointer + resolved immutables; "two artifacts" wording fixed (there are four). |
| P5 catalog/ranking | **Accepted** — confidence already removed; asymmetry flipped to higher-good with an explicit sign-case rule; `cost_curve_pctile` dropped (double-weights AISC) → 19 metrics; coverage rule, contribution formula, slider mechanics, tie policies pinned in §7. |
| P6 finance-source enum | **Accepted** — canonical `{our, yahoo}` reused ("Yahoo Fundamentals" is display wording only); URL compat regression; Tool D metrics + resilience content disabled with a truthful reason in yahoo mode (v1). |
| P7 history provenance/gates | **Accepted** — actual expiry/DTE on new signal-history rows; field-level backfill flags; per-(ticker,horizon) no-shrink; trailing coverage gates on expirations/contracts/sides/OI; structural dedupe for whole-chain sums — `option_quote_is_tradable` reserved for candidate/IV fields. |
| P8 availability authority | **Accepted** — new small required `option_availability` artifact with the LISTED/NONE_LISTED/FETCH_FAILED/FILTERED_WINDOW_EMPTY/UNKNOWN enum + evidence; only NONE_LISTED hides the section. |
| P9 benchmark alignment | **Accepted** — benchmarks resolved through the options manifest's immutable snapshots; per-series freshness status persisted; stale benchmarks omitted-with-reason; calendar rules pinned (§4.4). |
| P10 state/sizing | **Accepted** — score weights/directions travel in the URL (survive ranked-list clicks and back/forward); legacy option params preserved; sizing edge-case table pinned (§9.4). |
| P11 Lab/Full-Research/tests | **Accepted** — Lab cache key includes pointer + config hash; per-chart period labels; `lab_dial.yaml` refactor REMOVED from this project entirely; Full Research surviving panels + removed strings enumerated now; v1 test list inlined (self-contained); option read-set updated explicitly. |
| P12 M0.5 completeness | **Closed by `2594aba`** (measurements + narrow ARCH amendment) + this revision (P2 exception removed; stubs land in M1a). |

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
- **Finance source is a first-class key** (B7/H1/P6): the canonical machine enum is the
  existing `{our, yahoo}` (`screening/pipeline.py:48`, `normalize_finance_source`) — "Yahoo
  Fundamentals" is display wording only; existing `fundamentals_source=yahoo` URLs and forms
  keep working (compat regression). The pack persists per-source rows; percentiles per source
  for Tool B metrics; failing-check sentences persisted per source at spot. **Tool D content in
  yahoo mode (v1):** the persisted Tool D artifact is Our-View; rather than mixing sources, the
  resilience group and the three Tool D catalog metrics are disabled in yahoo mode with the
  truthful reason "resilience is computed on Our View inputs" — producing yahoo-mode Tool D via
  the shared model path is deferred work, recorded. The renderer picks one source consistently
  across cards, sentences, and score builder.
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

### 4.4 Performance series policy (B8, P9)
`ticker_page_performance` rows are precomputed per (ticker, series, view, horizon): common
comparison calendar per horizon; **one shared rebase date** = the latest first-observation among
the included series in that window, disclosed on the chart ("indexed to 100 at {date}"); a
series starting after the window start is labelled late-start; missing spans render as visible
gaps (the SVG builder gains explicit gap segments — no bridging, B8).

**Benchmark alignment (P9):** GDX/GDXJ are read through the current (or in-flight) options
manifest's **immutable run-stamped benchmark snapshots** (`benchmark_snapshot_paths`), never the
mutable cache directly. Each series row persists `series_status` (OK / STALE_OMITTED /
MISSING) + `series_as_of_date` + its source run id. A benchmark whose last observation is more
than `benchmark_max_staleness_days` (config, default 5 trading days) behind the equity as-of is
**omitted with a visible reason**, not drawn with a label. Note (payload spike): benchmark
parquets carry `*_local` columns only — the producer converts explicitly at the one normalize
boundary.

**Calendar rules (P9):** join on exact trading dates; no as-of fills inside a series; the rebase
basis uses the shared rebase date above; common ending date = the minimum last-date across
included series (later observations trimmed, disclosed); horizons are calendar-anchored (1Y/3Y/
5Y back from the common end, first trading observation on/after the cutoff; H7). Initial state:
**Compare view, 1Y** (the approved mock's opening state).

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

### 5.4 Implementation inventory (B2, P4)
`_artifact_map()` + `REQUIRED_ARTIFACTS` + `_tool_latest_directory_and_prefix()`
(model_state.py:519/48/1668) learn **all four ticker-page artifacts** (gold response,
percentiles, performance, research series); `_alignment()` (model_state.py:973) learns the
`ticker-page` stage and asserts its `snapshot_refresh_run_id` matches the tool generation;
immutable metadata assembly (model_state.py:741) covers them; `ProjectPaths` gains the
latest-alias properties; `run_pruning.py` gains the directories. **Cache identity (P4):** the
detail-loader signature keys from the model-state pointer file plus the manifest-**resolved
immutable** paths of the artifacts it loads — mutable aliases are not part of the identity and
are never the loading authority. Interruption/rollback tests per §5.3.

### 5.6 Exact schemas (P4) — authoritative, mirrored 1:1 by `golden_vector/contracts/ticker_page.py`

Common columns on every artifact: `schema_version` (int), `source_run_id`,
`snapshot_refresh_run_id`, `parent_refresh_id`, `config_hash` (all str, non-null).

**`ticker_page_gold_response` v1** — key (ticker, finance_source), unique, both non-null.
Columns: `ticker` str · `finance_source` str∈{our,yahoo} · per metric m ∈ {forward_revenue_musd,
forward_ebitda_musd, forward_net_income_musd, forward_eps, sustainable_fcf_musd}:
`line_slope_{m}` float64 nullable + `line_intercept_{m}` float64 nullable · constants
(`market_cap_musd`,`enterprise_value_musd`,`net_debt_musd`,`interest_expense_musd`,
`share_price_usd`,`aisc_usd_per_oz`,`cash_cost_usd_per_oz`,`production_oz`,`ebitda_ltm_musd`)
float64 nullable · `spot_gold_usd` float64 non-null · `spot_gold_date` str non-null · spot
display values (`spot_margin_usd_per_oz`,`spot_margin_pct`,`spot_fcf_yield`,`spot_ev_ebitda`,
`spot_forward_pe`,`spot_leverage_stressed`) float64 nullable · `gold_response_status`
str∈{OK, DEGRADED_NONLINEAR, DEGRADED_INPUTS} · `gold_response_reason` str nullable (non-null
iff status≠OK) · `linearity_max_residual` float64 nullable. **Tolerances (P4):** per metric
family — musd metrics `abs_tol_musd: 0.5`, `forward_eps` `abs_tol_eps: 0.005`, all metrics
`rel_tol: 0.001`; pass = residual ≤ max(abs_tol_family, rel_tol×|value|). **Residual
diagnostics** written to the run directory (not the artifact): per (ticker, source, metric,
probe_gold): expected, actual, residual, tolerance_applied, pass/fail — the loud-failure
message names the worst rows.

**`ticker_page_percentiles` v1** — key (ticker, finance_source, metric_key), unique, non-null.
Columns: key + `category` str∈{trading,corporate} · `raw_value` float64 nullable · `unit` str ·
`basis` str (window/accounting basis, e.g. "LTM", "fwd@spot", "156w") · `source_tool` str ·
`source_as_of_date` str · `pct_high_good` float64 nullable · `pct_low_good` float64 nullable ·
`metric_available` bool · `metric_reason` str nullable · `rank_eligible` bool ·
`rank_exclusion_reason` str nullable · `eligible_peer_count` int.

**`ticker_page_performance` v1** — key (ticker, series, view, horizon, date), unique, non-null;
`series` str∈{stock,gold,gdx,gdxj} · `view` str∈{price,rebased} · `horizon` str∈{1Y,3Y,5Y} ·
`date` date · `value` float64 nullable (null = visible gap) · `rebase_date` date ·
`late_start` bool · `series_status` str∈{OK, STALE_OMITTED, MISSING} · `series_reason` str
nullable · `series_as_of_date` date · `series_source_run_id` str · `currency_basis` str="USD".

**`ticker_page_research_series` v1** — three row-kinds in one keyed table (`kind`
str∈{weekly, horizon, window_fit}): weekly → (ticker, kind, date) + `stock_return` /
`gold_return` / `gdx_return` / `gdxj_return` float64 nullable; horizon → (ticker, kind,
horizon_label) + `horizon_return` float64 nullable + `basis` str; window_fit → (ticker, kind,
window) + `up_beta`/`down_beta`/`r_squared`/`weeks` float64/int nullable + `window_status` str.
Uniqueness enforced per kind-key; null-key rows rejected at publish.

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
  **A standalone run is non-authoritative:** it refreshes aliases and run-stamped files for
  development but does NOT republish model state — only a refresh publishes the pointer, so a
  standalone build can never make itself "current" against a mismatched generation.
- **`refresh --skip-tool-b` (P1):** the ticker-page stage is skipped with the tools it depends
  on; the published state marks the ticker-page artifacts **unavailable/stale for the new
  generation** (readers render degraded sections with that reason). Older ticker artifacts are
  never carried forward against a newer foundation generation.
Both paths self-report per-substep seconds + rows_built + rows_persisted by **reusing** the
existing timing helper (generalize `_record_step_timing`, model/pipeline.py:721, into shared
code — one copy, not a clone).

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

### 6.2 Row provenance + no-lookahead (P7)
Every chain-history row: `row_status ∈ {observed, carried_forward, backfilled}` **plus
field-level backfill flags** (`oi_split_backfilled` bool — coarse row status alone cannot say
which fields were enriched); `capture_run_id` (original observation) distinct from
`published_run_id` (current publisher) and distinct from the option set's required
`source_run_id` (which stays what it is today); `schema_version`. New canonical signal-history
observations gain `source_expiration` (date) + `source_dte` (int) — the actual expiry the
horizon resolved to; migrated older rows carry explicit unknowns. Any recomputed derived value
(including the iv_rv correction migration) uses only prices with
`price_date <= row.as_of_date` — pinned by a future-price-plant test. **No-shrink is per key
(P7):** the guard asserts the set of (ticker, signal_horizon_days) date-keys is a superset of
the previous generation's — a global distinct-date count can hide one ticker's disappearance.

### 6.3 The daily gate, exactly (H3, P7)
Capture unit = one refresh run's chain snapshot. **Whole-chain OI/volume sums use structural
validation only (P7):** duplicate contracts deduplicated by (expiration, option_type, strike)
last-quote-wins, values must be non-negative and observed — `option_quote_is_tradable` is NOT
applied here (it requires positive bid/ask/spread/activity and would silently drop illiquid
listed positions, contradicting M0's deliberately whole-chain sums). Tradability and IV-validity
gates (`iv_valid_range` [0.01, 3.0]) apply only to candidate selection and IV-derived fields.
**Capture completeness is judged against trailing coverage, not only the same-day max (P7):** a
capture must clear trailing-20-day-median floors on `n_expirations`, `n_contracts`, put-side
contract count, call-side contract count, AND total OI (`coverage_floor_ratio`, config) —
so a day where the "best" capture is itself partial is flagged, not crowned. Same-day: keep the
complete capture with the highest total OI (ties → latest run); intraday re-runs replace the
day's row only by winning that rule. No synthetic rows on holidays/weekends. Chain-level series
roll expiries naturally; diagnostics columns (`capture_quality`, per-floor pass flags) let the
UI explain poor coverage without recomputing. Field-level outliers are gated to NA per item.
Every threshold in `hedge_readiness.yaml` under `history_quality:`.

### 6.4 Schema migrations (B9, P3)
The single global option schema version + single artifact-name set cannot express "v3 still
valid while v4 adds artifacts" (model_state.py:1110-1141 requires every current name at strict
version equality). **Adopted contract (Codex option 1 — versioned name sets):**
- `contracts/option_artifacts.py` gains `OPTION_ARTIFACT_SETS = {3: <existing 10 names>,
  4: <10 + option_chain_history_daily + option_availability>}` and
  `OPTION_TRADING_READ_SET` (the overview loader's reads — **excludes** the two page-only
  artifacts, closing P11's loader-inventory gap; the ticker page uses dedicated readers).
- Validation (carry-forward and current-state) resolves the name set **by the generation's own
  stamped schema_version**: a v3 generation validates against the v3 set and stays fully
  usable; v4-only readers (`load_option_chain_history`, availability) return an explicit
  UNAVAILABLE_PRE_V4 state on a v3 generation → the page renders those trends/labels as
  "awaiting first v4 refresh", never as an error and never as "no options".
- The publisher always writes v4 (full set, atomic). First v4 refresh flips the generation.
- **Rollback matrix:** code rollback → v3 code reads a v4 generation's v3-named artifacts
  (superset tolerated: unknown names ignored by the v3 map) or the previous v3 pointer;
  data-pointer rollback → previous coherent generation (either version) stays current and
  validates against its own set. Partial v3 compatibility never counts as a complete v4 state.
- Distinct stores named explicitly (P3): the **mutable canonical** `option_signal_history.parquet`
  (merge target, no-shrink guarded), the **immutable published** `option_signal_history_points`
  (rebuilt from canonical each publish), and the **new** `option_chain_history_daily` (merge-
  forward, §6.1). `option_signal_history` schema gains `implied_move`, `source_expiration`,
  `source_dte`; candidate/slot artifacts gain greek columns.
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

**Deterministic semantics (P5):**
- **Percentile ties:** pandas `rank(pct=True)` average policy, documented in the "?" text.
  **Final-score ties:** deterministic order (score desc, ticker asc) with an explicit "tied"
  marker — two tie layers, two rules.
- **Peer cohort per metric:** a metric's percentile is computed over the peers with that metric
  present-and-eligible; each row persists `eligible_peer_count`.
- **Coverage rule:** a miner is ranked only when it has ≥ `min_active_metric_coverage` (config,
  0.6) of the user's ACTIVE metrics available; below that it stays visible in the ranked list
  as **unranked with the reason** ("has 4 of your 9 metrics"). Minimum cohort
  `min_eligible_peers` (config, 10) below which the builder shows "not enough comparable
  miners".
- **Weights:** integer points, slider step 1, budget 100; changing one weight renormalizes the
  others proportionally with largest-remainder rounding so the total is exactly 100; the ±10
  stability probe clamps at 0/100 and renormalizes the same way; deactivating a metric returns
  its points proportionally.
- **Contribution formula (pinned):** `contribution_i = weight_i × (pct_i − 50) / 50` — signed,
  weight-aware, neutral at the 50th percentile; bars scale by |contribution| with sign colour,
  so a 1-point metric can never look as influential as an 80-point one.
- **Asymmetry direction (P5):** `asymmetry_ratio_core` defaults **higher-good** (matches
  `model/scoring.py:50-68` and the approved mock). Sign rule: the ratio percentile is computed
  only over rows where both core betas are positive; a non-positive down-beta with positive
  up-beta is the maximally favourable regime — those rows rank at the top of the metric rather
  than entering the ratio pool; other non-positive-beta cases are metric-NA with reason.
- Zero active metrics → no score (opt-in, Q24); one active metric → that percentile with a
  breadth notice; per-metric NA → disabled for the company and excluded from its budget.
- **AISC appears once:** `cost_curve_aisc_percentile` is dropped from the catalog (it is
  oriented AISC — keeping both would let one idea be double-weighted). Catalog = **19 metrics**.
Everything the client combines is persisted; the combine rule is the §3.1 exception.

**Catalog (exact, 19 metrics — the contract test asserts every source column exists).**
`confidence_score` removed (requirements ban confidence on this page; it still gates
eligibility via `score_eligible`, it just isn't rankable). `cost_curve_aisc_percentile` removed
(double-weights AISC — P5). Every catalog entry carries label, unit/format, window/accounting
basis, source-as-of rule, exact eligibility predicate, missing policy, and coverage
participation in `config/ticker_page.yaml` — the table below is the source+direction summary.

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

Tool B metrics persist per finance source; the builder follows the page's source toggle
coherently (H1). The whole section is labelled **"at spot, as of {date} — the gold dial does not
move these ranks"** (H2). Scenario-aware ranking is deferred, not implied.

---

## 8. Options availability + routes (closes B5, B6, P8)

**Availability authority (P8):** none of the existing fields can truthfully prove "no listed
options" (optionability `none` also covers failed/empty captures; `EMPTY` fetch status conflates
an empty enumeration with a window-filtered one; `option_trading_overview` drops non-optionable
rows). New small **required** artifact `option_availability` (options stage, in the v4 set,
universe-complete — one row per ticker): `availability_status` str ∈ {LISTED, NONE_LISTED,
FETCH_FAILED, FILTERED_WINDOW_EMPTY, UNKNOWN} + `expirations_enumerated` int nullable +
`fetch_status` + `fetch_message` + `provider` + `capture_date` + provenance.
`NONE_LISTED` is written **only** when the expiration enumeration itself succeeded and returned
zero expirations. Only `NONE_LISTED` removes the section and nav anchor.

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

### 9.2 Verdict removal is a content edit, not a relocation (H6, P11 — enumerated now)
Surviving raw panels inside "Full research detail", exhaustively: the active-window and
cross-window **metric grids** (raw betas/r²/weeks only — the Gold Sensitivity Score,
`tool_a_rank`, and confidence score/label cells are removed); the **explanation cards** with
score/confidence prose rewritten to describe measured betas only; the **structural windows
table** (β/r²/weeks/status columns; score columns dropped); the **weekly-return scatter**; the
**volatility diagnostics** panel; the **exploratory horizon ladder**; every chart's accessible
data-table twin. Removed-string sweep (render-level, §8 list + "Gold Sensitivity Score",
"Confidence", rank prose) asserts none appear anywhere on the page, including inside
disclosures. Period labels (H7/P11): each Lab chart names its window — episodes scatter "since
2016", beat-rate cells "full history" — adjacent to the chart title.

### 9.3 No request-time analytics — the research series become a persisted artifact (P2)
Codex rejected the v2 "retained pre-existing computation" exception, correctly: Victor approved
exactly three browser modules, not a Python request-path exception, and the repo's definition
of done includes the infrastructure. **Adopted:** a fourth artifact,
`ticker_page_research_series`, is produced by the `ticker-page` stage and replaces the request-
path work when the new page ships — per ticker: the weekly return series
(`build_structural_weekly_series` output), the horizon-return ladder
(`compute_horizon_returns_for_ticker` output for every configured exploratory horizon), and the
per-window fit series for every selectable window (so the non-canonical-window recompute and
its `np.polyfit` sanctioned exception in `detail_panels.py` are **deleted**, and the token-sweep
exception list shrinks). The memoized loader then only reads artifacts. Schema in §5.6.

### 9.4 Navigation + state semantics (H5, P10)
Query-param state is canonical and survives back/forward and reloads:
- existing params preserved untouched: `financials_source` (incl. `fundamentals_source=yahoo`
  compat), beta `window`, and the legacy option params `side`, `horizon`, `size_mode`,
  `budget`, `quantity` (the sizing form's server flow keeps reading them);
- new params: `lab_h/lab_b/lab_s` (Lab controls — a valid Lab query reopens the disclosure,
  anchors and focuses it), `chart_view`/`chart_h`, `tw` (target window), and **`sb` — the score
  builder's weights+directions, compactly encoded (`sb=key:pts:dir,…`)**. P10's core point is
  adopted: the ranked list links to other tickers, so the comparison definition MUST travel —
  clicking through the list or going back never loses the user's weights.
- Form POST outcomes reopen the owning panel, anchor, and move focus to the flash/error.
- Ephemeral by design (each control's "?" says so, reset buttons provided): the dial position
  and chart legend toggles.
- Lab results get their own bounded cache keyed (ticker, h, b, s, **lab artifact pointer stat +
  live config hash** — P11) size 32, so 40 combinations can't evict the small detail cache and
  a Lab rebuild invalidates cached content.

**Sizing edge cases (P10, exact):** ask missing/zero/crossed (bid>ask)/below-intrinsic or quote
stale → the tool renders disabled-with-reason for that contract (never silently substitutes
mid); budget < one contract's cost → "0 contracts — one contract costs $X"; contracts =
floor(budget / (ask × 100)), whole contracts only, hard cap `max_contracts: 10000` (config);
share-price slider range = current price ±60%, step derived from price magnitude ($0.05 / $0.5
/ $1 bands), default = current price; break-even = strike − ask (puts) / strike + ask (calls);
ladder rows at ±10/20/30% and the break-even point; value at expiry = intrinsic only (Q34);
reset restores the server-rendered defaults.

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
| `config/lab_dial.yaml` | **REMOVED from this project entirely (P11/H4)** — the shared-Lab constant relocation is broader-than-ticker scope; it happens only as a separately approved standalone refactor. Shared-Lab keys stay out of `ticker_page.yaml`. |

---

## 11. Test strategy + acceptance gates

Self-contained (P11 — the v1 baseline inlined, no git archaeology needed):

- **Model unit tests:** linearity guard (synthetic kink fails loud; per-ticker degrade with
  reason); pack values equal a real in-memory Tool B at every probe price; percentile
  orientation incl. deliberate ties and NA; the §6.3 history gates each with a healthy control
  row; greeks vs published reference values; failing-sentence wording asserted at render level.
- **Serve render tests:** section order and requirements-§4 open/closed defaults; options
  section + nav anchor absent ONLY for a NONE_LISTED fixture while a control ticker keeps both;
  removed-string sweep (§9.2); dial spot column server-rendered with scenario cells carrying
  `data-metric`; Lab controls round-trip in `return_to`; forms regression (raw_overrides).
- **Guardrails:** repo-wide serve token sweep auto-covers `serve/ticker_page/`; per-module
  companion scans; `serve/ui` purity untouched; new JS files listed in the shell test.
- **One Playwright gate at M4** (batched, from `.playwright-mcp/`, server via
  `serve_with_socket_timeout.py`) + per-lane real-JS behavioural tests in M3.
- **Perf:** warm `/ticker/NEM` ≤ 100 ms; payload ≤ 300 KB (per §12); stage seconds in the
  manifest; `run_focused_selection.py` gains the new files.

Plus the round-one review's gates, verbatim adopted:

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
| **M0** ✅ | Isolated correctness fixes (`ce2583a`…`3f86c3d`) **+ round-two blocker fixes (M0-1..M0-5: IV/RV history migration RUN, Tool D schema v2 + truthful legacy render, RV determinism, unknown-vs-zero, finite validators)** | focused suites green per lane |
| **M0.5** ✅ | Requirements addendum · ARCHITECTURE exception text · payload spike measured (§12) · this v3 revision closing P1–P12 | remaining: code-level stubs land in M1a |
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
