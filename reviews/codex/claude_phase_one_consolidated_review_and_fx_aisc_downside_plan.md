# Claude action file: Phase One consolidated review + FX attribution + AISC/downside plan

**For:** Claude Code  
**Decision owner:** Victor  
**Reviewed code:** `dev-vic` at `226670e` (also `origin/dev-vic`)  
**Review date:** 2026-08-11  
**Status:** **CHANGES REQUIRED**  
**Authority:** This is the single current handoff. It supersedes the earlier Codex backend review and amends `claude_ticker_page_plan.md` where this file is more specific.

## Claude's instruction

Correct every confirmed finding in this file, add both requested ticker features, and close the tests and live-publication gates. Do not selectively defer a finding without a concrete technical blocker and Victor's agreement.

Do not build M2/M3 on the current v1 ticker artifacts and then repair their meanings in the renderer. Fix and rebuild the data spine first. Keep the implementation lean: reuse the existing ranking, chart, manifest, atomic-write, normalization, and help-text primitives; do not create a second analytics path or another composite score.

---

## 1. Executive verdict

Claude completed **M0/M1 backend foundations**, not the visible redesigned ticker page. The plan still has M2 serve wiring, M3 visible sections, and M4 browser/integration acceptance pending. The current `/ticker` route is therefore still the legacy page; that is remaining work, not a Phase-One regression.

The broad architecture is sound: compute once, persist, resolve through the model-state manifest, and degrade by item. Several self-review fixes are also good and should stay. However, Phase One cannot be accepted yet because seven reproduced issues change dates, rates, rankings, or user-facing financial values today.

### What is actually serious

| Class | Finding | Why it matters |
|---|---|---|
| Live wrong number | C1 AISC/sustaining-capex double count | Understates the AISC-margin proxy and can flip the 15% yield screen. |
| Live wrong number | C2 Tool C's “10%” hit-rate threshold uses the wrong return unit | Changes 57/61 current ticker rates after correcting the threshold. |
| Live wrong date | C3 Tool A uses the earlier input date | Labels data before all inputs were available; 854 current weekly rows are affected. |
| Live wrong date | C4 weekly performance invents Friday dates | Current artifacts can claim dates after the source data ends. |
| Live wrong rank | C5 degraded Tool D companies enter healthy percentile pools | Changes every currently healthy Tool D score in the audited workspace. |
| Live wrong source | C6 Yahoo source isolation is not enforced | Our-View resilience appears in Yahoo mode even though the approved plan disables it. |
| Live wrong cohort | C6 Yahoo eligibility is not enforced | Non-OK Yahoo financial rows enter current peer cohorts. |
| Defensive but required | C7, C8-C13 | Current data is mostly clean, but invalid FX/non-finite Greeks, incomplete semantic validation, mixed publication, and incomplete v4 health can be accepted or misreported later. |

This is not a request for a large generic validation framework. Implement the smallest shared predicates and artifact-aware checks that close the reproduced paths.

---

## 2. Confirmed findings and exact repairs

### C1 - P0: reported AISC is charged twice

**Evidence**

- `golden_vector/screening/layer1.py:54-58` computes:

  ```text
  (gold - AISC) x production - sustaining_capex
  ```

- `golden_vector/model/tool_d.py:650-658` computes an “FCF breakeven” as:

  ```text
  AISC + sustaining_capex / production
  ```

