# Codex Build Brief v2 — Options Liquidity & Scenario Lab (3 phases, data-gated)

**For:** Codex
**From:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Supersedes:** `claude_codex_options_liquidity_lab_build_brief.md` (v1) and the in-flight Option Trading clarity patch.
**Incorporates:** `codex_review_options_liquidity_lab_brief.md` (NEEDS CHANGES — all findings folded in) + Claude's added thoughts (§ marked ★).

## What changed in v2 (Codex findings → fix)
| Finding | Fix |
|---|---|
| **[Blocker] Step 0 can't prove GDX liquidity — ETF option chains aren't cached** (`has_GDX=False`; ingestion fetches only universe tickers; benchmarks are price-history only) | New **Phase 2** explicitly **ingests GDX/GDXJ option chains** (adds them as option-fetch targets + manifest + replay), *then* measures. Job 1 no longer depends on this. |
| **[Blocker] Job 2 overstates reuse** of `portfolio_totals`/`proxy_hedge`/`holdings` | Phase 3 reframed as **foundation + new hedge math**: extend holdings ingestion (IBKR CSV), symbol mapping, currency normalization, then **new** GDX/GDXJ portfolio-payoff sizing. Not "mostly reuse." |
| **[High] Portfolio needs symbol mapping + missing-beta rules** (only WAF/AAZ/EDVL/MTL/PAFL/SRB map cleanly; AAR/CLA/SBI/ALTNL don't; GDX-beta-proxy undefined) | Phase 3.1 adds a **symbol-map config** + ★same-company-multi-listing consolidation + ★a coverage-% + default-beta rule. |
| **[High] Job 1 + Job 2 over-scoped for one pass** | **Three phases** with the data gate between Job 1 and Job 2. Ship Job 1 first. |
| **[Med] Tier failure semantics** | §B specifies exact zero/neg/NaN handling + preserves existing strict quote gates; Tradable OI floor tuned after the gate. |
| **[Med] DTE/bucket acceptance too strong** | "≥1 bucket per horizon" removed; horizons **render bucket states incl. 'No usable contract' + near-miss; never force a candidate**. Monthly-expiry rule defined. |
| **[Med] Milestone A too vague** | §A lists exact columns to keep/hide. |
| **[Low] Refresh placeholder** | §D: strict "screening only" copy, no button-like control (disabled/non-interactive only). |
| **[Low] Replay/audit for ETF chains** | Phase 2 writes ETF chains into the latest options manifest + run replay manifest. |

## How to work
Continuous build with **deep self-review after each step, deeper at each checkpoint** (log in `reviews/codex/codex_options_lab_progress.md`). Stop only at the **data gate** and the two checkpoints. One commit per step + a self-review commit per phase. **No `git push`.** No live data in tests.

## Locked principles (carry from v1)
3-tier model (Tradable/Watch/No-trade); multiple buckets, **no "recommended/best/should buy" language**; relative spread dominant, volume = tiebreaker; `Last` informational only; **yfinance = screening only**; descriptive-not-predictive; honesty flags ("you may overpay", "lottery", half-spread cost, "options expensive on average"); measure GDX, never assert.

---

# PHASE 1 — Job 1: Single-stock Options Liquidity & Scenario Lab
*Independent of GDX/ETF data — ships value now for the optionable universe.*

### A — UI cleanup (concrete)
- Remove the long paragraphs (overview + detail); keep ONE compact note: `Cached options snapshot: <date>; screening only — live prices may differ.` Move caveats to a `Method` disclosure.
- **Stopgap table — keep exactly these columns**, hide the rest until D: `Ticker | Stock price | Down-β | Up-β | Tool A confidence | IV %ile | Put status | Call status | Snapshot date | Notes`. Drop the P&L/share columns and long `Why`/`Yahoo` text. One row per ticker on the overview.
**Acceptance:** no wall of text; the listed columns only; stock price + snapshot visible; no selection-logic change.

### B — Liquidity engine (keystone; pure + testable)
Per-contract metrics + the 3-tier classifier + `liquidity_score` (v1 formula: `0.55*spread + 0.25*oi + 0.10*premium + 0.05*depth + 0.05*volume`, spread-dominant, volume tiebreaker).
**Exact failure semantics (Codex [Med]):** zero/negative/NaN bid, ask, or mid → **fails the quote gate → No-trade** (preserve `options_chain.py` strictness, do not score invalid quotes); NaN OI/volume → treat as 0. **Tradable** starting gate: bid>0, ask>0, `rel_spread ≤ 0.20`, OI≥1, mid≥`0.15` — but **flag the OI floor for empirical tuning after the Phase-2 data is in** (Tradable may warrant a higher OI floor than Watch). Define `depth` = count of near-spot (±X% of spot) two-sided contracts.
**Build the shared `is_usable_candidate()` here** (Tradable-tier + bucket-fit) — the Candidate Finder will call this exact function.
**Acceptance:** tests for zero/neg/NaN quotes, huge spread, sub-min premium, high-OI-wide-spread; a diagnostic CLI prints a per-ticker liquidity summary; no UI redesign yet.

### C — Buckets (per side × horizon)
**DTE bands = search windows** (30d:21-45 tactical / 60d:46-75 / 90d:76-105 / 120d:106-150). **Selection lands on a real listed expiry; prefer a standard monthly** (3rd-Friday) expiry in-band, else nearest listed in-band. **Buckets:** Most-liquid, Near-ATM, Directional (calls 0.35-0.50 / puts −0.50 to −0.35), Tail put (−0.30 to −0.15), Model-fit (scenario strike). **Never force a candidate:** each bucket renders its state; when nothing qualifies, show **"No usable contract" + the best near-miss behind an expander**. Flag "lottery" (short+deep-OTM+high-IV). Config-driven thresholds (conventions, not laws).
**Acceptance:** 30d labeled tactical; AEM-like strike-50 cannot appear as a normal candidate; liquid NEM contracts stay visible; wide-spread near-spot contracts show as Watch, not invisible; empty buckets show "No usable contract", not a forced pick.

### D — Readable UI
Header strip (ticker, stock price, snapshot date, source, **disabled/non-interactive refresh placeholder only — never imply live quotes**) → liquidity summary (put/call Tradable/Watch/No-trade counts; "single-name options look thin" when most fail) → put/call tabs → **horizon cards** (compact rows: bucket, expiry, strike, moneyness, bid/ask/mid, spread %, **half-spread cost %**, OI, volume, tier, select) → expandable detail (delta, IV, Yahoo link, why accepted/rejected) → scenario calculator (after a contract is selected). Add the **beginner glossary** (Last/Bid/Ask/Mid/IV) + the "options are expensive on average" disclosure.
→ **CHECKPOINT 1: STOP & report.** Paste a liquid ticker (NEM) + a thin one (AEM): buckets, tiers, readable cards.

---

# PHASE 2 — Data gate: ETF option-chain ingestion + Step 0 measurement
*This is the blocker fix — GDX/GDXJ chains do not exist in cache today.*

### P2.1 — Ingest GDX/GDXJ option chains
Extend the options ingestion (`ingestion/options_phase.py`) so **GDX and GDXJ option chains are fetched and persisted like universe tickers** (not merely as price-history benchmarks): add them to the option-fetch targets, persist snapshots, and **record them in the latest options manifest + the run replay manifest** (Codex [Low] audit rule). Keep per-ticker error isolation. Tests with a fixture ETF chain.

### P2.2 — Measure GDX/GDXJ vs miners (the gate)
Run the Phase-1 liquidity engine on GDX/GDXJ and the miners; report **median relative spread, OI, volume, near-spot two-sided depth** for each.
→ **DECISION GATE: STOP & report.** If GDX/GDXJ are **materially more liquid** → proceed to Phase 3. If their chains are still unavailable or **not materially more liquid** → report and **halt**: Job 2's "hedge via GDX" premise needs rethinking (fallback: shares, or a different proxy).

---

# PHASE 3 — Job 2: Portfolio gold-downside hedge (only after the gate passes)
*This is mostly NEW build (per Codex) — foundation first, then hedge math.*

### P3.1 — Portfolio foundation (shared, reused later by Candidate Finder + Tool C/D)
- **IBKR CSV parser** → the `Holding` model (extend `hedge/holdings.py`; `load_holdings` currently only reads `holdings.yaml`). Source: `data/manual/portfolio/ibkr_positions_20260602.csv`.
- **Symbol-map config** (Codex [High]): IBKR symbol → universe ticker. Known clean maps: `WAF→WAF.AX, AAZ→AAZ.L, EDVL→EDV.L, MTL→MTL.L, PAFL→PAF.L, SRB→SRB.L`. **Unmapped need explicit entries:** `AAR→Astral (ASX), CLA→Celsius (ASX/LSE), SBI→Serabi (TSX), ALTNL→Altyngold (LSE)`. Anything still unmapped is listed as "unmapped — excluded from hedge math" (never silently dropped).
- ★ **Same-company, multi-listing consolidation (Claude):** the CSV holds **Serabi twice (SBI on TSX + SRB on LSE)** and **Celsius twice (ASX + LSE)**. Consolidate by underlying company so gold exposure isn't double-counted; show the consolidated view.
- **Multi-currency → USD:** normalize AUD/CAD/GBP position values to USD using the FX we already fetch. (No mixed-currency analytics — the repo's hard rule.)

### P3.2 — Beta coverage & missing-beta rule (Codex [High] + ★Claude)
- Use Tool A `down_beta_core` per mapped name. **Track coverage:** report "modeled on betas covering **X% of portfolio value**."
- ★ For names with **no/low-confidence beta** (micro-caps, no history): assign a **flagged default gold-beta** (e.g. universe median down-beta, or an explicit "assumed ~2.0"), and show **two numbers** — *known-beta downside* + *estimated total with default beta for the rest* — so the user sees what's measured vs assumed. **Never present a precise hedge over a half-estimated book.** The benchmark/GDX-beta fallback that's `None` in `proxy_hedge` is not a substitute — define the default here.

### P3.3 — Hedge sizing (NEW math) + honest framing
- Aggregate: `portfolio_gold_downside(gold%) = Σ position_value_usd × beta × gold%` over consolidated, mapped holdings.
- **Size a GDX/GDXJ put** to offset that downside: contracts ≈ portfolio gold-downside ÷ GDX-put payoff per contract at the same gold move, choosing strike/horizon from the **Phase-1 buckets** (so it's tradeable). This is **new** payoff math (not `compute_portfolio_totals`, which sizes per-holding single-name puts).
- ★ **Frame as ROUGH:** given symbol-map gaps, assumed betas, **basis risk** (GDX = large US miners vs your small foreign names — show a beta-dispersion estimate), and **FX** (GBP/AUD/CAD vs USD), this is order-of-magnitude hedge *sizing to consider*, not a precise hedge ratio. Say so plainly.
**Output:** *"~£271k gold-miner book, est. gold-down-beta ~X (betas cover Y% of value; rest assumed). Gold −10% → modeled loss ≈ £Z. Rough hedge: ~N GDX <strike> <expiry> puts (≈£C, ~W% of portfolio). Caveats: basis risk (GDX≠your names), FX (USD vs GBP/AUD/CAD), options expensive on average."*
→ **CHECKPOINT 2: STOP & report.** Paste the hedge output against the real CSV + the Phase-2 liquidity comparison.

---

# Out of scope (separate plans)
- **Refresh button** (background-job + status-page design; synchronous will time out).
- Vol-surface model; live executable pricing; any recommendation language; a public put-call-ratio "signal"; the refuted "illiquid options earn 3.4%/2.5% daily" claim; presenting index/earnings retail stats as miner-specific.

# ★ Claude's added thoughts (beyond Codex's findings)
1. **The data gate reframes the roadmap honestly:** Job 1 is high-value and ships *now* with zero GDX dependency; Job 2's value is entirely contingent on the Phase-2 measurement. Don't let Job 2's appeal delay Job 1.
2. **Same-company-multi-listing + multi-currency consolidation** is a genuine correctness issue for *this* portfolio (Serabi & Celsius each held on two exchanges) — handle it in the loader, not as an afterthought.
3. **Coverage % over false precision:** the honest output is "hedge sized on betas covering Y% of the book," with assumed betas flagged — consistent with the Candidate Finder's coverage philosophy.
4. **The portfolio loader is the seed of the future portfolio tool** — build it once, cleanly, in `hedge/holdings.py`; the Candidate Finder and Tool C/D will reuse the same parsed, mapped, currency-normalized holdings.
5. **If the Phase-2 gate fails** (GDX not usefully more liquid), the honest fallback for hedging this book is **shares/short or simply sizing-down** — not a forced option. Keep that as the documented alternative so "no good hedge" is itself a valid, honest answer.

# Done =
Phase 1 ships Job 1 (readable, tiered, bucketed, honest single-stock lab) through Checkpoint 1; Phase 2 ingests ETF chains + reports the liquidity gate; Phase 3 (only if the gate passes) ships the portfolio hedge with coverage %, consolidation, and basis/FX honesty through Checkpoint 2; the shared `is_usable_candidate` primitive + portfolio loader built once; full suite green; completion report written.
