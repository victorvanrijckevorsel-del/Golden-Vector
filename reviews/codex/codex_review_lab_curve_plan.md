# Codex Review: Lab Relative Performance Curve Plan v2

Verdict: NEEDS-REWORK

I reviewed `reviews/codex/claude_lab_relative_performance_curve_plan_v2.md` per `reviews/codex/claude_request_lab_curve_plan_review.md`. I also read the original draft, Lab code, forward-return helpers, weekly benchmark map, Lab loader, predictive-model guidance, validation spec, and the local variant ledger.

The core idea is good and the measured claims are correct. The plan is not build-ready because the top "DECISIONS LOCKED" block requires a 3-horizon x 2-benchmark implementation, while much of the lower implementation section still describes a 13w-only / 2-variant build. That contradiction is large enough that two engineers would build different artifacts.

## First-Hand Verification

I re-measured against the local cached parquet only; no live fetch.

| Claim | Result | Evidence |
|---|---:|---|
| 13w usable cells | 180 / 325 | matches plan |
| 26w usable cells | 148 / 323 | matches plan |
| 52w usable cells | 0 / 312 | matches plan |
| 13w `gold_down` usable | 54 / 65 | matches plan |
| 26w `gold_down` usable | 0 / 64 | matches plan |
| 52w `gold_down` usable | 0 / 64 | matches plan |
| GDX first weekly return | 2006-05-27/2006-06-02 | matches plan direction |
| GDXJ first weekly return | 2009-11-14/2009-11-20 | about 181 weeks shorter |
| Current `conditional_dial_analog` variants | 1 | `data/lab/variant_ledger.jsonl:1` |

Code claims also verified:

- `build_forward_return_panel` already emits `fwd_alpha_gdx_{h}w` and `fwd_alpha_gdxj_{h}w` for arbitrary horizons: `golden_vector/lab/forward_returns.py:20-48`.
- The current dial's private `_episode_frame` is a GDX-only fork of the same alpha math: `golden_vector/lab/conditional_dial.py:161-181`.
- Existing GDX-13w private alpha matched `build_forward_return_panel(..., [13])` exactly in my local check: 58,433 compared rows, max absolute difference `0.0`.
- `BENCHMARK_COLUMN_MAP` lives in `golden_vector/features/weekly_returns.py:19-22`.
- Current Lab persistence is direct-path, outside the model-state manifest: `golden_vector/serve/lab_data.py:40` reads `lab_dir(paths) / DIAL_TABLE_FILENAME`; `golden_vector/lab/conditional_dial.py:207-208` defines fixed `dial_table_13w_*` names.

## Findings

### BLOCKER 1 - Locked 3-horizon scope conflicts with the 13w-only implementation steps

The plan's top block says Emanuel locked `13w + 26w + 52w` as selectable lenses and that artifacts must carry `horizon_weeks` (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:12-20`, `:35-37`). It also says the dial family is now 6 variants (`:27-30`).

But the lower architecture/build sections still repeatedly specify a 13w-only implementation:

- `dial_episodes_13w_latest.parquet` at `reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:173` and `:215`.
- `build_forward_return_panel(weekly, horizons_weeks=[13])` at `:180` and `:208-210`.
- v1 artifact columns omit `horizon_weeks` and `benchmark` at `:215-218`.
- v2 tests say the ledger has exactly two dial variants at `:305`.
- Section 6 says every number carries horizon "13w forward" at `:331-332`.
- Section 7 says multiplicity is two variants and `n_trials = 2` at `:340-343`.

This is not just stale prose. It changes artifact names, route parameters, loader signatures, ledger counts, tests, and labels.

Concrete fix: rewrite the build sections so they consistently implement the locked decision:

- generic `dial_episodes_latest.parquet` and `dial_cells_latest.parquet`, not `*_13w_*`;
- `horizons_weeks=[13, 26, 52]`;
- episode rows keyed by `ticker, horizon_weeks, benchmark, week_period`;
- table/cell rows keyed by `ticker, bucket, horizon_weeks`, ranked by GDX with GDXJ comparison fields;
- `/lab` and `/lab/dial/<ticker>` both take `horizon=13|26|52`;
- tests expect 6 registered variants, not 2.

### BLOCKER 2 - Multiplicity handling is internally inconsistent and should read from the ledger, not from a hardcoded number

