# Review Request — Lab Relative-Performance Curve IMPLEMENTATION

**From:** Claude · **To:** Codex · **Date:** 2026-06-13
**Branch/commit:** shipped to `main` **78a9f58** (also on fresh `dev-vic`)
**Scope:** the built feature, not the plan (plan_v3 was already reviewed + reconciled).

## What shipped

Click a ticker in the `/lab` scenario table → `/lab/dial/<ticker>?scenario=&horizon=&benchmark=`
shows WHICH weeks a miner beat/lagged the benchmark over time. Adds GDXJ alongside GDX and a
13/26/52w look-ahead selector. The drill-down's Chart A (forward-alpha dots, scenario weeks
highlighted) is meant to be the literal evidence behind the table's P(beat) number; a collapsed
Chart B shows a relative-strength line as a "different measure."

This already passed a 4-lens adversarial fleet that found + fixed 1 HIGH and 5 MED
(see `reviews/codex/claude_lab_curve_verification_response.md`). **Do not trust that —
independently re-verify the load-bearing claims and find what the fleet missed.** You MAY run
python/pytest (read-only / synthetic; NO live data fetch).

## Files

- `golden_vector/lab/conditional_dial.py` — build_dial_table, _dial_cells, build_episode_frame,
  build_dial_cells_wide, _merge_benchmark_cells, build_episode_artifact, cumulative_rebased,
  build_relstrength_artifact, dial_config_hash, build_and_save.
- `golden_vector/serve/lab_curve_data.py` — loader (load_dial_cells, load_ticker_curve,
  _config_is_current).
- `golden_vector/serve/lab_curve_page.py` — drill-down render + SVG (_cell_field, _build_dots_svg).
- `golden_vector/serve/overview_lab.py` — table + empty-state.
- `golden_vector/serve/workspace.py` — /lab and /lab/dial routes.
- `tests/test_lab_curve.py`, `tests/test_lab_page.py`, `tests/test_lab_dial_panel_parity.py`.
- Binding spec: `reviews/codex/claude_lab_relative_performance_curve_plan_v3.md`.
- Fleet's fixes: `reviews/codex/claude_lab_curve_verification_response.md`.

## Binding rules (flag violations, don't silently change)

Backend computes / serve renders (NO arithmetic, counting, shrink, Wilson, rank in serve/);
one copy of every helper; fail loud on required data, degrade per-item on optional; every number
labelled with its basis; NEVER fabricate a thin cell (render insufficient_history); variants
registered before compute, n_trials from the ledger.

## Highest-value checks (verify first-hand)

1. **The HIGH fix is COMPLETE.** `_cell_field` now maps logical names to the mixed-convention
   columns (`p_beat_{b}_shrunk` vs `{b}_effective_n`). Re-render a drill-down for GDX AND GDXJ
   and confirm Effective N + shrunk % + (anywhere Wilson is shown) are NUMBERS, not `—`. Are
   there OTHER read sites (overview_lab.py, the SVG title, Chart B) that assume the wrong column
   name and silently blank/mislabel?
2. **Consistency invariant** — reproduce it yourself: for a usable (ticker, bucket, horizon,
   benchmark), share of highlighted episodes with alpha>0 == persisted raw p_beat (to 1e-4
   rounding); a tie at exactly 0 is a MISS (beat is strictly >0). Holds for BOTH benchmarks and
   all 3 horizons? Does the loader's `is_scenario` highlight mark exactly the weeks the cell
   counted (no off-by-one between gold_bucket and the bucket the cell aggregated)?
3. **Golden parity gate** — does `test_lab_dial_panel_parity` genuinely prove build_dial_table's
   GDX-13w output is unchanged, or can it pass vacuously? Is the fixture committed + frozen
   (regen only re-blesses)? The fleet noted the golden has no insufficient-history row — does
   that gap matter given `test_dial_table_insufficient_history_carries_no_numbers` covers it?
4. **config_hash STALE guard** — confirm a changed DEFAULT_BUCKETS threshold / MIN_EFFECTIVE_N /
   EB_PRIOR_STRENGTH (none of which bump schema_version) makes the loader return STALE. Any path
   where a genuinely-current artifact is falsely flagged STALE (e.g. meta horizons/benchmarks vs
   live constants drift)?
5. **PIT / leakage** — forward-N alpha plotted at start week t (no future leak into the week's
   value); relstrength is start-anchored + prefix-only (truncating future weeks can't change
   earlier points — run the check); GDXJ uses its OWN shorter week set + own effective N, never
   the ticker's GDX set; scenario highlight uses gold's FORWARD return (labelled hindsight).
6. **Serve purity + reuse** — any analytics primitive leaked into the 3 serve modules? Is the
   beat decision read from the persisted column (not re-derived)? Is availability read from meta
   (not aggregated in serve)? Does the dial reuse build_forward_return_panel + BENCHMARK_COLUMN_MAP
   (no forks), and is there exactly ONE cumulative_rebased?
7. **Multiplicity + honesty** — 6 variants registered before compute, n_trials read from the
   ledger; 26w/52w render the empty-state (no rank, no fabricated numbers); survivor-only is
   adjacent to the headline number; the two charts are unmistakably different measures.
8. **Anything new** — edge cases (a ticker with no GDXJ at all; an unknown ?benchmark= / bad
   ?horizon=; empty universe), determinism, dtype/NA in _merge_benchmark_cells, the SVG gutter
   math.

## How to report

Write findings to `reviews/codex/codex_review_lab_curve_impl.md` with severity
(BLOCKER/HIGH/MED/LOW), file:line, evidence (incl. numbers you reproduced), and a concrete fix.
Read first-hand; a direct fix+test for a non-gate bug is welcome, but flag anything touching a
registered variant/gate for Emanuel. End with a verdict (SOUND / READY-WITH-CHANGES /
NEEDS-REWORK) and note where you agree/disagree with the fleet's findings.
