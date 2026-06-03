# Option Trading Clarity Plan

Author: Codex  
Purpose: implementation plan for Claude review before coding  
Status: draft for review

## 1. Problem

The current Option Trading UI exposes technically correct fields, but it is not clear enough for a user deciding whether a put/call is sensible.

The AEM example shows the core failure:

- AEM stock price in the cached snapshot is about 174.96.
- The UI selected a 60d put with strike 50, mid 1.88, delta about -0.02.
- That contract came from cached Yahoo-derived option-chain data, but it is too far out-of-the-money to be shown as a normal candidate.
- The candidate selector was targeting a -0.25 put, but after liquidity filters it accepted the closest remaining option even though the delta gap was huge.
- The UI did not clearly show stock price, moneyness, ITM/OTM, data freshness, or why the candidate was selected.

There is also overview clutter:

- `Put P&L/share @ Gold -10% (60d)` and `Call P&L/share @ Gold +10% (60d, context)` are not useful in the overview table.
- `Confidence` is ambiguous because it means Tool A structural model confidence, not trade confidence.
- `Call Status: thin` is unclear to a non-technical user.

## 2. Locked User Decisions

1. Add a button in the UI to refresh all data the model uses from APIs.
2. The refresh should cover all dependencies, not options only.
3. The user wants one candidate for each horizon: 30, 60, 90, and 120.
4. The user wants links to the whole Yahoo option chain for the selected expiry, not exact-contract links.
5. Golden Vector should display cached prices only. Yahoo links are for manual inspection and may differ if the cache is stale.
6. A strike like 50 for a stock trading around 178 should not be shown as a normal candidate.
7. P&L/share scenario columns should be removed from the overview page.

## 3. Desired User Experience

### 3a. Option Trading Overview

The overview should answer only: "which tickers are worth opening?"

Recommended columns:

| Column | Reason |
| --- | --- |
| Ticker | Opens ticker detail page |
| Stock Price | Makes the option context legible immediately |
| Down Beta | Shows downside sensitivity to gold |
| Up Beta | Shows upside sensitivity to gold |
| Tool A Confidence | Renamed from `Confidence`; clarify this is model confidence |
| IV Percentile | Keep as market context |
| Optionability | Consider renaming display values to plain English |
| Put Candidates | Human-readable status, not raw `available/thin` |
| Call Candidates | Human-readable status, not raw `available/thin` |
| Last Options Snapshot | Makes cached data obvious |
| Notes | Short plain-English warnings |

Remove from overview:

- `Put P&L/share @ Gold -10% (60d)`
- `Call P&L/share @ Gold +10% (60d, context)`

Those belong in detail/scenario sections, not the high-level ticker list.

### 3b. Ticker Detail Header

At the top of the Option Trading detail panel, show a clear cached-data context block:

| Field | Example |
| --- | --- |
| Stock price | `AEM stock price: $174.96` |
| Options snapshot date | `2026-06-01` |
| Refresh run | `20260601T135914Z-update-data-f555b2fe` |
| Source | `Cached Yahoo Finance data via yfinance` |
| Risk-free rate | `3.60%` or explicit fallback |
| Cache warning | `Yahoo live pages may differ until you refresh data.` |

The stock price must be above the candidate table, not hidden inside scenario rows.

### 3c. Candidate Tables

Render one row for each horizon:

- 30d
- 60d
- 90d
- 120d

Each row should show either an acceptable candidate or a clear "no acceptable candidate" reason.

Candidate row fields:

| Field | Purpose |
| --- | --- |
| Horizon | 30d/60d/90d/120d |
| Expiry | Actual listed expiry date |
| Days | Actual days to expiry from snapshot date |
| Stock Price | Same cached underlying price used by the model |
| Strike | Contract strike |
| ITM/OTM | Plain label |
| Moneyness | Example: `11.4% OTM` |
| Last | Yahoo cached last trade price |
| Bid | Cached bid |
| Ask | Cached ask |
| Mid | Cached bid/ask midpoint used by Golden Vector |
| Delta | Supporting option sensitivity |
| Fit | Good / acceptable / poor / rejected |
| Open Interest | Liquidity |
| Volume | Liquidity |
| IV | Implied volatility |
| Yahoo Chain | Link to the whole chain for that expiry |
| Why | One short sentence explaining selection or rejection |

