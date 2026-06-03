# Review request for Codex: cross-check the academic research against the actual tool

## Role & mode
You are a senior quant engineer. This is a **READ-ONLY** review. Do **not** modify code or create commits. Produce one findings document only.

## What to do
I commissioned two adversarially-verified deep-research reports on the academic literature behind this tool. Your job is to **cross-check those research findings against what we actually implemented and planned**, and surface (a) places where the code/plan **diverges from what the literature says is correct**, (b) outright **errors or unsound math**, and (c) **concrete, research-grounded improvements** — especially metrics the papers endorse that we already compute but don't surface.

## Read first — the research
- `reviews/codex/research_academic_grounding_gold_model.md` (gold beta, down/up-beta, downside ranking, thin-tail estimation, linear-factor limits)
- `reviews/codex/research_options_methodology_and_predictors.md` (Black-Scholes IV / skew, ATM-straddle implied move, variance risk premium, predictive signals, commodity-equity-as-option)

## Then audit these implementation + plan files against the research
- `golden_vector/hedge/scenarios.py` — option P&L scenarios, beta×gold scaling, constant-IV-across-scenarios, breakeven math
- `golden_vector/hedge/candidate_puts.py` — candidate selection, per-contract IV, delta targeting
- `golden_vector/features/black_scholes.py` — BS put/call pricing, delta
- `golden_vector/features/options_chain.py` — ATM-straddle implied move, tradability/IV gates
- `golden_vector/features/options.py` — `iv_skew_*`, `iv_rv_ratio_*`, `realized_vol_*`, `atm_iv_*`, `iv_percentile_cross_sectional`
- `golden_vector/hedge/option_trading.py` + `golden_vector/serve/detail_panels.py` — what's surfaced to the user
- `golden_vector/model/structural.py` — how the gold betas (`down_beta_core`, `up_beta_core`, `structural_delta_core`) are built
- `reviews/codex/claude_tool_c_d_plan_v3.md` — the Tool C/D plan (downside ranking, thin-data policy, §2j descriptive-not-predictive framing, §2k option caveat)

## Specific things to verify or challenge (map each to the research)
1. **Per-contract IV is correct (DFW 1998).** Confirm `compute_scenario_bundle` prices each candidate with **its own** `implied_volatility`, not a single shared/ATM IV. Flag any place a wrong/shared IV is used. Confirm we are NOT (and need not) build a vol-surface model.
2. **Constant-IV-across-scenarios limitation.** The code holds IV fixed while the stock moves −20%..+20%. The research says this **understates** deep-down-move put values (vol rises in crashes / skew). Is this caveat surfaced to the user anywhere, or silently assumed? Recommend where to label it.
3. **Variance risk premium (Carr-Wu 2009; Coval-Shumway 2001).** Long options are expensive on average (milder for single names). Is there any honesty disclosure in the speculation/calculator UI? If not, flag it as a missing user-facing caveat.
4. **Predictive metrics we already compute but don't surface.** We calculate `iv_skew_*` (volatility smirk — Xing-Zhang-Zhao 2010 crash-risk predictor) and `iv_rv_ratio_*` (implied-vs-realized — BTZ 2009). Confirm they're computed correctly, check whether they're surfaced in the UI/Tool C, and assess whether the **skew sign convention** (`put_iv − call_iv`) matches the "steeper smirk = more downside risk" interpretation. Recommend how to surface them with honest "in-sample, validate, may decay" caveats.
5. **Public put-call ratio is weak (Pan-Poteshman 2006).** We compute `put_call_oi_ratio_*`. Confirm it's only used as context, not oversold as a predictor.
6. **Down-beta is descriptive, not a return predictor (Atilgan 2020; Levi-Welch-Karolyi 2020).** Check the Tool C plan v3 §2j framing and whether anything in the code/UI implies high-down-beta = higher expected return. Confirm plain beta (`structural_delta_core`) is shown alongside down-beta.
7. **Thin-tail flagging (Yamai-Yoshiba; Pitera-Schmidt; Barendse).** Confirm the plan's thin-tail metrics are flagged low-confidence and excluded from the headline rank, and that the worst-N-week average is honestly labeled.
8. **Linear `beta × gold%` at extremes (Brennan-Schwartz convexity; Shahzad 2021).** Confirm the −15/−20% rows are (or per §2k will be) labeled "approximate," and that operating leverage may worsen real downside.
9. **Breakeven & strategy math.** Re-derive the put breakeven `((K−prem)/S −1)/β` and call breakeven `((K+prem)/S −1)/β` and confirm signs/orientation are correct for both.

## Output
Write `reviews/codex/codex_review_research_vs_tool.md`:
- **Grade:** READY / MINOR CHANGES / NEEDS CHANGES (for "does the tool match the literature").
- **Findings first, ordered by severity**, each with concrete `file:line` references and the specific research finding it relates to.
- Separate **errors/unsound math** (must fix) from **research-grounded improvements** (should add) from **honesty/labeling gaps** (should disclose).
- Note any place the research itself is **mis-applied** in our plan (e.g., a single-name vs index-level confusion on the variance risk premium).
- Call out any **open citation gaps** (cross-commodity betas, AISC EBITDA-elasticity) we should not rely on yet.
- Do not rewrite the plans; do not implement fixes.
