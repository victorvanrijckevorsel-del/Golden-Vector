# Phase 5 — Capture & Behaviour engine: pre-registered walk-forward backtest spec

Status: **v2 DRAFT for Codex review** (Claude). Mirrors the rigor + structure of
`claude_program_a_validation_spec.md` (which shipped as the `/scorecard`). Nothing here runs until
this spec is reviewed (Codex), frozen, and every variant config is registered in the ledger.

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
(CONVEX/HEDGE/TORQUE/DEAD_WEIGHT) as a classifier — it is tested only via its *components* (E1
capture + E2 convexity); absolute capture levels; archetype/peer **stability** over time; transaction
costs; dead/delisted miners; the fundamentals/Tool-D/option signals; calibration over live time.

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
  with margin). `m` is written into every registered config; a drift test asserts the live family
  count equals 4. (This resolves the §11 scope so no gate is frozen against an undefined denominator.)
- **Universe / spine.** The persisted, run-stamped `dial_episodes` frame is the legal spine
  (immutable, sha256-stamped). Features and labels are read/derived from it; no request-path compute.
- **Join key.** W-FRI `week_period` strings only — never a raw `as_of_date`. (Mirrors Program A.)
- **As-of grid.** Expanding-window walk-forward via `walk_forward.generate_folds(week_periods,
  label_horizon_weeks=H, min_train_weeks=…, test_weeks=…, step_weeks=…)`. Folds carry an explicit
  `purged_periods` zone already excised from `train_periods`; we additionally call
  `assert_no_label_overlap(fold, label_horizon_weeks=H)` on every fold (belt-and-braces).
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
- **Deflated Sharpe Ratio (reported diagnostic).** Per experiment, report the DSR (Bailey & López de
  Prado) of the tercile long-short return series, with the variant count read from the **ledger
  `n_trials`** (never a hand-passed number) plus the skew/kurtosis + track-length adjustment. DSR > 0
  is a floor; the binding gate stays the IC NW-t + baseline gauntlet, but a signal that clears the IC
  bar yet has DSR ≤ 0 is flagged on the card (short/​skewed track record). (This satisfies the
  predictive-models rule against quoting performance without deflation + # variants.)
- **No ML.** Ranks and at most a single heavily-shrunk logistic/linear model. No trees, no NN, no
  gradient boosting (breadth ≈ 5–15 independent bets → flexible ML overfits by construction). Any
  model beyond a rank requires a red-team overfit note.
- **Tercile-portfolio spreads, not fold-win counts**, for effect size: sort names into terciles by
  the feature each fold (average-rank, ties by ticker — deterministic), measure the forward-label
  spread (top − bottom), t-test the per-fold spread series.
- **Noise ceiling (mandatory output).** Split-half outcome self-consistency (odd vs even forward
  weeks). A failing experiment is **NOT SUPPORTED** only if the split-half ceiling ≥ 0.30; otherwise
  **INCONCLUSIVE** (the outcome is unmeasurable at this horizon/breadth, not disproven).
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
  5. beats **≥ 5 of 6** baselines (§3) by paired NW-t, p < 0.05.

### E2 — Convexity validity (the CONVEX offense default)
- **id:** `p5_behaviour_convexity_validity`
- **Hypothesis:** higher `convexity` (= up_capture − down_capture) ranks higher forward
  *asymmetry* = (fwd_alpha in next gold-up window) − (fwd_alpha in next gold-down window) per name.
- **Feature:** `convexity` reconstructed per fold (train weeks only), at the default capture horizon.
- **Label:** per-name forward up-window-alpha minus forward down-window-alpha over the test span.
- **Gates:** same shape as E1 (1–3, 5); per-cell floor requires both sides ≥ 6 effective episodes.

### E3 — Peer-rank persistence (the "stronger miner" claim)
- **id:** `p5_behaviour_peer_persistence`
- **Hypothesis:** trailing `peer_percentile_median` (direction-specific) positively ranks the
  forward peer percentile / forward `fwd_alpha_gdx` rank — relative strength persists.
- **Feature:** trailing `peer_percentile_median` from `train_periods` peer points only.
- **Label:** forward peer percentile (recomputed on test-window episodes) AND `fwd_alpha_gdx_Hw` rank
  (two registered label variants).
- **Gates:** E1 gates 1–3 + 5; floor: pool `peer_count ≥ 20` (live `min_peer_count`).

### E4 — Behaviour-change INCREMENTAL value (FLAGSHIP; null pre-committed)
- **id:** `p5_behaviour_trend_incremental` (H=8 primary, H=13 robustness)
- **Hypothesis:** the recent-vs-older signal (`trend_delta_raw` sign, gated as in the live engine)
  predicts the forward beat-rate change **better than the all-history baseline** (the static
  `all_p_beat_shrunk` point estimate). This is the core novelty — does the time-decay view add
  anything beyond "use the whole history"?
- **Feature (signal):** `trend_delta_raw` (and the live gate: |raw| & |shrunk| ≥ threshold, MK sign,
  FDR) reconstructed per fold; **Baseline feature:** all-history shrunk beat rate.
- **Label:** the realized forward change in beat-rate vs GDX over the next window (and `fwd_alpha`).
- **Gate (the bar):** the trend signal's per-fold IC must **exceed the baseline's** by a paired
  fold-level **NW-t > 3**, AND add positive directed IC itself, AND clear the §3 baselines.
- **Pre-committed NULL:** if E4 fails, the scorecard ships the verbatim string *"On the survivor
  set, the recent-vs-older behaviour-change view did NOT add predictive value over the all-history
  estimate (paired NW-t = X, p = Y). The trend panel stays descriptive."* — a shipped null, per the
  predictive-models doctrine (the null is the modal, honest outcome at this breadth).

> Alpha-trend (`alpha_slope_per_year`) is tested as a **robustness slice inside E4** (same machinery,
> alpha label), not a separate headline — to keep the family size honest.

---

## 3. Baseline gauntlet (every experiment must beat ≥ 5 of 6, paired, after the noise ceiling)

Each baseline is a rank reconstructed per fold from `train_periods` and scored against the SAME label
as the experiment, so the comparison is apples-to-apples:

1. **equal-weight** (all names tied → IC ≈ 0 reference);
2. **GDX/GDXJ buy-and-hold** (the benchmark the alpha is measured against → 0 by construction; sanity);
3. **up-beta-only rank** — Tool A structural up-beta (`structural` model column), no behaviour signal;
4. **down-beta-only rank** — Tool A structural down-beta;
5. **all-history point estimate of the SAME quantity** the experiment uses (E1→all-history capture;
   E3→all-history peer-percentile median; E4→`all_p_beat_shrunk`) with NO time-decay / NO recent
   reframing — the "just use the whole history" null;
6. **26-week trailing momentum rank** (cumulative `stock_log_ret` over the trailing 26 weeks).

Comparison is a **one-sided paired Newey–West lag-1 t on the per-fold IC difference** (experiment −
baseline), df = n_folds, significance at p < 0.05; "beats" = the experiment's IC exceeds the
baseline's at that bar. The **≥ 5 of 6** rule is the multiplicity stance for the gauntlet (a single
baseline tie does not sink an otherwise-clean signal). A signal that cannot beat baseline 5 ("use the
whole history") is not earning its complexity — that comparison is the load-bearing one for E4.

---

## 4. Acceptance bar pre-registration (co-signed before any number is seen)

Because breadth caps achievable IR, an absolute IC floor cannot be guessed honestly. The procedure,
locked before compute:
1. Measure weekly **N_eff** (Ledoit–Wolf-shrunk residual-correlation participation ratio) on a
   **frozen pre-registration window** = the episode spine up to a fixed as-of date written in the
   ledger config. N_eff is a property of the residual-return covariance, not of any label, so
   measuring it leaks nothing — but pinning the window forbids re-measuring it after seeing results.
2. Derive the **required IC** to reach the **target IR ≈ 0.3 gross** (locked here; resolves §11.3)
   with **transfer coefficient 0.5** (literature default), via IR_ceiling ≈ IC × √N_eff × transfer.
3. **Claude + Codex co-sign** the resulting numeric IC floor + the gate set above, hash-locked in the
   ledger, **before** `evaluate_predictions` is ever called on real labels.
A pre-registered unreachable bar is meaningless; a lax one rubber-stamps noise — so the bar is
derived from breadth, not taste, and frozen. (N_eff and the IR-ceiling math are **new code** — see §8.)

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
- **PARTIAL** — some gates pass; the card lists each gate pass/fail.
- **NOT SUPPORTED** — gates fail AND the split-half ceiling ≥ 0.30 (outcome was measurable).
- **INCONCLUSIVE** — gates fail AND split-half ceiling < 0.30 (unmeasurable at this horizon/breadth).
- **NULL (shipped)** — E4's pre-committed "added no value" string.

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
  spread, hit-rate, leakage alarm); `forward_returns.build_forward_return_panel`;
  `ledger.register_variant` / `require_registered` / `n_trials`; the `scorecard`-style publisher.
