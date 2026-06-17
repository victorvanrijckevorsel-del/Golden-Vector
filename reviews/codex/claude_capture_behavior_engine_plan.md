# Plan: Symmetric Capture & Behaviour Engine (Lab)

Author: Claude
Date: 2026-06-17
Status: ✅ READY TO CODE — Codex's 8 findings + Claude's 4 re-review refinements folded in (§13); all
3 §12 decisions confirmed by Emanuel 2026-06-17 (Convex offense default · gold-only capture · 13w
levels / 8w trend labels).
Grounded first-hand in the current tree
(`conditional_dial.py`, `forward_returns.py`, `walk_forward.py`, `structural.py`,
`relative_behavior.py`, `tool_c.py`, the serve Lab modules, `config_models.py`) and cross-checked
against `.claude/skills/predictive-models/SKILL.md`,
`reviews/codex/research_time_decay_and_regime_change_trading.md`, and
`reviews/codex/codex_plan_behavior_trend_and_peer_ranking.md`.

Supersedes nothing yet; it absorbs the trend research + Codex's peer-ranking idea and reframes both
inside one symmetric engine. Where this plan and the two source docs differ, **this plan wins** and
says why.

---

## 0. TL;DR

Emanuel's requirement, in his words: *"the tool should always go in both directions — identify
stocks good for hedging but also stocks that would increase a lot. The beta works both ways."* Plus:
*"compare it with peers and the GDX(J)."*

So we do **not** build a hedging tool. We build a **direction-agnostic behaviour engine** that reads
each miner across the whole gold-move spectrum and answers, through **three reference frames**:

| Lens | Question | Metric (mostly already exists) |
|---|---|---|
| **vs GOLD** | How much of gold's move does it take, down vs up? ("beta both ways") | **Up/Down capture ratios + convexity** (NEW; industry-standard) |
| **vs GDX/GDXJ** | Is it worth owning over the ETF? | **P(beat) + median alpha**, shown down vs up (EXISTS — extend) |
| **vs PEERS** | Was it one of the *best miners* to own in that move? | **Cross-sectional percentile** (NEW, point-in-time) |

Each lens is computed **symmetrically** (gold-down *and* gold-up buckets) and gets a **time/trend
layer** so the all-history average can never hide a regime change. The two-axis output —
**down-capture × up-capture** — sorts every miner into four honest archetypes:

```
                 UP-CAPTURE (offense, gold rising)
                 low                         high
              ┌──────────────────┬──────────────────┐
   DOWN   good│  HEDGE           │  CONVEX ★        │
   RESIL.     │  holds up when   │  cushioned down, │
  (defense,   │  gold falls,     │  explosive up    │
  gold falling├──────────────────┼──────────────────┤
   high=good)bad│  DEAD WEIGHT   │  TORQUE          │
              │  lags both ways  │  rips up, brutal │
              │                  │  down            │
              └──────────────────┴──────────────────┘
```

**One spine, both directions, three lenses, descriptive-until-backtested.** The hedge view, the
torque view, the convex hunt, and a future "who's decaying / who's waking up" universe scan are all
thin reads of the same engine.

### What this plan changes vs the two source docs
1. **Reframes "behaviour trend" from hedging-only to fully symmetric** (down *and* up), with capture
   ratios as the magnitude backbone — directly answers "beta both ways."
2. **Adds the GOLD reference frame** (capture/convexity) the trend docs lacked; keeps GDX(J) (alpha)
   and peers (percentile) so all of Emanuel's three comparisons are covered.
3. **Demotes the heavy verdict machinery** (MK/FDR/labels) behind a *descriptive picture first*,
   matching "match rigor to risk" and "simplest thing that could work first."
4. **Confirms the peer-*trend* stays deferred** (survivorship poisons it — see §7), but the peer
   *snapshot* ships early.
5. **Pins the one schema change** that unlocks everything: persist the miner's own forward return.

---

## 1. The data spine — what exists, and the one change needed

The Lab already persists an episode spine, `dial_episodes_latest.parquet` (verified
`conditional_dial.py:375-387`), one row per `(ticker, horizon_weeks, benchmark, week)`:

```
ticker, horizon_weeks, benchmark, week_period, week_date,
gold_fwd_simple, gold_bucket, alpha, alpha_simple, beat, is_nonoverlap_anchor
```

- `gold_fwd_simple` — gold's forward simple return over the horizon → **the conditioning driver, already here.**
- `alpha` (log), `alpha_simple` (= `exp(alpha)-1`) — miner *minus benchmark* forward return → the GDX(J) lens, already here.
- `beat` = `alpha > 0` → already here.
- `is_nonoverlap_anchor` — every h-th episode per ticker, ≥ h weeks apart → the **independent** sample for any significance test, already here (`conditional_dial.py:483-496`).