Important: the UI should distinguish `last_price` from `mid`. The current UI showing only `Mid` caused confusion when compared with Yahoo's `Last price` column.

### 3d. Status Language

Replace raw statuses in the UI:

| Current value | User-facing label |
| --- | --- |
| `available` | `Usable candidate found` |
| `thin` | `Listed, but no usable candidate` or `Poor liquidity` |
| `none` | `No listed options` |

Do not show `thin` as a badge without explanation.

### 3e. Confidence Language

Rename `Confidence` to `Tool A Confidence` or `Model Confidence`.

Plain-English tooltip/help text:

> This is the confidence in the stock-vs-gold sensitivity model. It is not a trade recommendation and not option-price confidence.

## 4. Candidate Selection Change

### 4a. Current Problem

Current selection:

1. Select nearest listed expiry for a horizon.
2. Filter tradable contracts.
3. Compute Black-Scholes delta.
4. Pick the contract closest to target delta.

This fails when the remaining contracts are all poor. A delta -0.02 put can be selected for a target -0.25 put if it is the least bad remaining option.

### 4b. Revised Rule

Keep delta as a useful supporting metric, but add hard sanity gates before showing a candidate as normal.

For puts:

- A candidate must be below the current stock price unless explicitly marked as ITM protection.
- A candidate must not be absurdly far below the current stock price.
- A candidate must be close enough to the modeled stock price under the default downside scenario.
- A candidate must have a delta gap within a configured threshold, or be shown as rejected/poor fit.

For calls:

- A candidate must be above the current stock price unless explicitly marked as ITM.
- A candidate must not be absurdly far above the current stock price.
- A candidate must be close enough to the modeled stock price under the default upside scenario.
- A candidate must have a delta gap within a configured threshold, or be shown as rejected/poor fit.

### 4c. Recommended Default Scenario Anchor

Use scenario-aware selection for user explanation:

- Put target scenario: gold -10%.
- Call target scenario: gold +10%.

Example for AEM:

- Stock price: about 175.
- Down beta: about 1.33.
- Gold -10% implies modeled stock move around -13.3%.
- Modeled stock price: about 152.
- A 155 put is intuitive.
- A 50 put is not.

The exact selection can still rank by delta/liquidity, but the displayed candidate must pass a moneyness/scenario sanity check.

### 4d. Proposed Candidate Quality Labels

| Quality | Meaning |
| --- | --- |
| Good | Liquid enough, reasonable moneyness, delta near target |
| Acceptable | Usable but not ideal; show explanation |
| Poor fit | Listed and tradable, but far from strategy target |
| Rejected | Do not show as a candidate; show reason in the horizon row |

For AEM 60d strike 50:

- It should be rejected or shown only as a poor-fit diagnostic, not as a normal candidate.
- Recommended user-facing text: `No acceptable 60d put candidate. Closest tradable contract was strike 50, but it is 71% below the stock price and delta -0.02, too far from the target.`

## 5. Refresh Button

### 5a. Required Behavior

Add a UI action:

`Refresh market + options data`

It should refresh all data the Option Trading page depends on:

1. Foundation / market data refresh with options enabled.
2. Tool A recomputation.
3. Tool B recomputation.
4. Option Trading cache invalidation/reload.

The UI should not imply the refresh is instantaneous if it runs server-side for a while.

### 5b. Implementation Shape To Review

This needs careful design before coding because the current WSGI app may not have a background-job framework.

Practical v1 options:

1. **Synchronous POST action**
   - Button posts to a local route.
   - Server runs the refresh commands.
   - Browser waits until complete.
   - Simplest, but can time out or feel frozen.

2. **Start-local-command action with progress page**
   - Button starts the refresh process.
   - Redirect to a status page that polls/logs progress.
   - Better UX, more code.

3. **CLI-copy fallback**
   - Button shows exact command to run.
   - Not enough for the user's request, but useful as a fallback if process launching is unsafe.

Recommendation: implement a local-only POST route with a progress/status page if the current workspace server can safely spawn a process. If not, start with synchronous local-only execution and clear "running" state.

