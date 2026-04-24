# Tool A Rebased Gold vs Stock Chart Analysis

## Executive Verdict

This is a **good idea as an exploratory chart**, but **not as an official Tool A metric layer**.

The chart is useful because it gives the user an immediate visual answer to:

- how the stock has performed relative to gold over a chosen window
- whether the stock tends to overshoot, lag, or diverge from gold
- whether the relationship looks smooth, noisy, or unstable

But the current proposal becomes conceptually wrong when it starts calling the visual spread between the two rebased lines "`delta`" and the change in that spread "`gamma`".

For Tool A, that would be a mistake.

Why:

- official Tool A delta is now a **structural sensitivity measure**, not a rebased path gap
- official Tool A gamma is now a **regime/sensitivity concept**, not line acceleration on a rebased chart
- the Guo / Leung / Ward logic is about **dynamic implied leverage and factor behavior**, not about the distance between two indexed price paths

So my recommendation is:

- **build this chart**
- but build it as an **exploratory relative-performance view**
- **do not** let it redefine Tool A delta or gamma

## Bottom-Line Recommendation

| Question | Verdict |
|---|---|
| Should this chart exist in Tool A? | **Yes** |
| Should it be part of the official structural score logic? | **No** |
| Should the chart's line gap be called delta? | **No** |
| Should the chart's line acceleration be called gamma? | **No** |
| Best role | **Exploratory visual companion to official Tool A metrics** |

## What The Chart Actually Measures

If both series are rebased to 100 at the first common date in the selected window, the chart is showing:

- cumulative stock performance from the chosen start
- cumulative gold performance from the chosen start
- relative path divergence between the two

In simple terms:

- if the stock line is above the gold line, the stock has outperformed gold since the start date
- if it is below, it has underperformed gold since the start date
- if the stock line moves more violently, it is behaving more aggressively or more noisily than gold

Mathematically, this is an **indexed cumulative performance chart**.

If:

- `S_t` = USD-normalized stock price
- `G_t` = USD gold price
- `t0` = effective common start date

then:

- `stock_index_t = 100 * S_t / S_t0`
- `gold_index_t = 100 * G_t / G_t0`

This is a valid and standard visualization.

It is good for showing **path behavior**.

It is **not** the same thing as a structural sensitivity estimate.

## What The User Can Learn From It

This chart can be genuinely useful because it helps the user see things that tables hide.

### 1. Relative outperformance and underperformance

The user can immediately see:

- whether the stock has beaten gold over the chosen window
- whether it has lagged gold even in a favorable gold period
- whether the stock is only strong during a narrow subperiod

### 2. Timing and path shape

The user can see:

- whether the stock tends to move before gold, with gold, or after gold
- whether outperformance is persistent or quickly fades
- whether the stock overshoots gold on rallies and collapses harder on drawdowns

### 3. Visual instability

The chart can show:

- noisy zig-zag behavior
- repeated divergence then snap-back
- stock-specific behavior that clearly is not just "gold exposure"

That is valuable because Tool A is not only about raw leverage. It is also about whether the relationship is clean or messy.

### 4. Window dependence

This is one of the most useful educational features.

The same stock can look:

- excellent from one start date
- mediocre from another
- terrible from a third

That teaches the user an important truth:

**path-based visuals are sensitive to the chosen window.**

That is not a flaw if the product explains it clearly.

## What The User Cannot Safely Infer From It

This is the most important caution section.

### 1. The chart does not estimate official delta

The chart does **not** tell you structural delta in the Tool A sense.

Why:

- rebased price distance is cumulative relative performance
- official Tool A delta is a **returns-based sensitivity estimate**
- those are different concepts

Two stocks can end with almost identical rebased charts and still have different:

- weekly beta to gold
- asymmetry
- confidence
- downside fragility

### 2. The chart does not estimate official gamma

The proposal says:

- delta = gap between normalized stock and normalized gold
- gamma = change in that gap over time

That should **not** be adopted.

Why:

- the gap is not delta
- the derivative of that gap is not gamma
- the result would conflict with the current Tool A definitions and with the Guo paper framing

At best, that would be a measure of:

- path divergence speed
- relative acceleration
- cumulative outperformance momentum

Those may be interesting, but they are **not Tool A gamma**.

### 3. The chart does not prove causality

If the stock pulls away from gold, the user still does not know whether that was caused by:

- gold leverage
- idiosyncratic company news
- market risk-on / risk-off
- FX contamination if the upstream normalization were bad
- short-term speculative behavior

So the chart is a clue, not proof.

### 4. The chart can overstate cherry-picked narratives

If the user picks a start date near:

- a stock low
- a gold high
- a company-specific event

the visual story can become very flattering or very misleading.

This is why the chart must be explicitly labeled as **window-sensitive**.

## Where This Fits The Guo / Leung / Ward Logic

