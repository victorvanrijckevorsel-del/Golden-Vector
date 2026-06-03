# Claude improvement of Codex's option-selection plan — GDX/GDXJ + portfolio-level hedging

**Author:** Claude Code (Opus 4.8)
**Improves:** `codex_review_and_improved_option_selection_plan.md` (Codex's staged plan, which I endorse)
**Adds:** (1) answers to Codex's 8 review questions, (2) GDX/GDXJ as a **first-class vehicle** (two roles), (3) a **portfolio-level hedge** dimension — driven by the real portfolio at `data/manual/portfolio/`.
**Grade of Codex's plan:** strong — the three-tier (Tradable / Watch / No-trade) model, the cached-chain diagnostics, the staged milestones A–F, and the "no recommendation language" rule are all right. The additions below don't replace it; they extend it.

---

## 0. The reframing that changes the priorities (read first)
Emanuel's **actual portfolio** (`data/manual/portfolio/ibkr_positions_20260602.csv`) is ~£271k of **small/mid gold miners on ASX / LSE / TSX** (Astral, Celsius, West African, Serabi, Anglo Asian, Altyngold, Endeavour, Metals Exploration, Pan African), multi-currency (AUD/CAD/GBP).

**Almost none of these have liquid US-listed options.** Consequences:
- For **hedging this portfolio**, single-name puts are simply **not available** → the practical vehicle is a **GDX/GDXJ put (or shares/short)**, sized to the portfolio's aggregate gold exposure.
- So **GDX/GDXJ is the *primary* hedge path for the user, not a per-name fallback.** And the tool needs a **portfolio-level hedge view**, not only per-ticker selection.
- **Single-name option selection still matters** — but for the *optionable* (mostly US-listed) names in the screening universe (NEM, AEM, …), as a **speculation** surface and for users who hold those. Keep Codex's per-name buckets work; just don't assume the user can hedge *their* book with it.

So the priorities split into **two coherent jobs**, both using the same liquidity engine:
- **Job 1 (Codex's plan):** per-ticker option selection for the optionable universe (speculation + any held optionable names).
- **Job 2 (NEW):** portfolio-level gold-downside hedge via the liquid GDX/GDXJ proxy.

---

## 1. Answers to Codex's 8 review questions
1. **Spread tiers too strict/loose for miners?** Codex's own diagnostic proves a 10% gate is far too strict (only 2 puts near-spot pass). **Endorse the three tiers** (Tradable ≤20%, Watch ≤50%, No-trade >50%) as *starting* values, but make them **config-driven and tuned empirically per the cached chains** — they're an empirical line, not a law. The tier model (not a binary gate) is the single most important fix.
2. **DTE bands symmetric vs anchored to listed expiries?** **Both:** use the symmetric band (e.g. 46–75 for "60d") as the *search window*, but selection must always land on a **real listed expiry**, preferring **monthly** expiries (3rd-Friday standard monthlies are far more liquid than weeklies for thin miners). Don't synthesize a non-existent expiry.
3. **Bucket delta ranges appropriate?** Yes (research-backed): directional calls **35–50Δ** (not 25Δ lottery), directional puts **−35 to −50Δ**, tail puts **−15 to −30Δ**. Label them config-driven *conventions*, not laws (the exact thresholds are practitioner folklore per the research).
4. **Volume in score at 10% or display-only?** Research: option volume can coincide with **wider** spreads (adverse selection), so it must not be a primary rank. **Lower it to ~5% or pure tiebreaker; let OI carry "depth."** Keep spread dominant (Codex's 0.55). Never let volume rescue a bad spread.
5. **Min premium below which quote noise dominates?** ~**$0.10–$0.20**. Below that, the half-spread is a huge % of the premium. Also **surface the half-spread as a % of premium** (the De Silva ~9% finding) so cost is visible.
6. **Watch-tier selectable in the calculator?** **Yes, but with a loud "wide spread — you'll likely overpay" warning** (the illiquidity-premium finding). Let the user model it with eyes open; don't silently bless it.
7. **Show both watch and no-trade?** **Show Watch prominently; collapse No-trade behind an expander/diagnostic** (inspectable, not in the main flow). Agree with Codex.
8. **Citation cleanup?** Christoffersen et al. = *RFS* 2018; Chou et al. = *J. Futures Markets* 2011. **Do NOT surface** the refuted "illiquid options earn 3.4%/2.5% daily" claim. Retail loss/0DTE stats are **index/earnings-specific, not miner-specific** — use as guardrail rationale only. **Do not build a public put-call-ratio "signal."**

### Small refinements to Codex's plan
- Liquidity score: keep spread-dominant; trim volume to ≤5%/tiebreaker (per Q4).
- Add the **half-spread-cost-as-%-of-premium** as a first-class displayed field (the most decision-relevant cost number for a buyer).
- Min-premium gate ~$0.15 (config).

---

## 2. GDX/GDXJ as a first-class vehicle — two roles
Codex's Milestone E treats GDX/GDXJ as a per-name fallback. Promote it to a **first-class vehicle with two distinct roles**, both gated by the same "measure GDX liquidity first" step:

- **Role A — per-name proxy (Codex's E):** when a single miner's options are too thin, offer the GDX/GDXJ option that expresses the same *directional gold* view, with basis-risk language.
- **Role B — portfolio hedge (NEW, §3):** the GDX/GDXJ put as the vehicle to hedge the *whole portfolio's* gold-downside. This is the role that actually matters for Emanuel's real (optionless) holdings.

**Prerequisite (unchanged):** include GDX/GDXJ in the options refresh, run the same liquidity scan, and **only recommend the proxy when its measured liquidity is materially better** than the single-name alternative. If GDX/GDXJ chains aren't cached → "proxy unavailable until options refresh includes ETFs." Never assert ETF liquidity without the measurement.

---

## 3. NEW milestone — Portfolio-level gold-downside hedge
**Goal:** answer "if gold drops 10–20%, how much does my *whole portfolio* lose, and what GDX/GDXJ put (which strike/horizon, how many contracts) hedges that?" — for a portfolio that is mostly un-optionable single names.

**It reuses code we already built:**
- `hedge/portfolio_totals.py` — portfolio downside per gold scenario + hedge-cost sizing (already handles both shares and dollar-exposure holdings).
- `hedge/proxy_hedge.py` — maps non-optionable names to optionable proxies (the GDX/GDXJ idea, already conceptually present).
- The new **liquidity/bucket engine** (Codex's B/C) — to pick the *actual* GDX put (real, liquid, sensible strike) rather than a notional one.

**The flow:**
1. **Load the portfolio** (from `data/manual/portfolio/` — start by parsing the IBKR CSV into the existing `Holding` model; positions in AUD/CAD/GBP → normalize to USD using the FX we already fetch).
2. **Aggregate gold exposure:** `portfolio_gold_downside(gold_pct) = Σ position_value_usd × down_beta(stock) × gold_pct`, using Tool A down-betas (and flag positions whose beta is missing/low-confidence — many micro-caps will be).
3. **Size the hedge:** translate the portfolio's modeled £/£ loss at gold −10%/−20% into a **target GDX/GDXJ put position** — number of contracts ≈ (portfolio gold-downside £ ÷ GDX-put payoff per contract under the same gold move), choosing the strike/horizon from the **liquid-candidate buckets** (§Codex C) so the hedge is actually tradeable.
4. **Show the honest caveats:**
   - **Basis risk (big here):** GDX = large US-ish miners; the portfolio = small foreign miners → their gold-betas and idiosyncratic moves differ. Surface a basis-risk estimate (beta dispersion) so the user knows the hedge is approximate.
   - **Currency:** portfolio in GBP/AUD/CAD, GDX put in USD → FX adds tracking error. Flag it; don't over-engineer a multi-currency option model in v1.
   - **The "options are expensive on average / you may overpay" disclosures** still apply.

**Output (plain English):** *"Your ~£271k gold-miner portfolio has an estimated gold-down-beta of ~X. If gold falls 10%, modeled loss ≈ £Y. A rough hedge: ~N GDX <strike> <expiry> puts (cost ≈ £Z, ~W% of the portfolio). Caveats: GDX tracks large US miners, not your small foreign names (basis risk); USD vs your GBP/AUD/CAD (FX risk)."*

---

## 4. Updated milestone sequence
Keep Codex's A–F, insert the portfolio hedge after the proxy measurement:
- **A** — UI cleanup (quick).
- **B** — chain scanner + liquidity metrics/tiers (the shared engine).
- **C** — per-side/horizon **buckets** (Job 1; the optionable universe).
- **D** — readable horizon-card UI.
- **E** — **measure GDX/GDXJ liquidity** (prerequisite for both proxy roles).
- **E.5 (NEW)** — **per-name proxy** (Role A): "this name's options are thin → GDX equivalent."
- **G (NEW)** — **Portfolio hedge view** (Role B, §3): load the real portfolio, aggregate gold exposure, size a GDX/GDXJ put hedge, show basis/FX caveats. *(This is the piece that serves Emanuel's actual book.)*
- **F** — refresh button (separate, as Codex says).

*(Job 1 = single-stock selection ships in C/D for the optionable universe. Job 2 = portfolio hedge ships in G. Both stand on B + E.)*

---

## 5. How this connects to the future "portfolio tool" (holistic)
You flagged wanting a broader portfolio tool later. This milestone is the **first concrete piece** of it: it turns the IBKR CSV into a live `Holding` set, computes the portfolio's aggregate gold sensitivity, and produces a hedge. The same portfolio model then feeds:
- **Candidate Finder** (screen *your holdings* vs the universe),
- **Tool C/D** (which of your holdings are most downside-exposed / most fragile),
- a future **"what changed since last visit"** portfolio monitor.

So loading the portfolio (§3 step 1) is a **shared foundation** — build the portfolio loader once, reuse it everywhere. Recommend it lives in `hedge/holdings.py` (extend the existing `Holding`/`load_holdings`) + a small IBKR-CSV parser, not a one-off.

---

## 6. What stays exactly as Codex proposed
The three-tier model, the staged A→D build, the liquidity-score normalization math (with my Q4 tweak), the "no recommendation language" rule, the readable horizon-card UI, the "show watch, hide no-trade behind diagnostics," and the screening-only / yfinance-labeling stance. All good — don't change them.

## 7. Open items for the build
- Confirm GDX/GDXJ get into the options ingestion (so their chains are cached for the liquidity scan + hedge sizing). They may already be fetched as benchmarks — verify they're pulled as **option chains**, not just price history.
- Decide whether the IBKR-CSV parser is v1 (auto-parse) or the user first maps it into `holdings.yaml` (simpler v1; auto-parse later).
- The portfolio's micro-caps may have **no Tool A beta** (not in the universe / too little history) — define the fallback (use a sector/GDX beta proxy for those, clearly flagged).
