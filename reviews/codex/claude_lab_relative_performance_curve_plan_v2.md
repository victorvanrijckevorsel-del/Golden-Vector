# Plan (REVISED) -- Lab "Relative Performance Curve" drill-down (+ GDXJ benchmark)

**Author:** Claude (lead) -- reconciled from 5 adversarial critiques + first-hand code/data check
**Date:** 2026-06-12 - **Branch:** `dev-vic` - **Status:** REVISED DRAFT for Codex review (no code yet).

---

## DECISIONS LOCKED (Emanuel, 2026-06-12) -- these OVERRIDE the recommendations below

Emanuel reviewed the measured horizon evidence and chose:

1. **HORIZON: wire 13w + 26w + 52w as selectable lenses** (overrides the panel's
   "13w only" recommendation in Section 3). **Honesty reconciliation (binding):** we
   NEVER fabricate a number for a thin cell. At 26w/52w the cells that fall below
   `MIN_EFFECTIVE_N` render the existing `insufficient_history` state -- a plain
   "not enough independent history to count" with the evidence meter -- so the user
   SEES the evidence collapse as the window stretches (which is the point of looking).
   Each longer-horizon view leads with a one-line banner explaining the emptiness so it
   never reads as a broken page. The measured table in Section 3 stays as the on-page
   explanation of WHY the longer views are mostly blank.
2. **SCOPE: build v1 + v2 + v3 in ONE go** (the staged order in Section 5 becomes the
   internal build/test sequence, but everything ships together).
3. **v3 relative-strength line: KEEP it**, last, behind the "different measure" header
   with the trust-the-top-chart bridge sentence (Section 5 v3 as written).
4. **RANKING: rank by GDX, GDXJ as a comparison column** (my recommendation, accepted).

**Multiplicity consequence (must be honored in the build):** the dial family is no longer
2 variants -- it is **2 benchmarks x 3 horizons = 6 registered variants** (GDX/GDXJ x
13/26/52w). Register ALL SIX in the ledger BEFORE compute; persist all six hashes in the
meta; disclose `n_trials = 6` for the (still exploratory) dial family, kept separate from
the `validation_*` family. Any "which horizon predicts best" verdict STILL routes to a
pre-registered out-of-sample Scorecard experiment -- the 26w/52w lenses are for SEEING the
data thin out, never for picking a winner by eyeballing.

**Artifact shape consequence:** the persisted episode artifact gains a `horizon_weeks`
column (long-form keyed by `ticker, horizon_weeks, benchmark, week`), and the dial-table /
serve loaders take `horizon_weeks` + `benchmark` as parameters. Everything else in the plan
holds.

---

## 0. What changed from the draft, and why (read this first)

I re-measured the draft's own claims on the local parquet (no live fetch) and read every
helper it names. Five things in the draft were wrong or over-scoped; all five critiques
converged on the same fixes:

1. **HORIZON: cut the 13/26/52w selector entirely (BLOCKER).** Measured on the real
   65-ticker universe: usable dial cells are 13w 180/325 (55%), 26w 148/323 (46%),
   **52w 0/312 (0%)**. In the exact bucket the user clicks (`gold_down`): 13w **54/65**
   tickers pass the effective-N floor, **26w 0/64, 52w 0/64**. A 26w/52w "lens" hands the
   user a table that is **entirely blank for their scenario** -- not a lens, a dead end.
   Ship **13w only**. (Section 3.)
2. **FORK: reuse `build_forward_return_panel`, do not widen `_episode_frame` (BLOCKER).**
   That panel already emits `fwd_alpha_gdx_{h}w` AND `fwd_alpha_gdxj_{h}w` for any horizon
   on the same `forward_sum`/`reindex_contiguous_weeks` machinery. Widening the dial's
   private fork would be a second copy of alpha math that can drift. (Section 5, Step 1.)
3. **BENCHMARK MAP lives in `features/weekly_returns.py::BENCHMARK_COLUMN_MAP`**, not in
   hedge/option_signals (I grepped -- nothing there). The draft sent the implementer to
   the wrong module. (Section 4.)