**The single missing ingredient: the miner's OWN forward return.** Capture ratios (vs gold) and peer
rank (which miner did best) both need the miner's absolute return, not just its alpha vs GDX.
`build_forward_return_panel` already computes it as `fwd_log_ret_{h}w`
(`forward_returns.py:46-48`) — it is simply dropped before the episode artifact is built. So:

> **Schema change (one line of compute + a version bump):** carry `fwd_log_ret` through
> `build_episode_artifact` and persist `stock_fwd_simple = exp(fwd_log_ret) - 1`. Bump
> `DIAL_SCHEMA_VERSION 3 → 4`. The config-hash + loader already fail STALE on a version bump, so old
> artifacts self-invalidate.

`bench_fwd_simple` is **not** persisted but is exactly recoverable (`stock_fwd − alpha` in log space);
we don't need it for v1 (gold capture uses gold; peer rank uses stock return; GDX lens uses alpha).
Leave it out until a metric needs it.

Peer percentile is also per-episode and point-in-time, so it belongs **on the episode row** (compute
once, persist): add `peer_count`, `peer_percentile` (see §4.3).

---

## 2. The three reference frames (symmetric by construction)

The buckets already span the full spectrum and the down/up partitions are already derived **once**
from the bounds (`conditional_dial.py:40-72`): `DOWN_BUCKETS` (high bound ≤ 0), `UP_BUCKETS` (low
bound ≥ 0), with `gold_flat` in neither. The engine reuses these — it never hardcodes "down" or
"hedge."

### 2.1 vs GOLD — capture ratios + convexity (NEW)
The literal "beta both ways." For a `(ticker, horizon)`:
- **Down-capture** = how much of gold's drop the miner ate (low = good hedge).
- **Up-capture** = how much of gold's rally the miner grabbed (high = good torque).
- **Convexity** = up-capture − down-capture (high = the CONVEX dream).

Industry-standard (Morningstar up/down-capture), so it satisfies the "industry-standard metrics
only" rule. Math + robustness in §4.1.

### 2.2 vs GDX / GDXJ — beat-rate + alpha (EXISTS, extend)
`P(beat)`, shrunk `P(beat)`, Wilson interval, median alpha + 10–90% range are already computed per
`(ticker, benchmark, horizon, bucket)` (`_dial_cells`). We do **not** rebuild this. We:
- present it **symmetrically** (down buckets vs up buckets, which `build_profile_artifact` already
  aggregates into `gold_tilt`), and
- add the **trend layer** (§4.2) on top of the existing `beat`/`alpha` episode columns.

### 2.3 vs PEERS — cross-sectional percentile (NEW, point-in-time)
For each episode `(week, horizon, benchmark, bucket)`, rank every miner that **had valid data that
week** by `stock_fwd_simple`; the miner's percentile (100 = best that week, 0 = worst) is persisted on
its episode row. Aggregate to a **snapshot** ("typically top 18% in gold-down weeks"). The peer
*trend* is deferred (§7).

> All three lenses already share one grain (the episode) and one set of honesty primitives. That is
> what makes this a foundation rather than three features.

---

## 3. Financial soundness (cross-checked)

1. **Capture ratios are recognized, not invented** (Morningstar). Convexity = up-capture −
   down-capture is a transparent difference of two standard numbers, not an opaque composite. The
   four archetypes are a **2-D classification from two standard metrics with explicit config
   thresholds**, not a blended score — this stays on the right side of "industry-standard metrics
   only / no opaque composite scores."
2. **Miner convexity is real, not wishful.** Miners are option-like on gold (margins compress, so
   effective beta rises as gold falls *and* as gold rises — SKILL §2; Tufano). A name that is
   cushioned on the way down and explosive on the way up genuinely exists and is exactly what the
   CONVEX quadrant hunts.
3. **Bucket conditioning makes the capture ratio numerically stable.** The usual capture-ratio
   weakness — dividing by a near-zero benchmark move — cannot bite here: down buckets are gold ≤ −5%
   and up buckets are gold ≥ +5%, so the denominator is bounded away from zero by construction.
   `gold_flat` is excluded (capture is undefined when gold ≈ 0).
4. **Breadth-starved, so descriptive-first is correct** (SKILL §1/§3: ~60 names ⇒ IR is capped by
   breadth, ML is hopeless). We evaluate by **quantile spread / IC**, show **calibrated frequencies
   with sample size**, and let nothing rank live until a walk-forward backtest passes (§9 Phase 5).
5. **Survivorship is the load-bearing caveat.** Universe = 65 *survivors* (no dead-miner records —
   `conditional_dial.py:1141`). This biases every behaviour statistic *optimistically* and, crucially,
   **poisons cross-sectional peer *trends*** (§7). Capture/beat/alpha trends for a single name are
   far less affected (the name compares to itself over time), but the survivor-only caveat string
   stays stamped on every artifact, and "STABLE/IMPROVING" is never sold as reassurance.

