# Codex Holistic Review — 2026-04-24 (post-DataTables)

## Bottom-line paragraph

Yes: this is still a coherent tool, not a pile of unrelated features. The core shape still makes sense end to end: `update-data` publishes one local normalized backbone, Tool A and Tool B both read from it, Tool B parity/backfill stayed inside the screening/manual-data system, and the DataTables layer mostly respected the new “Python owns HTML/data attributes; JS owns DataTables” rule. The codebase is showing **strain**, but not **collapse**. The strain is concentrated in the workspace layer and in one important Tool A trust issue: the published “latest” Tool A snapshot can silently drop an active ticker if that ticker’s most recent complete weekly bar lags the rest of the universe. So my verdict is: **healthy enough to use, but now at the point where simplification and trust-hardening matter more than more features.**

## Top 5 findings

### 1. Tool A “latest snapshot” is not universe-stable — P1

**Where:** [golden_vector/ingestion/persist.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/persist.py:368), [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:119), live output [tool_a_latest.parquet](C:/Users/Emanuel/code/Golden-Vector/data/output/tool_a/tool_a_latest.parquet)

**What is happening:** the persisted “latest” Tool A snapshot is defined as “rows whose `as_of_date` equals the global max `as_of_date`.” That sounds reasonable, but in practice it means an active ticker can vanish from the latest overview if its most recent complete weekly bar lags by one week. Right now that is happening to `VAU.AX`: the active universe has 60 Tool A tickers, but latest Tool A has 59 rows. `VAU.AX` is still present in full Tool A history, but its latest structural row is `2026-04-17`, not `2026-04-24`, because its normalized daily history ends on `2026-04-24` with `MISSING_RETURN_BASIS`.

**Why this matters:** this is not just a missing row. It creates a product-trust problem. Emanuel sees “60 active tickers” in the universe and Tool B, but only 59 in Tool A latest. That makes the tool feel inconsistent even when the math is technically doing what the code says.

**What to change:** define official Tool A “latest” more explicitly. The clean options are:
- latest **common** structural week across the active Tool A universe
- or latest per-ticker row **plus** a visible stale flag

What I would not keep is the current silent global-max cut.

**Rough fix size:** medium

### 2. `workspace.py` is now the single biggest technical-debt concentration — P1

**Where:** [golden_vector/serve/workspace.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:178) through [workspace.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:3103)

**What is happening:** the workspace file is now carrying routing, state loading, provenance warnings, Tool A detail logic, Tool B editing, chart SVG rendering, static-file serving, overview filtering, and HTML helpers in one place. It still works, but it is the obvious place where every new feature is colliding.

**Why this matters:** this file is no longer “thin presentation.” It is the main product shell. That is not a crash risk today, but it is the clearest reason the repo will get harder to change next month.

**What to change:** split by natural responsibility, not by arbitrary file count:
- request routing + state loading
- overview pages (`/`, `/tool-a`, `/tool-b`)
- ticker detail page
- shared HTML/render helpers
- static helpers

I would not rewrite the workspace. I would split it surgically.

**Rough fix size:** medium/large

### 3. The Combined overview now has two control planes, and the UX hierarchy is muddy — P2

**Where:** [golden_vector/serve/workspace.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:799), [workspace.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:820), [workspace.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:909), [golden_vector/serve/static/workspace-tables.js](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/static/workspace-tables.js:1)

**What is happening:** the “augment server-side controls, never replace” rule is still technically intact, but the Combined view is now carrying:
- a server-side overview form (`search`, `profile`, `verdict`, `confidence`, `sort`)
- the lens selector / lens hint
- a client-side DataTables filter bar (`profile`, `confidence`, `volatility`, `verdict`)
- client-side header sorting

That is a lot of control surface on one page.

**Why this matters:** this is not a code-architecture failure. It is a product-coherence issue. The tool is still understandable, but the Combined page is now the closest thing to “two ways to do the same thing.”

**What to change:** keep the server-side controls, but make the hierarchy explicit:
- server-side controls decide the dataset / lens
- DataTables controls are only local table convenience

If needed, simplify the Combined server form rather than adding more client controls.

**Rough fix size:** small/medium

### 4. The DataTables layer landed with a clean architecture, but the test strategy is still one layer too low — P2

**Where:** [golden_vector/serve/static/workspace-tables.js](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/static/workspace-tables.js:1), [tests/test_workspace_datatables.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_workspace_datatables.py:1)

