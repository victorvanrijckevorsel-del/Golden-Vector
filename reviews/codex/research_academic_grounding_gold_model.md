# Academic grounding for the Golden Vector model

**Compiled:** 2026-06-03 (deep-research pass, adversarially verified — 24/25 claims survived 3-vote checks)
**Purpose:** check our design choices (gold beta, down-beta, downside ranking, option scenarios, AISC fragility) against the peer-reviewed literature. Verdict per area + the papers + what to keep/refine/caveat.

## TL;DR verdict
The literature **strongly supports the core architecture** and flags **two cautions** plus **two citation gaps** to close before relying on those parts.

| Our design choice | Literature verdict |
|---|---|
| Per-ticker gold beta from regressing weekly stock returns on weekly gold returns | ✅ **Validated** |
| Separate up-beta / down-beta; use downside (semi)volatility | ✅ **Theoretically sound** |
| Rank/flag by downside beta | ⚠️ **OK as a *descriptive* risk signal — NOT a return predictor** |
| Flag thin tail estimates (~15 worst-gold weeks) low-confidence | ✅✅ **Strongly validated** |
| Scenario stock move = beta × gold% at −20% | ⚠️ **Fine for small moves; approximate at extremes (miners are convex / operating-levered)** |
| Black–Scholes constant-IV for miner puts/calls | ❓ **Citation gap** — but fat-tails finding implies it understates deep-OTM puts |
| Tool D AISC margin / operating-leverage stress | ❓ **Citation gap** — but it's exactly the nonlinearity the linear model misses |

---

## 1. Miners are leveraged plays on gold — ✅ validated
- **Tufano (1998, *Journal of Finance*):** "The average mining stock moves 2 percent for each 1 percent change in gold prices, but exposures vary considerably over time and across firms." → gold beta ≈ 2 (well above 1), **and firm-specific / time-varying**.
- **Qin, Cai, Wang & Webb (2023, *J. Int. Financial Markets, Institutions & Money*):** miners are "far more sensitive to gold returns than to stock market returns," and "in their tail behavior, gold-mining stocks behave more like gold than like common stocks."
- **Erb & Harvey (2012, NBER w18706 / *FAJ* 2013), the "golden dilemma":** high real gold prices historically implied ≈ −10%/yr real returns over 10y — but explicitly a "known unknown."
- **Design note:** our weekly-regression gold beta is well-founded; estimating **live, per-firm** betas (not one fixed 2×) matches the evidence. **Do not hard-code a directional gold view** (Erb–Harvey: the forecast is uncertain).

## 2. Up/down-beta + semivariance — ✅ sound theory, ⚠️ not a return predictor
- **Bawa & Lindenberg (1977, *JFE*):** a distribution-free downside (mean-lower-partial-moment) CAPM that **nests the standard CAPM** — so the downside framework "does at least as well" in-sample.
- **Estrada (2002, *Emerging Markets Review*) D-CAPM:** downside beta = cosemivariance / market semivariance, computed as the **slope of a no-constant regression of downside-truncated stock returns on downside-truncated gold/market returns**. Explained emerging-market returns better than plain beta (R²=0.55).
- **What WE actually compute (audit-confirmed):** our `down_beta_core` is a **split-sample conditional beta** — the slope of an ordinary OLS-*with-intercept* regression of weekly stock returns on weekly gold returns, run over the subset of weeks where **gold fell** (`golden_vector/model/structural.py`). This is *not* Estrada's no-constant truncated formula, nor Ang-Chen-Xing's "condition on gold < mean." It is a legitimate, intuitive descriptive measure ("per 1% gold move, how much did the stock move during down weeks") — but **we must label it as a split-sample conditional beta, not as D-CAPM / Estrada.** Recommendation: keep it (tested, intuitive) + document the exact formula + add a formula contract test.
- **⚠️ CAUTION — the down-beta *return premium* is fragile:** **Atilgan, Demirtas & Gunaydin (2020, *European Financial Management*)** — the premium "doesn't hold after value-weighting or controlling for return determinants," and vanishes with bigger samples / more exchanges. **Levi, Welch & Karolyi (2020, *Review of Financial Studies*)** — "plain market beta is the better predictor, even for crashes… down-betas are useful for neither hedging nor risk-pricing."
- **Design note:** keep down-beta as a **descriptive ranking signal** ("how this miner behaved when gold fell"), **not** a claim that high-down-beta miners earn more. **Show plain beta alongside down-beta** and label the ranking "descriptive risk, not a return forecast." This *reinforces* our existing "show the data, don't issue verdicts" philosophy.

## 3. Thin-tail estimates from ~15 worst weeks — ✅✅ strongly validated
- **Yamai & Yoshiba (2002, via BIS):** Expected-Shortfall-style averages "need a larger sample than VaR for the same accuracy."
- **Pitera & Schmidt (arXiv:2010.09937):** plug-in tail estimators are **biased toward *underestimating* risk** "especially in small sample cases."
- **Barendse, Kole & van Dijk (2023, *J. Financial Econometrics*):** ignoring estimation error inflates false-rejection rates massively (up to 53% vs nominal 5%).
- **EVT literature (Resources Policy / classic):** averaging only the worst ~15 weeks is the **statistically wasteful** "block-of-extremes" approach; **peaks-over-threshold / Generalized Pareto** uses all data above a high threshold and is more reliable.
- **BIS CGFS:** normal-distribution tail formulas **understate** extreme moves (fat tails) — prefer empirical/historical tail measures.
- **Design note:** our decision to **flag the ~15-week tail metrics low-confidence and keep them out of the headline rank is exactly right** — that's the small-sample, deep-tail regime where estimates are unstable *and* biased to understate risk. *(Optional future upgrade: a peaks-over-threshold / GPD tail estimate instead of the simple average. Not required — the flagged average is acceptable for decision support.)*

