# Codex Review — Claude Ticker Page Plan

**Reviewed document:** reviews/codex/claude_ticker_page_plan.md at commit bd67f96  
**Requirements baseline:** reviews/codex/claude_ticker_page_requirements.md at commit a18839f  
**Review date:** 2026-08-11  
**Verdict:** **CHANGES REQUIRED — do not start M1 or later from this plan**

## Scope note

This review is pinned to the commit Victor named: bd67f96. The shared dev-vic branch advanced while the review was running and M0 was subsequently marked shipped. Those later code and plan changes were not part of this review and are not implicitly approved here. Safe, isolated M0 fixes can be reviewed on their own merits; the architecture and contract blockers below apply before M1, M2, or any visible section work.

No implementation files were changed for this review. No runtime tests were run because this is a plan and contract review.

## Bottom line

The plan has a strong product direction, useful section decomposition, good awareness of existing components, and a sensible desire to centralize configuration. It is not yet implementation-ready.

The largest issue is not polish. The plan silently changes several locked requirements and the repository's compute-once/persist/serve rule:

- it replaces a precomputed gold grid with browser-side financial calculations;
- it replaces a backend score function with browser-side weighted scoring and ranking;
- it computes performance in a request-time loader;
- it computes option sizing in JavaScript;
- it moves the gold control from the approved global control bar into one section;
- it expands a ticker-page project into shared Lab behavior.

Those are product and architecture decisions, not implementation details. The plan cannot approve its own exceptions. Victor must either confirm the changed contract and the locked requirements must be amended first, or the plan must return to the locked design.

Four other blockers are equally important: the new artifacts are not fully wired into coherent model state, the proposed option history duplicates an existing canonical history and can shrink or look ahead, score eligibility is undefined, and the proposed route rewrite breaks benchmark ETF links such as GDX.

## Decision gate for Claude

Claude should treat the work as follows:

| Work | Gate |
|---|---|
| Isolated M0 bug fixes | May continue only as separately tested fixes; this review does not verify the later M0 commits |
| M1 backend artifacts | **Hold** until B1–B9 below are resolved in a revised plan |
| M2 serve spine | **Hold** until artifact contracts, state semantics, and routes are specified |
| M3 visible sections | **Hold** until the product deviations and interaction semantics are approved |
| Merge milestone | Run the required branch/worktree/data-spine integration audit first |

## Blocking findings

### B1. The plan overrides the locked requirements without approval

**Evidence**

- Plan lines 85–126 replace the locked precomputed gold-price grid with two fitted lines and browser arithmetic.
- Plan lines 128–143 replace the locked model-layer score calculation with browser-side weighted sums, rank calculation, and stability checks.
- Plan lines 185–189 put sizing arithmetic in JavaScript.
- Plan lines 207–215 calculate performance inside the memoized detail loader.
- Plan lines 326–330 explicitly allow client-side analytical calculations.
- Locked requirements lines 127–141 say the backend computes, the serve layer renders, and nothing analytical is computed in a request or UI render path.
- Locked requirements lines 43–50 put the gold dial in the global control bar and require a precomputed grid.
- The approved mock also places the dial globally, while the plan places it in the Corporate & Gold section.

**Why this matters**

This is a change to both the approved product and the load-bearing data architecture. Calling the line model “equivalent to the grid” does not make it the approved grid, and adding a later milestone to change the architecture canon does not resolve the conflict.

**Required revision**

Add a short decision table at the top of the plan for every departure from the locked requirements:

1. approved requirement;
2. proposed replacement;
3. user-visible benefit;
4. architecture cost;
5. Victor's explicit decision.

Until that decision exists, restore the locked design:

- lookup-ready, persisted gold scenarios;
- backend-owned score behavior;
- persisted performance data;
- serve code that only selects and formats prepared values;
- the dial in the global control bar;
- ticker-page-only Lab changes.

