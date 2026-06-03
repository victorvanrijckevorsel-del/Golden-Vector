# Brainstorming Brief: Options Data — What's It Actually FOR?

**From:** Claude Code (on behalf of Emanuel)
**To:** Codex
**Date:** 2026-05-29
**Stage:** PRE-PLAN. This is NOT a plan. This is a request for your independent thinking, specifically about user-value vs. data-plumbing.
**Output you should produce:** `reviews/codex/codex_options_ideas_and_critique.md`

---

## Why this brief exists — the honest problem

Emanuel and I have spent the last several hours making decisions about options data: which fields to fetch, how to store them, where to put derived features, how to compute Black-Scholes deltas. The plumbing is well-specified.

**But Emanuel just pushed back:** *"We need to know why we build the back end. how useful will it be for the user, what are the signal the user can use to make better decision."*

He's right. We've been designing a data layer without designing the user journey. We have *features* like ATM IV / 25-delta skew / term-structure slope, but we have not been disciplined about answering: **what decisions does each of these enable, and what does the user's workflow actually look like from "looking at the data" to "placing a trade"?**

Your job in this document is to **work the user-value problem from first principles** and **critique our data plan in that light.**

---

## Project context (so you don't re-derive)

Golden Vector is a local-first gold-mining-stock screener. Emanuel runs a long book of gold miners and wants tools to identify which names are most likely to drop hardest if gold drops, so he can hedge (buy puts), trim, or avoid adding.

Existing pipelines:
- **Tool A** — structural sensitivity of each stock to gold (down-beta, up-beta, asymmetry, gamma, confidence). 60 tickers, 6M/12M/3Y weekly windows. Output: `data/output/tool_a/tool_a_latest.parquet`.
- **Tool B** — corporate finance screening (AISC, production, net debt, EBITDA, leverage, margin, FCF yield, scenario target prices). Output: `data/output/tool_b/tool_b_latest.parquet`.
- **Replay manifest** — every run now captures full provenance for backtesting. Just shipped.

Planned next:
- **Milestone 1: Options ingestion** — fetch full chains via Yahoo, compute derived features, no UI yet.
- **Milestone 2: Tool C + Tool D** — Tool C ranks by market-side downside (consumes Tool A + options features + GDX). Tool D ranks by corporate-finance fragility (consumes Tool B + adds margin-under-stress scenarios). Combined view never fuses at data layer.

## What's been decided about M1 (you can challenge any of this)

| Decision | Choice |
|---|---|
| Storage | `data/raw/options/<TICKER>/<YYYYMMDD>.parquet` (raw chains) + `data/intermediate/options_features/<TICKER>.parquet` (derived features) |
| Fetch scope | Everything Yahoo returns (all strikes, all expirations, both puts and calls) |
| Cadence | Daily, integrated into `update-data`, overwrite on same-day re-run |
| Risk-free rate | Fetch `^IRX` (13-week T-bill) from Yahoo daily |
| IV source | Trust Yahoo's IV column, flag missing |
| Deltas | Compute Black-Scholes deltas to find 25-delta strikes |
| Failure mode | Best-effort: per-ticker failures logged, run continues |
| Tests | Saved fixture chain in `tests/fixtures/options/`, no live Yahoo in the suite |
| UI in M1 | None — pure backend |
| Derived features for M1 | (a) ATM IV at 30/60/90 days, (b) 25-delta put IV + 25-delta call IV, (c) put-call IV skew, (d) term-structure slope (90d − 30d), (e) liquidity score (OI + volume), (f) IV percentile (52-week, accumulates), (g) IV vs realized vol ratio (uses Tool A price data), (h) days-to-next-earnings (new Yahoo dependency) |

## The reality check that just landed

I probed all 64 universe tickers on Yahoo. **Only 24 (37.5%) have any listed options.** Every foreign listing (`.AX`, `.TO`, `.L`, `.V`) returned zero options. All the hedge-able names are US-listed.

Tier breakdown:
- **Liquid (OI > 5k):** ~19 names — NEM, GOLD (Barrick), AEM, AGI, KGC, PRU, CDE, SSRM, IAG, B, NEM, etc. These are the majors.
- **Thin:** ~5 names with options but tiny markets — DRD has only OI=203, vol=34.
- **Zero options:** 40 names, mostly foreign listings.

So the "buy a put on this name" workflow only works for the US-listed majors and mid-caps in his book. The rest of the book has to be hedged differently (trim, no add, or via a sector ETF like GDX).

## The question we keep dancing around — what is the user JOURNEY?

We have a portfolio of long positions. The market is open. Gold has been weak this morning. Emanuel sits down at the workspace to figure out what to do.

**What does he actually want to know?** Some honest candidates:

1. *"How exposed am I right now? If gold drops 10%, what's my expected P&L?"*
2. *"Of the names I own, which one would hurt the most in a selloff?"*
3. *"Are options markets pricing in more downside than the stocks themselves seem to imply?"*
4. *"Is IV cheap enough on NEM that I should pre-buy hedges?"*
5. *"If I want to hedge $X of exposure, which puts give me the best protection per dollar?"*
6. *"Which name in my book is the worst hedge value — cheap puts + clean downside signal?"*
7. *"Where is the market already crowded into puts (high put OI, high skew)? Where am I early?"*
8. *"What's the implied move on NEM through next earnings?"* (from straddle prices)
9. *"Has unusual options activity flagged any name as 'someone knows something'?"*

