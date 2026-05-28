# Holistic Review Request — Full Codebase

Date: 2026-04-24
Requester: Emanuel (via Claude Opus 4.7)
Reviewer: Codex
Mode: Read-only, thorough

## Why this review

We've shipped a lot in the last few days. Emanuel wants an independent holistic pass — not to find every bug, but to answer the question **does this codebase still make sense as a coherent tool?** He's less interested in micro-nits, more interested in structural health.

Prior holistic review was [claude_review_request_holistic_repo_check_2026-04-23.md](claude_review_request_holistic_repo_check_2026-04-23.md) a day ago. Between then and now we've added:

- Tool B parity milestone (jurisdiction tiers synced, ARIS.TO fix, four target-price scenarios, screening-parameters override panel, in-memory recompute seam)
- Manual data backfill for 56 tickers from the friend's Excel
- DataTables layer (click-sort, filter dropdowns, global search) on all three overview views via one generic `workspace-tables.js`
- Centralized `scripts/friend_excel_import.py` for workbook ingestion mapping
- Several small review-loop iterations

Approximate current shape: **64 Python source files / ~14,600 lines**, **43 test files / ~8,500 lines**, **282 tests passing**.

## What I want from you

Four outputs, in order of importance:

1. **A single-paragraph answer** to: *"Is this still a coherent tool, or is it starting to show drift / bloat / inconsistency?"* Blunt is fine. Emanuel would rather hear "the Tool B pipeline has three overlapping code paths that should be one" than "looks good."

2. **Top 5 findings, priority-ordered.** P0/P1/P2/P3 each. Either serious bugs, serious tech debt, or serious product risk. If there aren't 5, list fewer.

3. **A technical-debt catalog.** Things that are fine today but will bite us in a month. Dead code paths, brittle tests, deprecated config knobs, README/docstring drift, security questions, performance ceilings.

4. **"What NOT to change"** — call out parts of the codebase that look weird but are actually load-bearing or intentional, so I don't go pruning the wrong thing later.

## What to review

A suggested tour. Spend the time where the friction is, skip where things are clean.

### Core pipeline — Is the math still coherent end-to-end?

- Foundation: [golden_vector/ingestion/foundation.py](golden_vector/ingestion/foundation.py) + persistence + raw QA
- Tool A structural: [golden_vector/model/structural.py](golden_vector/model/structural.py), [golden_vector/model/pipeline.py](golden_vector/model/pipeline.py)
- Tool B: [golden_vector/screening/pipeline.py](golden_vector/screening/pipeline.py), [layer1.py](golden_vector/screening/layer1.py), [layer2.py](golden_vector/screening/layer2.py), [targets.py](golden_vector/screening/targets.py), [verdicts.py](golden_vector/screening/verdicts.py), [ranking.py](golden_vector/screening/ranking.py)
- In-memory Tool B recompute: same `pipeline.py`, `compute_tool_b_in_memory` — is the seam still clean or has it diverged from the persistent path?

Specific questions:
- The four-scenario target-price split landed a while back. Any residual code that still behaves as though the max-of-6 mental model is canonical?
- `tool_b_score` still consumes `best_upside_pct` (max of 4). We accepted that semantics explicitly. Is it still the right call, or has the scenario split made it obsolete?
- Does any part of the code rely on implicit assumptions about the universe being 8 tickers (the original starter set) vs 59 active today?

### Workspace / serving — Does the separation of concerns actually hold?

- [golden_vector/serve/workspace.py](golden_vector/serve/workspace.py) (~3000 lines — biggest file in the repo)
- [golden_vector/serve/static/workspace-tables.js](golden_vector/serve/static/workspace-tables.js)
- [golden_vector/serve/screening_overrides.py](golden_vector/serve/screening_overrides.py)
- [golden_vector/serve/lenses.py](golden_vector/serve/lenses.py)

Specific questions:
- `workspace.py` is large. Is it cohesive or is it time to split? If split, what's the natural seam?
- Does the "Python owns HTML + data attributes; JS owns DataTables" rule hold globally now, or is there any sneaky inline-JS drift back toward Python?
- The Combined view's server-side filter form (`_render_overview_filters_form`) overlaps with the new DataTables filter bar. Is there user confusion risk now that there are two independent filter surfaces on the same page?
- Are all three views (`/`, `/tool-a`, `/tool-b`) consistent in: filter bar wiring, numeric-cell `data-order`, navigation hints, scenario override plumbing?

### Config + data integrity

- [config/universe.yaml](config/universe.yaml), [config/screening_params.yaml](config/screening_params.yaml), [config/scoring.yaml](config/scoring.yaml), etc.
- [golden_vector/contracts/config_models.py](golden_vector/contracts/config_models.py), [contracts/data_models.py](golden_vector/contracts/data_models.py)
- SQLite manual store schema: [golden_vector/screening/manual_store.py](golden_vector/screening/manual_store.py)
- Parquet outputs under `data/output/`

