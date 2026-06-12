# Safe Merge Handoff — Gold Dial Branch vs Current Option/Discovery Work

## Verdict

**Do not merge `m1-gold-dial` directly into `dev-vic` or `main`.**

This is a high-risk integration because the unmerged gold-dial work changes the
same data spine, refresh pipeline, Candidate Finder, Tool B UI, and persisted
artifact contracts that the recent option carry-forward / liquidity / column-help
work also changed.

A clean textual merge would not be enough. The main risk is logical drift:
schemas can still validate while readers show stale or wrong data; a manifest can
publish a coherent-looking state while one domain points at the wrong artifact;
and UI helpers can silently lose newer warnings or column help.

Claude: please improve this plan before starting the merge, then integrate through
a temporary branch with targeted contract checks.

## Current Branch State

As of this handoff:

| Branch / worktree | Commit | Merge state | Notes |
|---|---:|---|---|
| `main` | `81b7335` | current `origin/main` | Includes Milestone A carry-forward, B liquidity check, and D1 column-help first adopter. |
| `dev-vic` | `81b7335` | same as `origin/main` | Clean except local `AGENTS.md` memory update in the main worktree. |
| `m1-gold-dial` local worktree | `1849a1a` plus staged fixes | not merged | Contains gold-dial PR1-PR6 and staged verification fixes for fundamentals mapper/publish. |
| `origin/m1-gold-dial` | `993f955` | stale remote branch | Only contains PR1/PR2. Do **not** merge this remote alone; the local worktree has the later PR3-PR6 work. |

Merge base between current `main` and local `m1-gold-dial` is:

```text
db5cfbc docs: senior-engineer coding rules in CLAUDE.md/soul.md + plan/review/handoff artifacts
```

That means `m1-gold-dial` does **not** naturally include these later `main`
commits unless reconciled:

- `9f185d1` — Option snapshot carry-forward when publish gates block.
- `b831dfb` — Refuse mixed snapshot ids in carried option sets.
- `999994a` — Cached Liquidity Check medians cover tradable contracts only.
- `81b7335` — Column-help hover layer + Option Trading first adopter.

## What `m1-gold-dial` Adds

The branch is not just a UI branch. It changes core data contracts.

| Area | Main work in `m1-gold-dial` |
|---|---|
| Tool B spot gold | Persist canonical Tool B at dated spot gold; custom scenarios are isolated and do not publish latest aliases. |
| Tool B UI | Corporate Finance gold dial, fail-closed recompute, advanced assumptions panel. |
| Candidate Finder | Scenario injection for Tool B and Tool D frames, separate scenario cache. |
| Official fundamentals | New manifest-tracked official fundamentals artifact, raw Yahoo statements, mapper, resolver. |
| Yahoo fundamentals ingestion | Durable raw statement store, canonical mapper to net debt / EBITDA / D&A / interest / tax-rate handling. |
| Market vs Ours | Backend emits official-vs-our-view comparisons and status/rank fields; Tool B UI renders differences. |
| Model-state / pruning | Registers official fundamentals artifacts and protects them. |
| Staged verification fixes | Currency-basis mismatch, debt-leg/cash handling, annual labels, cross-period guards, full-outage latest-alias guard. |

## What Current `main` Adds Since the Branch Split

| Area | Main-line work that must survive |
|---|---|
| Option carry-forward | If live option signals fail quality gates, current core state can publish while options use the prior good snapshot. |
| Option snapshot identity | Carry-forward must refuse mixed snapshot ids across option artifacts. |
| Liquidity check | Cached Liquidity Check medians are based on tradable contracts only. |
| Column help | New `golden_vector/serve/column_help.py` and first adoption in Option Trading. |
| Option Trading warning/labels | Newer freshness and column-help UI must not be overwritten by older gold-dial serve code. |

## Highest-Risk Overlap

### 1. Model-State Manifest and Artifact Resolution

Files to inspect manually:

- `golden_vector/app/model_state.py`
- `golden_vector/cli.py`
- `golden_vector/contracts/option_artifacts.py`
- `golden_vector/contracts/fundamentals.py`
- `golden_vector/serve/option_trading_data.py`

Why dangerous:

- Option carry-forward introduced domain-specific freshness behavior for option artifacts.
- Gold dial introduces official fundamentals artifacts and scenario isolation.
- Both features rely on model-state artifact registration and current-state publishing.
- A bad merge can make the manifest look coherent while one domain silently points at stale, missing, or mutable aliases.

Must preserve:

- Core/current model-state remains the single pointer.
- Option artifacts can be carried forward when option publish gates block.
- Official fundamentals are optional but manifest-tracked and immutable.
- Scenario runs never advance latest aliases or the current model-state.
- Readers resolve through the manifest, not directly through mutable `latest` files.

### 2. Refresh Pipeline / CLI

Files to inspect manually:

- `golden_vector/cli.py`
- `golden_vector/fundamentals/fetch.py`
- `golden_vector/hedge/option_artifact_builder.py`
- `golden_vector/hedge/options_liquidity.py`

Why dangerous:

- Current `main` changed option-artifact behavior so option failures can be carried forward.
- Gold dial changes Tool B refresh behavior, adds `fetch-fundamentals`, and hardens official-fundamentals publish.
- Both affect when a full refresh is allowed to publish model-state.

Questions to answer before merging:

- Does full refresh run `fetch-fundamentals`? If yes, where in the sequence?
- If `fetch-fundamentals` fully fails, does it skip current aliases while keeping prior official fundamentals?
- If option signals fail, does it carry forward prior option artifacts and still publish core state?
- If both official fundamentals and option signals have degraded states, is the final status honest and visible?
- Are staged verification fixes in the local `m1-gold-dial` worktree committed before integration?

### 3. Candidate Finder

Files to inspect manually:

- `golden_vector/serve/candidate_finder_data.py`
- `golden_vector/serve/candidate_finder_page.py`
- `golden_vector/model/candidate_finder.py`
- `tests/test_candidate_finder_data.py`
- `tests/test_candidate_finder_page.py`

Why dangerous:

- Current main has Bull/Bear + Universe cleanup and option carry-forward behavior.
- Gold dial injects scenario Tool B/Tool D frames and a scenario cache.
- Candidate Finder is the user’s default home page and depends on Tool A/B/C/D plus option-derived fields.

Must preserve:

- Default path remains persisted current state, not scenario recompute.
- Scenario path uses injected backend frames and does not mutate current artifacts.
- Option carried-forward status is visible in Finder when option fields are stale.
- Bull/Bear presets and Universe toggle survive.
- No serve-side ranking math is introduced.

### 4. Tool B / Corporate Finance

Files to inspect manually:

- `golden_vector/screening/pipeline.py`
- `golden_vector/screening/schema.py`
- `golden_vector/screening/layer2.py`
- `golden_vector/screening/ranking.py`
- `golden_vector/serve/overview_tool_b.py`
- `golden_vector/serve/screening_overrides.py`
- `tests/test_tool_b_pipeline.py`
- `tests/test_tool_b_schema_contract.py`
- `tests/test_cli_tool_b.py`

Why dangerous:

- Gold dial adds spot provenance and official-vs-our-view fields.
- Current main has newer UI helper patterns and may expect different column-help / warning rendering.
- Tool B persisted schema changes are high risk because stale local parquets can pass partially and fail later.

Must preserve:

- Persisted Tool B canonical run is spot gold, not config default.
- Custom gold runs are run-stamped only and never become current.
- Official-vs-our values are computed backend-side.
- `financial_data_status` gates official rank eligibility.
- `CURRENCY_BASIS_MISMATCH` is reachable and excludes official rank.
- Old Tool B artifacts fail loud with a calm stale-data page.
- The gold dial and advanced assumptions recompute once and fail closed.

### 5. Official Fundamentals Data Store

Files to inspect manually:

- `golden_vector/contracts/fundamentals.py`
- `golden_vector/fundamentals/artifacts.py`
- `golden_vector/fundamentals/fetch.py`
- `golden_vector/fundamentals/mapper.py`
- `golden_vector/fundamentals/raw_store.py`
- `golden_vector/fundamentals/resolution.py`
- `golden_vector/ingestion/yahoo_client.py`
- `config/fundamentals.yaml`
- `tests/test_fundamentals_artifact_contract.py`
- `tests/test_fundamentals_fetch.py`

Why dangerous:

- This is new durable data infrastructure.
- It adds raw Yahoo statements under `data/raw/fundamentals/` and official mapped output under `data/output/fundamentals/`.
- It affects Tool B rank and comparison, but should never overwrite manual data.

Must preserve:

- Raw statements are immutable run-stamped plus latest convenience alias.
- Official fundamentals are manifest-tracked optional artifacts.
- Full Yahoo outage writes run-stamped evidence but does not advance latest/current.
- Missing debt leg is `MISSING`; missing cash is debt-only value but non-OK status.
- Annual statement fields are labeled `ANNUAL`, not fake `TTM`.
- Income/cashflow period mismatch degrades EBITDA/D&A.
- Statement currency vs feed currency mismatch is flagged as `CURRENCY_BASIS_MISMATCH`, never auto-converted silently.

### 6. Option Trading UI / Column Help

Files to inspect manually:

- `golden_vector/serve/overview_option_trading.py`
- `golden_vector/serve/detail_panels.py`
- `golden_vector/serve/option_signal_render.py`
- `golden_vector/serve/column_help.py`
- `golden_vector/serve/workspace.py`
- `tests/test_column_help.py`
- `tests/test_workspace_app.py`

Why dangerous:

- Current main added column-help and changed Option Trading display.
- `m1-gold-dial` branched before this and may have older serve rendering assumptions.
- A naive conflict resolution could drop the new explanations/freshness warnings.

Must preserve:

- Column-help helper exists and is used.
- Option Trading shows cached snapshot/freshness state clearly.
- No option calculations move into serve.
- Detail option panels still render signal cards/charts/scenarios.
- Carried-forward option data remains visibly labeled.

### 7. Tool D / Corporate Resilience

Files to inspect manually:

- `golden_vector/model/tool_d.py`
- `golden_vector/serve/overview_tool_d.py`
- `golden_vector/portfolio/*` if any Tool D columns are consumed there.

Why dangerous:

- Gold dial scenario injection uses Tool D in Candidate Finder.
- Tool D has a live gold-price override pattern that Tool B copied.
- Candidate Finder may join spot Tool D, scenario Tool D, and carried-forward option fields.

Must preserve:

- Persisted Tool D remains spot/current.
- Scenario Tool D is in-memory only.
- Finder scenario does not mutate persisted Tool D artifacts.
- Portfolio analytics that read Tool D columns are not broken by schema changes.

## Files Modified By `m1-gold-dial` That Overlap High-Risk Areas

Not exhaustive, but these are the first files to review conflict-by-conflict:

```text
golden_vector/app/config.py
golden_vector/app/model_state.py
golden_vector/app/paths.py
golden_vector/app/run_pruning.py
golden_vector/cli.py
golden_vector/common/numeric.py
golden_vector/contracts/config_models.py
golden_vector/contracts/fundamentals.py
golden_vector/hedge/option_artifact_builder.py
golden_vector/hedge/options_liquidity.py
golden_vector/model/tool_d.py
golden_vector/screening/pipeline.py
golden_vector/screening/ranking.py
golden_vector/screening/schema.py
golden_vector/serve/candidate_finder_data.py
golden_vector/serve/candidate_finder_page.py
golden_vector/serve/detail_panels.py
golden_vector/serve/model_state_banner.py
golden_vector/serve/option_signal_render.py
golden_vector/serve/option_trading_data.py
golden_vector/serve/overview_option_trading.py
golden_vector/serve/overview_tool_b.py
golden_vector/serve/overview_tool_d.py
golden_vector/serve/screening_overrides.py
golden_vector/serve/workspace.py
```

