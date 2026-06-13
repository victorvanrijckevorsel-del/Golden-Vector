# Plan (v3, build-ready) -- Lab "Relative Performance Curve" drill-down (+ GDXJ, multi-horizon)

**Author:** Claude · **Date:** 2026-06-13 · **Branch:** `dev-vic` (on `main` 104e9a9)
**Supersedes:** plan_v2 (had a 3-horizon top block over a 13w-only body -- Codex BLOCKER-1).
**Status:** reconciled per `reviews/codex/codex_review_lab_curve_plan.md` (NEEDS-REWORK ->
this). All 12 Codex findings folded in (changelog s11). No code written yet.

---

## 1. Locked decisions (Emanuel, 2026-06-12) -- the whole plan obeys these

1. **Horizons:** wire **13w + 26w + 52w** as selectable lenses (13w default).
2. **Scope:** build everything in **one** shippable unit (internal order in s8, shipped
   together).
3. **Second chart:** KEEP the relative-strength line, last + collapsed + clearly labelled.
4. **Ranking:** rank by **GDX**; GDXJ is a comparison column with its OWN evidence.

**Binding honesty rule that makes #1 safe:** we NEVER fabricate a number for a thin cell.
Measured on the real 65-ticker parquet (Codex re-verified, numbers match):

| Horizon | Usable cells (all buckets) | `gold_down` tickers passing the eff-N floor |
|---|---|---|
| 13w | 180/325 (55%) | 54/65 |
| 26w | 148/323 (46%) | **0/64** |
| 52w | **0/312 (0%)** | **0/64** |

So 26w/52w are largely (52w entirely) below `MIN_EFFECTIVE_N = 8.0`. They render as an
explicit **Evidence-check** view (s6), never as a normal ranked table with hidden numbers.
This turns "which period is best" into something the user can SEE thin out -- honestly.

---

## 2. What this builds

Click a ticker in the Lab dial table -> a drill-down that shows, on a chart, **which weeks
that miner beat or lagged the benchmark**, for the user's chosen gold scenario, with a
GDX/GDXJ toggle and a 13/26/52w horizon selector. The headline % on the chart provably
equals the table's number (same persisted column). A collapsed second chart shows overall
relative strength for feel.

---

## 3. Data model (load-bearing; from `lab/conditional_dial.py` + `lab/forward_returns.py`)

- **Episode = one week `t`.** Value = `alpha = stock_fwd_Hw - benchmark_fwd_Hw` (log
  returns over `t+1..t+H`). `beat = alpha > 0`. The week's **gold bucket** = gold's forward
  H-week simple return mapped through `DEFAULT_BUCKETS`.
- **Dial cell `(ticker, bucket, horizon)`** aggregates its episodes: raw `p_beat`,
  EB-shrunk `p_beat_shrunk` (pooled prior, strength 10), `median_alpha`, `alpha_q10/q90`,
  Wilson interval on **effective N** (`effective_n = n_weeks / horizon`, floor 8.0). Below
  floor -> `insufficient_history=True`, NO numbers (blank beats a hallucinated rate).
- **Canonical alpha producer:** `forward_returns.build_forward_return_panel(weekly,
  horizons_weeks=[...])` already emits `fwd_alpha_gdx_{h}w` and `fwd_alpha_gdxj_{h}w`
  per `(ticker, week)`. The dial's private `_episode_frame` is a GDX-only fork of this.
  **Codex verified** the private GDX-13w alpha == panel `fwd_alpha_gdx_13w` exactly
  (58,433 rows, max abs diff 0.0) -> the refactor in Step 1 is output-preserving for alpha.

**Four honesty facts the chart must respect:**
1. **Forward + overlapping** -- adjacent dots share H-1 of H weeks; smoothness is overlap,
   not evidence; effective N << dot count.
2. **Conditional** -- the table % counts ONLY scenario weeks; the chart must separate
   counted vs context weeks.
