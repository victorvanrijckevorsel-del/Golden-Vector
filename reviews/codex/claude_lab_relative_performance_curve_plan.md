# Plan — Lab "Relative Performance Curve" drill-down (+ GDXJ benchmark)

**Author:** Claude · **Date:** 2026-06-12 · **Branch:** `dev-vic` (on top of `main` 104e9a9)
**Status:** DRAFT for Codex review (no code written yet). Build happens after review, on the max model.

---

## 1. What Emanuel asked for

On the Lab's Conditional-Dial table (P(beat GDX) per ticker for a chosen gold
scenario), he wants to **click a ticker and see, on a chart, *which* weeks it
beat or lagged the benchmark over time** — a visual curve of relative
performance — so the 75.6%-style number can be checked by eye. He also wants
the **GDXJ** benchmark alongside GDX.

### Decisions locked with Emanuel (2026-06-12)

| # | Decision | Choice |
|---|----------|--------|
| D1 | What the curve plots | **Both, clearly labelled**: (a) the faithful forward-alpha dots that the table is literally made of, and (b) a familiar relative-strength line for overall feel. |
| D2 | Which weeks to show | **All weeks, with the gold-down (scenario) weeks highlighted** — full timeline as context, the counted weeks bolded. |
| D3 | GDXJ | **Same build**: add P(beat GDXJ) to the table + a GDX/GDXJ toggle on the drill-down. |
| D4 | Horizon | **PENDING Emanuel** — build multiple forward horizons (e.g. 13w / 26w / 52w) as *selectable lenses*, each honestly labelled with effective N + thin-history guard. Do **not** auto-pick a "winner" horizon by in-sample beat-rate (that is horizon-mining); judging which horizon actually *predicts* best is a Scorecard/validation job, out-of-sample, pre-registered. |

---

## 2. How the Lab data is actually shaped (load-bearing context)

From `golden_vector/lab/conditional_dial.py`:

- An **episode = one historical week `t`**. Its value is
  `alpha = stock_fwd_13w − benchmark_fwd_13w` (log returns over the **next 13
  weeks** from `t`). `beat = alpha > 0`. The week's **gold bucket** is gold's
  forward-13w simple return.
- A dial cell `(ticker, gold-bucket)` aggregates its episodes:
  `P(beat) = mean(beat)` (then EB-shrunk toward the pooled rate),
  `median_alpha`, `alpha_q10/q90`, Wilson interval on **effective N**
  (overlap-adjusted: 151 weeks ≈ 11.6 effective).
- Benchmark is **GDX only** today (`gdx_log_ret`, meta `benchmark:"GDX"`), but
  **GDXJ history is already loaded** in `build_and_save` and passed to
  `build_weekly_return_frame` — so the GDXJ benchmark column already exists in
  the weekly frame; the dial just doesn't use it yet.

**Three honesty facts the chart must respect** (these are the whole reason to
plan rather than just draw something):

1. **Forward + overlapping.** Adjacent dots share 12 of 13 weeks → the series
   is autocorrelated and looks smooth. Smoothness is overlap, not extra
   evidence. Effective N ≪ dot count; the page must say so.
2. **Conditional.** The table's % counts **only** the gold-down weeks. The
   chart must visually separate counted weeks from context weeks, or the user
   eyeballs the wrong population.
3. **Survivor-only / exploratory.** The dial is explicitly exploratory
   (no dead-miner records yet). Caveat carries onto the drill-down.

---

## 2b. The horizon question (13w vs longer) — and the trap in "which is best"

Emanuel asked: today we look 13 weeks forward — should we also look at longer
periods, and which is *best*? Two very different things hide in that word:

- **Multiple horizons as lenses = good and honest.** 13w (≈1 quarter), 26w
  (≈half year), 52w (≈1 year) each answer "did it beat the benchmark over the
  next N weeks." Showing them side by side, each clearly labelled, is just
  looking through different-length lenses. Useful.
- **"Pick the horizon that looks best" = horizon-mining = the exact backtest
  sin the Lab exists to avoid.** If we try many horizons and keep the one with
  the highest P(beat) or prettiest curve, we cherry-pick noise that won't
  repeat. Selecting a horizon must be **pre-registered and judged out of
  sample** (validation engine / Scorecard), never by eyeballing in-sample.

There is also a hard statistical cost to "longer": **longer horizon → far fewer
independent samples.** With ~158 weeks of history, effective (independent)
episodes are roughly `weeks / horizon`:

| Horizon | Raw episode weeks | ~Effective N | Read |
|---|---|---|---|
| 13w | ~150 | ~11–12 | Today's view; already thin. |
| 26w | ~150 | ~5–6 | Borderline; wider Wilson bands. |
| 52w | ~150 | ~2–3 | Below `MIN_EFFECTIVE_N` for most names → cells honestly say **insufficient history**. |

