# Codex Round-Two Review — Ticker Page Plan v2 and M0

- **Plan reviewed:** reviews/codex/claude_ticker_page_plan.md at d90d092
- **Requirements reviewed:** reviews/codex/claude_ticker_page_requirements.md at d90d092
- **M0 code reviewed:** ce2583a, a6e8bb1, 8b9db26, 3f86c3d
- **Review date:** 2026-08-11
- **Plan verdict:** **CHANGES REQUIRED — keep M1 on hold**
- **M0 verdict:** **FORWARD CODE MOSTLY CORRECT, BUT NOT SAFELY SHIPPED**

## Immediate action gate

Claude should take these actions in order:

1. Fix the two M0 release blockers in M0-1 and M0-2 below.
2. Resolve plan blockers P1–P9 before starting M1 producers. P9 defines an input contract used by the M1 performance producer.
3. Complete the measured payload spike and architecture amendment before calling M0.5 complete.
4. Resolve the remaining product/interaction contracts before M2/M3.

The plan does not need another wholesale rewrite. V2 is materially better. The remaining work is a finite set of contract, migration, and product-semantic corrections.

## What v2 genuinely improved

These first-review items are now solid enough at plan level:

- the browser-math decision is recorded in the requirements addendum;
- the dial is restored to the global control bar;
- true spot is separated from Tool B's configured $4,000 scenario;
- trailing leverage and stressed forward leverage have distinct labels;
- “Target window” replaces the misleading “expiry selector” wording;
- GDX/GDXJ keep their working Option Trading lens routes;
- performance becomes a persisted artifact and chart gaps are explicit;
- the five intended options states are described;
- target_delta is no longer mutated for the ATM row;
- Greeks are limited to selected candidates and have stated units;
- ticker-only Lab default behavior is explicit;
- accessibility, safe JSON embedding, contract ownership, and payload-spike sequencing are substantially improved.

Those improvements should be preserved.

## M0 implementation findings

### M0-1. [Release blocker] Tool D's column rename breaks the current persisted artifact

Commit 8b9db26 correctly identifies the modeling bug: the contextual FCF yield was always copied from the spot row. The new builder values are correct:

- golden_vector/model/tool_d.py:30–31 emits fcf_yield_at_g and fcf_yield_at_spot;
- golden_vector/model/tool_d.py:388–389 takes them from the stressed and spot rows respectively.

The release path is not compatible:

- fcf_yield was removed instead of migrated additively;
- golden_vector/serve/overview_tool_d.py:431 and 463 read only fcf_yield_at_g;
- golden_vector/ingestion/persist_tool_d.py has no Tool D schema version or migration;
- golden_vector/app/model_state.py validates file/readability metadata but not the new Tool D columns;
- Lab vintages key series by raw field name, so the rename also severs metric continuity.

A read-only check of the live workspace proved the failure: data/output/tool_d/tool_d_latest.parquet has 61 rows and contains only legacy fcf_yield. It has neither new column, and tool_d_spot_latest.parquet does not exist, so golden_vector/app/workspace_state.py:247–257 falls back to that legacy file. The new UI therefore renders the missing-value `-` placeholder while model state can still call the artifact usable.

**Required fix**

Use the least disruptive additive contract:

- retain fcf_yield as the corrected stressed/@G value for current-consumer compatibility;
- add fcf_yield_at_spot;
- either keep the renderer on fcf_yield or also retain fcf_yield_at_g as an explicit alias during a deprecation window;
- add a schema/semantic version boundary and rebuild the current artifact before switching labels/readers;
- migrate Lab vintages deliberately: historical fcf_yield values are spot values, so they must be backfilled, retired, or kept behind a version boundary rather than concatenated with new stressed values under one series name;
- add a regression that loads a legacy persisted artifact through the real reader and renders a truthful result or a loud rebuild requirement.