If Victor deliberately accepts any browser-side analytical exception, amend the locked requirements and architecture documentation before implementation. Define the exception narrowly and add tests that execute the real JavaScript. A Python parity test alone does not test JavaScript behavior.

### B2. The new artifact contract is incomplete and cannot guarantee coherent current state

**Evidence**

Plan lines 294–311 list artifact names and mention the artifact map, REQUIRED_ARTIFACTS, and paths, but omit several necessary parts of the state contract.

At bd67f96:

- golden_vector/app/model_state.py:1668–1685 only resolves known producer directories and prefixes;
- model-state alignment at golden_vector/app/model_state.py:973–1037 does not know a ticker-page producer stage;
- golden_vector/app/model_state.py:206–224 converts some missing/read failures into empty frames;
- immutable artifact metadata is assembled at golden_vector/app/model_state.py:741–816;
- golden_vector/app/run_pruning.py does not include a new ticker-page output directory.

The plan also omits a persisted performance artifact even though performance is a core section.

**Why this matters**

A new file existing on disk is not enough. Without one coherent pointer, schema validation, refresh identity, and explicit failure states, the page can mix generations or quietly display stale or corrupt data as current.

**Required revision**

Replace the loose artifact list with an exact contract table. For every artifact define:

- producer stage and output directory;
- immutable run-stamped filename and optional latest alias;
- schema name, schema version, required columns, key, and uniqueness rule;
- required versus optional status;
- source_run_id, snapshot_refresh_run_id, parent/foundation run IDs, and config hash;
- checksum and row-count metadata;
- finance source, as-of date, and applicable gold price where relevant;
- atomic publication order;
- reader validation and the user-visible failure state;
- run-pruning behavior.

Update the implementation inventory to include:

- producer-prefix resolution;
- artifact map and required-artifact policy;
- alignment and freshness evaluation;
- immutable manifest metadata;
- a dedicated validated reader;
- loader cache identity;
- run pruning;
- interruption/rollback tests.

A stale, corrupt, wrong-schema, or wrong-refresh ticker artifact must not be rendered as a valid empty section.

### B3. The proposed option history duplicates canonical history and can silently lose data

**Evidence**

Plan lines 145–165 introduce option_history_daily with ATM IV, skew, implied move, and IV/RV history.

Existing history already lives in golden_vector/model/option_signals.py:59–80, 101–177, and 921–940, keyed by ticker, date, and signal horizon. The proposed schema omits that horizon. Rebuilding from surviving data/runs is unsafe because run pruning can remove the only source for older dates.

The proposed realized-volatility backfill also needs a per-row date constraint. Without filtering price observations to dates at or before each history row's as_of_date, a rebuild can leak future prices into older rows.

**Why this matters**

Two histories for the same signal will drift. A history rebuilt only from retained runs can shrink. A look-ahead error can make historical comparisons appear better than they could have been in real time.

**Required revision**

Extend or derive from the existing canonical option-signal history rather than starting a second authority. The contract must:

- preserve signal_horizon_days and actual expiry/DTE;
- merge prior immutable history with the current capture;
- enforce no-shrink and deterministic deduplication gates;
- preserve older non-null backfilled values;
- record original capture run/date separately from the current publishing run;
- constrain every RV input to price_date <= history_row.as_of_date;
- record whether each row is observed, carried forward, or backfilled;
- define expiry-roll behavior and daily capture policy;
- never reconstruct durable history only from prunable run directories.

The history gate needs exact definitions for the trailing window, minimum samples, denominator, valid IV bounds, duplicate handling, missing values, and partial-capture quality.

### B4. Score eligibility, ranking, and provenance are undefined and duplicate Candidate Finder

**Evidence**

Plan lines 128–143 describe about 20 percentiles and browser ranking, but do not define:

- who is eligible;
- what happens when an active metric is missing;
- how degraded rows are handled;
- tie behavior;
- minimum peer count;
- one-company or all-missing cohorts;
- finance-source selection;
- coverage requirements;
- exact normalization and rounding.