So "longer" buys a more decision-relevant holding period but spends almost all
of the evidence. The honest way to help Emanuel choose is **not** to crown a
winner — it is to show, per horizon, the **effective N and the Wilson-interval
width** next to the beat-rate, so he can trade off "matches the horizon I'd
actually hold" against "has enough data to trust." The "best" period is a
judgment between relevance and evidence; we surface both and let him pick.

If he later wants a formal "which horizon predicts best" verdict, that is a new
Scorecard experiment (out-of-sample, pre-registered, multiplicity-disclosed) —
a separate, bigger piece than this drill-down.

## 3. Simplest thing that could work (stated first, per our rules)

The minimum that satisfies the ask would be **one chart vs GDX**: the faithful
forward-alpha dots over all weeks, scenario weeks highlighted, zero line, the
table's number annotated. No GDXJ, no second line, no new page (inline expand).

Emanuel explicitly chose more than the minimum (D1 both charts, D3 GDXJ). So the
plan below is the agreed scope — but we keep each *piece* as simple as it can be
and reuse existing helpers everywhere.

---

## 4. Architecture (must obey the repo canon)

- **Backend computes, serve renders.** All per-week series, alpha, rebased
  relative-strength, and the beat/lag flags are computed in the **lab build**
  and **persisted**. The serve layer only filters by ticker/scenario/benchmark
  and formats SVG. Add the new serve module to the `test_all_serve_modules_
  avoid_unsanctioned_analytics_tokens` sweep.
- **Compute once → persist → serve reads.** Extend `build_and_save` to also
  write a per-episode artifact; the page reads the alias. No request-path math.
- **One copy of everything.** Reuse `forward_sum` / `reindex_contiguous_weeks`
  (already used by the dial), the SVG helpers in `serve/charts.py`
  (`_build_beta_history_svg` / line+scatter builders), `help_term` for
  caveats, and the existing per-name benchmark map if one exists (grep
  `option_signals` / hedge for GDX-vs-GDXJ assignment before writing any).
- **Pre-registration discipline.** Adding GDXJ as a benchmark is a NEW
  registered variant config (`conditional_dial_analog` with `benchmark:"GDXJ"`
  or a `_v2` signal_id) registered in the ledger **before** compute, raising
  n_trials. The episode-series persistence itself exposes already-computed
  numbers (no new statistical claim, no new gate).

---

## 5. Build steps

### Step 1 — Data: GDXJ alpha + persisted episode series (`lab/conditional_dial.py`)
- Generalize `_episode_frame` to compute alpha vs **each** available benchmark:
  add `alpha_gdxj` (and `beat_gdxj`) using `gdxj_log_ret` when present; keep
  `alpha_gdx`. Degrade per-benchmark: a ticker with no GDXJ history gets NA
  GDXJ columns, never an abort (fail-loud only if GDX, the required base,
  is missing).
- Build GDXJ dial cells too (same machinery, `benchmark` field on `DialCell`),
  register the GDXJ variant in the ledger before compute.