4. **PERSISTENCE: the lab lives OUTSIDE the model-state manifest.** Confirmed: the dial
   writes one atomic `dial_table_13w_latest.parquet` and `serve/lab_data.py` reads it by
   direct path. The draft's "run-stamped immutable + latest alias via the manifest" is the
   PRODUCT spine, not the lab. Match the sibling dial artifact exactly. (Section 4.)
5. **CHARTS: Chart A is a NEW builder, not pure reuse.** `serve/charts.py` has a
   gold-vs-stock regression scatter (no date axis, no highlight subset) and a beta-history
   polyline (no dots). Neither does dated dots with a highlighted subset. Be honest. (Step 3.)

Plus: GDXJ degrades **per-week not per-ticker** (GDXJ history starts 2009-11 vs GDX 2006-05
-- measured ~180 weeks shorter), so it carries its OWN effective-N and `insufficient_history`.

The strong parts of the draft are kept: the faithful forward-alpha dot chart, the
consistency invariant (highlighted dots above zero == raw p_beat), the three honesty facts,
plot-at-`t` with a forward caption, and pre-registration before compute.

---

## 1. What Emanuel asked for

On the Lab's Conditional-Dial table (P(beat GDX) per ticker for a chosen gold scenario),
click a ticker and see, on a chart, **which weeks it beat or lagged the benchmark** -- so
the 75.6%-style number can be checked by eye. Also: add the **GDXJ** benchmark.

---

## 2. How the Lab data is shaped (load-bearing context)

From `golden_vector/lab/conditional_dial.py` and `golden_vector/lab/forward_returns.py`:

- An **episode = one historical week `t`**. Value =
  `alpha = stock_fwd_13w - benchmark_fwd_13w` (log returns over weeks `t+1..t+13`).
  `beat = alpha > 0`. The week's **gold bucket** is gold's forward-13w simple return.
- A dial cell `(ticker, bucket)` aggregates episodes: raw `p_beat = mean(beat)`, then an
  EB-shrunk `p_beat_shrunk` (pulled toward the pooled per-ticker-mean rate, prior strength
  10), `median_alpha`, `alpha_q10/q90`, Wilson interval on **effective N**
  (`effective_n = n_weeks / horizon`, floor `MIN_EFFECTIVE_N = 8.0`). Below the floor the
  cell carries NO numbers (`insufficient_history=True`) -- a blank beats a hallucinated rate.
- The canonical forward-alpha producer is
  `forward_returns.build_forward_return_panel(weekly, horizons_weeks=[...])`, which already
  emits `fwd_log_ret_{h}w`, `fwd_alpha_gdx_{h}w`, `fwd_alpha_gdxj_{h}w` per `(ticker,week)`
  with strict complete-window NA discipline. The dial's `_episode_frame` is a narrower
  GDX-only fork of the same math.

**Three honesty facts the chart must respect:**
1. **Forward + overlapping.** Adjacent dots share 12 of 13 forward weeks -> autocorrelated,
   looks smooth. Smoothness is overlap, not evidence. Effective N << dot count.
2. **Conditional.** The table's % counts ONLY the scenario weeks. The chart must visually
   separate counted weeks from context weeks.
3. **Survivor-only / exploratory.** No dead-miner records yet -> beat-rates are upward
   biased. This caveat must be **bound into the headline string**, not a footnote.

A fourth, subtle one (PIT): the scenario highlight uses gold's FORWARD return to colour the
START week, so a highlighted week is "weeks where gold WENT ON to fall 5-15% over the next
13 weeks" -- a hindsight grouping the user chose, never a signal knowable at `t`.

---

## 3. THE HORIZON DECISION (settled honestly)

**Recommendation: ship 13w ONLY. Do not build a 13/26/52w selector. Cut draft item D4.**

### Why -- measured, not asserted
`effective_n = scenario_weeks / horizon`, floor 8.0. With ~3 years of weekly history:

| Horizon | Usable cells (all buckets) | gold_down tickers passing floor | Read |
|---|---|---|---|
| **13w** | 180/325 (55%) | **54/65** | Today's view. Thin but real. |
| 26w | 148/323 (46%) | **0/64** | Empty for the scenario the user clicks. |
| 52w | **0/312 (0%)** | **0/64** | Empty everywhere. Every cell = insufficient_history. |

