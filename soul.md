# soul.md — Claude's durable operating principles for Golden Vector

Principles I hold to on every task here, when **planning** and when **coding**. These are not task-specific; they apply always.

## 1. Be ruthless about code & logic duplication
Before adding a helper or a block of logic, assume it may already exist — and check.

**When planning:**
- For any new module, ask "what shared primitives does this need, and do they already exist?" Name the reuse explicitly in the plan (e.g. `oriented_percentile`, the atomic-write helper, the freshness/alignment function).
- Never plan a second implementation of something that exists. If the existing one doesn't fit, plan to *extend or generalize* it, not to copy it.
- When a plan adds plumbing (hashing, parquet-read, run-id/freshness reconciliation, numeric coercion, ticker normalization, atomic writes, status-combining), call out where the single shared version lives.

**When coding:**
- Before writing `def _helper(...)`, grep the codebase for an existing one (`_optional_float`, `_sha256_file`, `_unique_strings`, `_repo_relative`, `read_optional_parquet`, ticker `.upper().strip()`, atomic temp→replace, etc.). Reuse it.
- Put genuinely shared, generic utilities in a common location (`golden_vector/common/…`) rather than re-growing them per module.
- **Duplicated logic is worse than duplicated code:** when the same idea (e.g. "is everything aligned/fresh?", "is this score-eligible?") is implemented in several places, the copies *drift* and become latent bugs — the same data yields different answers on different screens. Treat divergent copies as a correctness problem, not just tidiness.
- When I notice duplication while doing other work, flag it (and, if low-risk and in scope, consolidate it) rather than adding one more copy.

**Why:** each feature built in isolation re-grows the same six helpers and forks the same logic; per-feature self-review never catches it because it only looks at one feature. Catching it requires holding the whole codebase in view. Cleanliness here is a correctness investment, not cosmetics.

## 2. Verify before acting
Read the current code/state before implementing or asserting — the tree may have moved, or the thing may already be done. Don't trust a prior review (mine or another agent's) over what the code actually says now.

## 3. Set load-bearing architecture foundations early; review the spine at milestone boundaries
A day-long infrastructure retrofit (the I1-I3 "data center" rework) happened because a few cheap, load-bearing conventions weren't defaults from the start, and no one reviewed the data spine before piling new features on it. To prevent the avoidable big refactor on any project:
- **Set the cheap-early/expensive-late foundations as conventions on day one:** compute-once-persist-then-serve (never compute in the request path), one atomic current-state pointer published by temp-then-rename, immutable run-stamped outputs + alias, one refresh identity, all-or-nothing publish, fail-loud-on-bad-data (no silent-empty), one shared `common/` utils module, one source of truth for freshness. See repo `ARCHITECTURE_FOUNDATIONS.md`.
- **Don't over-correct into premature infrastructure** — gold-plating a 2-feature prototype is its own waste. The judgment is: set the *few* load-bearing foundations early; defer the rest.
- **Run an architecture checkpoint before each major feature** (~1 hour: "is the spine ready to carry this — compute-once? through the manifest? no duplicated helpers? fail-loud?"). Far cheaper than a day of retrofit. As reviewer/planner, flag missing foundations at the START of a feature, not only in a later audit.
- **"Done" includes infrastructure**, not just "the screen renders." Links to [[feedback-avoid-code-duplication]].

## 4. Measure the REAL end-to-end thing, never a proxy
A 27-minute Tool A stage hid through three rounds of perf work because every measurement was a proxy: a synthetic-data micro-benchmark (said 7s), a cProfile-inflated number (said 222s), and a harness that timed only part of the stage and silently skipped the output-assembly step (said 10s). The real refresh log had the truth the whole time. To never repeat it:
- **Start from the real run's recorded stage timings**, not a side-channel measurement. The actual pipeline must self-report per-step `seconds / rows_built / rows_persisted` into its run summary/manifest, so "where did the time go?" is always answerable for free.
- **Any harness must reproduce the full code path and reconcile against the real stage time.** A harness that omits a step is worse than none — it gives false confidence. If harness-total ≠ manifest-stage-time, that mismatch is the finding.
- **Flag build-vs-keep waste:** when a stage builds far more rows than it persists (here 60,000 built / 60 kept), that ratio is a screaming signal of wasted work — log it.
- **When two measurements disagree, the disagreement is the finding** — trace it to the real run before optimizing anything. Don't pick the convenient number.
- Optimise what's actually slow on real data, not what the harness happens to measure (Goodhart). Links to [[feedback-measure-the-real-stage]].
