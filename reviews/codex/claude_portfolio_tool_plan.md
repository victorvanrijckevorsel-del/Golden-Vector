# Plan — Portfolio tool (see your book; one section looks at hedging)

**Author:** Claude Code (Opus 4.8)
**Status:** for review, then build. **Sequencing: build LAST** — it consumes Tool A (betas/returns), Tool C/D (downside + resilience), and the option signals (hedge cost). Do it after those land.
**Data:** `data/manual/portfolio/ibkr_positions_20260602.csv` (real IBKR export) + `data/manual/holdings/holdings.yaml` (canonical holdings). **Gitignored / sensitive — never commit, never print the account number or exact values.**

## 1. What this tool is (Emanuel: a PORTFOLIO tool, not a hedging tool)
It is **not** branded as a hedging tool. It's a **portfolio tool** — see your actual book through every lens we've built — and **hedging is one section inside it.** The book is ~£270k of small/mid gold miners across AUD/CAD/GBP, mostly without liquid single-name options. The tool shows: **what you hold, your P&L, how your names relate to each other, your aggregate gold exposure, how the book holds up if gold falls, and — as one part — how to protect it.**

## 2. Core sections
### A) Composition (the at-a-glance view)
- **Holdings pie chart** — each position's weight in the book; a second slice by **currency** (AUD/CAD/GBP) and by **cost-curve/jurisdiction** if useful.
- Total value, # positions, per-currency split, cash.
- **Coverage banner:** "% of book analyzable" + the uncovered small-caps listed explicitly (never silently dropped).

### B) P&L — "what did I pay, and how's it doing" *(needs cost-basis data — see §3)*
- **Per-holding and total P&L** = current value − cost basis. Requires **cost basis + buy date**, which the current IBKR *positions* export does NOT contain — add them to `holdings.yaml` or import an IBKR *trades/lots* export (§3).
- **P&L-over-time chart** — reconstruct portfolio value over time from the price history we already fetch (for covered names) minus cost basis → a line of how the book's value/P&L evolved. (Covered names only; uncovered held flat or flagged.)

### C) Correlation (diversification / hidden concentration)
- A **correlation heatmap** of your holdings' weekly returns (covered names — we have the series via Tool A). Gold miners are all gold-correlated, so the value is spotting the **most-correlated pairs** (you're doubly exposed to the same move) vs the diversifiers. Blunt label: "AAZ.L and ALTN.L move 0.8 together — limited diversification between them."