If the old name must be removed, add a Tool D schema version, fail-loud reader, migration/rebuild step, and deployment ordering before changing the renderer. Do not silently show the missing `-` placeholder.

### M0-2. [Release blocker] The RV formula is fixed only for new rows; published history remains wrong

Commit ce2583a correctly changes return_basis_usd from a raw price-level standard deviation to percentage returns. That fixes newly computed feature rows.

It does not repair durable state:

- golden_vector/features/options.py changes only new calculations;
- golden_vector/ingestion/options_phase.py appends/replaces the current run;
- golden_vector/hedge/option_signals.py preserves historical ticker/date/horizon values and replaces only matching current keys;
- the existing Option Trading history chart already renders iv_rv_ratio.

A read-only check of data/output/options/option_signal_history.parquet found:

- 1,245 rows;
- 1,004 non-null IV/RV ratios;
- median ratio 0.004757076;
- 991 of 1,004 ratios below 0.05.

A normal refresh would append corrected observations beside old thousandths-scale values. That creates a large artificial discontinuity in a visible historical series.

**Required fix**

Move the date-bounded value-correction migration forward from M1c into the bug-fix gate, or mark the historical IV/RV series unavailable until migration. The migration must:

- use only prices dated at or before each history row;
- preserve row count and ticker/date/horizon keys;
- write migration provenance;
- rebuild the immutable published history points;
- publish the corrected history and option artifacts atomically;
- leave the previous coherent generation current on failure.

Until then, describe M0 as “forward fix code merged,” not “shipped.”

### M0-3. [Medium] Realized volatility is not deterministic across all supported pandas versions or input order

requirements.txt supports pandas >=2.2. The implementation calls bare pct_change() and tail() without first ordering by date.

Pandas 2.2's legacy default can forward-fill internal gaps, while pandas 3 uses no fill by default. Reversed or unsorted input can also select the wrong chronological window.

**Required fix**

- sort by date when a date column exists;
- reject or deterministically resolve duplicate dates;
- call pct_change(fill_method=None) explicitly;
- add tests for an internal missing price, reversed dates, and duplicate dates.

### M0-4. [Medium] Missing OI/volume fields become genuine zero activity

The new put/call split fields are useful and the healthy-chain arithmetic is correct. However:

- chain normalization can synthesize an absent vendor field as all-null;
- _put_call_sums coerces and fills all-null values to zero;
- the new history-facing fields then say “0” rather than “unknown.”

That makes a vendor/schema omission look like no positioning or volume.

**Required fix**

Return null when a non-empty chain has no observed values for the requested field, or persist observed counts/status alongside the sums. Add a non-empty/all-null regression. Empty chain and genuine observed zero must remain distinguishable.

### M0-5. [Low] Tool C's steep-beta validator accepts non-finite values

The threshold centralization in a6e8bb1 is otherwise clean and correctly threads one config through both tag paths. The validator only checks value <= 0, so NaN and positive infinity are accepted; negative infinity is already rejected.

Use the shared finite-number validation boundary and add NaN/positive-infinity/negative-infinity plus real YAML-load tests.

### M0 commit assessment

| Commit | Assessment |
|---|---|
| ce2583a RV + OI splits | Forward RV math is correct; durable migration and missing-vs-zero semantics remain |
| a6e8bb1 Tool C thresholds | Good refactor; add finite-value validation |
| 8b9db26 Tool D FCF pair | New calculation is correct; persisted-schema migration is a release blocker |
| 3f86c3d dead branches | Behavior-preserving cleanup; no issue found |

## Plan v2 blocking findings

### P1. [Critical] The refresh-stage identity algorithm reads the previous generation

Plan lines 181–186 say both the refresh and standalone ticker-page paths read the current model-state manifest for parent identity.

The current refresh coordinator explicitly documents the opposite reality:

- golden_vector/cli.py:3529–3532 says current model state still points at the previous refresh mid-run;
- the new model-state pointer is not published until golden_vector/cli.py:3638–3644.

