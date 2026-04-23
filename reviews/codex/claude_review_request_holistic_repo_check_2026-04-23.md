# Claude Review Request: Holistic Repo Check

Please perform a deep, read-only review of the **entire Golden Vector codebase** in its current state.

This is not a narrow feature review. The goal is to judge whether the repo is now coherent, trustworthy, and aligned with the intended product direction after a large amount of recent work.

Use this review to stress-test **Claude Opus 4.7** properly. Do not keep it shallow.

## Review Goal

Judge the whole product across:

- architecture and runtime flow
- data correctness and QA gates
- FX / normalization safety
- Tool A structural model correctness and explainability
- Tool B screening / manual-store correctness
- workspace presentation and usability
- persistence / latest-alias safety
- docs / tests / auditability

This review should answer:

- is the current product shape coherent?
- are the hard rules actually enforced in code?
- is the system trustworthy enough to use day to day?
- what is still wrong or weak at a repo-wide level?

## Product Context

Golden Vector is now a **local-first** product.

Current runtime model:

- `update-data` is the explicit market-data refresh step
- `tool-a` runs from the latest validated local snapshot
- `tool-b` runs from the latest validated local snapshot plus the local manual-data store
- `workspace` is the current product surface
- the old heavy Combined backend is removed from the active product
- the future compare view is intentionally deferred and is **not** part of this review

Current strategic shape:

- **Tool A** = structural-first gold-sensitivity engine
- **Tool B** = fundamental screening / valuation engine
- **Workspace** = local UI for Tool B inputs/notes and latest Tool A / Tool B outputs

## Most Important Conceptual Sources

Please treat these as first-class context:

- [ssrn-3172514.pdf](C:/Users/Emanuel/code/Golden-Vector/ssrn-3172514.pdf)
- [Gold_Framework_Implementation_Guide.docx](C:/Users/Emanuel/code/Golden-Vector/Gold_Framework_Implementation_Guide.docx)

Important:
- do **not** treat the implementation guide as automatically correct
- if the guide disagrees with the Guo / Leung / Ward logic, call that out
- if the code matches the guide but still looks conceptually weak, call that out

Secondary context for intent and presentation:

- [sprott-gold-equities-strategy-q1-2025-commentary.pdf](C:/Users/Emanuel/code/Golden-Vector/sprott-gold-equities-strategy-q1-2025-commentary.pdf)
- [Gold_Tickers_Historical_Prices_Final_WORKING2_EDITED_v3.xlsm](C:/Users/Emanuel/code/Golden-Vector/Gold_Tickers_Historical_Prices_Final_WORKING2_EDITED_v3.xlsm)
- [Gold_Mining_Screening_Updated_18Feb2026 (1).xlsx](C:/Users/Emanuel/code/Golden-Vector/Gold_Mining_Screening_Updated_18Feb2026%20(1).xlsx)

## Mandatory Repo Context To Read First

- [AGENTS.md](C:/Users/Emanuel/code/Golden-Vector/AGENTS.md)
- [CLAUDE.md](C:/Users/Emanuel/code/Golden-Vector/CLAUDE.md)
- [claude-python-rebuild-spec-gold-v1.md](C:/Users/Emanuel/code/Golden-Vector/claude-python-rebuild-spec-gold-v1.md)
- [codex-full-briefing.md](C:/Users/Emanuel/code/Golden-Vector/codex-full-briefing.md)
- [README.md](C:/Users/Emanuel/code/Golden-Vector/README.md)
- [docs/golden_vector_architecture_map.md](C:/Users/Emanuel/code/Golden-Vector/docs/golden_vector_architecture_map.md)
- [reviews/codex/product_runtime_redesign_plan.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/product_runtime_redesign_plan.md)

Please also read these recent reviews so you understand where the code has already been challenged:

- [reviews/codex/codex_review_post_workspace_hardening_2026-04-23.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/codex_review_post_workspace_hardening_2026-04-23.md)
- [reviews/codex/codex_review_tool_a_structural_redesign_findings.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/codex_review_tool_a_structural_redesign_findings.md)
- [reviews/codex/claude_review_tool_a_structural_redesign_findings.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_review_tool_a_structural_redesign_findings.md)
- [reviews/codex/merged_review_phase3_phase4_runtime_manual_store_comparison.md](C:/Users\Emanuel\code\Golden-Vector\reviews\codex\merged_review_phase3_phase4_runtime_manual_store_comparison.md)

## Files And Areas To Review

### Runtime / orchestration / persistence
- [main.py](C:/Users/Emanuel/code/Golden-Vector/main.py)
- [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py)
- [golden_vector/app/](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app)
- [golden_vector/ingestion/](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion)
- [golden_vector/contracts/](C:/Users/Emanuel/code/Golden-Vector/golden_vector/contracts)

### QA / normalization / FX
- [golden_vector/normalize/](C:/Users/Emanuel/code/Golden-Vector/golden_vector/normalize)
- [golden_vector/qa/](C:/Users/Emanuel/code/Golden-Vector/golden_vector/qa)

### Tool A
- [golden_vector/model/](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model)
- [golden_vector/features/](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features)

### Tool B
- [golden_vector/screening/](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening)

### Workspace / presentation
- [golden_vector/serve/workspace.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py)

### Legacy / de-scoped context
- [golden_vector/combined/README_LEGACY.md](C:/Users/Emanuel/code/Golden-Vector/golden_vector/combined/README_LEGACY.md)

### Tests
- [tests/](C:/Users/Emanuel/code/Golden-Vector/tests)

## Live Artifacts To Inspect

Please inspect the current produced artifacts, not just source code.