---

## 4. Mathematical specification

All math is **pure numpy/math** (scipy/statsmodels/sklearn are **not** installed — confirmed in
`requirements.txt`; do **not** add them). Every rate/ratio is stamped with its **effective N** (real
independent episode count), never the inflated weekly count.

### 4.0 Effective N (reuse, with the decay generalization)
`effective_n(n_weeks, label_horizon_weeks) = n_weeks / h` already exists
(`walk_forward.py:75-80`) and is the conservative-but-correct overlap deflation (research doc §1).
For decay-weighted aggregates, compose Kish ESS with the same `/h`:

```python
# golden_vector/lab/statistics.py
def decay_effective_n(weights, *, label_horizon_weeks):
    w = np.asarray(weights, float)
    kish = (w.sum() ** 2) / (w ** 2).sum()          # unequal-weight ESS
    return effective_n(kish, label_horizon_weeks=label_horizon_weeks)  # reuse /h — do NOT re-derive
```
Limit checks (must be unit tests): uniform weights → `n/h`; `h=1` → Kish. Feed `decay_effective_n`
(not raw n, not Kish) into shrink + Wilson.

### 4.1 Capture vs gold (direction-level, per ticker × horizon)
Capture is identified across a **whole direction** (all down buckets pooled, all up buckets pooled) —
not per single bucket — so the gold range is wide enough for a stable estimate (matches how
`build_profile_artifact` aggregates down vs up). Let `r_i = stock_fwd_simple`, `g_i =
gold_fwd_simple` over a ticker's down (resp. up) episodes:

```
down_capture = mean(r_i | gold_bucket ∈ DOWN_BUCKETS) / mean(g_i | gold_bucket ∈ DOWN_BUCKETS)
up_capture   = mean(r_i | gold_bucket ∈ UP_BUCKETS)   / mean(g_i | gold_bucket ∈ UP_BUCKETS)
convexity    = up_capture - down_capture
```
- **Ratio-of-means** (the standard capture definition), not mean-of-ratios — avoids per-episode
  blow-ups and matches Morningstar. Denominator bounded away from 0 by bucket conditioning (§3.3).
- **Interpretation:** `down_capture < 1` defensive (good hedge); `up_capture > 1` torque;
  `convexity > 0` convex.
- **Honesty:** attach `down_effective_n`, `up_effective_n`; if either side is below
  `min_direction_effective_n` the capture for that side is `null` with `capture_status =
  THIN_DOWN/THIN_UP/THIN_BOTH`. Persist the two component means so serve never divides.
- **Robustness companion:** also persist a **median-based** capture (`median(r)/median(g)`) as a
  diagnostic — miner returns are heavy-tailed (research doc: log-alpha skew −2.63), and a large
  mean/median gap is itself a "tail-driven, treat with care" flag.
- **Reconciliation with `structural.py` up/down beta (§7):** that is a *contemporaneous, 1-week OLS
  slope* feeding Tool A/C; this is a *forward h-week scenario capture* with the Lab honesty layer.
  Different horizon, different estimator, different question. Reuse the regime *definition*; do not
  reuse the number.

**Archetype** (a label from two standard metrics + config thresholds, not a score):
```
hedgey  = down_capture <= hedge_down_capture_max         # e.g. <= 0.8
torquey = up_capture   >= torque_up_capture_min          # e.g. >= 1.2
CONVEX ★ if hedgey and torquey
HEDGE     if hedgey and not torquey
TORQUE    if torquey and not hedgey
DEAD WEIGHT if not hedgey and not torquey
INSUFFICIENT if capture_status != OK
```

### 4.2 Trend layer (per ticker × benchmark × horizon × bucket, and per capture side)
This is the research-doc machinery (folded in, corrected). Recent-vs-older + decay, then a gated label.

> **EVENT-TIME windows, not calendar windows (measured correction, 2026-06-17).** A live check on
> `dial_episodes_latest.parquet` (65 tickers, 2006–2026) killed the original "last 4 calendar years"
> recent window: gold has mostly *risen* in 2022–2026, so in the last 4 calendar years **0/65** miners
> reach ≥6 independent gold-DOWN episodes at **any** horizon (median recent eff_n: 3.2@4w, 1.9@8w,
> 1.2@13w, 0.1@26w), while the gold-UP side is plentiful (8.7–14.2 at 4–13w). A calendar window
> therefore measures "how often gold happened to fall lately," not "did this stock's behaviour
> change." **Fix:** define the recent window in EVENT TIME — the most recent `recent_episodes`
> independent anchors vs the older anchors (split at the anchor count, e.g. recent half vs older
> half). All-history independent-episode depth is ample (down: 23.8@4w / 17.5@8w / 13.0@13w / 7.8@26w;
> up: 49.8 / 38.5 / 30.1 / 20.4), so a recent-half/older-half split clears the ≥6 floor at 4w/8w on
> BOTH directions, is marginal at 13w on the down side, and abstains at 26w. This both removes the
> gold-regime confound and restores 8w as an honest trend default.

