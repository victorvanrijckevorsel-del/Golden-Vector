# Codex Review - Program A Validation Engine Round 2

Verdict: READY WITH CHANGES

Scope reviewed first-hand:
- `reviews/codex/claude_request_validation_engine_review_round2.md`
- `reviews/codex/claude_program_a_validation_spec.md`
- `golden_vector/lab/validation.py`
- `tests/test_lab_validation.py`
- Shipped Tool C chain: `golden_vector/model/tool_c.py`,
  `golden_vector/model/pipeline.py`,
  `golden_vector/model/structural.py`,
  `golden_vector/features/gold_regime.py`,
  `golden_vector/features/relative_behavior.py`

I did not change source code. The registered gates are treated as binding; no
gate recommendation below should be implemented silently without Emanuel.

## Checks And Reproductions

- `python -m pytest tests/test_lab_validation.py -q -p no:cacheprovider`
  - Result: `21 passed in 127.06s`
- Reproduced latest Tool C parity independently:
  - Latest period: `2026-06-06/2026-06-12`
  - Live rows: `62`
  - Reconstructed rows: `62`
  - Common tickers: `62`
  - `tool_c_downside_score`: `54` non-null pairs, max absolute diff `0.0`
  - `tool_c_upside_score`: `54` non-null pairs, max absolute diff `0.0`
- Reproduced E3/E3b headline verdicts:
  - E3: `SUPPORTED`, `35` folds, mean directed IC `0.2230`, NW-t `8.58`,
    directional share `97.1%`, spread t `7.94`, median ceiling `0.078`
  - E3b: `SUPPORTED`, `36` folds, mean directed IC `0.1718`, NW-t `4.07`,
    directional share `80.6%`, spread t `4.09`, median ceiling `0.091`
- Fold autocorrelation / t-stat stress:
  - E3 IC lag-1 autocorr: `0.264`; E3b IC lag-1 autocorr: `0.354`
  - E3 IC t remains above gate under NW lag 2/3/4: `7.85 / 7.60 / 7.61`
  - E3b IC t remains above gate under NW lag 2/3/4: `3.77 / 3.68 / 3.73`
  - E3/E3b spread t also remains above gate under NW lag 4.
- Historical future-leak stress:
  - Deliberately rebuilding historical Tool C with an untruncated weekly frame
    changes historical scores materially. Example periods:
    - `2014-04-05/2014-04-11`: downside max diff `28.39`, upside max diff `34.38`
    - `2019-03-30/2019-04-05`: downside max diff `37.88`, upside max diff `38.18`
    - `2025-09-20/2025-09-26`: downside max diff `15.79`, upside max diff `9.82`
  - Conclusion: the current truncation is necessary and appears correct, but
    latest-only parity cannot catch a regression that removes it.
- Single-name dominance check for E3:
  - Base mean directed IC: `0.2230`, `35` folds, `61` tickers.
  - Largest leave-one-ticker-out change: removing `MUX` changes mean IC by
    `0.0160` to `0.2070`.
  - Conclusion: the E3 result does not appear to be carried by one or two names.

## Confirmed Correct / No Finding

### PIT truncation in `reconstruct_tool_c_scores_at`

Evidence:
- `golden_vector/lab/validation.py:863` slices the structural panel to
  `ctx.panel["week_period"] == t`.
- `golden_vector/lab/validation.py:890` truncates `weekly_returns` to
  `period <= t` before `build_gold_regime_frame` and
  `compute_relative_behavior_metrics`.
- `golden_vector/model/structural.py:910` passes the anchor `as_of_date` to
  `_trailing_volatility_window`.
- `golden_vector/model/structural.py:1029` uses `np.searchsorted(...,
  side="right")` and slices only the prior 52 rows.

Assessment:
The Tool C reconstruction path is PIT-safe as implemented. Feeding the full
`structural_weekly` frame into `compute_volatility_diagnostics` is safe because
the diagnostic code keys each ticker's trailing window to the Tool A anchor
`as_of_date`. The gold-regime and relative-behavior path also looks safe because
the weekly frame is explicitly truncated before those scanners run.

### E3 / E3b orientation

Evidence:
- `golden_vector/lab/validation.py:523` stores `ic = direction * ic_raw`.
- `golden_vector/lab/validation.py:528` stores `spread = direction * spread`.
- `golden_vector/lab/validation.py:578` computes `share` from directed ICs
  being positive.
- `golden_vector/lab/validation.py:717` sets E3 `direction=-1`.
- `golden_vector/lab/validation.py:750` leaves E3b at `direction=1`.
- `tests/test_lab_validation.py:415` tests the down-capture sign convention.
- `tests/test_lab_validation.py:430` tests that a raw negative IC becomes
  positive under E3's registered direction.

