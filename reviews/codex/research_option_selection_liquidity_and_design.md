# Option selection, liquidity & strike/horizon — research + design spec

**Compiled:** 2026-06-03 (deep-research pass, adversarially verified — 22/25 claims survived 3-vote checks; 3 refuted, listed below)
**Purpose:** answer "how do we pick a LIQUID, sensible put/call on thin gold-miner chains?" and turn it into concrete, implementable design rules for the Option Trading redesign ("Options Liquidity & Scenario Lab"). Pairs with `codex_review_option_trading_clarity_m1.md`.

## TL;DR — five design decisions the evidence supports
1. **Don't pick one rigid strike** — show **multiple candidate buckets per horizon**, defaulting beginners to **near-ATM / 35-50 delta** directional contracts, *away* from short-dated deep-OTM "lottery" contracts (they structurally lose money).
2. **Relative (%) bid-ask spread is the dominant liquidity metric** — make it the primary hard gate and the top weight. **High volume ≠ liquid** in options (it can mean *wider* spreads).
3. **Composite liquidity score** = relative spread (primary) + OI + both-sides-quoted + premium size + chain depth. Volume only confirms it trades.
4. **"Don't trade single-name options here — use shares or GDX/GDXJ"** is a legitimate first-class output, because thin options are **priced richer to buyers** (you overpay).
5. **yfinance is screening-only, not execution** — `last` is stale/non-executable, zero/missing bid-ask is common; treat `last` as informational, require a live bid/ask for any spread decision.

---

## Verified findings (cite → implement)

### Liquidity
- **Relative bid-ask spread is the academically-validated dominant metric** (Cao & Wei, *J. Financial Markets* 2010; Christoffersen, Goyenko, Jacobs & Karoui, *RFS* 2018). → **Primary hard gate + dominant weight:** `rel_spread = (ask − bid) / mid`.
- **Option liquidity is driven by adverse selection, not inventory → rising volume coincides with WIDER spreads** (Cao & Wei). → **Do NOT rank by volume.** Weight spread above volume; use volume/OI only to confirm a contract actually trades and quotes both sides.
- **Call vs put liquidity is direction-dependent** — call spreads narrow in up-markets, put spreads narrow in down-markets (Cao & Wei). → Legitimate basis to treat calls/puts **asymmetrically** with different default buckets.

### Pricing / "you overpay" on thin options
- **Illiquid single-name options are priced RICHER to buyers** — illiquidity raises the IV-curve level, concentrated in **OTM / long-dated on low-liquidity stocks** = exactly miners (Chou, Hsiao, Wang & Chung, *J. Futures Markets* 2011; Christoffersen et al. *RFS* 2018). → **Surface a "you are likely overpaying" warning** when spread is wide / OI thin; make "don't trade" first-class.
- **Demand pressure inflates option prices & the smirk; extends to single stocks** (Garleanu, Pedersen & Poteshman, *RFS* 2009). → Flag OTM puts as often demand-inflated; steer to shares/ETF. *(Caveat: headline result is index options; single-stock is the weaker leg.)*

### Retail behavior → guardrails (why a beginner tool must steer)
- **Retail option BUYERS systematically lose 5-9% (10-14% around earnings)** — overpay vs realized vol, pay huge spreads (~9% from the half-spread alone), and hold too long (De Silva, Smith & So, *Review of Finance* 2026). → **Show net-of-spread economics; warn against passive hold-to-expiry.**
- **Retail concentrates in very short-dated contracts** (median maturity 4 days→1 day 2020-22; ~75% of retail S&P 500 trades are 0DTE) (Bogousslavsky & Muravyev, *JFE*; Beckmeyer et al.). → **Don't default beginners to short-dated.** Default ~**60-90 DTE**; mark **<30 DTE "tactical only" + theta warning**.
- **Most retail trades are ATM/slightly-OTM (mean call moneyness 0.96), and lottery/skew-seeking does NOT produce profits** (Bogousslavsky & Muravyev). → **Default directional calls to ~35-50 delta (near-ATM), not 25-delta lottery.**
- **High-gambling/high-retail-proportion traders chase OTM + short + high-IV and pay a "lottery premium" (higher IV, worse returns)** (Choy, *J. Banking & Finance* 2015; Flynn, Liu & Popova, *J. Financial Markets* 2026). → **Flag short-dated + deep-OTM + high-IV as a "lottery" contract** with a higher-expected-loss warning, not a normal pick.
- **Option order flow predicts returns — but from NONPUBLIC dealer flow, not yfinance volume** (Pan & Poteshman, *RFS* 2006). → **Do NOT build a public put-call-ratio "signal" and present it as predictive.** Use only as background for why option markets are adverse-selected (→ the spread).

