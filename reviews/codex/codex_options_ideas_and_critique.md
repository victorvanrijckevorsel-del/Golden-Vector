# Options Brainstorming: User Value First

## Blunt Verdict

The current options plan is too much "capture the options market" and not enough "help Emanuel make a hedge decision today." Fetching full chains, computing ATM IV, 25-delta skew, term slope, liquidity, IV percentile, IV/RV, and earnings dates is technically reasonable. But as a user product, it still leaves Emanuel asking: which position hurts me, which hedge is affordable, which contract should I look at, and what should I do with names that have no listed options?

Golden Vector already has the first half of the answer. Tool A already publishes structural down/up beta, confidence, window status, weeks, and volatility diagnostics (`golden_vector/model/pipeline.py:61`, `golden_vector/model/pipeline.py:487`). Tool B already publishes margin, FCF yield, leverage, and valuation outputs (`golden_vector/screening/layer1.py:61`, `golden_vector/screening/pipeline.py:335`). Options should not become a third pile of descriptive data. Options should answer the missing second half: "What does protection cost, is it liquid enough, and is it cheap or expensive relative to the risk I am trying to hedge?"

So I would reframe the milestone from "Options ingestion" to "Hedge Readiness." Ingestion is necessary plumbing, but the user-facing output should be a small set of decision cards:

- direct optionable hedge candidates
- cheapest liquid hedge candidates
- expensive/crowded hedge candidates to avoid
- no-options names needing proxy hedge, trim, or no-add treatment
- contract candidates for 30/60/90 day protection

If M1 ships no UI and no decision-useful output, it may be correct engineering but weak product work.

## The Real User Journey

Emanuel's actual workflow is not "inspect IV features." It is closer to this:

1. He opens Golden Vector because gold is weak or he is worried about a drawdown.
2. He wants to know his current exposure: which owned names would likely hurt most if gold drops 5%, 10%, or 20%.
3. He wants to know which of those names can be hedged directly with options.
4. For optionable names, he wants a small contract shortlist: expiration, strike, bid/ask, open interest, premium cost, and expected protection.
5. For non-optionable names, he wants a proxy: GDX/GDXJ puts, NEM/AEM/GOLD puts, trim/no-add, or no practical hedge.
6. He wants to compare hedge cost against expected downside. A put can be liquid but too expensive.
7. He wants to act or defer: buy protection, trim, avoid adding, or do nothing.

That journey requires options data, but it also requires portfolio context, candidate-contract selection, and a cost/protection comparison. Current IV/skew features only partially support this.

## Audit Of Planned Features

| Planned feature | User decision it informs | What turns it into action | Verdict |
|---|---|---|---|
| ATM IV at 30/60/90 days | Is near-term protection broadly cheap or expensive? Which tenor is pricing more risk? | Show premium as percent of stock value, implied move, and comparison to realized vol or own history. | Keep, but do not show as a raw IV headline. Convert to cost and implied move. |
| 25-delta put IV + call IV | How expensive is downside insurance versus upside optionality? | Use the 25-delta put as a candidate hedge row with strike, expiry, premium, spread, OI, volume, and breakeven. | Keep 25-delta put. Call IV is mostly useful only to compute skew. |
| Put-call IV skew | Is downside insurance crowded or unusually expensive? | Compare current skew to cross-section and eventually history; flag "puts rich" or "puts cheap." | Keep, but as a crowding/cost context, not a standalone rank. |
| Term-structure slope | Is short-term risk priced richer than medium-term risk? | Show whether 30d insurance is unusually expensive versus 90d; useful for choosing tenor. | Keep as secondary. It is not enough to justify a hedge alone. |
| Liquidity score as OI + volume | Can Emanuel realistically trade this contract? | Use bid/ask spread percent, OI and volume at the candidate strike/expiry, stale quote checks, and minimum premium/market filters. | Replace. OI + volume is too crude. Liquidity must be contract-specific. |
| IV percentile over 52 weeks | Is insurance cheap relative to its own history? | Needs enough history. Until then, show sample size and use IV/RV plus cross-sectional percentile. | Defer as a mature metric. It has weak day-1 value. |
| IV vs realized vol ratio | Is implied volatility expensive versus the stock's actual recent movement? | Match tenors: 30d IV vs 30d realized, 60d vs 60d realized. Combine with down-risk from Tool A. | Keep. This is one of the best early value signals. |
| Days to next earnings | Is there a known event inside the option window? | Only useful if it changes contract choice or warns that IV is event-inflated. | Demote. Useful context, not worth making a fragile dependency early. |