- **Decay weights:** `weight_i = 0.5 ** (age_rank_i / half_life_episodes)` where `age_rank_i` is the
  episode's position back from the latest **independent anchor** (event-time), NOT calendar age — so
  decay is paced by evidence, not by how long gold sat still. (A calendar half-life is kept only as a
  diagnostic.)
- **Window-matched, leave-one-out, cross-sectional peer shrinkage** (research §2 — NOT the stock's
  own past, which would erase the very change we hunt): each window (recent/older/all/decay) shrinks
  toward the equal-ticker-weight peer pool for the **same window × bucket × horizon × benchmark**,
  excluding the ticker. `trend_delta = recent_p_shrunk − older_p_shrunk`; priors largely cancel in the
  delta. Falls back to neutral 0.5 with `recent_prior_source` stamped if the peer pool is thin.
- **Detector = Mann-Kendall on `is_nonoverlap_anchor` rows only** (research §3): continuity-corrected
  z, tie-aware var(S), τ effect size, `erfc`-based two-sided p — all pure-numpy. Running MK on
  overlapping weekly rows manufactures significance; pin "anchors-only" with a test.
- **Track continuous alpha too** (research §4): `alpha_median_decay` (weighted **median**, robust to
  the heavy tail), Theil-Sen slope on anchors, MK on anchors. Alpha (size) leads; beat (count) lags;
  surface both and treat divergence ("still wins, by less") as signal.
- **Capture trend:** compute down/up capture in recent vs older vs decay windows (decay-weighted
  capture = `Σ(w·r)/Σ(w·g)` per direction). v1 keeps this **descriptive** (delta + decay, gated by
  the effective-N floors) — no MK p-value on a derived ratio series (awkward at this N); the rigorous
  significance tests live on beat + alpha. State this limitation explicitly.

