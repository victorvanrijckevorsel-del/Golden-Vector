# Research: Time Decay, Regime Change, and Recency Weighting for Golden Vector

Author: Codex
Date: 2026-06-16
Purpose: give Claude and Emanuel a grounded design path for showing when a miner's historical behaviour has changed over time, so all-history averages do not hide deterioration or improvement.

## Executive Verdict

Emanuel's concern is correct. If a stock beat GDX 90% of the time in the first four years and only 10% in the last four years, the current all-history hit rate can show roughly 50% and hide the most important fact: the relationship changed.

The right fix is not to delete old data. Old data still carries information, especially in a small universe with sparse gold-down episodes. The right fix is to show three views side by side:

1. **All-history rate** - the stable descriptive baseline.
2. **Recent-window rate** - what happened in the last N years or last N independent episodes.
3. **Decay-weighted rate** - all observations count, but recent observations count more.

Then add a **trend-change label** only when the recent-vs-old gap is large and sample sizes are high enough. Do not call it a forecast until a walk-forward backtest proves that the recency layer improves next-period outcomes.

## Existing Repo Knowledge

I searched the repo's existing gold/options/predictive knowledge before looking outside.

Relevant local files:

- `reviews/codex/claude_predictive_layer_research.md`
- `reviews/codex/claude_predictive_layer_ideas.md`
- `reviews/codex/codex_predictive_layer_and_backtest_ideas.md`
- `reviews/codex/research_academic_grounding_gold_model.md`
- `reviews/codex/research_options_methodology_and_predictors.md`
- `reviews/codex/claude_lab_relative_performance_curve_plan_v3.md`
- `reviews/codex/codex_review_lab_data_storage_and_compute.md`
- `.claude/skills/predictive-models/SKILL.md`
- `golden_vector/lab/conditional_dial.py`
- `golden_vector/lab/beta_gap.py`
- `golden_vector/lab/walk_forward.py`

Repo facts that matter:

- The Lab already stores episode-level history in `data/lab/dial_episodes_latest.parquet`.
- Current episode rows include `ticker`, `horizon_weeks`, `benchmark`, `week_date`, `gold_bucket`, `alpha`, `alpha_simple`, `beat`, and `is_nonoverlap_anchor`.
- This is exactly the right data spine for a recency/trend layer. We do not need to compute this in serve.
- The existing Lab already uses:
  - empirical-Bayes shrinkage;
  - Wilson intervals;
  - effective N for overlapping forward windows;
  - walk-forward / purge logic;
  - a variant ledger.
- The local predictive skill already says miners have time-varying, firm-specific betas and that static beta is mis-specified.

The missing piece is a persisted, backend-computed view of **how the hit rate changes through time**.

## External Research Reviewed

### 1. Exponential decay is a standard risk-model idea, but it is not magic

RiskMetrics popularized exponentially weighted moving averages for financial risk. The practical idea is simple: recent observations get more weight than old observations, usually through a decay parameter.

Useful source:

- J.P. Morgan / Reuters, *RiskMetrics Technical Document* (1996), via MSCI: https://www.msci.com/documents/10199/5915b101-4206-4ba0-aee2-3449d5c7e95a
- Zumbach, G. O. (2007), *The RiskMetrics 2006 Methodology* (RiskMetrics Group; now hosted by MSCI) — note "2006" is the methodology name, published 2007; its contribution is long-memory (hyperbolic) decay, so for the plain EWMA/half-life standard the 1996 Technical Document above is the primary source: https://www.msci.com/research-and-insights/paper/rm2006-the-riskmetrics-2006-methodology

How this applies here:

- Use **half-life** instead of asking Emanuel to think about a lambda.
- Example: a 3-year half-life means an event from 3 years ago counts half as much as a fresh event; 6 years ago counts one quarter as much.
- Half-life is understandable, configurable, and testable.

Important caveat:

- Decay weighting can overreact if recent sample size is tiny. Golden Vector must pair every decay-weighted rate with an **effective sample size** and a **confidence label**.

### 2. Structural breaks are real, but formal break models are too heavy for v1

Bai and Perron formalized tests for multiple structural changes in regression models. Hamilton's regime-switching work models unobserved state changes. Pesaran and Timmermann show that when breaks exist, the best estimation window is a bias-variance tradeoff: old data may still help, but not always.

Useful sources:

- Hamilton (1989), *A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle*: https://www.jstor.org/stable/1912559 and https://ideas.repec.org/a/ecm/emetrp/v57y1989i2p357-84.html
- Bai and Perron (1998), *Estimating and Testing Linear Models with Multiple Structural Changes*: https://www.jstor.org/stable/2998540 and https://ideas.repec.org/a/ecm/emetrp/v66y1998i1p47-78.html
- Pesaran and Timmermann (2007), *Selection of Estimation Window in the Presence of Breaks*: https://ideas.repec.org/p/cam/camdae/1163.html and PDF: https://rady.ucsd.edu/_files/faculty-research/timmermann/estimation-window.pdf

How this applies here:

- Do not jump straight to Markov-switching or Bai-Perron break detection in the product UI.
- Start with a transparent, robust indicator:
  - recent-window hit rate;
  - older-window hit rate;
  - decay-weighted hit rate;
  - a large-gap flag only when both sides have enough events.
- Formal change-point tests can be a later research feature, not the first user-facing version.

### 3. Time-varying beta is directly relevant to gold miners

Golden Vector already knows this from its local research. Tufano's gold-miner work is particularly important: average miner exposure is high, but exposures vary across firms and over time. Adrian and Franzoni model time-varying betas with learning/Kalman-filter logic. Engle's DCC work gives a broader framework for time-varying correlations.

Useful sources:

- Tufano (1998), *The Determinants of Stock Price Exposure: Financial Engineering and the Gold Mining Industry*: https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00042 and SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=100317
- Adrian and Franzoni (2009), *Learning about Beta: Time-Varying Factor Loadings, Expected Returns, and the Conditional CAPM*, Journal of Empirical Finance 16(4):537-556, https://doi.org/10.1016/j.jempfin.2009.01.001 (FRBNY Staff Report 193: https://www.newyorkfed.org/research/staff_reports/sr193)
- Engle (2002), *Dynamic Conditional Correlation*: https://www.tandfonline.com/doi/abs/10.1198/073500102288618487 and NYU archive: https://archive.nyu.edu/handle/2451/26879

How this applies here:

- A miner's behaviour is not a fixed truth. It can change because of hedging, mine mix, leverage, country risk, dilution, or production changes.
- A recency layer should not just track hit rate. It should eventually track:
  - rolling/decayed down beta;
  - rolling/decayed up beta;
  - rolling/decayed alpha vs GDX/GDXJ;
  - rolling/decayed option signal behaviour once enough option history exists.

