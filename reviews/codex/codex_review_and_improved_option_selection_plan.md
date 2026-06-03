# Codex Review And Improved Plan - Option Selection Liquidity Design

Grade: READY FOR RESEARCH REVIEW, NOT READY FOR CODING

Reviewed file: `reviews/codex/research_option_selection_liquidity_and_design.md`

Scope: planning/review only. No source code changes made.

## Bottom Line

The research direction is right: the current single 25-delta candidate picker is the wrong shape for Emanuel's decision workflow. The next product should become an `Options Liquidity & Scenario Lab`, not a one-contract recommender.

But the plan is still too broad and too assertive in places. Before coding, Claude should review the research citations and convert the design into a staged implementation plan with measurable thresholds from our own cached chains.

The biggest change I would make: do not use one hard `tradable / not tradable` gate as the main UX. Use three tiers:

| Tier | Meaning |
| --- | --- |
| Tradable candidate | passes conservative quote/liquidity gates |
| Watch / expensive | two-sided quote exists, but spread or liquidity is poor |
| No-trade | zero/missing bid/ask, unusable quote, or absurd spread |

This avoids repeating the current problem where the UI collapses to almost no candidates.

## What The Research Spec Gets Right

1. **Multiple buckets per horizon is the right product shape.** A single 25-delta pick cannot explain the option chain. The user needs near-ATM, directional, tail/hedge, most-liquid, and model-fit views.

2. **Relative bid/ask spread should be the primary liquidity metric.** The current UI shows too many contracts as simply missing. Spread cost is the thing Emanuel needs to see.

3. **`Last` must not be treated as executable.** The spec is correct that `Last` is informational and bid/ask/mid drive current quote economics.

4. **No-trade is a valid answer.** Many single-name gold miner options are thin. The tool should say that plainly rather than forcing weak candidates.

5. **GDX/GDXJ proxy logic must be measured before being claimed.** The spec correctly flags that proxy-option liquidity is intuitive but still needs proof from our own chains.

## Findings To Fix Before Coding

### 1. The Plan Needs Stages

The current research spec jumps from literature findings to a full redesign. That is risky. Split the work:

| Stage | Goal | Ship? |
| --- | --- | --- |
| S0 | Remove verbose UI text and make current table less broken | yes, quick |
| S1 | Build chain scanner and liquidity diagnostics, no UI redesign yet | yes, internal/testable |
| S2 | Add bucket selection and horizon cards | yes |
| S3 | Add no-trade/proxy recommendations after measuring GDX/GDXJ | yes, if proven |
| S4 | Add refresh button/background job | separate plan |

Do not combine all of this into one milestone.

### 2. The Suggested 10-20% Spread Gate May Be Too Strict For Miner Options

Read-only diagnostic on the current cached snapshot:

| Side | Contracts | Two-sided | Near-spot two-sided | Near-spot spread <= 10% | <= 20% | <= 30% | <= 50% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Puts | 3,207 | 320 | 105 | 2 | 15 | 26 | 45 |
| Calls | 3,852 | 370 | 95 | 10 | 26 | 38 | 51 |

Near-spot means strike within 20% of stock price. This shows that a 10-20% hard gate will still hide most of the chain. It may be the right line for `tradable`, but not for the whole UI.

Recommended tiers:

| Tier | Starting rule |
| --- | --- |
| Tradable | bid > 0, ask > 0, rel spread <= 20%, OI >= 1, premium >= 0.10 |
| Watch / expensive | bid > 0, ask > 0, rel spread <= 50%, OI >= 1 |
| No-trade | no two-sided quote, rel spread > 50%, or invalid price |

These are starting values only. Claude should research and then tune against the cached chains.

### 3. "High Volume Is Not Liquid" Needs More Nuance

The research spec says high volume should not be ranked because it can coincide with wider spreads. That is directionally useful but too absolute for implementation.

Better rule:

- spread is the primary liquidity/cost metric;
- OI measures depth/participation;
- volume confirms recent trading interest;
- volume should never override a terrible spread;
- volume can break ties between otherwise similar contracts.

This avoids a brittle score that ignores real market activity.

### 4. Expiry Selection Should Scan A DTE Band, Not Only Nearest Expiry

The current implementation chooses the listed expiry nearest the target horizon. That can miss a more liquid nearby expiry. For example, a 60d target should probably scan a band such as 45-75 DTE and choose the best expiry/contract combination by liquidity and fit.

