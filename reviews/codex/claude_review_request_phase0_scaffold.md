# Claude Review Request: Phase 0 Scaffold

## Review Target

Review the Phase 0 scaffold work on branch `dev-vic` in read-only mode.

Primary files to review:

- `main.py`
- `requirements.txt`
- `README.md`
- `config/universe.yaml`
- `config/horizons.yaml`
- `config/qa.yaml`
- `config/scoring.yaml`
- `config/screening_params.yaml`
- `golden_vector/cli.py`
- `golden_vector/app/paths.py`
- `golden_vector/app/run_context.py`
- `golden_vector/app/logging.py`
- `golden_vector/app/config.py`
- `golden_vector/contracts/config_models.py`
- `golden_vector/contracts/data_models.py`
- `tests/test_paths.py`
- `tests/test_config_loading.py`
- `tests/test_config_models.py`
- `tests/test_run_context.py`

Cross-check against:

- `AGENTS.md`
- `CLAUDE.md`
- `reviews/codex/golden_vector_master_plan.md`
- `claude-python-rebuild-spec-gold-v1.md`
- `codex-full-briefing.md`

## Review Objective

Decide whether this Phase 0 scaffold is safe to build on for Phase 1 ingestion work.

Focus on:

- correctness of the CLI scaffold
- correctness of config loading and validation
- correctness of run metadata and audit logging
- whether the config contracts are strict enough for a config-driven pipeline
- whether the new tests actually protect the scaffold
- whether any hidden assumptions or silent failure paths remain

## Review Constraints

- Read only
- No code changes
- No silent assumptions
- Findings first, ordered by severity

## Required Checks

1. Look for anything in the scaffold that would make Phase 1 ingestion unsafe or misleading.
2. Look for weak config validation, especially cases where bad YAML could slip through silently.
3. Look for mismatches between the code scaffold and the master plan.
4. Look for runtime behavior that could misreport run status or hide missing setup.
5. Look for missing baseline tests that should exist before data-fetch code is added.
6. Look for any branch or workflow issues that conflict with repo rules.

## Output File

Write your findings to:

- `reviews/codex/claude_review_phase0_scaffold_findings.md`

## Output Format

Use this structure:

1. Findings
2. Residual risks
3. Final verdict: `READY`, `READY WITH MINOR CHANGES`, or `NOT READY`

Each finding should include:

- severity (`P0` to `P3`)
- short title
- exact file and line or section
- why it matters
- what should change
