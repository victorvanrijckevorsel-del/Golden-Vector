# Codex Build Brief — Options Liquidity & Scenario Lab (Jobs 1 + 2)

**For:** Codex
**From:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Supersedes:** the in-flight Option Trading clarity *patch* (the M1 work graded NEEDS CHANGES). This is the research-backed redesign that replaces it.
**Source docs (read first, full rationale lives there):**
- `reviews/codex/codex_review_and_improved_option_selection_plan.md` (your staged plan — the base)
- `reviews/codex/claude_improve_option_selection_plan_gdx_and_portfolio.md` (GDX two-roles + portfolio hedge + answers to your 8 questions)
- `reviews/codex/research_option_selection_liquidity_and_design.md` (the cited evidence)
- `reviews/codex/codex_review_option_trading_clarity_m1.md` (the diagnosis)
- `data/manual/portfolio/` (the REAL portfolio + README — drives Job 2)

## How to work
Build continuously to completion — **deep self-review after every step, deeper holistic review at each checkpoint** (logged in `reviews/codex/codex_options_lab_progress.md`). **Do not stop and wait** except at the one explicit decision gate (Step 0) and the two checkpoints. One commit per step + a self-review-fixes commit per milestone. **No `git push`.** No live data in tests. Pre-flight: confirm branch `dev-vic`, `pytest -q` baseline.

## Two jobs, one engine
- **Job 1 — single-stock option selection** for the *optionable* (mostly US-listed) universe (NEM, AEM…): speculation surface + any held optionable names.
- **Job 2 — portfolio gold-downside hedge** via the liquid GDX/GDXJ proxy: this is what serves Emanuel's real (mostly optionless, foreign) portfolio.
Both stand on the same **liquidity engine** (Milestone B). Build it once.

## Locked decisions (do not re-litigate)
- **Three tiers, not a binary gate:** Tradable / Watch-expensive / No-trade.
- **Multiple buckets per horizon**, not one pick. **No recommendation language** ("best/recommended/should buy" forbidden).
- **Relative bid-ask spread is the dominant liquidity metric**; volume is a tiebreaker only (high volume can mean *wider* spreads).
- **`Last` is informational, never executable**; always show live bid/ask + spread. **yfinance = screening only** (label the tool so).
- **GDX/GDXJ liquidity must be measured (Step 0), never asserted.**
- **Descriptive, not predictive**; surface "you may overpay" / "lottery" / "options are expensive on average" honestly.

---

## STEP 0 — Measure GDX/GDXJ option liquidity vs the miners (DECISION GATE)
The whole GDX proxy/portfolio-hedge direction rests on "GDX/GDXJ options are materially more liquid than single-name miner options." **Prove it from our cached chains before building on it.**
1. Confirm GDX/GDXJ **option chains** are cached (not just price history). If they're only fetched as price benchmarks, note what's needed to ingest their chains.
2. If cached, run the (about-to-be-built, or a quick inline) liquidity scan on GDX/GDXJ and on the miners; compare **median relative spread, OI, volume, near-spot two-sided depth**.
3. **Report findings in the progress log.** 
   - If GDX/GDXJ chains are **absent** OR **not materially more liquid** → **STOP and report**; Job 2 (portfolio hedge) needs rethinking before coding.
   - If confirmed more liquid → continue.
*(This is the one place to halt for a decision. Everything else runs continuously.)*

---

## MILESTONE A — Immediate UI cleanup (quick)
Absorb anything worth keeping from the current patch, then:
- Remove the long explanatory paragraphs from the overview and ticker detail; keep ONE compact note: `Cached options snapshot: <date>. Last prices may differ from live; screening only.`
- Collapse method/caveats into a `Method` disclosure.
- Make the current candidate table not-broken (reduce columns) as a stopgap until D.
**Acceptance:** no wall of text before the table; stock price + snapshot date visible; no selection-logic changes.

## MILESTONE B — Chain scanner + liquidity engine (the keystone)
Pure, testable engine over every contract. New structures (view-model layer, not raw analytics): `OptionContractMetrics`, `OptionLiquidityTier`, `OptionChainScan`.

