# Codex Candidate Finder Progress

## 2026-06-03 - Batch 1, Checkpoint A

Pre-flight:
- Confirmed branch: `dev-vic`.
- Read `reviews/codex/claude_codex_candidate_finder_build_brief.md`.
- Read `reviews/codex/claude_candidate_finder_plan_v2.md`, including section 12 refinements.
- Baseline `python -m pytest -q` before edits -> 586 passed.
- Plan check: Batch 1 is feasible against the current codebase. `golden_vector.hedge.options_liquidity.is_usable_candidate()` already exists as the single usable-options primitive; Batch 2 will reuse it in the data layer.

Implemented:
- Added `config/candidate_finder.yaml` with the curated criterion registry, default top-N, missing-data threshold, and bearish/bullish presets.
- Registered `candidate_finder.yaml` in `EXPECTED_CONFIG_FILES`, so it is validated and hashed with the rest of app config.
- Added `CandidateFinderConfig` and related Pydantic models to `contracts/config_models.py`.
- Added shared `oriented_percentile()` in `features/percentile_ranks.py`.
- Routed the existing options IV percentile calculation through the shared percentile helper.
- Added pure `model/candidate_finder.py` scoring engine:
  - weighted oriented percentiles;
  - post-filter peer-pool assumption;
  - missing-data renormalization;
  - rank eligibility with low-coverage rows sorted beneath eligible rows;
  - top-N tally;
  - empty-selection and all-zero-weight guards;
  - `score_eligible=False` treats Tool A beta criteria as missing.

Self-review notes:
- One existing `rank(pct=True)` implementation remains only inside `oriented_percentile()`.
- No second usable-options definition was added; Batch 2 must call `is_usable_candidate()`.
- The `0.67` minimum coverage threshold is compared against a two-decimal coverage fraction, so 2 of 3 criteria counts as 0.67 and is eligible.
- No UI, route, CLI, data join, or live market-data call was added in Batch 1.
- No recommendation language was added; labels describe screens and fit, not prescriptions.

Checks:
- `python -m pytest tests/test_percentile_ranks.py tests/test_candidate_finder_scoring.py tests/test_candidate_finder_config.py tests/test_config_loading.py tests/test_latest_data.py tests/test_config_models.py -q` -> 86 passed.
- `python -m pytest tests/test_percentile_ranks.py tests/test_candidate_finder_scoring.py tests/test_candidate_finder_config.py tests/test_config_loading.py tests/test_latest_data.py tests/test_options_phase.py tests/test_option_trading_data.py tests/test_options_liquidity.py -q` -> 44 passed.
- `python -m compileall golden_vector/features/percentile_ranks.py golden_vector/model/candidate_finder.py` -> passed.
- `python -m pytest -q` -> 601 passed.
- `git diff --check` -> passed with only Windows line-ending warnings.
- `python -m ruff check golden_vector tests` -> not run; `ruff` is not installed in this Python environment.
- `python -m mypy golden_vector` -> not run; `mypy` is not installed in this Python environment.
- `python -m pyright golden_vector` -> not run; `pyright` is not installed in this Python environment.

Checkpoint A status: reached. Stop here before Batch 2.

## 2026-06-03 - Batch 1 self-review fixes

Reviewed:
- Re-read the pure scoring engine and tests with a focus on malformed future UI/CLI input.
- Rechecked that the shared percentile helper remains the only `rank(pct=True)` implementation.
- Rechecked that no second usable-options definition was added.

Fixes:
- Added scoring-engine guards for duplicate selected criteria, invalid direction strings, malformed weights, non-finite weights, and negative weights.
- Added regression tests for duplicate criteria and invalid direction/weight inputs.

Checks:
- `python -m pytest tests/test_candidate_finder_scoring.py tests/test_percentile_ranks.py tests/test_candidate_finder_config.py tests/test_config_loading.py tests/test_latest_data.py tests/test_options_phase.py tests/test_option_trading_data.py tests/test_options_liquidity.py -q` -> 46 passed.
- `python -m compileall golden_vector/model/candidate_finder.py` -> passed.
- `python -m pytest -q` -> 603 passed.
- `git diff --check` -> passed with only Windows line-ending warnings.

## 2026-06-03 - Batch 2, Checkpoint B

Implemented:
- Added `golden_vector/serve/candidate_finder_data.py`.
- The data layer now joins the active ticker universe to latest Tool A, Tool B, options features, and the manual screening company-input store.
- Added derived market-cap ratios with missing/zero-market-cap guards:
  - `debt_to_mktcap`
  - `ebitda_to_mktcap`
  - `revenue_to_mktcap`
  - `netincome_to_mktcap`
