# Golden Vector Product And Runtime Redesign Plan

## 1. Purpose

This document replaces the earlier direction that treated Golden Vector as:

- Tool A
- Tool B
- a heavy Combined backend engine
- live market-data fetch during normal usage
- CSV-first manual Tool B inputs

That is no longer the intended product.

The new direction is simpler and more aligned with how the tool should actually be used:

- Tool A remains a standalone engine.
- Tool B remains a standalone engine.
- Combined is not a third engine. It becomes a later side-by-side view.
- Market data is refreshed only when the user explicitly asks.
- Normal usage reads local validated data, not Yahoo.
- Manual Tool B data should be edited inside the tool, not mainly through CSV files.
- The user should be able to attach notes/comments to each stock.

This plan is intentionally conservative. It is not a rewrite-for-elegance plan. It is a controlled redesign to align the codebase with the actual product.

## 2. Core Product Decisions Now Locked

### Decision A: Remove Combined as a backend engine

Combined is no longer a core pipeline that computes:

- combined score
- combined rank
- combined verdict
- historical full-history merged outputs

Instead, Combined becomes a future compare view that shows Tool A and Tool B outputs next to each other.

Reason:

- the current Combined backend is more complex than the product needs
- the existing full-history join is structurally noisy
- the real user need is comparison, not a third scoring engine

### Decision B: Make market-data refresh explicit

The tool should not fetch Yahoo data during normal use.

The tool should work in two modes:

1. `Update Data`
   Fetch market data, normalize it, run QA, and publish validated local artifacts.

2. `Use Tool`
   Read local validated artifacts only.

Reason:

- this is a long-horizon analytics tool, not a live trading tool
- explicit refresh makes the app faster, more stable, and more reproducible
- outputs become easier to trust because they are tied to a known local data snapshot

### Decision C: Replace CSV-first Tool B manual inputs with a local app data store

CSV is no longer the intended end-user editing surface for:

- AISC
- production
- source/confidence
- reporting dates

CSV may remain as:

- a bootstrap import path
- an export path
- a developer convenience

But the product should treat manual Tool B data as local application data.

Reason:

- these values change slowly
- direct in-tool editing is a better workflow
- CSV editing is fragile and not the right permanent interface

### Decision D: Add per-stock notes/comments

The user must be able to store comments per stock independently from the numeric Tool B inputs.

Reason:

- notes are part of the real workflow
- notes should not pollute calculation fields
- notes should remain editable even when numeric inputs stay unchanged

## 3. What This Plan Does Not Try To Do

This plan does not aim to:

- redesign Tool A formulas
- redesign Tool B formulas
- introduce a web UI immediately
- rewrite every DataFrame flow into a typed class hierarchy
- optimize every pipeline for maximum speed before the product model is correct

This plan focuses on the product/runtime spine only.

## 4. Target End-State After This Redesign

The end-state product should behave like this:

### Update workflow

The user triggers an explicit market-data refresh.

That refresh:

- fetches equities, gold, FX, and market snapshots from Yahoo
- standardizes raw data
- normalizes to USD
- runs QA
- publishes stable validated local artifacts
- records an `as_of_date` or run snapshot date

### Analysis workflow

Tool A and Tool B run from those local validated artifacts by default.

They do not fetch Yahoo unless the user explicitly asks for refresh.

### Tool B manual-data workflow

The user edits slow-moving company inputs directly in the tool.

Those inputs are stored locally in an application data store.

### Notes workflow

The user can attach stock-specific notes/comments that are stored separately from the numeric inputs.

### Combined workflow

At the end of the roadmap, Combined returns as a lightweight view that reads the latest Tool A and Tool B outputs and shows them side by side.

It is not treated as an independent analytics engine.

## 5. High-Level Redesign Sequence

The redesign should happen in five controlled phases:

| Phase | Name | Goal |
| --- | --- | --- |
| 0 | Guardrails | Freeze current behavior with tests before changing runtime behavior |
| 1 | Runtime Shift | Move from always-fetch behavior to explicit refresh plus local-first usage |
| 2 | Combined Removal | Remove the Combined backend from the active product surface |
| 3 | Manual Data Store | Move Tool B manual inputs away from CSV-first operation |
| 4 | Reliability Hardening | Fix the still-important safety issues that remain after the runtime shift |
| 5 | Future Combined View | Reintroduce Combined later as a lightweight side-by-side view only |

Phases 0 to 4 are the real redesign. Phase 5 is intentionally later.

## 6. Phase 0: Guardrails

### Goal

Protect the working system before changing runtime behavior.

### Why this comes first

We already have a working tool. We should not refactor the product direction without locking in the current known-good behavior first.

### Work

