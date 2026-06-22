# Codex Review - Lab Tool Holistic

Verdict: READY WITH CHANGES

This is a read-only review of the Lab / predictive-validation area. I did not
change source code. Focus was architecture, data integrity, point-in-time
correctness, backend/serve separation, test fidelity, and whether the Lab is
solid enough to become product evidence rather than only an exploratory panel.

## Checks Run

- `python -m pytest tests/test_lab_foundations.py tests/test_lab_walk_forward.py tests/test_lab_experiments.py tests/test_lab_page.py tests/test_lab_validation.py -q -p no:cacheprovider`
  - Result: `60 passed in 63.46s`
- `ruff check ...`
  - Could not run: `ruff` is not installed in this Python environment.
- `python -m ruff check ...`
  - Could not run: no `ruff` module installed.

## Overall Assessment

The Lab is much stronger than the first draft: the page is mostly render-only,
the conditional-dial table is backend-computed and persisted, forward labels
are strict-forward, Newey-West fold accounting is now pinned, Tool A core
reconstruction reuses the product `weighted_median`, and the vintage recorder
now resolves through the model-state manifest for product artifacts.

The remaining problems are mostly not simple syntax bugs. They are foundation
risks: Lab validation still reads some inputs through globs / mutable latest
files, pre-registration is not enforced at every publishable execution boundary,
and some important tests can skip on clean machines. If this stays an
exploratory research panel, those are tolerable. If it becomes the Scorecard /
evidence layer for "this model is supported," they should be fixed first.

## Findings

### HIGH 1 - Validation inputs can bypass the coherent current-state manifest

Evidence:
- `golden_vector/lab/validation.py:794` builds Tool C reconstruction inputs directly.
- `golden_vector/lab/validation.py:808` reads `data/intermediate/tool_a_structural/*latest*.parquet` via glob.
- `golden_vector/lab/validation.py:813` reads the first raw gold parquet via glob.
- `golden_vector/lab/validation.py:978` repeats the direct `*latest*` structural-panel glob in `load_validation_inputs`.
- `golden_vector/lab/conditional_dial.py:238` reads raw gold directly by glob.
- `golden_vector/serve/lab_data.py:37` reads `data/lab/dial_table_13w_latest.parquet` directly.

Why it matters:
The Lab is supposed to validate the same coherent model state the product is
serving. Direct glob/latest reads can silently mix artifacts from different
refreshes or pick the wrong file after a failed/partial refresh. That creates a
dangerous failure mode: a validation result can look official while not
actually matching the product snapshot.

Concrete fix:
Add one shared Lab input resolver that resolves product inputs through the
current model-state manifest and records the exact artifact path, run id, and
hash in Lab metadata. Lab outputs should be run-stamped artifacts with a
convenience latest alias, the same pattern as the main data spine. The serve
reader can still read a latest alias for the optional page, but any publishable
Scorecard/result should point at an immutable Lab artifact and its input
manifest.

### HIGH 2 - Pre-registration exists, but execution is not always gated by it

Evidence:
- `golden_vector/lab/ledger.py:139` defines `require_registered`.
- `golden_vector/lab/beta_gap.py:8` states that the variant must be registered before `run_experiment` executes.
- `golden_vector/lab/beta_gap.py:161` exposes `run_experiment(panel_with_nowcast)` without requiring or checking a registered variant.
- `golden_vector/lab/validation.py:381`, `:609`, `:642`, `:729`, `:760` return experiment verdicts by signal id, but the functions themselves do not require ledger registration.

Why it matters:
Pre-registration is the whole discipline that keeps backtests honest. The ledger
helpers are good, but the admissibility rule is not enforced at every boundary
where a result can be computed and later treated as evidence.

Concrete fix:
Keep pure helpers for tests, but introduce publish/writer entry points such as
`run_registered_validation_experiment(...)` or `publish_validation_results(...)`
that require `require_registered(...)` before compute and persist the matching
variant hash into the output metadata. Tests should prove an unregistered
variant cannot be persisted or displayed as an admissible result.

