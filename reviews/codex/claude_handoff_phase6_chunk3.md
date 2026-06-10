# Handoff to Codex — Phase 6, chunk 3 (final): #26 compare-view cleanup, #27b vendor-outage, #27c lint/type

**Status:** chunk-2 (#22 charts + #24 scenario) is built and self-reviewing. Finish that self-review and **leave chunk-2 staged for Claude to verify + commit** (Claude served it and the Option Trading page renders correctly). Then proceed to chunk 3 — it touches docs / ingestion / tooling config, which do **not** overlap chunk-2's serve files, so it can proceed without conflict.

**This is the LAST chunk of the completion plan.** After it lands and Claude commits, the whole plan (Phases 0–6) is done and Claude merges `dev-vic` → `main`.

**Specs (read both):** the Phase 6 section of `reviews/codex/claude_completion_plan_portfolio_and_tool_d.md` (#26, #27b, #27c) and `reviews/codex/codex_review_completion_plan_phase6.md` (findings #6 and #7 — the precise protect-list).

## FOR CODEX — build, in this order

### #26 — Retire the OLD workspace compare view (and ONLY that)
- Close the old workspace **side-by-side / pair compare-view** backlog (the deferred documentation/references for the old workspace two-pane compare).
- **DO NOT remove or weaken any of these** — they are the live hedge-report comparison and must stay:
  - `golden_vector/hedge/comparison.py`
  - the CLI `--comparison-sort-by` flag
  - the `comparison` section in `golden_vector/hedge/report.py` (the markdown comparison output)
- Net: this is mostly removing dead backlog/doc references to the retired workspace compare pane, with a test or guard that the CLI/markdown comparison path still works. If there's no actual dead code left to remove (only docs), say so explicitly rather than touching the live module.

### #27b — Single-vendor (Yahoo) outage behavior
- Define and implement the policy for when the data vendor is unavailable:
  - **Full outage** (Yahoo down entirely) vs **per-ticker outage** (some symbols fail) — distinct handling.
  - Decide and document whether a refresh **fails closed** (no publish, previous state intact) on a full outage, vs **publishes visible FAIL rows** for per-ticker failures (degrade per-item, never silently drop — carry-forward discipline).
  - **No live-vendor tests** — simulate outages with fakes/fixtures, never hit the network in tests.
- Tests: a simulated full outage leaves the previous model-state intact (fails closed); a simulated per-ticker outage publishes that ticker as a visible FAIL row and does not silently count it as healthy.

### #27c — Lint / type baseline
- **UPDATE (2026-06-09): ruff is now INSTALLED and approved by Emanuel** (ruff 0.15.16) — no separate install approval needed. The default-rule baseline currently flags **17 issues** across `golden_vector/` + `tests/`: 10× `F401` unused-import, 4× `F841` unused-variable, 1× `E741` ambiguous-variable-name, 1× `F402` import-shadowed-by-loop-var, 1× `F541` f-string-missing-placeholders.
- Add a **minimal** ruff config (`ruff.toml` or `[tool.ruff]` in a new `pyproject.toml`), scoped so the diff is reviewable.
- Add `ruff` (and later optionally `mypy`/`pyright`) to a **dev** dependency list (`requirements-dev.txt` or a `[dev]` extra) — do NOT add to the runtime `requirements.txt`.
- Clean up the 17 baseline findings as part of this item: **11 are `ruff check --fix`-able** (the unused imports + the f-string). For the 4 `F841` unused-variables and the `E741`/`F402` cases, **look manually** — do not blind-delete a variable whose RHS has a side effect, and rename the ambiguous name rather than deleting. Keep it one tidy, reviewable pass; run the full suite after.
- Add `mypy`/`pyright` only if the baseline is scoped and non-disruptive; if it would be noisy, defer it and say so.

## Carry-forward discipline
- Degrade per-item, never per-build (the #27b per-ticker FAIL rows).
- Fail closed on a full outage — never publish a half-built/empty state as healthy.
- No silent drops/caps — a failed ticker is a visible FAIL, not a missing row.
- Tests prove the behavior with fakes; no network in tests.

## Conventions
- `dev-vic` only. Build + leave everything **staged**; **Claude reviews and commits** — do not commit yourself.
- Do NOT touch `candidate_finder.py` / `tool_a` / `tool_c` / lenses, or the protected comparison module/flag/section above.
- Never touch/print `data/manual/*`.
- **Ping when chunk 3 is staged and the suite is green** (note in the ping whether the ruff install/baseline is pending Emanuel's OK). Claude verifies first-hand, commits, and then merges the completed plan to `main`.