Recommended DTE bands for research/review:

| Label | Initial DTE band | UI stance |
| --- | --- | --- |
| 30d | 21-45 | Tactical / high decay |
| 60d | 46-75 | Default near-term |
| 90d | 76-105 | Default standard |
| 120d | 106-150 | Slower thesis |

These bands should be config-driven.

### 5. Buckets Need Clear Definitions

The current spec names useful buckets but does not fully define conflict resolution. Proposed definitions:

| Bucket | Candidate rule | Reject if |
| --- | --- | --- |
| Most liquid | highest liquidity score inside DTE band and sensible moneyness range | no two-sided quote |
| Near ATM | smallest absolute moneyness among watch/tradable contracts | spread > watch cap |
| Directional call | call delta 0.35-0.55, best liquidity score | spread > watch cap |
| Directional put | put delta -0.55 to -0.35, best liquidity score | spread > watch cap |
| Tail put | put delta -0.30 to -0.15, best liquidity score | spread > watch cap |
| Model fit | strike closest to modeled stock scenario, then best liquidity score | spread > watch cap |

If no contract qualifies, the bucket still renders as `No usable contract`, with the best rejected contract shown behind an expand/click detail.

### 6. The Liquidity Score Needs Exact Normalization

The proposed 60/15/10/10/5 score is fine as a starting concept, but the plan needs exact math:

```text
spread_score = clamp(1 - rel_spread / watch_spread_cap, 0, 1)
oi_score = min(log1p(open_interest) / log1p(oi_cap), 1)
volume_score = min(log1p(volume) / log1p(volume_cap), 1)
premium_score = 1 if mid >= min_premium else mid / min_premium
depth_score = near_spot_two_sided_contracts / target_depth_count, capped at 1

liquidity_score =
  0.55 * spread_score +
  0.20 * oi_score +
  0.10 * volume_score +
  0.10 * premium_score +
  0.05 * depth_score
```

This is more implementable than "normalized spread" without a denominator.

### 7. The UI Plan Should Be More Concrete

The wide 19-column table must go. Recommended detail page layout:

1. **Header strip**
   - ticker
   - stock price
   - snapshot date
   - source
   - refresh status/button placeholder

2. **Liquidity summary**
   - put tradable/watch/no-trade counts
   - call tradable/watch/no-trade counts
   - best DTE band
   - "single-name options look thin" warning if most buckets fail

3. **Side tabs**
   - puts
   - calls

4. **Horizon cards**
   - 30d tactical
   - 60d default
   - 90d default
   - 120d slower thesis

5. **Each horizon card shows compact rows**
   - bucket
   - expiry
   - strike
   - moneyness
   - bid/ask/mid
   - spread %
   - OI
   - volume
   - tier
   - select/use in calculator

6. **Expandable detail**
   - delta
   - IV
   - Yahoo link
   - why accepted/rejected
   - stale/zero quote explanation

7. **Scenario calculator**
   - only after user selects a specific contract/bucket

### 8. The Product Should Avoid Implied Recommendation Language

Do not call any output `best trade`, `recommended`, or `should buy`. Use:

- `Most liquid`
- `Model fit`
- `Directional`
- `Tail hedge`
- `Too thin`
- `Watch only`

This is clearer and safer for a beginner founder.

### 9. GDX/GDXJ Proxy Should Be A Measured Fallback, Not A Promise

The plan correctly says to measure GDX/GDXJ first. Make that a required stage:

1. Load GDX/GDXJ chains from cached options data.
2. Compute the same liquidity summary as miners.
3. Compare median spread, OI, volume, near-spot depth.
4. Only show proxy option suggestions if the proxy is materially better.
5. Always show basis-risk language.

If GDX/GDXJ chains are not cached, show `proxy unavailable until options refresh includes ETFs`.

### 10. Data Provider Risk Needs A Decision

The plan says yfinance is screening-only. That is probably right, but the implementation plan needs a decision:

| Choice | Use case |
| --- | --- |
| yfinance only | local screening, low cost, clear stale-data warning |
| Cboe DataShop EOD | better EOD quote quality and NBBO fields |
| live broker/API quote | execution-aware workflow, not needed yet |

For now: keep yfinance but label the tool `screening only`. Do not imply live executable pricing.

## Improved Implementation Plan

### Milestone A - Immediate UI Cleanup