Following the plan would build ticker artifacts from yesterday's pointer, stamp the wrong parent_refresh_id, or reject fresh Tool A–D outputs as mixed.

**Required plan edit**

- The refresh path receives the in-flight parent_refresh_id, config hash, foundation/options snapshot identity, and exact upstream run IDs directly from the refresh coordinator.
- It reads the fresh stage outputs selected by that coordinator, not current model state.
- The standalone path may resolve through current model state.
- Define whether a successful standalone ticker-page build republishes model state. Updating aliases alone cannot make it authoritative.
- Define `refresh --skip-tool-b` explicitly: it may publish an explicitly partial state with ticker-page artifacts unavailable, leave the previous coherent pointer current, or be forbidden from publishing a complete state. It must never carry older ticker artifacts against a new foundation generation.
- Reuse/generalize the existing timing helper. Plan line 186 says “clone,” which conflicts with the no-duplication rule.

### P2. [Critical] Section 9.3 creates a new request-path exception Victor did not approve

Plan lines 334–341 retain these calculations in the memoized request loader:

- build_structural_weekly_series;
- compute_horizon_returns_for_ticker;
- the non-canonical-window behavior recompute.

The requirements addendum approves exactly three browser modules. It does not approve Python request-time analytics.

This still conflicts with:

- AGENTS.md:118 and 135;
- CLAUDE.md:125;
- ARCHITECTURE_FOUNDATIONS.md:15 and 29.

Calling the work pre-existing debt or adding it to the architecture file does not make the new ticker page complete under the repository's definition of done.

**Required plan edit**

Delete the proposed exception. Persist/reuse those retained values in the ticker-page stage or an existing Tool A artifact. If Victor explicitly wants a second exception, record a separate requirements decision first; do not combine it with the already approved browser exception.

### P3. [Critical] The v3-to-v4 options migration cannot work as written

Plan lines 229–234 say:

- code expects v4;
- v3 rows still validate;
- a v3 generation can be carried forward;
- the new option_chain_history_daily joins the required publish set.

Current architecture makes those statements mutually exclusive:

- golden_vector/contracts/option_artifacts.py has one global schema version and one global artifact-name set;
- golden_vector/app/model_state.py:1110–1141 requires every current artifact name at the exact current schema during carry-forward;
- golden_vector/app/model_state.py:1192–1200 uses strict version equality;
- golden_vector/serve/option_trading_data.py:640–662 resolves and validates the full configured set;
- a v3 generation cannot contain the new v4-only history artifact.

**Required plan edit**

Choose one real migration contract:

1. Versioned artifact-name sets and a legacy-v3 reader that serves only v3 fields while marking v4-only history/Greeks unavailable; or
2. Require a successful complete v4 build/migration before v4 code can publish current state.

Also specify separately:

- mutable canonical option_signal_history.parquet;
- immutable published option_signal_history_points;
- new option_chain_history_daily;
- code rollback versus data-pointer rollback;
- whether partial v3 compatibility can ever count as complete.

### P4. [High] The “exact artifact contract” is still shorthand

Plan section 5 defines three ticker-page artifacts, but line 174 calls them “the two ticker-page artifacts.” That risks omitting ticker_page_performance from model-state wiring.

The table also omits or abbreviates:

- numeric schema versions;
- exact column names, types, and nullability;
- exact schema module names;
- status/reason enums;
- uniqueness and null-key gates;
- source as-of and configuration compatibility rules.

Concrete gaps:

- gold_response_status has no required gold_response_reason;
- performance lacks series_status, series_as_of_date, currency/value basis, and missing-benchmark reason;
- percentiles lack metric unit, window/accounting basis, source as-of date, completeness, and metric-specific quality reason;
- one absolute tolerance named linearity_abs_tol_musd cannot apply to both million-dollar metrics and forward EPS;
- “line slope/intercept per metric,” “spot values,” and ditto marks are not an auditable schema.