### 4.3 Peer percentile (per episode, point-in-time)
Within each `(week_period, horizon_weeks, benchmark, gold_bucket)` group, over tickers with a valid
`stock_fwd_simple` **on that week**:
```
peer_count      = number of valid tickers in the event
peer_rank_1_best= average-rank of this ticker by stock_fwd_simple, descending (ties → average)
peer_percentile = 100 * (1 - (peer_rank_1_best - 1) / (peer_count - 1))   # 100=best, 0=worst
```
- **Point-in-time membership** (only tickers present that week — never today's universe).
- `peer_count < min_peer_count` (default 20) → `point_status = THIN_PEER_POOL`, percentile null.
- **Snapshot aggregate** per `(ticker, benchmark, horizon, bucket)`: median percentile (all / recent
  / older / decay), `top_quartile_rate`, `bottom_quartile_rate`. **No peer-trend label in v1** (§7).

### 4.4 Multiplicity + abstention (the honest default)
With ~thousands of cells and a median ~6–12 independent episodes per window, a gap-only rule fires on
~43% of cells **under the null** (research §5). So:
- **Raw p** = two-sided two-proportion z on **raw** window rates at per-window effective N.
- **FDR** = Benjamini-Hochberg at `q_fdr` (default 0.10), family size anchored to the ledger's
  `n_trials` (`ledger.py`), not a new invented count. (BH under positive dependence; do not silently
  upgrade to Bonferroni.)
- **Persist `mde_80pct_pp`** per cell ("could only have caught a change bigger than X points").
- **Joint gate → emit a directional label only if ALL hold, else `INSUFFICIENT_EVIDENCE`:**
  (1) both window effective-N ≥ floor; (2) |shrunk delta| ≥ threshold; (3) BH q ≤ q_fdr on raw p;
  (4) MK on anchors agrees in sign and `n_anchors ≥ min_anchors`.
- **Expectation-setter for Emanuel (verbatim-ready):** *"Most cells will say 'not enough evidence to
  call a change' — that's correct, not a bug. With only ~6–12 independent episodes per window we can
  reliably detect only a near-total flip (like 90%→10%). Without this discipline the tool would light
  up hundreds of false 'changed!' alarms."*

---

## 5. Reuse & no-duplication reconciliation (the senior-eng rule)

Three places already touch "two-sided" or "capture" ideas. The plan **reuses primitives** and keeps
the new engine distinct on a defensible axis (horizon + forward/contemporaneous + estimator):

| Existing | Layer / horizon / method | Relationship to this engine |
|---|---|---|
| `structural.py` `up_beta`/`down_beta`/`gamma`/`asymmetry_ratio` | Tool A/C, **contemporaneous 1-week OLS** on gold>0/<0 weeks | Reuse the up/down regime *definition*; the Lab capture is **forward h-week**, ratio-based, with the honesty layer. Different number, different question. |
| `relative_behavior.py` `rel_strength/rel_weakness`, tail averages | Features→Tool C, **weekly tail-event hit-rates** (gold best/worst 20%) | Conceptual cousin of capture but weekly + fraction-based + feeds Tool C scoring. The Lab version is forward + ratio + trend-aware. Note the overlap; do not fork the weekly logic into the Lab. |
| `build_profile_artifact` `gold_tilt` (down P(beat) − up P(beat)) | Lab, **per ticker×horizon×benchmark** | This engine **generalizes** it: gold_tilt is the beat-rate asymmetry; capture is the magnitude asymmetry. Reuse `DOWN_BUCKETS`/`UP_BUCKETS`, `cell_bucket_is_usable`, `GoldProfileConfig` patterns. |

**Extract-first (one copy), before the new builder:**
1. `eb_shrink(p_raw, eff_n, prior, strength)` ← inline at `conditional_dial.py:267-269`.
2. `pooled_prior(episodes, group_keys, *, leave_out=None)` ← `conditional_dial.py:236-242` (the
   all-history prior and the windowed peer prior become one path).
3. `wilson_interval` ← move from `conditional_dial.py:364` (or re-export).
4. `decay_effective_n`, `decay_weights`, `weighted_median`, `mann_kendall`, `theil_sen`,
   `benjamini_hochberg`, `peer_percentile` ← new pure-numpy in `golden_vector/lab/statistics.py`.
5. `weighted_median` already exists at `structural.py:1179-1199` — **lift it to
   `golden_vector/common/`** and have both `structural.py` and the Lab import it (don't fork; don't
   import `model/` from `lab/`).

`_dial_cells` is refactored to call #1–#3 so there is exactly one shrink/prior/Wilson implementation.

---

## 6. Architecture & code

### New modules
- `golden_vector/lab/statistics.py` — the shared pure-numpy primitives (§5). One home, fully tested.
- `golden_vector/lab/behavior_engine.py` — the builder: reads `dial_episodes`, validates
  schema/config hash, computes capture (§4.1), trend (§4.2), peer aggregates (§4.3), abstention
  (§4.4); writes artifacts. **All compute here — never in serve.**

### Config (validated, hashed)
- New `CaptureBehaviorConfig` in `contracts/config_models.py` (sibling of `GoldProfileConfig`,
  same `StrictConfigModel` + validators), loaded from `config/lab_behavior_trend.yaml`, **folded into
  `dial_config_hash`** so any threshold edit invalidates the artifact:
```yaml
version: 1
trend_window_basis: event_time    # recent vs older split on INDEPENDENT anchors, NOT calendar years
recent_anchor_fraction: 0.5       # recent = most-recent half of independent anchors; older = the rest
decay_half_life_episodes: 6       # decay paced by independent episodes (event-time), not calendar age
decay_half_life_years: 3          # DIAGNOSTIC only (calendar), not the gating decay
min_all_effective_n: 8.0          # reuse MIN_EFFECTIVE_N
min_recent_effective_n: 6.0
min_older_effective_n: 6.0
min_direction_effective_n: 6.0    # capture per-side floor
min_anchors: 8
min_peer_count: 20
trend_delta_threshold: 0.20
q_fdr: 0.10
eb_prior_strength: 10.0           # reuse EB_PRIOR_STRENGTH
recent_prior_min_pool_effective_n: 10.0
hedge_down_capture_max: 0.80
torque_up_capture_min: 1.20
alpha_slope_threshold: 0.01
rolling_event_window: 12
```

### Artifacts (slot into the existing all-or-nothing set)
Add to `DIAL_ARTIFACT_SPECS` (so `write_dial_artifacts` stays all-or-nothing and a build can't
half-wire), each run-stamped + `latest` alias, schema_version + config_hash stamped:
- `dial_episodes` (existing) — **+ `stock_fwd_simple`, `peer_count`, `peer_percentile`** (schema v4).
- `dial_capture` (NEW) — per `(ticker, horizon)`: down/up capture (mean & median), convexity,
  per-side effective N + means, `archetype`, `capture_status`, capture recent/older/decay deltas,
  `config_hash`, `caveat`.
- `dial_behavior_trend` (NEW) — per `(ticker, benchmark, horizon, bucket)`: all/recent/older/decay
  beat + alpha levels, beat-trend (delta, MK τ/z/p, raw p, BH q, mde, n_anchors, label, status),
  alpha-trend (median_decay, q10/q90, Theil-Sen slope, MK p, label), peer snapshot (median
  percentile all/recent/older/decay, top/bottom-quartile rates), `config_hash`, `caveat`.

### Serve (render only)
- Extend `lab_curve_data.py` loader to read the new artifacts with the **same** `_load_frame` /
  `_read_meta` / `_config_is_current` STALE/MISSING/CORRUPT/EMPTY pattern (verified pattern from the
  Explore pass), degrading to a calm unavailable state.
- Extend `lab_curve_page.py` to render the cards + the symmetric chart (down dots / up dots, capture
  bars, recency line). **No arithmetic.**
- **Extend the serve no-arithmetic guard** (`tests/test_lab_page.py:291-335`): add the new serve
  module(s) and forbid `mann_kendall`, `theil_sen`, `benjamini_hochberg`, `peer_percentile`,
  `decay_effective_n`, `down_capture`, `up_capture`, `/ mean(`, the archetype literals
  (`CONVEX`/`HEDGE`/`TORQUE`/`DEAD WEIGHT`), etc. — clone the Tool-D static-scan discipline.

---

## 7. Survivorship: why the peer *trend* is deferred (and the rest is not)

Universe = survivors only. An old episode's peer pool is missing the miners that later died (mostly
the weak ones), so old peer percentiles are biased **low** and the peer-*trend* shows fake
"improving." Therefore:
- **Ships now:** capture, beat/alpha levels + trends (a name vs its own past — minimally affected),
  peer **snapshot** (read as a *relative* benchmark, with caveat).