### Data quality
- **yfinance is adequate only for rough screening** — stale `last`, zero/missing bid-ask; real spread/quote work needs an **OPRA feed (Cboe DataShop EOD: NBBO bid/ask + sizes)** (Cboe DataShop). → Use yfinance first-pass; **treat `last` as informational only, never executable**; require a live bid/ask before any spread-based liquidity decision.

---

## Concrete design rules (research → implementation)

### 1. Liquidity score + hard gates
```
rel_spread = (ask − bid) / mid                      # PRIMARY
hard gates (reject as "no usable candidate"):
  - bid > 0 AND ask > 0           (both sides quoted)
  - rel_spread ≤ max_rel_spread   (config, start ~0.10–0.20; tune per F-below)
  - open_interest ≥ min_oi        (config)
liquidity_score (0–100, for ranking the survivors):
  ≈ 60% × (1 − normalized rel_spread)               # spread dominates
  + 15% × normalized open_interest
  + 10% × both-sides-quoted & non-stale
  + 10% × premium-size adequacy (avoid sub-$0.10 noise)
  + 5%  × chain depth near spot
  (volume only confirms "it trades"; NOT a primary rank input)
```

### 2. Candidate buckets per horizon (not one pick)
For each side × horizon, present up to:
| Bucket | Rule |
|---|---|
| **Most liquid** | highest `liquidity_score` among sensible strikes |
| **Near-ATM (~50Δ)** | strike closest to spot with acceptable liquidity |
| **Directional (calls 35-50Δ / puts −35 to −50Δ)** | the beginner default for a directional view |
| **Hedge / tail (puts −15 to −30Δ)** | cheaper downside; label "tail" |
| **Model-fit (scenario)** | strike nearest the modeled stock price: `beta × gold% → modeled price → strike` |
Mark one **"model preferred"** if it also passes liquidity. Calls and puts use **different defaults** (calls 35-50Δ; puts offer both near-ATM directional and 15-30Δ tail).

### 3. Horizon defaults
Default to **60d / 90d**; offer 120d for slower theses; **30d labeled "Tactical / high time-decay"** with a warning, never an equal default. (DTE labels are practitioner convention — config-driven, not laws.)

### 4. When too thin → no-trade + proxy (first-class)
If no candidate passes the hard gates for a side/horizon: output **"Single-name options too thin here"** and recommend **(a) the GDX/GDXJ sector-ETF option** that expresses the same gold view, or **(b) shares**, with a **basis-risk note** ("an ETF expresses the *sector* move, not this specific miner"). This reuses our existing `proxy_hedge` mapping concept.
> **IMPORTANT (open question O-1):** the premise that GDX/GDXJ options are *materially* more liquid than single-name miner options is **intuitive but NOT directly verified** in the literature. We have the chains — **measure it ourselves** (compare GDX/GDXJ relative-spread + OI vs the miners) before asserting it. Don't ship the proxy claim as fact until we've checked our own data.

### 5. Honesty signals to surface
- **"Likely overpaying"** flag when spread wide / OI thin (illiquidity premium).
- **"Lottery contract"** flag when short-dated + deep-OTM + high-IV.
- **Net-of-spread economics** (the half-spread is a ~first-order cost) + a "don't passively hold to expiry" note.
- These reinforce the existing "options are expensive on average" disclosure (variance risk premium, prior research).