For v1, keep it simpler: start with **hit-rate and alpha-trend history** from Lab episodes.

### 4. Gold relationships are time-varying too

Gold's hedge/safe-haven behaviour is not constant. Baur and Lucey study constant and time-varying stock/bond/gold relationships. Beckmann, Berger, and Czudaj use a smooth-transition approach and find gold's hedge/safe-haven role is market-specific.

Useful sources:

- Baur and Lucey (2010), *Is Gold a Hedge or a Safe Haven?*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=952289 and Wiley: https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6288.2010.00244.x
- Beckmann, Berger, and Czudaj (2015), *Does Gold Act as a Hedge or a Safe Haven for Stocks? A Smooth Transition Approach*: https://ideas.repec.org/p/zbw/rwirep/502.html and PDF: https://www.econstor.eu/bitstream/10419/103324/1/796232105.pdf

How this applies here:

- The user should not see a miner's all-history gold-down behaviour as timeless.
- If a miner used to be defensive but has become pro-cyclical, the tool should surface that plainly.

### 5. Momentum/trend evidence supports recency, but should not become a gold forecast

Moskowitz, Ooi, and Pedersen document time-series momentum across futures, including commodities. This supports the idea that recent market behaviour may contain information, but Golden Vector should not turn it into a direct "gold will go up/down" forecast.

Useful source:

- Moskowitz, Ooi, and Pedersen (2012), *Time Series Momentum*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463 and RePEc: https://ideas.repec.org/a/eee/jfinec/v104y2012i2p228-250.html

How this applies here:

- Use gold trend as a conditioning/context variable or abstention flag.
- Do not build a short-horizon gold point forecast.
- The better product question remains: **which miners behave better or worse under a user-chosen gold scenario, and has that behaviour changed recently?**

### 6. Shrinkage is necessary because sample sizes are small

Efron/Morris/James-Stein style shrinkage is the right statistical instinct: noisy proportions should be pulled toward a reasonable prior. Golden Vector already does empirical-Bayes shrinkage in the Lab. The recency layer should keep that discipline.

Useful sources:

- Efron and Morris, *Data Analysis Using Stein's Estimator and Its Generalizations*: https://jhanley.biostat.mcgill.ca/bios602/MultilevelData/EfronMorrisJASA1975.pdf
- Efron and Morris, *Stein's Paradox in Statistics*: https://efron.ckirby.su.domains/other/Article1977.pdf
- Brown (2008), *In-season prediction of batting averages: A field test of empirical Bayes and Bayes methodologies*: https://arxiv.org/abs/0803.3697

How this applies here:

- Recent windows often have few independent gold-down episodes.
- If recent data says "10%" from only 3 effective episodes, it should not override 15 years of evidence.
- A good UI shows: raw recent, shrunk recent, all-history, and effective N.

## Recommended Feature: "Behaviour Trend" Layer

### Product Question

For one miner, one benchmark, one horizon, and one gold scenario:

> Has this miner's ability to beat GDX/GDXJ in this scenario improved, deteriorated, or stayed stable over time?

This should answer Emanuel's example directly.

### What the User Should See

On `/lab/dial/<ticker>`:

1. **All history**
   - "Across all counted gold-down episodes: 52% beat GDX."

2. **Recent history**
   - "Last 4 years / last N independent episodes: 18% beat GDX."

3. **Decay-weighted history**
   - "Recency-weighted: 27% beat GDX, effective N 9.4."

4. **Trend label**
   - "Deteriorating vs older history" only if:
     - recent minus older is below a negative threshold, e.g. <= -20 percentage points;
     - both windows have enough effective N;
     - the current scenario itself is not thin.

5. **Time chart**
   - x-axis = time;
   - dots = historical scenario episodes;
   - green = beat benchmark;
   - red = lag benchmark;
   - optional rolling/decay line = smoothed beat rate through time;
   - shaded region = recent window.

### Plain-English Wording

Use:

- "Recent history has weakened."
- "Recent history has improved."
- "No clear change."
- "Too little recent evidence."

Avoid:

- "Probability" unless calibrated out of sample.
- "Forecast."
- "Regime detected" unless a formal regime model is actually used.
- "This stock is now bad/good."

## Backend Design

### New Artifact

Create a backend-computed artifact, not serve-side math:

`dial_behavior_trend_{run_id}.parquet`

and latest alias:

`dial_behavior_trend_latest.parquet`

One row per:

`ticker, benchmark, horizon_weeks, gold_bucket`

Suggested columns:

| Column | Meaning |
|---|---|
| `schema_version` | trend artifact schema |
| `ticker` | miner ticker |
| `benchmark` | GDX or GDXJ |
| `horizon_weeks` | 4/8/13/26 etc. |
| `gold_bucket` | scenario bucket |
| `all_n_weeks` | all scenario episode count |
| `all_effective_n` | all-history effective N |
| `all_p_beat_raw` | raw all-history hit rate |
| `all_p_beat_shrunk` | EB-shrunk all-history rate |
| `recent_window_years` | config value, e.g. 4 |
| `recent_n_weeks` | recent episode count |
| `recent_effective_n` | recent effective N |
| `recent_p_beat_raw` | recent raw hit rate |
| `recent_p_beat_shrunk` | recent EB-shrunk hit rate |
| `older_n_weeks` | older episode count |
| `older_effective_n` | older effective N |
| `older_p_beat_raw` | older raw hit rate |
| `older_p_beat_shrunk` | older EB-shrunk hit rate |
| `decay_half_life_years` | config value |
| `decay_effective_n` | effective N under weights |
| `decay_p_beat_raw` | weighted hit rate |
| `decay_p_beat_shrunk` | weighted/shrunk hit rate |
| `trend_delta_recent_vs_older` | recent minus older |
| `trend_label` | IMPROVING / DETERIORATING / STABLE / INSUFFICIENT |
| `trend_status` | OK / THIN_RECENT / THIN_OLDER / THIN_ALL / MISSING |
| `config_hash` | staleness guard |

Optional companion artifact for the line chart:

`dial_behavior_trend_points_{run_id}.parquet`

One row per counted scenario episode:

`ticker, benchmark, horizon_weeks, gold_bucket, week_date, beat, alpha_simple, decay_weight, rolling_p_beat, rolling_effective_n`

### Config

Add a validated config file, for example:

`config/lab_behavior_trend.yaml`

Initial defaults:

```yaml
version: 1
recent_window_years: 4
decay_half_life_years: 3
min_all_effective_n: 8.0
min_recent_effective_n: 4.0
min_older_effective_n: 4.0
trend_delta_threshold: 0.20
rolling_event_window: 12
```

Why these defaults:

