# Codex Build Brief v3 (FINAL) — Options Liquidity & Scenario Lab

**For:** Codex
**From:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Supersedes:** v1 and v2 of this brief, and the in-flight Option Trading clarity patch.
**Carries forward:** all of Codex's review fixes (`codex_review_options_liquidity_lab_brief.md`) + the research (`research_option_selection_liquidity_and_design.md`).

## Why v3 (Emanuel's clarification — this reframes the goal)
The tool's purpose, stated plainly:
> Emanuel is **long** a book of mostly small/optionless gold miners. To offset **gold-down** risk, he wants to **buy puts on *other*, liquid, optionable miners that would fall hard if gold drops** — the put profit offsets his portfolio loss. He is **not** hedging the specific stocks he owns. Calls are the symmetric gold-up bet. The Option tab is an **easy, complete browse of sensible, liquid put/call opportunities.**

Two consequences vs v2:
1. **Drop the auto-hedge-sizing.** The tool must **NOT** tell the user how much to hedge — the user decides. (v2's "size a GDX put to your £271k book" is removed.)
2. **The portfolio is context only**, and the full **portfolio tool is a separate future milestone.** This brief is the **Option tab**: browse + suggest **only sensible, liquid** contracts.

## The guiding principle (Emanuel's #2 — the heart of it)
> **Only ever suggest put/call contracts that *make sense to buy*: sensible strike/share-price ratio (not absurdly far OTM), sensible horizon, and *real liquidity* checked from the Yahoo data.** A junk contract (e.g. a strike-50 put on a $175 stock) is shown as **"no sensible liquid contract,"** never suggested. This is exactly what the deep research established (relative-spread-dominant liquidity, near-ATM/35-50Δ directional defaults, 60-90 DTE defaults).

## How to work
Continuous build with **deep self-review after each step, deeper at each checkpoint** (log in `reviews/codex/codex_options_lab_progress.md`). Stop only at the two checkpoints. One commit per step + a self-review commit per phase. **No `git push`.** No live data in tests. Pre-flight: confirm branch + `pytest -q` baseline.

## Locked principles
3-tier model (Tradable / Watch / No-trade); **suggest only sensible + liquid contracts**; multiple buckets per horizon; **no "recommended/best/should buy" language**; relative spread dominant, volume = tiebreaker; `Last` informational only; **yfinance = screening only**; descriptive-not-predictive; honesty flags ("you may overpay", "lottery", half-spread cost, "options expensive on average"); **measure GDX/GDXJ liquidity, never assert**; **never tell the user how much to hedge.**

---

# PHASE 1 — The sensible+liquid single-stock put/call lab (the core)

### A — UI cleanup (concrete)
- Remove the long paragraphs; keep ONE compact note: `Cached options snapshot: <date>; screening only — live prices may differ.` Move caveats to a `Method` disclosure.
- **Stopgap overview table — keep exactly:** `Ticker | Stock price | Down-β | Up-β | Tool A confidence | IV %ile | Put status | Call status | Snapshot date | Notes`. Drop P&L/share columns + long Why/Yahoo text. One row per ticker.
**Acceptance:** no wall of text; only those columns; stock price + snapshot visible; no selection-logic change.

### B — Liquidity engine (keystone; pure + testable)
Per-contract metrics + 3-tier classifier + `liquidity_score = 0.55*spread + 0.25*oi + 0.10*premium + 0.05*depth + 0.05*volume` (spread-dominant; volume tiebreaker only).
**Exact failure semantics:** zero/negative/NaN bid, ask, or mid → **fails the quote gate → No-trade** (preserve the existing strict gates in `features/options_chain.py`; never score invalid quotes); NaN OI/volume → 0. **Tradable** start: bid>0, ask>0, `rel_spread ≤ 0.20`, OI≥1, mid≥`0.15` — **flag the OI floor for empirical tuning** once we have the data (Tradable may need a higher OI floor than Watch). `depth` = count of near-spot (±X% of spot) two-sided contracts.
**Build the shared `is_usable_candidate()` here** (Tradable-tier + bucket-fit) — the Candidate Finder will call this exact function (one definition, no drift).
**Acceptance:** tests for zero/neg/NaN quotes, huge spread, sub-min premium, high-OI-wide-spread; a diagnostic CLI prints a per-ticker liquidity summary.

### C — Buckets (per side × horizon; only sensible+liquid)
**DTE bands = search windows; select a real listed expiry, prefer standard monthly (3rd-Friday) in-band, else nearest listed in-band:** 30d:21-45 (tactical/high-decay) · 60d:46-75 (default) · 90d:76-105 (default) · 120d:106-150 (slower). **Buckets:** Most-liquid · Near-ATM · Directional (calls 0.35-0.50 / puts −0.50 to −0.35) · Tail put (−0.30 to −0.15) · Model-fit (scenario strike = `beta × gold% → modeled price → nearest strike`). **Never force a candidate:** each bucket renders its state; when nothing sensible+liquid qualifies, show **"No sensible liquid contract" + best near-miss behind an expander.** Flag "lottery" (short+deep-OTM+high-IV). Thresholds config-driven (conventions, not laws).
**Acceptance:** 30d labeled tactical; a strike-50/$175 put can NEVER appear as a normal suggestion; liquid NEM contracts stay visible; wide-spread near-spot contracts show as Watch (not invisible); empty buckets show the honest "no sensible liquid contract," not a forced pick.

### D — Readable UI
Header strip (ticker, stock price, snapshot date, source, **disabled/non-interactive refresh placeholder only — never imply live quotes**) → liquidity summary (put/call Tradable/Watch/No-trade counts; "options look thin here" when most fail) → put/call tabs → **horizon cards** (compact rows: bucket, expiry, strike, moneyness, bid/ask/mid, spread %, **half-spread cost %**, OI, volume, tier, select) → expandable detail (delta, IV, Yahoo chain link, why accepted/rejected) → scenario calculator (after a contract is selected). Add the **beginner glossary** (Last/Bid/Ask/Mid/IV) + the "options are expensive on average; you can be right on direction and still lose" disclosure.
→ **CHECKPOINT 1: STOP & report.** Paste a liquid ticker (NEM) + a thin one (AEM): buckets, tiers, readable cards.

---

# PHASE 2 — Add GDX/GDXJ as liquid vehicles in the browse
*Emanuel: "GDX and GDXJ is a great addition." They're broad, liquid gold-down/up bets — include them as first-class rows in the same lab, not as an auto-hedger.*

### P2.1 — Ingest GDX/GDXJ **option chains** (blocker fix — they aren't cached today)
Today options ingestion fetches only universe tickers; GDX/GDXJ are pulled as **price** benchmarks, not option chains (`has_GDX=False` in the manifest). Extend `ingestion/options_phase.py` so **GDX & GDXJ option chains are fetched and persisted like universe tickers**, and **recorded in the latest options manifest + the run replay manifest** (auditability). Per-ticker error isolation. Tests with a fixture ETF chain.

### P2.2 — Surface GDX/GDXJ in the lab + measure their liquidity
Run the Phase-1 engine on GDX/GDXJ; they appear as rows in the browse with the same tiers/buckets. Report their median relative spread/OI/volume/depth vs the miners (informational — confirms they're the liquid broad-bet vehicles).
→ folds into the lab; no separate hedge calculator.
**Acceptance:** GDX/GDXJ appear as normal, sensible+liquid rows; their option chains are cached + in the manifest; their liquidity is visible alongside the miners.

---

# OUT OF SCOPE of this brief (separate, already-planned)
- **The cross-stock "best names to buy puts on" blended ranking** (down-beta + fragility + cheapness, liquidity-gated) = the **Candidate Finder** (`claude_candidate_finder_plan_v2.md`). The Option tab feeds it; it ranks *which* names to bet against. Build separately.
- **The portfolio tool** (load the IBKR book, show the user's rough gold exposure **as context** so *they* decide how much to bet — **no prescription**) = a separate future milestone. The shared portfolio loader (IBKR CSV → mapped, currency-normalized holdings, with same-company-multi-listing consolidation) belongs there.
- **The refresh button** (background-job + status page).
- **Auto-hedge-sizing of any kind** — removed per Emanuel's decision; the user always decides the amount.
- Vol-surface model; recommendation language; public put-call "signal"; the refuted "illiquid options earn 3.4%/2.5% daily" claim; presenting index/earnings retail stats as miner-specific.

---

# Self-review gate (after each step; deeper at checkpoints)
Read your diff hunk-by-hunk (scoped files only); `pytest -q` green, count ≥ baseline + new; verify acceptance; confirm **only sensible+liquid contracts are ever suggested** (junk → "no sensible liquid contract"); confirm the engine preserves the strict quote gates; confirm `is_usable_candidate` is the single shared primitive; confirm spread-dominant scoring + no recommendation language; confirm the UI never implies live quotes or prescribes a hedge amount. Fix, commit, log, continue.

# Done =
Phase 1 ships the readable, tiered, **sensible+liquid** single-stock put/call lab through Checkpoint 1; Phase 2 ingests GDX/GDXJ option chains and surfaces them as liquid rows; the shared `is_usable_candidate` primitive is built once; full suite green; completion report written. The Candidate Finder, the portfolio tool, and the refresh button remain separate milestones.