Reported industry AISC already includes sustaining capital. The World Gold Council definition is the relevant basis: [non-GAAP metrics guide](https://www.gold.org/goldhub/research/non-gaap-metrics-guide) and [production-cost methodology](https://www.gold.org/sites/default/files/downloads/2018-11/Production_costs_methodology_note.pdf).

The simple invariant is:

```text
at gold == reported AISC:
    AISC margin estimate == 0
    AISC breakeven == reported AISC
```

The current code instead gives `-sustaining_capex` and a higher breakeven.

**Current WDO example**

| Input/result | Value |
|---|---:|
| Gold | $4,452/oz |
| Reported AISC | $1,419/oz |
| Production | 192,500 oz |
| Sustaining capex entered separately | $110m |
| Current displayed proxy | $473.85m / 13.08% |
| Correct AISC-margin proxy | $583.85m / about 16.11% |

**Required lean fix**

1. Under reported-AISC semantics, use `(gold - AISC) x production` once. Do not subtract sustaining capex again.
2. Rename `sustainable_fcf_musd` and the UI wording to **AISC margin estimate** (or equally explicit wording). It is not audited accounting free cash flow.
3. Remove/rename the duplicated `fcf_breakeven` concept. In the lean model, the cost breakeven is AISC. A future true FCF model would need separately sourced pre-sustaining costs and other cash-flow items; do not pretend the current inputs provide that.
4. Keep `sustaining_capex_musd` as sourced context if useful, but do not charge it twice.
5. Version/rebuild Tool B, Tool D, Candidate Finder dependencies, gold-response lines, percentiles, Lab vintages affected by these fields, and their help text.

**Tests**

- `margin_estimate(gold=AISC) == 0` with nonzero sustaining capex.
- cost breakeven equals AISC.
- WDO-style case and a threshold-flip case.
- repository-wide removed-name/old-tooltip sweep.

### C2 - P1: Tool C's “10% decline” is not a 10% price decline

**Evidence**

`golden_vector/features/relative_behavior.py:214+` compares `stock_log_ret` directly with the configured simple threshold `-0.10`. A log return of `-0.10` is an ordinary price return of about `-9.52%`; the exact log threshold for a 10% ordinary decline is `log(0.90) = -0.1053605`. The upside side has the mirror mismatch: a +10% ordinary return is `log(1.10) = 0.0953102`, not `0.10`.

The same unit rule must be consistent in `golden_vector/features/gold_regime.py` for the configured +/-10% event flags.

**Measured current impact**

- 57 of 61 ticker hit rates change.
- 216 event classifications change.
- Examples: `THX.L` 12.28% -> 5.26%; `TXG` 23.75% -> 18.75%; `CDE` 28.57% -> 24.71%.

**Required fix**

Choose one shared boundary and test it:

- either convert weekly log returns with `expm1` before comparing to simple-return thresholds; or
- convert configured simple thresholds with `log1p` once before comparing to log returns.

Keep the user-facing definition intuitive: **the stock's ordinary price return fell at least 10% during a qualifying weak-gold week**. Rebuild Tool C and every dependent percentile/card before the downside feature ships.

### C3 - P1: Tool A weekly rows are dated before all inputs were available

**Evidence**

`golden_vector/model/structural.py:323-326` merges the last stock and gold observation in a week, uses both values, then stores the **minimum** of `stock_week_date` and `gold_week_date` as `as_of_date`.

A Thursday stock observation paired with Friday gold is therefore labelled Thursday even though Friday's gold input is inside the return. The audited workspace has 854 such rows across all 61 tickers.

**Required fix**

- Store the later availability date (`max`) unless the two series are first aligned to a genuinely common known date.
- Preserve `stock_source_date` and `gold_source_date` in the structural/research provenance where practical.
- Rebuild Tool A, Tool C, ticker research, and their percentiles.

**Tests:** Thursday/Friday in both directions, exchange holiday, missing Friday, and an invariant that no row date precedes either input date.

### C4 - P1: performance and research dates/bases are not yet truthful

There are four related issues in `golden_vector/model/ticker_page.py` and the research path.

1. `resample("W-FRI").last()` relabels the week's last real observation as Friday. Current source histories end on 2026-08-11, while an AEM performance row claims 2026-08-14. Preserve the selected observation's actual trading date.
2. The artifact records one `rebase_date`, but each series independently takes its first observation on/after it. It can therefore use different actual anchors and still claim a shared anchor. It also emits pre-anchor points divided by a future base value.
3. `_usd_series` and `compute_horizon_returns_for_ticker` do not consistently exclude non-`OK` normalization rows. A stale/invalid FX endpoint can become a chart or a horizon marked usable.
4. Trimming to the earliest series end overwrites `series_as_of_date`, so the artifact cannot disclose the source's true later date and trim reason. Missing stock can also yield a healthy-looking empty artifact.

**Required fix**

- Select one actual observation date common to every included series; every rebased series must equal exactly 100 on that date.
- Emit no rebased value before that anchor.
- Preserve actual weekly observation dates.
- Carry separate `source_last_date`, `common_end_date`, and `trim_reason`.
- Use one shared `normalization_status == OK` eligibility helper in structural, horizon, performance, and FX-attribution calculations.
- Persist explicit ticker/series status rows for missing stock, stale/missing benchmark, and missing research kinds.
- Label the price basis honestly (adjusted-close return basis when available versus raw close); do not call an index-to-100 value “USD price.”

**Tests:** non-overlapping exchange holidays, stale FX at the start/end/interior, a late benchmark, a source ending mid-week, exact 100 anchors, no pre-anchor rebased values, and explicit missing-stock state.

### C5 - P1: degraded Tool D rows distort healthy ranks

`golden_vector/model/tool_d.py:442-462` computes AISC/component percentiles over all rows, then masks degraded rows only after the percentile calculation.

In the current workspace, recomputing over `resilience_data_status == "OK"` changed all 45 healthy scores, moved the median score by 4.44 points, and changed 25 of 45 ranks.

**Required fix**

- Build every component percentile and the AISC percentile from eligible rows only.
- Apply the same mask before the peer pool, not after the score.
- Add the invariance test: appending any number or magnitude of degraded rows cannot move a healthy company's component, score, or rank.

### C6 - P1: ticker percentile cohorts do not enforce source truth

Four defects share one fix boundary in `build_score_percentiles` and its stage inputs.

1. Tool D metrics are copied into both finance sources, even though the approved plan says Yahoo v1 must disable them with: **“resilience is computed on Our View inputs.”**
2. Eight currently non-OK Yahoo financial metric records enter EV/EBITDA, forward-P/E, or leverage cohorts.
3. Tool B metrics have no metric-specific normalization, staleness, field-source, or completeness predicate, although the plan says they do.
4. The stage loads generic `tool_d`, not guaranteed `tool_d_spot`. A custom Tool D scenario can therefore enter a later standalone ticker build while the UI calls the result “at spot.”

**Required fix**

- Resolve `tool_d_spot` explicitly and assert `gold_price_used == spot_gold_usd` within tolerance plus aligned generation identity.
- In Yahoo mode, Tool D rows are unavailable, have null percentiles, and carry the exact approved reason.
- Implement one central per-metric eligibility resolver. At minimum:
  - market-dependent metrics require a usable normalized snapshot and the configured FX-staleness policy;
  - Yahoo dual-source financial metrics require their relevant official fields/statuses to be usable;
  - manual-only AISC/reserve-life fields remain explicitly Our-View mining assumptions in either display mode and do not inherit an irrelevant Yahoo failure;
  - missing eligibility fails closed in this exact artifact.
- Persist the resolved exclusion reason and source date for each metric.

**Tests**

- custom Tool D scenario -> ticker build still selects spot;
- Yahoo Tool D unavailable with exact reason;
- adding a stale/contaminated/missing Yahoo row cannot move a healthy cohort;
- AISC remains labelled Our View under Yahoo mode;
- every ineligible row has null percentiles.

### C7 - P1 defensive boundary: zero/negative/non-finite FX can be marked `OK`

Current live FX histories are clean and the normal AUD/CAD/GBP -> USD direction, London pence scaling, backward-only matching, and staleness behavior all passed. Preserve those controls.

The latent bug is real: `build_fx_lookup` drops null rates but does not require a finite positive rate, and the history/snapshot status builders test missing FX rather than invalid FX. Zero, negative, or infinite rates can therefore create zero/negative/infinite USD values with status `OK`.

**Required lean fix**

- At the one shared FX boundary, accept only finite `rate > 0`.
- Make raw QA fail loud on invalid rates; downstream normalized rows must never be `OK` when a rate is invalid.
- Preserve the original source symbol/date and distinguish invalid from ordinary missing data when the artifact supports a reason.
- Require finite positive USD price/market-cap outputs for concepts that must be positive.

Test zero, negative, NaN, +/-infinity, invalid text, valid GBP control, and stale-but-valid rates in both history and snapshot normalization.

### C8 - P1/P2: artifacts are not universe-complete and validators check shape, not meaning

**Silent omission**

- `ticker_page_stage.py:381-407` and `:429-474` skip failed/missing performance and research tickers and only write a stage warning.
- The percentile universe is the union of rows that happened to arrive.
- A 60-of-61 artifact can therefore be classified healthy while the failed company has no item-level state.
- The gold-response producer also derives its universe from produced Tool B rows instead of starting with the configured Tool-B-enabled universe.

**Shape-only validation**

`contracts/ticker_page.py:318-361` checks columns, null keys, and duplicates. Readers can still accept bad enums, wrong dtypes, non-finite values, percentages outside 0-100, blank provenance, `OK` rows missing required values, or degraded rows with no reason. A manifest SHA is checked only if present rather than required.

**Required fix**

- Pass the configured universe into every builder.
- Persist explicit unavailable/status rows or one small coverage table for every expected ticker/source/kind; keep healthy companies rather than failing the whole universe.
- Add a lean artifact-aware semantic validator reused before persistence, during publication, and on read. Enforce exact dtypes, enums, finite/range rules, status/reason coherence, nonblank IDs/config hash, schema version, required SHA, and expected coverage.
- Empty can be a typed file, but it cannot mean `OK` for a required populated generation.

Do not build a general schema framework. Four/five small contract functions with shared primitives are enough.

### C9 - P1 contract gap: the research and gold-response packs cannot yet support the approved UI truthfully

**Research series**

The v1 horizon row keeps one return but drops the retained Full-Research ladder's gold return, equity return, gold delta, coverage flag/reason, start/end dates, and source identity. Row kinds can also be absent with no per-kind status. `features/returns.py` currently loses normalization status.

Version the research schema before M2 so the retained UI reads persisted fields 1:1. Carry per-kind status/reason, exact period, units, and provenance. Do not recompute the missing ladder values in a request handler.

**Gold response**

The approved plan says failing checks/reasons are persisted by finance source, but v1 has no such fields. Also close these cheap guards while versioning:

- line/probe inputs, slopes, intercepts, actuals, and outputs must be finite;
- config must require both dial bounds plus a distinct interior probe;
- spot must be tested explicitly;
- diagnostics should rank failure severity by `residual / tolerance`, not compare raw EPS and USD-million residuals;
- `OK` must require its mandatory evidence.

### C10 - P1/P2: one coherent ticker generation and its provenance are not guaranteed

1. `persist_ticker_page.py:131-137` flips four aliases sequentially. A pass-two fault can leave a mixed alias set; refresh deliberately continues and then builds model state by rediscovering those aliases. When all artifacts share the same foundation snapshot ID, alignment can miss the mixed ticker source generations.
2. A standalone ticker run calls itself non-authoritative but still updates discoverable aliases; a later unrelated model-state publisher can adopt them.
3. `_parquet_artifact` reads `source_run_id` from the alias, resolves an immutable file, then does not recompute the ID from that immutable content.
4. Percentile `source_run_ids` are discarded; stage `upstream_run_ids` remain empty; stock/gold performance provenance is often `unknown`.
5. Standalone benchmark resolution reads the mutable current options manifest rather than the model-state-selected generation. It can fall back to mutable cache data and still produce an `OK` recent line with `unknown` provenance.

**Required fix**

- Publish one atomic ticker-generation pointer containing every immutable path, hash, schema version, row/coverage summary, and generation identity. Publish it only after all artifacts validate.
- Model state must consume that successful pointer/explicit publish result, never rediscover a failed or standalone alias set.
- Resolve the benchmark manifest through the same model-state/in-flight context as the tools; verify immutable hash and generation. Missing proof produces a visible missing/stale marker, not a mutable fallback.
- Re-read identity from the immutable selected content and compare it to the alias/pointer before publication.
- Plumb foundation/tool/benchmark run IDs from the live refresh or current manifest. No healthy row carries `unknown` for a required source.

Fault-inject every alias/pointer boundary and prove the previous complete generation remains current.

### C11 - P2 but cheap: manual financial inputs need business-domain bounds

The manual store now correctly rejects NaN/infinity, but it still accepts economically impossible signs/ranges. Negative sustaining capex can increase the current FCF proxy; negative royalty/interest/D&A can improve estimates; and 125 can become a 125% tax rate.

Add field-specific bounds at the one manual-input boundary:

- production, AISC, cash cost, reserve life: positive when supplied;
- sustaining capex, D&A, interest, royalty: nonnegative;
- tax/royalty fractions: within the chosen `[0,1]` policy after one explicit percent conversion;
- preserve valid negative net debt (net cash) and define the existing negative-EBITDA policy explicitly.

Apply the same validation to form/CLI and CSV import; required bad CSV input must not silently coerce to null. Keep any cash-cost imputation explicitly labelled and non-rankable unless the policy says otherwise.

### C12 - P2 option guardrails: finish finite Greeks and completeness-first capture selection

**Greeks**

`black_scholes.py` uses `optional_float`, which accepts infinity, and does not consistently validate the risk-free rate or final output. Non-finite inputs can persist NaN/infinite Greeks. Its theta description also says long-premium theta is always negative, which is false for some deep-in-the-money puts at positive rates.

- Use finite coercion for spot, strike, DTE, IV, rate, day count, and every returned Greek/price.
- Invalid inputs produce explicit unavailable values/reasons, not a crash or NaN.
- Call it **signed theta per calendar day**, not universally “time-decay cost.”
- Add a valid positive-theta put test plus NaN/+/-infinity tests.

**Chain history**

Cross-run same-day selection is fixed. The residual intra-frame path still chooses highest OI before calculating completeness. If one input frame contains a partial high-OI capture and a complete lower-OI capture, the partial can win.

- Gate every candidate capture first, then rank `complete > partial`, followed by OI and run ID.
- Add the adversarial intra-frame case. Preserve the already-correct cross-run and finite-count tests.

Also remove stale comments saying the v4 modules are dormant/active v3 now that the active schema is v4.

### C13 - P2: fresh option-v4 health is not version-set complete

Option carry-forward correctly validates a generation-specific full set, but fresh model-state completeness/alignment/freshness still relies heavily on the four static `REQUIRED_OPTION_ARTIFACT_NAMES`. A v4 state can therefore call the option domain complete/OK while v4-only chain history or availability is missing/corrupt.

Resolve the generation version first, then validate every member of `OPTION_ARTIFACT_SETS[version]` for presence, readability, hash, schema, source run, and snapshot alignment. Preserve the documented v3 legacy reader window.

---

## 3. New feature A: professional FX return attribution

### Product decision

Do **not** use the `$100 invested` device. Use professional return attribution.

Place a **Currency attribution** block directly below the Performance chart. It is part of Performance, not a new top-level page section. Show it when the normalized listing/quote currency is not USD. Do not infer it from headquarters, exchange country, or ticker suffix.

The universal line is:

> **FX changed the USD return by +7.7 percentage points.**

Then use a relationship-aware headline. For AAR.AX over the audited one-year window:

> **AUD strength offset about 87% of AAR's local-currency decline.**

Supporting figures:

| Component | AAR.AX 1Y illustration |
|---|---:|
| Local share return (AUD) | -8.8% |
| AUD/USD rate return | +8.4% |
| FX contribution to the USD return | +7.7 percentage points |
| USD-investor return | -1.1% |

Never headline `FX contribution / final USD return` blindly. When local and FX effects offset and the final return is near zero, it explodes; AAR would read around -670%, which is mathematically calculable and economically useless.

### Exact calculation

Let `L` be local return basis and `X` be USD per one unit of listing currency:

```text
r_local = L1 / L0 - 1
r_fx    = X1 / X0 - 1
r_usd   = (1 + r_local) * (1 + r_fx) - 1
fx_contribution_pp = r_usd - r_local
                   = (1 + r_local) * r_fx
```

The persisted reconciliation must close within a tight tolerance against `return_basis_usd` and the selected performance-chart endpoints.

### Narrative matrix

| Relationship | Headline rule |
|---|---|
| `SAME_DIRECTION` | “FX accounted for X% of the total USD gain/loss,” where `X = abs(fx_contribution_pp / r_usd)`. |
| `OFFSET` | “FX offset X% of the local gain/loss,” where `X = abs(fx_contribution_pp / r_local)`. |
| `REVERSAL` | “FX more than offset the local move and reversed the USD result.” Show signed values; do not force a misleading percentage headline. |
| `LOCAL_FLAT` | “The result was primarily currency-driven.” Show signed values. |
| `UNAVAILABLE` | Explain the missing/stale/invalid endpoint; do not fabricate attribution. |

Use tested near-zero tolerances only to avoid division noise. The signed values remain visible in every available case.

### Persisted contract

Add one small manifest-first `ticker_page_fx_attribution` artifact, one row per configured ticker and `1Y/3Y/5Y` horizon, including explicit `NOT_APPLICABLE_USD` rows that the UI hides:

- ticker, horizon, quote currency;
- exact chart start/end observation dates;
- local start/end values and return;
- FX start/end rates, source dates/symbols, staleness/status, and FX return;
- USD start/end values and return;
- `fx_contribution_pp`;
- relationship enum;
- nullable `share_of_usd_move` and `offset_of_local_move`;
- attribution status/reason;
- price/return basis label;
- normal ticker provenance plus foundation input ID.

Compute it beside the performance producer so both use one shared endpoint-selection primitive. Do not re-find dates or calculate attribution in Python serve code or JavaScript.

### UI details

- Follow the selected `chart_h` (1Y/3Y/5Y).
- Show the headline, then the three/four signed components and exact period.
- One small `?` explains listing-currency attribution versus operating/revenue currency exposure. This feature does **not** measure the latter.
- No extra FX line on the main chart in v1 and no `$100` text anywhere.
- Use the same shared implementation later if FX attribution is approved for Portfolio or Candidate Finder, but display it only on ticker detail in this milestone.

---

## 4. New feature B: current AISC and historical downside behavior

### Product decision

Add an open **Cost position and downside record** card near the top of Market Behaviour, after the core beta/rug context. Add a small link from the Corporate Finance AISC fact to this card.

Do not create an AISC/downside composite score and do not imply causation. Show two pieces of evidence side by side:

1. **Current reported AISC:** value, source/verification date, and lower-cost peer standing.
2. **Historical large-fall record:** exact hits/qualifying weak-gold weeks, rate, period, and lower-hit-rate peer standing.

Safe example structure after rebuilding the corrected data:

> “AAR is relatively low-cost versus eligible producers. Its historical large-fall rate during weak-gold weeks is near the peer middle.”

Do not hardcode the earlier `47/212` AAR example: C2 changes the event definition and the final rebuilt count must be used.

### Exact downside definition after C2

> Among weeks in gold's rolling weakest 20%, how often did the stock's ordinary weekly price return fall by at least 10%?

- Gold tail: rolling 156-week distribution with a 52-week warm-up, from Tool C config.
- Stock threshold: exact ordinary return <= -10%, not -10 log points.
- Display exact numerator and denominator and the period.
- Require Tool C score eligibility and minimum-event policy.

### Lean data change - reuse percentiles, do not add a sixth artifact

Both AISC and `downside_hit_rate` already exist in `ticker_page_percentiles`. Version that contract and add nullable metric-evidence fields rather than building another feature-specific artifact:

- `eligible_observation_count` (qualifying weak-gold weeks);
- `hit_count` (exact large-fall weeks; add it upstream in Tool C rather than reconstructing from a rounded rate);
- `source_period_start` / `source_period_end`;
- field-level source/verification status/date.

Configure the exact count/source columns per metric in the 19-metric catalog or a shared resolver. All unrelated metrics keep these fields null.

AISC is a company-reported/manual mining assumption in the current model even when the finance toggle says Yahoo. Keep the source label explicit and unchanged; do not imply Yahoo supplied it.

### Peer context

Use two existing percentile-rug primitives in the open card. Behind a closed **Peer relationship** disclosure, render a small scatter:

- x = current AISC;
- y = corrected historical large-fall rate;
- only finite, eligible paired producers;
- selected ticker highlighted;
- accessible data-table twin;
- no fitted line and no new score in v1.

Required caveat:

> “Current reported AISC is compared with historical share-price behavior in today's surviving eligible universe. The association does not establish causation.”

The serve layer may pair already-persisted AISC/downside rows for display, but it must not calculate a correlation, cohort statistic, or eligibility rule in the request path. If a coefficient is added later, compute/persist its method, sample size, period, and uncertainty first.

Reuse/generalize `serve/charts.py` rug/scatter/table primitives. Do not create a second chart implementation or a new JavaScript module for a static peer plot.

---

## 5. Architecture and plan amendments

Apply these edits to `claude_ticker_page_plan.md` while implementing:

1. Phase One remains **awaiting Codex corrections/live acceptance**, not complete for product serving.
2. The ticker page now has **five** persisted ticker artifacts: the corrected four plus `ticker_page_fx_attribution`. AISC/downside reuses percentile v2.
3. Version performance/research/percentiles where meanings or fields change; do not silently change v1 semantics.
4. Extend ProjectPaths, model state, alignment, pruning, cache identity, corruption states, and the atomic ticker-generation pointer for the FX artifact.
5. Add the `Cost position and downside record` card within Market Behaviour; page top-level order does not change.
6. Remove the stale M3 milestone text `(+ lab_dial.yaml move)`. Section 10 correctly says that refactor is outside this project.
7. M2 loaders consume only manifest/ticker-generation-resolved immutable artifacts and assemble view models; no analytics in request handlers.
8. M3 keeps the approved order: Performance -> Corporate Finance -> Market Behaviour -> conditional Options -> Compare on your own terms -> closed Inputs/notes.

The current legacy page still shows old ordering/composites/options behavior. Do not count that as Phase-One failure, but M3 acceptance must still remove/rewrite it exactly as the approved requirements specify.

---

## 6. Required implementation order

### Gate A - repair existing meanings

1. C1 AISC margin/breakeven semantics and names.
2. C2 exact simple-return hit thresholds.
3. C3 Tool A availability dates.
4. C7 FX finite-positive boundary and C11 manual-domain bounds.
5. Rebuild affected Tool A/B/C/D outputs and record before/after changes.

### Gate B - repair ranking and persisted contracts

6. C5 eligible-only Tool D pools.
7. C6 per-metric eligibility, Yahoo isolation, and spot Tool D authority.
8. C4 real performance dates/shared anchor/status; research normalization.
9. C8/C9 semantic contracts, universe coverage, research v2, and gold-response evidence.
10. C10 atomic ticker-generation publication, benchmark resolution, and complete provenance.
11. C12/C13 finite Greeks, intra-frame capture priority, and version-set option health.

### Gate C - add the requested data features

12. Add the shared performance-endpoint primitive and FX-attribution producer/artifact.
13. Add exact Tool C hit counts/period evidence and percentile v2 fields.
14. Update model-state/pruning/cache/loader contracts for the five-artifact generation.

### Gate D - M2/M3 UI

15. Build the read-only ticker serve spine.
16. Add Currency attribution under Performance.
17. Add Cost position and downside record in Market Behaviour plus the peer disclosure.
18. Complete the previously approved page sections/order/removals; do not let the two additions replace any existing acceptance requirement.

---

## 7. Acceptance tests

### Existing correctness

- AISC margin invariant and WDO-style threshold case.
- Exact simple +/-10% threshold boundary in log-return storage.
- Tool A row date never precedes either source date.
- Tool D scores/ranks invariant to degraded rows.
- Yahoo Tool D unavailable; bad Yahoo financial rows cannot alter cohorts.
- Custom Tool D scenario cannot enter spot percentiles.
- FX zero/negative/NaN/+/-infinity never returns normalized `OK`.
- One actual shared performance anchor at exactly 100; no invented Friday or pre-anchor values.
- Stale/invalid normalized rows cannot enter performance/research.
- Every configured ticker has an explicit state in every required artifact/domain.
- Semantic corruption probes fail for enums, dtypes, non-finite/ranges, blank provenance, contradictory status/reason, missing SHA, and partial coverage.
- Pass-two fault injection and standalone-build tests prove the previous generation remains authoritative.
- Immutable embedded IDs agree with ticker pointer and model state.
- Finite Greek tests including signed positive put theta.
- Intra-frame and cross-run option captures both prefer complete before OI.
- Fresh v3/v4 health validates the correct full artifact set.

### FX feature

- same-direction gain and loss;
- AAR-style offset and a full reversal;
- near-zero local/final return without an exploding percentage;
- USD listing explicit N/A and hidden UI;
- missing/stale/invalid endpoints with reason;
- 1Y/3Y/5Y exact reconciliation to the selected stock chart endpoints;
- minor-unit listing control (GBp -> GBP -> USD);
- no `$100` metaphor in rendered output;
- listing-currency caveat and exact dates/source visible.

### AISC/downside feature

- exact hit numerator, qualifying denominator, rate, and period agree;
- corrected ordinary-return threshold at the boundary;
- only finite eligible pairs enter strips/scatter;
- AISC lower-good and downside-rate lower-good orientation;
- degraded rows do not affect peer positions;
- AISC remains Our-View/company-reported under Yahoo mode;
- missing either side renders a reason rather than a conclusion;
- selected scatter point equals its accessible-table row;
- no causal/predictive wording, no fitted line, and no new composite score;
- keyboard, responsive, and disclosure accessibility checks.

### Final release gate

1. Focused calculation/contract/fault suites.
2. Ruff/type checks on changed modules.
3. Full deterministic pytest suite once at the final gate.
4. One real current-HEAD refresh that publishes option v4 plus all five ticker artifacts.
5. Every manifest-first loader reports `OK` or the expected explicit per-item degraded state.
6. Before/after diff for Tool A dates, Tool B margin/yield, Tool C hit rates, Tool D scores/ranks, Yahoo cohorts, and ticker percentiles.
7. One batched browser/real-JS M4 pass only after terminal/contract tests are green.
8. Mandatory branch/worktree integration audit before merge.

---

## 8. Review evidence and current integration state

- Current pin: `226670e`; local and `origin/dev-vic` matched at review start.
- One active worktree; no hidden unmerged feature branch was found. `dev-vic` is the only work not in `origin/main`.
- Focused current-HEAD architecture suite: 139 passed.
- Independent full deterministic suite at `226670e`: **1,905 passed in 1,451.31s**, exit 0.
- Independent `ruff check golden_vector tests`: **all checks passed**.
- Green is not proof of correct semantics here: existing tests intentionally expect several behaviors this review rejects, including Yahoo receiving Tool D values, missing-stock performance returning an empty frame, and `W-FRI` synthetic dates. Replace those expectations with the acceptance cases above.
- The live model-state inspected during review had not yet published the final current-HEAD ticker generation. Existing standalone ticker files are non-authoritative. A real refresh at the corrected code pin is mandatory before Phase One is accepted.
- Preserve these good fixes: manifest-first ticker reads; checksum verification when present; trading-day benchmark staleness; one selected price-basis column per performance series; missing-interior gold probe degradation; cross-run complete-first chain capture; option v4 reader window; and atomic final model-state pointer.

## Final decision

**CHANGES REQUIRED.** Fix C1-C13, rebuild one coherent generation, add the two features through the persisted contracts above, then continue M2/M3 and close M4. The intended result is not more complexity: it is a ticker page where every date, currency effect, peer comparison, AISC claim, and downside statistic means exactly what its label says.
