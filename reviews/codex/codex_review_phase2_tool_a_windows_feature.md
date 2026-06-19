# Codex Review - Phase 2 Tool A 2Y/5Y Display Windows

Date: 2026-06-19

Verdict: **NEEDS CHANGES**

## Findings

| Severity | File:line | Finding | Evidence | Concrete fix |
|---|---:|---|---|---|
| P1 | `golden_vector/portfolio/reader.py:117`, `golden_vector/portfolio/benchmark_betas.py:45`, `golden_vector/portfolio/models.py:13` | The deferred benchmark-artifact rebuild does not degrade gracefully for the Portfolio page. The overview handles old `benchmark_betas` artifacts, but `load_portfolio_data()` now requires `down_beta_2y`, `up_beta_2y`, `down_beta_5y`, and `up_beta_5y` while `PORTFOLIO_SCHEMA_VERSION` remains `8`. Current local artifacts still use schema `8` and lack those columns, so `/portfolio` returns the stale-schema 503 path until portfolio artifacts are rebuilt. | Focused live check against the current workspace: `load_portfolio_data(ProjectPaths.discover())` raises `PortfolioStaleSchemaError: benchmark betas schema validation failed: missing columns: down_beta_2y, up_beta_2y, down_beta_5y, up_beta_5y`. The code changed the required column contract in `BENCHMARK_BETA_COLUMNS` but did not bump the schema comment/version in `portfolio/models.py`. | Either rebuild/publish portfolio benchmark artifacts as part of this milestone and bump `PORTFOLIO_SCHEMA_VERSION` to `9`, or make the benchmark-betas reader explicitly backfill missing display-only columns with `NA` when consuming old schema-8 artifacts. Add a route/reader regression test that an old benchmark artifact with only 6M/12M/3Y columns keeps `/portfolio` usable or intentionally fails with a versioned rebuild message. |
| P2 | `golden_vector/model/structural.py:418`, `golden_vector/model/structural.py:438`, `golden_vector/model/structural.py:768` | Display-window structural rows reuse a 3Y normalization-issue summary, so a 5Y display row can omit normalization issues that occurred inside its own 5Y regression window but outside the last 3 years. This does not leak into scoring because `pipeline.py` filters to scoring windows, but it weakens the structural parquet as an audit source for the new 5Y rows. | `compute_structural_window_metrics()` builds one `issue_summaries` list and passes `issue_summaries[position]` to every window row. `_summarize_normalization_issues_by_as_of()` hard-codes `_window_start_values(..., "3Y")`. With Phase 2, that same summary is written onto 5Y rows. | Build issue summaries per window id, for example `issue_summaries_by_window[window_id][position]`, and pass the matching summary to `_compute_vectorized_window_metric()`. Keep scoring behavior unchanged by continuing to consume only scoring-window rows in `_build_tool_a_outputs()`. |
| P2 | `tests/test_workspace_datatables.py:419` | The known-deferred overview fallback for old benchmark artifacts is not directly pinned. | `_benchmark_reference_rows()` has a branch that renders `GDX / GDXJ benchmark - n/a for the {window} window yet` when a non-empty old benchmark frame lacks selected-window columns, but the test only covers 12M/3Y success and empty-frame output. It does not assert the critical 2Y/5Y old-artifact fallback. | Add a test with an old benchmark frame containing 6M/12M/3Y columns only, call `_benchmark_reference_rows(df, "2Y")`, and assert the explicit `n/a for the 2Y window yet` footer appears. |

## Invariant Review

I did not find a remaining path where 2Y/5Y rows reach Tool A score, rank, confidence, eligibility, profile, or anchors.

- `golden_vector/model/pipeline.py` builds `scoring_frame` from `app_config.scoring.structural_windows` before medians, confidence, counts, eligibility, normalization summary, and anchor selection.
- `_window_value_map()` iterates `weight_map`, so core medians only consume 6M/12M/3Y keys.
- `compute_volatility_diagnostics()` and `choose_structural_anchor_window()` still select anchors through `anchor_window_preference()` (`12M`, `3Y`, `6M`).
- `ScoringConfig.display_windows_disjoint_from_scoring()` prevents config-level duplicate rows that would inflate counts.

## Weighted Median Footgun

I checked callers of the dict-style `golden_vector.model.structural.weighted_median()`.

- Pipeline calls are fed by `_window_value_map()`, which only emits weight-map keys.
- Lab reconstruction now filters `window_id in weight_map` before calling `weighted_median()`.
- Other `weighted_median` hits use the array-style common/lab primitive, not the dict helper with default weight `1.0`.

No additional unmapped-key leak found.

## Verification

Focused tests run:

```text
python -m pytest tests/test_tool_a_pipeline.py::test_display_windows_never_change_rank_or_scoring tests/test_lab_validation.py::test_reconstruct_cores_ignores_display_windows tests/test_structural.py::test_volatility_anchor_never_selects_a_display_window tests/test_windows.py tests/test_workspace_datatables.py::test_tool_a_benchmark_reference_rows_render_in_tfoot tests/test_portfolio_m1.py::test_portfolio_pipeline_writes_benchmark_betas_without_universe_pollution
```

Result: **11 passed**.

Additional live-artifact check:

```text
load_portfolio_data(ProjectPaths.discover())
```

Result: **fails** with missing 2Y/5Y benchmark-beta columns on the current `benchmark_betas_latest.parquet`.
