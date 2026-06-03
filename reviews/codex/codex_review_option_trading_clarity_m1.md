# Codex Review - Option Trading Clarity M1

Grade: NEEDS CHANGES

Scope: review-only. No source code changes made. This file reviews the current Option Trading clarity implementation visible at `http://127.0.0.1:8770/option-trading` and the associated cached-data/code path.

## Executive View

The implementation is safer than the previous version because it no longer silently presents the AEM 60d strike 50 put as a normal candidate. However, it is not yet a good user-facing option-selection tool.

The current product shape is still too mechanical: it picks one contract per horizon using a single 25-delta target after hard liquidity filters. On the current cached snapshot this leaves only 2 accepted put slots out of 88 and 1 accepted call slot out of 88. That is not enough to support Emanuel's workflow of comparing realistic put/call opportunities.

The UI also has too much explanatory text in the main flow and the detail table is too wide to read. The correct next step is not another small patch. We need a short research-and-redesign step before more coding.

## Current Data Evidence

Read-only diagnostic against the current cached options snapshot:

| Metric | Current result |
| --- | ---: |
| Option Trading overview rows | 22 |
| Display horizons | 30 / 60 / 90 / 120 |
| Core optionability horizons | 30 / 60 / 90 |
| Delta-gap gate | 0.10 |
| Options snapshot date | 2026-06-01 |
| Put slots | 88 |
| Accepted put slots | 2 |
| Rejected put slots | 20 |
| No-tradable put slots | 65 |
| No-contract put slots | 1 |
| Call slots | 88 |
| Accepted call slots | 1 |
| Rejected call slots | 23 |
| No-tradable call slots | 64 |

Accepted put horizons are only:

| Ticker | Accepted put horizons |
| --- | --- |
| AEM | 30d |
| NEM | 60d |

Accepted call horizons are only:

| Ticker | Accepted call horizons |
| --- | --- |
| NEM | 120d |

This proves the current design is behaving as coded, but the coded design is too narrow for the intended decision workflow.

## Findings

### 1. The Overview And Detail Pages Are Too Text-Heavy

`golden_vector/serve/overview_option_trading.py:22-31` renders several explanatory paragraphs before the user reaches the table. `golden_vector/serve/detail_panels.py:197-205` repeats another long caveat paragraph on the ticker detail page. The sentence Emanuel called out should be removed from the main flow. It is conceptually valid, but it belongs in a help drawer, tooltip, or docs page, not above every option table.

Better: one compact note such as `Cached options snapshot: 2026-06-01. Last prices may differ from Yahoo live.` Keep legal/model caveats behind a small `Method` or `Assumptions` disclosure.

### 2. The Candidate Table Is Not Readable

`golden_vector/serve/detail_panels.py:340-378` renders 19 columns in one table, including long `Yahoo Chain` and `Why` text. The result is visible in the screenshot: narrow wrapped columns, tall rows, badges split across multiple lines, and the useful numbers are hard to scan.

Better: replace the wide table with horizon cards or a compact table:

| Horizon | Expiry | Stock | Best liquid put/call | Fit | Spread | OI | Volume | Action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Move `Why`, Yahoo link, delta details, and diagnostics into an expanded row/card. The main view should answer "is there a plausible trade here?" in one glance.

### 3. The Current Candidate Algorithm Is Too Narrow

`golden_vector/hedge/candidate_puts.py:118-132` defines a single target-delta slot search. It then chooses the nearest expiry, filters tradability, and calls `strike_for_target_delta` before applying the delta-gap gate around `candidate_puts.py:232-285`.

That is fine as a diagnostic, but not enough for a trading candidate finder. It conflates four different ideas:

| Concept | What it means |
| --- | --- |
| Liquid contract | Market is tradable enough: tight spread, bid/ask present, OI/volume/depth |
| Model-fit contract | Delta/moneyness/horizon matches the modeled thesis |
| Popular contract | High OI/volume relative to chain |
| Scenario contract | Strike/horizon makes sense for the user's expected stock/gold move |

The current code asks only: "what is the closest surviving 25-delta contract?" That is why the output collapses to almost nothing.

### 4. The Hard Liquidity Gate Creates A False Binary

The filter is safer than accepting bad quotes, but the UI now shows mostly `No tradable contract`. That is not very informative. A contract can fail for many different reasons:

- bid or ask is zero;
- spread is too wide;
- volume is zero today;
- open interest is low;
- IV is placeholder-like or extreme;
- quote looks stale.

