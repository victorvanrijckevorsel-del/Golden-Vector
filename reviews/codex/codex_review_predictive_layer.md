# Codex Review - Predictive Layer Research, Skill, and Build Ideas

**Verdict: READY WITH CHANGES.**

The direction is right: do not build a black-box price target; build an honest predictive lab around point-in-time features, future labels, walk-forward tests, and calibrated frequencies. But the current build order is too heavy in a few places, and one repo-level prerequisite is real: GDX/GDXJ benchmark returns are currently not flowing through `build_weekly_return_frame`, so any alpha-vs-GDX, residualized-label, or two-factor residual-momentum plan would be built on missing benchmark returns until that is fixed.

## Sources I Re-Checked

- Tufano's broad miner-exposure claim is real: the SSRN abstract says the average mining stock moved about 2 percent for a 1 percent gold move, with exposures varying over time/across firms and related to hedging, diversification, gold prices/volatility, and leverage.
- Blose/Shieh's theoretical gold-miner elasticity > 1 claim is real in the accessible IDEAS abstract.
- Chicago Fed Letter 464 supports the "macro short-horizon gold prediction is weak" stance: the daily regression shown on the page has R-squared 0.012.
- Erb/Harvey supports the long-horizon valuation/inflation-hedge caution, not a short-horizon trading signal.
- Gu/Kelly/Xiu supports the idea that momentum/liquidity/volatility are robust price-derived predictors in large equity universes, but it does not make tree/NN models sensible for this tiny universe.
- I did not verify the exact Faff/Chan "0.75" number from a primary accessible source. Keep the qualitative warning that Australian gold-stock betas differed by market/period, but do not quote that exact coefficient unless Claude extracts it from the paper.

## Critique

### HIGH - Residual-alpha plans are blocked by a current benchmark-return gap

The ideas plan puts GDX-hedged residual alpha at the center of the label store (`reviews/codex/claude_predictive_layer_ideas.md:25`) and later proposes residual momentum vs gold+GDX (`reviews/codex/claude_predictive_layer_ideas.md:83`). In the actual repo, `fetch_benchmark_histories` standardizes benchmarks with `standardize_equity_history` (`golden_vector/ingestion/fetch_benchmarks.py:39-48`), which produces local-price columns (`golden_vector/ingestion/standardize.py:50-68`). `options_phase` persists those frames directly (`golden_vector/ingestion/options_phase.py:495-499`). But `build_weekly_return_frame` only reads `return_basis_usd`, `adj_close_usd`, or `close_usd` (`golden_vector/features/weekly_returns.py:141-152`). On current cached data, `tool_c_latest.parquet` has 0 non-null `rel_weakness_vs_gdx_pct` / `rel_strength_vs_gdx_pct` rows while gold-relative fields are populated. Concrete fix: before any prediction work, normalize benchmark histories into the same return-basis contract as equities or teach `_price_basis` that USD benchmark `adj_close_local` is an allowed major-unit basis. Add a contract test that GDX/GDXJ return columns are non-null on a fixture and that Tool C relative-vs-GDX metrics do not silently degrade to all-null.

### HIGH - The Dead-Miner Registry is directionally right but too large as an M1 gate

The plan makes a survivorship-complete dead-miner registry non-negotiable and puts it in M1 (`reviews/codex/claude_predictive_layer_ideas.md:24`, `reviews/codex/claude_predictive_layer_ideas.md:117`). The current repo only has the live configured universe (`config/universe.yaml:5-18`) and the two benchmark ETFs (`config/benchmarks.yaml:2-9`); there is no constituent-ingestion package or `golden_vector/prediction/` package yet. Reconstructing historical GDX/GDXJ holdings from N-PORT filings, mapping delistings/acquisitions, and defining terminal-return rules is a separate data product. Fix the scope: M0 should define a `security_master` / `tombstone` schema and coverage report; M1 backtests can be labeled "survivor-only exploratory"; confirmatory backtests become admissible only after survivorship coverage is measured. Do not block the first useful Tool A-only lab on a multi-month registry.

### HIGH - The beta-gap nowcast is promising, but the "near-no-lose" language is too strong

I agree beta drift is the best candidate signal, but the plan overstates its certainty (`reviews/codex/claude_predictive_layer_ideas.md:56-62`). The repo's Tool A structural engine is fast and already computes all historical as-of dates (`golden_vector/model/structural.py:345-437`), and the latest manifest shows 185,838 structural rows built in 5.796s plus 61,946 volatility rows in 6.733s. That makes an as-of beta feature feasible. But current Tool A does plain OLS windows and split up/down betas (`golden_vector/model/structural.py:466-541`); it does not persist slope standard errors, EW 26w beta, or shrinkage uncertainty. The 6M window minimum is only 20 observations, and split-regime minimums bottom at 8 (`golden_vector/contracts/config_models.py:671-712`). Fix the claim: beta-gap is not a product upgrade until it beats static beta on forward-beta MAE out-of-sample. Build it as an experiment first; only replace dial betas after the MAE gate passes.

