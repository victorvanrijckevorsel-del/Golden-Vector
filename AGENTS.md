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

## Product idea generalization
When Victor suggests a product or UI idea, check whether the same concept applies elsewhere in the app. If it can be generalized across related pages, data surfaces, or repeated metric displays, say so proactively before planning implementation. Explain the general pattern in plain English and name the affected pages or components.

If Victor asks to add a control, explanation, source toggle, warning, `i` button, calculation detail, color rule, or similar UI treatment to one page, actively search for the same numbers or concept on other pages. Then say plainly, for example: "Hey Victor, these same numbers are also shown on the ticker detail page and Candidate Finder. Should we apply the same rule there too?" Do not wait for Victor to notice duplicated surfaces.

When a new tool, page, or feature request could reasonably be built either as a small local change or as a broader shared/product-wide feature, do not assume the smaller scope. Make the scope choice explicit before planning or coding: "Hey Victor, this can be built as a small change on this page, or as a larger shared feature across X/Y/Z. Which do you want?" This is a product-scope decision, so asking is required even in low-interruption execution mode.

## Git merge workflow (follow every time, automatically)
When a milestone is ready to ship:
1. Commit and push to `dev-vic`
2. Switch to `main`, pull latest, merge `dev-vic` into `main`
3. Push `main` to GitHub
4. Delete remote `dev-vic` branch (`git push origin --delete dev-vic`)
5. Switch back to `dev-vic` (recreate from `main`) to continue working
Do this automatically at each milestone — no need to ask.

## Branch integration safety
Before merging any branch, feature milestone, or worktree into `dev-vic` or
`main`, run a deliberate integration audit. This is mandatory when multiple
agents have been coding in parallel.

- List every local and remote branch that is not merged into `origin/main`.
- List every active worktree and note its branch, base commit, and ahead/behind
  state.
- Compare touched files across active branches before merging. Pay special
  attention to `golden_vector/app/model_state.py`, `golden_vector/cli.py`,
  `golden_vector/contracts/`, `golden_vector/serve/`, Candidate Finder,
  Option Trading, Tool B, portfolio artifacts, and all schema/manifest code.
- Do not assume a clean Git merge means a safe product merge. Schema changes,
  artifact contracts, model-state publishing, freshness handling, and UI
  readers can conflict logically without textual conflicts.
- If two branches touch the same data spine or serve surface, integrate through
  a temporary integration branch first. Run focused schema/reader tests, then
  the full suite, then a real workspace smoke check before declaring it safe.
- Never merge a branch that changes persisted artifacts, model-state manifest
  shape, refresh publishing, or reader resolution without checking whether
  another unmerged branch changed the same contract.
- Treat unmerged branch inventory as part of the handoff. Report what is
  merged, what is pending, and what must be reconciled next.

## Token efficiency (always apply — learned 2026-08-10)
Be conscious of token/context consumption and manage it proactively — flag waste yourself instead of letting Victor discover it in his usage panel.

- Browser/MCP tool results stay in the session context permanently: batch real-browser verification into one scripted pass at major gates only; keep return values minimal; write evidence to files; prefer file-loaded scripts over inline echoes.
- Prefer terminal/pytest verification over browser verification when both prove the same thing.
- Never rely on the user manually compacting context: keep persistent notes + committed evidence current at every boundary so automatic compaction/summarization is always lossless and long unattended runs stay safe.
- Use cheaper models for mechanical subagent work; reserve the strongest model for judgment-heavy review.

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

## Data architecture foundations
Use the full checklist in [ARCHITECTURE_FOUNDATIONS.md](ARCHITECTURE_FOUNDATIONS.md) as a standing reference for every project and every major feature. The rule is not to gold-plate prototypes; it is to set the few cheap, load-bearing data foundations early and check the data spine before stacking features on top.

Set these foundations as defaults from day one when building data-heavy features:

- Compute once, persist, serve reads. Analytics must not run in request handlers or UI render paths. Each stage reads inputs, computes, and writes a persisted artifact; readers only read artifacts.
- Use one atomic current-state pointer. A single manifest names the coherent current outputs and is published by write-temp-then-`os.replace`. Readers resolve through it instead of opening multiple mutable `latest` files directly.
- Write immutable run-stamped outputs plus a convenience alias. The pointer references immutable run-id files, while `latest` aliases remain convenience outputs only.
- Thread one refresh identity through every stage so coherence is an invariant, not a warning reconstructed later by comparing ids.
- Publish all-or-nothing. A failed or interrupted build leaves the previous good current state intact.
- Fail loud on bad data, never silent-empty. Required inputs use checked reads, schema validation, and checksum verification where it matters. Do not hide corrupt or missing required data behind empty frames.
- Keep shared utilities in one common package from the start: coercion, hashing, atomic writes, Parquet IO, ticker normalization, status combining, freshness, and alignment. Grep before adding any helper.
- Keep one source of truth for freshness/alignment and consume it everywhere. Do not recompute alignment separately per CLI command or screen.

Before adding a major feature, run a short architecture checkpoint:

- Is the data spine ready to carry this feature?
- Is the feature computed once and persisted?
- Are readers resolving through the current-state manifest?
- Are required inputs fail-loud rather than silent-empty?
- Did the work reuse existing common helpers instead of adding copies?

Treat a feature as done only when it is computed-once-and-persisted, resolved through the manifest, adds no duplicated helper, and fails loud on required bad data. A screen rendering successfully is not enough.

Smells that mean this debt is accumulating:

- A request handler computes, scans, models, or aggregates instead of reading a prepared artifact.
- More than one mutable `latest` file is treated as authoritative by readers.
- A second copy appears of an existing helper.
- Required input code does `except Exception: return empty`.
- A warning reconciles states that should not be able to diverge.

## Performance diagnostics
Diagnose performance from the real end-to-end run's recorded stage timings, never from a synthetic, isolated, or profiler-only proxy.

- Every pipeline stage must self-report enough timing and row-count detail into its run metadata or model-state manifest for "where did the time go?" to be answerable without rebuilding a custom profiler. Include per-step seconds, `rows_built`, and `rows_persisted` where those concepts apply.
- Harnesses are secondary checks, not the source of truth. A performance harness must reproduce the full relevant code path and reconcile against the recorded real stage timing; a harness that omits a step is worse than none because it creates false confidence.
- Flag build-vs-keep waste whenever a step builds far more rows than it persists or serves. Large `rows_built / rows_persisted` ratios are correctness and architecture smells, not just speed smells.
- When two measurements disagree, the disagreement is the finding. Trace the mismatch to the real run before optimizing anything.

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
