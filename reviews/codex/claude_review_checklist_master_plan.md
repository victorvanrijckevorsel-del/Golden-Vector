# Claude Review Checklist for `golden_vector_master_plan.md`

## Review Target

Review this file in read-only mode:

- `reviews/codex/golden_vector_master_plan.md`

Cross-check it against:

- `AGENTS.md`
- `CLAUDE.md`
- `claude-python-rebuild-spec-gold-v1.md`
- `codex-full-briefing.md`

Your task is not to implement anything. Your task is to decide whether the master plan is complete, internally consistent, feasible, and safe to hand to an implementation agent without leaving design decisions unresolved.

## Review Objective

Answer this question:

"Is the master plan implementation-ready without requiring the implementer to make product, architecture, data, or sequencing decisions on their own?"

A passing review means the plan is:

- decision-complete
- aligned with the repo hard rules
- realistic for an engine-first v1
- explicit about interfaces, failure behavior, and tests

## Review Constraints

This review is strictly read-only.

Rules:

- No code changes
- No plan edits
- No silent assumptions
- No approving vague language without explaining why it is sufficient
- No skipping sections because they seem reasonable at a glance

Read the whole plan before deciding whether it is ready.

## Mandatory Review Lenses

You must evaluate the plan through all of these lenses:

1. Architecture correctness
2. Tool independence plus combined-view clarity
3. Data-model and interface completeness
4. Horizon flexibility design
5. Historical-depth feasibility
6. QA and gating rigor
7. Testing completeness
8. Scope realism for v1
9. Missing assumptions or ambiguous defaults

## Required Checks

### A. Contradictions

Look for contradictions between sections, including:

- architecture vs milestone sequence
- tool boundaries vs combined behavior
- horizon flexibility vs official scoring protection
- max-history policy vs feasibility claims
- QA gates vs downstream behavior

### B. Undecided behavior

Find places where the implementer would still have to choose behavior, including:

- missing interface definitions
- missing data ownership rules
- unclear output responsibilities
- unclear defaults
- unclear failure handling

### C. Weak or underspecified interfaces

Challenge interfaces that are too vague to implement safely, especially:

- config contracts
- dataset contracts
- run orchestration contracts
- Tool A to Tool B join contracts
- comparison-output contracts

### D. Rule-violation risk

Find any path where these project rules could still slip through:

- mixed-currency analytics
- ad-hoc horizons entering official scores
- composite scores before QA gates pass
- hidden label overrides
- invented manual mining inputs

### E. Error-handling and acceptance gaps

Find missing treatment for:

- partial histories
- failed fetches
- inverse FX handling
- near-zero gold returns
- incomplete manual inputs
- partial joins in the combined layer
- deterministic rerun expectations

### F. Scope drift

Find places where the plan is too broad for engine-first v1, including:

- UI requirements disguised as engine requirements
- too many first-release deliverables
- hidden operational complexity that should be deferred

## Questions You Must Be Able to Answer

By the end of the review, you should be able to answer:

1. Can Tool A be built and shipped independently from Tool B?
2. Can Tool B be built and shipped independently from Tool A?
3. Does Combined View clearly consume published outputs rather than mixing internals?
4. Are official horizons protected from exploratory custom horizons?
5. Is the historical-depth strategy feasible without undermining reliability?
6. Are QA gates strong enough to block false confidence?
7. Are dataset and config contracts detailed enough to guide implementation?
8. Are milestone checkpoints practical enough to execute in order?

If any answer is "no" or "not clearly," raise a finding.

## Severity Standard

Use this order:

- `P0`: blocks safe implementation entirely
- `P1`: major ambiguity or design flaw that should be fixed before implementation
- `P2`: important gap or inconsistency that should be tightened before implementation
- `P3`: worthwhile improvement that does not block starting work

Use the lowest severity that still reflects the real risk.

## Required Output Format

Your review output must use this structure:

### 1. Findings

List findings first, ordered by severity.

For each finding include:

- severity
- short title
- exact section or sections involved
- why it matters
- what needs to be clarified, changed, or added

If there are no findings, say that explicitly.

### 2. Residual Risks

List remaining risks that may be acceptable but still deserve tracking.

### 3. Implementation Readiness

End with one clear status:

- `READY`
- `READY WITH MINOR CHANGES`
- `NOT READY`

Then explain that status in a short paragraph.

## Review Success Standard

The review passes only if the master plan is:

- implementation-ready
- aligned with `AGENTS.md` and `CLAUDE.md`
- consistent with `claude-python-rebuild-spec-gold-v1.md`
- consistent with `codex-full-briefing.md`
- decision-complete enough that another engineer or agent can start without inventing behavior

If it is not there yet, say so plainly and identify the blocking gaps.