The key pattern: nearly every planned feature becomes useful only after it is tied to a candidate contract and a decision threshold. "NEM 60d 25-delta put IV is 38%" is trivia. "NEM is top-tercile downside risk, the 60d 25-delta put costs 2.1% of notional, spread is 4%, OI is strong, and IV/RV is below 1.1" is a hedge candidate.

## What To Cut Or Demote

Cut "M1 has no UI" unless M1 is purely a one-day internal checkpoint. Even a minimal markdown/CLI report would force the data design to answer user questions. A backend-only options milestone can easily pass tests while creating no value.

Demote 52-week IV percentile. It is directionally right but day-1 weak. It will be useful after enough local history accumulates, but a metric that needs a year to mature should not be part of the first value promise. Replace early with IV/RV, cross-sectional IV percentile among optionable gold names, and raw option premium as percent of notional.

Demote days-to-earnings. It sounds professional, but for a gold-miner hedge workflow, the main event may be gold itself, CPI/Fed/jobs data, or sector risk. Earnings dates are useful if options are being chosen around a company event, but they should not complicate M1 unless the source is reliable and cheap.

Cut a single generic liquidity score. Hedgers care whether the specific contract they might buy is tradable. A ticker can have large total open interest while the 60-day 25-delta put is useless. Liquidity should be measured at candidate strikes and expirations.

Cut "full chain derived everything" as the first analytical goal. Storing raw full chains is fine for auditability, but the derived layer should be smaller and more decision-shaped.

## What To Add

Add a hedge contract shortlist. For each optionable ticker, produce maybe three rows: 30d, 60d, and 90d candidate puts. Each row should include expiry, strike, moneyness, approximate delta, bid, ask, mid, spread percent, volume, open interest, premium percent of stock notional, breakeven, and max useful payout under a simple stock-down scenario. This is the bridge from options data to action.

Add implied move from ATM straddles. This is more decision-useful than raw ATM IV because it translates the options market into "the market is pricing about X% movement by this expiry." The user can compare that to Tool A's gold-shock downside estimate and Tool B's fundamental stress view. If options imply 6% and Tool A/Tool B stress says the stock could plausibly fall 15%, protection may be interesting. If options imply 18%, insurance may already be too expensive.

Add expected downside versus premium. Use Tool A's down beta to estimate stock impact under gold down 5%, 10%, and 20%. Then compare that downside to the premium for candidate puts. This can create a plain-English output: "insurance cost is 2.0%; modeled 10% gold shock downside is 12%; protection looks cheap/normal/expensive." It is not a recommendation, but it is a useful screen.

Add put/call open interest and volume ratios, ideally split by OTM options. This answers whether the market is already crowded in downside protection. Total put/call ratio is rough, but it is familiar and useful. OTM put/call ratio is better for hedge demand.

Add optionability coverage as a first-class output. The probe says only 24 of 64 tickers have listed options. That is not a footnote; it is a product constraint. The UI should show "directly hedgeable," "thin options," and "no direct options." For the 40 no-option names, the tool must not dead-end.

Add proxy hedge mapping for no-option names. This could be simple at first: map each non-optionable stock to GDX, GDXJ, or the most behaviorally similar liquid optionable miner using Tool A return history/down beta. The output should show basis-risk warnings. A proxy hedge is not perfect, but "no listed options" is still an actionable answer if the next row says "closest liquid proxy: GDX or AEM, confidence low/medium/high."

Add a "hedge watchlist" score, but keep it interpretable. The ingredients should be:

- high downside exposure from Tool A
- hedgeable and liquid enough
- options not too expensive versus realized vol or implied/expected move
- not already extremely crowded by put/call positioning
- owned or watchlisted by Emanuel

This is a different product from Tool C. Tool C can rank downside risk. Hedge Watchlist ranks hedge usefulness.

## The Missing User Data

The biggest missing input is Emanuel's actual book. Without holdings, the tool cannot answer "how exposed am I?" or "how much protection do I need?" It can only rank tickers in the abstract.