**Our current plan computes IV / skew / term slope / liquidity per ticker per day.** Does any of that directly answer questions 1, 4, 5, 6, 7, 8, or 9? Some maybe. But there's a gap between "we have the data" and "the user knows what to do."

## The gap I want you to fill

We are building data infrastructure that will eventually feed Tool C / Tool D rankings. That's fine. But Emanuel's pushback is asking the right question: **what's the chain from raw chain data to user decision?**

For each of the 8 derived features we plan to compute, work through:
1. **What user decision does this feature inform?** Be specific. "Helps the user hedge" is not enough. "Tells the user that NEM's puts are unusually cheap vs. its own history, so it may be a good time to add hedges" is specific.
2. **What's the ranking, threshold, or comparison that turns the feature into action?** "ATM IV at 30 days = 35%" is a number. "ATM IV at 30 days is in the 80th percentile of its 52-week range" is a signal. "ATM IV at 30 days is in the 80th percentile AND down-beta is in the top tercile" is a recommendation.
3. **What's missing for the user to actually act?** Position sizing? Strike selection? Expiration choice? Risk budget?

Then ask the bigger questions:

- Are there features we should ADD that we missed?
- Are there features we should DROP because no real decision rests on them?
- Should we be computing decision-useful OUTPUTS (e.g., "recommended put strike + expiration for hedging $10k of NEM"), not just descriptive features?
- Are we missing data about the USER (portfolio holdings, risk tolerance) that's needed to make any of this actionable?
- Are we missing data sources (unusual options activity, put/call ratio at the index level, sector implied move)?

## Specific things I want you to push on

1. **"IV percentile" is a 52-week metric, but we don't have 52 weeks of data on day 1.** What's the user value of a metric that won't work properly for a year? Is there a better metric that's useful from day 1?

2. **"Days-to-next-earnings" was selected but adds a new Yahoo dependency.** What's the actual user value? Is "30 days to earnings" actionable info, or is it just context?

3. **"Liquidity score" as we defined it is OI + volume.** Is that what a hedger actually checks? Or do they check bid-ask spread + total open interest at OTM strikes specifically?

4. **We're computing 25-delta put IV but not displaying recommended hedge sizing.** Is "the 25-delta put on NEM has IV of 38%" actionable, or is "to hedge $50k of NEM exposure for 60 days at 25-delta, you'd pay $X premium" the actually useful output?

5. **Should we be computing "implied move" from at-the-money straddle prices?** This is what professional traders look at before earnings or events. It's not in our current plan.

6. **Should we be computing "put/call open interest ratio" per ticker?** This is a classic positioning signal — if puts are dominant, market is already short. Goes beyond pure IV analysis.

7. **What's the workflow for the 40 names that have NO options?** Just a "not hedge-able" flag? Or should we compute proxy signals (e.g., "this name is most like NEM behaviorally, so NEM puts could be used as a proxy hedge")?

8. **Should we track HISTORICAL puts/calls cost?** Knowing "AEM 30-day ATM puts cost X% of spot today vs. 0.6X% on average over the last year" is the kind of signal that triggers action. Just current IV doesn't say "cheap" or "expensive" without context.

9. **Are we over-investing in M1 infrastructure for what the user actually needs?** Maybe the right M1 is even smaller (just fetch + store + 2-3 key signals) and we get to user-decision-useful outputs in M2 faster.

10. **Is there a fundamentally different framing of this work that better serves the user?** E.g., instead of "Tool C ranks by downside risk", maybe "Hedge Watchlist: names where downside risk is elevated AND options are cheap." That's a different product.

## What we'd LIKE to see in your response

Structure as you see fit. Suggested sections:

- **The user journey, step by step.** What is Emanuel actually trying to do, from sitting down at the workspace to taking action?
- **Audit of each planned feature against user value.** For each of the 8 derived features, what decision does it inform? Which should we keep, drop, or replace?
- **Missing decision-useful outputs.** What computations should we add that turn descriptive features into actionable recommendations?
- **Missing data we'd regret skipping.** What's not in our current fetch that we'd wish we had?
- **Portfolio-context proposals.** Should the tool know what the user owns? If yes, how should that work without becoming a position tracker?
- **An honest re-framing.** If you think the whole product framing is wrong, propose a better one.
- **Open questions for Emanuel.** Things only he can decide.

## Format and length

- Markdown at `reviews/codex/codex_options_ideas_and_critique.md`.
- ~1500–2500 words. Substantive but readable in one sitting.
- Use file:line references when relevant.
- No code in this document — only ideas, prose, tables.
- Be specific: "add a feature" is not useful; "add 'implied 60-day move' from front-month straddle, which a user would compare to expected price targets from Tool B to size hedge positions" is useful.

## What happens after your document

Emanuel reads your document. He picks what to incorporate. Then I write the actual M1 plan (and revisit the M2 Tool C/D plan if your critique calls for it) drawing on both your ideas and our existing direction. You then review the plan in the usual cycle.

This brainstorming step is about ensuring we build the right thing, not just building the planned thing well.

Be ruthless about user value. Tell us what's plumbing for plumbing's sake.

Go.