- Added side-aware `has_usable_put_candidate` and `has_usable_call_candidate` fields from the existing option-trading bucket slots. No second usability rule was added; slot candidates are populated only through the shared `is_usable_candidate()` path.
- Added source alignment metadata for Tool A, Tool B, options, and manual store hash/as-of. Mixed Tool A / Tool B / options refresh ids are surfaced as warnings.
- Added a composite in-process cache key using Tool A refresh ids, Tool B refresh ids, options refresh id, and manual store hash.
- Added the `candidate-finder` CLI command. It reads a YAML/JSON screen spec, filters the peer pool by options side, runs the pure scorer, writes ranked parquet output, and records a run summary.

Self-review fixes made in the same batch:
- Guarded derived-ratio calculation when Tool B or any numerator field is absent.
- Allowed `--out` to point outside the repo without failing while printing or writing run metadata.
- Made CLI run status `WARN` when any Candidate Finder screen warning exists, not only when refresh alignment is mixed.
- Added regression tests for missing sources and external output paths.

Checks:
- `python -m pytest tests/test_candidate_finder_data.py tests/test_candidate_finder_scoring.py tests/test_candidate_finder_config.py tests/test_percentile_ranks.py tests/test_config_loading.py tests/test_latest_data.py tests/test_options_phase.py tests/test_option_trading_data.py tests/test_options_liquidity.py tests/test_cli_refresh_and_status.py -q` -> 59 passed.
- `python -m compileall golden_vector/serve/candidate_finder_data.py golden_vector/cli.py` -> passed.
- `git diff --check -- golden_vector/serve/candidate_finder_data.py golden_vector/cli.py tests/test_candidate_finder_data.py` -> passed with only the existing Windows line-ending warning on `golden_vector/cli.py`.
- `python -m pytest -q` -> 609 passed.
- `python -m ruff check golden_vector tests` -> not run; `ruff` is not installed in this Python environment.
- `python -m mypy golden_vector` -> not run; `mypy` is not installed in this Python environment.
- `python -m pyright golden_vector` -> not run; `pyright` is not installed in this Python environment.

Real current-data sample:

```text
Candidate Finder ranked parquet written: C:\Users\Emanuel\AppData\Local\Temp\candidate_finder_bearish_put.parquet
Rows: 5; peer pool: 5; options side: puts.
Warnings:
- Mixed refreshes in Candidate Finder sources (Tool A: 20260424T140753Z-update-data-6175c3fb; Tool B: 20260424T140753Z-update-data-6175c3fb; Options: 20260601T135914Z-update-data-f555b2fe).
Preview:
 rank ticker     score  rank_eligible  present_criteria_count  selected_criteria_count  top_n_tally
    1    AEM 74.000000           True                       5                        5            5
    2    NEM 64.666667           True                       5                        5            5
    3    KGC 61.333333           True                       5                        5            5
    4     CG 52.500000           True                       4                        5            4
    5    PRU 47.500000           True                       4                        5            4
```

Checkpoint B status: reached. Stop here before Batch 3 UI/routes.

## 2026-06-04 - Checkpoint B review fixes

Reviewed:
- Merged Claude's Checkpoint B review with Codex's self-review.
- Rechecked the data/scoring boundary, source freshness behavior, screen-spec parsing, zero-weight semantics, and producer-consumer field contract before UI work.

Fixes:
- Corrupt Tool A / Tool B latest parquet files now surface explicit Candidate Finder warnings instead of being indistinguishable from missing files.
- Candidate Finder cache keys now include Tool A / Tool B latest-file hashes, so a corrupt or changed latest file cannot be hidden by an earlier cached empty load.
- Added malformed-spec warnings for unknown presets, invalid `options_side`, invalid `top_n`, and non-list `criteria`.
- Zero-weight criteria now mean disabled when at least one selected criterion has positive weight. All-zero screens still fall back to equal weighting to avoid an empty accidental screen.
- Added a manual-store freshness warning when the manual store was updated after the latest Tool B source run timestamp.
- Added a producer-consumer contract test that every configured Candidate Finder criterion source field exists in the joined frame.