golden_vector/common/eligibility.py:10–38 and golden_vector/model/candidate_finder.py:295–300 and 336–429 already contain reusable eligibility and ranking behavior. golden_vector/model/percentile_ranks.py only masks nonnumeric values; it does not by itself exclude degraded subjects.

**Why this matters**

The same company could be rankable on one page and excluded on another. Worse, a degraded company could receive a convincing rank based on incomplete inputs.

**Required revision**

Generalize and reuse the existing Candidate Finder ranking/eligibility primitive. Do not create a second score engine.

The plan must include the exact metric catalog, not “about 20.” For each metric list:

- key and label;
- source artifact and source column;
- finance source;
- time window or accounting basis;
- direction/orientation;
- score eligibility rule;
- missing-data behavior;
- display format;
- whether it is spot-only or scenario-sensitive.

Persist or expose at minimum:

- rank_eligible;
- rank_exclusion_reason;
- active-metric completeness;
- cohort identity and eligible peer count;
- normalized weights;
- tie policy and deterministic rank basis;
- source/as-of/config/schema provenance.

Add explicit behavior for zero active metrics, one active metric, one eligible peer, all-missing metrics, ties, ±10-point shifts, weight renormalization, and degraded comparison rows.

### B5. The route rewrite breaks Option Trading benchmark links

**Evidence**

Plan lines 171–177 and 386–387 say to ignore/remove the lens query and route ticker links to the new canonical ticker page.

Today GDX and similar benchmark ETFs are supported through the Option Trading lens:

- golden_vector/serve/workspace.py:516–541;
- golden_vector/serve/overview_option_trading.py:403–410;
- tests/test_option_trading_routes.py:373–412.

A bare /ticker/GDX route is not equivalent and can return 404.

**Why this matters**

The route cleanup would turn working benchmark links into broken links.

**Required revision**

Preserve the lens route for benchmark ETFs or add a dedicated canonical benchmark route before removing the query parameter. Change only corporate-company links until route parity exists.

Add route tests for at least:

- AEM from Candidate Finder;
- AEM from Option Trading;
- GDX from Option Trading;
- GDXJ from Option Trading;
- direct canonical ticker URLs;
- browser back/forward behavior.

### B6. Options availability and selector semantics are not truthful enough

**Evidence**

The plan derives options_available from a raw options manifest. Model state may instead be serving a current, carried-forward, stale, corrupt, or misaligned artifact generation.

The UI calls the control an “expiry selector,” but the current system selects target horizon buckets. Calls and puts can resolve to different actual expiries; tests/test_option_horizon_selection.py:198–218 demonstrates this possibility.

The singular historical IV/skew/implied-move series also lacks a tenor definition even though the existing features are horizon-dependent.

**Why this matters**

“No options” is materially different from “our data is unavailable.” Calling a horizon target an expiry can mislead a trader, especially if the call and put rows are not from the same expiry.

**Required revision**

Resolve availability from the selected model-state artifacts, then define and test this state matrix:

| State | Page behavior |
|---|---|
| Company genuinely has no listed options | Options section absent |
| Current coherent option data | Full section with as-of date |
| Valid carried-forward data | Section visible with explicit stale/carried-forward label |
| Pipeline/artifact unavailable, corrupt, or misaligned | Degraded section with reason; never “no options” |
| Contracts exist but no eligible candidates | Context remains visible with a clear candidate-selection reason |

Either build common-expiry call/put rows and show the actual expiry, or rename the control to “target window” and show each row's actual expiry and DTE. A product decision is required before calling it an expiry selector.

Historical option series must be keyed by a canonical tenor/horizon and show actual expiry/DTE provenance.

### B7. Gold-response semantics are internally inconsistent

**Evidence**

The plan says the left column is “spot” and that it renders from the real Tool B row. At bd67f96, the default Tool B screening gold price comes from config and is $4,000; it is not necessarily current spot.