- **Deferred until dead-miner records exist:** peer **trend label**, and any universe-wide
  cross-sectional deterioration scan. This reverses Codex's plan, which gated peer-trend too weakly.

---

## 8. Cross-check vs the predictive-models skill + hard rules

| Rule | Compliance |
|---|---|
| Small-N ⇒ no ML, evaluate by IC/quantile spread | ✅ counting + ratios + rank; no trees/NN; backtest scores IC + top-minus-bottom spread |
| Calibrated frequencies + sample size, never point targets | ✅ "beat 7 of 12 episodes", effective N everywhere, Wilson intervals; capture shown with N + component means |
| Backtest validity (walk-forward, purge/embargo, PIT, deflated, t>3, log variants) | ✅ Phase 5 reuses `walk_forward` folds + `ledger` n_trials; capture/beat/alpha/peer are price-derived PIT-safe |
| Labels never join live features | ✅ separate artifacts; forward returns are labels, kept in the episode/label path, never in a live feature join |
| Don't predict gold price | ✅ gold is conditioning only (already enforced — `forward_returns.py` bans gold from labels) |
| No mixed currencies w/o normalization | ✅ all returns are unitless ratios |
| No ad-hoc horizons | ✅ reuse `DIAL_HORIZONS_WEEKS` |
| No opaque composite scores | ✅ capture/convexity are standard; archetype = 2-D classification from 2 standard metrics + config thresholds, raw numbers primary |
| Compute once → persist → serve reads; one normalize boundary | ✅ engine computes, serve renders; `exp()-1` stays the one simple-return boundary |
| Fail loud required / degrade per-item optional | ✅ schema/config validated loud; thin cells → explicit status, never silent empty |

---

## 9. Build sequence (foundation first — Emanuel wants depth, not speed)

- **Phase 0 — spine + shared math.** Add `stock_fwd_simple` to `dial_episodes` (schema v4); extract
  `eb_shrink`/`pooled_prior`/`wilson_interval` and add the new pure-numpy primitives in
  `statistics.py`; refactor `_dial_cells` onto them. Pure de-dup + one new column → full suite green.
- **Phase 1 — capture & convexity (the GOLD lens).** Build `dial_capture` (down/up capture,
  convexity, archetype, status, descriptive recent/older/decay). This is the symmetric backbone and
  the directly-answers-"beta both ways" deliverable.
- **Phase 2 — peer ranks (point-in-time).** Compute `peer_count`/`peer_percentile` on episodes +
  snapshot aggregates. Peer-trend deferred (§7).
- **Phase 3 — trend layer (beat + alpha).** MK-on-anchors, window-matched shrinkage, FDR, abstention
  gate, capture-trend (descriptive). Pin the anchors-only-significance invariant with a test.
- **Phase 4 — UI.** Symmetric cards + chart on `/lab/dial/<ticker>` (both directions, three lenses,
  recency line), all backend-read, serve-guard extended. Descriptive, not predictive.
- **Phase 5 — walk-forward backtest.** Does capture / convexity / recency / peer-rank predict the
  next move better than the all-history baseline? Brier + calibration + Spearman IC + top-minus-bottom
  spread, stable across folds, no look-ahead, variants logged. Scorecard only — no product ranking.
- **Phase 6 — Candidate Finder (only if Phase 5 passes).** Optional, default-OFF criteria:
  `down_capture`, `up_capture`, `convexity`, `recency_weighted_beat_rate`, `alpha_trend_slope`,
  `peer_percentile_decay`. Two upside rankings exposed — **"Raw torque"** (up-capture) and
  **"Convex"** (up-capture relative to down-capture) — see the open decision below.

---

## 10. Tests (behaviour-proving, not pass-by-accident)