Goal: fix the visible annoyance without changing candidate math.

Tasks:

1. Remove the long paragraph from the Option Trading overview.
2. Remove the long paragraph from ticker detail.
3. Keep only one compact cache/source note.
4. Collapse methodology/caveats into a `Method` section.
5. Make the current candidate table horizontally sane or temporarily reduce visible columns.

Acceptance:

- no long explanatory paragraph before the main table;
- stock price and snapshot date still visible;
- no source-code changes to selection logic.

### Milestone B - Chain Scanner And Metrics

Goal: compute contract-level metrics for every option contract.

New structures:

```text
OptionContractQuote
OptionContractMetrics
OptionLiquidityTier
OptionHorizonBand
OptionBucketCandidate
OptionChainScan
```

Metrics:

- bid/ask/mid/last
- rel_spread
- half_spread_cost
- moneyness_abs
- moneyness_label
- delta
- delta_gap_to_bucket
- OI
- volume
- premium_pct_spot
- IV
- quote_quality flags
- liquidity_score
- liquidity_tier

Acceptance:

- tests cover zero bid/ask, huge spread, stale/missing last, low premium, high OI but wide spread;
- diagnostic CLI or report can print per-ticker liquidity summary;
- no UI redesign required yet.

### Milestone C - Bucket Candidate Selection

Goal: choose multiple explainable buckets per side/horizon.

Tasks:

1. Define DTE bands in config.
2. For each ticker/side/horizon, scan all expiries in band.
3. Select bucket candidates using liquidity tier plus bucket fit.
4. Keep rejected best-near-miss candidates for explanation.
5. Do not hide watch-tier contracts; label them clearly.

Acceptance:

- each horizon can show more than one candidate bucket;
- 30d is labeled tactical;
- 60/90 are default comparison horizons;
- AEM-like strike 50 cannot become a normal candidate;
- NEM-like liquid contracts remain visible;
- PRU/BTG/AEM near-spot contracts with wide spreads show as watch/expensive, not invisible.

### Milestone D - UI Redesign

Goal: replace the 19-column table.

Tasks:

1. Add liquidity summary cards.
2. Add put/call tabs.
3. Add horizon cards.
4. Add compact bucket rows.
5. Add expandable contract details.
6. Move Yahoo links into action column or detail drawer.
7. Add beginner glossary for Last/Bid/Ask/Mid/IV.

Acceptance:

- no row text wraps into unreadable columns;
- user can compare liquid/watch/no-trade status at a glance;
- user sees why single-name options may be too thin;
- scenario calculator uses a selected bucket, not an implicit hidden candidate.

### Milestone E - Proxy Measurement

Goal: verify whether GDX/GDXJ are truly better option proxies.

Tasks:

1. Include GDX/GDXJ in options refresh or load if already cached.
2. Run same liquidity scan.
3. Compare miner vs ETF liquidity.
4. Add proxy suggestion only when measured proxy liquidity is better.

Acceptance:

- product never claims proxy liquidity without data;
- basis risk is visible;
- no proxy row appears if ETF chain is unavailable.

### Milestone F - Refresh Button

Goal: one button that refreshes all model data.

Keep this separate. It needs background job state, duplicate-run guard, logs, success/failure status, and cache invalidation.

## Recommended Claude Review Questions

Claude should review this improved plan and the source research before coding.

Questions:

1. Are the proposed spread tiers too strict or too loose for single-name gold miners?
2. Should DTE bands be symmetric around 30/60/90/120 or anchored to listed monthly expiries?
3. Are the bucket delta ranges appropriate for beginner directional calls and protective/speculative puts?
4. Should `volume` be included in score at 10%, or only shown as a display field/tiebreaker?
5. What is the minimum premium below which quote noise makes the contract unhelpful?
6. Should a watch-tier contract be selectable in the calculator, or only tradable-tier contracts?
7. Should the UI show both "watch" and "no-trade" rows, or hide no-trade behind diagnostics?
8. What exact source claims from the research doc need citation cleanup before being surfaced in product language?

## Final Recommendation

Do not code the full redesign yet.

First, have Claude verify the research claims and thresholds. Then implement Milestone A quickly to remove the obvious UI text/table problems. After that, implement B/C/D in order.

The most important product principle: show the option-chain landscape honestly. A weak but visible `watch / expensive` contract is more useful than a blank row, as long as the UI does not imply it is a good trade.

