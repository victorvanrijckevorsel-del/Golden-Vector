# Predictive Layer — Academic & Practitioner Research Foundation

**Author:** Claude Code (Opus 4.8). **Purpose:** ground a future "Predictive Lab" for Golden Vector (≈60 gold miners, weekly data, single user) in real research, so any predictive feature we build is defensible — not folklore. Companion to Codex's `codex_predictive_layer_and_backtest_ideas.md` and the distilled skill at `.claude/skills/predictive-models/`.

## How this was sourced (read this first — intellectual honesty)
A deep-research workflow fanned out 108 agents over 26 primary/secondary sources and extracted 125 claims, but **hit the session token limit mid-verification** — only 6 claims completed the 3-vote adversarial check before it died. So every claim below carries an explicit grounding tag:

- **`[V]`** — workflow-verified, 3-0 adversarial vote, with a source quote.
- **`[S]`** — sourced (in the fetched primary bibliography) but verification *abstained* due to the token limit (NOT refuted — content looks sound, treat as "strong but re-check before betting real money on the specific number").
- **`[F]`** — fetched and confirmed by me this session (WebFetch).
- **`[K]`** — my own domain knowledge of a canonical paper that is in the bibliography; verify the specific figure against the source before quoting it externally.

The honest headline finding (below) is itself `[V]`, so the load-bearing conclusion is solid.

---

## Area 1 — Gold price predictability: weak at short horizons, valuation-only at long ones

**Canonical work:** Erb & Harvey, *The Golden Dilemma* (Financial Analysts Journal, 2013) + update (SSRN 4807895, 2024); Baur & Lucey (2010, *Financial Review*); Chicago Fed Letter No. 464 (2021); survey ScienceDirect S1057521915001325.

- **Gold is not a reliable inflation hedge at investment horizons. `[V]`** Since 1975, realized 10-yr inflation has ≈**zero** correlation with 10-yr nominal gold returns, while gold returns correlate **~0.98** with *real-gold-price* changes. Fluctuations in the **real price of gold** (gold ÷ CPI), not inflation, drive returns. → **Do not use CPI / expected-inflation as a 1–6 month gold predictor.**
- **The real price of gold is the long-run valuation anchor. `[V]`** It averaged **~3.2** since 1975 (low 1.46 in 2001, high 8.73 in Jan 1980), and was **7.3** in 2012/2024. High real prices are followed by **below-average subsequent real returns** — but Erb & Harvey explicitly call this a **"known unknown,"** not a stable exploitable relationship. At today's ~7.3 the model-implied **10-yr** real return is negative in every specification. → A valuation signal, but **only at a ~10-year horizon**, useless for monthly trading.
- **Real interest rates are the best-documented driver — and still fragile. `[V]`/`[S]`** 10-yr TIPS vs real gold price: **−0.82** correlation (US, 1997–2012), but only **−0.31** in a longer UK sample (~9% of variance), and a plain time trend fits the US data better. Erb & Harvey: the link "may be more statistically apparent than real." Chicago Fed (2021) `[S]`: a 1pp rise in the 10-yr real rate lowers the real gold price ~**13%** in annual levels — but the regression **R² collapses from 0.87 (annual) → 0.12 (quarterly) → 0.012 (daily).** → A real-rates feature is worth having, but **regime-dependent**; macro explains **almost nothing at short horizons.**
- **ETF holdings track the price; other demand doesn't. `[V]`** 2010–2023, gold-ETF holdings had **0.74** correlation with the real gold price; jewelry, central banks, bars/coins ≈ **zero**. Authors decline to claim causality (FOMO/confounding). → ETF-flow data is the one demand series worth a feature, *as a coincident regime indicator, not a clean predictor.*
- **Hedge vs safe-haven. `[S]`** Baur & Lucey (2010): a *hedge* is uncorrelated with stocks **on average**; a *safe haven* is uncorrelated **during crashes**. Gold is both for stocks (not bonds), but the safe-haven effect is **short-lived (~15 trading days)** and disputed (Bredin et al. find up to a year; Lucey & Li find it unstable). → Reactive "fear" buying is not a durable multi-month signal.