### HIGH 3 - The contaminated leakage canary is not structurally tied to the publish guard

Evidence:
- `golden_vector/lab/validation.py:908` defines `time_reversal_ic_contrast`.
- `golden_vector/lab/validation.py:949` computes the contaminated IC as `spearman_ic(out, out)`.
- `golden_vector/lab/validation.py:953` appends contaminated values to a plain list.
- `golden_vector/lab/validation.py:956` returns `(honest_mean_ic, contaminated_mean_ic)` as floats.
- `golden_vector/lab/validation.py:960` defines `assert_publishable`, which only sees `ExperimentVerdict.contaminated`.
- `tests/test_lab_validation.py:250` tests the publish guard using a manually-created contaminated verdict, not the actual canary output.

Why it matters:
The canary proves the harness can detect leakage, but the contaminated run is
not represented as a contaminated result object. A future writer could log or
render the contaminated number without tripping `assert_publishable`.

Concrete fix:
Return a structured object from `time_reversal_ic_contrast` where the
contaminated leg is explicitly marked `contaminated=True`, or make the publisher
always execute the contrast internally and store it only in a quarantined
diagnostics field. Add a test that a contaminated contrast object cannot pass
the same publish path as real verdicts.

### MEDIUM 1 - Important parity tests can skip on clean machines

Evidence:
- `tests/test_lab_validation.py:316` tests Tool A reconstruction parity against local live artifacts.
- `tests/test_lab_validation.py:330` skips if local structural / Tool A artifacts are missing.
- `tests/test_lab_validation.py:374` tests Tool C reconstruction parity against local live artifacts.
- `tests/test_lab_validation.py:382` skips if local Tool C artifacts are missing.

Why it matters:
These are among the most important correctness tests, but on a fresh CI machine
or a reviewer workspace without artifacts, they do not protect the code. They
are useful smoke tests, not sufficient contract tests.

Concrete fix:
Keep the live-artifact parity tests as optional smoke tests, but add
fixture-backed parity tests with small, deterministic structural panels and
Tool C inputs. Also use the max/latest as-of period in live parity tests rather
than `iloc[0]`, because artifacts can contain mixed dates.

### MEDIUM 2 - Vintage append is atomic but not fully race-safe

Evidence:
- `golden_vector/lab/vintages.py:104` reads an existing vintage store.
- `golden_vector/lab/vintages.py:119` writes the combined frame atomically.
- `golden_vector/lab/vintages.py:154` avoids racing a live refresh owned by another process.

Why it matters:
The refresh-lock check is good, but two standalone vintage recorders can still
race each other. Because the store is read-modify-write and first-write-wins,
one process can drop rows written by the other. This is exactly the kind of
history we cannot honestly rebuild later.

Concrete fix:
Add a dedicated per-vintage-store lock, or implement an atomic compare/retry
loop around `_append_vintage`. Add a test that simulates two appenders and
proves both sets of rows survive.

### MEDIUM 3 - Corrupt Lab artifacts are hidden as "not built yet"

Evidence:
- `golden_vector/serve/lab_data.py:41` catches any parquet read exception and returns `LabDialData(available=False)`.

Why it matters:
For an optional research toy this is okay. For a decision-support Lab, corrupt
data should not look the same as missing data. Missing means "build it";
corrupt means "rebuild or investigate."

Concrete fix:
Return a distinct status, for example `available=False, error_status="CORRUPT_ARTIFACT"`,
and render a calm message: "Lab artifact is corrupt; rebuild the Lab artifact."
Keep the page friendly, but fail loud enough that data corruption is not hidden.

### MEDIUM 4 - Robustness cadence test does not exercise the actual grid function

Evidence:
- `tests/test_lab_validation.py:304` defines `test_robustness_slices_change_cadence_without_breaking`.
- The test creates `g52 = [g26[0]] + g26[2::2]` manually instead of calling `build_as_of_grid(panel, step=52)`.

Why it matters:
The implementation supports a `step` parameter in `build_as_of_grid`, but the
test does not prove that parameter works. A bug in the actual 52-week grid path
would pass.

