# Codex Review - Lab Relative-Performance Curve Implementation

Verdict: READY-WITH-CHANGES

No BLOCKER or HIGH findings. The implementation is directionally sound and the fleet's prior HIGH fix is real. I found one MEDIUM issue in the stale-config guard that can let old artifacts remain "current" after a live horizon/benchmark change, plus two LOW cleanup/data-honesty issues.

Scope reviewed first-hand: `golden_vector/lab/conditional_dial.py`, `golden_vector/serve/lab_curve_data.py`, `golden_vector/serve/lab_curve_page.py`, `golden_vector/serve/overview_lab.py`, `golden_vector/serve/workspace.py`, and the lab curve tests. I also read the binding plan and Claude's verification response. No live data fetches were run.

Checks run:

- `python -m pytest tests/test_lab_curve.py tests/test_lab_page.py tests/test_lab_dial_panel_parity.py -q -p no:cacheprovider` -> 22 passed.
- `python -m pytest tests/test_lab_foundations.py tests/test_lab_walk_forward.py tests/test_lab_experiments.py tests/test_lab_validation.py tests/test_lab_scorecard.py -q -p no:cacheprovider` -> 65 passed.
- `python -m ruff check ...` could not run because `ruff` is not installed in this environment (`No module named ruff`).

## Findings

### MEDIUM - Live horizon/benchmark changes can miss the STALE guard

Files: `golden_vector/serve/lab_curve_data.py:123`, `golden_vector/serve/lab_curve_data.py:127`, `golden_vector/serve/lab_curve_data.py:135`, `golden_vector/serve/lab_curve_data.py:140`

`_config_is_current()` recomputes the expected hash using `configured_horizons(meta)` and `configured_benchmarks(meta)`. Those helpers prefer the artifact's own `meta["horizons_weeks"]` and `meta["benchmarks"]` when present. That means if the live app changes from `[13, 26, 52]` to `[13, 26, 52, 104]`, or adds a new benchmark, an old artifact can still hash against its own old horizon/benchmark list and be accepted as current.

I reproduced the split behavior directly:

- Changing live `DEFAULT_BUCKETS`, `MIN_EFFECTIVE_N`, or `EB_PRIOR_STRENGTH` correctly returned `STALE`.
- Changing live `DIAL_HORIZONS_WEEKS` while loading an artifact whose meta still said `[13]` returned `available=True`, `error_status=None`.
- Changing live `DIAL_BENCHMARKS` to add a benchmark while loading an artifact whose meta still said `["GDX", "GDXJ"]` also returned `available=True`, `error_status=None`.

That violates the shipped feature's intended current-artifact contract: current workspace readers should fail closed when the live dial configuration changes. The fix is to make the current-reader freshness check compare artifact horizons/benchmarks against the live `DIAL_HORIZONS_WEEKS` and `DIAL_BENCHMARKS`, and compute the expected hash from the live values. If an archived artifact viewer is ever needed, keep that as a separate path rather than weakening the workspace "current" loader.

### LOW - Relative-strength Chart B can silently disappear on artifact problems

Files: `golden_vector/serve/lab_curve_data.py:251`, `golden_vector/serve/lab_curve_data.py:267`

`load_ticker_curve()` checks the primary episode/meta path before rendering Chart A, but `_relstrength_points()` independently loads `dial_relstrength_latest.parquet` and returns `[]` if the frame is missing or fails its required-column check. The page then renders Chart B as empty/contextual rather than distinguishing "no relative-strength data for this ticker" from "the relstrength artifact is missing/stale/corrupt."

This is not a blocker because Chart B is explicitly a collapsed context chart and the product-critical P(beat) evidence is Chart A. Still, it is weaker than the rest of this feature's fail-loud posture. Add a `relstrength_status` or similar optional status to `LabCurveData`, validate the relstrength frame against the same current meta, and render a calm "relative-strength artifact unavailable; rebuild Lab artifacts" state when the artifact itself is bad.

### LOW - `build_and_save()` docstring advertises a legacy artifact that is no longer written

Files: `golden_vector/lab/conditional_dial.py:600`, `golden_vector/lab/conditional_dial.py:611`, `golden_vector/lab/conditional_dial.py:613`, `golden_vector/lab/conditional_dial.py:674`

The `build_and_save()` docstring says it writes `dial_table_13w_latest.parquet` as a legacy GDX-13w table. The actual writes are `dial_cells_latest.parquet`, `dial_episodes_latest.parquet`, and `dial_relstrength_latest.parquet`. I did not find a runtime dependency on the legacy file; this appears to be stale documentation only.

Fix: remove the legacy-table bullet from the docstring or explicitly restore the write if backward compatibility is still required. I would remove the docstring line unless a real consumer is found.

## Load-bearing claims re-verified

### HIGH fix: complete

Files: `golden_vector/serve/lab_curve_page.py:62`, `golden_vector/serve/lab_curve_page.py:124`, `golden_vector/lab/conditional_dial.py:506`

