# Claude Review: Tool A Structural Redesign — Findings

Date: 2026-04-23
Reviewer: Claude (Opus 4.7, 1M context)
Branch: `dev-vic`
Mode: Read-only review.

This review reads the structural Tool A code, the implementation guide, the Guo / Leung / Ward (2018) SSRN paper, the live `tool_a_latest.csv` (snapshot run `20260423T111640Z-tool-a-25003370`, snapshot date 2026-04-22), the workspace presentation, and the test suite.

A note up front: I separate **bugs** (the code disagrees with itself or with stated intent) from **conceptual disagreements** (the design is internally consistent but I think it is wrong). The most important concern in this review is conceptual, but there are also several real bugs and inconsistencies in the live output. The structural redesign is a real improvement over the old horizon-first heuristic, but it is not yet ready as the official basis for ranking decisions.

---

## 1. Findings ordered P0 → P3

### P0 — Conceptual: "positive gamma = good upside torque" inverts the paper's prediction

Where:
- [golden_vector/model/explanations.py:53-55](golden_vector/model/explanations.py#L53-L55) — gamma narrative
- [golden_vector/model/labels.py:97-103](golden_vector/model/labels.py#L97-L103) — `CONVEX` profile
- [golden_vector/model/scoring.py:34-46](golden_vector/model/scoring.py#L34-L46) — gamma component score (positive ⇒ 1.0)
- [Gold_Framework_Implementation_Guide.docx](Gold_Framework_Implementation_Guide.docx) — gamma section

What the paper actually says (Sections 3.3 and 6 of [ssrn-3172514.pdf](ssrn-3172514.pdf)):
- Implied gold leverage `β_GLD(S)` is **decreasing** in spot gold (`β'(S) < 0`) and **convex** (`β''(S) > 0`).
- The "convexity" of the model is in the *time direction* — `β` spikes when gold is **falling** and the firm gets close to its default boundary. Up-gold weeks correspond to the **safer** regime, where `β` should be *lower*, not higher.
- The empirical paper finds that gold miner equities are **less levered than the model predicts on the upside** because firms exercise real options (hedging, mine closures, layoffs). The asymmetry the paper documents is *negative-skew at the firm level on rallies*, not the practitioner-friendly "positive convex upside torque" the implementation guide describes.

What the code does:
- `gamma = up_beta − down_beta`, scoring positive gamma at `1.0` and tagging it `CONVEX`.
- `build_gamma_explanation` says "Positive gamma … points to convex upside behaviour."
- `build_interaction_explanation` says positive gamma + high delta + low/moderate noise = "strong upside-torque name."

Conceptually this is the opposite of what the paper predicts. The implementation guide's "Method B: Up/Down Market Split" rule (`Delta(gold up) >> Delta(gold down) ⇒ positive gamma`) is the reverse of the model's `β'(S) < 0`. So the code matches the guide, but the **guide itself disagrees with the paper.**

This matters because the live BTG row already exhibits the disagreement: `up_beta_12m = 2.10 > down_beta_12m = 1.52`, gamma = +0.57, profile = CONVEX, score 92.5, rank 1. Per the paper, this pattern is more consistent with a high-cost / distressed-leverage profile than a "real-options-on-gold" upside name. It may still be a good investment, but the framework is selling it as convex upside on logic that the paper would not endorse.

I think the code should keep computing the up/down beta split (it is useful diagnostic information) but should:
1. Stop labelling the *positive* side "CONVEX" without a stronger explicit assumption.
2. Treat the *negative* side (down_beta > up_beta with delta > 1) as a fragility / negative-skew red flag, in line with both the paper's distress mechanics and the guide's own "ratio < 0.8 ⇒ avoid" advice.
3. Add a paragraph in the explanation cards naming what gamma is actually measuring (regime-conditional beta), without overclaiming option-like upside.

### P0 — Bug: Interaction explanation routinely contradicts the profile label and metrics

Where: [golden_vector/model/explanations.py:163-199](golden_vector/model/explanations.py#L163-L199) and [golden_vector/model/pipeline.py:401-412](golden_vector/model/pipeline.py#L401-L412)

In the live `tool_a_latest.csv` snapshot for 2026-04-24:

| Ticker | profile_label | structural_delta_core | structural_gamma_core | volatility_context | interaction_explanation |
|---|---|---|---|---|---|
| BTG | CONVEX | 1.80 | +0.57 | MODERATE_NOISE | "balanced … more balanced than specialized" |
| GOLD | LOW_LINKAGE | 0.50 | −0.23 | MODERATE_NOISE | "balanced …" |
| FRES.L | CONVEX | 1.32 | +0.50 | MODERATE_NOISE | "balanced …" (also tool_a_score = NaN, not flagged) |

Why: `build_interaction_explanation` only has four named branches — high-delta-with-positive-gamma-and-OK-noise, moderate-delta-with-low-gamma-and-low-noise, meaningful-delta-with-high-noise, and low-delta-with-positive-gamma. Anything else falls through to the generic "balanced" sentence. In particular there is **no branch for the BTG case**: a stock with `moderate_max ≤ delta_core < high_min` AND positive gamma AND low/moderate noise. There is also no branch for **CONVEX with MODERATE_NOISE.**

So the rank 1 official structural pick gets a summary line that contradicts the CONVEX profile and the metrics. The summary explanation directly composes the contradiction:

> "Convex. Confidence is high. This stock has some gold linkage, but the delta, gamma, and volatility mix is more balanced than specialized."

This is the user-facing line that sits at the top of the explanation cards. It is the single line a non-technical user is most likely to read, and on the highest-ranked name it is internally inconsistent.

### P1 — Bug: Score-ineligible rows still emit confident summary explanations

Where: [golden_vector/model/pipeline.py:362-412](golden_vector/model/pipeline.py#L362-L412)

FRES.L has `score_eligible = False`, `score_eligibility_reason = "UNACCEPTABLE_NORMALIZATION_STATUS"` (from `MISSING_RETURN_BASIS` in the trailing window), so `tool_a_score = NaN` and `tool_a_rank = NaN`. But the row still publishes:

- `profile_label = CONVEX`
- `confidence_label = HIGH`
- `tool_a_summary_explanation = "Convex. Confidence is high. ..."`

A user reading the workspace card for FRES.L sees a CONVEX/HIGH-CONFIDENCE label even though the system has refused to score the name. The score eligibility reason is in the row, but neither the workspace cards nor the summary text mention it.

I think the fix is small: when `score_eligible == False`, override the profile/confidence/summary text with something like "Score withheld: the trailing window contains return-basis gaps that block official Tool A scoring." Otherwise the explanation is louder than the actual signal.

### P1 — Bug: Labels can't see negative skew, so KGC reads as a "clean linear" name

Where: [golden_vector/model/labels.py:82-109](golden_vector/model/labels.py#L82-L109) and [golden_vector/model/explanations.py:163-199](golden_vector/model/explanations.py#L163-L199)

Live KGC row:
- `structural_delta_core = 1.58`
- `up_beta_12m = 1.10`, `down_beta_12m = 1.48` (down > up — falls more than it rises with gold)
- `structural_gamma_core = −0.37`, `asymmetry_ratio_core = 0.75`
- `volatility_context = LOW_NOISE`
- `profile_label = LINEAR`
- `interaction_explanation = "This is a clean linear gold exposure: strong delta, limited convexity, and low residual noise."`

The implementation guide is explicit (Step 4): asymmetry ratio < 0.8 means "Negative skew (avoid—stock falls more when gold falls)." The code's asymmetry threshold is wider (`weak_max = 0.9`), so KGC is correctly tagged "weak asymmetry" in the asymmetry card, but the *profile_label* and *interaction_explanation* never surface it. A user reading the page sees "LINEAR — clean exposure" instead of "fragile downside skew."

I think the fix is a `FRAGILE` (or `NEGATIVE_SKEW`) profile branch when `down_beta > up_beta` with `delta_core ≥ low_max`, with a matching interaction sentence. This is also the place to land the paper's distress intuition: a stock whose down-beta exceeds its up-beta is behaving like a more distressed leverage source.

### P1 — Bug / weakness: Confidence is saturated — every name reads HIGH

Where: [golden_vector/model/pipeline.py:496-538](golden_vector/model/pipeline.py#L496-L538) and [config/scoring.yaml:16-25](config/scoring.yaml#L16-L25)

Live confidence_score values for the six rankable names: 0.9831, 0.9852, 0.9950, 0.9964, 0.9921, 0.9830. All HIGH, all > 0.98. The threshold for HIGH is 0.75.

Why this happens:
- Coverage = 1.0 whenever 3 windows are eligible → contributes 0.30.
- `fit_score` saturates at `R² ≥ fit_good_r_squared = 0.30`, so any window with R² > 0.3 contributes the maximum → contributes 0.25.
- Sign agreement (all three deltas positive) → 0.25.
- Stability MAD-style score → ≈ 0.18.

Total ≈ 0.98. Once a stock has 3 eligible windows with sign-consistent positive delta and R² ≥ 0.30, the model declares maximum confidence. There is no way for the score to differentiate a clean R² = 0.7 reading from a marginal R² = 0.31 reading. In the live data the actual R²₁₂ₘ values range from 0.42 to 0.75, but every confidence comes out > 0.98.

This is internally consistent but undermines the whole purpose of confidence: it cannot lower itself when fit is genuinely weak. Practical fix: replace the saturating fit term with a non-saturating mapping (e.g. raw R² or `min(1, R²/0.5)`), and require the *worst* window's R² to count more than the average.

### P1 — Risk: STALE_FX is silently allowed into structural scoring

Where:
- [golden_vector/model/structural.py:107-129](golden_vector/model/structural.py#L107-L129) — drops non-OK rows from the regression sample
- [golden_vector/model/labels.py:53-79](golden_vector/model/labels.py#L53-L79) — only `MISSING_RETURN_BASIS` blocks score eligibility
- [config/scoring.yaml](config/scoring.yaml) and `QaConfig.block_on_stale_fx = False` — STALE_FX does not fail foundation either

A ticker with persistent STALE_FX in its trailing window (a) is silently filtered out of the regression sample, (b) produces a `normalization_issue_summary = "STALE_FX"` annotation, and (c) is still published as `score_eligible = True` if it has 2+ eligible structural windows. The workspace card never surfaces the annotation — `normalization_issue_summary` is in the parquet/csv but not rendered anywhere in [golden_vector/serve/workspace.py](golden_vector/serve/workspace.py).

This is exactly the pattern the review request asked me to find: "any place where stale FX or failed normalization is hidden instead of being surfaced." The current state is hidden-by-omission rather than hidden-by-design, but the effect is the same.

Suggested fix: surface `normalization_issue_summary` (and an explicit `fx_staleness_observed_max_days_in_window` field) on the workspace card, and either (a) gate score eligibility on STALE_FX too, or (b) downgrade `confidence_label` to MEDIUM/LOW when STALE_FX is present in the window.

### P1 — Bug: `asymmetry_component_score` and `asymmetry_ratio_core` use different inputs

Where: [golden_vector/model/pipeline.py:348-353](golden_vector/model/pipeline.py#L348-L353) vs [golden_vector/model/pipeline.py:285-287](golden_vector/model/pipeline.py#L285-L287)

`asymmetry_component_score` is computed using `up_beta_12m` and `down_beta_12m` only, while `asymmetry_ratio_core` is the weighted-median across {6M, 12M, 3Y}. So if the 12M window is missing or anomalous, the asymmetry component score does not benefit from the 6M / 3Y evidence. And the core ratio in the output column does not match the ratio used to compute the score.

This isn't a crash — `compute_asymmetry_component_score` falls back to 0.5 for missing data — but the published column and the score component are derived from inconsistent samples, which is brittle and hard to audit.

### P1 — Bug: `asymmetry_ratio` is set to None when `down_beta < 0`, hiding the strongest signal

Where: [golden_vector/model/structural.py:299-306](golden_vector/model/structural.py#L299-L306)

```python
asymmetry_ratio = (
    None
    if up_beta is None
    or down_beta is None
    or abs(down_beta) < 1e-9
    or down_beta <= 0
    else float(up_beta / down_beta)
)
```

The `down_beta <= 0` guard returns `None` when down-gold beta is negative — but that case (`up_beta > 0` and `down_beta < 0`) is *exactly* the strong asymmetry case the framework cares about (the stock rises with gold, but is uncorrelated or anti-correlated on the way down). The asymmetry component score patches this by special-casing `up_beta > 0 and down_beta <= 0 ⇒ 1.0`, but the published `asymmetry_ratio_*` columns and the asymmetry explanation will be missing or generic for those rows.

Suggested behaviour: keep `asymmetry_ratio = up_beta / down_beta` for negative `down_beta`, surface a sign indicator alongside, and let the explanation text say "down-gold weeks have inverted sensitivity, which is the cleanest asymmetry case."

### P2 — Bug: Latest weekly bar is built from a partial week and treated as a full one

Where: [golden_vector/model/structural.py:479-501](golden_vector/model/structural.py#L479-L501)

`_last_trading_day_per_week` groups by `W-FRI` periods and takes the last trading day in each period. For the current open week (snapshot date 2026-04-22, period end-time 2026-04-24), the "last trading day" is Wed 2026-04-22 — three trading days into the week. The bar is then labelled with `as_of_date = 2026-04-24`, and the next weekly log return spans Fri 2026-04-17 → Wed 2026-04-22, i.e. 4 calendar days, but is treated as a "weekly" return alongside genuine 7-day returns.

Effects:
- The regression beta is largely unaffected because both stock and gold get the same partial-week bias.
- Annualized weekly volatility is mildly downward-biased on the latest sample (one observation has a smaller effective horizon).
- Over time this also means the "as_of_date" published in the latest output is in the **future** relative to the data (`latest_output_as_of_date = 2026-04-24` vs `snapshot_as_of_date = 2026-04-22`). That's surprising in an audit log — the as_of_date a downstream user sees is not a date the system has data for.

Two reasonable fixes: (a) only emit a weekly bar when the week is complete (i.e., drop the in-progress week), or (b) use a rolling 5-trading-day bar and stamp `as_of_date` with the actual last data date.

### P2 — Bug: Volatility regression is independent of structural windows

Where: [golden_vector/model/structural.py:328-373](golden_vector/model/structural.py#L328-L373)

`compute_volatility_diagnostics` runs a fresh regression on `trailing.tail(52)` (last 52 weekly bars) and reports `residual_volatility_52w` from those residuals. This is computed independently of the 6M/12M/3Y structural betas used in scoring. So `residual_volatility_52w` is the residual to a *separate* 52-week beta, not to the published `structural_delta_12m`. A user comparing `residual_volatility_52w` to the structural delta in the same row will reasonably (and incorrectly) assume the residual was derived from that beta.

Either align the residual to the 12M structural beta or rename the field (e.g. `residual_volatility_52w_self_regression`) and explain it.

### P2 — Bug: 12M ineligibility cascades hard into scoring

Where: [golden_vector/model/pipeline.py:348-353](golden_vector/model/pipeline.py#L348-L353)

The asymmetry score uses the 12M window's `up_beta` / `down_beta` exclusively. The scatter chart in the workspace also pulls 12M only. If 12M happens to be `INELIGIBLE` (e.g., a ticker that has 6M and 3Y but a 12M gap due to data quality), the asymmetry component falls to its 0.5 fallback and the chart goes blank, even when 6M and 3Y are perfectly fine. There should be a fallback chain (12M → 3Y → 6M) and the published row should record which anchor window was used.

### P2 — Issue: `WINDOW_WEIGHTS = {"6M": 1.0, "12M": 2.0, "3Y": 1.0}` is hard-coded outside config

Where: [golden_vector/model/pipeline.py:105](golden_vector/model/pipeline.py#L105)

CLAUDE.md hard rule #2 says "Do not add new horizons ad hoc — modify only through centralized config." The structural windows are correctly fixed in scoring.yaml, but the *weighted-median weights* across them are a literal in pipeline.py. They should live in `ScoringConfig` so that any change is tracked in the config hash.

### P2 — Issue: `weighted_median` always anchors on 12M when 12M sits in the middle of the sorted values

Where: [golden_vector/model/structural.py:460-476](golden_vector/model/structural.py#L460-L476)

With `WINDOW_WEIGHTS = {6M:1, 12M:2, 3Y:1}` the cumulative-weight cutoff (`total/2 = 2.0`) is reached as soon as the 12M observation is hit (since 12M alone has weight 2). Sorted ascending, this means the function will return the 12M value whenever it is the smallest or middle, and will only deviate when 12M is the largest. In practice the function behaves more like "12M anchor with bias-toward-median" than a true weighted median. That's defensible but misleadingly named, and worth a clearer docstring or rename (e.g. `core_anchor_value`).

This is also why we see live rows where `structural_delta_core == structural_delta_12m` exactly (BTG, KGC, AEM, NEM, GOLD, FNV, FRES.L all show this).

### P2 — Issue: `score_eligibility_reason` only blocks `MISSING_RETURN_BASIS`

Where: [golden_vector/model/labels.py:71-78](golden_vector/model/labels.py#L71-L78)

```python
if scoring_config and "MISSING_RETURN_BASIS" in blocked_statuses:
    return False, "UNACCEPTABLE_NORMALIZATION_STATUS"
```

Only `MISSING_RETURN_BASIS` blocks. `STALE_FX` and `MISSING_FX` pass through silently. Combined with the `block_on_stale_fx = False` foundation policy, this means a name with stale FX through its window can still produce an "OK / score_eligible = True" Tool A row. Also, the `if scoring_config` guard is a no-op (the function is always called with a real `ScoringConfig`).

### P3 — Issue: Workspace `_render_scatter_panel` regression line is recomputed independently of the published 12M delta

Where: [golden_vector/serve/workspace.py:629-653](golden_vector/serve/workspace.py#L629-L653)

`_render_scatter_panel` calls `compute_regression(trailing.gold, trailing.stock)` on the last 52 weekly observations and draws that beta as the chart's regression line. The chart's slope can therefore differ from `structural_delta_12m` published in the same panel (different sample boundary, different filtering of normalization-issue rows). For the BTG case the delta on the chart and the metric card may not exactly agree.

### P3 — Issue: Workspace never surfaces `normalization_issue_summary`

Where: [golden_vector/serve/workspace.py](golden_vector/serve/workspace.py)

The field is in the published output and is the entire mechanism that warns on STALE_FX / MISSING_FX in the window, but it never appears in any rendered panel. That makes it functionally invisible to the workspace user.

### P3 — Issue: `_coerce_form_numeric` has dead code

Where: [golden_vector/serve/workspace.py:1137-1147](golden_vector/serve/workspace.py#L1137-L1147)

```python
if text.endswith("%"):
    return numeric / 100.0
return numeric if text.find("%") == -1 else numeric / 100.0
```

The trailing branch is unreachable: a string with `%` *not* at the end would fail `float(text)` first. Harmless but should be cleaned up.

### P3 — Issue: Exploratory horizon ladder shows raw `gold_delta = equity_return / gold_return`

Where: [golden_vector/serve/workspace.py:694-722](golden_vector/serve/workspace.py#L694-L722) and [golden_vector/features/returns.py:159-163](golden_vector/features/returns.py#L159-L163)

The "Horizon Leverage" column is a single-observation ratio. For small `gold_return` it explodes (the `near_zero_gold_return_threshold` blocks the very smallest cases, but values just above the threshold can still produce huge ratios). The hint says it is exploratory only, but the column is rendered next to a 2-decimal float and a "Status" cell. A user could easily read it as a comparable structural delta. I would either drop the column from the exploratory ladder or add an explicit "single-observation ratio, not a beta" note inline.

### P3 — Issue: Annualized "weekly volatility" uses log-return std × √52

This is the standard convention but it is the geometric (continuously-compounded) annualized volatility. The workspace prints it as "57.0%". For a beginner founder consuming the workspace, the units should probably be labelled "annualized log-vol" or have a one-line explanation that this is annualized.

### P3 — Issue: `compute_window_metric` uses `minimum_regime_observations = max(6, minimum_observations // 4)`

Where: [golden_vector/model/structural.py:272](golden_vector/model/structural.py#L272)

For 6M (minimum_observations=20), regime threshold = 6. So the 6M window's `up_beta`/`down_beta` can be estimated from as few as 6 observations — which is enough to compute a beta but is so noisy that the resulting gamma value should not really be trusted as evidence of a regime split. This is not a bug, but the `gamma_6m` and `asymmetry_ratio_6m` published from such small regime samples should arguably be flagged or dropped from the weighted median.

---

## 2. Conceptual alignment with the Guo / Leung / Ward paper

Short version: the redesign moves Tool A meaningfully closer to the paper's spirit (explicit regression-based delta on USD-normalized returns, structural windows, residual-vs-noise diagnostics), but the design **diverges from the paper in three important ways**, two of which are not currently labelled as deliberate departures.

1. **Single-factor regression vs the paper's two-factor regression.** The paper uses excess returns over the risk-free rate with **both gold and the broad equity market** as factors (paper equation 10). The code regresses stock log returns directly on gold log returns with no market factor and no risk-free adjustment. Without the market factor, any common equity-market drift leaks into `structural_delta` and into `r_squared`. For US-listed seniors during periods of S&P stress this can move beta meaningfully. This is a defensible simplification for a v1 product, but the implementation guide does not flag it as a deliberate departure from the paper.

2. **Long static windows vs the paper's short rolling regressions.** The paper estimates `β_GLD,t,j` from a **25-business-day rolling window with exponential decay 0.95**, then smooths the resulting time series with a Kalman Filter. The code uses 6M / 12M / 3Y *static* windows with equal weights. Long static windows wash out exactly the time-varying β behaviour the paper says is the whole point. The redesign is more stable, but it loses the regime-switching signal the paper demonstrates is real and economically meaningful. This is the single biggest conceptual gap, and it's not flagged as a deliberate trade-off in the explanation cards.

3. **Up-beta vs down-beta as a "convex upside" indicator inverts the paper's prediction.** The paper proves `β'(S) < 0` and `β''(S) > 0`: implied leverage **falls** as gold rises and **rises** as gold falls. The code's `gamma = up_beta − down_beta` (positive ⇒ "convex/optionality") therefore points the user toward a profile that, in the paper's framework, tends to indicate a high-cost or distressed firm rather than an attractive option-like upside. This is the conceptually most important issue (P0 above).

What the redesign *does* match well:
- USD normalization upstream of the regression sample (paper restricts to US-listed stocks, removing FX entirely; the code's USD normalization is the right analogue once the universe expands beyond US listings).
- Weekly rather than daily bars (the paper notes weekly is generally fine).
- Tracking residual variance (a clean structural-residual-vs-total-volatility split is in the right spirit).
- Explicit confidence built from coverage, fit, and stability — the paper's analogue is the Kalman filter's covariance estimate, but a simpler heuristic is reasonable for v1.

What the implementation guide gets right relative to the paper:
- Push toward at least 50 weeks of data for 12M deltas.
- R² ≥ 0.3 cutoff (the paper finds replicating-portfolio R² ≈ 0.65–0.7 with two factors, so a 0.3 single-factor R² is plausible).

Where the guide is weaker than the paper:
- The "delta band" classifications (1.5 / 2.0 / 2.5) are the guide's own thresholds, not from the paper. The paper's empirical betas for ABX/GG/GDX/GDXJ run roughly 1.0–3.5 with extreme spikes near distress; treating "1.5–1.8" as automatically high may over-classify steady-state seniors as high-torque names.
- The "asymmetry ratio < 0.8 → avoid" rule is a useful practitioner heuristic but is not in the paper. The code's threshold is wider (0.9), which is fine, but the threshold should probably be a config knob with a justification.
- The guide treats positive gamma as a fundamentally good thing. The paper would treat positive gamma in a steady-state producer as a sign of distress-sensitive leverage, not real-options upside.

I think the right framing for v2 of the implementation guide is: "The paper proves convexity is in the time-direction (β rises in distress). Our up-vs-down-beta split is a *crude regime-conditional proxy* for state-conditional beta, not a direct measure of option-like upside. We use it because real-time Kalman estimation of β_GLD(S) is out of scope for v1, but a positive gamma should be interpreted as 'the stock has been more sensitive in rising-gold weeks than falling-gold weeks over this sample,' nothing more."

---

## 3. Conceptual alignment with the implementation guide

Where the code follows the guide closely:
- Weekly Friday bars and log returns (Step 2/3).
- 6M / 12M / 3Y windows (Step 3).
- R² gate (`fit_warn_r_squared = 0.15`, `fit_good_r_squared = 0.30`) close to the guide's "R² > 0.30" rule (Step 3 quality check).
- Up-vs-down-beta split for gamma (Step 4 Method B).
- Asymmetry ratio = up-beta / down-beta with thresholds (Step 4).
- Profile labels (HIGH_DELTA, CONVEX, LINEAR, DEFENSIVE, LOW_LINKAGE) follow the guide's classification tree.

Where the code diverges from the guide silently:
- Gamma threshold in the guide is qualitative ("Delta(gold up) >> Delta(gold down)"); the code uses ±0.15 from the live config (vs the contract's ±0.25 default). The code is stricter than the contract default but this isn't documented anywhere.
- Asymmetry "weak/strong" thresholds in the live config are 0.9 / 1.1; the guide says < 0.8 / 0.8–1.2 / > 1.2. The code's bands are tighter on both sides.
- The guide's quality check #3 ("6M, 12M, and 3Y deltas should be within 30% of each other") is loosely captured by `delta_stability_score`, but the code never enforces a hard 30% rule. That's fine, but makes the guide look more conservative than the code.

Where I think the guide itself is weak (independent of the code):
- The conflation of "positive gamma" with "good upside torque" (already covered in P0 above).
- No mention of the multi-factor regression, the risk-free adjustment, or the time-varying β estimation that are central to the paper.
- The "Method A: Visual Rolling Delta" recommendation contradicts the long-window approach used in Method B and in the code. Either method is defensible, but the guide should pick one.

---

## 4. FX / normalization assessment

What the code gets right:
- Tool A consumes the USD-normalized snapshot, not raw equities (CLI gates on snapshot signature; structural code uses `return_basis_usd`).
- `equity_ok` filter requires `normalization_status == "OK"` AND `return_basis_usd > 0`, so non-OK rows do not reach the regression.
- `normalization_issue_summary` is emitted per (ticker, as_of_date) so the audit trail exists.
- Snapshot provenance is published in the output: `snapshot_refresh_run_id`, `fx_policy_max_staleness_days`, `fx_policy_block_on_stale_fx`, `source_run_id`.

What the code gets wrong or hides:
- **STALE_FX is silently allowed into score eligibility** (P1 above). Only `MISSING_RETURN_BASIS` blocks; everything else is annotated and passes through.
- **The workspace never surfaces `normalization_issue_summary`** (P3 above). The annotation might as well not exist for a workspace-only user.
- **There is no `fx_staleness_observed_max_days_in_window` field**. The output records the *policy* (`fx_policy_max_staleness_days`) but not the *observed* worst-case staleness in the window. So when a row has `STALE_FX` in `normalization_issue_summary`, you can't see how stale.
- The scatter panel's regression is computed on `weekly_series.tail(52)`, which already filters out non-OK rows from the structural sample. That's consistent — but the line on the chart silently disagrees with the structural_delta_12m metric whenever the 12M window contains issues that are filtered.

What is fine but worth confirming:
- `_foundation_signature` change-detection in [golden_vector/app/latest_data.py](golden_vector/app/latest_data.py) re-validates the universe and FX policy each Tool A run. Good defensive guard.
- Empty-run protection on the `*_latest` aliases ([codex_review_post_workspace_hardening_2026-04-23.md](reviews/codex/codex_review_post_workspace_hardening_2026-04-23.md)) prevents stale fallbacks from being clobbered. Good fix.

---

## 5. Explanation and dashboard / workspace assessment

The structural cards, explanation grid, scatter chart, up/down beta bar, and exploratory horizon ladder all communicate in roughly the right shape: a metric, a deterministic plain-English sentence, and an exploratory caveat. The redesign here is genuinely better than the prior horizon-only view.

What is genuinely good:
- Seven separate explanation cards (Delta, Gamma, Asymmetry, Volatility, Confidence, Interaction, Summary) are easier for a non-technical reader to scan than one block of text.
- The "Tool A is now structural-first" hint is clear, and the exploratory-horizon panel is correctly labelled "exploratory only … does not drive the official Tool A score."
- The scatter chart with regression overlay anchors the abstract "structural delta" number in something visual.
- The metric grid (Delta, Gamma, Asymmetry, Confidence, Volatility, Score, Profile) is the right summary header for a stock's structural footprint.

What is misleading or weak:
- **Summary explanation contradicts the metrics** in the BTG / GOLD / FRES.L cases (P0/P1 above). The single line at the top of the card is the most read line on the page; getting it wrong on the rank 1 name is a real trust issue.
- **Score-ineligible names get confident profile/confidence labels** (P1 above). FRES.L's CONVEX / HIGH cards do not surface its `tool_a_score = NaN` or its `MISSING_RETURN_BASIS` block.
- **`normalization_issue_summary` is never rendered** (P3 above).
- The scatter chart's regression line is recomputed locally and can disagree with `structural_delta_12m` (P3 above).
- The exploratory horizon ladder shows a "Horizon Leverage" column that is a single-observation ratio. The hint says exploratory but the column reads like a comparable beta.
- The confidence card always says "High confidence …" because the score saturates above 0.98 (P1 above). The text becomes filler.

What is missing:
- A dedicated red-flag panel for STALE_FX / MISSING_FX / MISSING_RETURN_BASIS in the trailing window.
- A "score withheld" treatment for `score_eligible = False` rows.
- A way to see the rank's source: which window contributed each component, what the worst-case fit was, which week-count was used.

---

## 6. Missing tests / residual risks

Tests that would have caught bugs above and don't exist today:
- A pipeline test where 12M is INELIGIBLE but 6M / 3Y are ELIGIBLE — exposes the asymmetry score's hard 12M dependency.
- A pipeline test where `down_beta < 0` and `up_beta > 0` — exposes the `asymmetry_ratio = None` early-return.
- A pipeline test where `normalization_issue_summary == "STALE_FX"` — confirms whether scoring gates it (currently it does not).
- A label test for a ticker with `down_beta > up_beta` and `delta_core ≥ 1.5` — exposes the missing FRAGILE / NEGATIVE_SKEW branch.
- An interaction-explanation test for the BTG case (`moderate_max ≤ delta < high_min`, positive gamma, MODERATE_NOISE) — exposes the "balanced" fallback.
- A test that an ineligible row's summary explanation does **not** present a confident CONVEX/HIGH-CONFIDENCE narrative.
- A test of `weighted_median` directly across 3 windows showing why it equals 12M for the typical case.
- A test of `_last_trading_day_per_week` with a partial week — confirms whether the open week is included or excluded.
- A test that confidence_score < 0.95 in a moderate-fit scenario (current synthetic tests build deterministic high-fit equity histories, so confidence is always ≈ 1).
- A workspace render test that asserts `normalization_issue_summary` appears in the rendered HTML when present.
- A workspace render test for a `score_eligible = False` row (asserts the page surfaces "score withheld" rather than "Tool A Score: -").

Residual risks beyond bugs:
- The hard-coded `WINDOW_WEIGHTS` outside config makes it hard to track changes (P2 above).
- The single-factor regression conceals market-driven beta drift in stress periods.
- The static window approach is comfortable but obscures regime change. If the user ever cares about "what is the current regime?" — the kind of question the Sprott commentary addresses — the structural model can't answer it.

---

## 7. Final verdict

**NOT READY** as the official basis for ranking decisions, because:
- The rank 1 name (BTG) ships with a summary explanation that contradicts its own profile and metrics (P0/P1).
- A score-ineligible name (FRES.L) ships with a confident CONVEX / HIGH-CONFIDENCE narrative and no surfaced reason for the missing score (P1).
- A name with negative skew (KGC) reads as a "clean linear gold exposure" (P1).
- Confidence is saturated and cannot lower itself for genuinely weak fits (P1).
- STALE_FX bypasses score eligibility silently and is never surfaced in the workspace (P1).
- The "positive gamma = good upside torque" framing inverts the paper's prediction (P0 conceptual).

That said: the redesign **is** mathematically coherent at the regression level, **is** meaningfully closer to the paper than the old horizon-first model, and **is** well separated from the exploratory horizon layer. The bugs above are concrete and targeted; none of them require redesigning the structural pipeline. After fixing P0/P1 items and clarifying the gamma interpretation in the implementation guide, this should be straightforwardly **READY WITH MINOR CHANGES** in a subsequent review pass.

The implementation guide itself needs a v2 that (a) acknowledges the single-factor / static-window simplifications relative to the paper, (b) reframes "positive gamma" as a regime-conditional beta proxy rather than upside torque, and (c) adds an explicit FRAGILE / NEGATIVE_SKEW profile aligned with its own asymmetry-ratio < 0.8 rule.

---

## Quick answers to the seven Specific Questions

1. **Is the new official Tool A mathematically coherent?** Yes at the regression level (centered OLS, weekly log returns, USD-normalized basis). The volatility module is internally consistent. The scoring weights sum to 1, the bands are ordered, and the eligibility logic is deterministic. The mathematical issues are at the *interpretation* layer (gamma/asymmetry semantics) and at edge cases (negative down_beta, partial week, saturation).

2. **Is it meaningfully closer to the Guo / Leung / Ward logic than the old horizon-first model?** Yes. Single-factor regression on USD weekly log returns is the right family of models. The horizon-return ratio approach was a heuristic; this is a regression. The remaining gap is real (no market factor, static windows, no Kalman smoothing, "convexity" mapped to the wrong direction), but the redesign is unambiguously a step forward.

3. **Does the implementation guide still need conceptual refinement after this redesign?** Yes — see Section 2 / Section 3. Specifically: name the simplifications relative to the paper, reframe gamma, add the FRAGILE / NEGATIVE_SKEW profile aligned with the guide's own < 0.8 rule, and pick one of "Method A rolling delta" / "Method B up-down split" rather than presenting both.

4. **Is volatility integrated in the right way, or should it be treated differently?** Mostly right — total / residual / downside is the right triple. Two adjustments: (a) tie residual volatility to the structural beta used in scoring (or rename the field), and (b) call out that high downside volatility should arguably *lower* confidence directly, not just shift profile_label.

5. **Are the new explanation fields genuinely valuable, or are they still too shallow or too risky?** Valuable in shape, risky in content today. The seven-card layout is right. But (a) interaction_explanation has a "balanced" fallback that overrides the metrics, (b) summary_explanation runs on score-ineligible rows, and (c) confidence_explanation almost always says "high confidence" because the score saturates. After P0/P1 fixes the cards become genuinely decision-useful.

6. **Is the workspace now the right presentation shape for Tool A, or should it be improved before more feature work?** Right shape, needs three additions before more feature work: (a) surface `normalization_issue_summary`, (b) treat `score_eligible = False` as a first-class state (don't render confident CONVEX/HIGH labels), and (c) align the scatter regression line with the published structural_delta_12m. After those it's a solid v1 surface to iterate on.

7. **What are the most important remaining weaknesses before we can fully trust Tool A?**
   1. The P0/P1 explanation/label inconsistencies (BTG, FRES.L, KGC).
   2. Confidence saturation hiding genuinely weak fits.
   3. STALE_FX bypass and invisibility in the workspace.
   4. The conceptual mismatch between "positive gamma = good" and the paper's `β'(S) < 0` prediction.
   5. The single-factor regression and static long windows departing from the paper's two-factor / short-rolling / Kalman-smoothed approach without flagging it as deliberate.
