# Phase 5 — Capture & Behaviour engine: pre-registered walk-forward backtest spec

Status: **v3 — Codex review applied; proposed FREEZE-READY** (Claude). Mirrors the rigor + structure
of `claude_program_a_validation_spec.md` (which shipped as the `/scorecard`). Nothing here runs until
this is re-confirmed, frozen, and every variant config is registered in the ledger.

> **v3 changelog — applied Codex's review (`codex_review_phase5_backtest_spec.md`, verdict NEEDS
> CHANGES, 7 blockers).** (1) **Froze fold geometry** `min_train_weeks=260, test_weeks=1,
> step_weeks=H` with stamped expected fold counts + a cross-fold label-overlap assertion, which is
> what makes the lag-1 NW-t valid (§1). (2) **Fixed the baseline gauntlet** — dropped the constant
> (equal-weight / buy-and-hold) ranks from the paired-Spearman test (they have no rank variation →
> Spearman is undefined); the paired gauntlet is now 4 real baselines, beat ≥ 3 of 4 (§3). (3) Made
> the **N_eff-derived required-IC / IR-ceiling a binding gate** (else verdict caps at PARTIAL) and
> froze its full derivation, including a **pure-numpy Ledoit–Wolf** formula (no new dependency) (§4,
> gates). (4) **Ledger role/family semantics** + DSR denominator pinned; removed the "DSR diagnostic
> but also a floor" contradiction — DSR is reported and caps *performance wording* only (§1, §8).
> (5) **Pinned E4 grain + an ordered verdict-precedence table** so the shipped NULL can't overclaim
> (§2 E4, §6). (6) **Defined E2's forward-asymmetry label** exactly with side floors (§2 E2). (7)
> Specified the **scorecard schema/render contract**, added GDXJ + convexity-threshold + Lab-rank to
> NOT-tested, pinned the split-half convention, added a pure-python p-value helper, and corrected the
> one-copy note (`newey_west_t` / `tercile_portfolio_spread` already exist in `validation.py` — reuse,
> not new) (§0, §6, §8).

> **v1 → v2 changelog (applied after an internal 5-dimension/70-agent adversarial review, 62 findings
> → ~9 distinct issues).** Pinned the **family size `m`** and resolved the §11 scope so no gate is
> frozen against an undefined denominator (§1.1). Strengthened **fold purity** — every *fitted*
> quantity (capture, EB priors, peer pools, FDR family, recent/older split) is refit within
> `train_periods` only, with a new **prior-leakage canary** (§1, §5). Pinned **target IR** and
> clarified N_eff is measured on a frozen pre-window (§4). Added a reported **Deflated Sharpe** and
> fixed the false "no new primitives" claim — the genuinely NEW helpers are now enumerated (§8).
> Specified the **baseline reconstructions + test sidedness** (§3). Clarified **regime conditioning**
> is outcome-side, never feature-side (§1). Made the **survivor caveat universal** and added the
> archetype label to the "NOT tested" list (§0, §6). Findings digest:
> `reviews/codex/` (this review was internal; Codex's is the next pass).

**One sentence:** does the Capture & Behaviour engine's descriptive output (capture / convexity /
peer-rank / behaviour-change) actually *predict* the next move better than dumb baselines on a
walk-forward, leak-guarded, breadth-honest test — and if not, ship that null as a trust feature.

**The pre-registration contract (the whole point):** every gate threshold, hypothesis, feature
reconstruction, label definition, and the acceptance bar below are locked in the variant ledger
(`ledger.register_variant`) BEFORE any number is computed. `validation.py`-style module constants
must equal the registered configs (a drift test asserts it). Changing a gate after seeing a result,
without a new registered variant, is the malpractice this document exists to prevent.

---

## 0. What the engine claims, and what we test (claim-fidelity table)

| Lens | User-facing claim | Exact test here | Explicitly NOT tested |
|------|-------------------|-----------------|------------------------|
| Capture / archetype | "Low fall-capture = hedge; high rise-capture = torque" | E1: does the capture rank forward beat-vs-GDX in the *matching* gold regime? | That archetypes are stable labels; absolute capture levels |
| Convexity (CONVEX offense) | "convexity > 0 = the convex sweet spot" | E2: does convexity rank forward (up-minus-down) asymmetry? | That convexity predicts total return |
| Peer rank | "historically one of the stronger miners in that move" | E3: does trailing peer-rank persist (predict forward peer-rank / alpha)? | Causation; that high rank = future winner |
| Behaviour-change (trend) | "IMPROVING / DETERIORATING" | E4 (flagship): does the recent-vs-older signal beat the all-history baseline? | Anything live until this passes |
| — (all) | — | — | **Costs, dead miners, options/fundamentals signals, calibration over live time** |