Tool D already evaluates Tool B at spot and spot × 0.90 in golden_vector/model/tool_d.py:94–150. The plan proposes another pair of Tool B evaluations and a single $2,000 linearity probe.

The plan also changes leverage to net_debt / forward_ebitda(g), while the established Tool B leverage concept is net_debt / ebitda_ltm. Reusing the same “leverage” label would silently change the meaning.

Finally, a fixed server-rendered failure sentence can become false when the dial crosses a threshold.

**Why this matters**

The page could label a configured scenario as spot, show conflicting finance-source results, or update a number while leaving its pass/fail explanation stale.

**Required revision**

- Persist explicit spot display values; never infer spot from the default Tool B row.
- Reuse or extend Tool D/Tool B calculations instead of recomputing the same concept independently.
- Make finance_source a first-class artifact key and cache identity. Select the source before caching or store both source rows in the cached object.
- Define whether leverage remains trailing or becomes “stressed forward leverage,” and label it accurately.
- Probe both configured dial bounds plus at least one interior point.
- Define line tolerance as absolute and/or relative, including behavior near zero.
- Separate systemic nonlinearity, which fails the stage, from one ticker's bad inputs, which degrades that ticker with a reason.
- Make scenario-dependent pass/fail explanations update with the scenario, or label fixed explanations explicitly as spot-only.
- Show a short unavailable reason when a ratio is invalid; do not silently render a blank.

### B8. Performance remains request-time analytics and the comparison basis is misleading

**Evidence**

Plan lines 206–215 build performance inside the memoized ticker-detail loader. The artifact table contains no ticker performance artifact.

The current comparison helper in golden_vector/model/structural.py:348–370 rebases each series independently. That can put “100” on different calendar dates. The SVG renderer in golden_vector/serve/charts.py:388–447 drops missing points and can visually bridge gaps.

GDX/GDXJ histories are mutable cached data written during the options phase and normalized later in a request path. A refresh using --no-options can therefore leave them older than the company data.

The “full research” content also retains existing weekly/horizon/volatility calculations from golden_vector/serve/workspace_state.py:321–477 and detail_panels.py. Moving the markup does not remove those request-time computations.

**Why this matters**

The comparison can look precise while starting each line on a different date or mixing refresh generations. It also perpetuates the exact request-time architecture debt the project is meant to remove.

**Required revision**

Add a persisted ticker_page_performance_series contract keyed by:

- ticker;
- comparison series;
- view and horizon;
- date;
- source/as-of;
- refresh identity.

Define a common comparison calendar and common rebasing date, a policy for late-starting series, and visible gaps rather than connected missing spans. Missing or stale benchmarks need an explicit reason.

Move benchmark history into a coherent foundation/performance stage, or gate it by aligned refresh identity. Do not make benchmark freshness depend implicitly on whether the options phase ran.

Audit every retained Full Research calculation. Persist/reuse prepared artifacts or explicitly remove the analytical request-path exception.

### B9. The option candidate/Greeks design does not match the current contracts

**Evidence**

Plan lines 182–183 and the config table say to add 0.50 to a target-delta list. The current hedge_readiness.target_delta is a singular negative hedge delta, not a list. Existing option candidate rows already use near_atm and directional buckets by side and horizon in golden_vector/model/options_liquidity.py:367–414 and 561–668, stamped at lines 1204–1207.

The full option_contract_metrics artifact is intentionally excluded from the serve payload because of its size. The model-state object has no route for serving an entire chain to one ticker page.

The option artifact contract is version 3 and persistence expects every declared artifact. Adding history or Greeks therefore needs a deliberate migration.

**Why this matters**

The proposed change mutates the wrong configuration concept, risks loading a very large global chain into the page path, and leaves old/current artifact compatibility undefined.

**Required revision**