- 4 years is long enough to include several miner cycles but short enough to catch business change.
- 3-year half-life is intuitive and not too aggressive.
- The thresholds should be config-sourced and adjusted only after backtest evidence.

### Formulas

For each scenario episode `i`:

```text
age_years_i = (latest_episode_date - episode_date_i) / 365.25
weight_i = 0.5 ** (age_years_i / half_life_years)
decay_p_beat_raw = sum(weight_i * beat_i) / sum(weight_i)
decay_effective_n = (sum(weight_i) ** 2) / sum(weight_i ** 2)
```

Recent-vs-older:

```text
recent = episodes with week_date >= latest_date - recent_window_years
older = episodes before that cutoff
trend_delta = recent_p_beat_shrunk - older_p_beat_shrunk
```

Trend label:

```text
if any required effective N is below floor:
    trend_label = INSUFFICIENT
elif trend_delta >= trend_delta_threshold:
    trend_label = IMPROVING
elif trend_delta <= -trend_delta_threshold:
    trend_label = DETERIORATING
else:
    trend_label = STABLE
```

### Shrinkage

Reuse the Lab's existing empirical-Bayes spirit. Do not let tiny recent windows dominate.

The simplest v1:

```text
p_shrunk = (p_raw * effective_n + prior * prior_strength) / (effective_n + prior_strength)
```

Where:

- `prior` = all-ticker pooled rate for the same bucket/horizon/benchmark, or the existing Lab bucket prior.
- `prior_strength` = existing `EB_PRIOR_STRENGTH` unless the Lab team decides the recency layer needs its own config.

Important: if this duplicates `_dial_cells` shrinkage logic, extract a shared helper first. Do not add a second copy.

## UI Design

### Where It Should Live

Put it on the existing `/lab/dial/<ticker>` page, near the top, under the current profile/tilt summary.

Do not put it only in Option Trading. The time-change question is broader than options.

### Suggested UI Block

Title:

> Behaviour trend in this scenario

Cards:

| Card | Example |
|---|---|
| All history | 52% beat GDX, effective N 18 |
| Recent 4 years | 18% beat GDX, effective N 6 |
| Recency-weighted | 27% beat GDX, effective N 9 |
| Change | Deteriorating vs older history |

Chart:

- event dots through time;
- optional rolling/decay line;
- no bridges over gaps;
- show sample count and effective N.

### Beginner-Friendly Explanation

Short text only:

> Recent episodes are shown separately because miner behaviour can change. The recency-weighted number uses all history but gives more weight to newer episodes.

Avoid long essays. Put methodological detail in a collapsed `Method` section.

## Backtest Before Ranking

This is the most important discipline.

Do not let `decay_p_beat` or `trend_label` rank Candidate Finder immediately.

First run a walk-forward comparison:

At each historical date `t`:

1. Build all-history, recent-window, and decay-weighted features using only episodes before `t`.
2. Predict the next scenario episode or next forward window.
3. Score:
   - Brier score for beat probability;
   - log loss if probabilities are well-formed;
   - hit rate;
   - calibration by decile;
   - IC / rank spread if used cross-sectionally.
4. Compare against the current all-history baseline.

Acceptance gate before it affects ranking:

- decay-weighted rate beats all-history rate on Brier score out of sample;
- improvement is stable across folds, not one lucky period;
- sample-size and calibration remain acceptable;
- no hidden look-ahead from using future bucket membership.

If the test fails, still ship the trend view as descriptive evidence, but do not rank with it.

## What Not To Do

1. Do not replace all-history with recent-only.
   - That throws away too much evidence in a sparse miner universe.

2. Do not call recent deterioration a forecast.
   - It is a warning flag until validated.

3. Do not compute this in serve.
   - It is arithmetic over historical episodes and belongs in the Lab build.

4. Do not hide sample size.
   - Every displayed rate must carry raw N and effective N.

5. Do not use formal Markov-switching / Bai-Perron change points in v1.
   - They are academically legitimate, but too heavy and too easy to overstate for the current UX.

6. Do not add another shrinkage implementation.
   - Reuse/extract the existing Lab shrinkage primitive.

## Recommended Build Sequence

### Phase 1 - Research artifact and read-only display

- Add validated `lab_behavior_trend.yaml`.
- Build `dial_behavior_trend` from persisted `dial_episodes`.
- Add a tiny loader that fails STALE/CORRUPT/MISSING cleanly.
- Render the four cards + trend chart on `/lab/dial/<ticker>`.
- No Candidate Finder ranking changes.

### Phase 2 - Backtest

- Add a walk-forward evaluation comparing:
  - all-history rate;
  - recent-window rate;
  - decay-weighted rate;
  - simple rolling event-window rate.
- Store a scorecard with Brier score, calibration, and sample-size diagnostics.

### Phase 3 - Ranking integration only if proven

- If decay-weighted or trend-change metrics beat the baseline, expose them as optional Candidate Finder criteria.
- If not, keep them as descriptive warnings only.

## My Recommendation To Claude

Build the feature as a **Lab behaviour-trend layer**, not as a trading signal yet.

The product should say:

> "The full history says one thing, but the recent history has changed."

It should not yet say:

> "Therefore this stock is more likely to beat next time."

The strongest first version is:

- all-history vs recent vs decay-weighted;
- effective N everywhere;
- backend artifact;
- no serve arithmetic;
- no ranking use until walk-forward validation.

That gives Emanuel exactly the insight he wants while preserving Golden Vector's honesty standard.

## Source List

Local Golden Vector sources:

- `reviews/codex/claude_predictive_layer_research.md`
- `reviews/codex/claude_predictive_layer_ideas.md`
- `.claude/skills/predictive-models/SKILL.md`
- `reviews/codex/research_academic_grounding_gold_model.md`
- `reviews/codex/research_options_methodology_and_predictors.md`
- `reviews/codex/claude_gold_profile_dashboard_plan.md`
- `golden_vector/lab/conditional_dial.py`
- `golden_vector/lab/beta_gap.py`
- `golden_vector/lab/walk_forward.py`

External sources:

- J.P. Morgan / Reuters, RiskMetrics Technical Document: https://www.msci.com/documents/10199/5915b101-4206-4ba0-aee2-3449d5c7e95a
- Zumbach, G. O. (2007), The RiskMetrics 2006 Methodology (RiskMetrics Group; now hosted by MSCI): https://www.msci.com/research-and-insights/paper/rm2006-the-riskmetrics-2006-methodology
- Hamilton (1989), regime switching: https://ideas.repec.org/a/ecm/emetrp/v57y1989i2p357-84.html
- Bai and Perron (1998), structural breaks: https://ideas.repec.org/a/ecm/emetrp/v66y1998i1p47-78.html
- Pesaran and Timmermann (2007), estimation windows under breaks: https://ideas.repec.org/p/cam/camdae/1163.html
- Tufano (1998), gold-miner exposure: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=100317
- Adrian and Franzoni (2009), time-varying beta: https://ideas.repec.org/a/eee/empfin/v16y2009i4p537-556.html
- Engle (2002), dynamic conditional correlation: https://archive.nyu.edu/handle/2451/26879
- Baur and Lucey (2010), gold hedge/safe haven: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=952289
- Beckmann, Berger, and Czudaj (2015), smooth-transition gold hedge/safe haven: https://ideas.repec.org/p/zbw/rwirep/502.html
- Moskowitz, Ooi, and Pedersen (2012), time-series momentum: https://ideas.repec.org/a/eee/jfinec/v104y2012i2p228-250.html
- Efron and Morris, empirical-Bayes / Stein shrinkage: https://jhanley.biostat.mcgill.ca/bios602/MultilevelData/EfronMorrisJASA1975.pdf
- Brown (2008), empirical Bayes for binomial performance prediction: https://arxiv.org/abs/0803.3697

---

# Addendum (Claude): build-ready expert corrections

Author: Claude
Date: 2026-06-16
Status: extends Codex's note above. Where this addendum and the note conflict, **this addendum wins** — every change below is grounded first-hand in the live `data/lab/dial_episodes_latest.parquet` (434,442 rows, 65 tickers, 2006–2026) and in the repo primitives, with line numbers verified against the current tree.

## 0. TL;DR — what changes vs the note above

Codex's design (three views + trend label + backend artifact + backtest-before-ranking) is the right shape. Five things in it are statistically wrong or too thin to build safely. All five were found independently by separate expert passes and cross-checked against the real data.

| # | Codex said | Correct version | Why it matters |
|---|---|---|---|
| 1 | `decay_effective_n = (Σw)² / Σ(w²)` | `decay_effective_n = ((Σw)² / Σ(w²)) / h` — Kish ESS **divided by the horizon** | Our weekly `beat` rows are overlapping h-week labels → autocorrelated. Codex's formula is the ESS for *independent* draws. Without `/h` the confidence gates are ~h× too lax (13× at h=13) and the recent-vs-older z is inflated ~√h → systematic **false "behaviour changed" flags**. |
| 2 | Shrink toward "the existing Lab bucket prior" (ambiguous) | Shrink **each window toward its OWN window-matched cross-sectional peer pool** (recent→recent peers, older→older peers), leave-one-out, equal-ticker weight | Shrinking the recent window toward the **same stock's all-history** rate mechanically erases the regime change you are trying to surface (verified: a real 0.90→0.10 drop reverts to 0.79). |
| 3 | Trend label from a single recent-vs-older gap | **Mann-Kendall monotone-trend test on the independent non-overlap anchors**, with the 2-window gap kept only as a same-signed magnitude confirmer | The 2-window gap is cut-point-sensitive (one real cell flips sign between a 4-yr and an 8-yr cut). MK uses the whole shape, is distribution-free, and needs no new dependency. |
| 4 | Track the binary `beat` rate | Track **continuous `alpha`** too (decayed *median* + Theil-Sen/MK slope on anchors), and surface both | `beat` throws away win/loss size, so it is weak and slow at small N. The alpha trend flags ~5× more deteriorations and earlier — it is the *leading* indicator; beat rate is the *lagging* confirmation. |
| 5 | Label fires on a ≥20pp gap + effective-N floors | Add **Benjamini-Hochberg FDR control + a power/MDE reality check**; INSUFFICIENT EVIDENCE becomes the **common default** | Across ~2,600 cells a gap-only rule fires on ~43% of gated cells **under the null** (~577 false alarms). At our real eff_n (median ~11/window) only a near-total flip (90%→10%) is reliably detectable. |

The unifying theme: **honesty about how little independent evidence we actually have.** A cell with 158 weekly rows at h=13 has only ~12 independent episodes. Every gate, interval, and significance test must run on that real count, not the inflated weekly count.

---

## 1. CORRECTION — `decay_effective_n` must be deflated by the horizon

### The bug
Codex's `decay_effective_n = (Σwᵢ)² / Σ(wᵢ²)` is the **Kish effective sample size** — correct for *independent* weighted observations. But our `beat` rows are **not** independent: each is an h-week-forward label sampled every week, so consecutive rows share h−1 weeks of the same return path. The repo already knows this — `walk_forward.effective_n` (verified at `walk_forward.py:75-80`) is literally `n_weeks / h`, and its module docstring says *"overlapping h-week labels sampled weekly are NOT independent; effective_n divides by the horizon."*

### The fix
Compose the two corrections — they multiply:

```python
kish_ess          = (w.sum() ** 2) / (w ** 2).sum()          # Codex's number: unequal-weight ESS
decay_effective_n = effective_n(kish_ess, label_horizon_weeks=h)   # = kish_ess / h  ← use everywhere
```

Implement it as a tiny primitive so there is exactly **one** overlap-deflation in the codebase:

```python
# golden_vector/lab/walk_forward.py  (next to effective_n)
def decay_effective_n(weights, *, label_horizon_weeks):
    w = np.asarray(weights, dtype=float)
    kish = (w.sum() ** 2) / (w ** 2).sum()
    return effective_n(kish, label_horizon_weeks=label_horizon_weeks)   # reuses the /h, do NOT re-write n/h
```

