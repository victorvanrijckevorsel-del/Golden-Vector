# Codex Ideas - Predictive Layer + Backtesting for Golden Vector

## Executive View

Golden Vector can become more predictive, but it should not jump straight to a black-box "price target" model. The right next layer is a disciplined **Predictive Lab**:

- compute point-in-time features;
- compute future labels only after the fact;
- backtest whether signals actually predicted useful outcomes;
- then expose live predictions as probabilities/ranges, not certainties.

The core product question should be:

> Given what we knew on date T, which miners tended to outperform, underperform, or break when gold moved over the next 30/60/120 days?

This is different from the current tool, which mostly answers:

> What is this miner's structure today?

## What "Predictive" Should Mean

Avoid exact stock-price prediction at first. It is noisy and gives false precision.

Better prediction targets:

| Target | Why it matters |
|---|---|
| 30d / 60d / 120d forward return vs GDX/GDXJ | "Will this name beat miner peers?" |
| Forward return conditional on gold up/down regimes | "Does this stock behave as expected when gold moves?" |
| Top-quintile / bottom-quintile probability | Easier and more robust than exact return |
| Drawdown probability during gold selloff | Useful for risk and put/call screening |
| Option trade outcome | "Would this selected put/call have paid off after premium?" |

Preferred live output:

> "Historically, similar setups outperformed GDX over 120d 61% of the time, with median alpha +7%."

Not:

> "This stock will go to $220."

## Signals Worth Testing

Use existing Golden Vector outputs first.

### Tool A / Structural Gold Sensitivity

- down beta;
- up beta;
- delta/gamma/asymmetry;
- confidence;
- gold downside/upside ranks;
- hit rates during gold-up/gold-down weeks.

These are the cleanest first backtest candidates because they can be reconstructed from historical prices.

### Tool B / Corporate Finance

- AISC;
- margin %;
- EV/EBITDA;
- forward P/E;
- FCF yield;
- leverage;
- reserve life;
- market cap/liquidity.

Backtest caution: only valid point-in-time if we have historical snapshots. Do not backtest today's AISC or leverage as if we knew it in 2022.

### Tool D / Corporate Resilience

- interest-cover gold;
- debt-stress gold;
- FCF-breakeven gold;
- cost curve percentile;
- survival distance at current gold;
- deterioration rate under falling gold.

Useful predictive question:

> In past gold selloffs, did names with worse survival lines underperform more?

### Options / Market-Implied Signals

- sector-relative 25-delta skew;
- IV/RV;
- option liquidity tier;
- OI/volume concentration by strike;
- put/call activity confirmation.

Backtest caution: option-chain history starts only once we retain snapshots. Do not fabricate historical options signals from today's chain.

### Hedge Book / Production Hedging

This is important and currently missing.

Manual fields to collect:

- `hedged_oz_12m`;
- `hedged_pct_12m`;
- `hedge_type` = forward / put / collar / stream / offtake;
- `avg_fixed_price`;
- `avg_floor_price`;
- `avg_cap_price`;
- `maturity_date`;
- `source_url`;
- `source_date`;
- `confidence`.

Why it matters:

- heavily hedged miner should have less upside to gold rallies;
- forward-sold production protects downside but caps upside;
- puts protect downside while preserving upside;
- collars protect downside and cap upside;
- recently changed hedge books can make historical beta stale.

Use this as context first. Only model it after enough point-in-time history exists.

## Required Architecture

Build this as a backend-only data product. Serve/UI must only render persisted prediction/backtest artifacts.

Proposed package:

`golden_vector/prediction/`

Suggested modules:

- `feature_store.py`
- `labels.py`
- `models.py`
- `backtest.py`
- `metrics.py`
- `reader.py`
- `schemas.py`

### Feature Store

Persist one row per ticker per as-of date:

`prediction_features_{run_id}.parquet`

Minimum columns:

- `as_of_date`;
- `ticker`;
- feature source run ids;
- Tool A fields;
- Tool B fields where point-in-time safe;
- Tool C/D fields where point-in-time safe;
- option-signal fields where available;
- data-status fields;
- feature availability flags.

Hard rule:

> A feature row may contain only data available at `as_of_date`.

### Label Store

Persist future outcomes separately:

`prediction_labels_{run_id}.parquet`

Labels:

- `forward_return_30d`;
- `forward_return_60d`;
- `forward_return_120d`;
- `forward_alpha_vs_gdx_30d`;
- `forward_alpha_vs_gdx_60d`;
- `forward_alpha_vs_gdx_120d`;
- `gold_return_30d`;
- `gold_return_60d`;
- `gold_return_120d`;
- `gold_regime_60d` = up / flat / down;
- `realized_drawdown_60d`;
- `top_quintile_120d`;
- `bottom_quintile_120d`.

Hard rule:

> Labels are future data and must never join into live feature generation.

### Model Output Store

Persist live predictions:

`prediction_output_{run_id}.parquet`

Columns:

- `ticker`;
- `as_of_date`;
- `model_version`;
- `target_horizon`;
- `predicted_alpha_vs_gdx`;
- `prob_outperform`;
- `prob_bottom_quintile`;
- `prediction_confidence`;
- `top_drivers`;
- `data_status`;
- `training_window_start`;
- `training_window_end`;
- `sample_size`.

This must be manifest-integrated and immutable run-stamped.

## Backtesting Design

Use walk-forward testing.

Example:

1. Train on data through 2021-12-31.
2. Predict 2022-01-31.
3. Wait forward horizon.
4. Score prediction.
5. Roll forward.

Never randomly shuffle time-series rows.

### Metrics

Report:

- hit rate;
- average forward alpha;
- median forward alpha;
- top-minus-bottom quintile spread;
- information coefficient;
- max drawdown;
- turnover;
- number of observations;
- number of unique tickers;
- performance by gold regime;
- performance by market-cap bucket;
- performance by data-quality bucket.

Also report failure cases:

- false positives;
- false negatives;
- high-confidence wrong calls;
- signals that only worked in one regime.

## Model Choice

Start simple.

### Baseline 0 - Naive Benchmarks

- equal-weight universe;
- GDX/GDXJ benchmark;
- up-beta only;
- down-beta only;
- low-AISC only;
- high-margin only.

Every predictive model must beat these.

### Model 1 - Transparent Rank Model

No machine learning yet. Combine a few signals with fixed weights and test:

- up-beta for gold-up regime;
- down-beta/fragility for gold-down regime;
- resilience for drawdown protection;
- valuation for medium-term alpha.

This helps us understand whether the current tools have predictive content.

### Model 2 - Regularized Regression / Logistic Regression

Use ridge/logistic regression:

- target = forward alpha or top-quintile probability;
- features standardized within each as-of date;
- coefficients visible;
- shrinkage reduces overfitting.

Good first "real model."

### Model 3 - Gradient Boosting Later

Only after the simple model proves useful.

Gradient boosting can capture nonlinear interactions, but it is easier to overfit, especially with a small universe.

Avoid neural networks. The data is too small.

## Backtest Overfitting Guardrails

Investment backtests are easy to fool.

Guardrails:

- keep train/test time separated;
- no future fundamentals;
- no using today's hedge data in old periods;
- no using today's option chain historically;
- no tuning 50 variants and showing only the winner;
- include transaction costs/slippage;
- report sample size;
- report confidence intervals;
- compare against simple baselines;
- freeze model versions once tested.

Useful references for Claude:

- Andrew Lo, "The Statistics of Sharpe Ratios" - Sharpe ratios have estimation error.
- Bailey / Borwein / Lopez de Prado / Zhu, "The Probability of Backtest Overfitting" - many good-looking backtests are false positives.
- Fama/French risk-factor literature - factor exposure and cross-sectional returns need benchmark discipline.

## What Can Be Backtested Now vs Later

### Backtestable Soon

- Tool A structural features from historical prices.
- Forward returns and alpha vs GDX/GDXJ.
- Gold-up/gold-down regime labels.
- Simple rank models using price-derived features.

### Needs Point-in-Time Snapshots First

- Tool B fundamentals;
- Tool D resilience;
- option signals;
- hedge-book disclosure;
- manual company inputs;
- Yahoo official fundamentals once added.

For these, start collecting now. Do not pretend historical values existed.

## Suggested Milestones

### M0 - Prediction Audit

Goal: decide exactly which existing fields are point-in-time safe.

Deliverables:

- field inventory;
- point-in-time status for each field;
- leakage risk rating;
- list of fields allowed in first backtest.

### M1 - Feature + Label Store

Backend only.

Deliverables:

- `prediction_features` artifact;
- `prediction_labels` artifact;
- schema tests;
- manifest registration;
- no serve integration yet.

Start with historical Tool A + returns only.

### M2 - Baseline Backtests

Deliverables:

- baseline strategy results;
- top-minus-bottom quintile charts;
- hit-rate by horizon;
- gold-regime split;
- report file under `data/output/prediction/`.

Question answered:

> Do existing Golden Vector signals contain predictive information?

### M3 - Transparent Prediction Score

Deliverables:

- simple backend prediction model;
- persisted predictions;
- model versioning;
- walk-forward backtest;
- live Candidate Finder optional criterion: `prob_outperform_120d`.

### M4 - Add Point-in-Time Fundamentals

Only after data collection matures.

Deliverables:

- historical snapshots where available;
- no-leakage tests;
- fundamentals-aware backtest.

### M5 - Options + Hedge-Book Predictive Features

Only after option-chain history and hedge-book snapshots exist.

Deliverables:

- option-signal backtests;
- hedge-adjusted gold beta tests;
- option trade outcome backtests.

## Product UI Idea

Do not add this as another vague ranking.

Add a "Predictive Lab" page with:

- model version;
- training period;
- test period;
- sample size;
- hit rate;
- expected alpha;
- confidence;
- top drivers;
- backtest results;
- warning when data history is too short.

Candidate Finder can later consume only a few simple fields:

- `prob_outperform_120d`;
- `prob_bottom_quintile_60d`;
- `expected_alpha_vs_gdx_120d`;
- `prediction_confidence`.

## Biggest Risks

1. Future-data leakage.
2. Backtest overfitting.
3. Too few tickers / too few regimes.
4. Fundamentals not point-in-time.
5. Option-chain history too short.
6. Hedge-book data manual and inconsistent.
7. UI turning probabilistic output into fake certainty.

## Recommendation

Build the predictive layer in this order:

1. backtest Tool A only;
2. prove the existing signals have predictive value;
3. collect point-in-time snapshots for fundamentals/options/hedges;
4. then add transparent prediction scores;
5. only later test more complex models.

Do not start with a black-box model. Start with a rigorous backtest engine and use it to decide what deserves to become predictive.
