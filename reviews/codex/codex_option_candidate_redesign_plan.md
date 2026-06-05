# Option Candidate Redesign Plan

## Grade Target

READY FOR CLAUDE REVIEW. Do not implement until Claude has reviewed this plan and Emanuel has approved the final shape.

## 1. Problem

The current Option Trading detail page shows too many bucket rows per horizon:

- `Most liquid`
- `Near-ATM`
- `Directional`
- `Tail`
- `Model fit`

This makes the UI look precise, but in thin option chains those buckets often collapse onto the same contract. Example: for AEM, every 30d put bucket showed strike `155`. That is not useful. It gives the user five labels but one real contract idea.

The current UI also shows untradable / rejected rows, includes a visible `Half-spread Cost` column, and treats `30d` as a normal primary horizon even though it is often too short-dated and illiquid for Emanuel's workflow.

## 2. Locked User Decisions

1. Candidate shape:
   - For each target horizon, show four candidate slots:
     - put near-ATM
     - put directional
     - call near-ATM
     - call directional
   - This means up to 12 candidate rows per ticker across the three horizon bands.

2. Horizons:
   - Target around `60d`, `90d`, `120d`.
   - Do not force exact DTE.
   - Prefer the best liquid contract inside a flexible band, even if the actual expiry is closer to 70d for the 60d target, etc.
   - Remove `30d` from the primary candidate view.

3. Strike buckets:
   - Put near-ATM: OTM put, roughly `0% to 5%` below stock price.
   - Put directional: OTM put, preferred `15% to 20%` below stock price, allowed `12% to 22%` when liquidity is materially better.
   - Call near-ATM: OTM call, roughly `0% to 5%` above stock price.
   - Call directional: OTM call, preferred `15% to 20%` above stock price, allowed `12% to 22%` when liquidity is materially better.

4. Rejected/untradable display:
   - Do not show untradable contracts in the candidate table.
   - If no acceptable contract exists, show the slot as `No liquid candidate` with a short reason, not the rejected contract details.

5. Liquidity fallback:
   - Start strict.
   - If strict rules find nothing, loosen once and show a yellow/watch candidate.
   - Do not loosen repeatedly until garbage appears.

6. Pricing:
   - Use mid price only in candidate and scenario display.
   - Remove visible `Half-spread Cost`.
   - Keep bid/ask visible as context, but do not compute a separate half-spread cost column.

7. Language:
   - Use `Candidate`, not `suggestion`, `recommendation`, `best`, or `should buy`.

## 3. Proposed User-Facing Shape

Detail page section should change from side tabs with many buckets to a compact candidate matrix:

| Horizon Target | Actual Expiry | Side | Candidate Type | Strike | OTM % | Mid | Bid / Ask | Spread | OI | Volume | Tier | Select | Yahoo Chain |
|---|---|---|---|---:|---:|---:|---|---:|---:|---:|---|---|---|
| ~60d | 2026-07-17, 46 DTE | Put | Near-ATM | 180 | 2.9% | 12.80 | 11.90 / 13.70 | 14.1% | 704 | 1 | Tradable | Select | Open |
| ~60d | ... | Put | Directional | ... | 12-22% OTM | ... | ... | ... | ... | ... | Tradable/Watch | Select | Open |
| ~60d | ... | Call | Near-ATM | ... | 0-5% OTM | ... | ... | ... | ... | ... | Tradable/Watch | Select | Open |
| ~60d | ... | Call | Directional | ... | 12-22% OTM | ... | ... | ... | ... | ... | Tradable/Watch | Select | Open |

Repeat for `~90d` and `~120d`.

Rules:

- The candidate table should contain at most 12 rows.
- Rows with no candidate should show slot-level text only:
  - `No liquid candidate`
  - reason: `No contract in 12-22% OTM range passed relaxed liquidity rules.`
