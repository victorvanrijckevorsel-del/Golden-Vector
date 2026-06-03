# Codex Implementation Brief: Workspace Split

**To:** Codex
**From:** Claude Code
**Date:** 2026-05-28
**Plan being implemented:** [claude_workspace_split_plan.md](claude_workspace_split_plan.md) (v2)
**Your role:** Implementer

You graded plan v1 as `READY WITH MINOR CHANGES`. Plan v2 (same file) addresses all 6 findings — see the v2 changelog at the top of the plan. Re-read the plan to confirm, then execute it per the instructions below.

---

## Your role this session

Execute the 12 steps in §4 of the plan, one commit per step. Stop at the defined checkpoints (below) and report. Wait for Emanuel to say "continue" before starting the next phase.

## Do NOT read workspace.py end-to-end

It is 4130 lines and will overflow your context window. The plan maps every top-level function and constant to its current line number — trust §1 and §3d.

When you need to move a function, open ONLY that function's line range plus ~10 lines of context above and below. Do not load the whole file. Use grep for cross-references.

## Git workflow (FOLLOW EXACTLY)

- All work happens on branch `dev-vic`. Confirm with `git branch --show-current`.
- One commit per step in §4. Twelve steps → twelve commits.
- Commit message format:
  `workspace split step <N>: <one-line description>`
  e.g. `workspace split step 3: move format helpers to format_helpers.py`
- Do NOT amend commits. Do NOT rebase. Do NOT merge to main.
- Do NOT skip hooks (no `--no-verify`). Do NOT force-push.
- Do NOT run `git push` — Emanuel handles pushing to remote.
- Do NOT delete any data files, runs, snapshots, or untracked files.

## Test gate (run between every step)

Command: `python -m pytest -q`

Pass condition: all tests green AND no new warnings beyond the baseline. Establish the baseline at the start of the session by running the suite once and recording the pass count + warning count in your progress log (below).

If any step breaks tests, **STOP that step.** Do not start the next one. Revert your last commit with `git reset --soft HEAD~1`, fix the issue, re-commit, re-run tests. If you can't fix it in 15 minutes of bounded effort, stop and report — do not improvise.

## Manual smoke check (at the steps that require it per §4)

1. Start the app: `python main.py serve` (background OK)
2. Hit the four URLs and confirm they render the same markers as before:
   - `/`
   - `/tool-a`
   - `/tool-b`
   - `/ticker/AEM`
3. For **step 11 specifically**, ALSO check:
   - `/ticker/AEM?lens=tool-a` → must render identically to `/ticker/AEM`
   - `/ticker/AEM?lens=banana` → must render the tool-a page, return 200, NOT 404
4. Stop the app.

You don't have a browser. Use `curl` and grep the HTML for known markers (page titles, key headings, table IDs). That is sufficient for "visually identical" at the HTTP level. State explicitly in your progress log that you used a curl-grep check, not a real browser.

## Self-review at every step (do all 5, every commit)

These are **mandatory** per-step checks that catch failure modes the test suite alone misses. Do every one before moving to the next step.

### 1. Read your own diff before committing

After staging changes, run `git diff --staged` and read it end-to-end. Look for:
- Edits to lines you did NOT intend to change (whitespace shifts, reordered imports, lost blank lines)
- Functions or constants that got moved but lost a piece of their body
- Imports left behind in the old location that are now unused
- Any change that touches a file outside the step's scope

If you see something unintended, fix it before committing. The commit should match what the step says it does, nothing else.

### 2. HTML baseline snapshots (do this ONCE at the start, before step 2)

Before starting step 2, capture HTML baselines:

```bash
mkdir -p /tmp/workspace_baseline
python main.py serve &  # background
sleep 2
curl -s http://localhost:<port>/             > /tmp/workspace_baseline/combined.html
curl -s http://localhost:<port>/tool-a       > /tmp/workspace_baseline/tool-a.html
curl -s http://localhost:<port>/tool-b       > /tmp/workspace_baseline/tool-b.html
curl -s http://localhost:<port>/ticker/AEM   > /tmp/workspace_baseline/ticker-aem.html
# stop the app
```

After any step with a manual smoke check (per §4: steps 2, 8, 11), re-capture and `diff` against the baseline. After step 2, the only expected diff is the new `<link rel="stylesheet" href="/static/workspace.css">` line — nothing else. After step 8 and step 11, expected diff is zero unless explicitly noted in the plan. Any unexpected diff = STOP and investigate before continuing.

### 3. Test count must never decrease

Record the baseline test pass count at session start (`python -m pytest -q` → e.g. "280 passed"). After every step, the pass count must be **greater than or equal to** the baseline. If the count drops — even by one — that is a STOP condition, because the most common cause is a test file that silently failed to import after a move. A green suite with fewer tests is not a green suite.

### 4. Confirm the old location is empty

After moving a function or constant out of `workspace.py`, verify it is gone from there and present in its new home:

```bash
rg "<symbol-name>" golden_vector/serve/workspace.py   # must be empty (or only references via import)
rg "<symbol-name>" golden_vector/serve/<new-file>.py  # must have the definition
```