The UI should show the best available chain context even when no official candidate is accepted. For example: `No official candidate, but the most liquid 60d put is strike X with spread Y%, OI Z, volume W`. This would help Emanuel understand whether the ticker truly has no usable options or whether the current thresholds are just too strict.

### 5. One Candidate Per Horizon Is The Wrong Shape

Emanuel asked to see 30/60/90/120, but that does not mean exactly one contract per horizon. A realistic view should probably show several contract types per horizon:

| Bucket | Purpose |
| --- | --- |
| ATM / near-ATM | Most direct directional exposure; usually more liquid |
| 30-40 delta | Directional but less expensive than ATM |
| 15-25 delta | Cheaper tail/hedge exposure |
| Highest-liquidity contract | What the market actually trades most |

Then the UI can label one as "model preferred" if it exists, without hiding the liquidity landscape.

### 6. 30d Should Not Be A Default "Good" Horizon Without More Research

The current display includes 30d because the user asked for it, and that is fine. But 30d long options can decay quickly and bid/ask quality can be worse near expiry. We should not make 30d look equivalent to 60/90/120. The default candidate for a beginner user should probably bias toward 60-120 DTE unless there is a short-term event thesis.

Possible UI language:

| Horizon | Label |
| --- | --- |
| 30d | Tactical / high time-decay |
| 60d | Near-term directional |
| 90d | Standard scenario horizon |
| 120d | Slower thesis / lower time pressure |

This needs research before locking the labels.

### 7. Calls And Puts Should Not Use Identical Candidate Logic

The same 25-delta target is currently applied symmetrically to puts and calls through `golden_vector/serve/option_trading_data.py:431-449`. That may be too simplistic.

For downside protection, a 15-30 delta put can make sense. For speculative upside calls, 25-delta calls may be lottery-like and less beginner-friendly than 35-50 delta calls. The user specifically wants to understand call/put opportunities; we need different candidate buckets by intent, not one shared target.

### 8. Current Overview Status Is Misleading Because It Hides The Liquidity Problem

The overview screenshot shows only NEM when filters are set to usable candidates. The page has 22 optionable tickers, but almost all are `thin`. That is not obvious enough. The overview should show counts at the top:

- `22 optionable tickers`
- `2 accepted put contracts`
- `1 accepted call contract`
- `Most failures: no bid/ask or too-wide spread`

This would immediately explain why the table looks sparse.

### 9. Yahoo Last Price vs Executable Quote Is Still A Product Risk

The code now displays `last_price` separately from `mid`, which is good. But the product still needs clearer language:

- Yahoo `Last` is the last traded price, not necessarily executable now.
- Golden Vector `Mid` is `(bid + ask) / 2`, and only meaningful when bid/ask are credible.
- If bid/ask are zero, the last price may be stale.

This matters because Emanuel compared the site to Yahoo and saw different prices. The current cache note is helpful, but the table should make stale or zero-bid/ask quotes visually obvious.

### 10. The Refresh Button Is Still Missing

The user explicitly expects a button that refreshes all data the model uses. It was correctly split out of M1, but the current UI now makes the absence more obvious because cached Yahoo data is central to the decision. M2 should not be delayed much longer.

This still needs a background job/status-page design. Do not make it a synchronous blocking button.

## Research Notes

This is preliminary qualitative research, not enough to finalize candidate rules.

Useful sources found:

1. Cao, Wei, and Zheng, "Option Market Liquidity: Commonality and Other Characteristics" (Journal of Financial Markets, 2010). The paper studies equity option liquidity across moneyness and maturity, and supports treating liquidity as multidimensional rather than only volume/open interest. Source: https://www-2.rotman.utoronto.ca/~wei/research/JBF_2010.pdf

2. Bollen and Whaley, "Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?" (Journal of Finance, 2004). Relevant because demand pressure, especially for options at different strikes, affects implied volatility and therefore price. Source: https://ssrn.com/abstract=385082

3. Garleanu, Pedersen, and Poteshman, "Demand-Based Option Pricing" (Review of Financial Studies, 2009). Relevant because option prices can reflect investor demand and intermediary constraints, not just Black-Scholes fair value. Source: https://academic.oup.com/rfs/article/22/10/4259/1580966

4. Pan and Poteshman, "The Information in Option Volume for Future Stock Prices" (Review of Financial Studies, 2006). Relevant because option volume can be informative, especially when separated by option type and moneyness. Source: https://academic.oup.com/rfs/article-abstract/19/3/871/1575925

5. Bogousslavsky and Muravyev, "Who Trades Options and Which Options Do They Trade?" (2024 working paper). Relevant because retail option flow often concentrates in short-term purchases and lottery-like contracts, which should not automatically become a recommended default. Source: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4292074