- Never show a rejected contract's strike, bid, ask, mid, or IV in the main candidate table.
- Each row should show actual expiry and DTE because target horizon is intentionally flexible.
- Add a short method disclosure:
  - `Open interest is existing open contracts, not today's volume. Volume is today's activity. Spread is ask minus bid divided by mid. Lower spread is usually better for entering/exiting.`

## 4. New Candidate Buckets

Replace the old visible buckets with:

```text
put_near_atm
put_directional
call_near_atm
call_directional
```

Implementation detail: these can be represented as generic `near_atm` / `directional` buckets scoped by side, or explicit bucket IDs. The UI should display:

- `Put near-ATM`
- `Put directional`
- `Call near-ATM`
- `Call directional`

Do not keep visible rows for:

- `most_liquid`
- `tail`
- `model_fit`

`most_liquid` should become an input to scoring, not a row. `tail` and `model_fit` are too confusing for the current workflow and are out of scope for this redesign.

## 5. Horizon Bands

Use these bands unless Claude strongly objects:

| Target | Allowed DTE |
|---:|---:|
| 60d | 40-80 |
| 90d | 75-110 |
| 120d | 105-150 |

Current default `OptionLiquiditySettings.band_for_horizon()` has `60: 46-75`, `90: 76-105`, `120: 106-150`. The plan should widen 60d/90d as above and remove 30d from display/config.

Important: actual expiry selection should be liquidity-aware, not simply nearest expiry. A 70d expiry with materially better spread/OI is allowed to win the `~60d` target.

## 6. OTM Definitions

Use sign-aware OTM math, not absolute moneyness alone.

For a put:

```text
otm_pct = (underlying_price - strike) / underlying_price
```

Valid OTM put requires `strike < underlying_price`.

For a call:

```text
otm_pct = (strike - underlying_price) / underlying_price
```

Valid OTM call requires `strike > underlying_price`.

Near-ATM target:

```text
0.00 <= otm_pct <= 0.05
```

Directional preferred:

```text
0.15 <= otm_pct <= 0.20
```

Directional allowed when liquidity is materially better:

```text
0.12 <= otm_pct <= 0.22
```

Do not allow ITM contracts in these candidate slots. If the most liquid option is ITM, it can influence liquidity context but should not become the near-ATM OTM candidate.

## 7. Liquidity Tiers

Keep three internal tiers:

- `tradable`
- `watch`
- `no_trade`

But UI candidate table should show only:

- `Tradable`
- `Watch`
- `No liquid candidate`

### Strict Pass

Candidate can be `Tradable` if:

- bid > 0
- ask > 0
- mid > 0
- implied volatility inside existing configured IV bounds
- relative spread <= strict threshold
- open interest >= strict threshold
- mid >= minimum premium
- OTM bucket fit passes

Suggested starting thresholds:

| Slot | Max Spread | Min OI | Min Mid |
|---|---:|---:|---:|
| Near-ATM | 25% | 100 | 0.20 |
| Directional | 35% | 50 | 0.10 |

### Relaxed Pass

If strict pass finds no candidate for a slot, run one relaxed pass:

| Slot | Max Spread | Min OI | Min Mid |
|---|---:|---:|---:|
| Near-ATM | 35% | 50 | 0.15 |
| Directional | 45% | 25 | 0.05 |

Relaxed candidates should be shown as `Watch`, not `Tradable`.

Hard floors:

- bid/ask/mid still must exist and be positive.
- relative spread above 45% should never be shown.
- no OI and no volume should generally not be shown unless Claude can justify an exception.
- no repeated loosening.

## 8. Scoring Within A Slot

The selector should choose the best liquid fit, not the exact DTE or exact strike.

Suggested score components:

```text
score =
  0.35 * spread_score
  0.25 * otm_fit_score
  0.20 * open_interest_score
  0.10 * dte_fit_score
  0.05 * volume_score
  0.05 * standard_monthly_bonus
```

Plain English:

- lower spread is better
- closer to the target OTM range is better
- higher open interest is better
- closer to target horizon is better, but not at the expense of liquidity
- volume helps, but should not dominate because it is one-day noisy
- standard monthly expiry can get a small bonus because it often has better liquidity