> **Honest 1–6 month consensus:** gold short-horizon return predictability is **weak-to-negligible** from macro fundamentals. The only robust structure is (a) long-horizon valuation mean-reversion (10y), and (b) — from the broader literature — **trend/momentum** in the price itself. **Implication that reframes the whole product: do not try to predict gold. Predict *relative miner behaviour conditional on gold scenarios* — which is exactly what the dial + Tool A already set up.**

---

## Area 2 — Miners as leveraged, convex, *non-stationary* gold plays

**Canonical work:** Tufano (1996, *Journal of Finance*, hedge-book database) and Tufano (1998, JF, "The Determinants of Stock Price Exposure"); McDonald & Solnik (1977); Blose & Shieh (1995); Borenstein & Farrell (2007); Faff & Chan (1998).

- **Miners are ~2× leveraged gold — on average. `[S]`** Tufano's 1973–1994 North-American sample: average gold-price **elasticity ≈ 2** (1% gold → ~2% stock). Blose & Shieh / McDonald & Solnik: elasticity **> 1**, and **greater for high-cost miners** (thin margin = more operating leverage).
- **Exposure is convex / option-like. `[S]`** Beta is **higher when gold is lower, when gold vol is lower, and for more financially leveraged firms** — i.e. **beta rises as margin shrinks.** This is the operating-leverage view, and it directly validates Golden Vector's margin-dependent survival lines (Tool D) and up/down-beta asymmetry (Tool A).
- **Betas are NOT stable parameters. `[S]`** They vary substantially **across firms and over time.** A single static beta per miner is mis-specified. **Hedge books and diversification measurably reduce effective beta** — so a producer's hedging must be tracked (this is why Codex's hedge-book fields matter).
- **The leveraged-play is not universal. `[S]`** Faff & Chan (1998), Australian monthly 1979–1997: gold coefficient ≈ **0.75** (stocks *less* volatile than gold), and only market + gold mattered (rates/FX added nothing). → Betas differ by market, period, and cost structure — never assume "2×."
- **Beyond gold:** energy costs (diesel/power are a big AISC input), country/jurisdiction risk, and **financing/dilution risk for juniors** drive miner returns independent of gold. Selective-hedging (market-timing) ability: **little evidence** (Tufano). Managerial compensation predicts hedging intensity (options → hedge less; stock → hedge more) `[S]`.

> **Takeaway:** the repo's existing structural outputs (returns-based dynamic betas, asymmetry, margin-dependent survival) are **exactly the literature-endorsed representation** — *provided they're treated as time-varying and firm-specific, never static.* The cross-sectional miner question ("which miner outperforms given a gold move?") is far more tractable than predicting gold.

---

## Area 3 — Cross-sectional prediction in a *tiny* universe: the binding constraint

**Canonical work:** Grinold & Kahn, *Active Portfolio Management* (Fundamental Law); Buckle (2004) / "Fundamental Law Redux" (transfer coefficient); Gu, Kelly & Xiu, *Empirical Asset Pricing via Machine Learning* (RFS, 2020).

- **The Fundamental Law is the governing equation. `[K]`** Information Ratio ≈ **IC × √(Breadth) × TC**, where IC = cross-sectional rank-correlation of signal with forward return, Breadth = number of *independent* bets, TC = transfer coefficient (how cleanly the signal becomes positions). **With ~60 names, breadth is structurally low** — so even a genuinely good signal (IC ≈ 0.03–0.05, which is "good" in equities) yields a **modest** IR. This is the single most important constraint on the whole project: *we are breadth-starved, not model-starved.*
- **ML wins only with breadth we don't have. `[F]`/`[K]`** Gu-Kelly-Xiu show trees and shallow neural nets beat linear models out-of-sample — but on **~30,000 stocks**, with a monthly OOS R² of only **~0.40%** even there, and the value comes from nonlinear interactions across a huge cross-section. The most important predictors were **momentum, liquidity, and volatility** (price-derived, point-in-time-safe — good for us). **With 60 names, gradient boosting / neural nets are statistically hopeless** (too few cross-sectional observations per period to fit interactions without overfitting).
- **What *does* work small. `[K]`** Cross-sectional **z-scored ranks**, a **few** signals, **ridge / logistic regression with heavy shrinkage**, and **Bayesian / rank-based** robustness. Rank and quantile-spread methods are robust to the outliers and fat tails that dominate a 60-name miner cross-section.