Checks:
- `python -m pytest tests/test_candidate_finder_data.py tests/test_candidate_finder_scoring.py tests/test_candidate_finder_config.py tests/test_percentile_ranks.py -q` -> 29 passed.
- `python -m compileall golden_vector/serve/candidate_finder_data.py golden_vector/model/candidate_finder.py golden_vector/cli.py` -> passed.
- `git diff --check -- golden_vector/serve/candidate_finder_data.py golden_vector/model/candidate_finder.py tests/test_candidate_finder_data.py tests/test_candidate_finder_scoring.py` -> passed with only Windows line-ending warnings.
- `python -m pytest -q` -> 615 passed.
- `python -m ruff check golden_vector tests` -> not run; `ruff` is not installed in this Python environment.
- `python -m mypy golden_vector` -> not run; `mypy` is not installed in this Python environment.
- `python -m pyright golden_vector` -> not run; `pyright` is not installed in this Python environment.

Real current-data sample after fixes:

```text
Candidate Finder ranked parquet written: C:\Users\Emanuel\AppData\Local\Temp\candidate_finder_bearish_put_after_fixes.parquet
Rows: 5; peer pool: 5; options side: puts.
Warnings:
- Mixed refreshes in Candidate Finder sources (Tool A: 20260424T140753Z-update-data-6175c3fb; Tool B: 20260424T140753Z-update-data-6175c3fb; Options: 20260601T135914Z-update-data-f555b2fe).
Preview:
 rank ticker     score  rank_eligible  present_criteria_count  selected_criteria_count  top_n_tally
    1    AEM 74.000000           True                       5                        5            5
    2    NEM 64.666667           True                       5                        5            5
    3    KGC 61.333333           True                       5                        5            5
    4     CG 52.500000           True                       4                        5            4
    5    PRU 47.500000           True                       4                        5            4
```

Status: review fixes complete. Candidate Finder remains stopped before Batch 3 UI/routes.

## 2026-06-04 - Batch 3, Checkpoint C

Implemented:
- Added the `/candidate-finder` workspace route and top-nav tab.
- Added `golden_vector/serve/candidate_finder_page.py` as the server-rendered Candidate Finder UI.
- Added the default bearish-put and bullish-call preset lenses as URL-driven screen links.
- Added a custom screen builder with options-side toggle (`puts`, `calls`, `either`, `none`), per-criterion direction, weight, and top-N controls.
- Added View 1 per-criterion top-list cards and View 2 split ranking tables for eligible rows and low-coverage rows.
- Added the mixed-refresh warning banner and a Fit Score tooltip that explains the weighted-percentile score without treating it as a forecast.
- Added focused route/renderer regression tests for default preset rendering, custom query plumbing, route reachability, warning display, DataTables markup, and recommendation-language avoidance.

Self-review fixes made in the same batch:
- Corrected UI direction values to use the scorer contract (`high_good` / `low_good`) instead of display-only labels.
- Corrected the top-list renderer to use `CriterionTopEntry` objects from the scoring engine.
- Avoided false invalid-direction warnings when a manually-entered query omits optional direction or weight fields.
- Used the existing sortable numeric `<td data-order=...>` helper for Candidate Finder ranking table numeric columns.
- Kept empty ranking tables out of DataTables enhancement to avoid unsupported `colspan` rows in enhanced tables.
- Made the top navigation wrap so the new fifth tab stays reachable in the narrow in-app browser.

Checks:
- `python -m pytest tests/test_candidate_finder_page.py tests/test_candidate_finder_data.py tests/test_candidate_finder_scoring.py -q` -> 22 passed.
- `python -m pytest tests/test_candidate_finder_page.py tests/test_candidate_finder_data.py tests/test_candidate_finder_scoring.py tests/test_workspace_datatables.py -q` -> 49 passed.
- `python -m pytest tests/test_candidate_finder_page.py tests/test_workspace_datatables.py -q` -> 30 passed after the nav wrap fix.
- `python -m compileall golden_vector/serve/candidate_finder_page.py golden_vector/serve/workspace.py golden_vector/serve/page_shell.py` -> passed.
- `python -m pytest -q` -> 618 passed.
- `python -m ruff check golden_vector tests` -> not run; `ruff` is not installed in this Python environment.
- `python -m mypy golden_vector` -> not run; `mypy` is not installed in this Python environment.
- `python -m pyright golden_vector` -> not run; `pyright` is not installed in this Python environment.

Browser sample:
- Started a fresh workspace server on `http://127.0.0.1:8772` because port `8771` was already in use.
- Opened `http://127.0.0.1:8772/candidate-finder?preset=bearish_put`.
- Verified title, active bearish preset, mixed-refresh banner, View 1, View 2, Fit Score tooltip, and DataTables markup against current cached data.
- Verified the bullish-call preset and a custom `options_side=either` query also render with the expected selected controls.
- Sample screenshot saved to `reviews/codex/candidate_finder_checkpoint_c_sample.png`.

Checkpoint C status: reached. Stop here before any next batch.