Do not use half-spread cost in the visible UI. It can be removed from scoring too unless Claude sees a reason to keep it internally; relative spread already captures the main friction.

## 9. Deduplication

Within each ticker and horizon target:

- A single contract must not appear twice.
- If put near-ATM and put directional choose the same contract, keep the bucket where it best fits and mark the other slot `No distinct liquid candidate`.
- Same for calls.
- Put and call candidates can never be duplicates because side differs.

The old `_unique_candidates()` currently dedupes by `(horizon_days, bucket, expiration, strike, option_type)`, which still allows the same contract to appear under multiple bucket labels. This must change for the new candidate display/grids.

## 10. Yahoo Chain Links

Each candidate row should have an `Open Yahoo chain` link for the exact selected expiry.

Requirements:

- Link should point to the current ticker's Yahoo options page.
- Link must select the exact expiration when possible.
- If Yahoo requires an epoch timestamp, compute it from the expiry date.
- If exact expiry-linking is unreliable, link to the options page and label it `Open Yahoo options`; do not pretend exact expiry is guaranteed.

The existing `_yahoo_chain_link(slot.ticker, expiry)` should be audited before reuse.

## 11. Files Likely In Scope

Primary:

- `golden_vector/hedge/options_liquidity.py`
  - Replace visible bucket logic with near-ATM/directional selection.
  - Add sign-aware OTM helpers.
  - Add strict/relaxed per-slot thresholds.
  - Add distinct-candidate deduping.

- `golden_vector/serve/detail_panels.py`
  - Replace two separate bucket tables with one compact candidate matrix or two side sections using the same 4-slot contract.
  - Remove visible `Half-spread Cost`.
  - Hide rejected contract details.
  - Add clearer glossary for open interest, volume, spread, and mid.

- `golden_vector/serve/option_trading_data.py`
  - Ensure displayed horizons are 60/90/120 only.
  - Ensure candidate grids and sizing selection can address the new bucket IDs.
  - Update `_allowed_buckets()` and selection query parsing.

- `config/hedge_readiness.yaml` or equivalent config model fields
  - Remove `30d` from display horizons.
  - Add/adjust DTE bands.
  - Add near/directional OTM ranges and relaxed liquidity thresholds if we want these configurable.

Tests:

- `tests/test_options_liquidity.py`
- `tests/test_option_trading_routes.py`
- `tests/test_option_trading_overview.py`
- `tests/test_option_trading_data.py`
- Any candidate-grid tests that currently assert old bucket IDs.

Possibly in scope:

- CLI markdown report if it renders old buckets.
- Snapshot/parquet schema tests if candidate bucket IDs are persisted.

Out of scope:

- Live API refresh button.
- Full-chain in-app browser/table.
- Backtesting.
- Tool C/Tool D logic.
- Recommendation/trade-decision thresholds.
- Real-time quote validation.

## 12. Proposed Implementation Steps

### Step 1 - Contract Audit

Read exact current tests and data contracts around:

- `OptionCandidate.bucket`
- `OptionCandidateSlot.bucket`
- `candidate_grids`
- `call_candidate_grids`
- sizing selection URL parameters
- markdown report references

Output a quick note in progress log before coding.

### Step 2 - Introduce New Bucket IDs Behind Feature-Compatible Helpers

Add new bucket IDs and labels:

```text
near_atm
directional
```

or explicit:

```text
put_near_atm
put_directional
call_near_atm
call_directional
```

Recommendation: keep `bucket` side-neutral (`near_atm`, `directional`) and use `option_type` for side. This minimizes schema churn and selection URL changes.

Remove `most_liquid`, `tail`, and `model_fit` from displayed slots. If old code still needs labels during transition, map old IDs only in tests or migration helpers, not in the primary UI.

### Step 3 - Add OTM Bucket Fit Helpers

Add pure helpers:

- `otm_pct(metric)`
- `is_otm(metric)`
- `near_atm_bucket_fit(metric)`
- `directional_bucket_fit(metric, allow_relaxed_range: bool)`

Tests:

- put below spot is OTM
- put above spot is ITM and rejected
- call above spot is OTM
- call below spot is ITM and rejected
- near bucket accepts 0-5%
- directional preferred accepts 15-20%
- directional relaxed accepts 12-22%

### Step 4 - Add Strict/Relaxed Slot Selection

Implement slot selection as:

1. Filter metrics to horizon DTE band.
2. Filter to side.
3. Filter to OTM bucket range.
4. Run strict liquidity pass.
5. If no strict candidate, run relaxed liquidity pass.
6. Score candidates.
7. Return `accepted` with `liquidity_tier=tradable` for strict, `rejected` or `accepted` with `liquidity_tier=watch` for relaxed depending on existing semantics.

Important semantic choice:

- For UI selectability, `Watch` should still be selectable if Emanuel chose "loosen the rules."
- Existing code uses `slot.candidate is not None` as selectable. Therefore relaxed `Watch` candidates likely need to be `candidate`, not `rejected_candidate`, with `liquidity_tier='watch'`.
- Update `is_usable_candidate()` carefully because Candidate Finder currently treats `slot.candidate is not None` as usable. If Watch becomes selectable, decide whether Candidate Finder should count watch candidates as "usable" or only tradable. My recommendation: Candidate Finder side filter should count only `tradable`, not `watch`, unless explicitly changed.

Claude should push hard on this semantic point.

### Step 5 - Deduplicate Per Horizon

After selecting the two buckets for a side and horizon:

- If same contract appears twice, keep the bucket with lower bucket-fit penalty.
- If tied, keep near-ATM over directional only when OTM <= 8%; otherwise keep directional.
- Mark the other as no distinct liquid candidate.

Tests:

- same strike/expiry for near and directional does not produce duplicate visible rows.
- no distinct candidate slot does not expose rejected quote values.

### Step 6 - Update UI

In `detail_panels.py`:

- Replace current put/call bucket tables with either:
  - one `Option Candidates` matrix grouped by horizon, or
  - two compact side tables with identical columns.

Recommendation: one matrix grouped by horizon is easier to compare:

```text
~60d target
  Put near-ATM
  Put directional
  Call near-ATM
  Call directional
```

Columns:

- Candidate
- Target
- Expiry / DTE
- Strike
- OTM
- Mid
- Bid / Ask
- Spread
- OI
- Volume
- Tier
- Select
- Yahoo Chain

Remove:

- Half-spread Cost
- rejected candidate row details
- `30d tactical / high time-decay`

Keep:

- Stock price visible in context table.
- Snapshot date and source.
- Risk-free fallback notice.
- Sizing calculator, but default selected bucket should use the new candidate IDs.

### Step 7 - Update Sizing Selection

Update query handling:

Existing URL shape:

```text
/ticker/AEM?lens=option-trading&side=put&horizon=60&bucket=most_liquid#option-sizing
```

New examples:

```text
/ticker/AEM?lens=option-trading&side=put&horizon=60&bucket=near_atm#option-sizing
/ticker/AEM?lens=option-trading&side=call&horizon=90&bucket=directional#option-sizing
```

Invalid bucket should fall back to first selectable candidate for that side/horizon, with a note.

If no selectable candidate exists, sizing calculator should display no selected contract and explain why.

### Step 8 - Update Option Trading Overview

The overview should not say "put status available" just because any old bucket has something.

Recommended status labels:

- `Tradable candidate`
- `Watch candidate`
- `No liquid candidate`

For each ticker, status should be based on the new candidate slots:

- tradable if at least one near/directional slot is strict tradable
- watch if no tradable but at least one relaxed watch
- no liquid candidate otherwise

Candidate Finder side filters should probably use only tradable by default. If using watch too, label it clearly.

### Step 9 - Tests And Fixtures

Add fixture chains that prove:

1. 30d contracts exist but are not displayed.
2. 70d can win the ~60d target over a weaker exact/closer expiry.
3. Near-ATM put uses 0-5% below spot.
4. Near-ATM call uses 0-5% above spot.
5. Directional put uses 12-22% below spot when liquidity is better.
6. Directional call uses 12-22% above spot when liquidity is better.
7. Relaxed watch candidate appears when strict fails.
8. No no-trade contract appears in the candidate table.
9. Duplicate same contract across buckets is collapsed.
10. Half-spread cost is not rendered.
11. Mid price is used in scenario/sizing display.
12. Yahoo chain link includes the selected expiry if supported.

### Step 10 - Browser Verification

Use the in-app browser on AEM:

- confirm no 30d candidate group
- confirm ~60/~90/~120 groups
- confirm each group has max four rows
- confirm no repeated same strike/expiry under multiple bucket names
- confirm no `Half-spread Cost`
- confirm no untradable row details
- confirm Yahoo chain links are visible
- confirm stock price remains visible
- confirm page does not horizontally overflow on narrow viewport

## 13. Acceptance Criteria

1. Primary option candidate UI shows target horizons ~60d, ~90d, ~120d only.
2. Each target horizon shows up to four candidates: put near-ATM, put directional, call near-ATM, call directional.
3. Candidate expiry can be flexible inside the allowed DTE band.
4. Candidate strike can be flexible inside the OTM bucket, including directional 12-22% when liquidity is much better.
5. No untradable contract details appear in candidate rows.
6. No duplicate contract appears twice inside the same horizon/side.
7. Half-spread cost is removed from visible UI.
8. Mid price is the displayed candidate price and the sizing/scenario basis.
9. Candidate rows include actual expiry date and DTE.
10. Candidate rows include bid/ask, spread, OI, volume, and tier.
11. Yahoo chain link is available for each candidate row.
12. Language uses "Candidate", not recommendation language.
13. Full test suite passes.
14. Browser verification passes on AEM current cached data.

## 14. Key Risks For Claude To Review

1. `Watch` semantics:
   If relaxed candidates are selectable, they will likely be `slot.candidate`, but Candidate Finder currently treats `slot.candidate is not None` as a usable side candidate. Should Candidate Finder count Watch candidates or only strict Tradable candidates?

2. Bucket ID migration:
   Old URL/query/test/report paths may assume `most_liquid`, `tail`, or `model_fit`. The plan should not silently break sizing links or reports.

3. Liquidity score overfitting:
   The proposed weights are intuitive, not academically calibrated. They should be simple and explainable, but not pretend to be predictive.

4. DTE band overlap:
   `90d` and `120d` bands are adjacent but not overlapping in the proposal. If a very liquid 105d contract exists, it falls into 90d/120d boundary behavior. Claude should verify exact edge handling.

5. Duplicates:
   Deduplication must operate on actual contract identity `(option_type, expiration, strike)`, not bucket label.

6. OTM sign:
   Existing `moneyness_pct` is absolute distance from spot. It is insufficient for "OTM only"; sign-aware logic is mandatory.

7. Source data quality:
   Yahoo chains sometimes have zero bid/ask with stale last price. The plan must not let last price make a no-bid/no-ask contract look usable.

8. Overview/Detail consistency:
   Option Trading overview, Candidate Finder side filters, and ticker detail candidates must agree on what "candidate available" means.

9. User trust:
   If no candidate exists, the page should say so plainly. Do not fill slots with bad contracts just to keep a complete 12-row matrix.

## 15. Recommended Open Decision Before Coding

Claude should specifically answer this before implementation:

Should relaxed `Watch` candidates count as "available" for:

1. ticker detail Select links?
2. Option Trading overview status?
3. Candidate Finder side filters?

My recommendation:

- selectable in ticker detail: yes
- overview: show separate `Watch candidate`
- Candidate Finder side filters: no, use strict Tradable only unless user explicitly chooses a Watch-inclusive filter later
