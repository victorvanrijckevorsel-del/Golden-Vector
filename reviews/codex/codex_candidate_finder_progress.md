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
