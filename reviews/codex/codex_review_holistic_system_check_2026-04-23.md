# Codex Holistic System Check — 2026-04-23

## Findings

### `P2` Top-level operator docs now disagree with the real workspace and Tool A artifact behavior

- [README.md](C:/Users/Emanuel/code/Golden-Vector/README.md:44) still says structural Tool A window metrics are written under `data/output/tool_a/`, but the code publishes the stable structural artifact to [golden_vector/app/paths.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app/paths.py:179) via [golden_vector/ingestion/persist.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/persist.py:194), which means `data/intermediate/tool_a_structural/tool_a_structural_latest.parquet`.
- [README.md](C:/Users/Emanuel/code/Golden-Vector/README.md:89) still tells the user to drop to the CLI to clear a company field, but the workspace now supports explicit per-field clearing with checkboxes in [golden_vector/serve/workspace.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:242) and [golden_vector/serve/workspace.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:1474).

Why this matters:
the code is more usable than the docs suggest, so the product will look clumsier and more confusing than it really is. This also causes future reviews to look in the wrong place for Tool A structural artifacts.

### `P2` The architecture map still teaches the old Tool A mental model

- [docs/golden_vector_architecture_map.md](C:/Users/Emanuel/code/Golden-Vector/docs/golden_vector_architecture_map.md:28) to [docs/golden_vector_architecture_map.md](C:/Users/Emanuel/code/Golden-Vector/docs/golden_vector_architecture_map.md:30) still show the official Tool A path as `normalization -> horizons -> horizon QA -> Tool A model`, even though Tool A is now structural-first and the horizon engine is exploratory only.
- [docs/golden_vector_architecture_map.md](C:/Users/Emanuel/code/Golden-Vector/docs/golden_vector_architecture_map.md:64) still points `tool-a` through `features/pipeline.py`, while the real runtime calls the structural Tool A pipeline directly from [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py:26) and [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py:488).
- [docs/golden_vector_architecture_map.md](C:/Users/Emanuel/code/Golden-Vector/docs/golden_vector_architecture_map.md:79) still says `170 passing tests`, while the current working tree passed `225` tests in this review run.

Why this matters:
the repo’s core logic is now cleaner than the architecture map implies. Leaving the old topology in place risks pushing future implementation and review work back toward the exploratory horizon layer as if it were still the official Tool A backbone.

### `P3` The codebase now has a better operational control surface than the docs advertise

- The CLI now has explicit `refresh` and `status` commands in [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py:67), [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py:91), [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py:1345), and [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py:1393).
- The top-level docs still teach mainly the older manual choreography (`update-data`, `tool-a`, `manual-data init`, `tool-b`, `workspace`) in [README.md](C:/Users/Emanuel/code/Golden-Vector/README.md:94) to [README.md](C:/Users/Emanuel/code/Golden-Vector/README.md:100) and do not explain when `refresh` and `status` are the better daily operator path.

Why this matters:
this is not a broken-code issue, but it does make the whole tool feel less coherent than it actually is. The runtime surface is now better than the operator guidance.

## What I Checked

- Current top-level docs and product docs:
  - [README.md](C:/Users/Emanuel/code/Golden-Vector/README.md)
  - [docs/golden_vector_architecture_map.md](C:/Users/Emanuel/code/Golden-Vector/docs/golden_vector_architecture_map.md)
  - [reviews/codex/claude_finish_v1_next_steps_plan.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_finish_v1_next_steps_plan.md)
- Current orchestration and runtime:
  - [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py)
  - [golden_vector/app/latest_data.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app/latest_data.py)
  - [golden_vector/app/paths.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app/paths.py)
- Current Tool A stack:
  - [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py)
  - [golden_vector/model/structural.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/structural.py)
  - [golden_vector/model/scoring.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/scoring.py)
  - [golden_vector/model/labels.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/labels.py)
  - [golden_vector/model/explanations.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/explanations.py)
- Current Tool B stack:
  - [golden_vector/screening/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/pipeline.py)
  - [golden_vector/screening/manual_store.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/screening/manual_store.py)
- Current workspace layer:
  - [golden_vector/serve/workspace.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py)
  - [golden_vector/serve/lenses.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/lenses.py)
- Persistence and artifact layout:
  - [golden_vector/ingestion/persist.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/persist.py)

## Validation

- Full test suite on the current working tree:
  - `python -m pytest -q`
  - Result: `225 passed`

## Overall Assessment

The repo is **coherent as a product**.

The main module boundaries make sense together now:

- `update-data` publishes one shared validated local snapshot.
- Tool A consumes that snapshot as the official structural model.
- Tool B consumes that snapshot plus the SQLite manual store.
- The workspace reads the published latest Tool A / Tool B outputs and adds presentation-only lenses.
- Provenance and local-first usage are now consistent enough that the tool behaves like one integrated product rather than two disconnected scripts.

I did **not** find a new whole-system integration defect in this pass. The main remaining issues are about documentation and operator guidance lagging behind the code.

## Verdict

**`READY WITH MINOR CHANGES`**

The codebase currently makes sense as a whole. Before the next milestone is called finished, I would update the README and architecture map so they match the product that now actually exists.

## Note

This review is a snapshot of the working tree on `2026-04-23` while Claude was actively coding. The integration verdict is therefore tied to the exact tree I validated here, including the `225 passed` test run above.