### D) Gold exposure
- **Effective gold exposure** = Σ (position USD value × the name's gold beta, from Tool A). For uncovered small-caps, a documented **default miner beta** so they still count, flagged "estimated."
- "Your ~£270k book ≈ £X of *effective* gold exposure (gold-beta-adjusted)."

### E) Resilience — what breaks first if gold falls
Overlay Corporate Resilience v2 on the covered holdings: at a chosen stressed gold price, **which of your names go margin-/FCF-/interest-negative**, and **what % of your book** sits in fragile names. "At $2,500 gold, 3 holdings (X% of the book) stop covering interest."

### F) Hedging (one section — two routes)
Protect the aggregate gold exposure from a gold drop. **Two complementary routes:**
1. **Sector hedge (GDX/GDXJ)** — the liquid default. `short notional ≈ effective gold exposure ÷ GDX gold beta`; `# GDX puts ≈ notional ÷ (GDX price × 100)`. Plus hedge-cost context from the option signals (is GDX IV cheap/expensive now). FX surfaced (GBP book vs USD instrument), one note, not a model.
2. ⭐ **Proxy / overshoot hedge (single name expected to fall MORE)** — Emanuel's point, and *the whole reason for some of the tools*: instead of (or alongside) GDX, **short or put a name we expect to crash harder than the sector if gold drops**, so a smaller hedge does more work. Rank candidates by **high down-beta (Tool A `down_beta`)** + **worst downside behavior (Tool C downside rank)** + **fragility (Corporate Resilience: highest breakeven gold / over-levers earliest)** + **tradability (liquid options or shortable)**. Surface: *"Proxy hedge idea: short/put NAME X — high down-beta (~1.8×), breaks even only at $2,400, ranks worst on downside — expected to fall ~2× the sector in a gold crash."* This is the inverse of the buy screen, and it reuses Tool A/C/D directly.

### G) Holdings profile table
Covered holdings with their Tool A (gold beta / profile), Corporate Finance (checks), Corporate Resilience (breakeven gold), and option-signal reads — the character of the book at a glance.

## 3. Data handling (the unglamorous but load-bearing part)
- **Ticker normalization** — map broker symbols to universe tickers: exchange-suffix rules (IBKR `AAZ` → `AAZ.L`, `EDV`→`EDV.L`, `PAF`→`PAF.L`; `.TO`/`.AX` handling), and an explicit override map for dual listings (Serabi `SBI`(TSX)/`SRB`(LSE) → one universe ticker). Put the override map in config, not inferred in code.
- **Coverage honesty (no silent gaps):** compute `% of portfolio value that is analyzable` and **list the uncovered names explicitly** ("AAR, WAF, MTL — not in the covered universe; included in the hedge at an estimated miner beta, excluded from quality/resilience"). Never silently drop a holding.
- **Currency** — convert each position to a common currency (USD or GBP) using the FX we already fetch; show the per-currency split.
- **Source of truth:** prefer `holdings.yaml` (clean: ticker + shares/dollar_exposure) as the canonical input; use the IBKR CSV as the importer that *produces* it. Current market values for covered names come from the foundation prices we already fetch.
- **Cost basis + buy date — NOT in the current data (the P&L blocker).** The IBKR *positions* export has only mark-to-market *period* P&L (Prior Price → Price), not "since you bought," and there's no trades file. To enable P&L (§2-B), add `cost_basis` (avg price or total cost) + `purchase_date` per holding to `holdings.yaml`, **or** import an IBKR *Trades/Lots* report (which has them). The P&L-over-time chart then reconstructs from the price history we already have for covered names. Until that data exists, the tool shows composition/exposure/resilience/hedging but **labels P&L "add cost basis to enable,"** not a fake number.

## 4. Backend / architecture (single source of truth, no duplication)
- **All portfolio math at refresh (or a `portfolio` CLI step), persisted** — aggregate exposure, hedge sizing, resilience overlay, FX split. The serve layer **reads and renders only**; no portfolio arithmetic in the request path.
- **Reuse, don't re-derive:** betas from Tool A's persisted output; survival from Tool D; hedge cost from the option-signal artifacts; FX from the foundation. The portfolio tool is an **aggregation layer**, not new financial formulas.
- Persist a `portfolio_summary` artifact (exposure, hedge recommendation, coverage, FX) + a `portfolio_holdings` artifact (per-name joined reads), with schema_version + run identity + a fail-loud stale guard, consistent with the other artifacts.

## 5. UI (a Portfolio tab — composition first, hedging is a section)
- **Composition (top):** the **holdings pie chart** (weights), per-currency split, total value/cash, coverage banner. The at-a-glance "what do I own."
- **P&L:** total + per-holding P&L, and the **P&L-over-time line chart** (or "add cost basis to enable" if the data isn't there yet).
- **Correlation heatmap:** holdings' return correlations — spotting doubled-up vs diversifying pairs.
- **Exposure + Resilience:** effective gold exposure; a **gold-stress slider** (reuse Corporate Resilience's) showing "% of book fragile / which names break."
- **Hedging section (not the whole page):** the GDX/GDXJ sizing card **and** the proxy-short candidates ("names expected to fall more"), with hedge-cost context + the FX note.
- **Holdings table:** covered names with their A/B/D/signal reads; uncovered names listed separately.
- Charts: pie, P&L-over-time, correlation heatmap — data computed at refresh, UI only plots (reuse `serve/charts.py`). Compact, formulas-on-hover, blunt + accurate.

## 6. Honest limits
- The hedge is a **sector proxy (GDX/GDXJ), so there's basis risk** — your specific miners won't move exactly like GDX. State it.
- **Uncovered small-caps** are included in the hedge at an estimated beta only (no per-name analysis).
- **FX** is surfaced, not modeled — the hedge has currency mismatch the user manages.
- The IBKR export is a **point-in-time snapshot**; covered-name values update with live prices, the rest don't until re-exported.

## 7. Decisions for Emanuel
1. **Cost basis + buy date for P&L** — will you add `cost_basis`/`purchase_date` to `holdings.yaml`, or export an IBKR Trades/Lots report? (Until one of those, P&L is shown as "add cost basis to enable," not faked.)
2. **Uncovered small-caps:** include them in the exposure/hedge at an *estimated* miner beta (recommended — they're real gold exposure), or exclude and just flag?
3. **Base currency** for totals — **GBP** (how you think about it) or USD? (Recommended GBP; hedge instrument is USD.)
4. **Proxy-short candidates:** rank by down-beta + downside rank + fragility + tradability (recommended) — confirm that's the right definition of "would fall more."

## 8. Self-review
Reframed per Emanuel: a **portfolio tool** (composition, P&L, correlation, exposure, resilience) with **hedging as one section**, not a hedging tool. The hedging section now has *two* routes — the GDX/GDXJ sector hedge **and** the proxy-short ("name expected to fall more"), which is the inverse of the buy screen and reuses Tool A down-beta + Tool C + Tool D directly (the whole point of those tools). It's an **aggregation layer** (no new formulas, no duplication), backend-computed + persisted, honest about its gaps: **P&L needs cost-basis/date data we don't have yet** (flagged, not faked); coverage/basis/FX limits stated. Builds **after** the option signals + Corporate Resilience v2. Judgment calls in §7 — propose defaults, confirm.