### MEDIUM - "Do not predict gold" is right for point forecasts, too dogmatic for regimes

Claude's reframe is mostly correct (`reviews/codex/claude_predictive_layer_ideas.md:9`), and the skill correctly warns against a short-horizon gold-price predictor (`.claude/skills/predictive-models/SKILL.md:25-28`). But the same skill admits trend/momentum is one of the only robust gold-side structures (`.claude/skills/predictive-models/SKILL.md:26`). Do not build "gold will be $X" forecasts, but do include gold trend, realized gold volatility, real-rate regime, and ETF-flow regime as conditioning variables or abstention gates. That is different from point prediction and fits the user's dial: "when gold is in this regime, how reliable is this miner signal?"

### MEDIUM - "Residualize-or-die" overcorrects by making residual alpha the only label

Residual alpha is important, but the plan says the label store holds only GDX-hedged residual alpha (`reviews/codex/claude_predictive_layer_ideas.md:25`). Codex's original sketch kept multiple labels: raw forward returns, alpha vs GDX/GDXJ, gold returns/regimes, drawdown, and top/bottom quintiles (`reviews/codex/codex_predictive_layer_and_backtest_ideas.md:168-180`). Keep that broader label store. Product questions differ: a put buyer cares about drawdown and option payoff; a stock picker cares about alpha vs GDX; a portfolio owner cares about raw dollar drawdown. Fix: store multiple labels, but require every "skill" claim to show factor contamination diagnostics and residualized alpha alongside raw outcomes.

### MEDIUM - The foundation list is too large for the first shipped milestone

The plan says F1, F2, F3, F7, F8 are non-negotiable (`reviews/codex/claude_predictive_layer_ideas.md:32`), and the honesty layer adds seven more contracts (`reviews/codex/claude_predictive_layer_ideas.md:38-47`). That is more infrastructure than needed before the first honest answer. Minimum honest foundation should be: benchmark-return fix, PIT field registry, feature store, label store, walk-forward/purge split, variant ledger, leakage canaries, and sample-size reporting. Defer full PBO/DSR, full dead-miner registry, block-conformal intervals, and Candidate-Finder kill-switch until there is a model that might actually be consumed.

### MEDIUM - The current repo already has descriptive event machinery; reuse it instead of building a parallel lab from scratch

Tool C already builds weekly returns through the Tool A weekly sampler (`golden_vector/features/weekly_returns.py:25-77`), classifies rolling gold regimes (`golden_vector/features/gold_regime.py:20-77`), and computes event-based relative behavior (`golden_vector/features/relative_behavior.py:39-184`). The predictive plan should explicitly reuse these primitives for the first analog table and then generalize them into `golden_vector/prediction/`, rather than reimplementing gold-regime/event logic under new names. Fix: the M0 design should name these as source primitives and include a migration path: `features.weekly_returns` -> persisted weekly feature store; `features.gold_regime` -> prediction regime labels; `features.relative_behavior` -> descriptive baseline/backtest primitive.

### MEDIUM - The skill is too absolute about "no ML"

The skill says "No gradient boosting, no NN" and mostly this is correct (`.claude/skills/predictive-models/SKILL.md:33-35`). But it should distinguish between product models and diagnostic models. For Golden Vector v1, tree/NN should be banned from live output. However, ridge/logistic, monotonic additive models, and small Bayesian/hierarchical shrinkage are acceptable if they are transparent and heavily regularized. Fix wording: "No flexible ML in live decision surfaces for this universe; diagnostic ML is allowed only behind a red-team overfit report and may not feed Candidate Finder."

### LOW - The exact Faff/Chan coefficient should be removed unless re-extracted

The research report quotes a gold coefficient around 0.75 for Faff/Chan (`reviews/codex/claude_predictive_layer_research.md:38`) and the skill repeats the same idea (`.claude/skills/predictive-models/SKILL.md:30`). I could verify the publication exists, but not the exact coefficient from a primary accessible source. This is not load-bearing, because Tufano and Blose/Shieh already support "betas vary, do not assume 2x." Fix: keep the qualitative point; drop the exact coefficient or mark it "unverified until paper table is extracted."

### LOW - The original hedge-book idea was retained, but it needs a concrete "start clock" artifact

Codex's original sketch listed hedge-book fields (`reviews/codex/codex_predictive_layer_and_backtest_ideas.md:93-118`), and Claude correctly deferred causal inference (`reviews/codex/claude_predictive_layer_ideas.md:107-110`). What is missing is a small artifact now: `hedge_disclosure_vintages_{run_id}.parquet`, with ticker, disclosure date, source URL, hedged ounces/percent, instrument type, price/floor/cap, maturity, confidence, and extractor notes. This should be collection-only for a long time, but it is exactly the kind of data we cannot backfill honestly later.

