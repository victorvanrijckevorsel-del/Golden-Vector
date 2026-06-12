# Lab first experiments — results record (2026-06-12)

Both experiments were sha256-registered in the variant ledger BEFORE compute
(`data/lab/variant_ledger.jsonl`, n_trials=2: `8dbc6c3b08fc`, `3dfa4c670c48`).
Artifacts: `data/lab/dial_table_13w_latest.parquet`,
`beta_gap_panel_latest.parquet`, `beta_gap_verdict_latest.json`.

## 1. Conditional Dial analog table (spine) — BUILT, sensible

13-week forward gold buckets (simple-return space), GDX-relative outcomes,
GDX-era only (post-2006-05; 59,216 ticker-weeks). 325 cells = 65 tickers × 5
buckets; **180 usable, 145 honest blanks** — both ±15%+ tail buckets have
ZERO usable cells (13w gold moves that big are too rare for ≥8 effective
episodes), and they say "insufficient history" instead of inventing a number.

Smell test passes hard: in `gold_down` (−15%..−5%), the most resilient name
is **FNV** (royalty model; raw P(beat GDX)=0.95 over 151 weeks, shrunk 0.75),
with PRU/CG next; the worst are the high-cost leveraged producers
**CDE/IAG/HMY/HOC.L** (raw ~0.27–0.31, median alpha ≈ −7..−9%). Exactly the
structure a domain expert would draw by hand — but now counted, with Wilson
intervals on episode-adjusted N and EB shrinkage toward the pooled rate.

## 2. Beta-gap nowcast (flagship) — GATE FAILED; the null ships

Pre-registered gate: beat BOTH persistence baselines on next-26w-beta MAE by
≥10%, t>3, in ≥70% of 39 walk-forward folds (26w test windows, 156w min
train, purge=26w; 56,104 scorable ticker-weeks, 65 tickers).

| Comparison | MAE improvement | t | fold win rate | gate |
|---|---|---|---|---|
| vs slow structural beta (156w, Tool A's) | **+0.72%** | 1.28 | 56% | **FAIL** |
| vs raw fast beta (26w EW) | +7.54% | 5.24 | 82% | partial |

**Verdict (binding, per pre-registration): the dial keeps Tool A's
structural betas.** No re-runs, no parameter search — a second variant would
need its own ledger entry and a multiplicity-adjusted bar.

What the failure teaches (this is the valuable part):
1. **Tool A's 156w structural beta is already near-optimal** for predicting
   next-26w realized beta on this universe. The "beta drift" signal adds
   ~0.7% — noise-level.
2. **Unshrunk fast betas would have made the dial WORSE** (the nowcast beats
   them by 7.5%, t=5.2). The James-Stein machinery mostly shrank the
   fast-slow gap to zero — correctly detecting that the gap is noise.
3. The cross-sectional JS factor frequently hit full shrinkage (nowcast ≡
   slow beta in many folds), which is why the vs-slow improvement is small
   and positive rather than negative: the shrinkage knew when to do nothing.

## Caveats carried on both results

- Survivor-only universe (today's 65 names with full histories) — results are
  exploratory under decision D2's labeling; no dead-miner records yet.
- Overlapping weekly episodes: all intervals/t-stats use episode-adjusted N
  (weeks ÷ horizon), raw N shown alongside.
- Dial table is GDX-era only; deeper US-only history is possible later.
- Weekly W-FRI grid throughout; "13w" ≈ one quarter, not exactly 60 trading
  days — labeled as such.

## Follow-ups

- ~~Serve surface for the dial table~~ **DONE 2026-06-12: `/lab` workspace
  page.** Backend emits `rank_in_bucket` (one rank column), `bucket_label`,
  and alphas converted to simple relative outperformance (exp−1, exact for
  medians/quantiles) at artifact build time; `serve/lab_data.py` +
  `serve/overview_lab.py` are render-only (static-scan guardrail test
  enforces it, cloned from the Tool-D pattern); insufficient-history rows
  render with NO numbers; survivor-only caveat + episode-adjusted-N note in
  the page banner; `python -m golden_vector.lab.conditional_dial` rebuilds
  the artifact + provenance meta.
- Optional next registered experiment: per-regime (up vs down) beta split,
  ONLY if Emanuel wants it — the ledger bar rises with each trial.
- Dead-miner registry (D2) before any confirmatory claims.

## Vintage backfill record — 2026-06-12

One-time backfill from published run-stamped snapshots (newest file per
as_of_date; every source file verified present in a historical model-state
manifest, so each was the legitimately published state for its date —
PIT-correct; v2 option fields recorded as they were then):

- option_signal_summary: +6,886 rows (as-of 06-08, 06-09, 06-11)
- tool_b: +17,534 rows (8 dates back to 2026-04-22; April generations carry
  the sparser old field set — research reads select by field name)
- tool_d: +11,723 rows (06-05 → 06-11)
- option_trading_overview: nothing recoverable (stamped copies pruned)

Caveat noted: a backfilled vintage_date equals the artifact's as_of_date,
which can precede its publish timestamp by a few hours (e.g. tool_b
generated 06-12 05:13 carries as_of 06-11). Immaterial at weekly research
granularity; flagged for honesty. `recorded_at_utc` carries a "(backfill)"
suffix so backfilled rows are distinguishable from live captures forever.