## Required Integration Sequence

### Step 0 — Freeze and Inventory

1. Ensure current `main` and `dev-vic` are at `81b7335` or newer.
2. Commit or intentionally park the `AGENTS.md` memory update.
3. In the `m1-gold-dial` worktree, commit the staged verification fixes first.
4. Confirm there are no untracked source/test files in either worktree except intentional review docs.
5. Record:
   - `git worktree list`
   - `git branch --all --no-merged origin/main`
   - `git log --oneline origin/main..m1-gold-dial`

### Step 1 — Create Integration Branch From Current Main

Create a temporary branch from current `main`, for example:

```text
integration/gold-dial-after-option-d1
```

Do not merge directly into `dev-vic`.

### Step 2 — Merge Local `m1-gold-dial`, Not Remote `origin/m1-gold-dial`

Use the local branch/worktree state after staged fixes are committed.

Reason: `origin/m1-gold-dial` only has PR1/PR2. The local branch has the full PR1-PR6 work and verification fixes.

### Step 3 — Resolve Conflicts By Product Contract, Not By "Keep Mine/Ours"

Conflict-resolution rules:

- If conflict touches option carry-forward, preserve current `main` behavior unless gold-dial adds strictly compatible manifest metadata.
- If conflict touches Tool B spot/gold dial, preserve gold-dial behavior.
- If conflict touches official fundamentals, preserve gold-dial behavior but ensure it fits current model-state publish rules.
- If conflict touches column help or Option Trading display, preserve current `main` D1 behavior and adapt gold-dial additions around it.
- If conflict touches Candidate Finder, preserve Bull/Bear/Universe UX from current `main` and add gold scenario injection behind it.
- If conflict touches shared helper logic, use the common helper and delete duplicate variants.

### Step 4 — Contract Tests Before Full Suite

Run focused tests first:

```text
python -m pytest tests/test_cli_refresh_and_status.py -q
python -m pytest tests/test_option_carry_forward.py tests/test_tradable_liquidity.py -q
python -m pytest tests/test_fundamentals_artifact_contract.py tests/test_fundamentals_fetch.py -q
python -m pytest tests/test_tool_b_pipeline.py tests/test_tool_b_schema_contract.py tests/test_cli_tool_b.py -q
python -m pytest tests/test_candidate_finder_data.py tests/test_candidate_finder_page.py -q
python -m pytest tests/test_column_help.py tests/test_workspace_app.py -q
```

Then run:

```text
ruff check golden_vector tests
python -m pytest -q
```

### Step 5 — Refresh / Smoke Test

After tests pass, run a real local smoke flow.

Minimum:

1. `python main.py status`
2. `python main.py refresh`
3. If refresh is outside US options hours, confirm:
   - core artifacts publish;
   - options carry forward;
   - model-state says options are carried forward, not live.
4. Start workspace.
5. Inspect:
   - `/`
   - `/tool-b`
   - `/tool-d`
   - `/option-trading`
   - `/ticker/AEM?lens=option-trading`

### Step 6 — Manual UI Checks

Check these by eye:

- Candidate Finder still has Bull/Bear and Universe controls.
- Candidate Finder warns if option data is carried forward.
- Option Trading still has column-help/freshness wording.
- Corporate Finance shows gold dial.
- Corporate Finance shows Market/API vs Ours comparison.
- Corporate Finance "Rank by Official" sorts names with missing/degraded official data last.
- Tool B stale-schema page is calm and actionable.
- Ticker detail option lens still renders option scenarios/charts.

## Specific Failure Modes To Watch For

### Failure Mode A — Option carry-forward lost

Symptom:

- Refresh before US options open blocks whole model-state again.

Cause:

- Gold-dial `cli.py` merge overwrote option carry-forward publish behavior.

Test/guard:

- `tests/test_option_carry_forward.py`
- Real refresh outside US options hours.

### Failure Mode B — Official fundamentals latest alias advances on outage

Symptom:

- Yahoo fundamentals outage overwrites good `fetched_fundamentals_latest.parquet`.

Cause:

- Staged verification fix in `m1-gold-dial` not included or conflict-resolved away.

Test/guard:

- `tests/test_fundamentals_fetch.py` full-outage test.

### Failure Mode C — UI shows stale options as live

Symptom:

- Option Trading uses carried-forward option artifacts but no freshness box/warning.

Cause:

- Serve layer reads option frames but ignores option freshness domain metadata.

Test/guard:

- Workspace render test for carried-forward option state.
- Manual `/option-trading` smoke check.

### Failure Mode D — Candidate Finder scenario cache leaks across gold prices

Symptom:

- Finder scenario at one gold price reuses rows from another gold price.

Cause:

- Cache key conflict between file-hash default cache and value-keyed scenario cache.

Test/guard:

- Candidate Finder scenario cache tests.
- Manual two-price Finder smoke check.

### Failure Mode E — Tool B official rank includes degraded API data

Symptom:

- Official rank calculated even when official fundamentals are stale/missing/currency-mismatched.

Cause:

- `financial_data_status` gate lost in merge.

Test/guard:

- `tests/test_tool_b_pipeline.py` degraded official data and currency-basis mismatch tests.

### Failure Mode F — Column help disappears

Symptom:

- Option Trading criterion/field explanations revert to raw field names or no help.

Cause:

- `m1-gold-dial` older serve files overwrite D1 column-help work.

Test/guard:

- `tests/test_column_help.py`
- Manual Option Trading page check.

### Failure Mode G — Schema appears valid but old data is semantically stale

Symptom:

- Page renders with missing new fields or incorrect assumptions after merge.

Cause:

- Required schema columns not updated, or stale parquet accepted.

Test/guard:

- Schema contract tests.
- Full refresh after merge.
- Calm stale-artifact 503 tests.

## Proposed Merge Order

1. Claude finishes any active review and ensures `main/dev-vic` are clean at or after `81b7335`.
2. Codex/Claude commit staged `m1-gold-dial` verification fixes in the `m1-gold-dial` worktree.
3. Create `integration/gold-dial-after-option-d1` from `main`.
4. Merge local `m1-gold-dial`.
5. Resolve conflicts with the product-contract rules above.
6. Run focused contract suites.
7. Run full suite.
8. Run refresh + workspace smoke.
9. Only then fast-forward or merge integration into `dev-vic`.
10. Do not delete `m1-gold-dial` until after a successful real refresh and UI verification.

## Questions For Claude Before Coding The Merge

1. Should option freshness domains live directly in `model_state.py`, or should we introduce a small shared artifact-freshness helper first?
2. Should `fetch-fundamentals` be part of full `refresh` immediately, or should it remain a separate command until the first successful official-data refresh?
3. What should happen if both option artifacts are carried forward and official fundamentals are stale/degraded in the same run?
4. Is Candidate Finder allowed to combine scenario Tool B/Tool D frames with carried-forward option fields, or should scenario Finder explicitly mark option fields as from spot/current?
5. Which UI should own the first "Market/API vs Ours" experience: `/tool-b` only, or also Candidate Finder detail/columns?
6. Should the gold-dial branch be rebased/merged onto current main before conflict resolution, or should we cherry-pick PRs one by one into the integration branch?

## Recommended Answer To Question 6

Prefer **integration branch + merge local `m1-gold-dial` once**, not cherry-pick, unless conflicts become unreviewable.

Reason:

- The gold-dial commits are a connected data contract sequence.
- Cherry-picking PR5/PR6 without PR1-PR4 would be easy to get wrong.
- But if the merge conflict is too large, fall back to cherry-picking in this order:
  1. PR1/PR2 Tool B spot + dial
  2. PR3 Finder scenario
  3. PR4 official artifact contract
  4. PR5 fundamentals ingestion/mapper + verification fixes
  5. PR6 Market-vs-Ours UI

At each cherry-pick boundary, run the focused tests for that surface.

