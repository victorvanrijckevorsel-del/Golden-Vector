# Golden Vector — Understanding the Model (a field guide)

**For:** Emanuel — a from-first-principles explanation of what this tool does, the financial ideas behind every piece, why we built it the way we did, and what the academic research says about whether each choice is sound.
**Date:** 2026-06-03
**How to read this:** top to bottom is a story. Each section first explains the *idea* in plain English, then *how we measure it*, then *what the research says*, then *what to trust and what to be careful about*. There's a glossary at the end — skim it first if a term is new.

---

## Part 0 — The one big idea

Everything in this tool rests on a single insight:

> **A gold-mining company's stock is a *leveraged bet* on the price of gold.**

Why "leveraged"? Imagine a miner that digs gold out of the ground for $1,500 an ounce (its cost) and sells it at $2,000 (the market price). Its **profit margin** is $500/oz. Now gold rises 10%, to $2,200. The miner's *cost didn't change* — it's still $1,500 — so its margin jumps from $500 to $700. That's a **40% jump in profit from a 10% rise in gold.** The company's costs are mostly *fixed*, so every dollar gold moves flows straight to the bottom line, magnified. That magnification is called **operating leverage**, and it's why miner *stocks* swing much harder than gold itself.

The flip side is the danger: if gold *falls* 10% to $1,800, the margin drops from $500 to $300 — a 40% *collapse* in profit. And if gold fell to near $1,500, the company would make almost nothing. This asymmetry — big upside, but a cliff on the downside — is the heart of what our tool measures.

**The academic anchor.** This isn't folklore. The classic study, **Tufano (1998, *Journal of Finance*)**, measured it directly: *"The average mining stock moves 2 percent for each 1 percent change in gold prices."* So the typical miner has roughly **twice** the sensitivity of gold itself — and Tufano stressed that this sensitivity **"varies considerably over time and across firms."** A more recent study (**Qin et al. 2023**) found miners behave *more like gold than like ordinary stocks*, especially in their extreme moves.

So our whole tool is built to answer, for each miner: **how leveraged is it to gold, in which direction, and how fragile is the company if gold falls?** — and then, **what options trades let you bet on that?**

---

## Part 1 — "Gold beta": how much a miner moves with gold

### The idea
**Beta** is just a number that answers: *"When gold moves 1%, how much does this stock move, on average?"* A beta of 2 means the stock moves ~2% per 1% of gold. A beta of 0.5 means it barely reacts. A beta below 0 would mean it moves *opposite* to gold (rare for a miner).

### How we measure it
We take years of **weekly** price history for the stock and for gold, convert them to weekly returns (percentage changes), and run a **regression** — a line of best fit — of the stock's returns against gold's returns. The *slope* of that line is the beta. Steeper line = more sensitive stock.

