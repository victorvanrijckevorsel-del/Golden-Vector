# Plan: Behaviour Trend + Peer Ranking for the Lab Dial

## Verdict

Build these two ideas together as a **Lab behaviour-trend layer**:

1. **Time / regime-change view**: all-history vs recent vs decay-weighted behaviour, with honest sample-size gates.
2. **Peer-universe ranking**: in the same gold scenario, where did this stock rank versus other miners, not only versus GDX/GDXJ.

This should be descriptive first, not a live ranking signal. It becomes a Candidate Finder criterion only after walk-forward validation proves it improves out-of-sample decisions.

## Product Problem

The current Lab answers:

> In historical gold-down or gold-up episodes, how often did this stock beat GDX/GDXJ?

That is useful, but it can hide time change.

Example:

- First 4 years: stock beat GDX 90% of the time.
- Last 4 years: stock beat GDX 10% of the time.
- All-history average: about 50%.

The 50% all-history number is mathematically true but decision-misleading. The user needs to see that behaviour changed.

The current benchmark comparison also answers only:

> Did it beat GDX/GDXJ?

It does not answer:

> Was it one of the best miners to own in that gold scenario?

That second question requires ranking the stock versus the miner universe in the same historical episodes.

## Existing Repo Grounding

Use the existing Lab data spine.

Relevant current facts:

- `golden_vector/lab/conditional_dial.py` already builds `dial_episodes_latest.parquet`.
- Episode rows already include:
  - `ticker`
  - `benchmark`
  - `horizon_weeks`
  - `gold_bucket`
  - `week_date`
  - `beat`
  - `alpha`
  - `alpha_simple`
  - `is_nonoverlap_anchor`
- `alpha_simple = exp(alpha) - 1`, which is the correct simple-return basis for user-facing percentages.
- `golden_vector/lab/walk_forward.py::effective_n()` already applies the key overlap correction:
  - effective independent observations = `n_weeks / horizon_weeks`
- The Lab already uses empirical-Bayes shrinkage and Wilson intervals.
- The Lab already has a config hash / stale-artifact pattern.

Do not compute any of this in `serve/`. Backend computes, persists, serve renders.

## Academic / Statistical Grounding

Use the corrections in:

- `reviews/codex/research_time_decay_and_regime_change_trading.md`
- `.claude/skills/predictive-models/SKILL.md`
- `reviews/codex/claude_predictive_layer_research.md`

Key rules:

1. **Overlapping forward labels are not independent.**
   A 13-week forward return sampled weekly shares most of its return window with adjacent rows. Raw row count overstates evidence.

2. **Use effective N, not raw N.**

   Unweighted:

   ```text
   effective_n = n_rows / horizon_weeks
   ```

   Decay-weighted:

   ```text
   kish_ess = (sum(weights)^2) / sum(weights^2)
   decay_effective_n = kish_ess / horizon_weeks
   ```

3. **Shrink small samples.**
   Recent history is often thin. A recent 10% hit rate from 2-3 effective episodes must not override all history without a warning.

4. **Shrink toward the right prior.**
   Recent-window rates should shrink toward the recent cross-sectional peer pool for the same scenario, not toward the same stock's all-history rate. Shrinking recent back toward same-stock all-history mechanically hides the very change we want to detect.

5. **Track alpha, not only beat rate.**
   Beat rate is binary. Alpha tells whether the size of outperformance is improving or fading.

6. **Trend tests must use independent anchors.**
   Use `is_nonoverlap_anchor == True` for Mann-Kendall / Theil-Sen trend tests. Do not run significance tests over every overlapping weekly row.

7. **Most cells should abstain.**
   With sparse independent episodes, the correct label is often `INSUFFICIENT_EVIDENCE`, not `IMPROVING` or `DETERIORATING`.

8. **Control multiple comparisons.**
   We test many tickers, horizons, benchmarks, and buckets. Use Benjamini-Hochberg FDR before showing confident trend labels.

## Feature 1: Behaviour Trend Over Time

### User Question

For one stock, benchmark, horizon, and gold scenario:

> Has this stock's behaviour improved, deteriorated, or stayed stable over time?

### Displayed Outputs

For the selected cell on `/lab/dial/<ticker>`:

