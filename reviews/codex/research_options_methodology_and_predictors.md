# Options methodology check + predictive metrics + commodity-equity generalization

**Compiled:** 2026-06-03 (deep-research pass 2, adversarially verified — 23/25 claims survived 3-vote checks)
**Purpose:** (A) is our put/call volatility math correct? (B) what predictive metrics are worth adding? (C) does the "equity = option on the commodity" idea generalize beyond gold?

## TL;DR
- **(A) Our options/volatility methodology is correct** and matches academic best practice. One honesty caution: **long options are, on average, expensive** (variance risk premium) — though much milder for single stocks than for indexes.
- **(B) Add two predictive signals we *already compute*:** the **option volatility skew/smirk** (a real crash-risk predictor) and the **implied-vs-realized vol spread**. Both honest, both low-cost. The public **put-call ratio is a weak signal** — don't oversell it.
- **(C) The "commodity equity = call option on the commodity" theory is the right backbone (Brennan–Schwartz 1985)**, but the cross-commodity numbers (oil/copper/silver/uranium betas, AISC elasticity) **did not survive verification** — still an open gap to source before building a generalized fragility module.

---

## (A) Is our options / volatility method correct? — ✅ yes
**1. Using each listed contract's OWN market IV (what we do) is the endorsed approach — don't build a surface model.**
- **Dumas, Fleming & Whaley (1998, *Journal of Finance* 53(6):2059-2106), "Implied Volatility Functions: Empirical Tests":** the fancy fitted volatility-surface (DVF) model "is no better than an ad hoc procedure that merely smooths Black-Scholes implied volatilities across exercise prices," and **out-of-sample "its performance is worse than that of an ad hoc Black-Scholes model with variable implied volatilities."**
- **Rubinstein (1994, *J. Finance* 49(3):771-818), "Implied Binomial Trees":** the skew/smile is real (returns aren't lognormal); a tree can fit it exactly — but DFW show that buys you nothing out-of-sample.
- **Design note (sound):** our per-contract IV pricing already absorbs the skew. A surface/term-structure model is **optional, not necessary**. *(Caveat: DFW tested S&P index options, not single-name miners — it's a general anti-overfitting result.)*
- **Our code is consistent:** `compute_scenario_bundle` prices each candidate with **that candidate's own `implied_volatility`** — correct. The known limitation we already label: we hold that IV **constant across the gold scenarios**, so a −20% crash (where IV would spike) **understates** the put's value. The research reinforces keeping that caveat.

**2. ATM-straddle implied move** — a standard practitioner estimate of the expected move to expiry. Sound. *(Best academic source in-batch was a blog; the method itself is uncontroversial.)*

**3. The one caution that matters — the Variance Risk Premium (long options are expensive on average).**
- **Carr & Wu (2009, *Review of Financial Studies* 22(3):1311-1341), "Variance Risk Premiums":** implied/option-quoted variance **systematically exceeds** realized variance; premia are "strongly negative for the S&P 500 and 100 indexes." **Coval & Shumway (2001, *J. Finance*):** shorting a zero-beta ATM SPX straddle earned **~3.15%/week** — i.e., the *long* side lost that. **Christensen & Prabhala (1998, *JFE*):** ATM IV is an efficient forecast of realized vol — but priced *above* it.
- **The single-name nuance (directly relevant to us):** Carr & Wu — "the variance risk premia for the Nasdaq 100 index and for **most individual stocks are also negative, but with a smaller absolute magnitude**," often insignificant. **So the "options are too expensive" effect is much milder for single miners than the dramatic index numbers suggest.**
- **Design note (honesty):** for a speculative long-put/long-call tool, **disclose that buying premium is a negative-expectancy bet on average** — favorable only with a directional/event edge, not as a standing strategy. Milder for single names, but real. This fits the "be honest with the user" principle.

## (B) Predictive metrics worth adding
**1. ⭐ Option volatility SKEW / SMIRK — the strongest add, and we already compute it.**
- **Xing, Zhang & Zhao (2010, *JFQA* 45(3):641-662), "What Does the Individual Option Volatility Smirk Tell Us About Future Equity Returns?":** "the shape of the volatility smirk has significant cross-sectional predictive power for future equity returns" — **steepest-smirk stocks underperform flattest by ~10.9%/yr risk-adjusted**, persists ~6 months, linked to the worst subsequent earnings shocks (informed traders buying OTM puts before bad news).
- **We already compute `iv_skew_{h}d` = put_IV − call_IV** in `features/options.py`. **Recommendation:** surface it as a **crash-risk / downside signal** in the Option Trading tab and as a Tool C context column. **Honest caveat:** in-sample alpha (1996-2005), can decay post-publication — **validate on our own data, present as a flag not a guarantee.**

**2. Implied-vs-realized vol spread (variance risk premium proxy) — also already computed.**
- **Bollerslev, Tauchen & Zhou (2009, *RFS* 22(11)):** the VRP predicts returns, **peaks at the 1-4 month horizon**, beats P/E and default spread there. **Zhou (2010, Fed FEDS):** "predictability is short-run... peaks around one to four months and dies out." **Caveats:** established with **model-free (VIX-style)** implied variance, not per-contract BS IV; **out-of-sample weak** (Pyun 2016).
- **We already compute `iv_rv_ratio_{h}d`** (atm IV ÷ realized vol). **Recommendation:** surface it so the user **sees when options are expensive** (IV ≫ RV = overpaying). Treat as a "modest short-horizon tilt," not an edge. *(A true VRP signal would need a model-free integrated implied-variance built from the chain — a future upgrade.)*

**3. Put-call ratio — weak; don't oversell.**
- **Pan & Poteshman (2006, *RFS* 19(3)):** the strong predictive result uses a **proprietary buy-to-open *signed* dataset** — "ordinary publicly-available put-call ratios do NOT reproduce the result." Our public `put_call_oi_ratio` is a **weak** signal. **Recommendation:** keep it as context only; set expectations low.

**4. Refuted / cautionary:** two strong-form "short-vol is nearly free money" claims were **refuted** in verification — crash/jump risk is a real cost of selling options. (Relevant if we ever surface short strategies.)

## (C) Commodity equities as options on the commodity — ❓ under-evidenced, open gap
- **Theory backbone:** **Brennan & Schwartz (1985, *Journal of Business* 58(2):135-157), "Evaluating Natural Resource Investments"** — a mine / undeveloped reserve is an **option on the commodity**; operating leverage creates **convexity**. This is the right conceptual basis for generalizing "stock move = beta × commodity%" to oil/copper/silver/uranium producers. **But it was NOT in the verified-claim set this batch (medium confidence)** — cited, not independently confirmed here.
- **Cross-commodity betas + AISC elasticity (oil E&P vs WTI, copper, silver, uranium, coal; producer break-even / EBITDA sensitivity):** **none survived verification.** Sources were *fetched* (Brennan-Schwartz PDF; **World Gold Council AISC guidance — `gold.org` non-GAAP metrics standard**, a primary source; oil/copper papers) but not adversarially confirmed.
- **Design note:** the generalization is **theoretically reasonable** but **not yet research-backed quantitatively**. Before building a multi-commodity fragility module (or trusting Tool D's EBITDA-stress magnitudes), **commission a focused, verified pass** on (a) cross-commodity equity betas/convexity and (b) AISC/cost-curve EBITDA elasticity per commodity. For gold specifically, the **WGC AISC standard** is the authoritative definition to anchor Tool D's cost inputs.

---

## Concrete recommendations
1. **Keep per-contract market IV** (validated) — do **not** build a vol-surface model.
2. **Keep the constant-IV-across-scenarios caveat** — research confirms it understates deep-down-move put values.
3. **Add an honest "long premium is negative-expectancy on average (milder for single names)" disclosure** to the speculation/calculator UI (Carr-Wu, Coval-Shumway).
4. **Surface the volatility skew (`iv_skew`) as a crash-risk signal** — strongest predictive add, already computed; label "in-sample signal, validate, may decay" (Xing-Zhang-Zhao).
5. **Surface implied-vs-realized vol (`iv_rv_ratio`)** so users see when options are expensive — short-horizon tilt only (BTZ, Zhou).
6. **Down-rank the public put-call ratio** to context-only (the strong version needs proprietary signed flow).
7. **Open research gap to close** before multi-commodity / Tool-D-magnitude reliance: cross-commodity betas + AISC EBITDA-elasticity (and anchor gold cost inputs to the **WGC AISC standard**).

## Key sources
- Dumas, Fleming & Whaley 1998, *J. Finance* — per-contract IV beats surface OOS
- Rubinstein 1994, *J. Finance* — implied trees / smile is real
- Carr & Wu 2009, *RFS* — variance risk premium (negative; weaker single-name)
- Coval & Shumway 2001, *J. Finance* — short straddle ~3.15%/wk (long side loses)
- Christensen & Prabhala 1998, *JFE* — IV efficient forecast of RV
- Bollerslev, Tauchen & Zhou 2009, *RFS*; Zhou 2010, Fed — VRP predicts returns, short-horizon
- Xing, Zhang & Zhao 2010, *JFQA* — volatility smirk predicts returns (−10.9%/yr)
- Pan & Poteshman 2006, *RFS* — signed option flow predicts; public P/C weak
- Pyun 2016, *JFE* — VRP out-of-sample critique
- Brennan & Schwartz 1985, *J. Business* — resource equity as commodity option *(theory, unverified in-batch)*
- World Gold Council — AISC non-GAAP standard (`gold.org`) *(primary, anchor for Tool D costs)*