Assessment:
The sign is correct end-to-end. High Tool C downside score means more fragile;
future down-capture is better when higher; therefore a working downside score
has raw IC < 0 and directed IC > 0. E3b is the positive-direction mirror.

### Low ceiling / high t-stat pattern

Assessment:
This is uncomfortable but not, by itself, evidence of leakage. The median
split-half ceiling is low because the per-name forward down/up-capture outcome
is noisy. The supported result comes from consistent cross-sectional ordering
across many disjoint folds and tercile portfolios. My lag-stress and
leave-one-name-out checks did not overturn it. I would publish the caveat
prominently, but I do not see grounds to invalidate E3/E3b.

## Findings

### HIGH 1 - Time-reversal canary still does not satisfy the spec's contaminated-result contract

Evidence:
- Spec requires the time-reversal contrast to emit `contaminated=True` and for
  the Scorecard build to refuse it:
  `reviews/codex/claude_program_a_validation_spec.md:197`.
- `golden_vector/lab/validation.py:908` defines `time_reversal_ic_contrast`.
- `golden_vector/lab/validation.py:949` computes the contaminated IC as
  `spearman_ic(out, out)`.
- `golden_vector/lab/validation.py:953` appends contaminated ICs to a plain
  list.
- `golden_vector/lab/validation.py:956` returns only two floats.
- `golden_vector/lab/validation.py:960` defines `assert_publishable`, but it
  only sees `ExperimentVerdict.contaminated`.
- `tests/test_lab_validation.py:250` tests the publish guard with a manually
  constructed contaminated verdict, not the real time-reversal canary output.

Why this matters:
The numeric canary is good, but the contaminated leg is not structurally tied to
the publish guard. A future Scorecard writer could log or render the
contaminated metric as diagnostics without ever passing a contaminated verdict
through `assert_publishable`.

Concrete fix:
Return a structured canary result where the contaminated leg is explicitly
marked `contaminated=True`, or add a Scorecard/publisher wrapper that runs
`time_reversal_ic_contrast` and stores the contaminated side only in a
quarantined diagnostics field. Add a test that the actual contaminated canary
object cannot pass the publish path.

### MEDIUM 1 - Ledger drift guard still omits E3/E3b

Evidence:
- Review brief explicitly asks to confirm E3/E3b coverage:
  `reviews/codex/claude_request_validation_engine_review_round2.md:20`.
- `tests/test_lab_validation.py:346` defines
  `test_ledger_constants_match_registered_gates`.
- `tests/test_lab_validation.py:360` loads only `validation_e1a`,
  `validation_e1b`, and `validation_e2`.
- E3 and E3b are implemented at `golden_vector/lab/validation.py:717` and
  `golden_vector/lab/validation.py:750`.

Why this matters:
The gates are registered and binding. The more complex Tool C experiments are
exactly where post-hoc drift would be most damaging, but the guard currently
does not pin their registered direction, spread gate, baseline identity, or
other config fields.

Concrete fix:
Extend the ledger-drift test to load `validation_e3` and `validation_e3b` from
`data/lab/variant_ledger.jsonl` and assert at least:
- E3 direction is negative / registered as downside-fragility orientation.
- E3b direction is positive.
- E3/E3b use `spread_gate=0.0`.
- E3 baseline is `down_beta_core_only`.
- E3b baseline is `up_beta_core_only`.
- Any registered t/share thresholds match the implementation constants.

Do not change the registered gates silently; if the ledger and code disagree,
that is a product decision for Emanuel.

### MEDIUM 2 - Latest-period parity is real, but it does not exercise historical PIT truncation

Evidence:
- `tests/test_lab_validation.py:374` defines the Tool C reconstruction parity
  test.
- `tests/test_lab_validation.py:386` chooses the period from
  `live["as_of_date"].iloc[0]`.
- My reproduction at latest exactly matched live Tool C output: 54/54 non-null
  scores on both downside and upside, max diff `0.0`.
- My deliberate untruncated historical reconstruction changed historical
  scores materially, proving truncation matters at historical dates.

Why this matters:
At the latest period, full history and `<= t` history are effectively the same.
So latest parity can prove the call chain mirrors the product, but it cannot
prove the no-future boundary. A future regression that removes
`weekly_returns <= t` could still pass latest parity.

Concrete fix:
Add a future-injection canary: choose a historical period `t`, append extreme
future weekly rows after `t` to `ctx.weekly_returns`, and assert
`reconstruct_tool_c_scores_at(t, ctx)` is unchanged. This directly proves the
reconstruction ignores future weekly data. Also change the latest parity test
to choose `max(as_of_date)` rather than `iloc[0]`.

