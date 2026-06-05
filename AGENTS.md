# Codex working rules for this repo

## About the user
Emanuel is a beginner founder. Explain decisions in plain English, avoid jargon. He learns fast but prefers understanding WHY before jumping into implementation. He values low-interruption execution — do the work, show results, don't over-ask. He expects structured output (tables, summaries, test results). Git user is Victor Van Rijckevorsel.

## Execution mode
Use low-interruption execution mode. Work continuously — do NOT ask for permission on every file change. Just do the work and show results.

## Pre-approved actions — do ALL of these without asking
All of the following are approved without prompting. Never ask for confirmation on these:

### File operations
- Create, read, edit, and delete any source code file (`.py`, `.yaml`, `.yml`, `.json`, `.toml`, `.cfg`, `.txt`, `.md`)
- Create new directories anywhere in the repo
- Read/inspect data files (CSV, Parquet, Excel)
- `ls`, `mkdir`, `rm` for temp files

### Dev workflow
- Run Python scripts (`python main.py`, `python -m pytest`)
- Run type checks (`mypy`, `pyright`)
- Run linting (`ruff`, `flake8`)
- Activate/use virtual environment
- Install packages listed in `requirements.txt`

### Git (on feature branch only)
- `git status`, `git diff`, `git log`, `git branch`, `git show`, `git checkout -b`
- `git add`, `git commit`, `git push`

### General rule
- Any read-only or non-destructive bash command is pre-approved
- Creating or editing source code files is pre-approved — do not ask for each file
- If a change is obviously correct, safe, and improves the code — proceed directly

Batch related safe commands into one block per step.

## Ask before risky actions ONLY
Only ask for confirmation on these specific actions:
- Deleting data files or outputs
- `git reset --hard`, force-push, rebase
- Changes outside this repo
- Secrets/API key config changes
- Installing new dependencies NOT in requirements.txt
- Any action that calls external paid APIs (e.g., fetching live market data)

Everything else: just do it.

## Workflow
1. Brief plan
2. Execute — create files, write code, run tests. Do not pause between files to ask.
3. Brief result + next step

## Git merge workflow (follow every time, automatically)
When a milestone is ready to ship:
1. Commit and push to `dev-vic`
2. Switch to `main`, pull latest, merge `dev-vic` into `main`
3. Push `main` to GitHub
4. Delete remote `dev-vic` branch (`git push origin --delete dev-vic`)
5. Switch back to `dev-vic` (recreate from `main`) to continue working
Do this automatically at each milestone — no need to ask.

## Fix bugs immediately
When a bug or code smell is identified, fix it now unless there's a concrete reason to defer. "It works for now" is NOT a valid reason to defer.

## Code cleanliness / avoid duplication
Be ruthless about duplicated code and duplicated logic.

- Before adding any helper or logic block, search the codebase for an existing implementation and reuse it. Common suspects include numeric coercion (`_optional_float`, `_numeric`, `as_float`), file hashing (`_sha256_file`, `_file_sha256`), parquet-read-with-fallback helpers (`read_optional_parquet`), `_unique_strings`, `_repo_relative`, ticker normalization (`.upper().strip()`), atomic temp-file-to-replace writes, status-combining, and run-id/freshness reconciliation.
- Put genuinely shared, generic utilities in one common location, such as `golden_vector/common/`, instead of re-growing the same helper in each new module.
- In plans, name the existing shared primitives the new work will reuse, such as `oriented_percentile`, the atomic-write helper, and the alignment function. Never plan a second implementation of something that exists; extend or generalize the existing one.
- Treat duplicated logic as a correctness problem, not just tidiness. When the same idea, such as "is everything aligned/fresh?" or "is this score-eligible?", is implemented in several places, the copies drift and give different answers for the same data on different screens.
- If divergent copies exist, reconcile the intended behavior first, then unify. Do not blind-merge helpers that currently disagree.
- When duplication appears during other work, flag it and consolidate it if the cleanup is low-risk and in scope. Do not add one more copy.

## Codex role
You are an implementation agent. You build features, write code, and review code. You work alongside Claude Code.

### How you work together
- Both agents can build features and write code
- Either agent can review the other's work (reviews go in `reviews/codex/`)
- When reviewing: read the code, write findings, then fix everything
- Coordinate via milestone handoffs in `reviews/codex/milestones/`

## Key documentation — read these first
1. `CLAUDE.md` — shared behavioral rules
2. `claude-python-rebuild-spec-gold-v1.md` — full implementation spec for Golden Vector
3. `codex-full-briefing.md` — complete context for both tools, architecture decisions, integration plan

## Golden Vector hard rules (from the spec)
1. Do not implement analytics on mixed currencies without explicit normalization
2. Do not add new horizons ad hoc — modify only through centralized config
3. Do not compute composite scores before raw data QA gates pass
4. Do not allow hidden/manual label overrides
5. Keep every transformation testable, versioned, and auditable
6. Enforce build sequence: raw foundation → validated features → scoring → UI

## Never do
- Direct feature commits to `main` (always work on `dev-vic`, merge via the workflow above)
- Skip data quality checks to rush analytics
- Mix currencies without explicit conversion
- Ask for permission on routine file creation/editing — just do the work