Wilson interval width confirms collapse (FNV 0.32 -> 0.42 -> 0.62; AEM 0.49 -> 0.59 -> 0.72):
a 0.62-0.72-wide 95% band on a probability is no information. Offering 26w/52w would teach a
beginner that "the data exists but is blank," which is worse than not offering it.

### How relevance-vs-evidence is made visible (on the single 13w view)
Even at 13w the evidence is thin, so the page shows BOTH sides of the tradeoff next to every
beat-rate, driven off the SAME `MIN_EFFECTIVE_N=8.0` (no second hardcoded cutoff):
- **Effective N** with a plain-English band: `eff_n >= 8` -> "okay-ish (still thin)";
  `eff_n < 8` -> "too few -- number hidden". This is the evidence meter.
- **Wilson interval width** rendered next to the point estimate (the dial already persists
  `wilson_low/high`).
A single page sentence explains WHY 13w: "We judge over 13 weeks because ~3 years of weekly
history leaves only ~6 independent half-year episodes and ~2-3 yearly ones -- not enough to
count anything reliably. Whether a longer holding period actually predicts better is a
separate, out-of-sample experiment, not a dial you eyeball here."

### What "best period" means -- and what must NOT be eyeballed
"Best horizon" is NOT a single-horizon question and must NEVER be answered by comparing
in-sample beat-rates across horizons -- that is textbook horizon-mining (SKILL.md red flag,
validation spec pre-registration gate). Even the SET of highlighted weeks changes with
horizon (a "gold down 5-15% over 13w" week is often a different week than over 26w -- I
measured FNV scenario counts moving 151 -> 171 -> 133), so cross-horizon eyeballing is
doubly misleading. **If Emanuel ever wants a real "which horizon predicts best" verdict, it
is a new, separately pre-registered out-of-sample Scorecard experiment in the `validation_*`
family -- judged by the Scorecard, never chosen by looking at the dial.** Cutting D4 keeps
that boundary clean.

### Multiplicity effect of cutting D4
Dial family today = 1 registered variant (`conditional_dial_analog`, GDX, 13w; confirmed in
`data/lab/variant_ledger.jsonl`). Adding GDXJ (v2) makes it **2** (GDX-13w, GDXJ-13w). Had
D4 lived it would have been up to 6 (2 benchmarks x 3 horizons) -- a quiet 6x. The dial
family stays exploratory and stays separate from the `validation_*` family (m=5).

---

## 4. Architecture (repo canon -- corrected to match the tree)

- **Backend computes, serve renders.** All alpha/beat flags, the per-week gold bucket, the
  relative-strength series, effective N, and Wilson bands are computed in the LAB BUILD and
  persisted. Serve filters by `(ticker, scenario, benchmark)` and formats SVG. No
  request-path arithmetic.
- **Compute once -> persist -> serve reads.** Match the LAB precedent exactly (NOT the
  product spine): write `dial_episodes_13w_latest.parquet` via `write_parquet_atomic` into
  `lab_dir(paths)`; the new serve loader reads it by **direct path** (mirror
  `serve/lab_data.py`). Lab artifacts live OUTSIDE the model-state manifest (per
  `validation_spec` s6) -- do not claim manifest/alias/run-stamp resolution. If run-stamped
  immutability is ever wanted for lab research artifacts, that is a separate change to BOTH
  the dial-table AND the episode artifact together, not a one-off here.
- **One copy of everything (the load-bearing fixes):**
  - Reuse `forward_returns.build_forward_return_panel(weekly, horizons_weeks=[13])` for the
    alpha/beat columns. Do NOT generalize `_episode_frame`. Better: have
    `conditional_dial.build_dial_table` CONSUME the panel so the dial's `alpha_gdx` and the
    chart's `alpha_gdx` are literally the same computed column -- then the consistency test
    is guaranteed by construction.
  - Use `features.weekly_returns.BENCHMARK_COLUMN_MAP` (`{"GDX":"gdx_log_ret",
    "GDXJ":"gdxj_log_ret"}`) as the single `{benchmark -> column}` source, both in the
    builder and in the serve toggle's benchmark validation. (Do NOT grep hedge/option_signals
    -- that map is not there.)
  - Add ONE shared helper `cumulative_rebased(log_return_series, base=100.0) -> Series`
    (in `golden_vector/lab/`) for the relative-strength line; call it for both benchmarks.
    Do not write a fourth ad-hoc cumsum->exp->rebase.