**What is happening:** the current tests do a good job proving:
- static assets are served safely
- HTML carries the right `data-*` contract
- filter bars are derived from rendered data

What they do **not** prove is the actual in-browser behavior of the DataTables layer.

**Why this matters:** for a local UI, that is acceptable for now, but it is now a real blind spot because the workspace is no longer a thin novelty layer; it is the main daily-use surface.

**What to change:** add one very small browser-level smoke path later. Not a huge suite. Just enough to prove:
- table initializes
- one sort works
- one dropdown filter works
- one global search works

**Rough fix size:** medium

### 5. Legacy and one-shot surfaces are still contained, but they are starting to accumulate maintenance weight — P3

**Where:** [golden_vector/combined](C:/Users/Emanuel/code/Golden-Vector/golden_vector/combined), [golden_vector/contracts/data_models.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/contracts/data_models.py:232), [config/scoring.yaml](C:/Users/Emanuel/code/Golden-Vector/config/scoring.yaml), [scripts/sync_universe_tiers_from_excel.py](C:/Users/Emanuel/code/Golden-Vector/scripts/sync_universe_tiers_from_excel.py:1), [scripts/backfill_manual_data_from_excel.py](C:/Users/Emanuel/code/Golden-Vector/scripts/backfill_manual_data_from_excel.py:1), [docs/golden_vector_architecture_map.md](C:/Users/Emanuel/code/Golden-Vector/docs/golden_vector_architecture_map.md:79)

**What is happening:** none of these are breaking the tool, but they show the typical “fast milestone” residue:
- legacy Combined code still exists, plus some Combined-related config still lives in active models
- `ToolBOutput` is in sync with live parquet but is documentation-only, not runtime-enforced
- the Excel sync/backfill scripts are useful, but clearly one-off
- top-level docs are already drifting (`170 passing tests` is stale; the suite is at 282)

**Why this matters:** today this is manageable. In a month it becomes “which thing is canonical?”

**What to change:** quarantine the old/one-shot surfaces more clearly, and do a doc/config cleanup pass after the next product milestone rather than letting them keep drifting.

**Rough fix size:** small/medium

## Technical-debt catalog

| Item | Severity | Fix-when | Notes |
|---|---|---|---|
| `workspace.py` monolith | High | Next workspace milestone | Biggest single debt item in the repo |
| Tool A latest snapshot uses global max `as_of_date` | High | Next Tool A trust pass | Causes silent latest-row omission for lagging tickers |
| Combined page has overlapping server + client control surfaces | Medium | Next UX cleanup | Rule is still intact, but the page is close to overload |
| DataTables behavior is only contract-tested, not browser-tested | Medium | When touching workspace again | Good enough now, but likely next regression vector |
| Docs drift (`README`, architecture map) | Medium | Next documentation pass | Architecture map still says `170 passing tests` and “Serve/dashboard started” |
| `combined_verdict_thresholds` still lives in active scoring config | Low/Medium | When cleaning legacy Combined residue | Active Tool A uses `scoring.yaml`, but that subsection is legacy-only |
| `ToolBOutput` is synced but not runtime-enforced | Low/Medium | When contract enforcement becomes useful | Fine today; just don’t assume it validates live parquet automatically |
| `sync_universe_tiers_from_excel.py` is a line-based YAML rewriter | Medium | Before next major universe sync | Safe enough for current file shape, brittle as a general tool |
| `backfill_manual_data_from_excel.py` is repo-worthy history, but workbook-shape dependent | Medium | Before next backfill cycle | Keep it, but treat it as migration tooling, not product runtime |
| Review/docs/process files are growing | Low | When consolidating handoff docs | Not a repo-health problem yet, but the canonical docs should stay obvious |

## What NOT to change

- Do **not** collapse Tool A official structural metrics back into the exploratory horizon ladder. The current split is correct.
- Do **not** reintroduce CSV as the primary Tool B workflow. SQLite as the source of truth is the right product shape.
- Do **not** move the friend-ticker mapping into runtime code. Keeping it import-side in [scripts/friend_excel_import.py](C:/Users/Emanuel/code/Golden-Vector/scripts/friend_excel_import.py) is correct.
- Do **not** delete `compute_tool_b_in_memory`. It is the right shared seam between the persistent Tool B pipeline and the workspace override view.
- Do **not** let Python drift back into hand-assembling DataTables logic. The generic [workspace-tables.js](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/static/workspace-tables.js) pattern is the right architecture.
- Do **not** replace server-side controls with DataTables-only behavior. The current rule — augment, don’t replace — is still the right one.
- Do **not** create a second source of truth for jurisdiction tiers. [config/universe.yaml](C:/Users/Emanuel/code/Golden-Vector/config/universe.yaml) should remain canonical after the parity work.
- Do **not** prune the inactive legacy fixture tickers just because they look odd. They are still load-bearing test/data fixtures.