The top says register all six variants and disclose `n_trials = 6` (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:27-30`). Later sections still say to register only GDX and GDXJ and disclose `n_trials = 2` (`:192-196`, `:280`, `:305`, `:342-343`).

The actual ledger is exact-config based: `register_variant` writes one variant hash per `signal_id + config` at `golden_vector/lab/ledger.py:46-88`, and `n_trials` counts loaded records at `golden_vector/lab/ledger.py:130-136`.

Concrete fix: register six exact configs before compute:

`(benchmark=GDX|GDXJ) x (horizon_weeks=13|26|52)`.

Then put `variant_hashes_by_benchmark_horizon` into meta and set `n_trials` from `n_trials(lab_dir, signal_id="conditional_dial_analog")` after registration. Add a test that all six are present and that changing benchmark or horizon changes the hash.

### HIGH 1 - The output-preserving refactor needs a full GDX-13w parity gate, not just a p_beat spot check

The plan correctly wants `build_dial_table` to consume `build_forward_return_panel` instead of keeping private alpha math (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:54-57`, `:207-214`). I verified this is feasible: current private GDX-13w alpha exactly matched the panel's `fwd_alpha_gdx_13w`.

But the requested contract is stronger: the shipped GDX-13w dial output must remain bit-for-bit identical. The plan's tests focus on p_beat reconstruction and chart/table consistency (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:253-261`). That does not pin the full existing table: EB prior, Wilson bounds, median alpha, q10/q90, insufficient-history flags, rank order, rounding, and NA handling could drift.

Concrete fix: before the refactor, create a fixture or local-golden comparison that builds the current GDX-13w table with the old path and the new panel-backed path, then asserts equality on all public columns for all buckets. This should include at least:

- `p_beat_gdx`
- `p_beat_gdx_shrunk`
- `wilson_low/high`
- `median_alpha`
- `alpha_q10/q90`
- `effective_n`
- `insufficient_history`
- `rank_in_bucket`

### HIGH 2 - The 26w/52w override needs a stronger beginner-safe empty-state contract

The plan says longer horizons will show `insufficient_history` and a banner explaining emptiness (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:12-20`). That is necessary but not sufficient.

Measured evidence: 52w has 0 usable cells overall; 26w has 0 usable cells for the `gold_down` bucket, which is likely the user's main downside scenario. A normal-looking selectable table with mostly hidden numbers can still make a beginner think "the tool is broken" or "52w is a valid comparable lens."

Concrete fix: keep 13w as default, but make 26w/52w explicitly "Evidence check" views:

- selector labels should include availability, e.g. `26w (gold-down: no usable cells)` and `52w (no usable cells)`;
- when all cells in the selected bucket are insufficient, render a dedicated explanation panel instead of a normal sortable table;
- no rank, no sorting, and no "top names" language when all rows are insufficient;
- show the measured evidence table beside the empty state;
- test that 52w renders no rank column values and no misleading sortable ranking.

This respects Emanuel's choice to expose the horizons while making the evidence collapse impossible to misread.

### HIGH 3 - The ranking/table shape is underspecified for "rank by GDX, show GDXJ as comparison"

The locked decision says ranking follows GDX and GDXJ is a comparison column (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:25`). The lower plan says GDXJ gets its own `benchmark` field and its own dial cells (`:274-280`), while also saying the table adds a GDXJ column beside GDX (`:282-286`).

Those are different shapes:

- long-form benchmark rows: one row per `(ticker, bucket, horizon, benchmark)`;
- wide comparison rows: one row per `(ticker, bucket, horizon)` with GDX and GDXJ fields.

The current table is one row per `(ticker, bucket)` and ranks by GDX at `golden_vector/lab/conditional_dial.py:148-157`. The current serve loader sorts that table by `rank_in_bucket` at `golden_vector/serve/lab_data.py:62`, and `overview_lab.py` renders hard-coded GDX columns at `golden_vector/serve/overview_lab.py:89-93` and `:125-126`.

Concrete fix: define two artifacts:

- `dial_episodes_latest.parquet`: long-form by benchmark for chart detail.
- `dial_cells_latest.parquet`: wide by ticker/bucket/horizon for overview, carrying GDX-ranked fields and GDXJ comparison/evidence fields.

If the plan instead wants a single long-form artifact, it must specify exactly how the GDX-ranked overview row is derived.

### MEDIUM 1 - The chart marker logic would push computation into serve unless persisted

The architecture says backend computes and serve renders (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:168-171`). Chart A asks for independent non-overlapping episodes to be drawn as larger markers (`:231-236`). But the proposed v1 episode columns do not include any `is_nonoverlap_anchor` or marker-class field (`:215-218`).

If serve infers marker class from row position or dates, that is UI-side computation.

Concrete fix: persist `is_nonoverlap_anchor` or `episode_overlap_group` in the episode artifact, computed per `(ticker, horizon_weeks, benchmark)`. Serve should only map the persisted boolean to marker size/opacity.

### MEDIUM 2 - GDXJ degradation is conceptually right, but the overview needs benchmark-specific evidence fields

The plan correctly says GDXJ must degrade per-week and carry its own effective N/Wilson/insufficient-history state (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:274-280`). The code supports independent GDX/GDXJ missingness through `BENCHMARK_COLUMN_MAP` and outer weekly benchmark joins in `golden_vector/features/weekly_returns.py:19-22` and `:82-110`.