The loader cache should key from the authoritative model-state pointer plus its resolved immutable paths. Adding mutable aliases to that signature would cause spurious invalidation and weaken pointer-centric cache identity; loading authority must remain the manifest-resolved immutable files.

**Required plan edit**

Replace section 5's shorthand with exact versioned schema tables and change “two” to “three.” Add per-metric gold residual diagnostics: metric, probe gold, expected, actual, residual, tolerance, and failure reason.

### P5. [High] The score catalog and ranking rules are still incorrect

There are several independent problems:

1. Plan line 271 adds confidence_score, while requirements lines 31–33 and 41 explicitly remove confidence from this page.
2. Plan line 270 says lower asymmetry_ratio_core is better. The approved mock and golden_vector/model/scoring.py:50–68 establish higher asymmetry as the default favorable direction. Production scoring also treats positive up-beta with nonpositive down-beta as maximally favorable, so a raw-ratio percentile still needs explicit sign handling.
3. Subject missing-data behavior is described, but peer missing-data behavior is not.
4. Candidate Finder currently renormalizes each row over present metrics with a coverage threshold. Without a ticker-page rule, miners can be ranked on different sets of criteria.
5. Contribution bars have no formula. The approved mock's current bar width ignores the selected weight, so a 1-point metric can look as influential as an 80-point metric.
6. Metric-percentile ties and final combined-score ties are not distinguished.

**Required plan edit**

- Remove confidence_score; the catalog becomes 20 metrics.
- Make asymmetry_ratio_core higher-good by default, and define eligibility/ranking for negative or zero down-beta sign cases before computing its percentile.
- Add label, unit/format, window/accounting basis, source-as-of rule, exact eligibility predicate, missing policy, and coverage rule to every metric.
- Define a common active-metric cohort or an exact minimum completeness fraction.
- Keep low-coverage miners visible in “all miners,” but explicitly unranked with a reason.
- Persist/embed active completeness and rank exclusion reason.
- Pin contribution as a weight-aware quantity, including sign/neutral basis.
- Define activation, deactivation, slider step, rounding/residual allocation, ±10 boundary behavior, one-metric behavior, and deterministic final-rank ties.
- Decide whether offering both raw AISC and its derived cost-curve percentile is deliberate; otherwise it lets one underlying idea be double-weighted.

### P6. [High] Finance-source coherence is asserted but not producible

Plan lines 89–93 define machine values {our, official}. Existing canonical values are {our, yahoo}:

- golden_vector/screening/pipeline.py:48;
- normalize_finance_source maps aliases to yahoo;
- golden_vector/model/tool_d.py:580–581 uses an exact yahoo check.

Following the plan literally can bypass official-source Tool D behavior.

The score catalog also includes Tool D metrics, including finance-sensitive survival_distance and fragility, while the plan promises per-source percentiles only for Tool B. Current persisted Tool D defaults to Our View.

**Required plan edit**

- Reuse canonical {our, yahoo} internally and render “Yahoo Fundamentals” as the user label, or migrate the enum centrally.
- Preserve existing fundamentals_source=yahoo URLs, forms, and bookmarks with a compatibility regression; “official” should remain display wording unless the enum is migrated centrally.
- Build source-specific Tool D spot values, eligibility, and percentiles through the shared Tool D model path.
- If official Tool D cannot be produced, disable those metrics and resilience content in official mode with a truthful reason.
- Persist failing-check facts/sentences per finance source at spot.

### P7. [High] Option history quality and provenance remain unsafe

The one-authority split in section 6 is a good correction. The implementation contract remains incomplete:

- canonical signal history still lacks actual source expiry/DTE despite acceptance saying those survive rebuilds;
- row_status is too coarse when only some fields are backfilled;
- published_run_id does not replace the option artifacts' required source_run_id;
- the current no-shrink guard counts global distinct dates, so one ticker/horizon can disappear while the count stays unchanged;
- the highest same-day OI capture is automatically treated as the reference, so the rule cannot prove that the highest capture itself is complete;
- a lone capture is checked mainly by expiration count, not trailing contract, side, and OI coverage.

