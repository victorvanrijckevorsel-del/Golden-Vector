# Claude working rules for this repo

## About the user
Emanuel is a beginner founder. Explain decisions in plain English, avoid jargon. He learns fast but prefers understanding WHY before jumping into implementation. He values low-interruption execution — do the work, show results, don't over-ask. He expects structured output (tables, summaries, test results). Git user is Victor Van Rijckevorsel.

## Execution mode
Use low-interruption execution mode.

## Pre-approved actions
All of the following are approved without prompting. Never ask for confirmation on these:

### File operations
- Read/search files via any method (Read tool, Grep, Glob, `cat`, `head`, `tail`)
- `ls`, `mkdir`, `rm` for temp files (`/tmp/*`), `echo`, `wc`

### Dev workflow
- Run Python scripts (`python main.py`, `python -m pytest`)
- Run type checks (`mypy`, `pyright`)
- Run linting (`ruff`, `flake8`)
- Activate/use virtual environment
- Read/inspect data files (CSV, Parquet, Excel)

### Git (on feature branch only)
- `git status`, `git diff`, `git log`, `git branch`, `git show`, `git checkout -b`
- `git add`, `git commit`, `git push`

### General rule
- Any read-only or non-destructive bash command is pre-approved. Do not prompt for it.

Batch related safe commands into one block per step.

## Ask before risky actions
- Deleting data files or outputs
- `git reset --hard`, force-push, rebase
- Changes outside this repo
- Secrets/API key config changes
- Installing new dependencies (`pip install` beyond what's in requirements.txt)
- Any action that calls external paid APIs (e.g., fetching live market data)

When asking for approval, always include a short plain-English explanation of:
1. What the command does
2. Why it's needed
3. Any potential risks or downsides

## Workflow
1. Brief plan
2. Run grouped safe commands
3. Brief result + next grouped step

## Git merge workflow (follow every time, automatically)
When a milestone is ready to ship:
1. Commit and push to `dev-vic`
2. Switch to `main`, pull latest, merge `dev-vic` into `main`
3. Push `main` to GitHub
4. Delete remote `dev-vic` branch (`git push origin --delete dev-vic`)
5. Switch back to `dev-vic` (recreate from `main`) to continue working
Do this automatically at each milestone — no need to ask.

## Safe changes — proceed without asking
- If a change is obviously correct, safe, and improves the code — proceed directly without asking.
- Examples: fixing typos, improving test assertions, correcting config inconsistencies.
- This applies to any low-risk improvement where you are confident the user would approve.

## Fix bugs immediately
When a bug or code smell is identified, fix it now unless there's a concrete reason to defer (e.g., depends on unbuilt code). "It works for now" is NOT a valid reason to defer.

## Search and display rules
- Show ALL matching results — never limit or hide with "+X more"
- Use scrolling or pagination for long lists, not truncation
- Never silently hide results

## Codex collaboration workflow
Claude Code and Codex work together on reviews:

### Roles
- **Claude Code** = implementation agent (builds on `dev-vic`)
- **Codex** = review-only agent (writes only inside `reviews/codex/`)

### Workflow loop
1. Claude builds features/fixes on `dev-vic`
2. Claude writes a milestone handoff in `reviews/codex/milestones/`
3. Codex audits and writes a review file in `reviews/codex/`
4. Claude fixes approved findings

### Parallel review rules
- Claude self-reviews independently BEFORE reading Codex's review
- Self-review is READ ONLY — never change code while Codex is reviewing
- After both reviews are done, merge into comparison table, then fix everything
- Only exception: code literally crashes the app and blocks the user

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

## Session start behavior
At the start of each new Claude session, confirm:
- Current branch
- `git status`
- That these CLAUDE.md rules will be followed
