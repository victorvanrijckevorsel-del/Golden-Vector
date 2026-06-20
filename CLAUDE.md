# Claude working rules for this repo

## About the user
Emanuel is a beginner founder. Explain decisions in plain English, avoid jargon. He learns fast but prefers understanding WHY before jumping into implementation. He values low-interruption execution — do the work, show results, don't over-ask. He expects structured output (tables, summaries, test results). Git user is Victor Van Rijckevorsel.

## Rule 
please call me Victor everytime that you talk to me 

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

## Product consistency & scope (always apply — Claude AND Codex)
When Victor suggests a new tool, page, UI control, data view, explanation/`i` button, source toggle, warning, metric treatment, color rule, source comparison, or similar product idea, do NOT assume he wants the smallest/local version.

### Ask the scope question FIRST (required — even in low-interruption mode)
If the request could reasonably be built either way:
1. **Small scope** — only on the page/tool Victor named.
2. **Bigger scope** — generalized across related pages, repeated metrics, shared components, or the wider product.

…you must explicitly surface the scope choice BEFORE writing a plan or coding. Plain language, e.g.:
> "Victor, this can be built as a small change only on this page, or as a shared feature across X/Y/Z because the same data appears there too. Which scope do you want?"

This question is REQUIRED even in low-interruption mode — it's a product-scope decision, not routine implementation permission. Do NOT silently pick the smaller version because it's easier/faster. Make the tradeoff clear, ask, then execute once Victor answers.

### Actively check for duplicated surfaces
When Victor asks for an `i` button, data-source toggle, calculation explanation, color rule, source comparison, warning, or similar treatment on one page, actively search whether the same numbers or concept appear elsewhere (ticker detail page, Candidate Finder, workspace tools, portfolio views). If they do, call it out plainly and ask whether the same rule should apply there too. Example:
> "Hey Victor, these same numbers are also shown on the ticker detail page and Candidate Finder. Should we apply the same rule there too?"

Do NOT wait for Victor to notice duplicated surfaces. The goal is whole-product usability, not patching one isolated page when the same user need appears elsewhere.

## Search and display rules
- Show ALL matching results — never limit or hide with "+X more"
- Use scrolling or pagination for long lists, not truncation
- Never silently hide results

## Codex collaboration workflow
Claude Code and Codex are both implementation agents:

### Roles
- **Claude Code** = implementation agent (builds on `dev-vic`)
- **Codex** = implementation agent (builds features, writes code, also reviews)

### How they work together
- Both agents can build features and write code
- Either agent can review the other's work (reviews go in `reviews/codex/`)
- When reviewing: read the code, write findings, then fix everything
- Coordinate via milestone handoffs in `reviews/codex/milestones/`

### Parallel review rules
- When both agents review the same code, merge findings into a comparison table, then fix
- Only exception to "don't change code while reviewing": code literally crashes the app

## Senior engineer coding rules (always apply — Claude AND Codex; both read this file)
Compact canon. Full rationale + war stories live in `soul.md` and `ARCHITECTURE_FOUNDATIONS.md` — read those before any major feature.

### Where code lives
- **Backend computes, serve renders.** No arithmetic, ratio math, coalesce/fallback resolution ("official unless missing"), or rank-basis decisions in `serve/` or templates. The model layer emits resolved, display-ready columns; pages only format, and sort on ONE backend-provided rank column. Every new serve surface gets a static-scan guardrail test (clone the Tool-D serve-arithmetic test in `tests/test_workspace_app.py`).
- **Compute once → persist → serve reads.** Nothing computes in a request path. Stage = read inputs → compute → persisted artifact. Readers resolve through the model-state manifest; outputs are immutable run-stamped files + a `latest` alias; publish is all-or-nothing (a failed build leaves the last good state intact).
- **One copy of everything.** Grep before writing any helper — check `golden_vector/common/` first. Never fork logic; extend or generalize the existing implementation. Duplicated logic is a latent correctness bug: copies drift and the same data gives different answers on different screens.

### Data integrity
- **Fail loud on required data; degrade per item on optional data.** Never `except: return empty` on a required input. One bad ticker marks that ticker and continues — it never aborts the build.
- **Degraded/stale data is EXCLUDED from rankings and confident headlines, not just flagged.** Route it to an explicit degraded state (NA rank, sorts last). Flag-only shipped once and became a review's only HIGH finding — never again.
- **Every threshold lives once, in config.** No hardcoded constant that duplicates a config value — twins drift.
- **One normalize boundary** for currency / pence / units / scale. Never an ad-hoc conversion at a call site.
- **Label every number with its basis.** Gold/price-dependent values carry provenance (`gold_price_used`, basis, date) as real columns. An unlabeled assumption is how the EV/EBITDA confusion happened.

### Quality bar
- **Tests prove behavior — never pass by accident.** Exclusion tests use an otherwise-healthy subject plus a healthy control row; determinism tests include deliberate ties and NA values; user-facing strings are asserted at render level.
- **Verify before acting.** Read the current code first; trust no prior review (own or the other agent's) over what the tree says now.
- **Measure the real run**, never a proxy or harness alone; pipeline stages self-report per-step seconds + row counts.
- **Simplest design that could work, written first.** Propose it before anything bigger; match rigor to risk.
- **Industry-standard metrics only** (EV/EBITDA, P/E, FCF yield, Net Debt/EBITDA, AISC) — no invented or opaque composite scores.
- **Fix bugs and smells now** — "it works for now" is not a deferral reason.

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