We use **weekly** (not daily) data on purpose: daily moves are noisy and full of one-off jitter; weekly returns smooth that out and capture the real structural relationship. (This is Tool A's job in our system; the betas live in fields like `down_beta_core` and `up_beta_core`.)

### What the research says
Estimating a firm-specific beta by regressing returns on the commodity is exactly the standard, well-founded approach. And because Tufano showed beta **varies by firm and over time**, our choice to compute a *fresh, per-miner* beta — rather than assume one fixed "2×" for everyone — is the right one.

### What to trust / be careful about
- **Trust:** beta is a solid, simple, well-understood measure of sensitivity.
- **Careful:** beta is an *average over the past*. It can drift. A miner that hedged its gold, took on debt, or changed its mines can have a different beta next year. That's why we also track *confidence* (how well the line actually fits — the "R²") and only rank names where the data is good enough.

---

## Part 2 — Up-beta vs down-beta: miners fall harder than they rise

### The idea
Here's a subtlety that matters enormously for someone betting on the *downside*: a miner's sensitivity to gold **isn't the same up and down.** Because of that operating-leverage cliff (Part 0) and because fear moves markets faster than greed, many miners **fall harder when gold drops than they rise when gold gains.** A stock might have an up-beta of 1.5 but a down-beta of 2.2.

So we split beta into two:
- **Up-beta** — sensitivity measured only over the weeks gold *rose*.
- **Down-beta** — sensitivity measured only over the weeks gold *fell*.

For a tool whose main job is "what happens to this stock if gold falls," **down-beta is the star metric.**

### How we measure it (and an honest label)
We take all the weeks where **gold fell**, and run the same best-fit-line regression on just those weeks; the slope is the **down-beta**. Same for up-weeks → up-beta.

There's an honesty point here worth knowing. In academic finance there are a few competing precise definitions of "downside beta" (Estrada's "D-CAPM," Ang-Chen-Xing's version, etc.), each with slightly different math. **What we compute is a "split-sample conditional beta"** — literally "the beta during weeks gold fell" — which is intuitive and defensible, but it is *not identical* to the textbook D-CAPM formula. So in the tool we should call it what it is (a conditional/down-week beta), not borrow an academic label that implies a different calculation. (We've noted this; it's a documentation precision issue, not a math error.)

### What the research says — and a crucial caution
The theory behind using downside risk is solid (**Bawa & Lindenberg 1977**, *JFE*, built a downside version of the standard asset-pricing model; the idea that you should care about *downside* variation more than total wiggle is well-grounded when returns are lopsided, which miners' are).

**But here is the single most important caution in this whole document:** a serious modern literature (**Atilgan, Demirtas & Gunaydin 2020**; **Levi, Welch & Karolyi 2020**, *Review of Financial Studies*) found that **down-beta does *not* reliably predict higher future returns.** In plain English: a high-down-beta stock has historically *fallen harder when gold fell* — but that does **not** mean it will *earn you more* going forward. One paper bluntly concluded down-betas are useful for "neither hedging nor risk-pricing."

### What to trust / be careful about
- **Trust:** down-beta as a **description of past behaviour** — "this miner has historically been violent on the downside." That's genuinely useful for picking which stock to buy a *put* on.
- **Careful:** do **not** read the downside ranking as a *forecast of returns*. The tool ranks **risk/sensitivity, not reward.** We deliberately show **plain beta next to down-beta** and label the ranking "descriptive, not a prediction," precisely because the research says the predictive claim doesn't hold up.

---

## Part 3 — Ranking miners by downside risk (this is "Tool C")

### The idea
Once we can measure how each miner behaves when gold falls, we can **rank the whole universe** from "most exposed to a gold drop" to "least." That ranking is the entry point: if you think gold is going to fall and you want to buy puts, you start with the names that fall hardest.

But down-beta alone is a thin story. So Tool C combines a few **downside signals**:
- **Down-beta** — how much it falls per 1% of gold drop.
- **Downside volatility** — how violent its drawdowns have been (not just direction, but severity).
- **Relative weakness** — in the weeks gold fell, *how often did this stock underperform gold itself* (or the GDX miner ETF)? A stock that *reliably* lags in bad times is structurally weak.
- **Downside hit-rate** — how often it dropped hard (say ≥10%) during gold-down weeks.

Each of these gets turned into a **percentile** (where does this miner rank, 0–100, versus its peers), and the headline rank is an average of those percentiles.

### What the research says
Using *multiple* downside descriptors rather than one number is sound, and percentile ranks are more honest than a single fabricated "score" (they don't pretend to a precision the data doesn't have). The relative-weakness and hit-rate signals are statistically *sturdier* than the tail metrics in Part 4, because they're built from many weeks of data.

### What to trust / be careful about
- **Trust:** the ranking as a **shortlist generator** — "these are the names most worth a closer look for a downside bet."
- **Careful:** same as Part 2 — it ranks *risk*, not *reward*. And it's only as good as the betas underneath it, which is why we gate on data quality.

---

## Part 4 — Tail risk and the "thin data" problem (why we flag low-confidence)

### The idea
The scariest question is: *"In the very worst gold weeks, what did this stock do?"* That's **tail risk** — the behaviour in the extreme left edge of the distribution. We measure it by averaging a stock's return over, say, the **worst 10–15 weeks for gold** in the last few years.

### The honest problem
Here's the catch, and it's the thing you specifically asked us to handle honestly: **a few years of history only contains ~15 "worst gold weeks."** Averaging just 15 numbers gives a **noisy, unreliable** estimate. Worse — and this is the part most people miss — the statistics literature shows these small-sample tail averages are **biased toward *understating* risk**: they tend to make things look *safer* than they really are, exactly when you most need the truth.

### What the research says
This is rock-solid, multi-source territory:
- **Yamai & Yoshiba (2002, BIS):** tail-loss measures "need a larger sample than [ordinary risk measures] for the same level of accuracy."
- **Pitera & Schmidt (2020):** small-sample tail estimators are biased toward **underestimating** risk.
- **Barendse et al. (2023, *J. Financial Econometrics*):** ignoring this estimation error wildly inflates false conclusions.
- Plus: normal-distribution assumptions *understate* extreme moves because real returns are **fat-tailed** (more extremes than a bell curve predicts).

### What we do (and why it's right)
We **compute** the worst-week tail numbers and **show** them — but we **flag them low-confidence** and we **keep them out of the headline ranking** so a 15-sample fluke can't move the ranking. A stock with too little history gets a "thin history" tag instead of a falsely precise number. The research validates this exactly. (A fancier method called "peaks-over-threshold" exists if we ever want a sturdier tail estimate — noted for the future, not needed now.)

### What to trust / be careful about
- **Trust:** the flagged tail numbers as a *rough hint*, clearly marked uncertain.
- **Careful:** never treat a thin-data tail number as precise — and we don't.

---

## Part 5 — Options 101: puts, calls, and the price of a bet

### The idea (in case any of this is new)
An **option** is a contract that lets you bet on a stock's direction with a small, *fixed* amount of money at risk:
- A **call** is the right to *buy* the stock at a set "strike" price. You buy calls if you think the stock will **go up**. Worst case you lose the **premium** (what you paid); upside is large.
- A **put** is the right to *sell* the stock at a set strike. You buy puts if you think the stock will **go down**. Again, worst case is the premium; the payoff grows as the stock falls.

Because a miner is a leveraged bet on gold (Part 0), **a put on a miner is a leveraged bet that gold falls**, and **a call on a miner is a leveraged bet that gold rises.** That's the core of the Option Trading part of our tool.

### The price of an option, and "implied volatility"
How do you know if an option is cheap or expensive? The famous **Black-Scholes** formula prices an option from a few inputs: the stock price, the strike, the time left, interest rates, and — the big one — **volatility** (how much the stock is expected to jump around). More expected movement = pricier option (more chance it pays off).

Turn that around: given the *market price* of an option, you can back out the volatility the market is assuming. That's the **implied volatility (IV)** — the market's bet on future turbulence, baked into the option's price.

### The "smile" / "skew" — and why our approach is correct
In a perfect Black-Scholes world, every option on a stock would imply the *same* volatility. In reality they don't: options at different strikes imply *different* IVs — a pattern called the **volatility skew** or **smile**. For stocks, downside puts usually imply *higher* IV than upside calls — the market charges more for crash protection (that's the **skew**).

The natural worry: do we need a complicated "volatility surface" model to handle this? **The research says no — and validates exactly what we do.** The landmark study, **Dumas, Fleming & Whaley (1998, *Journal of Finance*)**, tested sophisticated surface models against the simple approach of *just using each option's own market-quoted IV* — and found the simple approach **won out-of-sample.** Since we price each contract with **its own market IV**, we automatically absorb the skew without overcomplicating anything. (**Rubinstein 1994** confirms the skew is real but shows fancier models don't predict better.)