Safety requirements:

- Local workspace only.
- No external paid APIs beyond already-approved data fetches.
- Prevent double-click duplicate refreshes.
- Show last run status.
- Capture failure output.
- Never run arbitrary user input as a shell command.

## 6. Yahoo Expiry Links

Each candidate/horizon row should include:

`Open Yahoo chain for expiry`

The link should point to the whole Yahoo option chain for the ticker and selected expiry.

Implementation note:

- Yahoo uses an expiry date parameter in option-chain URLs.
- Build this from the cached candidate expiry date.
- Verify the exact URL format in implementation because Yahoo page URLs can change.

Display warning:

> Golden Vector shows cached prices from the last refresh. Yahoo may now differ.

## 7. Data Model Changes

Likely additions to `OptionCandidate` or a nearby view model:

- `last_price`
- `moneyness`
- `moneyness_label`
- `itm_otm_label`
- `quality`
- `quality_reason`
- `target_delta`
- `target_delta_gap`
- `target_scenario_gold_move`
- `modeled_stock_price_at_target`
- `yahoo_chain_url`

Avoid overloading raw analytics models with UI-only language if a view model is cleaner.

## 8. Config Changes

Add 120d to the configured target horizons:

```yaml
target_horizons_days:
  - 30
  - 60
  - 90
  - 120
```

Add or use existing guardrails:

- `delta_gap_warning_threshold`: currently configured as `0.10`, but not used by candidate selection.
- Add a hard reject threshold if needed, for example `candidate_max_delta_gap`.
- Add moneyness guardrails, for example:
  - `put_min_moneyness`: reject puts with strike/current_price below a threshold.
  - `call_max_moneyness`: reject calls with strike/current_price above a threshold.
- Add scenario-distance guardrail, for example max distance from modeled scenario stock price.

The exact thresholds need Claude/product review. The important point is that a strike 50 put for a 175-178 stock must not pass as a normal candidate.

## 9. Tests

Add targeted tests before/with the code change.

Required test cases:

1. AEM-like chain rejects a 50 strike put for a 175 stock as a normal 60d candidate.
2. 30/60/90/120 horizon rows are rendered even when some horizons have no acceptable candidate.
3. Candidate table shows stock price, expiry date, days to expiry, ITM/OTM, moneyness, last, bid, ask, mid.
4. UI labels say `Tool A Confidence`, not just `Confidence`.
5. Overview no longer renders put/call P&L/share columns.
6. `thin` is not exposed raw to the user.
7. Yahoo chain URL is generated from ticker + expiry date.
8. Cached-data warning renders with manifest as-of date and refresh run id.
9. Refresh route cannot start duplicate refreshes.
10. Refresh route recomputes all dependencies or clearly reports failure.

## 10. Acceptance Criteria

The change is acceptable when:

- A user can see the stock price before reading any option candidate.
- A user can tell whether each candidate is ITM or OTM.
- A user can see the cached snapshot date/source.
- A user can open Yahoo's whole option chain for the selected expiry.
- The page shows 30d, 60d, 90d, and 120d.
- A bad candidate like AEM 60d strike 50 is not shown as a normal recommendation.
- The overview no longer shows confusing P&L/share scenario columns.
- `Confidence` and `thin` are explained or renamed.
- The refresh button updates all data needed by the Option Trading page.
- Tests cover the AEM-like failure mode.

## 11. Open Review Questions For Claude

1. Should bad candidates be completely hidden, or should the horizon row show the rejected contract and reason?
   - Codex recommendation: show the horizon row with `No acceptable candidate` and a short rejected-contract reason.

2. What exact moneyness guardrails should we use?
   - Codex recommendation: start conservative and config-driven. The AEM 50/175 case must fail.

3. Should scenario-aware target strike replace target-delta selection, or should it be an additional sanity check?
   - Codex recommendation: keep delta/liquidity for market sanity, but use scenario price as a user-facing reason and hard sanity check.

4. What is the safest refresh-button architecture in the current local WSGI app?
   - Codex recommendation: local-only route with duplicate-run guard and clear status reporting.

5. Should the overview show stock price for every optionable ticker?
   - Codex recommendation: yes.