Do this for every symbol moved in the step. If a symbol still appears in `workspace.py` outside an import line, the move is incomplete.

### 5. Stop conditions (any of these = halt and report)

- Test pass count dropped
- A test that was green now errors or skips
- HTML baseline diff shows unexpected changes
- A grep check (#4 above) finds a symbol in two places
- You spent more than 15 minutes trying to fix one issue

Do not continue past any of these. Report and wait for Emanuel.

## Decisions already locked (do not re-litigate)

1. Tool-shaped split for the detail page only. Lens param, default `"tool-a"`.
2. Mechanical split everywhere else.
3. Snapshot retention: audit first (step 1), write code only if the audit finds a real gap.
4. No abstractions for predictive tools or short/put-finder. Shape the interface only.

## Progress log (write as you go)

Create `reviews/codex/codex_workspace_split_progress.md` at the start of the session with the baseline test pass count. After each step, append one line:

```
Step <N> (<step-name>): committed <commit-sha>. Tests: <pass>/<total>. Smoke check: <yes/no/skipped>. Notes: <one line, optional>.
```

## Checkpoints — STOP and report at each one

At each checkpoint, post a short summary in chat: commits made, test pass count, anything surprising. Then wait for "continue" before starting the next phase.

- **CHECKPOINT A** — after step 1 (audit doc only, code-free).
  Report what retention is and is not present. Wait for "continue."

- **CHECKPOINT B** — after step 2 (CSS extraction).
  Report on visual smoke check result. CSS is the only step with visual-regression risk, so explicit pause here. Wait for "continue."

- **CHECKPOINT C** — after step 7 (charts moved).
  Half-way mark. All "leaf" extractions done. Report current `workspace.py` size. Wait for "continue."

- **CHECKPOINT D** — after step 12 (verify).
  Final report: total commits, final `workspace.py` size, full test pass count, all smoke checks confirmed. **Also write the completion report described below — Claude needs it to do a thorough code review.**

## Completion report (write at Checkpoint D)

Write this file: `reviews/codex/codex_workspace_split_completion_report.md`.

Claude will read this report alongside the diff to do a structural review. The report should make Claude's job easier, not just summarize what you did. Include:

### 1. Final layout readback
List every file in `golden_vector/serve/` after step 12, with its final line count, and a one-line description of what's in it. Compare against the §3b target layout in the plan — call out any difference.

### 2. Deviations from the plan
Every time you had to make a judgment call not specified in the plan, list it here with: what you decided, why, and where in the code it landed (`file:line`). Examples of what counts: a constant you had to move that wasn't in §3d, a helper you had to extract mid-step to avoid a circular import, a default value you had to choose. If you had zero deviations, say so explicitly.

### 3. Symbols moved per file
For each new file, list the function and constant names it now owns (one column each). This lets Claude quickly confirm nothing was misfiled without re-reading 4130 lines.

### 4. HTML baseline diff results
For each step that had a smoke check (2, 8, 11), paste the diff output (or "zero differences"). Be honest — small unexpected diffs are okay if explained; silent unexpected diffs are not.

### 5. Acceptance criteria checklist
Go through every bullet in §5 of the plan and tick it: ✅ met / ❌ not met / ⚠ partial. For any not-met or partial, explain.

### 6. Test deltas
- Baseline pass count: <N>
- Final pass count: <M>
- New test files added (if any): <list>
- Tests modified (if any, with reason): <list>

### 7. Open questions for the reviewer
Things you'd like Claude to look at specifically. Examples: "I wasn't sure whether `_helper_X` belonged in `format_helpers` or `detail_panels` — please sanity-check"; "step 9 imports look unusual to me, worth a second look." If nothing, say so.

The report should be short and structured — Claude will use it as a guided tour of the diff, not a replacement for reading the diff.

Between checkpoints, execute the steps in sequence without pausing, as long as tests stay green.

## Out of scope — DO NOT do any of these

- Designing a `DetailLensSpec` or panel registry (wait for second lens)
- Building any predictive tool or short/put-finder
- Adding new retention beyond what the §2 audit shows is missing
- Refactoring `lenses.py`, `screening_overrides.py`, or `workspace-tables.js`
- Touching anything outside `golden_vector/serve/` except writing `docs/snapshot_retention_audit.md` per step 1
- Performance work, dependency upgrades, type hint improvements
- Splitting commits, rebasing, force-pushing, merging to main
- Running `git push`

## If anything is ambiguous

Stop and ask. Do not improvise on structural decisions. The plan is specific by design; if it doesn't cover your case, that's a signal to pause, not to invent. Better to ask one question than to do a step that has to be reverted.

## Start now

1. Confirm branch: `git branch --show-current` → should output `dev-vic`
2. Record baseline: `python -m pytest -q` and note the pass count
3. Create `reviews/codex/codex_workspace_split_progress.md` with the baseline
4. Re-read `reviews/codex/claude_workspace_split_plan.md` (v2) and confirm the v2 changelog addresses all 6 of your v1 findings
5. Begin step 1
6. Stop at **CHECKPOINT A** and report