## Answers to the 6 concrete questions

1. **Single biggest technical debt item**

   `workspace.py` is the single biggest technical debt item. It still works, but it is now the place where every UI/product concern is converging, and it is large enough that “just one more small change” will keep getting more expensive.

2. **Single biggest product risk**

   The single biggest product risk is **trust drift in Tool A latest output**. Right now a perfectly valid active ticker (`VAU.AX`) can disappear from the latest Tool A snapshot because one trailing daily row breaks weekly completeness. That makes the product look inconsistent even though the underlying data/history still exists.

3. **Is the "augment server-side controls, never replace" rule still intact on every view?**

   **Yes, technically it is still intact on all three overview views.**

   - `/tool-a`: server-side search still exists; DataTables adds local sorting/filtering.
   - `/tool-b`: server-side search + override form still exist; DataTables adds local sorting/filtering.
   - `/`: server-side overview form + lens selector still exist; DataTables adds local sorting/filtering.

   The rule is not broken. The issue is that the Combined page is now the closest thing to “too many surfaces,” so the hierarchy should be made clearer.

4. **Does the `universe.yaml` / manual-store / parquet schema triple have any silent inconsistency?**

   **Mostly no — it is healthier than I expected.**

   What I checked:
   - active Tool B universe = 60 tickers
   - manual store coverage = 60/60 active tickers populated
   - Tool B latest parquet = 60 rows, no active-missing tickers
   - manual store orphans are the intentional inactive fixture tickers (`GOLD`, `FNV`, `FRES.L`)

   The one meaningful inconsistency is **Tool A latest**, not Tool B:
   - active Tool A universe = 60
   - Tool A latest parquet = 59 rows
   - missing active ticker = `VAU.AX`

   Also: `ToolBOutput` in [data_models.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/contracts/data_models.py) is **documentation-only**, but at review time it still matched the live Tool B parquet schema exactly.

5. **Readiness for a real-use week**

   **Yes, with one caveat.**

   If Emanuel runs `refresh` every morning for a week, I do **not** expect the whole system to fall apart. The local-first runtime, Tool B manual-data store, and status summary all look strong enough for real use.

   The caveat is Tool A trust/readability:
   - latest ticker counts can drift if one ticker lags structurally
   - the workspace is usable, but the main UI shell is carrying a lot of complexity in one file

   So my answer is: **ready enough to use, not yet finished enough to stop simplifying**.

   I did not run a live `refresh` in this pass because that would mutate market-data outputs; this answer is based on the passing suite, `status`, code inspection, and live artifact inspection.

6. **The "simple first" rule — is there a surface that violates it?**

   **Yes: the workspace rendering layer is the clearest violation.**

   Not because it is “wrong,” but because too much product logic now lives in one place. The DataTables layer itself is actually a good example of the rule being followed. The place where the repo is drifting away from “simple first” is the overall workspace shell, especially the Combined overview page.

## Process / meta

- The recent review loops were worth it. The DataTables layer is noticeably cleaner because the team stepped back from the earlier over-built design and moved to one generic JS file driven by HTML attributes.
- The repo does **not** look like it needs a rewrite. It looks like it needs one consolidation cycle.
- The next high-value work is not more feature invention. It is:
  1. fix Tool A latest-snapshot semantics
  2. split the workspace at the natural seams
  3. clean stale docs / legacy config residue
- I tried to hit the live workspace shell from `http://127.0.0.1:8765` during this review, but the shell-side probe was not reliable in this session, so I am not claiming a browser-click review here. This verdict is based on the repo state, test suite (`282 passed`), `python main.py status`, live parquet/manual-store inspection, and direct code inspection.

Three quick answers from the deeper code tour that are worth preserving:
- The old “max-of-6 Tool B targets” mental model does **not** appear to be driving active runtime anymore. The active Tool B path is aligned around the current four scenarios.
- `tool_b_score` consuming `best_upside_pct` is still acceptable for v1 because the score is now secondary to verdict + the four visible scenario columns. It is a coarse ranking helper, not the real analysis layer.
- I found **no obvious hard-coded assumption** that the universe is still the original 8-ticker starter set. The active runtime is using dynamic counts and active-ticker config as expected.