**Per-contract metrics:** bid, ask, mid, last, `rel_spread=(ask-bid)/mid`, `half_spread_cost_pct = (rel_spread/2)`, moneyness + label, delta, OI, volume, premium_pct_spot, IV, quote-quality flags, `liquidity_score`, `liquidity_tier`.

**Tiers (config-driven starting values; tune from the Step-0 data):**
| Tier | Rule |
|---|---|
| **Tradable** | bid>0, ask>0, `rel_spread ≤ 0.20`, OI≥1, mid≥`0.15` |
| **Watch / expensive** | bid>0, ask>0, `rel_spread ≤ 0.50`, OI≥1 |
| **No-trade** | no two-sided quote, `rel_spread > 0.50`, or invalid price |

**Liquidity score (0–1) — spread-dominant, volume minimal (per the research):**
```
spread_score  = clamp(1 - rel_spread / watch_spread_cap, 0, 1)
oi_score      = min(log1p(open_interest) / log1p(oi_cap), 1)
premium_score = 1 if mid >= min_premium else mid / min_premium
depth_score   = near_spot_two_sided_count / target_depth_count   (cap 1)
volume_score  = min(log1p(volume) / log1p(volume_cap), 1)
liquidity_score = 0.55*spread_score + 0.25*oi_score + 0.10*premium_score
                + 0.05*depth_score + 0.05*volume_score
```
(Volume never rescues a bad spread; it only breaks ties — this is the Q4 answer.)

**The shared "usable candidate" primitive lives here** — `is_usable_candidate()` = Tradable-tier + bucket-fit. The Candidate Finder's side-aware filter will call THIS exact function (one definition, no drift).

**Acceptance:** tests cover zero bid/ask, huge spread, stale/missing last, sub-min premium, high-OI-but-wide-spread; a diagnostic CLI/report prints a per-ticker liquidity summary; no UI redesign yet.

## MILESTONE C — Per-side/horizon buckets (Job 1)
**DTE bands (config; select a real listed expiry in-band, prefer monthlies):**
| Label | Band | UI stance |
|---|---|---|
| 30d | 21–45 | Tactical / high time-decay |
| 60d | 46–75 | Default near-term |
| 90d | 76–105 | Default standard |
| 120d | 106–150 | Slower thesis |

**Buckets per side × horizon** (each renders "No usable contract" + best near-miss behind an expander if none qualifies):
| Bucket | Rule |
|---|---|
| Most liquid | highest `liquidity_score` in band + sensible moneyness |
| Near-ATM | smallest \|moneyness\| among Tradable/Watch |
| Directional (call) | call delta 0.35–0.50 |
| Directional (put) | put delta −0.50 to −0.35 |
| Tail put | put delta −0.30 to −0.15 |
| Model-fit | strike nearest modeled stock price (`beta × gold% → price`), then best liquidity |
Calls and puts use **different defaults** (research-backed). Mark one **"Model fit"** when it also passes liquidity. Flag **"lottery"** when short-dated + deep-OTM + high-IV.
**Acceptance:** each horizon shows ≥1 bucket; 30d labeled tactical; AEM-like strike-50 can't be a normal candidate; liquid NEM-like contracts stay visible; wide-spread near-spot contracts show as Watch (not invisible).

## MILESTONE D — Readable UI (replace the 19-column table)
Header strip (ticker, stock price, snapshot date, source, refresh placeholder) → liquidity summary (put/call Tradable/Watch/No-trade counts; "single-name options look thin" warning when most buckets fail) → put/call tabs → **horizon cards** (compact rows: bucket, expiry, strike, moneyness, bid/ask/mid, spread%, **half-spread cost %**, OI, volume, tier, select) → expandable detail (delta, IV, Yahoo chain link, why accepted/rejected, stale/zero-quote note) → scenario calculator (only after a contract is selected). Add the **beginner glossary** (Last/Bid/Ask/Mid/IV per the research doc) + the **"options are expensive on average / you can be right on direction and still lose"** disclosure.
**Acceptance:** no wrapped unreadable rows; tiers visible at a glance; "too thin" is obvious; calculator uses the selected bucket.
→ **CHECKPOINT 1: STOP & report.** Paste a sample ticker (liquid, e.g. NEM) and a thin one (e.g. AEM) showing buckets + tiers + the readable cards.