| Display | Meaning |
| --- | --- |
| All history | Long-run baseline hit rate and alpha |
| Recent window | Last 4 years, or configured window |
| Older history | History before recent window |
| Decay-weighted | Uses all history but weights newer episodes more |
| Trend label | Deteriorating / improving / stable / insufficient |
| Effective N | Independent evidence count, not raw weekly rows |

Example wording:

```text
All history: 74% beat GDX, effective N 12.2.
Recent 4 years: insufficient independent evidence.
Recency-weighted: 63%, effective N 5.8.
Alpha trend: weakening, but not enough evidence for a confident label.
```

Avoid:

- "Forecast"
- "Probability of beating next time"
- "Regime detected"
- "This stock is now good/bad"

Use:

- "Recent history has weakened"
- "Recent history has improved"
- "No clear change"
- "Not enough independent evidence"

### Core Formulas

Age and decay weights:

```text
age_years_i = (latest_episode_date - week_date_i) / 365.25
weight_i = 0.5 ** (age_years_i / decay_half_life_years)
```

Weighted beat rate:

```text
decay_p_beat_raw = sum(weight_i * beat_i) / sum(weight_i)
```

Weighted effective N:

```text
kish_ess = (sum(weight_i) ** 2) / sum(weight_i ** 2)
decay_effective_n = kish_ess / horizon_weeks
```

Empirical-Bayes shrinkage:

```text
p_shrunk = (p_raw * effective_n + prior * prior_strength) / (effective_n + prior_strength)
```

Recent-vs-older delta:

```text
trend_delta = recent_p_beat_shrunk - older_p_beat_shrunk
```

### Priors

Use cross-sectional peer priors:

- All-history cell shrinks toward all-history peer pool for the same benchmark / horizon / bucket.
- Recent cell shrinks toward recent peer pool for the same benchmark / horizon / bucket.
- Older cell shrinks toward older peer pool for the same benchmark / horizon / bucket.
- Leave the current ticker out of its own prior.
- Equal-weight tickers in the prior pool so one ticker with many rows does not dominate.
- If peer pool effective N is too thin, fall back to neutral `0.5` and flag `THIN_PEER_POOL`.

### Trend Detection

Do not label a trend from the recent-vs-older gap alone. The gap is useful for display but unstable as a detector.

Use a joint gate:

1. Recent effective N passes floor.
2. Older effective N passes floor.
3. Absolute shrunk recent-vs-older gap passes threshold.
4. Two-proportion raw-rate p-value passes after Benjamini-Hochberg q adjustment.
5. Mann-Kendall trend on non-overlap anchors agrees in sign.
6. Anchor count passes floor.

Trend label:

```text
if sample floors fail:
    INSUFFICIENT_EVIDENCE
elif abs(delta) < threshold:
    STABLE
elif q_value > q_fdr:
    STABLE or INSUFFICIENT_EVIDENCE
elif mann_kendall_sign disagrees:
    MIXED
elif delta > 0:
    IMPROVING
else:
    DETERIORATING
```

For v1, prefer conservative `INSUFFICIENT_EVIDENCE` over over-labeling.

### Alpha Trend

Track continuous outperformance too.

Use `alpha_simple`, not log alpha, for user-facing values.

Columns:

- `alpha_median_all`
- `alpha_median_recent`
- `alpha_median_older`
- `alpha_median_decay`
- `alpha_q10_decay`
- `alpha_q90_decay`
- `alpha_trend_slope_per_year`
- `alpha_trend_mk_p`
- `alpha_trend_label`

Use:

- Weighted median for decayed alpha level.
- Theil-Sen slope on non-overlap anchors for alpha trend.
- Mann-Kendall p-value on non-overlap anchors for alpha trend significance.

Reason: a stock can keep beating GDX but by less and less. Beat rate misses that; alpha catches it.

## Feature 2: Peer-Universe Ranking

### User Question

For the same gold scenario:

> Was this stock one of the better miners, average, or one of the worst?

Benchmark comparison and peer ranking answer different questions:

| View | Question |
| --- | --- |
| Vs GDX/GDXJ | Did this stock beat the investable sector benchmark? |
| Vs miner peers | Was this stock good compared with alternative miners? |

We should show both.

### Event-Level Peer Rank

For each episode date, benchmark, horizon, and gold bucket:

1. Find all tickers with valid `alpha_simple` or forward return for that same event.
2. Rank them cross-sectionally.
3. Compute this stock's percentile among peers.