- **Persist a long-form episode artifact** `dial_episodes_13w_latest.parquet`
  (+ run-stamped immutable + `latest` alias, per the spine pattern). Columns:
  `ticker, week_period, week_date, gold_fwd_simple, gold_bucket,
  alpha_gdx, beat_gdx, alpha_gdxj, beat_gdxj,
  relstrength_gdx, relstrength_gdxj`.
  - `gold_bucket` is the assigned bucket per week (so serve can highlight the
    user's scenario without re-bucketing).
  - `relstrength_*` = cumulative **weekly (non-overlapping)** stock−benchmark
    log return, exp'd and rebased to 100 — the D1(b) line. Computed in the
    build, NOT serve. Clearly a *different* statistic from the forward-alpha
    dots (weekly, unconditional) — labelled as such.
- Meta json records: benchmarks present, horizon, bucket defs, variant hashes,
  input provenance (sha), survivor-only caveat.

### Step 2 — Serve data (`serve/lab_curve_data.py`, new)
- Read the episode artifact + dial cells via the model-state manifest/alias
  (explicit path, no `glob[0]`).
- `load_ticker_curve(ticker, *, scenario_bucket, benchmark)` → a render DTO:
  ordered weekly points (date, alpha, beat flag, is_scenario flag,
  relstrength), plus the matching dial cell (P shrunk/raw, median alpha,
  q10/q90, effective N, Wilson, history-OK flag). CORRUPT vs MISSING distinct.
- No arithmetic here beyond selecting/escaping; everything numeric is read
  straight from the artifact.

### Step 3 — Serve render (`serve/lab_curve_page.py`, new) + route
- A drill-down page `/lab/dial/<ticker>?scenario=<bucket>&benchmark=<GDX|GDXJ>`
  (scenario + benchmark in the URL so the view is shareable/stable).
- **Chart A (hero, faithful):** x = week, y = forward-13w alpha vs benchmark
  (%). All weeks faint; **scenario weeks bold/coloured**; zero line. Annotate:
  "<P>% of the highlighted dots are above zero" — and that this equals the
  table's raw P(beat). Caption: forward-looking, overlapping (effective N = …),
  conditional on the chosen gold scenario.
- **Chart B (context):** the relative-strength line (rebased 100), all weeks,
  labelled "overall vs <benchmark>, every week — not conditional on the gold
  scenario." Rising = beating lately.
- **GDX/GDXJ toggle** (two links swapping `benchmark`), reusing the
  gold-scenario dropdown styling. Reuse `serve/charts.py` SVG builders; do not
  fork chart code.
- `help_term` caveats for: effective N / overlap, conditional subset, GDXJ vs
  GDX meaning (juniors vs broad), survivor-only.

### Step 4 — Table wiring (`serve/` Lab dial table)
- Add a **P(beat GDXJ), shrunk** column next to P(beat GDX) (NA where no GDXJ
  history — degrades, sorts last; never blank-as-zero). Keep the single
  backend rank column (rank stays by the page's chosen benchmark; document it).
- Make each ticker link to the Step-3 drill-down carrying the **currently
  selected gold scenario** + benchmark.

### Step 5 — Tests (prove behaviour, can't pass by accident)
- **Consistency (the prize test):** for a sample ticker+scenario, the share of
  *highlighted* dots with alpha>0 in the artifact **equals** the dial cell's
  raw `p_beat` (within float tol). This is what makes "chart can't disagree
  with the table"真. Include a tie at exactly 0.
- **Episode parity:** rebuilding `alpha_gdx` for the latest period from raw
  inputs matches the persisted episode value (no forked math).
- **GDXJ degrade:** a ticker with GDX but no GDXJ history → GDXJ columns NA,
  GDX intact, build does not abort; a healthy control row stays full.
- **Highlight correctness:** only weeks whose `gold_bucket` == selected scenario
  are marked counted; determinism under row shuffle; NA/thin handled.
- **Serve guardrail:** new modules added to the no-arithmetic sweep; a static
  test that the page sorts on the backend rank only and renders no computed
  ratio.
- **Relative-strength is weekly/non-overlapping** (a unit test that it does not
  reuse the 13w forward window — guards the double-count trap).

---

## 6. Honesty / labelling requirements (non-negotiable)
- Every number on the page carries its basis: benchmark (GDX/GDXJ), horizon
  (13w forward), scenario bucket, effective N, survivor-only.
- The two charts are explicitly different statistics (conditional forward dots
  vs unconditional weekly line) — never implied to be the same.
- Degraded/missing GDXJ → explicit NA state, excluded from any ranking, not
  silently zero.

---

## 7. Open sub-decisions (my recommendation — Codex/Emanuel can override)
1. **Table: both P(beat) columns vs a single benchmark toggle.** Rec: show
   **both columns** (GDX and GDXJ) so juniors-vs-broad is visible at a glance;
   the *curve* gets the toggle. (Alt: one toggle swaps the whole page.)
2. **Rank basis when both benchmarks shown.** Rec: keep rank by **GDX** (the
   established base); GDXJ is context. Revisit if Emanuel wants juniors ranked
   on GDXJ.
3. **Drill-down location.** Rec: **dedicated page** (room for two charts +
   caveats) over inline expand.
4. **Highlight style.** Rec: bold/coloured dots for scenario weeks over shaded
   vertical bands (simpler SVG, reuses scatter builder).

---

## 8. Risks
- **Overlap double-count** in the relative-strength line → mitigated by using
  weekly non-overlapping returns for line B (test-guarded).
- **Multiplicity** from adding GDXJ → register the variant before compute;
  disclose n_trials bump. Dial stays exploratory (not a scorecard gate), so no
  confirmatory claim is implied.
- **Survivor-only** → caveat repeated on the drill-down; graduating to a
  confident claim still waits on the dead-miner registry (D2).
- **Artifact size** ~65 tickers × ~158 weeks × 2 benchmarks ≈ 20k rows — one
  small parquet, no concern.

---

## 9. Review asks for Codex
1. Is the **episode artifact** the right seam (compute-once/persist), or should
   the series already exist somewhere I can reuse instead of adding a writer?
2. Is the **consistency test** (highlighted-dots-above-zero == raw p_beat) the
   correct invariant, and is float tolerance the only gotcha?
3. Does adding **GDXJ** demand a fresh ledger variant (my read: yes), and is
   exploratory-status enough to avoid a scorecard gate?
4. Any **PIT/leak** subtlety I'm missing — the dots are forward returns shown at
   the episode's *start* week; is plotting them at `t` (not `t+13`) the honest
   choice, and should the x-axis note that each dot "looks forward 13 weeks"?
5. Anywhere this **forks existing logic** (benchmark assignment, rebasing,
   SVG) that I should reuse instead.