### Foundation / latest snapshot
- [data/intermediate/status/latest_foundation_manifest.json](C:/Users/Emanuel/code/Golden-Vector/data/intermediate/status/latest_foundation_manifest.json)

### Latest Tool A
- [data/output/tool_a/tool_a_latest.csv](C:/Users/Emanuel/code/Golden-Vector/data/output/tool_a/tool_a_latest.csv)
- [data/output/tool_a/tool_a_latest.parquet](C:/Users/Emanuel/code/Golden-Vector/data/output/tool_a/tool_a_latest.parquet)
- [data/runs/20260423T122721Z-tool-a-ac236d2b/metadata.json](C:/Users/Emanuel/code/Golden-Vector/data/runs/20260423T122721Z-tool-a-ac236d2b/metadata.json)

### Latest Tool B
- [data/output/tool_b/tool_b_latest.csv](C:/Users/Emanuel/code/Golden-Vector/data/output/tool_b/tool_b_latest.csv)
- [data/output/tool_b/tool_b_latest.parquet](C:/Users/Emanuel/code/Golden-Vector/data/output/tool_b/tool_b_latest.parquet)

### Manual data store
- [data/manual/screening/manual_screening.sqlite3](C:/Users/Emanuel/code/Golden-Vector/data/manual/screening/manual_screening.sqlite3)

Use these artifacts to check:

- whether published output schemas make sense
- whether latest aliases are safe and consistent
- whether provenance is sufficient
- whether the explanation text matches the actual metrics
- whether Tool B/manual-store behavior looks coherent and auditable

## Mandatory Review Lenses

### 1. Whole-system architecture
- Is the current local-first architecture coherent end to end?
- Does the repo reflect the actual product shape, or are there still deep mismatches between code and docs?
- Are there duplicated responsibilities or leftover dead paths that still create risk?

### 2. Runtime and orchestration
- Is `update-data -> tool-a/tool-b -> workspace` actually enforced cleanly?
- Are there hidden side effects, fragile assumptions, or path-coupling issues?
- Are latest-artifact pointers and manifests safe enough?

### 3. FX / normalization / QA
- Find any place where mixed-currency analytics can still leak through.
- Find any place where Tool A or Tool B can proceed despite normalization issues without surfacing them strongly enough.
- Check stale FX handling, blocked normalization states, and auditability.

### 4. Tool A structural model
- Is Tool A now mathematically coherent?
- Does it meaningfully match the paper and a sensible interpretation of the guide?
- Are score, labels, explanations, and workspace presentation aligned with each other?
- Are any parts of the old exploratory horizon model still leaking into the official structural model?

### 5. Tool B model and manual-data workflow
- Is the Tool B pipeline coherent and still correct after the runtime/manual-store redesign?
- Is the SQLite manual-store model sound?
- Are there operator risks in import/export, backup, store mutation, or note handling?
- Are there data fields or workflows that are still too fragile?

### 6. Workspace quality
- Is the workspace now the right product surface for v1?
- Are Tool A and Tool B both presented clearly?
- Are explanations intuitive for a non-technical user?
- Is anything misleading, too quiet, or too visually confusing?

### 7. Persistence / outputs / auditability
- Are outputs versioned and traceable enough?
- Are latest aliases safe?
- Could empty, stale, or partial runs silently mislead the workspace?
- Are important policy assumptions carried through to outputs?

### 8. Tests and regression safety
- Are the most important failure modes covered?
- What important edge cases are still untested?
- Are there weak or overly synthetic tests that might let bad math or bad workflow behavior pass?

### 9. Docs and operator guidance
- Do the current docs describe the actual product, not the old one?
- What would still confuse a new contributor or a future agent?

## Required Checks

Please explicitly check for the following and call them out if found:

1. Any remaining mixed-currency or weak FX handling path.
2. Any place where stale or blocked normalization still looks valid to the user.
3. Any mismatch between latest published artifacts and workspace interpretation.
4. Any Tool A explanation or label that still overstates what the metrics justify.
5. Any Tool B/manual-store workflow that still mutates data unexpectedly.
6. Any CSV import/export path that is misleading, lossy, or unsafe.
7. Any persistence/latest-alias bug that could show stale or broken data.
8. Any significant mismatch between code and docs.
9. Any major conceptual mismatch between the Guo paper, the implementation guide, and the current Tool A.
10. Any area where the codebase still feels structurally brittle even if the tests pass.

## Specific Questions To Answer

Please answer these directly in the review:

1. Is the current product architecture coherent and trustworthy overall?
2. Is Tool A now good enough to be treated as the official structural model?
3. Is Tool B / manual-data handling now strong enough for normal daily use?
4. Is the workspace now a good enough product surface for v1, or is it still too thin / too risky?
5. What are the most important remaining conceptual weaknesses?
6. What are the most important remaining engineering weaknesses?
7. If you had to prioritize only the next 3 things to fix or improve, what would they be?

## Output Rules

- Read-only review only
- No code changes
- Findings first, ordered by severity
- Be concrete and cite files / lines where possible
- Separate **bugs**, **architectural weaknesses**, and **conceptual disagreements**
- Do not hide behind vague wording if you think something is weak

Please write your review to:

- `reviews/codex/claude_review_holistic_repo_check_2026-04-23_findings.md`

Use this structure:

1. Findings ordered `P0` to `P3`
2. Architecture assessment
3. Tool A assessment
4. Tool B / manual-store assessment
5. FX / normalization / QA assessment
6. Workspace / presentation assessment
7. Tests / docs / residual risks
8. Final verdict: `READY`, `READY WITH MINOR CHANGES`, or `NOT READY`