- **Pre-registration discipline.** Loop `register_variant` over `[("GDX", cfg_gdx),
  ("GDXJ", cfg_gdxj)]` BEFORE compute; persist BOTH variant hashes in the meta json
  (`variant_hashes` list). The episode-series persistence itself exposes already-computed
  numbers -- no new statistical claim, no new gate. Disclose the dial family is now
  `n_trials = 2`, exploratory, distinct from `validation_*`.

---

## 5. Staged build order (each stage independently shippable + testable)

Resolves the simplest-design critic vs the user's full-scope picks. v1 is the MVP all five
critics endorse; v2 and v3 are clearly separable.

### v1 -- The faithful GDX dot chart (the core value; ships alone)

**Step 1.1 -- Episode artifact (`lab/conditional_dial.py`).**
- Refactor `build_dial_table` to obtain `alpha_gdx`/`beat_gdx` from
  `build_forward_return_panel(weekly, horizons_weeks=[13])` (left-merge the panel's
  `fwd_alpha_gdx_13w` onto the dial's own `gold_fwd_simple`/`gold_bucket` join). Retire the
  dial's private alpha math. `beat_gdx = fwd_alpha_gdx_13w > 0` computed once.
- Compute the per-week `gold_bucket` ONCE from `DEFAULT_BUCKETS` + `gold_fwd_simple` (the
  single normalize boundary) and use the SAME assignment for both the dial cells and the
  persisted per-week rows.
- Persist **one long-form** episode artifact `dial_episodes_13w_latest.parquet` via
  `write_parquet_atomic` into `lab_dir(paths)`. Columns:
  `ticker, week_period, week_date, gold_fwd_simple, gold_bucket, alpha_gdx, beat_gdx`.
  (GDXJ + relstrength columns are added in v2/v3; the long-form shape leaves room.)
- Meta json: benchmark(s) present, horizon=13, bucket defs, `variant_hashes`, input sha,
  survivor-only caveat.

**Step 1.2 -- Serve loader (`serve/lab_curve_data.py`, new).** Read the episode artifact +
the matching dial cell by direct path (mirror `lab_data.py`; CORRUPT vs MISSING distinct).
`load_ticker_curve(ticker, *, scenario_bucket)` -> render DTO: ordered weekly points
`(date, alpha, beat, is_scenario)` + the dial cell (`p_beat` raw AND shrunk, median alpha,
q10/q90, effective_n, wilson_low/high, insufficient_history). No arithmetic beyond select/escape.

**Step 1.3 -- Serve render (`serve/lab_curve_page.py`, new) + route.** v1 renders **inline**
on the existing Lab dial page (expand-on-click / detail section reusing `lab_data.py`'s
pattern) -- a dedicated route is deferred to v2 when a second chart/benchmark needs the room.
- **Chart A (hero):** NEW builder `_build_timeseries_dots_svg(dates, values, highlight_mask,
  zero_line=True)` in `serve/charts.py` (extract the date-axis `x_at` + zero-line core out of
  `_build_beta_history_svg` so the beta chart and this share it -- legitimate de-dup). x =
  episode start week; y = forward-13w alpha vs GDX (%). Context weeks faint; **scenario weeks
  bold/coloured**; zero line. Independent (non-overlapping) episodes drawn as larger markers,
  overlapping weeks fainter, so a green streak does not read as many wins.
- **Headline annotation (bind the qualifiers IN the string):**
  "`<P_raw>%` of scenario dots are above zero -- across **surviving miners only** (no
  delisted names), **exploratory**. Effective N = `<eff_n>` (thin)." Quote the RAW beat-rate
  here (it equals the dot share); show the SHRUNK number beside it labelled "ranked/smoothed".
- **Forward-window honesty (hard requirements, not a maybe):** (a) x-axis title reads
  literally "Episode start week (each dot = the NEXT 13 weeks of alpha vs GDX)"; (b) the last
  13 weeks carry NO dots and a visible "no forward window yet -- needs 13 more weeks" gutter
  (forward_sum returns NA there); (c) a faint shaded `t..t+13` span on the hovered/sample dot
  in the help popover so the forward window is SEEN once.