Every result card carries the §0 "NOT tested" list verbatim (mandatory honesty enumeration).

**Explicitly NOT tested (enumerated on every card):** the discrete **archetype label**
(CONVEX/HEDGE/TORQUE/DEAD_WEIGHT) as a classifier — tested only via its *components* (E1 capture + E2
convexity); the **absolute convexity sign / `convexity > 0` "sweet spot" as a classifier** (E2 tests
convexity as a *rank*, not the zero threshold); absolute capture levels; archetype/peer **stability**
over time; **GDXJ-relative** predictive claims (every label here is "vs GDX"; GDXJ is a deferred
robustness variant, §10); the **other Lab ranks + the gold-profile tilt label** (Phase 5 covers only
the behaviour-engine lenses, not everything the `/scorecard` page shows); transaction costs;
dead/delisted miners; the fundamentals/Tool-D/option signals; calibration over live time.

**Scope boundary:** Phase 5 adds a **`/scorecard` section only**. It does NOT change the
`/lab/dial` behaviour panel, which stays **descriptive** (per §7's architectural gate) until an
experiment reaches its verdict — and even SUPPORTED is survivor-only, never a live buy signal.

---

## 1. Shared design (binding for every experiment)

- **Family size `m` = 4 (LOCKED before any compute).** The gated headline experiments are exactly
  **E1, E2, E3, E4**. Everything else is *pre-registered robustness*, reported but NOT a separate
  gated headline and NOT counted in `m`: the second forward horizon per experiment (8w↔13w), E3's
  two label variants, and E4's alpha-trend slice. Each is still `register_variant`-ed (so its config
  is hashed and auditable) but tagged `role: "robustness"`. The binding bar is the headline
  fold-level NW-t > 3 (one-sided, p ≈ 0.001); family-wise α ≈ m × 0.001 ≈ **0.004** (survives 0.05
  with margin). Every registered config carries `trial_family_id="phase5_behaviour"`, a `role`
  (`"headline"` for the 4 gated experiments, `"robustness"` for horizon/label/alpha slices), and the
  frozen `m=4`; a drift test asserts the live headline count equals 4. The **DSR trial denominator
  `dsr_n_trials`** = the phase-wide count of ALL registered Phase 5 variants (headline + robustness +
  reruns), read from a role-aware ledger count — NOT the bare `n_trials()` (which the current ledger
  only supports per-`signal_id`; the role-aware count is a small ledger extension, §8). (Resolves the
  §11 scope + Codex BLOCKER 4.)
- **Universe / spine.** The persisted, run-stamped `dial_episodes` frame is the legal spine
  (immutable, sha256-stamped). Features and labels are read/derived from it; no request-path compute.
- **Join key.** W-FRI `week_period` strings only — never a raw `as_of_date`. (Mirrors Program A.)
- **As-of grid (FROZEN).** Expanding-window walk-forward via `walk_forward.generate_folds(
  week_periods, label_horizon_weeks=H, min_train_weeks=260, test_weeks=1, step_weeks=H)`. **`test_weeks=1`
  + `step_weeks=H` is what makes each fold a single disjoint as-of observation** spaced one horizon
  apart, so the fold-level NW-t legitimately uses `n = n_folds` (lag-1). Expected fold counts on the
  current `dial_episodes_latest` spine (stamped in meta before compute): **≈ 74 folds at H=8, ≈ 45 at
  H=13** (re-counted + frozen at registration). We call `assert_no_label_overlap(fold,
  label_horizon_weeks=H)` per fold AND a new **`assert_no_test_label_overlap_across_folds`** (adjacent
  test as-of weeks must be ≥ H apart so no two test labels share a forward week) — without the latter
  the disjoint-observation assumption behind lag-1 is unproven (Codex BLOCKER 1).
- **Forward horizon.** Primary **H = 13 weeks** (matches the capture grounding horizon + Program A's
  product decision). The behaviour-change experiment (E4) is registered at **H = 8 weeks** (its
  locked trend horizon). A second registered variant per experiment runs the *other* horizon as a
  robustness slice (so the horizon choice is pre-committed, not cherry-picked).