## MILESTONE E.5 — Per-name GDX proxy (GDX Role A)
For an optionable-but-thin (or non-optionable) single name: offer the GDX/GDXJ option expressing the same directional gold view, **only if Step 0 confirmed the proxy is more liquid**, with **basis-risk language** ("expresses the sector, not this specific miner"). If GDX chains unavailable → "proxy unavailable until options refresh includes ETFs."

## MILESTONE G — Portfolio gold-downside hedge (Job 2 — the one that serves the real book)
Reuses `hedge/portfolio_totals.py` + `hedge/proxy_hedge.py` + the Milestone-B engine.
1. **Portfolio loader (shared foundation):** parse `data/manual/portfolio/ibkr_positions_20260602.csv` into the existing `Holding` model; normalize AUD/CAD/GBP → USD using the FX we already fetch. (v1 may instead map the CSV into `holdings.yaml`; auto-parse is the goal — your call, simpler v1 acceptable.) Build this in `hedge/holdings.py`, not a one-off — it's reused by the Candidate Finder and Tool C/D.
2. **Aggregate gold exposure:** `portfolio_gold_downside(gold%) = Σ position_value_usd × down_beta(stock) × gold%`, using Tool A down-betas. **Flag positions with missing/low-confidence betas** (many micro-caps); for those, fall back to a sector/GDX beta proxy, clearly labeled.
3. **Size the hedge:** translate modeled portfolio loss at gold −10%/−20% into a target GDX/GDXJ put position (≈ portfolio gold-downside ÷ GDX-put payoff per contract at the same gold move), choosing the strike/horizon from the **Milestone-C buckets** so the hedge is actually tradeable.
4. **Surface caveats honestly:** **basis risk** (GDX = large US miners; portfolio = small foreign miners → beta dispersion estimate), **FX** (GBP/AUD/CAD vs USD), the overpaying/expensive disclosures.
**Output (plain English):** *"Your ~£271k gold-miner portfolio has est. gold-down-beta ~X. Gold −10% → modeled loss ≈ £Y. Rough hedge: ~N GDX <strike> <expiry> puts (≈£Z, ~W% of portfolio). Caveats: GDX tracks large US miners not your small foreign names (basis risk); USD vs GBP/AUD/CAD (FX)."*
**Acceptance:** loads the real portfolio; computes aggregate gold-downside; sizes a tradeable GDX/GDXJ put; basis + FX caveats visible; missing-beta positions flagged + proxied.
→ **CHECKPOINT 2: STOP & report.** Paste the portfolio hedge output against the real CSV + the liquidity comparison from Step 0.

## MILESTONE F — Refresh button (SEPARATE — do NOT build here)
Out of scope for this brief. Needs a background-job + status-page design (synchronous will time out). Its own plan later.

---

## Self-review gate (after every step; deeper at checkpoints)
Read your diff hunk-by-hunk (scoped files only); `pytest -q` green, count ≥ baseline + new; verify the step's acceptance; for UI, confirm the honesty disclosures + glossary render; confirm the **`is_usable_candidate` primitive is the single shared one**; confirm spread-dominant scoring (volume not over-weighted); confirm no recommendation language. Fix, commit, log, continue.

## Out of scope / don'ts
- The refresh button (Milestone F — separate plan).
- A volatility-surface model (per-contract IV is correct).
- Any "best trade / recommended / should buy" language.
- A public put-call-ratio "predictive signal" (the edge is nonpublic — research-confirmed).
- Asserting GDX liquidity without the Step-0 measurement.
- Surfacing the refuted "illiquid options earn 3.4%/2.5% daily" claim, or presenting index/earnings retail stats as miner-specific.

## Done =
Step 0 measured + reported; A–D ship Job 1 (readable, tiered, bucketed, honest); E.5 + G ship Job 2 (per-name proxy + portfolio hedge) **if Step 0 confirmed GDX liquidity**; full suite green; the shared portfolio loader + `is_usable_candidate` primitive built once; completion report written; stopped at the checkpoints for review.