Use only tickers with valid data on that historical date. Do not compare against today's full universe if a ticker had no data then.

Definitions:

```text
peer_count = number of valid tickers in this event
peer_rank_1_best = rank by alpha_simple, descending
peer_percentile = 100 * (1 - (rank_1_best - 1) / (peer_count - 1))
```

So:

- `100` = best miner in that event
- `50` = middle of the pack
- `0` = worst miner in that event

Tie handling:

- Use average rank for ties.
- Persist both `peer_rank_1_best` and `peer_percentile`.

Minimum peer count:

- Require `peer_count >= min_peer_count`, default maybe `20`.
- If below floor, set `peer_status = THIN_PEER_POOL`.

### Aggregated Peer Metrics

For each ticker / benchmark / horizon / gold bucket:

| Metric | Meaning |
| --- | --- |
| `peer_percentile_median_all` | Typical rank across all history |
| `peer_percentile_median_recent` | Typical recent rank |
| `peer_percentile_median_older` | Older-history rank |
| `peer_percentile_decay` | Recency-weighted rank |
| `top_quartile_rate_all` | How often it was top 25% of miners |
| `bottom_quartile_rate_all` | How often it was bottom 25% |
| `top_quartile_rate_recent` | Recent top-quartile frequency |
| `bottom_quartile_rate_recent` | Recent bottom-quartile frequency |
| `peer_trend_delta` | Recent median percentile minus older median percentile |
| `peer_trend_label` | Improving / deteriorating / stable / insufficient |

Plain English examples:

```text
Vs miners: PRU was typically top 18% in similar gold-down episodes.
Recent peer rank has deteriorated: top 20% historically, middle of pack recently.
```

### Peer Ranking Should Not Replace Benchmark View

Keep both:

```text
Benchmark view:
PRU beat GDX 74% of the time; median alpha +12%.

Peer view:
PRU ranked top quartile among miners 61% of the time; recent peer percentile weakened.
```

The peer view is more useful for stock selection. The benchmark view is more useful for "why not just buy GDX/GDXJ?"

## Artifacts

### 1. `dial_behavior_trend`

Persist backend-computed, run-stamped and latest alias:

```text
dial_behavior_trend_{run_id}.parquet
dial_behavior_trend_latest.parquet
```

One row per:

```text
ticker, benchmark, horizon_weeks, gold_bucket
```

Core columns:

```text
schema_version
source_run_id
config_hash
ticker
benchmark
horizon_weeks
gold_bucket

all_n_rows
all_effective_n
all_p_beat_raw
all_p_beat_shrunk
all_alpha_median

recent_window_years
recent_n_rows
recent_effective_n
recent_p_beat_raw
recent_p_beat_shrunk
recent_alpha_median

older_n_rows
older_effective_n
older_p_beat_raw
older_p_beat_shrunk
older_alpha_median

decay_half_life_years
decay_kish_ess
decay_effective_n
decay_p_beat_raw
decay_p_beat_shrunk
alpha_median_decay
alpha_q10_decay
alpha_q90_decay

trend_delta_recent_vs_older
trend_p_value
trend_q_value
n_anchors
trend_tau
trend_mk_z
trend_mk_p
trend_label
trend_status
mde_80pct_pp

peer_count_median
peer_percentile_median_all
peer_percentile_median_recent
peer_percentile_median_older
peer_percentile_decay
top_quartile_rate_all
bottom_quartile_rate_all
top_quartile_rate_recent
bottom_quartile_rate_recent
peer_trend_delta
peer_trend_label
peer_trend_status

alpha_trend_slope_per_year
alpha_trend_n_anchors
alpha_trend_mk_z
alpha_trend_mk_p
alpha_trend_label
```

### 2. `dial_behavior_trend_points`

Persist backend-computed chart points:

```text
dial_behavior_trend_points_{run_id}.parquet
dial_behavior_trend_points_latest.parquet
```

One row per counted episode:

```text
schema_version
source_run_id
config_hash
ticker
benchmark
horizon_weeks
gold_bucket
week_date
beat
alpha_simple
is_nonoverlap_anchor
decay_weight
rolling_p_beat
rolling_effective_n
peer_count
peer_rank_1_best
peer_percentile
top_quartile
bottom_quartile
point_status
```

This gives the UI everything it needs without calculating ranks in serve.

## Config

Add validated config:

```text
config/lab_behavior_trend.yaml
```

Suggested defaults:

```yaml
version: 1
recent_window_years: 4
decay_half_life_years: 3
decay_overlap_deflation: horizon

min_all_effective_n: 8.0
min_recent_effective_n: 6.0
min_older_effective_n: 6.0
min_anchors: 8
min_peer_count: 20

trend_delta_threshold: 0.20
q_fdr: 0.10

eb_prior_strength: 10.0
recent_prior_min_pool_effective_n: 10.0

alpha_slope_threshold: 0.01
alpha_trend_p_threshold: 0.10

rolling_event_window: 12
top_peer_percentile_cutoff: 75
bottom_peer_percentile_cutoff: 25
```

All thresholds must be config-sourced and included in the Lab config hash.

## Shared Primitives To Extract First

Do this before building the new artifact. Avoid duplicated math.

Create or extend a Lab stats/helper module, for example:

```text
golden_vector/lab/statistics.py
```

Shared primitives:

```python
eb_shrink(p_raw, effective_n, prior, prior_strength)
pooled_prior(...)
decay_weights(dates, latest_date, half_life_years)
decay_effective_n(weights, label_horizon_weeks)
weighted_median(values, weights)
mann_kendall_test(values)
theil_sen_slope(dates, values)
benjamini_hochberg(p_values, q)
peer_percentile(values, target_value)
```

Refactor existing `_dial_cells` to reuse `eb_shrink()` and `pooled_prior()` so there is one shrinkage implementation.

`decay_effective_n()` should reuse `walk_forward.effective_n()` or exactly match its overlap convention.

## Backend Architecture

New backend module:

```text
golden_vector/lab/behavior_trend.py
```

Responsibilities:

1. Read `dial_episodes`.
2. Validate schema and config hash.
3. Compute event-level peer ranks.
4. Compute all/recent/older/decay summaries.
5. Compute trend labels with abstention gates.
6. Compute chart points.
7. Write run-stamped artifacts and latest aliases.

Serve layer:

```text
golden_vector/serve/lab_curve_data.py
golden_vector/serve/lab_curve_page.py
```

Serve responsibilities only:

- load persisted trend artifact;
- select rows for ticker/benchmark/horizon/bucket;
- render cards and SVGs;
- show stale/missing/insufficient messages.

No rate calculations, rank calculations, shrinkage, trend labels, or peer percentiles in serve.

## UI Plan

Location:

```text
/lab/dial/<ticker>
```

Place below the current profile / tilt summary and above the detailed distribution.

Section title:

```text
Behaviour Over Time
```

Cards:

1. **All History**
   - `74% beat GDX`
   - `effective N 12.2`

2. **Recent 4 Years**
   - `Not enough independent evidence`
   - or `28% beat GDX, effective N 6.4`

3. **Recency-Weighted**
   - `63% beat GDX`
   - `effective N 5.8`

4. **Vs Miner Peers**
   - `Typical rank: top 18%`
   - `Top quartile in 61% of episodes`

5. **Trend**
   - `Deteriorating`
   - `Stable`
   - `Insufficient evidence`

Charts:

1. **Episode timeline**
   - x-axis = time
   - green dot = beat GDX/GDXJ
   - red dot = lagged GDX/GDXJ
   - marker shape or border for non-overlap anchors

2. **Recency line**
   - rolling or decayed hit rate through time
   - no significance claim

3. **Peer percentile line**
   - 0-100 peer percentile through time
   - show 75 and 25 lines for top/bottom quartile

4. **Alpha trend**
   - optional small line or summary marker for median alpha trend

Text should be short:

```text
Recent episodes are shown separately because miner behaviour can change. The recency-weighted number uses all history but gives more weight to newer episodes. These are historical counts, not forecasts.
```

## Backtest Gate Before Candidate Finder

Do not use `trend_label`, `decay_p_beat`, or `peer_percentile_decay` in Candidate Finder ranking until validated.

Backtest design:

At each walk-forward date:

1. Use only episodes before date `t`.
2. Build all-history, recent, decay, and peer-rank features.
3. Predict future `beat` or future alpha over the selected horizon.
4. Compare:
   - all-history baseline;
   - recent-window rate;
   - decay-weighted rate;
   - peer percentile summary;
   - alpha trend.

Metrics:

- Brier score for beat probabilities.
- Calibration by bucket.
- Spearman IC for peer percentile / alpha trend vs future alpha.
- Top-minus-bottom quantile spread.
- Stability across folds.

Acceptance before ranking:

- beats all-history baseline out of sample;
- improvement is stable across folds;
- no look-ahead;
- sample-size gates remain honest;
- result is not one lucky period;
- variant count is logged in the Lab ledger.

If it fails, keep the panel as descriptive context only.

## Tests

### Math

- `decay_effective_n` equals raw Kish ESS at horizon 1.
- Uniform weights recover `n / horizon_weeks`.
- Weighted hit rate handles all-zero/all-one/mixed values.
- EB shrink pulls small samples toward the correct peer prior.
- Recent shrink uses recent peer prior, not same-stock all-history.
- Mann-Kendall uses only non-overlap anchors.
- Theil-Sen slope uses only anchors for inference.
- Benjamini-Hochberg q-values are monotonic and correct.
- Peer percentile gives 100 to best, 0 to worst, handles ties.

### Artifact

- Missing required episode columns fail loud.
- Config hash changes mark artifact stale.
- Thin recent/older/peer pool yields `INSUFFICIENT_EVIDENCE`, not a directional label.
- A synthetic 90% -> 10% deterioration with enough anchors labels `DETERIORATING`.
- A noisy flat series labels `STABLE` or `INSUFFICIENT`, not deteriorating.
- Peer rank uses only tickers with valid event data on that date.
- Early-date thin peer pools are flagged.

### Serve

- Serve renders persisted labels and metrics only.
- Static guard: no shrinkage, ranking, p-value, percentile, or trend math in serve.
- Missing/stale/corrupt trend artifact renders calm unavailable state.
- UI shows effective N beside every rate.
- UI says historical / exploratory / not forecast.

### Backtest

- Walk-forward feature generation uses only past episodes.
- Purge/embargo respected for overlapping labels.
- Labels and features never join future outcomes into live artifacts.

## Risks

| Risk | Mitigation |
| --- | --- |
| False trend labels from tiny samples | Effective N floors, anchors-only tests, FDR, abstain by default |
| User reads history as forecast | Wording: historical, exploratory, not forecast |
| Survivorship bias | Keep existing caveat; do not overstate; future project needs delisted/dead miners |
| Too much UI | Use compact cards and one timeline; keep method collapsed |
| Duplicated shrinkage/math | Extract shared primitives first |
| Peer ranking look-ahead | Rank only against tickers with valid data on that event date |
| Too many Candidate Finder knobs | Do not expose as criteria until backtested |

## Build Sequence

### Phase 0 - Extract Shared Math

- Add shared Lab statistics helpers.
- Refactor existing `_dial_cells` to use them.
- No user-facing behaviour change.
- Full focused Lab tests green.

### Phase 1 - Peer Event Ranks

- Compute peer rank / percentile for every episode.
- Persist in `dial_behavior_trend_points`.
- Add tests for event-date peer pools, ties, min peer count, and top/bottom quartile flags.

### Phase 2 - Behaviour Trend Artifact

- Compute all/recent/older/decay hit rates.
- Compute alpha trend.
- Compute peer aggregate summaries.
- Compute trend labels with abstention gates.
- Persist `dial_behavior_trend`.

### Phase 3 - Lab Dial UI

- Load trend artifacts in `lab_curve_data`.
- Render cards and timeline on `/lab/dial/<ticker>`.
- Keep all calculations backend-only.
- Add stale/unavailable UI states.

### Phase 4 - Walk-Forward Validation

- Backtest all-history vs recent vs decay vs peer-rank features.
- Publish scorecard, not a product ranking.

### Phase 5 - Optional Candidate Finder Integration

Only if Phase 4 passes:

- Add optional Candidate Finder criteria:
  - `recency_weighted_beat_rate`
  - `peer_percentile_decay`
  - `alpha_trend_slope`
  - `trend_label`
- Default off until Emanuel explicitly chooses to use them.

## Recommendation

Build Phase 0-3 as descriptive Lab insight. It directly solves Emanuel's concern:

> The old average can hide that recent behaviour changed.

Also add peer ranking because it answers a more useful stock-selection question:

> In this kind of gold move, was this stock actually one of the better miners?

Do not use either as a ranking signal until Phase 4 proves it beats the all-history baseline out of sample.
