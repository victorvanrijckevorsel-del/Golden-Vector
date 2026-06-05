# Tool D — redesign: gold-price-calibratable quality scorecard

**Author:** Claude Code (Opus 4.8)
**Date:** 2026-06-04
**Supersedes:** the Tool D section of `claude_tool_c_d_plan_v3.md`. **Tool C is unchanged.**
**Why:** Emanuel clarified Tool D should be richer than "EBITDA collapses by X% if gold drops 20%." It should be a **gold-price-calibratable quality scorecard** that reuses the metrics his screening Excel (= Tool B + the manual store) already computes.

## Emanuel's locked decisions
1. **A single tunable gold price.** One input/slider — set a gold price, everything recomputes at it (not a fixed −10/−20 stress table).
2. **Metrics shown separately, and you can watch them move with gold:** how **EBITDA** changes as the gold price moves, and how the **EBITDA-connected ratios** change — **net-debt/EBITDA (leverage)** and **EV/EBITDA**.
3. **A gold-stressed *quality* scorecard — symmetric** (usable for an UP-gold thesis or a DOWN-gold thesis), not a downside-only fragility tool.

## Data confirmed (2026-06-04)
**61 of 63 miners** have AISC, production, net debt, EBITDA, cash cost, reserve life in the manual store. The screening Excel tabs (Layer 1 Robust Screen, Layer 2 Earnings Model, Price comparisons, AISC/Production verification) **map exactly to Tool B + the manual store.** So every metric Tool D needs already exists — no new data.

## The core idea
> **Tool D = Tool B's earnings model with a live gold-price dial, showing EBITDA and every EBITDA-derived ratio recompute, plus an overall quality rank at that gold price — symmetric for up- or down-gold.**

The key mechanic, driven by one gold-price input `G`:
```
G  →  forward_revenue = production_oz × G
   →  forward_EBITDA(G)   (reuse Tool B Layer-2 earnings model: revenue − cash cost − royalty, etc.)
   →  margin_per_oz(G) = G − AISC ;  headroom_to_breakeven(G) = (G − AISC)/G
   →  leverage_stressed(G) = net_debt / forward_EBITDA(G)        ← gold-sensitive
   →  ev_ebitda(G) = (market_cap + net_debt) / forward_EBITDA(G) ← gold-sensitive
   →  per-metric views  +  a composite "quality at G" rank
```

### Important fix vs Tool B
Tool B's published `leverage` = `net_debt / ebitda_ltm` (trailing, **not** gold-sensitive). Emanuel wants leverage to **move with gold**, so Tool D computes **`leverage_stressed(G) = net_debt / forward_EBITDA(G)`** — the gold-dependent forward EBITDA. (Tool B's `ev_ebitda` already uses forward EBITDA, so it's already gold-sensitive.)

## What it outputs (per ticker, at the chosen gold price G)
**Separate, watch-them-move metrics:**
- `forward_ebitda_at_G` (and % change vs a reference gold price)
- `leverage_stressed_at_G` = net_debt / forward_EBITDA(G)
- `ev_ebitda_at_G`
- `margin_per_oz_at_G`, `headroom_to_breakeven_pct_at_G`, `breaks_even_at_gold_usd` (= AISC)
- context (not gold-driven): cash cost, reserve life, market cap, FCF yield, Tool B targets/upside, screening verdict

**A composite "quality at G" score + rank** (0–100, percentile), blended from the stressed metrics with config weights. **Symmetric:** the *same* engine, just at a different G — at high G fragile miners look strong (margin expansion, deleveraging); at low G they look weak. So one tool serves both theses.

**Tags** (gold-aware): `margin_negative_at_G`, `leverage_undefined_at_G` (EBITDA ≤ 0 → null ratio + tag, never inf), `thin_margin_at_G`, `deleveraging_strongly` (at high G), `missing_aisc/production/debt`.

## How you use it
- **CLI:** `python main.py tool-d --gold-price 1800` → a scorecard parquet at that gold price.
- **UI:** a Tool D tab with a **single gold-price input/slider**; the table recomputes EBITDA, leverage, EV/EBITDA, margins, and the quality rank live. Sortable. Plain-English "at $1,800 gold" framing.

## Reuse, not reimplement
Tool D should **call Tool B's Layer-1/Layer-2 earnings functions** (`golden_vector/screening/layer1.py`, `layer2.py`) at the chosen gold price rather than duplicating the revenue/EBITDA math — those already encode royalty, cash cost, DA, interest, tax. Tool D adds: the gold dial, the gold-sensitive leverage, and the composite quality scoring/ranking. (Confirm those functions are callable with a gold-price argument outside the full Tool B pipeline; if not, a thin extraction is the first step.)

## Honest caveats (kept)
- It's a **screening/scenario** view, not a precise valuation. Forward EBITDA from `production × (G − costs)` is a simplification of a real income statement (hedging, by-products, grade changes, ramp-ups are ignored). Label it "simplified gold-economics model."
- The **composite quality score is descriptive**, not a return forecast (same lesson as Tool A/C).
- Reserve life / cash cost are static manual inputs — as good as the manual data.

## Connection to the rest
- The **"quality at G" rank becomes a Candidate Finder criterion** (config) — so you can screen "best names for a gold-DOWN bet" (low-G quality weak + high down-beta + usable puts) or "best for a gold-UP bet" (high-G quality strong + high up-beta + usable calls). The gold price is the parameter that flips the lens.
- Tool C (downside price-behavior ranking) is unchanged and complementary: Tool C = how the **stock** moves; Tool D = how the **economics** look at a chosen gold price.

## What changes in the build plan
- The Tool D schema (§2e of the C/D plan) is replaced by the above (gold-parametrized fields + quality rank). The margin/leverage math moves from fixed −10/−20 to a **single `G` parameter**, with leverage using forward EBITDA.
- New: the **gold-price input** (CLI flag + UI slider) and reuse of Tool B's earnings functions.
- Everything else in the C/D v3 plan (provenance, eligibility, percentile-rank helper reuse, config registration) still applies.

## Open items to confirm
- **OD-A:** the composite "quality at G" weighting — equal across stressed-margin / leverage / valuation, or weighted? *(Recommend: equal v1, config-driven.)*
- **OD-B:** reference gold price for the "% change in EBITDA" column — current spot, or the user's chosen G vs spot? *(Recommend: show vs current spot.)*
- **OD-C:** confirm Tool B's Layer-1/2 functions are cleanly callable at an arbitrary gold price (the one technical prerequisite).