### What to trust / be careful about
- **Trust:** per-contract IV pricing — it's the endorsed, pragmatic method.
- **Careful:** see Part 6 (the constant-IV-in-scenarios limitation) and Part 7 (options are expensive on average).

---

## Part 6 — Using options as leveraged gold bets (our scenario engine)

### The idea
This is where Parts 1–5 come together. For a chosen miner and a chosen option, we ask: **"If gold moves −20%, −10%, 0%, +10%, +20%, what happens to this option's value and my profit/loss?"**

The chain of logic:
1. Pick a gold move, say **−10%**.
2. Use the miner's **down-beta** to translate that into a stock move: if down-beta is 2, the stock falls ~20%.
3. Feed that new stock price into **Black-Scholes** (with the option's own IV) to value the option.
4. Compare to what you paid → your **profit or loss**.

We do this for **puts** (using down-beta, with gold-*down* scenarios) and **calls** (using up-beta, with gold-*up* scenarios). We also compute the **breakeven** — how far gold must move before the trade just breaks even.

### Two honest limitations (both research-confirmed)
**(a) The straight-line assumption breaks at extremes.** Step 2 uses a simple straight-line rule (stock move = beta × gold move). That's fine for small moves, but for a **−20%** shock it's only approximate: miners are *convex* (their behaviour curves, because of that operating-leverage cliff and the "embedded real option" in their reserves — **Brennan & Schwartz 1985**; **Shahzad et al. 2021**). Real downside can be **worse** than the straight line implies. So the −15%/−20% rows should be read as **approximate** — and that nonlinear downside is exactly what Tool D (Part 9) is built to capture.

**(b) We hold volatility constant across the scenarios.** When we move the stock to its −20% price, we keep its IV the same. In a real crash, **fear spikes and IV jumps**, which would make a put worth *more* than our model shows. So our scenario tool tends to **understate** how much a put pays in a genuine crash. We label this "constant-IV" limitation, and the research (fat tails, skew) confirms it's the right caveat to flag.

Also worth a labeling fix we identified: the scenario table's "value" columns are **model-computed Black-Scholes values, not live market quotes** — so they should be labeled "modeled value," not "quote."

---

## Part 7 — The uncomfortable truth: options are expensive on average

### The idea
This is the most important honesty point for anyone *buying* options speculatively. On average, **options cost a bit more than they "should"** based on how much stocks actually end up moving. The implied volatility baked into option prices tends to run **higher** than the volatility that actually shows up. The gap is called the **variance risk premium**, and it exists because option *sellers* demand to be paid for taking on crash risk.

### What the research says
- **Carr & Wu (2009, *RFS*):** the variance risk premium is **strongly negative** — buyers of volatility (i.e. option buyers) earn negative average returns.
- **Coval & Shumway (2001, *J. Finance*):** *selling* a market straddle earned ~3% **per week** — meaning the *buyer* lost roughly that. Long options are, on average, a losing proposition.
- **The nuance that matters for us:** this effect is **strong for index options but much milder for individual stocks** (Carr & Wu). Our universe is *single-name miners*, so the "too expensive" penalty is **smaller** than the dramatic index numbers — but it's still real.

### What this means for the tool (and you)
Buying puts or calls is a **slightly negative-expectancy bet on average** — you're paying a premium for the chance of a payoff. That's **fine when you have a real directional view** (e.g., "I think gold is about to fall"), but it's **not** a money-printing machine to run blindly. The tool should say this plainly: *"You can be right on direction and still lose if the move is too small or too slow."* We're adding that disclosure.

---

## Part 8 — Predictive signals: what actually works (and what doesn't)

You asked whether there are *predictive* metrics worth adding. The research gives a clear, honest answer.

**Worth adding (and we already compute the raw data):**
- **Volatility skew / "smirk"** — *the* strongest one. **Xing, Zhang & Zhao (2010, *JFQA*)** found that stocks whose options show the steepest downside skew **underperformed by ~10.9%/year** — because informed traders quietly buy downside puts *before* bad news. We already compute `iv_skew` (put-IV minus call-IV); surfacing it as a **crash-risk flag** is genuinely useful. *Caveat:* it's an in-sample finding that may weaken over time — show it as a flag, validate on our own data, don't treat it as gospel.
- **Implied-vs-realized vol** (`iv_rv_ratio`) — tells you when options look **expensive vs how much the stock actually moves.** Useful context (ties to Part 7), and a weak short-horizon return signal (**Bollerslev-Tauchen-Zhou 2009**). We already compute it; surface it.

**Don't oversell:**
- **Put-call ratio** — the *strong* predictive version (**Pan & Poteshman 2006**) needs **proprietary** "who-initiated-the-trade" data we don't have. The public ratio we can compute is a **weak** signal. Keep it as context only, don't dress it up.

**The honest meta-point:** most published market-prediction signals are *in-sample* and **fade after publication.** We should add the skew and IV/RV signals as **flags with caveats**, not as triggers that make decisions for you.

---

## Part 9 — Corporate fragility: which miners *break* if gold falls (this is "Tool D")

### The idea
Parts 1–8 are about *stock price* behaviour. Tool D asks a different, deeper question: **which companies are financially fragile** — i.e., which ones get into real trouble (not just a lower stock price) if gold falls?

The key number is **AISC — "All-In Sustaining Cost"** — the all-in cost to produce an ounce of gold (mining, processing, sustaining capital, overhead). It's the miner's **break-even gold price.** A miner with AISC of $1,200 has a fat cushion at $2,000 gold; one with AISC of $1,850 is living on the edge.

Tool D computes, for each miner:
- **Margin per ounce** = gold price − AISC, at today's gold and at gold −10% / −20%.
- **Estimated profit (EBITDA)** at each of those gold levels — and how fast it collapses (the operating-leverage cliff from Part 0, made concrete).
- **Headroom to break-even** — how far gold can fall before this company makes nothing.
- **Leverage under stress** — debt compared to that *shrunken* profit (a company can look fine today and be drowning in debt after a 20% gold drop).

A miner that is **both** high-down-beta (falls hard — Tool C) **and** financially fragile (might break — Tool D) is the textbook target for a downside bet: it falls hard *and* there's a real chance of a deeper problem.

### What the research says — and an honest gap
The *logic* is impeccable and is the concrete version of operating leverage (Part 0). The **theoretical backbone** — that a resource company's equity is essentially a **call option on the commodity**, with reserves as options and costs creating convexity — is **Brennan & Schwartz (1985, *Journal of Business*)**.

**The honest gap:** the *precise numbers* — exactly how much EBITDA collapses per 10% gold drop, calibrated across companies — did **not** survive our research verification yet. The authoritative cost definition (the **World Gold Council's AISC standard**) is solid and is what we anchor to, but the *elasticity* (the exact sensitivity) needs one more dedicated research pass before we treat Tool D's stress *magnitudes* as precise. The *direction and ranking* are trustworthy; the exact percentages should be treated as estimates for now.

---

## Part 10 — The bigger picture: "equity = an option on the commodity," and beyond gold

Step back and notice the beautiful symmetry: **Tool D treats the company as an option on gold** (its equity is worth something only when gold > cost, like a call option with strike = AISC), and **the Option Trading tool buys actual options on that company.** It's options on top of an option-like equity — leverage on leverage. That's why these miners swing so hard, and why a careful tool is worth building.

**Does this generalize beyond gold?** In theory, yes — **Brennan & Schwartz (1985)** applies to *any* commodity producer: oil & gas companies vs crude, copper miners vs copper, silver, uranium, and so on. They should all show >1 commodity-betas and option-like convexity. **But** the cross-commodity *evidence* (their actual betas, their cost curves) is **not yet verified** in our research — so a multi-commodity version is a *sound idea that needs its own research pass* before we build it. For now the tool is gold-specific, which is the right place to start.

---

## Part 11 — How the pieces fit together (the assembly)

The tool is built in a strict order — **raw data → validated features → scoring → user interface** — so nothing downstream trusts un-QA'd data:

1. **Foundation / ingestion** — fetch and clean gold, FX, and each miner's price history; normalize everything to **USD** (we never mix currencies — a hard rule). QA gates catch bad data.
2. **Tool A — sensitivity** — the gold betas (up/down/core), volatility, confidence. *(Built.)*
3. **Tool B — screening** — fundamental valuation and a verdict, under a stated gold-price assumption. *(Built.)*
4. **Options ingestion** — pull the live option chains for the ~half of miners that have listed options. *(Built.)*
5. **Options engine + Option Trading tab** — candidate puts/calls, the scenario engine, the interactive sizing calculator. *(Built.)*
6. **Tool C — downside ranking** — combine the downside signals into a risk ranking that feeds the Option Trading tab. *(Planned.)*
7. **Tool D — fragility ranking** — the AISC margin-stress view. *(Planned.)*

Every published number records **where it came from** (a hashed source run) so any result can be reproduced later — that's the "replay" system. (One honest gap we found: replay currently verifies the *manifests* but doesn't yet re-check every underlying file they point to — a fix we've queued.)

---

## Part 12 — What to trust, and what to be humble about

**Trust (research-backed):**
- Miners are leveraged plays on gold; per-firm betas are the right way to measure it.
- Per-contract IV option pricing; Black-Scholes math, parity, and strategy signs are sound.
- Flagging thin tail data as low-confidence and keeping it out of rankings.
- Down-beta as a **descriptive** risk ranking.

**Be humble about (research-flagged):**
- Down-beta does **not** predict returns — it ranks risk, not reward.
- Buying options is **expensive on average** — a directional edge is required, not a free lunch.
- The straight-line beta breaks down at **extreme** (−20%) moves; real downside can be worse.
- Constant-IV scenarios **understate** put payoffs in a real crash.
- Tool D's stress *magnitudes* and any *multi-commodity* extension need more calibration before being treated as precise.
- Most "predictive" signals are in-sample and **fade** — use them as flags, not oracles.

The honest summary: **the architecture is sound and well-grounded in serious literature; the cautions are all about not over-claiming precision or predictive power.** For a tool that will inform real-money decisions, "powerful but humble about its limits" is exactly the right posture.

---

## Glossary

- **Beta** — how much a stock moves per 1% move in gold (the slope of a best-fit line).
- **Up-beta / Down-beta** — beta measured only in gold-up weeks / gold-down weeks.
- **Operating leverage** — fixed costs that magnify profit swings when revenue (gold price) moves.
- **AISC (All-In Sustaining Cost)** — a miner's all-in cost per ounce; its break-even gold price.
- **EBITDA** — a common measure of operating profit.
- **Option / Put / Call** — a contract to sell (put) or buy (call) at a set price; a leveraged directional bet with a fixed maximum loss (the premium).
- **Premium** — what you pay for an option.
- **Strike** — the price at which an option lets you buy/sell.
- **Black-Scholes** — the standard option-pricing formula.
- **Implied volatility (IV)** — the future turbulence the market has priced into an option.
- **Volatility skew / smile** — IV differing across strikes; downside puts usually pricier (the "skew").
- **Variance risk premium** — the tendency for implied vol to exceed realized vol, making options expensive on average.
- **Tail risk** — behaviour in the extreme worst outcomes.
- **Percentile rank** — where something sits, 0–100, versus its peers.
- **Convexity** — a curved (non-straight-line) response; miners curve, especially on the downside.
- **Replay / provenance** — recording exactly which data produced a result, so it can be reproduced.

## Sources (the serious papers behind this)
Tufano 1998 (*J. Finance*); Qin et al. 2023 (*JIFMIM*); Erb & Harvey 2012 (NBER/*FAJ*); Bawa & Lindenberg 1977 (*JFE*); Estrada 2002 (*Emerging Markets Review*); Atilgan-Demirtas-Gunaydin 2020 (*Eur. Fin. Mgmt*); Levi-Welch-Karolyi 2020 (*RFS*); Yamai-Yoshiba 2002 (BIS); Pitera-Schmidt 2020; Barendse-Kole-van Dijk 2023 (*J. Fin. Econometrics*); Shahzad et al. 2021 (*Resources Policy*); Dumas-Fleming-Whaley 1998 (*J. Finance*); Rubinstein 1994 (*J. Finance*); Carr & Wu 2009 (*RFS*); Coval & Shumway 2001 (*J. Finance*); Christensen & Prabhala 1998 (*JFE*); Bollerslev-Tauchen-Zhou 2009 (*RFS*); Xing-Zhang-Zhao 2010 (*JFQA*); Pan & Poteshman 2006 (*RFS*); Brennan & Schwartz 1985 (*J. Business*); World Gold Council AISC standard. (Full detail + verification status in `research_academic_grounding_gold_model.md` and `research_options_methodology_and_predictors.md`.)