## 4. Linear `beta × gold%` for large moves — ⚠️ approximate at extremes
- **Shahzad, Rahman, Lucey & Uddin (2021, *Resources Policy*):** miners carry an **embedded real option in gold** that is "time-varying" — i.e. **convex / nonlinear**, consistent with operating leverage.
- A stronger claim that beta literally **flips sign across quantiles** was **refuted** in verification (1–2 votes) — so do **not** assume the relationship reverses.
- **Design note:** scaling the option scenarios as `beta × gold%` is fine for small moves; for −15%/−20% **label results "approximate (linear factor model)"** and note that **operating leverage can make the real downside *worse* than linear beta implies**. That downside amplifier is precisely what **Tool D (AISC margin stress)** is built to capture — so the linear option model and Tool D are complementary, not redundant.

## 5. Black–Scholes constant-IV — ❓ citation gap (but partially implied)
- **No primary source was adversarially verified in this batch** on volatility skew/smile. However the **fat-tails finding (BIS)** implies lognormal/constant-IV BS **understates deep out-of-the-money put values** (the empirical volatility skew). Real markets price downside puts richer than a single-IV BS model.
- **Leads fetched but not yet verified** (worth a follow-up pass): Rubinstein (1994, *J. Finance*, "Implied Binomial Trees"); Dumas, Fleming & Whaley (1997, *J. Finance*, "Implied Volatility Functions"); Hull et al. (skew modeling).
- **Design note:** our existing "constant-IV v1 limitation" label is the right call. Where we use **market-quoted IV per listed contract** (the candidate's own IV), we partially absorb the skew already. Keep the caveat; don't claim BS is exact for deep-OTM strikes.

## 6. AISC / operating leverage / producer break-even — ❓ citation gap
- **No adversarially-verified primary source** in this batch quantified producer EBITDA sensitivity to a 10–20% gold drop.
- **Leads fetched but not yet verified:** Baranowski & Pera (mining margins, *journals.pan.pl*); World Gold Council "Higher gold price eases pressure on producer margins" (2024); an operating-leverage/AISC industry piece. Classic academic anchors to chase: the **World Gold Council AISC standard**, and elasticity/leverage work (e.g., Blose & Shieh; Twite 2002).
- **Design note:** the **economic logic of Tool D is sound** (margin = gold − AISC; fixed costs ⇒ operating leverage ⇒ EBITDA falls faster than gold), and §4 above shows it captures the very nonlinearity the linear option model misses. But **calibrate/cite it separately** before treating its stress numbers as authoritative — run a focused research pass on AISC elasticity.

---

## Concrete plan refinements this suggests
1. **Tool C (plan v3):** show **plain/symmetric beta next to down-beta**, and label the downside ranking **"descriptive risk, not a return forecast"** (Atilgan 2020; Levi–Welch–Karolyi 2020). Optionally verify our `down_beta_core` matches Estrada's no-constant truncated-regression definition.
2. **Option scenarios (shipped):** add an **"approximate at extremes"** note to the −15/−20% rows; state that operating leverage may worsen downside beyond linear beta (cross-link to Tool D).
3. **Tail metrics (plan v3):** our low-confidence flagging is validated; note **GPD/peaks-over-threshold** as a possible future upgrade.
4. **Close the two citation gaps** with a follow-up research pass before relying on (a) the BS-skew magnitude and (b) AISC/operating-leverage elasticity.

## Open questions flagged by the research
- Should the composite down-rank **down-weight down-beta vs plain beta**, or just show both with the "descriptive" label? *(Lean: show both, descriptive label.)*
- Upgrade the tail metric to **GPD** or keep the flagged average? *(Lean: keep flagged average for v1.)*
- Quantify BS-skew distortion across −20%..+20% — needs a dedicated source.
- Calibrate AISC/EBITDA elasticity from industry data — needs a dedicated source.

## Source list (all primary/peer-reviewed unless noted)
- Tufano 1998, *J. Finance* — gold beta of miners
- Qin, Cai, Wang & Webb 2023, *JIFMIM* — miners' gold vs market sensitivity & tails
- Erb & Harvey 2012, NBER w18706 / *FAJ* 2013 — the golden dilemma
- Bawa & Lindenberg 1977, *JFE* — downside CAPM
- Estrada 2002, *Emerging Markets Review* — D-CAPM / downside beta recipe
- Atilgan, Demirtas & Gunaydin 2020, *European Financial Management* — down-beta premium fragility
- Levi, Welch & Karolyi 2020, *Review of Financial Studies* — plain beta predicts better
- Yamai & Yoshiba 2002 (BIS) — ES needs larger samples
- Pitera & Schmidt 2020, arXiv:2010.09937 — small-sample tail bias
- Barendse, Kole & van Dijk 2023, *J. Financial Econometrics* — estimation error in VaR/ES backtests
- Shahzad, Rahman, Lucey & Uddin 2021, *Resources Policy* — embedded real option in miners
- BIS CGFS (Mar 2002) — fat tails understate extremes
- *(unverified leads)* Rubinstein 1994 & Dumas-Fleming-Whaley 1997, *J. Finance* (skew); Baranowski & Pera, World Gold Council (AISC)