6. Schwab option chain guidance. Industry source, not academic, but useful for user-facing explanations of volume, open interest, bid, ask, and implied volatility fields. Source: https://www.schwab.com/learn/story/how-to-read-options-chain

7. Cboe DataShop option quote snapshots. Useful for thinking about better option data quality; Cboe offers quote snapshots near 15:45 ET, which may be more representative than stale Yahoo last prices for liquidity analysis. Source: https://datashop.cboe.com/option-quotes-end-of-day-with-calcs

## Proposed Direction Before More Coding

### A. Reframe The Feature

Rename mentally from `Option Trading candidate picker` to:

`Options Liquidity & Scenario Lab`

The tool should first show whether a ticker has liquid option markets, then help compare plausible contracts. It should not pretend a single formula can pick "the" option.

### B. Add A Chain Scanner Layer

Instead of one selected contract per horizon, compute a scan table per ticker/side/expiry:

| Field | Purpose |
| --- | --- |
| expiry / DTE | horizon |
| strike / moneyness / delta | economic exposure |
| bid / ask / mid / last | quote context |
| relative spread | primary liquidity metric |
| open interest | depth / market participation |
| volume | today's activity |
| premium % of stock | cost |
| IV | volatility price |
| liquidity score | compact ranking |
| reason flags | why accepted/rejected |

Then derive candidate buckets from that scan instead of throwing most contracts away before the UI sees them.

### C. Show Multiple Candidate Buckets

For each side/horizon, consider showing:

| Bucket | Possible rule |
| --- | --- |
| Most liquid | highest liquidity score among sensible strikes |
| Near ATM | strike closest to stock price with acceptable liquidity |
| Directional | delta roughly 0.35-0.50 for calls, -0.35 to -0.50 for puts |
| Hedge/tail | delta roughly 0.15-0.30 for puts |
| Model fit | closest to modeled stock scenario if liquidity is acceptable |

The exact delta ranges should be researched and validated before implementation.

### D. Make No-Trade A First-Class Outcome

For many gold miners, the honest output may be:

`Do not trade single-name options here; use shares or a more liquid proxy like GDX/GDXJ.`

This should be shown clearly, not buried in `No tradable contract`.

### E. Redesign The UI

Recommended UI shape:

1. Header row:
   - ticker
   - stock price
   - snapshot date
   - refresh button/status
   - source

2. Compact liquidity summary:
   - puts: accepted / rejected / no-trade counts
   - calls: accepted / rejected / no-trade counts
   - best liquid expiry
   - overall liquidity label

3. Horizon cards for 30/60/90/120:
   - show 1-3 compact contract rows, not 19 columns
   - keep `Why` as expandable detail
   - keep Yahoo link as one small action button

4. Scenario calculator:
   - appears after user chooses a specific contract
   - should not dominate the initial page

5. Method/caveat text:
   - move to collapsed `Method` section
   - remove the long paragraph from the top of every page

## Claude Deep Research Brief

Claude should do a dedicated research pass before the next implementation plan.

Questions for Claude:

1. What strike ranges are most commonly used for directional long calls and protective/speculative puts in single-name equities?

2. What horizons are most practical for a beginner user buying options: 30, 45, 60, 90, 120, 180 DTE? Which should be default and which should be "tactical only"?

3. How should liquidity be scored for single-name options?
   - relative spread
   - dollar spread
   - OI
   - volume
   - bid/ask nonzero
   - premium size
   - quote staleness
   - chain depth around spot

4. Should calls and puts use different default delta/moneyness buckets?

5. What should the tool do when single-name options are too thin?
   - show no-trade?
   - suggest proxy hedge/speculation through GDX/GDXJ?
   - show shares instead?

6. Is Yahoo/yfinance option data good enough for this workflow, or do we need a better quote source for bid/ask and open interest?

7. What is the right UI language for `Last`, `Bid`, `Ask`, `Mid`, and `IV` so a beginner does not mistake stale last trade for a current executable price?

Expected Claude output:

- short literature summary with links;
- practical strike/horizon recommendations;
- proposed liquidity scoring formula;
- candidate bucket definitions;
- UI wireframe recommendation;
- explicit "do not trade / use proxy" handling;
- implementation plan that avoids another wide unreadable table.

## Recommended Grade For Current M1

NEEDS CHANGES before shipping as a user-facing option selection tool.

It is acceptable as an internal diagnostic prototype. It is not yet acceptable as the final Option Trading UI.