The Guo / Leung / Ward paper is important because it frames gold miner equities as:

- option-like claims on gold-linked assets
- with dynamic leverage
- influenced by gold price regimes and broader market effects

That logic **does support** adding richer path-based visuals.

But the paper does **not** say that a rebased price chart is the right estimator of implied leverage.

In fact, the paper is much closer to:

- dynamic factor exposure
- changing beta / leverage
- state dependence

than to:

- indexed cumulative line gaps

So the correct relationship is:

- the chart can **illustrate** option-like path behavior
- the chart cannot **replace** the structural measurement of it

## Where This Fits The Implementation Guide

The implementation guide says delta should be measured from:

- weekly prices
- weekly log returns
- regression slope / beta

That is much closer to the current structural Tool A than to the proposed chart delta.

So if this chart is added, it should be framed as:

- a companion visual
- not a replacement for the guide's sensitivity logic

## Main Problems In The Current Proposal

## 1. The optional delta definition is not correct for Tool A

The proposal says:

- delta = difference between normalized stock and normalized gold at each date

That is not a sensitivity measure.

It is better described as:

- rebased performance spread
- cumulative outperformance gap

That can be useful, but it should not be called delta.

## 2. The optional gamma definition is not correct for Tool A

The proposal says:

- gamma = change in delta over time

If delta itself is only a path gap, then this gamma becomes:

- change in path gap
- relative acceleration

Again, potentially interesting, but not official gamma.

If we use that name inside Tool A, we will make the product less accurate, not more accurate.

## 3. Start-date sensitivity is a major risk

This is inherent to rebasing.

A stock that is structurally good can look weak if the start date is:

- immediately after a local stock rally
- or before a temporary correction

A fragile stock can look brilliant if the start date is:

- right after its own drawdown low

So the chart should never be shown without:

- the selected horizon clearly displayed
- the effective rebasing date clearly displayed
- a warning that the picture changes with the chosen start point

## 4. Daily alignment can create false detail

Gold and equities do not always share the exact same trading calendar.

If the chart uses daily data naively, the user may over-read:

- holiday gaps
- market closure differences
- stale dates

Given Tool A's official model already works on **weekly USD-normalized returns**, the safest default for this chart is:

- **weekly cadence by default**

Daily can exist as an exploratory toggle later, but weekly is more aligned with the framework.

## 5. The chart alone does not separate leverage from noise

A volatile stock can visually look "interesting" simply because it is chaotic.

That does not mean:

- stronger structural delta
- better convexity
- better optionality

It may just mean:

- higher residual noise
- stock-specific instability

That is why this chart should sit next to:

- official structural delta
- official gamma / asymmetry
- volatility diagnostics
- confidence

## What To Call Things Instead

If this chart is added, I would avoid delta/gamma language entirely inside the chart layer.

Use names like:

| Proposed current name | Better name |
|---|---|
| Delta (line gap) | `rebased_performance_spread` |
| Delta (line gap) | `cumulative_outperformance_gap` |
| Delta (line gap) | `relative_path_spread` |
| Gamma (change in gap) | `relative_path_acceleration` |
| Gamma (change in gap) | `spread_momentum` |

Best of these:

- `relative_path_spread`
- `relative_strength_ratio`
- `relative_path_acceleration` only if really needed

But my stronger recommendation is:

- show the chart
- maybe show a ratio panel
- do **not** create a second pseudo-gamma layer unless there is a very clear use case

## Better Analytics To Pair With The Chart

If you want this view to be accurate and decision-useful, I would pair it with two better secondary measures.

## 1. Relative strength ratio

Instead of only:

- `stock_index - gold_index`

also compute:

- `relative_strength = stock_index / gold_index`

Why this is better:

- it scales naturally
- it avoids some of the interpretive awkwardness of simple point differences
- it answers: "How much has the stock outperformed or underperformed gold on a relative basis?"

Even better:

- `log_relative_strength = ln(stock_index / gold_index)`

That is mathematically cleaner and additive through time.

## 2. Drawdown comparison

Add an optional small panel or summary for:

- stock drawdown from rebased high
- gold drawdown from rebased high

This is useful because many miners look attractive on upside but are much uglier on downside.

That helps the user connect:

- relative path behavior
- downside fragility
- volatility

## 3. Official structural metric cards beside the chart

This is probably the most important design recommendation.

Beside the rebased chart, show the official Tool A metrics:

- structural delta core
- gamma / fragility interpretation
- asymmetry
- confidence
- total / residual / downside volatility

That stops the chart from becoming a free-floating narrative device.

## How The User Should Interpret The Chart

Here is the interpretation layer I would actually teach in the product.