- **Scenario-highlight honesty:** legend/caption says verbatim "Highlighted = weeks where
  gold WENT ON to fall 5-15% over the FOLLOWING 13 weeks (a hindsight grouping you chose, not
  a signal available on that date)." Never label them bare "gold-down weeks."
- `help_term` caveats: effective N / overlap, conditional subset, survivor-only (beginner
  one-liner: "only miners still trading today are included; the losers are missing, so real
  beat-rates were probably lower -- exploratory").

**Step 1.4 -- v1 tests (prove behaviour):**
- **Consistency (the prize):** share of highlighted, non-NA, non-truncated dots with
  `alpha > 0` == the cell's RAW `p_beat` within float tol; include a deliberate `alpha == 0`
  tie (must count as a MISS, since `beat` is strictly `> 0`).
- **Episode parity vs the PANEL:** dial `p_beat` for a `(ticker, bucket)` reconstructed from
  `build_forward_return_panel` == persisted dial `p_beat` (proves no forked math).
- **Highlight correctness:** only weeks whose persisted `gold_bucket == scenario` are marked;
  the bucket on highlighted weeks is IDENTICAL to the bucket the dial counted (not just the
  count); determinism under row shuffle; NA/thin handled.
- **Forward-window render test:** x-axis label string contains "next 13 weeks"/"forward";
  a render test that the right-edge gutter renders and the trailing 13 weeks have no dot.
- **Survivor caveat render test:** the drill-down HTML contains the survivor-only string
  ADJACENT to the headline percentage (binds the qualifier to the number, not a meta field).
- **Serve guardrail:** clone the per-file pattern -- assert `lab_curve_data.py` /
  `lab_curve_page.py` contain none of `{".cumsum(", "np.exp(", "* 100", "forward_sum",
  "rolling("}` and DO call the loader (proves rebase/alpha math stayed in the build). Assert
  the page sorts only on the backend `rank_in_bucket`. (The global serve sweep auto-globs new
  modules -- no manual add needed.)

### v2 -- GDXJ benchmark (column in the table + toggle on the chart)

**Step 2.1 -- Data.** Add `alpha_gdxj`/`beat_gdxj` from the SAME panel
(`fwd_alpha_gdxj_13w`). **Degrade per-WEEK, not per-ticker:** define the GDXJ episode set on
`gdxj_log_ret`-non-null weeks INDEPENDENTLY (GDXJ starts 2009-11 vs GDX 2006-05, ~180 weeks
shorter), so each benchmark carries its OWN week set, effective N, Wilson band, and
`insufficient_history` flag. A week with GDX but no GDXJ -> `alpha_gdxj` NA (never abort;
fail-loud only if GDX, the required base, is missing). Build GDXJ dial cells (own `benchmark`
field). Register the GDXJ variant before compute (now `n_trials = 2`).

**Step 2.2 -- Table column.** Add a **P(beat GDXJ), shrunk** column next to P(beat GDX),
labelled with its shorter history window (from 2009-11) and its OWN effective N. NA where no
GDXJ history (degrades, sorts last, never blank-as-zero). **Keep the single backend rank
column ranked by GDX** (the established base); a header help-term states "GDXJ shown for
comparison; ranking follows GDX," with the sort caret only on GDX. The dial intentionally
shows both benchmarks as user-selectable LENSES -- document explicitly that it does NOT
consume the hedge tool's per-ticker `_benchmark_map` (that is single-peer assignment; this is
exploratory cross-benchmark comparison) so we don't introduce a second "benchmark for ticker
X" concept.

**Step 2.3 -- Chart toggle + dedicated route.** Promote to a dedicated page
`/lab/dial/<ticker>?scenario=<bucket>&benchmark=<GDX|GDXJ>` (now justified -- two benchmarks
need the room; scenario+benchmark in the URL = shareable). GDX/GDXJ toggle = two links
swapping `benchmark`, validated against `BENCHMARK_COLUMN_MAP` keys (reject `?benchmark=FOO`).
On the GDXJ view, show the **GDXJ-specific** eff_n and Wilson width, not the GDX one. Add two
`ColumnHelp`/`help_term` entries (absent today, confirmed): "GDX = the big broad miner ETF
(large established miners)"; "GDXJ = the junior ETF (smaller, more volatile miners that swing
harder both ways) -- beating GDXJ is easier in gold-up, harder in gold-down."