> **Takeaway:** the model choice is essentially decided by statistics, not taste: **simple ranks + shrunk linear, evaluated by IC and top-vs-bottom quantile spread. No ML.** Effort should go into finding a *few high-IC, orthogonal* signals — not into model complexity. Codex's "Model 1 transparent rank → Model 2 regularized regression, avoid neural nets" sequence is exactly right and now has a citation.

---

## Area 4 — Backtest validity: the discipline matters more than the model

**Canonical work:** López de Prado, *Advances in Financial Machine Learning* (2018); Bailey & López de Prado, *Deflated Sharpe Ratio* + *Probability of Backtest Overfitting* (CSCV); Harvey, Liu & Zhu (RFS, 2016); White's Reality Check (2000) / Hansen SPA (2005).

- **Overlapping forward-return labels leak. `[K]`** A 120-day forward return on weekly data means consecutive rows share most of their label window. Naive K-fold CV therefore trains on the future. Fix: **walk-forward** + **purged K-fold with an embargo** (drop training rows whose label window overlaps the test set, plus an embargo gap). Never shuffle time-series rows.
- **Deflate the Sharpe. `[F]`** The **Deflated Sharpe Ratio** (Bailey & López de Prado) corrects an observed Sharpe for **(1) the number of strategies/variants tried, (2) skew & excess kurtosis, (3) track-record length** — backtested Sharpes are "systematically inflated and often meaningless without adjustment for the number of strategies tested." **PBO via CSCV** quantifies the probability a winning backtest is luck; the **Minimum Track-Record Length** says how much history is needed to trust a given Sharpe.
- **Raise the significance bar. `[K]`** Harvey-Liu-Zhu: after decades of factor mining, a newly "discovered" signal needs a **t-stat > ~3.0**, not 2.0 — most published factors are probably false positives. White/Hansen formalize testing the *best* strategy against the *universe of strategies tried* to control data-snooping.
- **The classic biases, all live for us. `[K]`** Look-ahead; **survivorship** (delisted/acquired miners — *gold juniors die*; excluding them fabricates alpha); **point-in-time fundamentals** (restatements + reporting lag — today's AISC ≠ what we knew in 2022); and **transaction-cost realism** (small illiquid miners have wide spreads + market impact — a paper edge evaporates after costs).

> **Takeaway:** build the **backtest engine first**, and make its guardrails non-negotiable: walk-forward, purge+embargo, a survivorship-complete universe (including dead miners), realistic costs, and **report a Deflated Sharpe + the number of variants tried** on every result. This is Codex's "rigorous backtest engine before any model" instinct, now with the exact standards attached.

---

## Area 5 — Probabilistic outputs: calibrated frequencies, not point targets

**Canonical work:** Romano, Patterson & Candès, *Conformalized Quantile Regression* (NeurIPS, 2019); Gneiting & Raftery on proper scoring; Spiegelhalter on uncertainty communication (e.g. *Visualizing Uncertainty About the Future*, Science 2011).

- **A "61% outperform" claim is only meaningful if calibrated. `[K]`** Calibration = when you say 61%, it happens ~61% of the time. Measure it with the **Brier score** and **reliability diagrams**, tracked over time. An uncalibrated probability is worse than a hedge ("uncertain").
- **Give ranges, via quantile regression / prediction intervals. `[K]`**
- **Conformal intervals come with a catch we must respect. `[F]`** Conformalized Quantile Regression gives a **distribution-free, finite-sample coverage guarantee** and **adapts interval width to local uncertainty** — *but it assumes **exchangeability**, which **time-series/financial data violates.*** So off-the-shelf conformal coverage is **not** guaranteed here; we'd need time-series/block-conformal variants and must treat coverage as **approximate, monitored empirically.** (This is the kind of false-rigor trap to flag loudly in the UI.)
- **Communicate as expected frequencies. `[K]`** Spiegelhalter's evidence: lay audiences understand **"X out of 100"** framing far better than abstract probabilities; show **ranges**, attach **sample size**, and **avoid false precision** (no "$220 price target").

> **Takeaway:** the live output should be a **calibrated base-rate frequency with a sample size and an interval** — "in **N** past setups like this, **X**/100 beat GDX over 120d; median alpha +M%, 10–90% range A–B" — and a **calibration scorecard** the user can see. Never a point target. Conformal intervals are usable but only with the exchangeability caveat surfaced.

---

## One page — what this means for our build order

The literature **strongly endorses Codex's cautious sequence** and sharpens it with four hard constraints:

1. **Reframe the product. `[V]`-grounded.** Don't predict gold (short-horizon macro predictability ≈ 0). Predict **relative, cross-sectional miner behaviour conditional on gold scenarios** — which the gold dial + Tool A betas already set up. The product question is "which miners win/break when gold moves," not "where is gold going."
2. **Engine before model.** Build the walk-forward backtester with purge+embargo, a **survivorship-complete** universe (dead miners included), realistic costs, and a **Deflated-Sharpe + variant-count** report — *before* any predictive model. The discipline is the moat.
3. **Statistics dictate simple models.** ~60 names = low breadth (Fundamental Law) = **ranks + heavily-shrunk linear/logistic only. No tree ensembles, no neural nets.** Gate everything on **IC, quantile-spread, and a t>3 / Deflated-Sharpe** bar against naive baselines (equal-weight, up-beta-only, low-AISC-only).
4. **Outputs are calibrated frequencies.** Base-rate "X out of 100" with sample size + interval + a live calibration scorecard. Conformal intervals only with the time-series exchangeability caveat shown.

**Backtestable now** (point-in-time-safe, price-derived): Tool A structural betas/asymmetry, forward returns & alpha-vs-GDX, gold up/down regime labels, simple rank models. **Needs history first** (start collecting, never fabricate): Tool B fundamentals (restatement+PIT), Tool D resilience, option signals, hedge books.

**The deepest insight from the literature:** miner gold exposure is **convex, firm-specific, time-varying, and hedge-dependent** — so the highest-value predictive features are not "is this miner cheap" but **"how does this miner's *effective, current* gold sensitivity differ from its naive historical beta, and does that gap predict behaviour in the next gold move?"** That is a genuinely under-exploited, literature-grounded angle the idea pass below develops.

### Bibliography (26 primary/secondary sources from the research run)
Erb & Harvey 2013/2024 (SSRN 2078535, 4807895) · Baur & Lucey 2010 (Financial Review) · survey S1057521915001325 · Chicago Fed Letter 464 (2021) · Tufano 1996/1998 (JF; 0022-1082.00042, j.1540-6261.1996.tb04064.x) · RFE 2014 · S0301420720309211 · S0278425417300704 · Gu-Kelly-Xiu 2020 (RFS 33/5/2223) · Grinold-Kahn Fundamental Law + Redux (ResearchGate) · Harvey-Liu-Zhu 2016 (RFS 29/1/5) · Bailey-López de Prado Deflated Sharpe (davidhbailey.com) + PBO (GARP) · Romano-Patterson-Candès 2019 (NeurIPS, conformalized QR) · Spiegelhalter risk communication · Quantpedia (secondary). Full URLs in the research-run output.