3. **Survivor-only / exploratory** -- bound INTO the headline string, render-tested adjacent.
4. **Highlight is a hindsight grouping** -- the scenario colour uses gold's FORWARD return
   to mark the START week ("gold WENT ON to fall 5-15% over the following H weeks"), never a
   signal knowable at `t`.

---

## 4. Architecture (repo canon; corrected to the tree)

- **Backend computes / serve renders.** Every number (alpha, beat, per-week gold bucket,
  effective N, Wilson bands, marker class, relative-strength, display-ready percents) is
  computed in the lab build and persisted. Serve filters by `(ticker, scenario, horizon,
  benchmark)` and formats. No request-path arithmetic.
- **One copy of everything (the load-bearing reuses):**
  - `build_dial_table` **consumes** `build_forward_return_panel(weekly,
    horizons_weeks=[13,26,52])`; the dial's `alpha` and the chart's `alpha` are literally
    the same computed column. Retire `_episode_frame`'s private alpha math.
  - `features.weekly_returns.BENCHMARK_COLUMN_MAP` (`{"GDX":"gdx_log_ret",
    "GDXJ":"gdxj_log_ret"}`) is the single `{benchmark->column}` source -- in the builder
    AND in the serve toggle validation. (Confirmed NOT in hedge/option_signals.)
  - The per-week gold-bucket assignment (`_assign_bucket` over `DEFAULT_BUCKETS`) is
    computed ONCE and used for both the cells and the persisted episode rows -- never
    re-bucketed in serve.
  - ONE shared `cumulative_rebased(log_return_series, *, base=100.0)` helper in
    `golden_vector/lab/` for the v3 line, called per benchmark. No fourth ad-hoc rebase.
- **Compute once -> persist -> serve reads (LAB precedent, NOT the product spine).** The
  Lab lives OUTSIDE the model-state manifest (confirmed: `serve/lab_data.py:40` reads
  `lab_dir(paths)/FILENAME` by direct path). We mirror that with **two artifacts**:
  - `dial_episodes_latest.parquet` -- **long-form** chart detail, one row per
    `(ticker, horizon_weeks, benchmark, week_period)`.
  - `dial_cells_latest.parquet` -- **wide** overview, one row per
    `(ticker, bucket, horizon_weeks)`, GDX-ranked with GDXJ comparison + per-benchmark
    evidence fields.
  Both written via `write_parquet_atomic` into `lab_dir(paths)`; both read by direct path.
- **Stale-shape protection (Codex MED-4).** Each meta json carries `schema_version` and a
  `config_hash` (horizons + benchmarks + bucket defs). The loaders return **STALE/CORRUPT**
  (distinct from MISSING) if required columns or the configured horizons/benchmarks are
  absent -- failing loud without joining the product manifest.
- **Pre-registration (Codex BLOCKER-2).** Loop `register_variant` over the **6 exact
  configs** `{benchmark in [GDX,GDXJ]} x {horizon_weeks in [13,26,52]}` BEFORE compute;
  store `variant_hashes_by_benchmark_horizon` in meta; set the disclosed count from
  `n_trials(lab_dir, signal_id="conditional_dial_analog")` AFTER registration (read from the
  ledger, never hardcoded). Family stays exploratory, separate from `validation_*`.

---

## 5. Persisted artifact schemas (exact)

**`dial_episodes_latest.parquet`** (long-form; feeds both charts):
`ticker, horizon_weeks, benchmark, week_period, week_date, gold_fwd_simple, gold_bucket,
alpha, beat, is_nonoverlap_anchor, relstrength`
- `alpha`/`beat` = vs the row's `benchmark` at `horizon_weeks` (NA where that benchmark's
  forward window is incomplete -- e.g. GDXJ pre-2009).
- `is_nonoverlap_anchor` (Codex MED-1) = computed per `(ticker, horizon, benchmark)`: True on
  every Hth week so serve draws independent episodes larger WITHOUT inferring from position.