- **Labels (PIT-safe, hedged).** Built by `forward_returns.build_forward_return_panel(…,
  horizons_weeks=[H])`, which yields strictly-forward, complete-window-only columns
  (`fwd_alpha_gdx_Hw` = stock fwd minus GDX fwd over weeks t+1..t+H; NaN unless all H weeks present).
  **Labels are GDX-hedged residual alpha, never raw forward return** — so the test cannot reward
  plain gold-factor exposure (addresses the "residualize-or-die" rule). A contamination check
  regresses the realized label P&L on gold forward return per fold and flags `CONTAMINATED` if
  R² > 0.20 or |t| > 3 (documented, not silently dropped).
- **No feature looks forward, and every FITTED quantity is refit within the fold.** Each feature for a
  test week `w` uses ONLY episodes with `week_period` in `fold.train_periods`. Critically, the live
  `behavior_engine` computes capture means, the EB priors (`all_prior`/`rec_prior`/`old_prior`), the
  peer pools + percentiles, the BH-FDR family, and the recent-vs-older split boundary on the WHOLE
  cohort — a Phase 5 backtest must **re-fit all of these inside each training fold** (new per-fold
  reconstruction code; never a call to the full-history live build). Any cross-fold fitted quantity is
  leakage. A dedicated **prior-leakage canary** (§5.8) proves a full-cohort-fitted prior is caught.
- **Regime conditioning is OUTCOME-side, never feature-side.** `gold_bucket` is the *realized* forward
  gold regime of the scored episode; conditioning a LABEL on it ("within the gold-down episodes that
  actually occurred, did low fall-capture win?") is legitimate stratification, not leakage. No FEATURE
  may use any forward gold value; if a feature ever needs a regime flag, it uses a strictly-lagged
  threshold (the live `gold_regime` rolling quantile includes the current week — banned on the feature
  side here).
- **Metrics.** `evaluation.evaluate_predictions(frame, label_horizon_weeks=H, …)` →
  per-date Spearman rank-IC, IC `t-stat` (computed on **effective_n = n_dates / H**, never raw n),
  MAE, hit-rate (sign agreement), top/bottom **quantile spread** (default 0.2), and the
  `leakage_alarm` (|mean IC| > 0.90 → INADMISSIBLE).
- **t-stat rule (predictive experiments).** Report BOTH (a) the IC `t-stat` on effective-N (from
  `evaluate_predictions`) and (b) a **fold-level Newey–West lag-1 t** on the per-fold IC series with
  **n = number of folds** (NOT n/H — the folds are the disjoint observations; applying the n/H
  correction to the disjoint-grid t-path is forbidden and guarded by a canary, mirroring Program A).
  The binding bar is the fold-level NW-t. **df = n_folds** for both the fold-IC NW-t and the
  tercile-spread t (stated on every card); the spread-t is confirmatory, the IC NW-t is binding.
- **Deflated Sharpe Ratio (reported; caps wording, does NOT gate).** Per experiment, report the DSR
  (Bailey & López de Prado) of the tercile long-short return series, with the trial denominator =
  `dsr_n_trials` (above) and the skew/kurtosis + track-length adjustment. DSR is **not a pass/fail
  gate** (the binding gates are the IC NW-t, the required-IC floor, and the baseline gauntlet) — but a
  signal that clears those yet has **DSR ≤ 0 caps the card's *performance* wording** (it may say "ranks
  forward returns" but NOT "would have been a profitable strategy"; the card prints the short/skewed
  track-record reason). This removes the v2 "diagnostic but also a floor" contradiction (Codex
  BLOCKER 4) while still satisfying the predictive-models rule against quoting performance without
  deflation + # variants.
- **No ML.** Ranks and at most a single heavily-shrunk logistic/linear model. No trees, no NN, no
  gradient boosting (breadth ≈ 5–15 independent bets → flexible ML overfits by construction). Any
  model beyond a rank requires a red-team overfit note.
- **Tercile-portfolio spreads, not fold-win counts**, for effect size: sort names into terciles by
  the feature each fold (average-rank, ties by ticker — deterministic), measure the forward-label
  spread (top − bottom), t-test the per-fold spread series.
- **Noise ceiling (mandatory output; convention FROZEN).** Split-half outcome self-consistency (odd
  vs even forward weeks), reported as the **Spearman–Brown-corrected** reliability `2r/(1+r)` (since
  each half is shorter than the full-horizon label, the raw split understates measurability — Codex
  MEDIUM); the raw `r` is reported alongside. Computed only when ≥ 15 names and ≥ 10 folds contribute.
  A failing experiment is **NOT SUPPORTED** only if the corrected ceiling ≥ 0.30; otherwise
  **INCONCLUSIVE** (unmeasurable at this horizon/breadth, not disproven).