- **GENUINELY NEW code this spec requires** (acknowledged, not hidden — they belong in
  `behaviour_backtest.py` or a shared `lab/statistics.py` addition, grep-first): (a) **per-fold
  feature reconstruction** of capture/convexity/peer-rank/trend on `train_periods` only; (b) the
  **fold-level Newey–West lag-1 t** on the per-fold IC/spread series (evaluation.py has only the
  effective-N IC t-stat); (c) **N_eff / effective-breadth** (Ledoit–Wolf shrunk residual-correlation
  participation ratio) + the IR-ceiling math; (d) **Deflated Sharpe Ratio**; (e) the **label
  contamination check** (regress P&L on forward gold, flag R²>0.20 / |t|>3); (f) the **9-canary
  harness**. Each is a small, tested addition — but they ARE new, and the build estimate must include
  them.
- Run-stamped artifact `data/lab/behaviour_backtest_<stamp>.parquet` + `_latest` alias + meta JSON
  (registered variant hashes, n_trials, N_eff, gate pass/fail, canary results, source-spine sha256,
  built-at). All-or-nothing publish via `write_run_stamped_set`; publisher refuses on any failed
  canary or `contaminated=True` (mirrors the Scorecard publisher).
- Serve: a section on the existing `/scorecard` page (render-only, guardrailed), each experiment a
  card with verdict + key numbers + the §0 untested list + the survivor caveat. No new compute in
  serve (static-scan guard extended).

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

**Still genuinely for Codex (judgement calls, not blockers):**
- Is **target IR 0.3 / transfer 0.5** the right pre-committed bar for a ~60-name survivor universe, or
  too lax/strict? (The number is load-bearing — co-sign or counter-propose before any compute.)
- For the **fold-level NW-t**, is lag-1 enough given 8–13w label overlap, or should the NW lag scale
  with the horizon? (Program A used lag-1 on a 26w disjoint grid.)
- Is the **DSR reported-not-gated** stance acceptable, or should DSR > critical be a binding gate?
- Walk-forward **fold parameters** (`min_train_weeks`, `test_weeks`, `step_weeks`) — propose values
  given the ~2010→now weekly span and how many disjoint folds that yields (affects every t df).