Specific questions:
- `data_models.py` has `ToolBOutput` — is it actually imported anywhere or is it documentation-only? If the latter, should it stay in sync with the real parquet schema?
- After the Tool B parity backfill, does the SQLite store still have any stale / orphaned rows? Check by comparing `company_inputs.ticker` with `universe.yaml` active tickers.
- Is `config/scoring.yaml` still in use, or superseded by `config/screening_params.yaml`?

### CLI surface

Commands to exercise: `update-data`, `foundation` (alias), `tool-a`, `tool-b`, `refresh`, `status`, `workspace`, `manual-data {init,show,set-company,set-reporting,set-verification,import-csv,export-csv}`, `manual-note {add,list}`, `compare-horizons`.

- Does `python main.py refresh` actually do the right thing end-to-end?
- `status` summary — any reporting gap given the data now has 60+ tickers?
- Is anything in `cli.py` unreachable or deprecated?

### Test suite

282 tests across 43 files. We're not looking for "are there enough tests" — we're looking for:
- Blind spots (end-to-end paths that no test covers)
- Brittle tests (will break on trivial refactors)
- Over-tested areas (three tests proving the same thing)
- Tests that pass but don't actually prove the product works

### Backfill scripts

- [scripts/friend_excel_import.py](scripts/friend_excel_import.py)
- [scripts/sync_universe_tiers_from_excel.py](scripts/sync_universe_tiers_from_excel.py)
- [scripts/backfill_manual_data_from_excel.py](scripts/backfill_manual_data_from_excel.py)

They were one-shots but they live in the repo now. Should they be?

### Documentation

- [README.md](README.md) — is it accurate after all the changes?
- [CLAUDE.md](CLAUDE.md) — Claude-code working rules, still current?
- `docs/` folder if any
- Review files under `reviews/codex/` — does the size of this folder start to hurt signal-to-noise?

## Concrete questions I want answered

1. **Single biggest technical debt item.** One answer, pick one.
2. **Single biggest product risk.** What could make this tool stop being useful for Emanuel? (E.g., a Yahoo data assumption we depend on, a friend-Excel divergence, a silent math drift.)
3. **Is the "augment server-side controls, never replace" rule still intact on every view**, or did DataTables quietly take over somewhere it shouldn't?
4. **Does the universe.yaml / manual-store / parquet schema triple have any silent inconsistency?** (E.g., a ticker in universe that has no manual data AND never will, or a manual row for a ticker that was removed from the universe.)
5. **Readiness for a real-use week.** If Emanuel just used this tool every day for a week and ran `refresh` every morning, would anything break or degrade?
6. **The "simple first" rule** we both added to memory last round — looking across the whole codebase, is there a surface that violates it that we should revisit?

## What NOT to dig into

Save your time:

- The `reviews/codex/` folder is by design a process artifact; don't score it for signal. But do flag if the review files themselves are now cluttering or contradicting each other.
- The `data/manual/screening/manual_screening.sqlite3.bak.2026-04-24` backup file is deliberate — safe to delete but no rush.
- The `.xlsx / .xlsm / .docx / .pdf` files at the repo root are research artifacts, not code. Ignore.
- The 3 legacy-fixture tickers (`GOLD`, `FNV`, `FRES.L`) in `universe.yaml` with `active: false` are intentionally there for test fixtures. Don't suggest removing them unless you find they're actually unused.
- Don't re-verify things from prior review cycles unless you see evidence they've regressed.

## Setup

```bash
python -m pytest -q                  # should be 282 passing
python main.py status                # current operational state
python main.py workspace             # http://127.0.0.1:8765
```

If you want to exercise the DataTables layer in a browser, click any header to sort, use the dropdowns on `/tool-b` to filter by verdict / layer 1, and try `/?lens=upside_torque` + click a header to confirm the lens-coexistence behavior works visually.

Also helpful before writing findings:

```bash
git log --oneline -30                # last few cycles of shipped work
wc -l golden_vector/serve/workspace.py   # single-file size check
```

## Output format

Write `reviews/codex/codex_holistic_review_2026-04-24_post_datatables.md` with:

```markdown
# Codex Holistic Review — 2026-04-24 (post-DataTables)

## Bottom-line paragraph

## Top 5 findings

### 1. [title] — [P0/P1/P2/P3]
(where, why, what to change, rough fix size)

### 2. ...

## Technical-debt catalog
(table preferred — item | severity | fix-when | notes)

## What NOT to change
(list)

## Answers to the 6 concrete questions
(numbered)

## Process / meta
(anything about how we've been working together that's worth flagging — honest take)
```

Take your time. Depth over breadth. If the answer to a question is "I don't know without running X," say so — don't guess.

Thanks.