### MEDIUM 3 - Important parity tests can skip on clean machines

Evidence:
- `tests/test_lab_validation.py:316` tests Tool A parity against local live
  artifacts.
- `tests/test_lab_validation.py:330` skips if the local structural panel or
  Tool A artifact is missing.
- `tests/test_lab_validation.py:374` tests Tool C parity against local live
  artifacts.
- `tests/test_lab_validation.py:382` skips if the local Tool C artifact is
  missing.

Why this matters:
The parity tests are important, but they are not guaranteed CI contract tests.
On a clean machine without built artifacts, the most important no-forked-math
checks can disappear.

Concrete fix:
Keep the live-artifact parity tests as smoke tests, but add deterministic
fixture-backed parity tests for the Tool A core reconstruction and Tool C
score reconstruction. The fixture can be small; it only needs to prove the Lab
path calls the same scoring primitives and handles score eligibility/component
sinking the same way as the shipped path.

### MEDIUM 4 - Validation input loading still uses direct globs instead of a coherent input resolver

Evidence:
- `golden_vector/lab/validation.py:794` builds the Tool C reconstruction context.
- `golden_vector/lab/validation.py:808` reads
  `data/intermediate/tool_a_structural/*latest*.parquet` via glob.
- `golden_vector/lab/validation.py:813` reads the first raw gold parquet via
  glob.
- `golden_vector/lab/validation.py:971` defines `load_validation_inputs`.
- `golden_vector/lab/validation.py:978` repeats the structural `*latest*`
  glob.
- `golden_vector/lab/validation.py:985` repeats the first raw gold parquet
  glob.

Why this matters:
The implementation currently worked locally, but this is fragile for a
validation engine. It can accidentally mix a structural panel, raw gold file,
equity histories, and benchmarks from different refresh contexts. That is less
severe than a direct math leak, but it weakens provenance and reproducibility.

Concrete fix:
Create one shared validation input resolver that records exactly which product
artifacts and raw/intermediate inputs were used, preferably through the
current-state manifest where available. At minimum, write the selected paths,
file hashes, and run ids into the eventual Scorecard metadata.

### NIT 1 - E3 sign canary is good but not full end-to-end

Evidence:
- `tests/test_lab_validation.py:415` pins the sign of
  `forward_capture_vs_gdx`.
- `tests/test_lab_validation.py:430` pins `direction=-1` on a synthetic
  Spearman example.

Why this matters:
These tests cover the two critical pieces, but they do not run the full
`run_e3(...)` pipeline on a synthetic Tool C-like fixture where a fragile
ranking passes and a perverse ranking fails.

Concrete fix:
Optional: add a fixture-level E3 test with a simple injected `rank_fn` and
`outcome_fn` through `_validity_experiment` that proves the full gate plumbing
stores positive values for the correct negative-orientation case and negative
values for the perverse case. This is not a blocker because the existing tests
cover the sign components.

### NIT 2 - Low-ceiling/high-t diagnostics should be persisted with the result

Evidence:
- E3 reproduced with median ceiling `0.078` and NW-t `8.58`.
- E3b reproduced with median ceiling `0.091` and NW-t `4.07`.
- Additional stress checks showed the results survive NW lag 4 and are not
  single-name dominated.

Why this matters:
The result is credible, but a skeptical reader will ask the same question
Emanuel asked: how can a low-ceiling outcome still produce a strong verdict?
The answer is fold consistency plus portfolio aggregation. That explanation
should be backed by saved diagnostics, not just a review note.

Concrete fix:
When persistence lands, include non-gate diagnostics in the metadata:
fold IC lag-1 autocorrelation, optional NW-lag sensitivity, fold count, median
ceiling, and a short explanation that low per-name ceiling limits effect-size
interpretation but does not void the registered gates when they pass.

## Final Judgment

The E3/E3b Tool C reconstruction is directionally and technically sound. I do
not see a future leak in the implemented `reconstruct_tool_c_scores_at` path,
and I independently reproduced the exact latest Tool C parity. The low
split-half ceiling is a real caveat, but the additional stress checks support
Claude's interpretation: the signal is a weak/noisy per-name outcome that is
consistent enough across folds and tercile portfolios to pass the
pre-registered gates.

Before this becomes a published Scorecard, fix the guardrail gaps above:
contaminated-canary publish wiring, E3/E3b ledger drift coverage, a historical
future-injection PIT test, and less skippable parity tests. Those are not
reasons to reject the core engine, but they are worth closing before the result
is productized.