### Why it's right (and verified on the real data)
- For the idealized overlap of i.i.d. weekly increments the autocorrelation is exactly triangular, ρ_k = max(1 − k/h, 0), and the variance-inflation factor `1 + 2·Σ_{k=1}^{h-1}(1 − k/h) = h` **exactly** — which is *why* `effective_n = n/h` is correct in the first place.
- **Two limit checks** (both confirmed numerically): uniform weights w≡1 over n weeks → `decay_effective_n = n/h` (recovers the existing primitive); h=1 (truly non-overlapping) → `decay_effective_n = kish_ess` (recovers Codex's formula). So `kish/h` is the unique consistent generalization.
- **Empirically:** the lag-k autocorrelation of `beat` decays almost perfectly linearly from 0.73 at lag 1 to ~0 at lag 13 (= h) and is noise beyond — the textbook MA(h−1) signature. `is_nonoverlap_anchor` rows number ≈ n/h (667 anchors vs 8,852 rows at h=13; ratio 13.3). The measured variance-inflation factor is 9.2 < 13, so `n/h` is mildly **conservative** (real beats are slightly less autocorrelated than the ideal because bucket conditioning re-randomizes membership) — it fails safe, never overstates evidence.
- **Impact if you skip `/h`:** at h=13 the gates accept cells with ~13× less real evidence than they think, and the recent-vs-older z-statistic measured 0.22 (raw n) vs 0.06 (correct effective n) on a real null cell — i.e. raw-n over-rejects by ~√h and manufactures "behaviour changed" alarms.

### Stamp & feed
Store `decay_effective_n` = Kish/h (optionally keep raw `decay_kish_ess` as a diagnostic only). Feed `decay_effective_n` — **not** raw n, **not** kish — into the existing shrink and Wilson primitives:

```python
p_shrunk      = (p_raw*decay_effective_n + prior*EB_PRIOR_STRENGTH) / (decay_effective_n + EB_PRIOR_STRENGTH)
wilson_low, wilson_high = _wilson_interval(p_raw, decay_effective_n)
```

---

## 2. CORRECTION — shrinkage target: window-matched cross-sectional peers, never the stock's own past

### The trap
Shrinking the **recent** window toward the **same stock's all-history** rate pulls the estimate back to the very value the recent window is supposed to contradict — it mechanically hides the regime change. Verified on the live artifact: a deteriorated cell (recent `p_raw=0.10`, recent eff_n≈1.6) shrinks to **0.79** toward its own 0.90 all-history. The change vanishes.

### The fix
Use a genuine empirical-Bayes prior that is **window-matched and leakage-free** — the generalization of what `_dial_cells` already does (verified at `conditional_dial.py:236-242`: the prior is the per-bucket *mean of per-ticker means*, equal ticker weight, so a long-history miner can't dominate):

```python
# per (horizon h, benchmark, bucket); leave-one-out over peers j != i; equal ticker weight
prior_recent_i = mean_j ( mean(beat over RECENT window for ticker j) )    # j != i
prior_older_i  = mean_j ( mean(beat over OLDER  window for ticker j) )    # j != i
```

Shrink each window toward its **own** contemporaneous peer pool, then take the difference:

```python
recent_p_shrunk = eb_shrink(recent_p_raw, recent_eff_n, prior_recent_i, EB_PRIOR_STRENGTH)
older_p_shrunk  = eb_shrink(older_p_raw,  older_eff_n,  prior_older_i,  EB_PRIOR_STRENGTH)
trend_delta     = recent_p_shrunk - older_p_shrunk      # priors largely cancel → true divergence survives
```

Because both windows are pulled toward near-equal peer pools (measured ~0.55 recent vs ~0.525 older for gold_down), the prior largely cancels in the *delta*, so a genuine divergence survives while pure single-cell noise is damped symmetrically. The same deteriorated cell above now shrinks to **0.49** toward peers (or 0.445 toward neutral 0.5) — noise tamed, signal preserved.

### Rules
- **Leave-one-out** the peer pool (exclude ticker i) so a stock is never partly shrunk toward itself.
- **Window-matched**: recent→recent pool, older→older pool. Mixing them re-couples the windows and re-dampens the signal.
- **Fallback**: use the cross-sectional prior only when `recent_pool_effective_n ≥ EB_PRIOR_STRENGTH (=10)` — i.e. the prior is at least as informative as the pseudo-count it injects; otherwise fall back to neutral 0.5 and stamp `recent_prior_source='neutral_0.5'`.
- **Never** use the stock's own all-history rate as the recent prior.
- **Survivorship**: the peer pool is built from 65 *surviving* tickers (no dead-miner records yet), so it is upward-biased — read it as a *relative* benchmark for divergence, not an absolute base rate.

This is also a one-copy win: extract the existing inline shrink at `conditional_dial.py:267` into `eb_shrink(p_raw, eff_n, prior, strength)` and the pooled-mean-of-means at `:236-242` into `pooled_prior(episodes, group_keys, leave_out=ticker)`, then call both from `_dial_cells` **and** the new trend builder.

---

## 3. CORRECTION — detector: Mann-Kendall on independent anchors, not a single window cut

### Why the 2-window gap alone is unsafe
It is cut-point-sensitive: on a real cell (IAG) the recent-minus-older swing is −0.305 at a 4-year cut but −0.099 at an 8-year cut — **same data, opposite verdict**. A label that flips with an arbitrary knob is not trustworthy.

### v1 detector
Run a **Mann-Kendall monotone-trend test** on the time-ordered `beat` values at the cell's **non-overlap anchor** rows (`is_nonoverlap_anchor == True` — by construction ≥ h weeks apart, so the independent sample, count ≈ effective_n). Pure numpy/math (scipy/statsmodels/sklearn are **not installed** — confirmed; do not add them):

```python
# anchors = beat values at is_nonoverlap_anchor==True, time-ordered; m = len(anchors)
S   = sum(sign(anchors[j] - anchors[i]) for i < j)
c0, c1 = (anchors == 0).sum(), (anchors == 1).sum()          # tie groups for a binary series
VarS = (m*(m-1)*(2*m+5) - (c0*(c0-1)*(2*c0+5) + c1*(c1-1)*(2*c1+5))) / 18
z    = 0.0 if (VarS <= 0 or S == 0) else (S - sign(S)) / sqrt(VarS)   # continuity-corrected
tau  = S / (0.5*m*(m-1))                                       # effect size (Kendall tau-b)
mk_p = math.erfc(abs(z) / sqrt(2))                            # two-sided normal approx, no scipy
```

Verified: on the user's literal motivating case (monotone 90%→10% over ~12 anchors) MK returns z=−2.64, p≈0.008, tau=−0.52; on noisy-flat data it correctly returns ~null (z≈−0.4). A logistic/WLS fit to the 158 overlapping rows instead **manufactures** significance from autocorrelated duplicates — the exact false-trend trap — and once its SE is honestly deflated to effective_n it never reaches |t|>1.65 across all 54 usable gold_down cells. The rank test is the right call at this N.

The 2-window gap stays **only** as a human-readable magnitude/direction companion and a same-signed confirmer — never as the significance gate.

---

## 4. CORRECTION — track continuous `alpha`, not just binary `beat`

`beat` is a thresholded projection of `alpha`: `beat_rate = P(alpha>0) = F_alpha(0)`, so a downward shift of the whole alpha distribution moves the beat rate only at rate `f_alpha(0)` (the density at zero). A cell whose alpha sits well above zero can lose half its edge with **no** beat-rate move until the mass crosses the line. That is why beat is slow and `alpha` is the leading indicator.

Verified (13w/GDX, 162 cells with ≥12 anchors): an MK trend on continuous alpha flags **10** cells at p<0.05 vs only **2** for the same test on binary beat; 9 alpha-trends are missed by beat against 1 the reverse (~5× detection power).

Compute, per cell, on the persisted `alpha_simple` (the ONE normalize boundary, `= exp(alpha)-1`, verified at `conditional_dial.py:274`):
- **`alpha_median_decay`** — recency-weighted **median** via Hazen cumulative-weight interpolation. Use the **median, not the mean**: measured log-alpha skew −2.63, kurtosis 40.3; one −5.4 tail episode drags a mean negative while the median is +0.001.
- **`alpha_trend_slope_per_year`** — **Theil-Sen** slope (median of pairwise slopes, ~29% breakdown, immune to the same tail outliers) on **anchors only**.
- **`alpha_trend_mk_z` / `alpha_trend_mk_p`** — Mann-Kendall on the same anchors (significance/direction).

**Load-bearing rule:** compute the slope and MK p-value **only on `is_nonoverlap_anchor` rows**. On the overlapping weekly rows the p-values collapse toward 0 and every cell looks "significant." Pin this with a test that feeds overlapping rows and asserts the test used ~n/h points. (The decayed *median level* may use all rows — it is a descriptive statistic, not an inference.)

**Track both, and treat disagreement as signal:** alpha = sensitive/leading ("each win is getting thinner"), beat = interpretable/lagging ("beat 7 of 10 times"). A cell can show a strong alpha decline with a flat beat rate (edge thinning but still winning) — that is information about which regime the cell is in, not a bug. Surface a cell as a warning when **either** crosses its gate.

---

## 5. CORRECTION — multiple comparisons + power: INSUFFICIENT must be the default

The universe is ~2,600 cells (65 tickers × 5 buckets × 4 horizons × 2 benchmarks; ~1,351 clear the eff_n≥8 floor). At the real per-window effective N (median ~11, 25th pct ~6):

- A **gap-only** rule fires on ~**43%** of gated cells **under the null** — roughly **577 false** "deteriorating/improving" flags.
- **Power is tiny.** Minimum detectable effect at 80% power ≈ **65pp at eff_n=8, 55pp at eff_n=12**. A true 20pp shift is detected with only ~12–16% power — essentially invisible. Only a near-total flip (90%→10%, ~98–100% power) is reliably catchable.

So the honest product stance is that **"not enough evidence to call a change" is the common, correct default**, and a confident label is rare. Enforce it with a real significance test + FDR control:

1. **Raw p-value** — two-sided two-proportion z-test on the **raw** window rates using per-window effective N (pooled SE). Run the test on the **raw** rates; use the **shrunk** delta only for the effect-size gate and display — do **not** double-shrink.
2. **FDR** — Benjamini-Hochberg at q=0.10 across the tested family; anchor the family size `m` to the ledger's existing `n_trials` (reuse `golden_vector/lab/ledger.py`, do not invent a new trial count). BH controls FDR under positive dependence (cells share tickers/buckets); do not silently upgrade to Bonferroni — it would push nearly everything to INSUFFICIENT.
3. **Persist `mde_80pct_pp`** per cell so the UI can say *"could only have caught a change bigger than X points."*

### The joint abstention gate (emit a directional label only if ALL hold; else INSUFFICIENT_EVIDENCE)
1. **Sample**: `recent_effective_n ≥ min_recent_effective_n` AND `older_effective_n ≥ min_older_effective_n` (default 6.0 each — below ~6 even a 65pp gap is under-powered).
2. **Effect**: `abs(trend_delta) ≥ trend_delta_threshold` on the **shrunk** rates (default 0.20).
3. **Significance after multiplicity**: BH-adjusted `q ≤ q_fdr` (default 0.10) on the **raw**-rate two-proportion p.
4. **Robustness**: Mann-Kendall on anchors agrees in sign (`sign(tau) == sign(trend_delta)`) and `n_anchors ≥ min_anchors` (default 8).

Then: `q≤q_fdr AND delta≥+thr AND tau>0` → IMPROVING; `q≤q_fdr AND delta≤−thr AND tau<0` → DETERIORATING; else STABLE if both windows powered; else INSUFFICIENT_EVIDENCE.

### Expectation-setter for Emanuel (verbatim-ready, plain English)
> "Most cells will say *'not enough evidence to call a change'* — that's correct, not a bug. With only ~6–12 independent episodes per window, we can reliably detect only a near-total flip (like beating 90% of the time dropping to 10%). A subtle 20-point drift is below our resolution, so we deliberately stay silent rather than flag noise. Without this discipline the tool would light up ~570 false 'deteriorating/improving' alarms across the universe."

---

## 6. Consolidated corrected spec (supersedes the note's table/config where they differ)

### Artifact columns — `dial_behavior_trend` (one row per ticker × benchmark × horizon_weeks × gold_bucket)
Keep Codex's column set, with these **corrections/additions**:
- `decay_effective_n` now stores **Kish/h** (not Kish). Optional diagnostic `decay_kish_ess`.
- `recent_prior_source` ∈ {`cross_sectional_recent`, `neutral_0.5`}, plus `recent_pool_effective_n`.
- Add the **continuous-alpha** columns: `alpha_median_all`, `alpha_median_recent`, `alpha_median_decay`, `alpha_decay_effective_n`, `alpha_q10_decay`, `alpha_q90_decay`, `alpha_trend_slope_per_year`, `alpha_trend_n_anchors`, `alpha_trend_mk_z`, `alpha_trend_mk_p`, `alpha_trend_label` ∈ {ALPHA_IMPROVING, ALPHA_DETERIORATING, ALPHA_STABLE, INSUFFICIENT}.
- Add the **beat-trend significance** columns: `n_anchors`, `trend_tau`, `trend_z`, `trend_mk_p`, `trend_p_value` (raw two-proportion), `trend_q_value` (BH-adjusted), `mde_80pct_pp`.
- `trend_status` ∈ {OK, THIN_RECENT, THIN_OLDER, THIN_ALL, THIN_PEER_POOL, MISSING}; `trend_label` ∈ {IMPROVING, DETERIORATING, STABLE, INSUFFICIENT_EVIDENCE}.
- `config_hash` folds in every threshold below (reuse `dial_config_hash`) so an edit invalidates the artifact.

### Config — `config/lab_behavior_trend.yaml` (validated; corrected defaults)
```yaml
version: 1
recent_window_years: 4
decay_half_life_years: 3
decay_overlap_deflation: horizon        # documents that decay_effective_n = Kish / horizon_weeks
min_all_effective_n: 8.0                 # reuse MIN_EFFECTIVE_N
min_recent_effective_n: 6.0              # per-window floor (NOT the 8.0 cell floor) — from the MDE table
min_older_effective_n: 6.0
min_anchors: 8                           # a slope/MK on < 8 independent points is noise
trend_delta_threshold: 0.20
q_fdr: 0.10                              # Benjamini-Hochberg
recent_prior_min_pool_effective_n: 10    # = EB_PRIOR_STRENGTH; else fall back to neutral 0.5
eb_prior_strength: 10.0                  # reuse EB_PRIOR_STRENGTH
alpha_slope_threshold: 0.01              # 1pp of simple alpha per year
alpha_trend_p_threshold: 0.10
rolling_event_window: 12
```

### Extract-first (one-copy rule — do this before the trend builder)
1. `eb_shrink(p_raw, eff_n, prior, strength)` ← from `conditional_dial.py:267`.
2. `pooled_prior(episodes, group_keys, *, leave_out=None)` ← from `conditional_dial.py:236-242` (the windowed peer prior and the all-history prior become one path).
3. `decay_effective_n(weights, *, label_horizon_weeks)` ← in `walk_forward.py`, reusing `effective_n`.

`_dial_cells` must be refactored to call #1 and #2 so there is no second copy. New serve surface (the `/lab/dial` cards) gets the static-scan no-arithmetic guardrail test (clone the Tool-D serve-arithmetic test in `tests/test_workspace_app.py`).

---

## 7. Revised build sequence

- **Phase 0 — extract shared primitives** (`eb_shrink`, `pooled_prior`, `decay_effective_n`); refactor `_dial_cells` onto them; full suite green. No behaviour change — pure de-duplication, so it's safe to land first.
- **Phase 1 — backend artifact + read-only display.** Build `dial_behavior_trend` from persisted `dial_episodes` with the corrected effective N, window-matched peer-shrinkage, MK-on-anchors detector, continuous-alpha columns, and the joint abstention gate (incl. BH-FDR). Fail-closed loader (STALE/CORRUPT/MISSING). Render the cards + time chart on `/lab/dial/<ticker>`. **No Candidate Finder ranking.** Pin the anchors-only-significance invariant with a test.
- **Phase 2 — walk-forward backtest** (Codex's gate, unchanged): decay/recency feature must beat the all-history baseline on out-of-sample Brier across folds, no look-ahead from future bucket membership.
- **Phase 3 — ranking only if proven.** If it passes, expose as an optional Candidate Finder criterion; otherwise keep it descriptive.

### Cross-cutting non-negotiables
- **Survivorship bias** (no dead-miner records yet) biases every trend statistic *optimistically* — never present STABLE/IMPROVING as reassurance; keep the exploratory caveat string on the artifact.
- **Descriptive, not predictive**, until Phase 2 passes: "the recent history has changed," never "therefore more likely to beat next time."
- At the **default 13w horizon the recent 4-yr gold_down window is genuinely too thin** for a label (median recent eff_n≈1.6; 0/65 tickers reach eff_n≥4). The label is only honestly supportable at 4w/8w — abstain (INSUFFICIENT) everywhere the floor isn't met rather than weaken the floor.

---

## 8. Additional sources (this addendum)

All references below were independently web-verified (existence, attribution, working URL, and claim-match) — see §9. DOIs are the canonical, stable links.

Overlap / effective-N:
- Kish (1965), *Survey Sampling*, Wiley — design effect / effective sample size (Σw)²/Σw² (the Kish ESS): https://archive.org/details/surveysampling0000kish
- Hansen & Hodrick (1980), *Forward Exchange Rates as Optimal Predictors of Future Spot Rates: An Econometric Analysis*, JPE 88(5):829-853 — overlapping h-step forecast errors form an MA(h−1) process (the structure that motivates deflating by the horizon; **cite for the MA(h−1) result only, not the numeric n/h rule**): https://doi.org/10.1086/260910
- Newey & West (1987), *A Simple, Positive Semi-Definite, HAC Covariance Matrix*, Econometrica 55(3):703-708 — Bartlett/triangular weighting + variance inflation for autocorrelated series: https://www.jstor.org/stable/1913610
- Richardson & Smith (1991), *Tests of Financial Models in the Presence of Overlapping Observations*, RFS 4(2):227-254 — overlap induces an MA error structure and reduces effective independent observations below the raw count: https://doi.org/10.1093/rfs/4.2.227
- Valkanov (2003), *Long-horizon regressions: theoretical results and applications*, JFE 68(2):201-232 — under overlap the t-statistic does not converge and extra overlapping observations add no proportional information (the t/√T rescaling is the overlap deflation): https://doi.org/10.1016/S0304-405X(03)00065-5
- Boudoukh, Richardson & Whitelaw (2008), *The Myth of Long-Horizon Predictability*, RFS 21(4):1577-1605 — overlapping long-horizon statistics are ~99% correlated across horizons under the null and overstate evidence (driven by overlap **and** regressor persistence): https://doi.org/10.1093/rfs/hhl042
  - Note: our `effective_n = n/h` is the **conservative** special case — the measured variance-inflation factor (9.2 at h=13) sits *below* h, and the efficient-estimation literature (Harri & Brorsen (2009), *The Overlapping Data Problem*, QQASS 3(3):78-115, https://ssrn.com/abstract=76460) shows GLS can recover information *beyond* the n/h floor, so n/h fails safe by under-counting. (Harri & Brorsen is cited here for that efficiency caution only — it does **not** assert the n/h rule.)

Robust trend / change:
- Mann (1945), *Nonparametric Tests Against Trend*, Econometrica 13(3):245-259: https://www.jstor.org/stable/1907187
- Kendall (1975), *Rank Correlation Methods*, 4th ed., Griffin — tau-b + tie-corrected var(S) (OCLC 3827024)
- Hamed & Rao (1998), *A modified Mann-Kendall trend test for autocorrelated data*, J. Hydrology 204:182-196 — autocorrelation inflates MK significance; correct via the effective variance: https://doi.org/10.1016/S0022-1694(97)00125-X
- Yue, Pilon, Phinney & Cavadias (2002), *The influence of autocorrelation on the ability to detect trend in hydrological series*, Hydrological Processes 16(9):1807-1829 — autocorrelation distorts MK trend detection; account for it (our fix: test on the independent non-overlap anchors): https://doi.org/10.1002/hyp.1095
- Yue & Wang (2004), *The Mann-Kendall Test Modified by Effective Sample Size to Detect Trend in Serially Correlated Hydrological Series*, Water Resources Management 18(3):201-218 — use effective N, not raw n, for MK significance: https://doi.org/10.1023/B:WARM.0000043140.61082.60
- Theil (1950), *A rank-invariant method of linear and polynomial regression analysis, I–III*, Nederl. Akad. Wetensch. Proc. 53:386-392, 521-525, 1397-1412 — originated the median-of-pairwise-slopes estimator: https://ir.cwi.nl/pub/18448
- Sen (1968), *Estimates of the Regression Coefficient Based on Kendall's Tau*, JASA 63(324):1379-1389 — the Theil-Sen rank-based robust slope: https://doi.org/10.1080/01621459.1968.10480934
- Hodges & Lehmann (1963), *Estimates of Location Based on Rank Tests*, Ann. Math. Statist. 34(2):598-611 — rank-based location estimators (median of pairwise averages): https://doi.org/10.1214/aoms/1177704172
- Hampel (1971), *A General Qualitative Definition of Robustness*, Ann. Math. Statist. 42(6):1887-1896 — introduced the breakdown-point concept: https://doi.org/10.1214/aoms/1177693054
- Huber (1981), *Robust Statistics*, Wiley — the median's ½ breakdown point + M-estimation robustness (**cited for the median only**; breakdown-point *concept* → Hampel 1971; Theil-Sen → Sen 1968 / Theil 1950): https://doi.org/10.1002/0471725250

Shrinkage:
- James & Stein (1961), *Estimation with Quadratic Loss*, Proc. 4th Berkeley Symp. 1:361-379 — foundational shrinkage theorem (dominates the sample mean for ≥3 dimensions): https://projecteuclid.org/euclid.bsmsp/1200512173
- Efron & Morris (1975), *Data Analysis Using Stein's Estimator and Its Generalizations*, JASA 70(350):311-319 — shrink each unit toward the cross-unit grand mean: https://doi.org/10.1080/01621459.1975.10479864
- Efron & Morris (1977), *Stein's Paradox in Statistics*, Scientific American 236(5):119-127 — lay exposition: https://efron.ckirby.su.domains/other/Article1977.pdf
- Brown (2008), *In-season prediction of batting averages*, Ann. Appl. Stat. 2(1):113-152 — EB toward a contemporaneous cross-sectional mean beats raw rates: https://arxiv.org/abs/0803.3697

Multiplicity / power:
- Benjamini & Hochberg (1995), *Controlling the False Discovery Rate*, JRSS-B 57(1):289-300 — the step-up FDR procedure (**proven for independent tests**): https://doi.org/10.1111/j.2517-6161.1995.tb02031.x
- Benjamini & Yekutieli (2001), *The Control of the False Discovery Rate in Multiple Testing under Dependency*, Ann. Statist. 29(4):1165-1188 — FDR under PRDS / arbitrary dependence (**use this when cells are correlated**): https://doi.org/10.1214/aos/1013699998
- Cohen (1988), *Statistical Power Analysis for the Behavioral Sciences*, 2nd ed., Lawrence Erlbaum — power/MDE; Ch. 6 defines Cohen's h for two-proportion tests: https://doi.org/10.4324/9780203771587
- Newcombe (1998a), *Two-sided confidence intervals for the single proportion: comparison of seven methods*, Stat. Med. 17(8):857-872: https://doi.org/10.1002/(SICI)1097-0258(19980430)17:8%3C857::AID-SIM777%3E3.0.CO;2-E
- Newcombe (1998b), *Interval estimation for the difference between independent proportions: comparison of eleven methods*, Stat. Med. 17(8):873-890 — Wilson-score interval for the difference of proportions: https://doi.org/10.1002/(SICI)1097-0258(19980430)17:8%3C873::AID-SIM779%3E3.0.CO;2-I
- Wilson (1927), *Probable Inference, the Law of Succession, and Statistical Inference*, JASA 22(158):209-212 — the Wilson score interval (our `_wilson_interval`): https://www.jstor.org/stable/2276774

Repo grounding (verified first-hand, current tree): `walk_forward.py:75-80` (`effective_n = n/h`, with the overlap docstring); `conditional_dial.py:74` (`MIN_EFFECTIVE_N=8`), `:75` (`EB_PRIOR_STRENGTH=10`), `:236-242` (per-bucket mean-of-per-ticker-means pooled prior), `:267-269` (EB shrink), `:274` (`alpha_simple = exp(alpha)-1`), `:364` (`_wilson_interval`), `:386/476` (`is_nonoverlap_anchor`); empirical checks on `data/lab/dial_episodes_latest.parquet` (434,442 rows, 65 tickers, 2006–2026).

---

## 9. Citation verification log (Claude, 2026-06-16)

Every academic citation in this document — Codex's original note **and** this addendum — was independently verified against the live web (existence, attribution, working URL, and **claim-match against the actual source**), one verifier per citation plus a senior audit; the replacement and co-cite sources above were then verified the same way *before* being added. **Result: high confidence. All cited works exist — no fabricated references.** Of the original 30, 21 were correct as-is. Findings and corrections:

**One real defect (now fixed).** This addendum had cited **Britten-Jones, Neuberger & Nolte (2011)** for "effective sample ≈ n/h." A full-text read found the paper *never states* the n/h rule — it is a data-aggregation method for overlapping regressions, not the effective-N heuristic. **Removed.** The overlap deflation is now grounded in Hansen-Hodrick (1980) for the MA(h−1) error structure plus **Richardson-Smith (1991), Valkanov (2003), and Boudoukh-Richardson-Whitelaw (2008)**, which do establish that overlapping observations carry far less independent information than the raw count. Our `effective_n = n/h` is the conservative end of that range (measured VIF 9.2 < 13).

**Rejected on claim-match.** Harri & Brorsen (2009) was a candidate n/h source but it actually argues *against* treating n/h as the usable information (GLS recovers more), so it is cited only as the efficiency caution that makes n/h conservative — never as the n/h justification.

**Precision corrections applied** (real papers, fixed details): RiskMetrics-2006 (author is **Zumbach**, not "MSCI"; year **2007** not 2006; for plain EWMA the 1996 doc is the primary source); Adrian-Franzoni URL (broken `.html` suffix → no-extension NY Fed URL); Hansen-Hodrick (full title + DOI; claim narrowed to MA(h−1) only); Yue-Wang-2004 title (`…Hydrological Series`, not `…Data`); Huber-1981 narrowed to the median/breakdown-point, with **Hampel (1971)** added for the breakdown-point concept and **Theil (1950)** for the Theil-Sen origin; Cohen-1988 and Benjamini-Hochberg-1995 DOIs added (+ dependence caveat → Benjamini-Yekutieli 2001); Newcombe-1998 split into both companion papers with full titles + DOIs.

**Co-cites added for completeness** (all verified): James & Stein (1961) foundational shrinkage theorem; Theil (1950); Hampel (1971); Yue-Pilon-Phinney-Cavadias (2002).

**Re-examined for over-claiming and confirmed sound:** Moskowitz-Ooi-Pedersen (2012) and Bai-Perron (1998) — their caveats are already stated in the note.

The two factual errors in Codex's original source list (RiskMetrics-2006 attribution; Adrian-Franzoni URL) have also been corrected inline above in §"External Research Reviewed" / the source list.