- `relstrength` (v3) = `cumulative_rebased` of weekly NON-overlapping `stock - benchmark`
  log return, anchored to the pair's first common week.

**`dial_cells_latest.parquet`** (wide; feeds the overview table):
`ticker, bucket, horizon_weeks, rank_in_bucket,`
`p_beat_gdx, p_beat_gdx_shrunk, median_alpha_gdx, alpha_q10_gdx, alpha_q90_gdx,
 gdx_n_weeks, gdx_effective_n, gdx_insufficient_history, gdx_wilson_low, gdx_wilson_high,`
`p_beat_gdxj, p_beat_gdxj_shrunk, median_alpha_gdxj, alpha_q10_gdxj, alpha_q90_gdxj,
 gdxj_n_weeks, gdxj_effective_n, gdxj_insufficient_history, gdxj_wilson_low, gdxj_wilson_high,`
`p_beat_gdx_pct, p_beat_gdxj_pct  (display-ready strings/values so serve never does *100)`
- `rank_in_bucket` is by **GDX** `p_beat_shrunk` (Codex HIGH-3 wide shape). GDXJ fields are
  comparison-only; each benchmark carries its OWN evidence (Codex MED-2), so a GDXJ
  probability is never shown beside a GDX effective N.
- Rows where a benchmark is `insufficient_history` carry NULL probabilities for that
  benchmark (degrade, sort last, never zero).

---

## 6. The 26w/52w empty-state contract (Codex HIGH-2) -- beginner-safe

13w is the default. 26w/52w are **Evidence-check** lenses:
- Selector labels carry availability: `13w`, `26w (gold-down: no usable cells)`,
  `52w (no usable cells)` -- derived from the persisted `insufficient_history` counts, not
  hardcoded.
- When EVERY cell in the selected `(bucket, horizon)` is insufficient, render a dedicated
  **explanation panel** instead of a sortable table: no rank column, no sorting, no
  "top names" language -- the measured evidence table (s1) shown beside it, plus the one
  sentence: "Over a longer window, ~3 years of weekly history leaves too few independent
  episodes to count anything reliably; this is why the dial judges over 13 weeks."
- Tests assert the 52w view renders no rank values and no sortable ranking (s8 Step 6).

---

## 7. Chart + table render requirements

**Chart A (hero, faithful):** NEW builder `_build_timeseries_dots_svg(dates, values,
highlight_mask, anchor_mask, zero_line=True)` in `serve/charts.py`. Honest de-dup: extract
the shared date-axis (`x_at`) + zero-line core out of `_build_beta_history_svg` so both
share it (Codex confirmed neither existing builder does dated dots with a highlight subset).
- x = episode start week; y = forward-H alpha vs the chosen benchmark (%). Context weeks
  faint; **scenario weeks bold/coloured**; `is_nonoverlap_anchor` weeks drawn larger; zero
  line.
- **Headline (qualifiers bound IN the string):** "`<p_beat_raw_pct>` of scenario dots are
  above zero -- surviving miners only (no delisted names), exploratory. Effective N =
  `<eff_n>` (thin)." Quote the RAW beat-rate (it equals the dot share); show the shrunk
  number beside it labelled "ranked/smoothed".
- **Forward-window honesty (hard):** x-axis title "Episode start week (each dot = the NEXT
  H weeks of alpha vs <benchmark>)"; the trailing H weeks carry no dots + a visible "no
  forward window yet" gutter; the help popover shades one sample `t..t+H` span so the window
  is seen once.
- **Highlight caption (verbatim):** "Highlighted = weeks where gold WENT ON to fall 5-15%
  over the FOLLOWING H weeks (a hindsight grouping you chose, not a signal available on that
  date)."