But if the overview row shows GDX and GDXJ side by side, it needs explicit GDXJ evidence columns. Otherwise the page could show a GDXJ probability beside the GDX effective N, which would be wrong.

Concrete fix: persist and render separate evidence fields, e.g.:

- `gdx_n_weeks`, `gdx_effective_n`, `gdx_insufficient_history`, `gdx_wilson_low/high`;
- `gdxj_n_weeks`, `gdxj_effective_n`, `gdxj_insufficient_history`, `gdxj_wilson_low/high`.

### MEDIUM 3 - Relative-strength line is PIT-safe as described, but should default collapsed

The v3 line pins the rebase anchor to the first common week and forbids end-anchoring (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:312-318`). That closes the main look-ahead risk. It also correctly labels the line as a different measure (`:319-326`).

The remaining product risk is user attention: the lower chart is not the statistic behind the table. Since Emanuel locked "KEEP it", I would not remove it, but it should default collapsed or clearly secondary.

Concrete fix: render Chart A first and expanded. Render Chart B under a collapsed "Different measure: overall relative strength" section, with the "trust the top chart for the counted probability" bridge sentence visible before expansion.

### MEDIUM 4 - Direct-path Lab persistence is acceptable, but needs schema/config freshness protection

The plan is right that Lab artifacts live outside the model-state manifest and should mirror current Lab direct-path persistence (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:172-178`). Current code confirms this: `golden_vector/serve/lab_data.py:40` reads the direct Lab path, and `golden_vector/lab/conditional_dial.py:257-273` writes the current table/meta.

But adding horizon/benchmark parameters makes stale Lab artifacts easier to misuse. The current direct-path pattern has no manifest freshness protection.

Concrete fix: add a Lab artifact schema version and config hash to the meta. The loader should return CORRUPT/STALE if required columns or configured horizons/benchmarks are missing. This keeps Lab outside the model-state manifest while still failing loud on stale shape.

### LOW 1 - The serve guardrail token list is too blunt

The plan wants the serve guardrail to reject tokens including `* 100` (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:266-268`). That can false-positive on harmless display formatting. The important ban is on analytics primitives, not all multiplication.

Concrete fix: forbid `forward_sum`, `.rolling(`, `.cumsum(`, `np.exp(`, `build_forward_return_panel`, `_assign_bucket`, and direct Wilson/effective-N calls in serve. If `* 100` must be forbidden, persist display-ready percent values in the DTO and state that explicitly.

### LOW 2 - Artifact size estimate is stale after the 3-horizon override

The plan estimates roughly `<25k rows` from `65 tickers x 158 weeks x (1-2 benchmarks)` (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:345`). With 3 horizons and 2 benchmarks the upper bound is closer to `65 x 158 x 3 x 2`, about 61k rows before NA drops. Still small, but the plan should update the estimate.

## Answers To The Review Questions

1. Override honesty: showing 26w/52w can be honest, but only if those views are clearly "evidence collapse" views, not normal ranked tables. 52w especially needs a no-ranking empty-state contract.
2. Output-preserving refactor: feasible, but not guaranteed by the current test plan. Add full GDX-13w old-vs-new parity, not only p_beat checks.
3. Consistency invariant: yes, `share(highlighted non-NA alpha > 0) == raw p_beat` is the right invariant. Ties at exactly zero must be misses. Run it separately per benchmark and horizon.
4. PIT/leakage: plotting forward-N alpha at start week `t` is acceptable if captions are as explicit as planned. v3 rebase from first common week is PIT-safe enough; forbid end-anchoring and test prefix stability.
5. Multiplicity: six registered variants is the right handling if Emanuel wants all horizons. But the plan must actually register six and report the ledger-derived count. A completely empty 52w variant is allowed only if it is labelled as an evidence-collapse lens, not a useful ranking lens.
6. Forked logic: the plan correctly removes the alpha fork by using `build_forward_return_panel`, but it still risks forking gold-bucket/episode construction, marker-class logic, and percent formatting unless those are centralized/persisted.

## Final Recommendation

Do not code from this plan yet. The data measurements are correct and the architecture instincts are mostly right, but the plan needs one reconciliation pass:

1. Decide the artifact shape for 3 horizons x 2 benchmarks.
2. Replace all `*_13w_*`, `[13]`, `n_trials=2`, and "13w only" implementation language with the locked 6-variant design.
3. Add full GDX-13w parity before refactoring.
4. Define the 26w/52w empty-state/no-ranking behavior.
5. Persist chart marker/evidence fields so serve remains render-only.

After those changes I would expect this to move to READY-WITH-CHANGES rather than NEEDS-REWORK.