| Visual pattern | Likely meaning | What user should check next |
|---|---|---|
| Stock and gold move closely together | strong path similarity in this window | check official delta and confidence |
| Stock rises faster than gold and falls faster too | leveraged or high-vol behavior | check structural delta and downside volatility |
| Stock outperforms gold on rallies but gives it back quickly | unstable or event-driven linkage | check confidence and residual volatility |
| Stock lags gold even during gold strength | weak linkage or company-specific drag | check LOW_LINKAGE / fragility / Tool B |
| Lines cross repeatedly | unstable relationship | check confidence and window consistency |
| Stock diverges sharply around one event | company-specific catalyst or shock | do not treat as structural gold behavior without confirmation |

## Best Design For The Actual Chart

## Recommended chart type

### Main panel

- X-axis: date
- Y-axis: rebased index, start = 100
- Line 1: stock, rebased
- Line 2: gold, rebased

### Supporting panels

I would strongly recommend:

1. **Main chart:** rebased stock vs gold
2. **Secondary panel:** relative strength ratio or log-relative-strength
3. **Metric cards:** official structural Tool A outputs

That is much stronger than trying to overload the main chart with pseudo-delta and pseudo-gamma.

## Default cadence

For Tool A, default to:

- **weekly**

Why:

- aligns with the official structural model
- reduces noisy false detail
- aligns with the implementation guide's weekly logic

Optional later:

- daily toggle for exploratory use

## Horizon controls

I would not start with fully freeform dates as the primary UI.

Instead, use:

- `6M`
- `12M`
- `3Y`
- optional custom range under an "Exploratory" control

Why:

- this preserves alignment with official Tool A windows
- it reduces accidental cherry-picking
- it makes the chart easier to interpret alongside the official metrics

## Scale options

For longer windows, a log-scale option is worth considering.

Why:

- a linear indexed chart can make later compounding visually dominate earlier moves
- log scale keeps percentage changes more comparable through time

I would not force log scale by default, but I would keep it as an optional view.

## Accuracy And FX Rules

This part should be treated as non-negotiable.

## 1. Use only canonical USD-normalized stock prices

The chart must use:

- stock prices already normalized to USD upstream
- the same canonical gold USD series Tool A uses

It must **not**:

- re-run FX logic inside the chart layer
- mix local-currency stock with USD gold

## 2. Rebase only after alignment

Correct sequence:

1. normalize stock to USD
2. choose common cadence
3. align by common dates
4. determine effective common start date
5. rebase both series to 100

Do **not** rebase before date alignment.

## 3. Use adjusted equity prices

The stock series should use the adjusted USD basis already used by Tool A.

Otherwise:

- splits
- dividends
- corporate actions

will distort the visual comparison.

## 4. Display effective start and end dates explicitly

If the user chooses:

- start date = `2025-01-01`

but the first common valid weekly date is:

- `2025-01-03`

then the UI should say so.

That matters for trust.

## 5. Respect normalization status gates

If the underlying stock series is normalization-blocked or not trusted, the chart should not quietly render.

At minimum:

- show a blocked or withheld state
- explain that the chart is unavailable because the USD-normalized series is not trusted

## Should This Chart Use Delta And Gamma At All?

My answer:

- **not in the official Tool A naming**

If you want a chart-specific analytics layer, it should use different names.

### What I would allow

- relative path spread
- relative strength ratio
- relative path acceleration

### What I would not allow

- calling line-gap "`delta`"
- calling line-acceleration "`gamma`"

That would create conceptual conflict with the core tool.

## Better Version Of The Idea

If I were turning this into the best Tool A version, I would build:

## Version 1

- weekly rebased stock vs gold chart
- fixed horizons: `6M`, `12M`, `3Y`
- visible note: "Exploratory relative-performance view"
- structural metric cards beside it

## Version 2

- secondary panel with relative strength ratio
- regime shading for up-gold vs down-gold weeks
- optional drawdown comparison

## Version 3

- optional custom date range
- optional daily view
- optional log-scale toggle

That would be much cleaner than trying to immediately turn the chart itself into a new metric engine.

## Final Recommendation

This chart is worth building.

But it should be built with this framing:

### What it is

- a **rebased relative-performance chart**
- a visual tool for understanding path behavior
- an exploratory companion to official Tool A

### What it is not

- not official delta
- not official gamma
- not the score basis

### What I would change from your current proposal

1. Keep the rebased chart idea.
2. Remove the proposed delta/gamma naming from the chart layer.
3. Default to weekly cadence and official preset horizons.
4. Add a relative-strength or spread panel instead of chart-level pseudo-gamma.
5. Pair the chart with official structural Tool A metrics.
6. Enforce USD-only, normalization-safe input handling.
7. Clearly disclose that the start date changes the picture.

## Final One-Sentence Verdict

**Yes, build it, but build it as an exploratory rebased relative-performance view, not as a replacement for Tool A's official structural delta and gamma framework.**
