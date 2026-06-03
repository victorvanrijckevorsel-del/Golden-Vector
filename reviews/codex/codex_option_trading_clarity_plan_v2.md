# Option Trading Clarity Plan v2

Author: Codex  
Purpose: revised implementation plan after Claude review  
Sources:
- `reviews/codex/codex_option_trading_clarity_plan.md`
- `reviews/codex/claude_review_codex_option_trading_clarity_plan.md`

Status: ready for Claude review before coding

## 1. Executive Decision

This should be split into two milestones:

1. **M1: Option Trading clarity and candidate safety**
   - Fix misleading candidates.
   - Make cached stock/option context obvious.
   - Show 30/60/90/120 candidate rows.
   - Add Yahoo expiry-chain links.
   - Simplify confusing overview labels and columns.

2. **M2: Refresh button**
   - Add a workspace button that refreshes all data the model depends on.
   - This is a background-job/status-page problem, not a synchronous table change.
   - Do not block the clarity fixes on this infrastructure work.

Reason: M1 is high-value and low-risk. M2 is important, but it can hang or duplicate data-fetch jobs if implemented casually.

## 2. Problem To Fix

The current UI can show a candidate that is technically listed but practically useless. AEM is the concrete example:

- Cached stock price: about 174.96.
- UI selected a 60d put with strike 50.
- That put has delta around -0.02.
- The target put is around -0.25 delta.
- Delta gap is about 0.23, so this is not a reasonable main candidate.

The candidate was chosen because the code picked the closest surviving option after liquidity filters, without checking whether the closest surviving option was still close enough.

The UI also hides important context:

- stock price is not prominent;
- cached data date/source is not prominent;
- Yahoo `last price` and Golden Vector `mid` are not distinguished clearly;
- `thin` and `Confidence` are unclear labels;
- overview P&L columns are not useful there.

## 3. Locked User Decisions

1. The user wants one row for each horizon: 30, 60, 90, and 120.
2. The user wants whole Yahoo option-chain links for each selected expiry.
3. Golden Vector should display cached prices only.
4. Yahoo links are for manual inspection and may show newer live data.
5. A strike like 50 for a stock around 175-178 should not show as a normal candidate.
6. The P&L/share columns should be removed from the Option Trading overview.
7. The refresh button must eventually refresh all model data, not just options.

## 4. Milestone M1: Clarity And Candidate Safety

### 4a. Coordinate With Existing Shipping-Safety Work

Start from the current committed UI state after shipping-safety fixes.

Preserve useful safety language:

- long-option premium can be lost;
- option scenario values are descriptive, not predictions;
- IV skew and IV/RV context remain available.

But simplify the overview:

- keep overview focused on "which ticker should I open?";
- move richer scenario and IV explanations to ticker detail where the user has context.

### 4b. Diagnostic First

Before changing selection rules, run a read-only diagnostic on AEM and at least one other liquid optionable ticker:

- selected expiry per horizon;
- number of puts/calls before tradability filters;
- number surviving tradability filters;
- surviving strikes, bid/ask, IV, delta, delta gap;
- reason near-the-money contracts failed if they failed.

Purpose: confirm whether AEM strike 50 happened only because selection lacked a delta-gap gate, or whether the tradability filter is wrongly rejecting good contracts.

Do not tune thresholds until this diagnostic is understood.

### 4c. Candidate Selection Rule

Keep the current broad method:

1. choose listed expiry nearest the target horizon;
2. filter tradable contracts;
3. compute Black-Scholes delta;
4. pick the listed strike closest to target delta.

Add one hard accept/reject gate:

- candidate must have `delta_gap <= delta_gap_warning_threshold`;
- use existing config value first: `delta_gap_warning_threshold: 0.10`;
- if review shows this is too strict/loose, rename or split into `candidate_max_delta_gap`.

Do not add three overlapping hard gates for moneyness, scenario-distance, and delta-gap. Delta-gap is the primary mathematical rule.

Use moneyness and scenario price as explanation:

- "strike is 71% below stock price";
- "gold -10% implies stock around 152, so strike 50 is far away";
- "nearest tradable contract was rejected because delta -0.02 is too far from target -0.25".

### 4d. Candidate Slots

The UI needs one row per horizon, even when no acceptable candidate exists.

Introduce a display/domain structure like `OptionCandidateSlot`:

- `horizon_days`
- `target_expiry`
- `candidate`
- `rejected_candidate`
- `status`: `accepted`, `rejected`, `none`
- `reason`

Existing code that expects `list[OptionCandidate]` can continue receiving only accepted candidates.

Preferred shape:

- selection core returns slots;
- existing `build_candidate_grid` wraps/filter accepted candidates for backward compatibility;
- Option Trading detail uses slots so it can render 30/60/90/120 rows consistently.

### 4e. Quality Labels

Use plain labels:

| Internal status | User label |
| --- | --- |
| accepted and small delta gap | Good fit |
| accepted but near threshold | Acceptable fit |
| rejected by delta gap | No acceptable candidate |
| no tradable contracts | No tradable contract |
| no listed chain | No listed options |

For AEM-like 60d strike 50:

> No acceptable 60d put candidate. The closest tradable contract was strike 50, but it is about 71% below the stock price and delta -0.02 is too far from the target -0.25.

### 4f. 120d Without Shrinking The Universe

Do not simply add 120d to `target_horizons_days` while leaving optionability unchanged.

Current optionability logic effectively requires every configured target horizon to have a usable put. Adding 120d there would silently downgrade names from `directly_hedgeable` to `thin`.

Plan:

- add 120d as a displayed candidate horizon;
- decouple optionability tier from the full displayed horizon set;
- preserve current optionability behavior by using core optionability horizons of 30/60/90, or explicitly configure `optionability_core_horizons_days`;
- do not require 120d for `directly_hedgeable` in this milestone.

This prevents a UI clarity change from changing the optionable universe.

### 4g. Ticker Detail Header

At the top of the Option Trading detail panel, show:

| Field | Example |
| --- | --- |
| Stock price | `AEM stock price: $174.96` |
| Options snapshot date | `2026-06-01` |
| Refresh run | `20260601T135914Z-update-data-f555b2fe` |
| Source | `Cached Yahoo Finance data via yfinance` |
| Risk-free rate | `3.60%` or explicit fallback |
| Cache warning | `Yahoo live pages may differ until data is refreshed.` |

Stock price must appear before candidate tables.

### 4h. Candidate Table Fields

Each put/call table row should show:

| Field | Notes |
| --- | --- |
| Horizon | 30/60/90/120 |
| Expiry | listed expiry date |
| Days | days to expiry from cached snapshot date |
| Stock Price | cached underlying price |
| Strike | selected/rejected strike |
| ITM/OTM | plain label |
| Moneyness | example: `11.4% OTM` |
| Last | cached Yahoo last trade price |
| Bid | cached Yahoo bid |
| Ask | cached Yahoo ask |
| Mid | Golden Vector midpoint used for modeling |
| Delta | option sensitivity |
| Delta Gap | distance from target delta |
| Fit | Good / Acceptable / No acceptable candidate |
| OI | open interest |
| Volume | volume |
| IV | implied volatility |
| Yahoo Chain | whole chain for that expiry |
| Why | one-sentence reason |

Important: show `Last` and `Mid` separately. The user compared Yahoo's `Last price` with Golden Vector's `Mid`, which created understandable confusion.

### 4i. Yahoo Chain Links

Each horizon row should link to the full Yahoo option chain for the row's expiry.

Implementation notes:

- build URL from ticker and expiry date;
- verify exact Yahoo URL parameter format during implementation;
- link is user-initiated and external;
- label clearly: `Open Yahoo chain for this expiry`.

Display warning:

> Golden Vector shows cached prices from the last refresh. Yahoo may now differ.

### 4j. Overview Cleanup

The overview should answer: "which tickers should I open?"

Recommended columns:

| Column | Reason |
| --- | --- |
| Ticker | opens detail |
| Stock Price | immediate option context |
| Down Beta | downside sensitivity |
| Up Beta | upside sensitivity |
| Tool A Confidence | model confidence, not trade confidence |
| IV Percentile | option-cost context |
| Optionability | plain English |
| Put Candidates | side-aware status |
| Call Candidates | side-aware status |
| Last Options Snapshot | cached-data visibility |
| Notes | concise warnings |

Remove:

- `Put P&L/share @ Gold -10% (60d)`;
- `Call P&L/share @ Gold +10% (60d, context)`.

Move those scenario values to detail only.

### 4k. Plain-English Labels

Replace raw labels:

| Current | New |
| --- | --- |
| `Confidence` | `Tool A Confidence` |
| `available` | `Usable candidate found` |
| `thin` | `Listed, but no usable candidate` or `Poor liquidity` |
| `none` | `No listed options` |

Tooltip/help text for Tool A Confidence:

> This is confidence in the stock-vs-gold sensitivity model. It is not option-price confidence and not a trade recommendation.

Use the same status language later in Candidate Finder.

## 5. Milestone M2: Refresh Button

The refresh button remains required, but should be a separate plan.

### 5a. Required Behavior

Button label:

`Refresh market + options data`

It refreshes all dependencies:

1. foundation market data with options enabled;
2. Tool A;
3. Tool B;
4. option features/candidate cache.

### 5b. Architecture

Do not implement this as a synchronous POST that blocks the browser.

Use a background-process plus status-page design:

- local-only POST starts a refresh job;
- duplicate-run guard prevents double-click duplicate jobs;
- status page shows running/completed/failed;
- output log is captured;
- final state shows updated snapshot/run ids;
- Option Trading caches are cleared after success.

The exact implementation deserves its own short plan before coding.

## 6. Data Model Plan

Prefer a view-model/slot layer over bloating `OptionCandidate` with UI-only language.

Likely structures:

- `OptionCandidateSlot`
- `OptionCandidateDisplayRow`
- `OptionTradingSourceContext`

`OptionCandidate` can stay focused on accepted tradeable candidate facts. If `last_price` is useful outside UI, it can be added there; otherwise flow it into the display row by looking up the raw chain row.

Option overview row likely needs:

- `current_stock_price`;
- `options_as_of_date`;
- `options_refresh_run_id`;
- side-aware put/call status labels.

## 7. Config Plan

Config changes:

```yaml
display_horizons_days:
  - 30
  - 60
  - 90
  - 120

optionability_core_horizons_days:
  - 30
  - 60
  - 90

delta_gap_warning_threshold: 0.10
```

Whether this lives inside `hedge_readiness.yaml` as new fields or reuses `target_horizons_days` should be decided during implementation, but the invariant is:

- 120d appears in the UI;
- 120d does not silently change `directly_hedgeable` classification.

## 8. Tests

Required tests:

1. AEM-like chain rejects 60d strike 50 as an accepted candidate.
2. Rejected candidate still renders a horizon row with reason.
3. Accepted 30d strike 155-like candidate renders as accepted when delta gap is within threshold.
4. One row renders for 30/60/90/120.
5. Adding 120d does not downgrade optionability when core 30/60/90 are present.
6. Candidate row shows stock price, expiry, days, ITM/OTM, moneyness, last, bid, ask, mid, delta, delta gap.
7. Yahoo chain URL is generated from ticker and expiry.
8. Cached-data header shows source, snapshot date, refresh run id, and warning.
9. Overview no longer renders put/call P&L/share columns.
10. Overview says `Tool A Confidence`, not `Confidence`.
11. Raw `thin` does not appear in user-facing option status.
12. Diagnostic test or fixture proves tradability survivors are inspectable enough to debug AEM-like cases.

Refresh-button tests belong to M2, not M1.

## 9. Acceptance Criteria For M1

M1 is done when:

- stock price is visible before option candidates;
- cached data date/source is visible;
- put/call candidate tables show 30/60/90/120 rows;
- a bad candidate like AEM 60d strike 50 is not shown as a normal recommendation;
- rejected horizons explain why;
- `Last`, `Bid`, `Ask`, and `Mid` are distinct;
- ITM/OTM and moneyness are visible;
- Yahoo expiry-chain links are present;
- overview no longer contains the confusing P&L/share columns;
- status/confidence labels are plain English;
- 120d does not silently shrink the optionable universe;
- test suite covers the AEM-like failure mode.

## 10. My Final Recommendation

Claude's review is directionally right. I would adopt these changes:

- yes: sequence after shipping-safety state;
- yes: split refresh into M2;
- yes: use delta-gap as the single hard gate;
- yes: diagnose AEM tradability before threshold tuning;
- yes: decouple 120d display from optionability classification.

I would not drop 120d, because Emanuel explicitly asked for it. I would make it display/candidate-level first, not a new requirement for being called directly hedgeable.

I would not use scenario-distance as a hard gate. It is better as explanation because it helps the user understand why a 155 put makes sense and a 50 put does not.