Most importantly, plan line 218 reuses option_quote_is_tradable. That helper requires positive bid/ask/mid, spread, minimum activity, and valid IV. It is correct for action-oriented candidate selection, but wrong for whole-chain OI/volume. It would remove illiquid listed positions and make historical totals disagree with M0's deliberately whole-chain sums.

**Required plan edit**

- Add actual source expiration and DTE to new signal-history observations; migrated older rows may be explicitly unknown.
- Preserve capture_run_id, current source_run_id, publisher ID, and field-level backfill provenance separately.
- Enforce monotonic key preservation per ticker and horizon, not just a global date count.
- Gate captures against trailing expiration, contract, put-side, call-side, and OI coverage.
- Use structural deduplication and nonnegative/observed-field checks for OI/volume.
- Reserve tradability/liquidity/IV gates for candidate and IV-derived fields.

### P8. [High] “Genuinely no listed options” has no truthful artifact field

Plan line 302 says a current artifact proves no listed options. Existing data cannot make that claim safely:

- optionability none can reflect an empty/failed upstream capture or a missing/defaulted record, not proven exchange listing absence;
- the current EMPTY fetch status covers both an empty expiration enumeration and an enumeration where no expiration matched the configured fetch mode;
- option_trading_overview drops non-optionable rows;
- the consumer artifact retains status/message but no stable availability authority.

**Required plan edit**

Persist universe-complete per-ticker availability rows or a small required artifact with an exact enum such as:

- LISTED;
- NONE_LISTED;
- FETCH_FAILED;
- FILTERED_WINDOW_EMPTY;
- UNKNOWN.

Include enumeration evidence, provider/source, capture date, and reason. Only confirmed NONE_LISTED may remove the section and nav anchor.

## Other high-priority plan corrections

### P9. Performance needs immutable benchmark alignment, not merely an old-date label

Persisting performance and sharing one rebase basis are good changes. However, GDX/GDXJ currently come from mutable caches written in the options phase. Plan lines 129–137 allow an older benchmark to appear as an ordinary series with a label.

Resolve the benchmark through the exact in-flight/current options manifest and immutable snapshot. Persist per-series freshness/alignment status. A benchmark outside the accepted freshness rule should be omitted/degraded with a reason.

Also define:

- exchange-calendar join behavior;
- whether dates must match exactly or may use an as-of rule;
- allowable staleness;
- common ending date;
- Compare/1Y as the approved initial state;
- shared rebase basis **and** late-start disclosure where applicable.

### P10. Navigation destroys comparison state and sizing remains under-specified

Plan lines 343–348 intentionally reset score weights on navigation. The score builder's required ranked list links to another ticker, so clicking it loses the comparison definition the user just built.

The state contract also omits existing corporate option parameters such as side, horizon, size_mode, budget, and quantity, plus chart view/horizon and new target-window/contract/share-price state.

Preserve or explicitly translate legacy parameters. Decide which comparison state travels in URL/history/session state. At minimum, score weights/directions must survive clicks within the ranked list and browser back/forward.

Sizing still needs exact behavior for:

- missing, zero, stale, crossed, or below-intrinsic ask;
- invalid/zero budgets;
- whole-contract flooring;
- caps and partial-contract rejection;
- slider range and step derivation;
- break-even and ladder points;
- reset behavior.

### P11. Lab, Full Research, and test contracts remain partly deferred