- Reuse/generalize the existing near_atm and directional candidate buckets.
- Do not add 0.50 to the singular hedge target_delta setting.
- Prefer stamping Greeks onto selected candidate rows. If a broader chain is genuinely required, create a ticker-partitioned artifact and prove the payload/caching model.
- Bump the option artifact schema deliberately and specify first-refresh, carry-forward, rollback, and old-schema behavior.
- Do not add history to a global artifact list if that makes the main Option Trading loader read it; use a dedicated reader where appropriate.
- Define Greek units and assumptions: gamma basis, vega per volatility point or per 1.00, theta per day or year, risk-free rate, dividend yield, IV, DTE, model version, and as-of date.
- Reuse the shared contract multiplier and intrinsic-value primitives.
- Specify sizing behavior for missing/zero ask, ask below intrinsic, stale quote, zero budget, rounding, caps, and partial contracts.

## High-priority findings

### H1. The metric catalog and finance-source contract must be exact

“About 20 metrics” is not an implementable contract. List all metrics before building the table. Each metric must have one source, one accounting basis, one orientation, one format, one missing policy, and one eligibility rule.

The finance-source toggle must select coherent values across Corporate & Gold, score percentiles, pass/fail sentences, and retained finance details. Tool D currently represents one source path; serve code must not combine a resilience statement from one source with a ratio from another.

### H2. Scenario-aware versus spot-only content needs a visible rule

If the gold dial changes corporate finance numbers but the score-builder percentiles remain based on spot, label the score builder “spot/as-of; unaffected by the dial.” If the intended product is scenario-aware rankings, those scenario percentiles/ranks must be modeled and persisted coherently.

Do not allow the same page to imply that all gold-sensitive analysis moved while only one section changed.

### H3. The history gate needs a statistically robust definition

Choosing one snapshot by highest aggregate open interest can favor duplicate or inflated captures. Define:

- the capture unit;
- how duplicate contracts are identified;
- valid quote/IV filters;
- coverage numerator and denominator;
- minimum contract and side counts;
- tie-breaking;
- holiday/weekend behavior;
- expiry rolls;
- missing calls or puts;
- the canonical daily record;
- whether intraday reruns replace or append.

Add diagnostics to the artifact so the UI can explain poor coverage without recomputing it.

### H4. Lab scope and ownership are under-specified

The locked scope is the ticker page. Moving shared Lab horizons/buckets into a new global configuration changes standalone Lab behavior and several import-time contracts. Keep the change page-local unless Victor approves the broader refactor.

The existing Lab has a separate pointer and a config hash. If that architecture remains, the plan must update the shared Lab config loader/hash and include pointer/config identity in the ticker detail cache signature. A Lab rebuild must invalidate cached ticker content.

Do not put shared Lab defaults inside ticker_page.yaml.

### H5. Query-string interactions need complete navigation behavior

Valid Lab parameters should reopen the Market Lab details element, scroll/anchor to it, and restore the chosen state. Back and forward must restore the UI, not merely change the URL.

After a save or validation error in a closed Inputs panel, reopen the relevant panel, anchor to it, and move focus to the result/error. Otherwise the page can reload with no visible explanation of what happened.

Define reset behavior for the gold dial, score weights, source selection, chart series, horizon, and Lab inputs.

### H6. “Full research” must not reintroduce removed composite scores

The plan says existing content is re-homed, but the current detail panels include Gold Sensitivity Score, confidence/profile treatments, and composite prose. Section 8 also says those composites are removed.

Name the exact raw panels that survive. Remove or rewrite composite-score labels and prose rather than moving them into an accordion unnoticed.

### H7. Chart period semantics are inconsistent

The behavioral episode chart uses a 2016+ period while some beat-rate cells can use all history. Either calculate the cells over the same period or label both periods clearly.

For option history, show the selected tenor/horizon in the title and tooltip. For performance, define whether 1Y/3Y/5Y uses trading days, calendar boundaries, or first observation after a cutoff.

### H8. Accessibility requirements need behavioral acceptance tests

The plan's table/text twins are a good start but are not enough. Add:

- semantic buttons for interactive chart controls;
- aria-pressed or equivalent selected state;
- labels and output elements for sliders;
- a polite live region for scenario/rank changes;
- keyboard focus and visible focus states;
- inactive SVG layers that are hidden from both sighted and assistive users;
- accessible explanations for unavailable/degraded states;
- reduced-motion behavior.

Responsive tests must verify controls, tables, and interaction flow, not only screenshots at several widths.

### H9. Payload and cache risk must be measured before M2

The approved local mock is already large before real option rows, history, performance, and accessibility twins are added. The plan postpones the payload spike to M4; that is too late.

Move a real representative payload spike before M2. Measure:

- HTML bytes;
- embedded JSON bytes;
- gzip size;
- row counts per section;
- cold load;
- warm cached load;
- detail-cache memory;
- cache hit behavior.

The Lab's roughly 40 query combinations should not compete blindly with the existing small detail cache. Give Lab results a separate bounded cache or a compact prepared representation.

## Implementation and integration corrections

### I1. The proposed parallel M1 lanes overlap

M1c and M1d both touch option schemas, builders, persistence, and model state. M1a and M1b both touch ticker-page contracts/configuration, publishing, and model state. These are not independent lanes.

Revise the dependencies and identify a single contract owner. If multiple worktrees are used:

1. land shared contracts first;
2. make producer lanes consume those contracts;
3. integrate through a temporary branch when two lanes touch the same data spine;
4. compare touched files and artifact semantics, not just Git conflicts;
5. run focused contract/reader tests, then the full suite, then one real workspace smoke check.

### I2. Atomic persistence must cover the whole published set

Do not copy an older persistence module if it writes aliases and the pointer sequentially. Use the shared atomic multi-file write/publish primitives. Publish the current-state pointer last so an interrupted build leaves the previous complete generation visible.

The plan should include a fault-injection test that interrupts each publication boundary.

### I3. Stage identity must work for refresh and standalone commands

The current full refresh and standalone stage paths do not all resolve inputs the same way. Specify, for each new builder:

- what parent manifest it reads;
- what refresh ID it inherits;
- how standalone runs find their parent;
- which upstream tool/foundation IDs are asserted;
- how mixed generations are rejected;
- what timing and row-count metadata is recorded.

Every substantial substep should record seconds, rows_built, and rows_persisted. A large built/persisted ratio must be visible.

### I4. Safe embedded state is part of the contract

If the page embeds JSON for charts or controls, use one safe serialization primitive. Test strings containing closing script tags, ampersands, Unicode separators, quotes, and missing values. Page-specific JavaScript should no-op safely on pages where its markup is absent.

## Required acceptance-test additions

The revised plan should add these gates before declaring the page complete.

### Artifact and state gates

- Every new artifact is immutable, schema-validated, checksummed where required, and resolved through the current-state pointer.
- Mismatched refresh identities produce an unavailable/degraded state, never mixed values.
- Stale schema, corrupt Parquet, and checksum mismatch fail explicitly.
- An interrupted build preserves the prior good current state.
- Run pruning retains every current immutable artifact and cannot erase canonical history.
- Current, carried-forward, stale, corrupt, and genuinely absent options render differently.

### History and modeling gates

- Option history cannot shrink after a rerun.
- Duplicate captures resolve deterministically.
- Signal horizon and actual expiry/DTE survive rebuilds.
- Backfilled RV never reads a price after the history row's date.
- Degraded subjects never receive a percentile or rank.
- Tie, NA, missing-peer, one-peer, all-missing, and finance-source cases are deterministic.
- Gold lines pass at both bounds and interior points; near-zero tolerance is tested.
- Spot is actual spot, not the configured Tool B scenario.
- Scenario threshold crossings update both number and explanation.

### Route and interaction gates

- AEM, GDX, and GDXJ links work from every originating overview.
- Browser back/forward restores source, dial, Lab, score-builder, chart, and option state.
- A valid Lab query reopens and focuses the Lab section.
- Save and validation outcomes remain visible after reload.
- “No listed options” is never used for pipeline failure.