Golden Vector does not need to become a full portfolio tracker. A portfolio-lite input is enough:

- ticker
- owned yes/no
- dollar exposure or shares
- optional target hedge percent
- optional max premium budget
- optional notes

This should be local-first and simple, like the Tool B manual-data store. Then the options layer can say: "You own $50k of AEM. A 60d 25-delta put hedge for roughly 50% notional costs about $X before commissions." Without this, the user must do the most important calculation manually outside the tool.

There should also be a watchlist mode for names Emanuel does not own but is considering adding. For those, the output is not "buy puts"; it is "avoid adding until hedge cost/risk improves" or "risk is elevated but hedge is cheap."

## Workflow For The 40 Names With No Options

A "not hedgeable" flag is necessary but not enough. The product should split non-optionable names into three action paths:

1. Trim/no-add candidate: high downside risk, no direct hedge, weak fundamentals.
2. Proxy hedge candidate: high downside risk, no direct hedge, but strong correlation/downside similarity to GDX, GDXJ, or a liquid miner.
3. Monitor only: no direct hedge, but downside evidence or exposure is not strong enough to act.

This matters because most of the universe is foreign-listed and unoptionable. If the options work only serves the 24 US-listed names, it misses a major part of the portfolio problem.

## Better Milestone Shape

I would make M1 smaller but more useful:

1. Fetch raw option chains for optionable tickers and store them with provenance.
2. Identify direct optionability and liquidity tiers.
3. Build a candidate put grid for 30/60/90 day expiries.
4. Compute ATM implied move, premium percent, spread percent, OI, volume, and IV/RV.
5. Produce a local report/table that ranks "hedge readiness" for optionable names.
6. Explicitly list non-optionable names with proxy/trim/no-add placeholders.

That would deliver user value before building the full analytical warehouse. Then M2 can add richer history, skew history, put/call ratios, proxy-hedge math, and UI integration.

This also fits the existing architecture. `update-data` is already the Yahoo-backed refresh command, while Tool A and Tool B run from local snapshots (`docs/golden_vector_architecture_map.md:63`). The output directories already retain latest and historical Tool A/B outputs (`docs/golden_vector_architecture_map.md:88`). Options should follow that local-first pattern, but the first artifact should be useful, not merely complete.

## Reframing The Product

I would stop thinking of this as "options features for Tool C." I would frame it as three surfaces:

1. Downside Risk: which names are most exposed if gold falls? This is mostly Tool A plus Tool B stress.
2. Hedge Readiness: which exposed names have liquid, reasonably priced puts?
3. Hedge Construction: if Emanuel owns $X, what contracts or proxies should he inspect?

That framing keeps the logic honest. A stock can be high downside risk but impossible to hedge directly. A stock can be hedgeable but the options can be too expensive. A stock can have cheap puts but low downside exposure, making it irrelevant. User value comes from the intersection, not from options features alone.

## Open Questions For Emanuel

1. Is the main use case hedging existing positions, deciding what not to buy, or finding shorts?
2. Is Emanuel willing to maintain a simple local holdings file with dollar exposure per ticker?
3. What hedge horizon matters most: 30 days, 60 days, 90 days, or through specific events?
4. Does he prefer direct single-name hedges even when liquidity is mediocre, or cleaner ETF hedges with more basis risk?
5. What is an acceptable hedge budget: 1%, 2%, 5% of protected notional?
6. Should the tool ever suggest a contract, or only produce a shortlist for manual inspection?
7. Are GDX and GDXJ acceptable proxy hedges for foreign-listed/non-optionable names?
8. Should "too expensive to hedge" become a reason to trim or avoid adding?

## Final Recommendation

Do not build options plumbing as an isolated backend milestone unless it is extremely short. Build the smallest chain capture that supports a decision-useful Hedge Readiness report.

The first user-value target should be:

"For the names I own or watch, show me which are vulnerable, which can be hedged directly, what the likely hedge costs, whether the option market is cheap or expensive, and what I should do for names with no options."

Everything else is secondary. ATM IV, skew, term slope, and IV percentile are useful only if they serve that workflow. If they do not produce a better hedge, trim, avoid, or wait decision, they are plumbing for plumbing's sake.