- **Math:** `decay_effective_n` → Kish at h=1, `n/h` at uniform weights; capture handles all-down /
  all-up / mixed; capture denominator never near-zero given bucket conditioning; MK uses anchors only
  (feed overlapping rows, assert ~n/h points used); Theil-Sen on anchors only; BH q monotone; peer
  percentile 100=best/0=worst, ties = average; weighted median robust to a tail outlier.
- **Capture correctness:** synthetic miner with `r = 0.5·g` on down and `r = 2·g` on up →
  down_capture≈0.5, up_capture≈2.0, convexity≈1.5, archetype CONVEX.
- **Trend:** synthetic 90%→10% over ≥12 anchors → DETERIORATING; noisy-flat → STABLE/INSUFFICIENT;
  recent shrink uses recent peer prior (not same-stock all-history — assert the regime survives).
- **Artifact:** missing required column fails loud; config-hash change → STALE; thin
  recent/older/direction/peer pool → INSUFFICIENT/THIN status, never a directional label.
- **Serve:** static no-arithmetic guard extended; missing/stale/corrupt → calm unavailable; effective
  N shown beside every rate; "historical / exploratory / not a forecast" string asserted at render.
- **Backtest:** walk-forward uses only past episodes; purge/embargo respected; labels never join live
  features.

---

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Capture ratio duplicates `up_beta`/`down_beta` / `relative_behavior` | §5: distinct horizon + forward + estimator; reuse the *definition* + primitives, not the number; note the overlap explicitly |
| Heavy-tailed returns distort mean-based capture | Persist median-based capture companion + flag large mean/median gaps |
| Peer trend survivorship bias | §7: peer-trend + universe scan deferred until dead-miner data |
| False trend labels from tiny samples | Effective-N floors, anchors-only tests, BH-FDR, abstain by default |
| User reads history as forecast | Descriptive-only wording until Phase 5; caveat on every artifact |
| Artifact sprawl / half-wired build | All new artifacts in `DIAL_ARTIFACT_SPECS` (all-or-nothing write) |
| Serve arithmetic creeps in | Extend the static-scan guard before writing the page |
| Too many Candidate Finder knobs | All default-OFF; none rank until Phase 5 proves it |

---

## 12. Decisions for Emanuel — ✅ RESOLVED 2026-06-17

> **Confirmed:** (1) offense default = **Convex** (upside relative to downside; raw torque one click
> away); (2) capture is **gold-only** (GDX/GDXJ stays the beat-rate/alpha lens); (3) horizons =
> **13w for capture levels/archetype, 8w for behaviour-change labels** (abstain where a side is thin).
> The original options are kept below for the record.

1. **"Increase a lot" = raw torque or convex?** I'm baking in **both** as separate upside rankings
   ("Raw torque" = highest up-capture; "Convex" = highest up-capture *relative to* down-capture).
   Default headline for the offense view: **Convex** (better risk-adjusted), with Raw torque one click
   away. Confirm or flip the default.
2. **Capture reference = gold only, or also a capture-vs-GDX?** Plan uses **gold** for capture (the
   macro "beta both ways") and keeps **alpha/beat** for the GDX(J) comparison (capturing GDX ≈
   relative sector beta, less interpretable). Confirm gold-only capture for v1.
3. **Default horizons (now measured, not guessed — see §4.2 box).** Capture *levels*/archetype have
   ample depth at every horizon → **default 13w** (matches the tool default). Trend *labels*, on
   **event-time** windows, are honest at **4w/8w** on both directions, marginal at 13w on the down
   side, too thin at 26w → **default 8w**, abstaining where a side's anchors fall below the floor. The
   earlier "calendar 4-year window" idea is dropped: it left 0/65 miners powered on the hedge side
   (gold rarely fell in 2022–2026). Confirm 13w-levels / 8w-trend.