### Chart and payload gates

- Comparison series share a common start or clearly disclose a late start.
- Missing periods create visible gaps rather than false connecting lines.
- Table/text twins contain the same values and dates as charts.
- Payload and cache budgets pass with a representative option-heavy ticker, not only NEM.
- JavaScript tests exercise the real dial, scoring, reset, and accessibility behavior.

### Integration gates

- Run the focused ticker, Tool B/D, Option Trading, Candidate Finder, Lab, model-state, schema, carry-forward, pruning, and route suites.
- Run the full test suite.
- Run a real-workspace smoke build and load at least a normal miner, a ticker with weak/missing inputs, a company with no options, an option-heavy company, GDX, and GDXJ.
- Perform the mandatory unmerged-branch/worktree/touched-file audit before merging.

## Required plan rewrite checklist

Claude can use this as the concrete edit checklist:

1. Add an explicit “Decisions requiring Victor” section and resolve every locked-requirement deviation.
2. Remove all unapproved browser/request-path analytics, or document an approved narrow exception and update the locked documents first.
3. Replace the artifact list with exact versioned contracts, including a performance artifact.
4. Extend the existing canonical option history instead of creating a second one.
5. Define no-shrink, no-lookahead, horizon, capture, and provenance behavior.
6. Reuse the Candidate Finder eligibility/ranking engine and publish the exact metric catalog.
7. Define the full options state matrix and preserve benchmark ETF routes.
8. Correct target-delta/bucket semantics and define the Greeks schema and units.
9. Define actual spot, finance-source coherence, leverage basis, line invariants, and scenario-aware explanations.
10. Define a common calendar/rebase policy and coherent benchmark provenance.
11. Keep shared Lab configuration out of ticker_page.yaml and decide whether the global Lab refactor is in scope.
12. Move the payload/cache spike ahead of M2.
13. Replace overlapping “parallel lanes” with explicit contract-first dependencies and an integration owner.
14. Expand acceptance tests with the gates above.
15. Add a migration/rollback section for every changed schema and persisted artifact.

## Recommended revised sequence

| Milestone | Contents | Exit gate |
|---|---|---|
| M0 | Isolated correctness fixes only | Focused tests and separate code review |
| M0.5 | Product decisions, locked-requirement amendments if approved, exact metric/state/artifact contracts, representative payload spike | Victor decisions recorded; Codex blockers closed |
| M1a | Shared schemas, eligibility primitive, config ownership, state/publishing plumbing | Contract, fault, alignment, and migration tests |
| M1b | Corporate/gold, percentile, and performance producers | Immutable coherent artifacts; no request-time analytics |
| M1c | Existing option-history extension, candidate Greeks, carry-forward migration | No-shrink/no-lookahead/schema tests |
| M1 integration | Temporary integration branch if data-spine files overlap | Focused suites, full suite, real workspace smoke |
| M2 | Read-only serve spine, route compatibility, explicit state matrix | Reader/cache/route tests |
| M3 | Visible sections and interactions | Behavioral, accessibility, responsive, and real-JS tests |
| M4 | Final optimization and release audit | Budgets, provenance, docs, full integration audit |

## What is already strong

The revised plan should preserve these strengths:

- the page-level section decomposition is clear;
- reusing existing chart and detail components is directionally right;
- the plan correctly identifies the realized-volatility bug and several configuration literals;
- moving raw useful details behind progressive disclosure is sensible;
- removing unexplained composite scores is the right product move;
- explicit source switching, calculation explanations, missing-data handling, and accessibility twins are good requirements;
- the proposed milestone structure can work once its dependencies and contracts are corrected.

The recommendation is therefore **revise, not abandon**. Once the locked decisions, data contracts, history authority, ranking semantics, routes, and state model are made explicit, this can become a strong implementation plan.