**Overview table:** GDX-ranked (single rank caret on GDX), with a P(beat GDXJ) comparison
column showing its own shorter-history evidence. `help_term` glossary entries (absent today,
confirmed): "GDX = broad/large miners"; "GDXJ = juniors -- smaller, swing harder; beating it
is easier in gold-up, harder in gold-down". Ticker links to
`/lab/dial/<ticker>?scenario=<bucket>&horizon=<13|26|52>&benchmark=<GDX|GDXJ>`.

**Chart B (v3, collapsed -- Codex MED-3):** relative-strength line, rendered UNDER a
collapsed "Different measure: overall relative strength" section, with the bridge sentence
"they answer different questions; the top counts only your scenario, the bottom every week;
trust the top here" visible BEFORE expansion. PIT-safe: first-common-week anchor, end-
anchoring forbidden, basis tag in meta.

---

## 8. Build order (internal; all ships together)

- **Step 1 -- Output-preserving refactor + parity gate (Codex HIGH-1).** Make
  `build_dial_table` consume `build_forward_return_panel`. BEFORE merging, add a
  **golden parity test**: build the current GDX-13w table via the old path and the new
  panel-backed path; assert equality on ALL public columns for ALL buckets --
  `p_beat_gdx, p_beat_gdx_shrunk, wilson_low/high, median_alpha, alpha_q10/q90,
  effective_n, insufficient_history, rank_in_bucket` (incl. rounding + NA handling). This
  is the gate that the refactor changed nothing shipped.
- **Step 2 -- Generic build across horizons x benchmarks.** Register the 6 variants;
  compute cells + episodes for `[13,26,52] x [GDX,GDXJ]`; persist the two artifacts (s5)
  with `schema_version` + `config_hash`. GDXJ degrades per-week (own week set / eff-N /
  Wilson / insufficient flag); fail loud only if GDX (the base) is missing.
- **Step 3 -- Serve loaders (`serve/lab_curve_data.py`, new).** Read both artifacts by
  direct path (mirror `lab_data.py`), params `(ticker, scenario, horizon, benchmark)`,
  STALE/CORRUPT vs MISSING. Validate `benchmark` against `BENCHMARK_COLUMN_MAP` keys and
  `horizon` against the configured set. No arithmetic beyond select/format.
- **Step 4 -- Overview wiring.** Migrate the existing Lab table loader to
  `dial_cells_latest.parquet` filtered to the selected horizon (default 13w), GDX-ranked +
  GDXJ comparison; horizon selector with availability labels; empty-state panel (s6).
- **Step 5 -- Drill-down page + charts.** `/lab/dial/<ticker>` route; Chart A; GDX/GDXJ
  toggle; Chart B collapsed.
- **Step 6 -- Tests (prove behaviour):**
  - **Golden parity gate** (Step 1) -- full GDX-13w old-vs-new equality.
  - **Consistency invariant, per (benchmark, horizon):** share of highlighted non-NA dots
    with `alpha > 0` == cell raw `p_beat`; a deliberate `alpha == 0` tie counts as a MISS
    (beat is strictly `> 0`).
  - **Episode parity vs panel:** dial `p_beat` reconstructed from
    `build_forward_return_panel` == persisted -- proves no forked math.
  - **Highlight correctness:** only weeks with persisted `gold_bucket == scenario` marked;
    the bucket on highlighted weeks IS the bucket the cell counted; determinism under
    shuffle; NA/thin handled.
  - **Empty-state:** 52w (and 26w gold-down) render the explanation panel, no rank values,
    no sortable ranking.
  - **GDXJ partial degrade:** a ticker with full GDX but only post-2009 GDXJ -> shorter
    GDXJ week set, smaller GDXJ eff-N, GDXJ `p_beat` over GDXJ-available weeks only; healthy
    control with full GDXJ history stays full.
  - **Marker persistence:** `is_nonoverlap_anchor` present + correct cadence; render maps it
    to marker size only (serve infers nothing).
  - **Forward-window render:** x-axis label contains "next H weeks"/"forward"; trailing H
    weeks have no dot + the gutter renders.
  - **Survivor caveat render:** the survivor-only string renders ADJACENT to the headline %.
  - **v3 rebase:** `series[0] == 100`; value at week k depends only on returns <= k (prefix
    stability on a truncated frame -- closes end-anchor look-ahead); never reuses the
    H-week forward window.
  - **Schema-stale:** loader returns STALE when a configured horizon/benchmark column is
    missing from the artifact.
  - **Ledger:** exactly 6 `conditional_dial_analog` variants after build; changing benchmark
    OR horizon changes the hash; disclosed count read from the ledger.
  - **Serve guardrail (Codex LOW-1):** assert the new serve modules contain none of
    `{"forward_sum", ".rolling(", ".cumsum(", "np.exp(", "build_forward_return_panel",
    "_assign_bucket"}` and no direct Wilson/effective-N calls; display percents come from
    the persisted `*_pct` fields (do NOT ban bare `* 100`). Page sorts only on
    `rank_in_bucket`.