- **Breadth meter (mandatory output).** Report weekly effective breadth N_eff (participation ratio of
  the shrunk residual-return correlation matrix) and the implied IR ceiling
  (IC × √N_eff × transfer). Every IC/DSR/sample claim is contextualized by N_eff. This is the
  "you are breadth-starved, not model-starved" honesty line.

---

## 2. The experiments (registered variants)

Each is registered with `register_variant(lab_dir, signal_id=<id>, config=<the full dict below>)`
and gated through `require_registered(...)` before compute. `signal_id` prefix = `p5_behaviour_`.

### E1 — Capture validity (the HEDGE/TORQUE claim)
- **id:** `p5_behaviour_capture_validity` (variants: `H=13` primary, `H=8` robustness)
- **Hypothesis (directional, regime-conditional):** within gold-DOWN episodes, a *lower*
  `down_capture_mean` ranks *higher* forward `fwd_alpha_gdx`; within gold-UP episodes, a *higher*
  `up_capture_mean` ranks higher forward alpha.
- **Feature:** the side-appropriate capture, reconstructed per fold from `train_periods` episodes only
  (same `_capture_side` math as `behavior_engine`, restricted to the fold's training weeks).
- **Label:** `fwd_alpha_gdx_Hw` on the test episodes, conditioned on the same gold bucket.
- **Gates (all must pass):**
  1. directed mean rank-IC in the hypothesised sign, fold-level **NW-t > 3** (one-sided);
  2. IC in the hypothesised sign in **≥ 70%** of folds;
  3. tercile forward-alpha spread in the hypothesised sign with **t > 2** (one-sided);
  4. per-cell floor: only episodes with side `effective_n ≥ 6` (the live `min_direction_effective_n`);
  5. beats **≥ 3 of 4** paired baselines (§3) by one-sided paired NW-t, p < 0.05;
  6. **economic-size gate (binding):** `|mean directed IC| ≥ required_ic_floor` AND the implied
     `IR_ceiling ≥ 0.3` (both from §4's frozen N_eff derivation) — else the verdict caps at PARTIAL
     ("statistically positive but economically too small"), never SUPPORTED (Codex BLOCKER 3).
- **Down/up slices (implementation note):** run the gold-DOWN and gold-UP regimes as separate
  registered slices with FIXED prediction columns (down → `down_capture_mean`, up → `up_capture_mean`);
  the gold bucket is the realized outcome regime of the scored episode (no forward gold in any feature).

### E2 — Convexity validity (the CONVEX offense default)
- **id:** `p5_behaviour_convexity_validity`
- **Hypothesis:** higher `convexity` (= up_capture − down_capture) ranks higher forward *asymmetry*.
- **Feature:** `convexity` reconstructed per fold (train weeks only), at the default capture horizon.
- **Label (exact, buildable):** per name in a fold's test span,
  `asymmetry = mean(fwd_alpha_gdx_Hw | test episodes whose realized gold_bucket ∈ {gold_up,
  gold_up_big}) − mean(fwd_alpha_gdx_Hw | test episodes whose realized gold_bucket ∈ {gold_down,
  gold_down_big})`. **Per-side floor:** a name is scored only if it has ≥ 4 forward-up AND ≥ 4
  forward-down test episodes in that fold; **fold coverage:** a fold is scored only if ≥ 15 names clear
  both sides, else the fold is skipped and reported (not silently dropped). (Resolves Codex BLOCKER 6.)
- **All-history baseline (baseline 5 for E2):** the same asymmetry built from the name's full-history
  `convexity` point estimate (no per-fold reframing) — defined explicitly so the gauntlet is buildable.
- **Gates:** E1 gates 1–3, 5, 6; per-cell floor requires both capture sides ≥ 6 effective episodes.

### E3 — Peer-rank persistence (the "stronger miner" claim)
- **id:** `p5_behaviour_peer_persistence`
- **Hypothesis:** trailing `peer_percentile_median` (direction-specific) positively ranks the
  forward peer percentile / forward `fwd_alpha_gdx` rank — relative strength persists.
- **Feature:** trailing `peer_percentile_median` from `train_periods` peer points only.
- **Label:** forward peer percentile (recomputed on test-window episodes) AND `fwd_alpha_gdx_Hw` rank
  (two registered label variants; primary = forward peer percentile).
- **Gates:** E1 gates 1–3, 5, 6; floor: pool `peer_count ≥ 20` (live `min_peer_count`).

### E4 — Behaviour-change INCREMENTAL value (FLAGSHIP; null pre-committed)
- **id:** `p5_behaviour_trend_incremental`
- **Pinned grain (FROZEN, Codex BLOCKER 5):** `primary_benchmark = GDX`; `primary_horizon = 8w`
  (13w = robustness); `primary_bucket_scope = gold-down` (= {gold_down, gold_down_big} — the hedge
  side, where behaviour change matters most and the trend panel is read); `primary_label` =
  per-(ticker) realized forward beat-rate-vs-GDX change at the SAME (benchmark, horizon, bucket-scope)
  grain as the feature; `fwd_alpha` is a registered robustness label. The feature is aggregated to the
  label grain before registration (no per-bucket signal scored against a cross-bucket label).
- **Hypothesis:** the recent-vs-older signal (`trend_delta_raw` sign, gated as in the live engine)
  predicts that forward beat-rate change **better than the all-history baseline** (the static
  `all_p_beat_shrunk` point estimate) — does the time-decay view add anything beyond the whole history?
- **Feature (signal):** `trend_delta_raw` (with the live gate: |raw| & |shrunk| ≥ threshold, MK sign,
  FDR) reconstructed per fold; **Baseline feature:** all-history shrunk beat rate, same grain.
- **Gate (the bar):** the trend signal's per-fold IC must **exceed the baseline's** by a one-sided
  paired fold-level **NW-t > 3**, AND add positive directed IC itself clearing gate 6, AND clear §3.
- **Verdict follows the §6 precedence table** (not a bare pass/fail). The pre-committed NULL string —
  *"On the survivor set, the recent-vs-older behaviour-change view did NOT add predictive value over
  the all-history estimate (paired NW-t = X, p = Y). The trend panel stays descriptive."* — is shipped
  **only** when the all-history incremental comparison is MEASURABLE (split-half ceiling ≥ 0.30) and
  fails; a low-ceiling failure is INCONCLUSIVE, a canary failure is inadmissible, and a different gate
  failing yields NOT SUPPORTED/PARTIAL with gate-specific wording — so the NULL never overclaims
  (Codex BLOCKER 5 / E4 honesty).

> Alpha-trend (`alpha_slope_per_year`) is tested as a **robustness slice inside E4** (same machinery,
> alpha label), not a separate headline — to keep the family size honest.

---

## 3. Baseline gauntlet (every experiment must beat ≥ 3 of 4 PAIRED baselines)

Each registered baseline carries an explicit `{label, benchmark, orientation sign, missing-data
policy, statistic}` and is a rank reconstructed per fold from `train_periods`, scored against the
SAME label as the experiment. **Constant ranks cannot enter a paired Spearman-IC test** (the repo's
`spearman_ic` returns `None` when a side has no rank variation), so the two degenerate baselines are
**reported as references, not paired-tested** (Codex BLOCKER 2):

**Reported references (not in the paired gauntlet):**
- **equal-weight** — constant rank → IC ≡ 0 by construction (sanity floor);
- **GDX/GDXJ buy-and-hold** — the benchmark the alpha is measured against → 0 by construction (sanity).

**The 4 PAIRED baselines (beat ≥ 3 of 4):**
1. **up-beta-only rank** — Tool A structural up-beta (orientation: higher = better forward alpha);
2. **down-beta-only rank** — Tool A structural down-beta (orientation per experiment direction);
3. **all-history point estimate of the SAME quantity** (E1 → all-history capture; E2 → all-history
   convexity asymmetry, defined in §2 E2; E3 → all-history peer-percentile median; E4 →
   `all_p_beat_shrunk`) — NO time-decay / NO recent reframing — the "just use the whole history" null;
4. **26-week trailing momentum rank** (cumulative `stock_log_ret`, trailing 26 weeks).

Comparison is a **one-sided paired Newey–West lag-1 t on the per-fold IC difference** (experiment −
baseline), df = n_folds, p < 0.05; "beats" = the experiment's IC exceeds the baseline's at that bar.
The **≥ 3 of 4** rule is the multiplicity stance. **Baseline 3 ("use the whole history") is the
load-bearing comparison** — especially for E4; a signal that cannot beat it is not earning its
complexity.

---

## 4. Acceptance bar pre-registration (co-signed before any number is seen)

Because breadth caps achievable IR, an absolute IC floor cannot be guessed honestly. The full
derivation is FROZEN here (every input pinned so it cannot be re-tuned after seeing results):
1. **N_eff inputs (frozen):** weekly **residual returns** = each name's weekly log return minus its
   trailing-104-week-beta × GDX weekly log return; computed over the **frozen pre-window** = the
   `dial_episodes` spine up to **as-of 2024-12-27 (W-FRI)** (a fixed date written in the ledger,
   leaving recent weeks unseen). Names with < 104 valid weeks in the window are excluded;
   pairwise-complete weeks only.
2. **Shrinkage (PURE NUMPY — no new dependency):** the analytic Ledoit–Wolf intensity toward a
   constant-correlation target, computed in numpy/`math` only (closed form: shrink the sample
   correlation toward the average off-diagonal correlation; intensity = clamp(π̂ − ρ̂)/γ̂, 0..1). The
   repo's Lab stats are deliberately numpy/math-only and there is no scipy/sklearn — so this formula,
   its window, its return input, and its missing-data policy are ledger-locked (Codex BLOCKER 7).
3. **N_eff = participation ratio** of the shrunk correlation matrix eigenvalues: `(Σλ)² / Σλ²`.
4. **Required IC:** the smallest IC with `IR_ceiling = IC × √N_eff × transfer ≥ target IR`, at
   **target IR = 0.3 gross** and **transfer = 0.5** (Codex co-signed these as reasonable for a ~60-name
   survivor universe). Solve `required_ic_floor = 0.3 / (0.5 × √N_eff)`.
5. **Binding gate (not just reported):** each experiment's gate 6 requires `|mean directed IC| ≥
   required_ic_floor` AND `IR_ceiling ≥ 0.3`; failing it caps the verdict at **PARTIAL**
   ("statistically positive but economically too small"), never SUPPORTED (Codex BLOCKER 3).
6. **Claude + Codex co-sign** the resulting numeric floor + the gate set, hash-locked in the ledger,
   **before** `evaluate_predictions` is ever called on real labels.
(N_eff + the shrinkage + the IR math are **new pure-numpy code** — see §8.)

---

## 5. Canaries (CI, all numeric, must fail-loud)

1. **Label-as-feature:** smuggle the forward label in as a feature → |IC| ≈ 1 → `leakage_alarm`
   blocks admissibility.
2. **Shuffled ranks:** 20 fixed-seed within-date shuffles → **≤ 2** may show |fold-NW-t| ≥ 2
   (single-shuffle ~5% false-positive by construction).
3. **Time-reversal contrast:** a rank built from FORWARD data must beat the honest rank by **ΔIC ≥
   0.15** and emit `contaminated=True` → the scorecard publisher refuses to publish.
4. **Sign canaries:** synthetic always-hedge and always-torque tickers must land in the registered
   direction in E1/E2.
5. **eff_n guard:** the disjoint-grid fold-NW-t path must use n_folds; applying the n/H correction on
   that path raises.
6. **High-|IC| alarm:** |mean IC| ≥ 0.90 halts publication pending audit (does not auto-void; the
   binding admissibility test is the time-reversal contrast).
7. **Kill-list (existing CI):** no gold-return target; labels never join the feature artifact; no ML;
   no hardcoded horizon outside config.
8. **Prior/fit leakage:** re-run any experiment with its EB priors / capture means / peer pool fit on
   the FULL cohort instead of `train_periods`; the test must detect the difference and the honest
   (train-only) path must be the one that runs — a full-cohort fit can only ever inflate IC, so a
   silent full-fit is inadmissible. (Covers the gap canary 3's forward-shift does not.)
9. **Tercile-spread shuffle:** 20 fixed-seed within-fold rank shuffles → **≤ 2** may pass the gate-3
   tercile-spread t (matches canary 2's methodology for the spread metric, not just fold-IC).

---

## 6. Verdict vocabulary (binding strings)

- **SUPPORTED (exploratory — survivor-only universe)** — all gates pass. **Capped at SUPPORTED**;
  never VALIDATED until the dead-miner registry exists (survivor bias is structural and upward —
  the dead miners are exactly the high-down-beta capital-destroyers the tool flags). The survivor
  caveat applies **uniformly to all four experiments** (capture, convexity, peer, trend — every one
  is computed on the 65 survivors) and is printed on every card; no experiment is exempt.
- **PARTIAL** — some gates pass; the card lists each gate pass/fail. Includes the **economic-size cap**:
  gates 1–5 pass but gate 6 fails (IC statistically positive but below required_ic_floor / IR < 0.3).
- **NOT SUPPORTED** — gates fail AND the split-half ceiling ≥ 0.30 (outcome was measurable).
- **INCONCLUSIVE** — gates fail AND split-half ceiling < 0.30 (unmeasurable at this horizon/breadth).
- **NULL (shipped)** — E4 only: the all-history incremental comparison is measurable and fails.

**Ordered verdict precedence (evaluated top-down; first match wins — Codex BLOCKER 5):**
1. any **canary fails** → **INADMISSIBLE** (publication refused; nothing rendered);
2. **all primary gates (1–6) pass** → **SUPPORTED (exploratory — survivor-only)**;
3. gates fail AND **split-half ceiling < 0.30** → **INCONCLUSIVE**;
4. **E4 only:** the measurable all-history-incremental comparison fails (ceiling ≥ 0.30) → **NULL**
   (the §2 E4 string);
5. gates 1–5 pass, only gate 6 (economic size) fails → **PARTIAL (economically too small)**;
6. any other measurable gate failure → **NOT SUPPORTED / PARTIAL** with gate-specific wording.
This ordering is what stops the E4 NULL string from being shipped for a non-incremental failure
(canary, low ceiling, or a different gate).

---

## 7. Survivor-only ceiling + architectural gate

- **Verdict ceiling:** SUPPORTED, never VALIDATED, until a `security_master` / tombstone registry
  reconstructs historical GDX/GDXJ membership + terminal-return rules (multi-month SEC N-PORT work;
  **out of Phase 5 scope** — schema only, deferred). No such registry exists today (grep-confirmed).
- **Architectural gate (binding):** nothing in this engine may rank live or feed a Candidate Finder
  until E1–E4 reach SUPPORTED *and* the survivor caveat is shown. The panel stays **descriptive**
  exactly as it is today until then. (This is the existing "descriptive-until-backtested" invariant,
  now with a concrete passing condition.)

---

## 8. The tool that ships

- New module `golden_vector/lab/behaviour_backtest.py` (compute-once → persist), CLI
  `python -m golden_vector.lab.behaviour_backtest`.
- **REUSED as-is** (one-copy; grep before touching): `walk_forward.generate_folds` /
  `assert_no_label_overlap` / `effective_n`; `evaluation.evaluate_predictions` (rank-IC, quantile
  spread, hit-rate, leakage alarm); `validation.spearman_ic` / **`validation.newey_west_t`** /
  **`validation.tercile_portfolio_spread`** (these ALREADY EXIST — Codex caught my v2 mislabelling
  them "new"; the fold-level NW-t and tercile spread are a REUSE, not new code); `forward_returns.
  build_forward_return_panel`; `ledger.register_variant` / `require_registered`; the `scorecard`-style
  publisher. **One-copy action:** if a generic metric is needed by both `validation.py` and
  `behaviour_backtest.py`, extract it to `lab/statistics.py` and re-export — never re-implement.
- **GENUINELY NEW code** (small, tested; in `behaviour_backtest.py` or shared `lab/statistics.py`,
  grep-first): (a) **per-fold feature reconstruction** of capture/convexity/peer-rank/trend on
  `train_periods` only; (b) **N_eff / effective-breadth** = pure-numpy Ledoit–Wolf shrinkage +
  participation ratio (§4) + the IR-ceiling math; (c) **Deflated Sharpe Ratio** (pure-numpy); (d) the
  **label contamination check** (regress P&L on forward gold, flag R²>0.20 / |t|>3); (e) a pure-python
  **`t_to_p_one_sided(t, df)`** survival approximation (the repo has no scipy, but E4's "p = Y" and the
  baseline `p < 0.05` need a p-value, not just a t — Codex MEDIUM); (f) a **role-aware ledger count**
  (`n_trials_by_role(family_id, role)` / `dsr_n_trials(family_id)`) extending `ledger.py`, since the
  current `n_trials()` is total-or-per-`signal_id` only (Codex BLOCKER 4); (g) the
  **`assert_no_test_label_overlap_across_folds`** check (§1); (h) the **9-canary harness**.
- **Artifact + scorecard schema (Codex MEDIUM).** Publish a run-stamped
  `data/lab/behaviour_backtest_<stamp>.parquet` + `_latest` + meta JSON carrying, per experiment:
  `signal_id, trial_family_id, role, variant_hash, verdict, mean_ic, fold_nw_t, fold_share,
  tercile_spread_t, required_ic_floor, ir_ceiling, n_eff, dsr, dsr_n_trials, split_half_ceiling,
  baseline_pass_count, canary_results, p_value, source_spine_sha256, not_tested_list, survivor_caveat,
  built_at`. The existing `/scorecard` row schema does NOT carry these → **bump the scorecard schema to
  v2** (append Phase 5 rows) OR add a separate behaviour-backtest reader/render path; either way add
  **render-level tests** asserting N_eff, DSR, the canary summary, the survivor caveat, and the
  verbatim NOT-tested list appear on the card. All-or-nothing publish via `write_run_stamped_set`;
  publisher refuses on any failed canary or `contaminated=True`.
- Serve: a Phase-5 section on `/scorecard` (render-only, guardrailed; static-scan guard extended),
  scoped-copy **"these behaviour-engine lenses"** — NOT the existing "every ranking the product shows
  is tested" line (which would overclaim; Codex LOW). The `/lab/dial` panel is unchanged (§0).

---

## 9. Execution order (banked — each step gated green before the next)

1. Pre-register all variant configs + the co-signed acceptance bar in the ledger (nothing computes
   before this).
2. Implement `behaviour_backtest.py` feature/label reconstruction + the 9 canaries (§5) as tests
   FIRST (canaries must be red on rigged input, green on honest input) before any real run.
3. Measure N_eff + derive the required-IC bar; co-sign; hash-lock.
4. Run once. Bank verdicts. No re-runs without a new ledger entry + multiplicity-adjusted bar.
5. Publish the scorecard section; full-suite green; both-agent review; merge.

---

## 10. Explicitly deferred (collect/scope only — never fabricate, never block)

- **Dead-miner registry reconstruction** (schema-first only here; full build is a separate multi-month
  data product) — the gate to ever reach VALIDATED.
- **Realistic transaction-cost / slippage model** per liquidity tier (results are gross until added;
  stated on every card).
- **Full PBO / CSCV and block-conformal prediction intervals** — add when a signal actually clears the
  bar; the §1–§5 gates suffice for a first honest verdict.
- **Calibration-over-live-time (Brier/reliability tracking)** — starts only once a probability ships.
- **GDXJ-relative predictive claims** — every Phase 5 label is "vs GDX"; GDXJ-relative validity is a
  deferred robustness variant (register `*_gdxj` variants in a later pass), and until then every card
  states GDXJ-relative behaviour is NOT tested (Codex MEDIUM).
- **Fundamentals / Tool D / option signals** — forward-accrual only (no PIT history yet), as in
  Program A's E4.

---

## 11. Decisions — RESOLVED in v2 (was: open), + what still needs Codex's eye

**Resolved in v2 (locked, no longer open):**
1. **Family size `m` = 4** (E1, E2, E3, E4 headlines); horizon/label/alpha variants are registered
   robustness, not separate gated tests (§1.1). *Resolves the old "scope/fold E2 into E1" question —
   E2 stays a separate headline because convexity IS the CONVEX-default product claim.*
2. **E4 horizon** = 8w headline / 13w robustness (§1 forward-horizon). **E3 labels** = both forward
   peer-percentile and forward GDX-alpha rank, as registered robustness variants (§2 E3).
3. **Target IR ≈ 0.3 gross, transfer 0.5** drives the required-IC floor (§4).

**Resolved in v3 via Codex's review answers (now frozen):**
- **Target IR 0.3 / transfer 0.5** — Codex co-signed as reasonable for a ~60-name survivor universe;
  frozen, with the required-IC mechanically derived from the pinned pre-window and made a binding gate
  (§4 gate 6).
- **NW lag** — lag-1 is valid because fold geometry is now `test_weeks=1, step_weeks=H` (single
  as-of observations one horizon apart) + the cross-fold label-overlap assertion (§1).
- **DSR** — reported, not gated; DSR failure caps performance wording only; denominator is the
  phase-wide role-aware count (§1, §8).
- **Fold parameters** — `min_train_weeks=260, test_weeks=1, step_weeks=H`; expected ≈ 74 folds (H=8) /
  ≈ 45 (H=13), stamped before compute (§1).

**Remaining for the freeze sign-off (mechanical, not design):** compute N_eff on the pinned
pre-window → publish the numeric `required_ic_floor` → Claude + Codex co-sign that single number, then
register all variant configs. No open design questions remain.