**Step 2.4 -- v2 tests.** GDXJ degrade is **partial not just total**: a ticker with GDX-era
weeks but only post-2009 GDXJ weeks must produce a SHORTER GDXJ episode set, a smaller GDXJ
effective N, and a GDXJ `p_beat` computed only over GDXJ-available highlighted weeks -- plus
a healthy control with full GDXJ history. Run the consistency test SEPARATELY per benchmark.
Toggle rejects an unknown benchmark key. Ledger has exactly two dial variants after build.

### v3 -- Relative-strength context line (deferrable; ship behind a clear header, or drop)

This is the lowest value-per-risk piece (a DIFFERENT statistic from the table number) and the
biggest "user eyeballs the wrong population" risk. Ship only if Emanuel still wants it after
using the dot chart.
- **Data:** `relstrength_gdx`/`relstrength_gdxj` = cumulative **weekly NON-OVERLAPPING**
  stock-minus-benchmark log return, exp'd and rebased to 100 via the shared
  `cumulative_rebased` helper, computed in the build. **Pin the rebase anchor to the FIRST
  common week of the pair (start = 100); forbid end-anchoring** (end-anchoring silently
  encodes the end state into every earlier point -- a cosmetic look-ahead). Persist with an
  explicit basis tag in the meta: "weekly non-overlapping, unconditional, rebased=100 at
  `<start date>`."
- **Render (Chart B, demoted/collapsed below Chart A):** captioned "Different measure: weekly
  relative strength, EVERY week, NOT the conditional forward number above -- shown for feel,
  not for counting." A bridge sentence between the charts: "they answer different questions;
  the top counts only your scenario, the bottom every week; trust the top here."
- **Tests:** assert `series[0] == 100`; assert the value at week k depends only on returns
  through week k (recompute on a truncated frame, require the prefix matches -- closes the
  end-anchor PIT hole); assert it never reuses the 13w forward window (guards the
  double-count). Render test that the "different measure" header string is present.

---

## 6. Honesty / labelling requirements (non-negotiable)
- Every number carries its basis: benchmark (GDX/GDXJ + its history-start), horizon (13w
  forward), scenario bucket, effective N, survivor-only.
- Survivor-only + exploratory are bound INTO the headline string, not a footnote, and
  render-tested adjacent to the number.
- Scenario highlight is described as a forward/hindsight grouping ("went on to ... over the
  following 13 weeks"), never as a knowable-at-`t` signal.
- Degraded/missing GDXJ -> explicit NA, excluded from ranking, never silently zero.
- The two charts (v3) are explicitly different statistics; never implied equal.

## 7. Risks
- **Overlap double-count** (v3 line) -> weekly non-overlapping returns + the non-overlap test.
- **Multiplicity** -> two dial variants registered before compute, both hashes in meta,
  disclosed `n_trials = 2`, exploratory (no scorecard gate), family separate from `validation_*`.
- **Survivor-only** -> bound-in caveat; a confident claim still waits on the dead-miner registry.
- **Artifact size** -> ~65 tickers x ~158 weeks x (1-2 benchmarks) ~ <25k rows, one small parquet.

## 8. Review asks for Codex
1. Confirm the dial should CONSUME `build_forward_return_panel` (not widen `_episode_frame`)
   and that the parity test should assert against the panel.
2. Confirm the lab-precedent persistence (single atomic `_latest`, direct-path read, outside
   the manifest) is correct vs any desire for run-stamped lab artifacts.
3. Confirm 13w-only is the right call given the measured 26w/52w emptiness, and that any
   horizon comparison is routed to a pre-registered `validation_*` experiment.
4. Confirm the per-WEEK GDXJ degrade (own eff_n / Wilson / insufficient_history) and the
   separate-per-benchmark consistency test.
5. Confirm the new chart builders are the right de-dup seam (shared date-axis/zero-line core
   pulled out of `_build_beta_history_svg`).