---

## 9. Multiplicity & honesty
- Dial family goes 1 -> **6** registered variants (GDX/GDXJ x 13/26/52w), all hashes in
  meta, disclosed count **read from the ledger**, exploratory, separate from `validation_*`
  (m=5). The empty 52w variants are labelled evidence-collapse lenses, never useful rankings.
- "Which horizon predicts best" is NOT answerable by eyeballing in-sample beat-rates across
  horizons (horizon-mining; the highlighted-week SET even shifts with horizon). Any such
  verdict is a new, separately pre-registered OUT-OF-SAMPLE `validation_*` Scorecard
  experiment -- never read off this dial.

## 10. Risks + size
- Overlap double-count (v3 line) -> weekly non-overlapping returns + non-overlap test.
- Refactor drift -> the Step-1 golden parity gate.
- Stale artifact misuse -> schema_version + config_hash + STALE loader state.
- Survivor-only -> bound-in caveat; a confident claim still waits on the dead-miner registry.
- **Artifact size (Codex LOW-2):** upper bound ~`65 x 158 x 3 x 2` ~ 61k episode rows before
  NA drops (52w/ GDXJ-early drop many); still one small parquet each.

## 11. Changelog vs v2 (Codex findings -> resolution)
| Codex | Resolution |
|---|---|
| BLOCKER-1 (3-horizon top vs 13w body) | Whole plan rewritten generic across horizons; `*_13w_*`/`[13]`/`n_trials=2` purged. |
| BLOCKER-2 (multiplicity inconsistent) | 6 exact configs registered before compute; disclosed count read from ledger; hash test. |
| HIGH-1 (parity only spot-checked) | Step-1 golden gate over ALL public GDX-13w columns before refactor. |
| HIGH-2 (26w/52w empty-state) | s6 Evidence-check contract: availability labels, explanation panel, no rank/sort, tested. |
| HIGH-3 (table shape underspecified) | Two artifacts (s5): long-form episodes + wide GDX-ranked cells with GDXJ comparison. |
| MED-1 (marker computed in serve) | `is_nonoverlap_anchor` persisted; serve maps to size only. |
| MED-2 (benchmark evidence fields) | Separate `gdx_*` / `gdxj_*` evidence columns (s5). |
| MED-3 (v3 line attention) | Chart B collapsed by default + bridge sentence before expansion. |
| MED-4 (stale Lab shape) | `schema_version` + `config_hash`; loaders STALE/CORRUPT vs MISSING. |
| LOW-1 (guardrail too blunt) | Ban analytics primitives, not `* 100`; persist `*_pct`. |
| LOW-2 (size estimate) | Updated to ~61k upper bound. |

## 12. Ready-for-build check
All BLOCKER/HIGH findings resolved in-plan; Codex expected this to move to
READY-WITH-CHANGES. Suggest one short Codex confirm of THIS file (or proceed to build on
max). No registered gate was changed; the 6 variants are registered before any compute.
