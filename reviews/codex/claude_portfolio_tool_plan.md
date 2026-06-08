# Plan — Portfolio tool: "what's my gold exposure, how do I hedge it, what breaks first"

**Author:** Claude Code (Opus 4.8)
**Status:** for review, then build. **Sequencing: build LAST** — it consumes Tool A (betas), Tool D / Corporate Resilience v2 (survival), and the option signals (GDX/GDXJ hedge cost). Do it after those land.
**Data:** `data/manual/portfolio/ibkr_positions_20260602.csv` (real IBKR export) + `data/manual/holdings/holdings.yaml` (canonical holdings). **Gitignored / sensitive — never commit, never print the account number or exact values.**

## 1. What this tool is (and is NOT)
Per the portfolio README, this is **not** a second screener for names you own. The book is **~£270k of small/mid gold miners across AUD/CAD/GBP** that **mostly have no liquid single-name options**. So the tool answers the one question those facts force:

> **"How much gold exposure do I actually carry, how do I hedge it with the only liquid vehicle (GDX/GDXJ put or short), and which of my holdings are most fragile if gold falls?"**

It's the **personal lens** that reuses everything else: Tool A (gold beta), Tool D/Corporate Resilience (survival under a gold drop), the option signals (is GDX hedging cheap or expensive now), and FX.

## 2. Core value — three things, in priority order
### A) Aggregate gold exposure → the hedge sizing (the headline)
- **Effective gold exposure** = Σ (position value in USD × the name's gold beta). For covered names, use Tool A's structural beta; for **uncovered** names (small ASX/explorers not in the universe), use a documented **default miner beta** (or the GDX beta) so they still count toward the hedge — and flag them as "estimated."
- **Hedge sizing:** to neutralize a gold drop, `GDX notional to short ≈ effective gold exposure ÷ GDX's own gold beta`; `# GDX puts ≈ that notional ÷ (GDX price × 100)`. Show it as a plain instruction: *"Your book ≈ £X of effective gold exposure. To hedge a 20% gold drop you'd short ≈ £Y of GDX, or buy ≈ N GDX 90-day puts."*
- **Hedge cost context** (from the option signals): is GDX/GDXJ IV cheap or expensive right now (IV-rank / IV-vs-RV)? "Hedging is cheap/expensive at the moment."
- **FX, surfaced not over-engineered:** the book is AUD/CAD/GBP; gold/GDX are USD. State the FX exposure of the hedge (a GBP book hedged with a USD instrument), one clear note — don't build an FX model.

### B) Portfolio resilience — what breaks first if gold falls
Overlay Corporate Resilience v2 on the **covered** holdings: at a chosen stressed gold price, **which of your names go margin-/FCF-/interest-negative**, and **what % of your portfolio value** sits in fragile names. "At $2,500 gold, 3 of your holdings (X% of the book) stop covering interest." This is the downside companion to the hedge.

### C) Holdings profile — quality + sensitivity of what you actually own
A compact table of your covered holdings with their Tool A (gold beta / profile), Corporate Finance (checks passed), Corporate Resilience (breakeven gold), and option-signal (sector-relative skew) reads — so you see the character of the book at a glance, and spot a fragile or low-quality holding.

## 3. Data handling (the unglamorous but load-bearing part)
- **Ticker normalization** — map broker symbols to universe tickers: exchange-suffix rules (IBKR `AAZ` → `AAZ.L`, `EDV`→`EDV.L`, `PAF`→`PAF.L`; `.TO`/`.AX` handling), and an explicit override map for dual listings (Serabi `SBI`(TSX)/`SRB`(LSE) → one universe ticker). Put the override map in config, not inferred in code.
- **Coverage honesty (no silent gaps):** compute `% of portfolio value that is analyzable` and **list the uncovered names explicitly** ("AAR, WAF, MTL — not in the covered universe; included in the hedge at an estimated miner beta, excluded from quality/resilience"). Never silently drop a holding.
- **Currency** — convert each position to a common currency (USD or GBP) using the FX we already fetch; show the per-currency split.
- **Source of truth:** prefer `holdings.yaml` (clean: ticker + shares/dollar_exposure) as the canonical input; use the IBKR CSV as the importer that *produces* it. Current market values for covered names come from the foundation prices we already fetch.

## 4. Backend / architecture (single source of truth, no duplication)
- **All portfolio math at refresh (or a `portfolio` CLI step), persisted** — aggregate exposure, hedge sizing, resilience overlay, FX split. The serve layer **reads and renders only**; no portfolio arithmetic in the request path.
- **Reuse, don't re-derive:** betas from Tool A's persisted output; survival from Tool D; hedge cost from the option-signal artifacts; FX from the foundation. The portfolio tool is an **aggregation layer**, not new financial formulas.
- Persist a `portfolio_summary` artifact (exposure, hedge recommendation, coverage, FX) + a `portfolio_holdings` artifact (per-name joined reads), with schema_version + run identity + a fail-loud stale guard, consistent with the other artifacts.

## 5. UI (a Portfolio tab)
- **Top: the hedge card** — effective gold exposure, the GDX/GDXJ hedge instruction (short notional + put count), hedge-cost context (cheap/expensive now), and the FX note.
- **Resilience strip** — at a gold-stress slider (reuse Corporate Resilience's), "% of book fragile / names that break."
- **Holdings table** — covered names with their A/B/D/signal reads; uncovered names listed separately with the coverage note.
- Compact, formulas-on-hover (the Tool D lesson). Blunt + accurate.

## 6. Honest limits
- The hedge is a **sector proxy (GDX/GDXJ), so there's basis risk** — your specific miners won't move exactly like GDX. State it.
- **Uncovered small-caps** are included in the hedge at an estimated beta only (no per-name analysis).
- **FX** is surfaced, not modeled — the hedge has currency mismatch the user manages.
- The IBKR export is a **point-in-time snapshot**; covered-name values update with live prices, the rest don't until re-exported.

## 7. Decisions for Emanuel
1. **Primary output = the hedge card** (effective exposure → GDX/GDXJ sizing + cost), with resilience + holdings profile beneath. (Recommended — matches the README's stated need.) Or do you want it more dashboard-first?
2. **Uncovered small-caps in the hedge:** include at an estimated miner beta (recommended — they're real gold exposure), or exclude and just flag them?
3. **Common currency:** USD or GBP for the totals? (Recommended GBP, since that's how you think about the book; hedge instrument is USD.)

## 8. Self-review
This makes the portfolio tool *distinct and personal*: it answers "what's my gold exposure, how do I hedge it, what breaks first" — grounded in the README's design-critical fact that the real names are unhedgeable individually, so GDX/GDXJ + aggregate sizing is the point. It's an **aggregation layer** over Tool A/D + the option signals (no new formulas, no duplication), backend-computed + persisted, honest about coverage/basis/FX limits. Dependencies mean it builds **after** the option signals and Corporate Resilience v2. Main judgment calls in §7 (output emphasis, uncovered-name handling, base currency) — propose defaults, confirm with Emanuel.