```

---

## 13. Codex review resolutions (2026-06-17) — Claude re-review

Codex reviewed this plan (`reviews/codex/codex_review_capture_behavior_engine_plan.md`). All eight
findings are **adopted**; the plan is updated as below. Status moves to **READY TO CODE** once
Emanuel answers §12.

1. **HIGH — peer percentile must be benchmark-independent.** `stock_fwd_simple` does not depend on
   GDX/GDXJ, so peer ranks are computed on **distinct `(ticker, week_period, horizon_weeks,
   gold_bucket)` stock-return rows BEFORE benchmark expansion**, then the same `peer_count` /
   `peer_percentile` is joined onto both benchmark rows. Group key drops `benchmark`. Add a test
   where one stock/week/horizon appears under both GDX and GDXJ and the peer percentile is identical
   (no double-count). Any benchmark-scoped universe, if ever wanted, is a separately-named metric.

2. **MEDIUM — split the config hash.** Keep the existing **`dial_config_hash`** for the raw
   episode/cell/profile spine. Add a **separate `behavior_config_hash`** covering `CaptureBehaviorConfig`
   (`q_fdr`, `hedge_down_capture_max`, `torque_up_capture_min`, `alpha_slope_threshold`, `min_peer_count`).
   Stamp both in metadata; serve validates only the hash for the artifact it reads. A label-threshold
   edit must not make `dial_episodes`/`cells`/`profile` or the existing Lab page look stale.

3. **MEDIUM — `min_peer_count` must not mutate raw episode rows.** Persist raw `peer_count` and raw
   `peer_percentile` whenever `peer_count >= 2`; `peer_percentile = null` only for the mathematically
   undefined `peer_count < 2`. `THIN_PEER_POOL` / null-for-display from `min_peer_count` is applied in
   `dial_behavior_trend` (or a render-ready artifact), never in the base episode artifact. Tests:
   `peer_count` 1, ties, and a `min_peer_count` change that does NOT alter episode rows.

4. **MEDIUM — pin the capture headline sample (Claude refinement of Codex's fix).** Codex's risk is
   real (clustered multi-week moves over-weight the mean), but overlap inflates *variance*, not
   *bias*, of a mean — and anchors are very few (~n/h), so anchor-only would throw away precision to
   fix a bias that isn't there. So: **display the all-rows capture** (`capture_all_rows`, unbiased)
   as the value, but **gate the hard ARCHETYPE label** on effective-N *plus* an anchor cross-check —
   also compute `capture_anchor` and, **if the archetype flips between all-rows and anchors, abstain
   (INSUFFICIENT)**. Persist both; test that overlapping rows cannot manufacture a stronger archetype
   than the anchors support.

5. **MEDIUM — pin the event-time split grain.** Recent/older is split **within the target grain AFTER
   filtering to anchor rows**: bucket trend within `(ticker, benchmark, horizon, bucket)`; capture
   trend within `(ticker, horizon, direction)` over `DOWN_BUCKETS`/`UP_BUCKETS` anchors. Persist the
   recent/older anchor counts and the split index per cell. Test with uneven up/down spacing.

6. **LOW — kill the log/simple mix-up.** Persist **`stock_fwd_log`** alongside `stock_fwd_simple` (it
   already exists pre-drop) and write the recovery explicitly:
   `bench_fwd_simple = exp(log1p(stock_fwd_simple) - alpha) - 1`. Add a round-trip test vs the existing
   forward-return panel columns.

7. **LOW — refine the serve guard (Claude correction of the folded-in fix).** Forbid compute
   helpers/operators in serve (`mann_kendall`, `theil_sen`, `.mean(`, `.groupby(`, `.rank(`,
   `/ mean(`, …) and **allow persisted COLUMN NAMES** (`peer_percentile`, `down_capture`,
   `up_capture`) — those are legitimate in typed structures/renderer constants. BUT **keep the
   archetype VALUE words forbidden** (`CONVEX`/`HEDGE`/`TORQUE`/`DEAD WEIGHT`), exactly as the
   existing guard forbids `Defensive`/`Steady`/`Pro-cyclical`: serve must echo the persisted
   `archetype` string, never re-decide it. Add render-level tests proving serve echoes persisted
   values without recomputing.

8. **LOW — survivorship caveat constrains the headline too.** Peer snapshot stays survivor-only and
   visibly caveated; prefer recent/decay peer values over all-history for any headline; stamp
   `survivor_universe=true` and a `peer_snapshot_status`/`caveat` on the artifact.

### Claude re-review additions (beyond Codex's 8)

9. **MED — `behavior_config_hash` must also track the spine.** Splitting the hash (#2) is right, but
   the behavior artifacts are *derived from* `dial_episodes`. If the spine is rebuilt or its
   `DIAL_SCHEMA_VERSION` bumps while behavior thresholds are unchanged, a derived artifact would still
   pass its own hash and go silently stale. So `behavior_config_hash` must fold in the spine's
   `schema_version` + source-run pointer (or the raw `dial_config_hash`). Test: a spine rebuild
   invalidates the behavior artifacts even with identical behavior config.

10. **MED — the archetype cutoffs are unjustified numbers (same smell Emanuel caught on horizons).**
    `hedge_down_capture_max=0.8` and `torque_up_capture_min=1.2` are picked by feel. Before they ship,
    set them from the **real cross-sectional distribution** of miner capture (e.g. quantiles of actual
    down/up-capture across the 65 names), the way the horizon set was chosen from measured usable
    counts — not by guess. Phase 1 must print the distribution and the cutoffs derived from it; the
    config values are then grounded, not arbitrary.

**Net effect on sequencing:** Tier-1 schema gains `stock_fwd_log`; the artifact family splits into a
raw spine (one hash) and a behavior layer (second hash, which also tracks the spine); peer ranks move
pre-expansion and are computed on a benchmark-independent stock-return source; archetype cutoffs are
data-derived in Phase 1. None of this changes the user-facing lenses in §0 — it hardens the contracts
before any code is written.