- Add characterization tests for current `foundation`, `tool-a`, and `tool-b` flows.
- Add tests that prove the local artifact layout and latest snapshot behavior we want to preserve.
- Add tests that pin the current Tool A and Tool B published outputs at a contract level.

### Files likely affected

- [tests](C:/Users/Emanuel/code/Golden-Vector/tests)
- [golden_vector/ingestion/persist.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/persist.py)
- [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py)

### Acceptance criteria

- Existing Tool A and Tool B workflows remain green under test.
- We can safely remove Combined later without guessing whether Tool A or Tool B broke.

## 7. Phase 1: Runtime Shift To Explicit Refresh Plus Local-First Use

### Goal

Change the tool from:

- fetch on most command paths

to:

- refresh once explicitly
- use local validated data by default

### Product behavior after this phase

The expected command model becomes:

- `python main.py update-data`
- `python main.py tool-a`
- `python main.py tool-b --gold-price 4000`

Where:

- `update-data` is the command that touches Yahoo by default
- `tool-a` uses the latest validated local market-data artifacts
- `tool-b` uses the latest validated local market-data artifacts plus local manual inputs

### Why this phase matters

This is the biggest practical improvement to the product:

- faster everyday use
- more stable runs
- reproducible snapshots
- less dependence on Yahoo uptime and behavior during normal analysis

### Work

- Introduce or repurpose a single explicit refresh command, likely `update-data`.
- Make `tool-a` local-only by default.
- Make `tool-b` local-only by default.
- Ensure refresh publishes stable latest artifacts or a manifest that later commands can read.
- Ensure every local-use command fails cleanly if no validated local data exists yet.

### Files likely affected

- [main.py](C:/Users/Emanuel/code/Golden-Vector/main.py)
- [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py)
- [golden_vector/ingestion/foundation.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/foundation.py)
- [golden_vector/ingestion/persist.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/persist.py)
- [golden_vector/app/run_context.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app/run_context.py)

### Acceptance criteria

- A normal Tool A run does not fetch Yahoo.
- A normal Tool B run does not fetch Yahoo.
- A user can refresh data once, then use Tool A and Tool B repeatedly from local artifacts.
- The tool clearly exposes the snapshot date used by Tool A and Tool B.

## 8. Phase 2: Remove Combined From The Active Backend

### Goal

Remove the current Combined backend pipeline from the active product because it is not the right shape for the product we now want.

### Why this phase matters

The current Combined layer adds:

- unnecessary backend logic
- unnecessary maintenance burden
- a misleading sense of third-engine precision

And it does not match the actual goal, which is side-by-side inspection.

### Work

- Remove the active `combined` CLI command.
- Remove Combined-specific pipeline orchestration from the main runtime path.
- Remove Combined output publishing from normal product outputs.
- Remove or archive Combined tests that validate the old backend behavior.
- Update docs so the repo clearly treats Combined as a future view, not an active engine.

### Files likely affected

- [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py)
- [golden_vector/combined](C:/Users/Emanuel/code/Golden-Vector/golden_vector/combined)
- [tests](C:/Users/Emanuel/code/Golden-Vector/tests)
- [README.md](C:/Users/Emanuel/code/Golden-Vector/README.md)
- [docs/golden_vector_architecture_map.md](C:/Users/Emanuel/code/Golden-Vector/docs/golden_vector_architecture_map.md)
- [reviews/codex/golden_vector_master_plan.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/golden_vector_master_plan.md)

### Acceptance criteria

- Tool A and Tool B still work cleanly after Combined removal.
- The user-facing docs no longer describe Combined as an active backend engine.
- There is no longer a need to maintain combined scores, combined ranks, or combined verdict logic in the active codebase.

## 9. Phase 3: Replace CSV-First Manual Inputs With A Local Manual Data Store

### Goal

Move Tool B manual inputs from CSV-first operation toward a proper local application data layer.

### Recommended storage choice

Use a local SQLite store.

Reason:

- SQLite is a good fit for slow-moving structured records
- it is safer and more expressive than CSV for direct editing
- it supports notes/comments cleanly
- it is easy to query, test, export, and migrate

### Data entities to support

#### Company inputs

One record per stock for fields such as:

- ticker
- AISC
- production
- source
- source date
- confidence
- last updated date

#### Notes/comments

Separate records from company inputs, so notes do not mix with calculation fields.

Fields should include at least:

- ticker
- note text
- created at
- updated at
- optional tag/status

### Work

- Define the local schema for Tool B company inputs.
- Define the local schema for stock notes.
- Build a migration path from the current CSV files into the new store.
- Make Tool B read from the local store instead of treating CSV as the primary source.
- Keep CSV import/export only as optional support paths if still useful.