Concrete fix:
Change or add a test that calls `build_as_of_grid(panel, step=52)` directly and
asserts the fold count/cadence is different from the 26-period grid.

### MEDIUM 5 - Ledger drift test does not cover E3/E3b

Evidence:
- `tests/test_lab_validation.py:346` defines `test_ledger_constants_match_registered_gates`.
- `tests/test_lab_validation.py:360` loads only `validation_e1a`, `validation_e1b`, and `validation_e2`.
- E3 and E3b are implemented at `golden_vector/lab/validation.py:717` and `:750`.

Why it matters:
E3/E3b are exactly the more complicated Tool C validation paths. Their gates,
directions, and baseline definitions should be pinned against the registered
ledger too.

Concrete fix:
Extend the ledger-drift test to include `validation_e3` and `validation_e3b`,
including direction, spread gate, baseline identity, and any registered
minimums.

### MEDIUM 6 - Some experiment APIs are under-typed and easy to misuse

Evidence:
- `golden_vector/lab/validation.py:438` defines `BaselineSpec`.
- `golden_vector/lab/validation.py:443` types `rank_fn` as `object`.
- `golden_vector/lab/validation.py:460` / `:461` also accept `rank_fn` and `outcome_fn` as `object`.

Why it matters:
These functions are sensitive because they define what gets ranked and what is
treated as the future outcome. Loose typing increases the chance of a silent
wrong experiment shape.

Concrete fix:
Use `Callable[[pd.Period], pd.Series]` for rank functions and
`Callable[[str, pd.Period, str | None], float | None]` for outcome functions.
Validate combinations explicitly: default rank path requires `panel`,
`rank_column`, and `weight_map`; default outcome path requires
`ticker_weekly`.

### NIT 1 - Lab CLI/report strings contain Unicode that can render badly on Windows

Evidence:
- `golden_vector/lab/validation.py:382` contains `Δ`.
- `golden_vector/lab/validation.py:623` contains `≥`.
- `golden_vector/lab/validation.py:967` contains an em dash.
- `reviews/codex/claude_program_a_results.md` currently displays mojibake such as `â€”` and `Î”` in this environment.

Why it matters:
The math is not wrong, but Emanuel works on Windows. If Lab verdicts are printed
or reviewed in a non-UTF-8 terminal, important text can become unreadable.

Concrete fix:
Prefer ASCII in CLI/review output, or force UTF-8 output where the Lab writes
reports. The website can still render proper symbols if needed.

## Strengths To Preserve

- `golden_vector/lab/forward_returns.py` correctly uses strict-forward labels
  and complete-window accounting.
- `golden_vector/lab/walk_forward.py` has clear purge/embargo logic and an
  explicit overlap assertion.
- `golden_vector/lab/conditional_dial.py` computes the analog table backend-side
  and stores a persisted artifact; `serve/overview_lab.py` mostly formats it.
- `golden_vector/lab/vintages.py` now avoids recording option data unless the
  manifest freshness status is `OK`, which is the right fail-closed shape.
- `golden_vector/lab/ledger.py` handles torn final lines defensively and keeps
  the ledger append discipline mostly intact.
- `golden_vector/lab/validation.py` now reuses the product `weighted_median`,
  eliminating a serious duplicated-math risk from the first draft.

## Suggested Fix Order

1. Add a manifest-backed Lab input resolver and run-stamped Lab artifact writer.
2. Add publish/writer gates that require a registered variant hash before any
   verdict becomes admissible.
3. Tie contaminated canaries into the same publish guard.
4. Replace skip-prone live parity tests with deterministic fixture parity tests;
   keep live parity as optional smoke.
5. Add a race guard for vintage append.
6. Tighten the remaining tests: real `step=52`, E3/E3b ledger drift, corrupt
   artifact status.

After those changes, the Lab can be treated as a credible foundation for the
Scorecard. Until then, I would label it as "research-grade / exploratory" rather
than "product-grade evidence."