- The Lab side-cache key must include its pointer stat/hash, behavior metadata, and live config hash, not only ticker and controls.
- Define whether each Lab cell/chart uses all history or 2016+; label differing periods beside the output.
- Remove the shared lab_dial.yaml refactor from this ticker-only project unless separately approved. A behavior-preserving shared refactor is still broader implementation scope.
- Enumerate the exact surviving Full Research raw panels now. Deferring them to an M2 spec does not close the composite-removal finding.
- Copy required v1 tests into v2. “Everything from v1” makes the supposedly authoritative v2 plan non-self-contained.
- Update the option loader inventory explicitly. Its current loop derives reads from the global option artifact set, so merely saying the new history has a dedicated reader does not prevent the overview loader from reading it.

### P12. M0.5 is not complete until measurements and canon changes exist

Plan lines 401–407 still contain working payload targets. This is correct sequencing, but line 419's exit gate is not yet met.

Before M1:

- record NEM and option-heavy payload, gzip, row-count, cold/warm, memory, and cache-hit measurements;
- set budgets from the evidence;
- amend ARCHITECTURE_FOUNDATIONS.md only for the three Victor-approved browser modules;
- do not add the unapproved Python request-path exception;
- land exact schema/config/empty-reader stubs;
- re-run this review gate.

## First-review closure matrix

| First-review area | V2 status |
|---|---|
| B1 locked requirement deviations | Partial: browser decisions recorded; Python request exception remains unapproved |
| B2 artifact contract | Open |
| B3 history authority/no-shrink/no-lookahead | Partial |
| B4 score engine/eligibility | Open |
| B5 benchmark ETF routes | Closed at plan level |
| B6 options state/target wording | Partial |
| B7 spot/leverage/line semantics | Mostly closed; source/tolerance schema remains |
| B8 performance/request compute | Partial; request compute and benchmark coherence remain open |
| B9 target delta/Greeks/migration/sizing | Partial |
| H1 metric catalog/finance-source contract | Open |
| H2 spot-only labeling | Closed |
| H3 statistically robust history gate | Open |
| H4 Lab scope/cache | Partial |
| H5 query/focus/form behavior | Closed for named query state; comparison navigation remains open |
| H6 composite removal | Open |
| H7 chart period semantics | Partial |
| H8 accessibility | Substantially closed at plan level |
| H9 payload sequencing | Closed as sequencing; measurements still pending |
| I1 contract ownership/integration | Closed at plan level |
| I2 atomic publication | Partial: standalone current-state publication needs definition |
| I3 stage identity | Open and blocking |
| I4 safe embedding | Closed at plan level |

## Required revision checklist for Claude

1. Fix M0's Tool D persisted-schema migration.
2. Correct or suppress old IV/RV history before adding new-scale observations.
3. Make RV ordering/missing semantics deterministic and preserve unknown OI/volume as unknown.
4. Split refresh-stage identity from standalone-stage identity.
5. Remove the unapproved Python request-time exception.
6. Define a workable v3/v4 option migration and rollback matrix.
7. Make all three ticker artifact schemas exact and versioned.
8. Remove confidence, correct asymmetry direction, and finish rank/contribution/completeness rules.
9. Use the canonical finance-source enum and produce source-coherent Tool D values.
10. Separate whole-chain validation from tradability gates and strengthen history provenance/no-shrink gates.
11. Add a real per-ticker options availability authority.
12. Make benchmark inputs immutable/aligned and finish calendar rules.
13. Preserve score/legacy option state and define sizing edge cases.
14. Finish Lab cache/period, Full Research inventory, and self-contained tests.
15. Record payload/cache measurements before M1.

## Verification evidence

- 133 focused M0 tests passed in 261.14 seconds.
- 179 additional config, persistence, Tool D, Option Trading, and route tests passed in 173.20 seconds.
- Independent audit runs passed 120 and 187 focused tests.
- git diff bd67f96..3f86c3d --check passed.
- Read-only workspace checks exposed the Tool D legacy-column incompatibility and old-scale option history described above.
- Full repository suite: **1,728 passed in 1,155.29 seconds (19:15).**

No implementation files were changed by this review. The unrelated untracked naukri.md was not touched.