### Files likely affected

- [golden_vector/screening/manual_data.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/manual_data.py)
- [golden_vector/screening/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/pipeline.py)
- new local-store module, likely under `golden_vector/screening/` or `golden_vector/app/`
- [data/manual](C:/Users/Emanuel/code/Golden-Vector/data/manual)

### Acceptance criteria

- Tool B can run entirely from local application data plus validated market-data artifacts.
- Manual CSV editing is no longer the main user workflow.
- Users can store and retrieve notes/comments per stock.

## 10. Phase 4: Reliability Hardening That Still Matters

### Goal

Fix the real safety issues that remain relevant even after the product direction changes.

### Why this phase still matters

These issues are not about elegance. They are about trust:

- brittle market snapshot parsing
- stale FX being used without clear labeling
- side effects on manual data during normal runs

### Work

#### A. Make normal Tool B runs read-only with respect to manual data

Normal execution must not rewrite user-owned company-input records as a side effect.

#### B. Harden market snapshot parsing

Snapshot parsing should produce explicit invalid-status rows or warnings instead of relying on exceptions and optimistic assumptions.

#### C. Add FX staleness control

Add config-driven FX freshness rules such as:

- `max_fx_staleness_days`
- warn/fail behavior in QA

Rows using FX older than that threshold should be labeled clearly.

### Files likely affected

- [golden_vector/screening/manual_data.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/manual_data.py)
- [golden_vector/ingestion/standardize.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/standardize.py)
- [golden_vector/normalize/calendar.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/normalize/calendar.py)
- [golden_vector/normalize/prices_usd.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/normalize/prices_usd.py)
- [golden_vector/normalize/market_snapshot.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/normalize/market_snapshot.py)
- [golden_vector/qa/normalization_quality.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/qa/normalization_quality.py)
- [config/qa.yaml](C:/Users/Emanuel/code/Golden-Vector/config/qa.yaml)

### Acceptance criteria

- Normal Tool B execution no longer mutates manual input storage.
- Snapshot parsing degrades gracefully on malformed Yahoo payloads.
- FX staleness is visible, testable, and governed by config.

## 11. Phase 5: Future Combined View At The End

### Goal

Bring Combined back only after the product model is correct, and only as a lightweight compare view.

### Intended shape

The future Combined view should:

- read the latest Tool A published output
- read the latest Tool B published output for a chosen gold scenario
- join on ticker
- display selected Tool A and Tool B fields side by side

This should not require:

- a combined score by default
- a combined verdict by default
- a full-history combined pipeline

### Acceptance criteria

- Combined is a view layer, not a third analytics engine.
- The output is easy to inspect and explain.
- The join is latest-first and one-row-per-stock by default.

## 12. Recommended Implementation Order

This is the recommended order of execution:

1. Phase 0: Guardrails
2. Phase 1: Runtime shift
3. Phase 2: Combined removal
4. Phase 4: Reliability hardening
5. Phase 3: Manual data store
6. Phase 5: Future Combined view

### Why this order

This order prioritizes:

1. preserving working behavior
2. fixing the runtime model first
3. removing unnecessary backend complexity early
4. keeping real reliability fixes
5. only then rebuilding the Tool B manual-data experience properly

Phase 3 is intentionally placed after the runtime shift because it is a real product improvement, but it is bigger than the immediate runtime correction.

## 13. Risk Management

### Risks this redesign reduces

- over-fetching and rebuilding market data unnecessarily
- dependence on Yahoo during normal analysis
- maintenance burden from an unnecessary Combined backend
- fragile CSV-based manual workflows
- lack of a proper place for stock notes/comments

### Risks this redesign introduces

- migration complexity from CSV to local app storage
- temporary doc drift while Combined is being removed
- need for clear local-artifact and manifest semantics

### Mitigation

- add regression tests first
- remove Combined only after Tool A and Tool B local-first flows are protected
- keep CSV import/export available during the migration period

## 14. What Success Looks Like

The redesign is successful when the tool behaves like this:

1. The user clicks or runs `Update Data`.
2. The tool fetches market data, validates it, and stores a dated local snapshot.
3. The user opens Tool A repeatedly without re-fetching Yahoo.
4. The user opens Tool B repeatedly without re-fetching Yahoo.
5. The user edits AISC/production and notes directly in the tool.
6. The user can inspect Tool A and Tool B results independently.
7. Combined no longer exists as heavy backend logic.
8. Later, a side-by-side compare view can be added cleanly at the presentation layer.

## 15. Recommended Next Action

Before changing the code, the next action should be:

- approve this redesign direction explicitly
- then start with Phase 0 and Phase 1 only

That keeps the first execution slice focused and low-risk.