### 6. Beginner glossary (UI)
- **Last** — price of the most recent trade; *can be hours stale and is not executable*.
- **Bid** — best price a buyer will pay (what you'd get if selling).
- **Ask** — best price a seller will take (what you'd pay if buying).
- **Mid** — (Bid + Ask) / 2; a fair-value *estimate*, not a guaranteed fill.
- **IV** — the market's expected future volatility baked into the price; higher IV = more expensive option.
- **Always show the live Bid/Ask spread, not just Last.**

### 7. The organizing principle
**Scenario-anchored model-fit + buckets**, not a single delta target. Compute the modeled stock price from `beta × gold%`, pick the model-fit strike near it, AND show the liquidity-driven buckets so the user sees the tradeable landscape. Delta and moneyness are *inputs to the buckets*, not the sole selector.

---

## Honest caveats (must carry into the product)
- **Scope mismatch:** the strongest retail-behavior evidence (0DTE ~75%, lottery-seeking, 5-14% losses) is from **S&P 500 INDEX options and earnings single-names — NOT gold miners.** It justifies the guardrails but must **not** be presented as miner-specific data.
- **Practitioner folklore (config-driven, label as conventions, not laws):** the exact delta buckets (35-50 / 15-30), DTE defaults, the "theta accelerates in the final 30-45 days" rule, and — importantly — **"GDX/GDXJ options are more liquid than miner options"** (see O-1, verify ourselves).
- **Do NOT use these refuted claims:** (a) "illiquid options earn a 3.4%/2.5% daily premium" — **refuted 0-3**; (b) "retail concentrates in short-dated *calls* on meme stocks, 1-day held ~an hour" — refuted; (c) "retail predominantly buys deep-OTM for skewness" — refuted (most are ATM/slightly-OTM).
- **Don't reproduce Pan-Poteshman's predictive edge from public yfinance volume** — it's nonpublic dealer flow.
- Citation tidy: Christoffersen et al. = *RFS* 2018; Chou et al. = *J. Futures Markets* 2011.

## Open questions to resolve in our own data / next research
- **O-1:** Measure GDX/GDXJ option liquidity (relative spread, OI) vs the miners from our cached chains — confirm the proxy premise before relying on it.
- **O-2:** Concrete `max_rel_spread` / `min_oi` thresholds that best separate "tradable" from "too thin" for *commodity-producer* single-names; how they scale with premium size + horizon.
- **O-3:** Basis-risk magnitude of expressing a single-miner thesis via a GDX option (beta dispersion) — quantify for the user.
- **O-4:** Empirically supported optimal DTE for long directional buyers (beyond the 60-90d heuristic).

## Sources
Cao & Wei 2010 (*J. Financial Markets*); Christoffersen, Goyenko, Jacobs & Karoui 2018 (*RFS*); Chou, Hsiao, Wang & Chung 2011 (*J. Futures Markets*); Garleanu, Pedersen & Poteshman 2009 (*RFS*); De Silva, Smith & So 2026 (*Review of Finance*); Bogousslavsky & Muravyev (*JFE*, "An Anatomy of Retail Option Trading"); Beckmeyer, Branger & Gayda (SSRN 4404704); Choy 2015 (*J. Banking & Finance*); Flynn, Liu & Popova 2026 (*J. Financial Markets*); Pan & Poteshman 2006 (*RFS*); Cboe DataShop (OPRA EOD). Plus the prior options research (`research_options_methodology_and_predictors.md`) on per-contract IV and the variance risk premium.

---

## How this becomes the redesign plan
This spec answers Codex's M1 research brief. The next step is a build plan ("Options Liquidity & Scenario Lab") that implements: the liquidity score + hard gates (§1), the per-horizon buckets (§2), horizon defaults (§3), the **measure-GDX-first** then no-trade/proxy logic (§4 + O-1), the honesty flags (§5), the glossary (§6), and a **readable horizon-card UI** (not the 19-column table). The shared `is_usable_candidate` / liquidity-score primitive built here is the same one the Candidate Finder's side-aware filter consumes.