`_cell_field()` now maps the mixed column conventions explicitly: `p_beat_{benchmark}_shrunk` for probabilities and `{benchmark}_effective_n` for effective N. I rendered a real local drill-down using the current artifacts:

- `FNV` vs `GDX`, 13w: `gdx_effective_n=11.62`, `p_beat_gdx_shrunk=0.7563`; rendered headline included numeric effective N and shrunk probability.
- `FNV` vs `GDXJ`, 13w: `gdxj_effective_n=10.54`, `p_beat_gdxj_shrunk=0.7707`; rendered headline included numeric effective N and shrunk probability.

I did not find another read site assuming the old column naming convention.

### Consistency invariant: holds on the local artifacts

Files: `golden_vector/lab/conditional_dial.py:226`, `golden_vector/lab/conditional_dial.py:279`, `golden_vector/serve/lab_curve_data.py:229`

I checked the persisted local artifacts directly: `dial_cells_latest.parquet` had 960 rows and `dial_episodes_latest.parquet` had 318,974 rows. For every usable cell in the local artifact:

- GDX: 328 usable cells checked, 0 mismatches.
- GDXJ: 285 usable cells checked, 0 mismatches.

For each `(ticker, bucket, horizon, benchmark)`, the share of scenario-highlighted episodes with `alpha > 0` matched the persisted raw `p_beat` to the expected 1e-4 rounding. The beat rule is strict (`frame["beat"] = (frame["alpha"] > 0)`), so an exact zero alpha is a miss. The scenario highlight is keyed from `gold_bucket`, which is the same bucket used by `_dial_cells()`.

### Golden parity gate: real, not vacuous

Files: `tests/test_lab_dial_panel_parity.py`, `tests/fixtures/lab/dial_golden_13w.parquet`

The parity test compares a committed frozen fixture against the built GDX-13w output and asserts both schema and frame equality. It is not just checking that something exists. The fleet's noted gap is real - the golden fixture does not contain an insufficient-history row - but the insufficient-history behavior is covered separately by `test_dial_table_insufficient_history_carries_no_numbers`, so I do not see a missing gate here.

### PIT / leakage: no issue found

Files: `golden_vector/lab/conditional_dial.py:226`, `golden_vector/lab/conditional_dial.py:536`, `golden_vector/lab/conditional_dial.py:550`

The forward-alpha episodes reuse `build_forward_return_panel()` and plot the forward-N outcome at the start week. That is a hindsight label, not a predictive feature leaking into an earlier score. The page labels this as "forward alpha" evidence. `cumulative_rebased()` is a single shared helper, and the relstrength artifact is start-anchored/prefix-stable. GDXJ also uses its own effective week set; the live artifact showed different effective N for GDX and GDXJ on the same ticker, which confirms it is not reusing the GDX count.

One nuance: `build_relstrength_artifact()` starts at the first valid relative-return week and then rebases through the suffix. If there are interior missing weeks, pandas' cumulative sum behavior can bridge those gaps. That does not affect Chart A or the P(beat) claim, and Chart B is explicitly a different/context measure, so I would not block on it unless the relative-strength chart becomes decision-critical.

### Serve purity and reuse: acceptable

Files: `golden_vector/serve/lab_curve_page.py:124`, `golden_vector/serve/lab_curve_page.py:190`, `golden_vector/serve/overview_lab.py`

I did not find Wilson, empirical-Bayes shrinkage, rank, or dial-cell construction leaking into serve. The serve layer formats values and renders persisted fields. `_render_headline()` does count scenario points for the explanatory "counted weeks" line and reads persisted `beat` flags, but it does not recompute the persisted probability, shrinkage, Wilson interval, rank, or bucket membership. That is acceptable for rendering evidence text.

### Multiplicity and honesty: mostly good

Files: `golden_vector/lab/conditional_dial.py:600`, `golden_vector/lab/conditional_dial.py:429`

The build path registers variants before writing outputs, and `n_trials` comes from the ledger. In my local ledger, `n_trials` for `conditional_dial` was 10 rather than 6 because older 4w/8w variants are still recorded alongside the newly shipped 13/26/52w x GDX/GDXJ variants. That is the right behavior for an append-only ledger; plan/review prose should not assume the local total is exactly 6 once older variants exist.

The overview uses persisted rank and insufficient-history flags. I did not find fabricated numbers for insufficient cells.

## Agreement with the fleet

I agree with the fleet's main conclusion that the prior HIGH bug was fixed: GDXJ headlines now read the correct mixed-convention columns and render numeric values. I also agree that Chart B is a separate measure and should remain visually/verbally distinct from the forward-alpha evidence.

The main thing the fleet appears to have missed is the config-hash edge case for live horizon/benchmark drift. The guard works for bucket/floor/EB changes, but not for default horizon/benchmark changes because it hashes the artifact's stored horizon/benchmark list back against itself.