## Additions

1. **Benchmark-return normalization as M0.** This is not optional. Without it, alpha-vs-GDX and residual momentum are fake or all-null.
2. **Point-in-time field registry.** One YAML/Parquet registry listing each candidate feature, source artifact, lag rule, whether it is PIT-safe today, and whether it is allowed in exploratory vs confirmatory backtests.
3. **Persisted weekly return store.** The repo currently computes weekly returns for Tool C but does not persist that frame as a first-class artifact. Persist `weekly_returns_{run_id}.parquet` through the manifest so prediction, Tool C, and future diagnostics consume the same return base.
4. **Gold regime features as conditioning, not forecasts.** Add gold trend, gold volatility, and real-rate regime as columns that explain when a miner signal is valid. Do not emit a gold point forecast.
5. **Two benchmark families.** Store both GDX and GDXJ alpha labels. Many juniors are closer to GDXJ; forcing every name to GDX can hide the actual relative skill question.
6. **Price-only break baseline.** Before testing Tool D, build a price-only drawdown/break baseline using beta, residual volatility, liquidity/market-cap, and momentum. Tool D only deserves "predictive" language if it beats this baseline once PIT fundamentals mature.
7. **Maturity ledger for live predictions.** Do not let Candidate Finder consume a prediction until the prediction type has at least 30 matured live predictions and calibration is not failing. Claude had this idea; keep it, but defer it until live predictions exist.

## Recommended Shortlist To Build First

| Build | One-line value | Why it survives the critique | Effort | Milestone | Pass/fail gate |
|---|---|---|---|---|---|
| 1. M0 data spine: benchmark-return fix + PIT field registry + weekly feature/label artifact contracts | Makes all later backtests possible and honest. | Pays off even if every alpha signal nulls; fixes a real current GDX/GDXJ gap. | M | M0 | GDX/GDXJ weekly returns non-null in a fixture and current data; feature rows contain only allowed PIT fields; labels are separate artifacts and cannot join live features. |
| 2. Walk-forward backtest harness with purge/embargo, variant ledger, and leakage canaries | Prevents fooling ourselves before any model exists. | Small universe means process discipline is the edge. | M | M0/M1 | Canaries must fail when label-as-feature, shifted-feature, or shuffled-label leakage is planted; every run records variant count/config hash. |
| 3. Conditional Scenario Dial analog table | Gives Emanuel useful "X out of 100 similar setups" without claiming alpha. | It is descriptive, transparent, and uses existing Tool A/history machinery; it is still useful under the null. | M | M1 | For each cell, render raw N, effective N, interval, median alpha vs GDX/GDXJ, and "insufficient history" when N is low; no live page computes it request-time. |
| 4. EB-shrunk dynamic beta / beta-gap nowcast experiment | Potentially upgrades the gold dial and option/hedge scenarios. | Tests a measurement improvement, not a price oracle; can ship as "shrunk beta" only if accuracy improves. | M | M1/M2 | Walk-forward next-26w beta MAE improves at least 10% vs static Tool A beta and raw fast beta, with no hidden deterioration in low-liquidity names. If it fails, ship the null and keep static beta. |
| 5. Price-only residual momentum and break baseline | Creates a hard benchmark for any later Tool D/fundamental predictive claims. | Uses point-in-time price data we already have; momentum/liquidity/volatility are the best-supported simple predictors. | S/M | M2 | Must beat raw momentum and naive beta/low-AISC baselines after costs; if not, it remains a descriptive yardstick only. |

## Recommended Revised Build Order

1. **M0 - Repair and register the data spine.** Benchmark returns, PIT field registry, weekly return artifact, feature/label schemas, kill-list basics.
2. **M1 - Build the honest backtest harness and analog dial.** Walk-forward, purge/embargo, variant ledger, canaries, conditional scenario table.
3. **M2 - Test beta shrinkage / beta-gap and price-only baselines.** Do not put anything in Candidate Finder yet.
4. **M3 - Only ship survivors live.** A survivor must have a passed backtest, a sample-size/calibration card, and a live-maturity ledger.
5. **M4+ - Add fundamentals/options/hedge history once vintages mature.** Until then, collect them and label them as not historically backtestable.

## Bottom Line For Emanuel

The best predictive product is not "this stock will rise." It is:

> "When gold does X, stocks with this current structure historically did Y relative to GDX/GDXJ, based on N honest past episodes. The evidence is strong/weak, and here is whether the signal has proven itself live."

Build the lab, but keep it small at first. The first real work should be data integrity and an analog table, not a full dead-miner registry or a sophisticated probability engine. The beta-gap nowcast is the most interesting signal, but it earns its place only by beating static beta out of sample.
