# Program A — Tool Validation Pre-Registration Spec (v2 FINAL, 2026-06-12)

**v2 supersedes v1 after a 4-lens adversarial design review (49 findings: 4
BLOCKER, 13 HIGH; all integrated below; review record in the workflow output
and summarized in §8).** This document is binding once its experiments are
registered in `data/lab/variant_ledger.jsonl`. Gates cannot change after
registration; any follow-up variant raises the multiplicity count and must
say so. Nulls are shippable.

## 0. What each tool claims, and what we test (claim fidelity, corrected)

| Tool | What the user relies on | What we TEST (exact) | Untested (must be enumerated on the card) |
|---|---|---|---|
| Tool A | The **Δ Core gearing number** (`structural_delta_core`, the weighted MEDIAN across 6M/12M/3Y windows) and the page's composite rank | E1a: Δ Core rank **stability**; E1b: Δ Core rank **validity** vs forward realized beta | The composite `tool_a_score` ordering (gamma/asymmetry/confidence weighted; ρ≈0.30 to raw delta today), gamma & asymmetry favorability claims |
| Tool C downside | "Top of the downside table = **most fragile** when gold falls" (**HIGH score = MOST damaged** — orientation verified in `model/tool_c.py::_add_component_scores`: unweighted mean of fragility-oriented percentiles) | E3: downside composite vs forward down-capture, **orientation pinned in §2** | threshold/tag claims |
| Tool C upside | Symmetric claim: "top of upside table = most upside capture" | E3b: upside composite twin (the page claims symmetry; testing half would overstate) | — |
| Tool B / Tool D / Finder presets / option signals | various | **E4 forward accrual only** — outcomes, horizons, exact vintage FIELD NAMES pinned in §5 | everything until accrual completes |

**Look-ahead refusal (binding, unchanged):** no fabricated Tool B/D backtests
from today's single fundamentals vintage. Finder presets: **selection
behavior is untested** — presets are threshold-AND-conjunction filters, which
rank-IC results on underlying columns do NOT validate. The card must say so
verbatim.

## 1. Shared design (all backtest experiments) — corrected

- **Join key (binding):** every universe selection, rank extraction, and
  label join keys on the **W-FRI `week_period`**, never the raw
  `as_of_date` (4% of panel rows are stamped off-Friday; holiday weeks split
  the cross-section to fragments as small as 1 name — e.g. week of
  2014-12-26 splits 1/32/19). Per ticker per period: the latest row in that
  period. Forward windows = periods **strictly greater** than t's period.
  CI test: a synthetic Thursday-stamped ticker is neither dropped nor
  double-counted.
- **As-of grid:** experiment as-ofs every **26 periods**, anchored at
  **2004-04-23** (first ≥15-eligible cross-section). If a scheduled as-of
  has <15 eligible names or <80% of the median cross-section of the
  surrounding ±4 full weeks, step back one week (at most 2) before skipping
  the fold. Expected folds: **~43 (E1), ~38–40 (E2/E3/E3b, GDX era
  2006-05+, ~2 skipped for <8 forward down-weeks)**.
- **Forward horizon:** 26 weeks. Outcome windows are disjoint. (NOT claimed:
  fold independence under the alternative — rank windows overlap; see
  t-stat rule.)
- **Rank-at-t (binding):** `structural_delta_core` / `down_beta_core` are
  reconstructed PIT as the **weighted median across the panel's
  6M/12M/3Y windows** using the existing `weighted_median` +
  `structural_weight_map` config — the same math the product ships. No
  forked math; parity test required: reconstruction at the latest as-of must
  reproduce `tool_a_latest.parquet` core columns exactly.
- **t-stat rule (binding — closes the eff_n trap):** fold-level series use
  **n = number of folds**. The lab evaluator's `effective_n = n/h` division
  is for weekly overlapping samples and MUST NOT be applied to the
  pre-spaced disjoint grid (it would yield eff_n≈1.7 and void every gate).
  `validation.py` computes fold-level t directly as mean/se with a
  **Newey–West lag-1** standard error (rank windows overlap adjacent
  folds). Unit test: 43 synthetic disjoint folds → finite t scaled by √43;
  calling the weekly-evaluator path with h=26 on this grid must raise.
- **Sidedness (binding):** all gate tests are **one-sided** in the
  registered direction (every hypothesis is directional). Multiplicity:
  **m = 5 gated experiments** (E1a, E1b, E2, E3, E3b). t>3 one-sided at
  df≈37–42 gives p≈0.0023; ×5 = 0.0115 → **family-wise α ≈ 0.012**:
  survives α=0.05 with margin; effectively at the α=0.01 boundary — stated
  honestly here. Prior ledger entries (beta_gap ×2, conditional_dial) are a
  separate, already-reported family; this program's family is the
  `validation_*` signal-id prefix.
- **Noise ceiling (mandatory companion output):** every experiment
  publishes a per-fold **outcome split-half self-consistency** (forward
  outcome computed on odd vs even forward weeks — or odd/even down-weeks
  for E2/E3 — rank-correlated). Outcome-vs-outcome, so it never unblinds
  the feature. **INCONCLUSIVE rule (pre-registered):** if gates fail AND
  the median split-half consistency < 0.30, the verdict is
  **INCONCLUSIVE — outcome unmeasurable at this horizon**, not NOT
  SUPPORTED.
- **Caveats bound into every headline:** survivor-only universe (verdict
  word capped at **SUPPORTED**, never VALIDATED, until dead-miner records
  exist — see §3); code-vintage (the panel is data-PIT but regenerated with
  2026 code/config/universe/back-adjusted prices — caveat string required;
  panel `source_run_id` 20260612T051338Z + config hash recorded in each
  ledger entry).
- **Robustness slices (pre-registered, reported beside headline):**
  (a) fixed cohort = tickers eligible before 2010-01-01 only;
  (b) 52w-spaced fold grid (~half the folds) for any SUPPORTED verdict.
- **Descriptive extras (ungated):** top-5 vs bottom-5 mean forward outcome
  per fold; per-fold IC vs its ceiling; fold-IC lag-1 autocorrelation.
- **Tercile rule:** terciles by average-rank with fixed boundaries; ties
  broken by ticker (deterministic).

## 2. The experiments (gates corrected per review)

### E1a — Tool A Δ Core rank STABILITY (`validation_e1a`)
- **Statistic:** Spearman between Δ Core ranks at t and at **t+52** (52, not
  26 — adjacent 12M windows share 26 weeks and would mechanically inflate
  stability). ~21 non-overlapping fold pairs.
- **Gates (level claim — no t-gate; sampling error of the mean at n≈21,
  fold-std≈0.15 is ±0.03, far inside the gate margin):**
  1. mean stability-IC ≥ **0.45** (measured reliability ceiling ≈ 0.60);
  2. stability-IC ≥ 0.30 in ≥ **80%** of fold pairs.

### E1b — Tool A Δ Core rank VALIDITY vs realized beta (`validation_e1b`)
- **Outcome:** realized OLS beta over the 26 forward weeks (≥20 weeks
  present per ticker, else dropped; count reported per fold).
- **Gates:**
  1. mean fold IC > 0, one-sided **NW-t > 3**;
  2. IC > 0 in ≥ **70%** of folds;
  3. **tercile-PORTFOLIO** forward-beta spread (top-tercile mean minus
     bottom-tercile mean, portfolio averaging cuts noise ≈√18) ≥ **0.20**
     beta units with one-sided t > 2. (Calibration: today's true Δ Core
     tercile spread ≈ 0.57; × measured 26w rank autocorrelation ≈ 0.73 →
     perfect-persistence expectation ≈ 0.42; gate = ~half.)
- **Baselines (paired, not fold-win counting — a 50% fold-win rule passes
  under the null 56% of the time):** one-sided **paired t > 2** on per-fold
  IC differences vs (a) the single 12M window column ("does the multi-window
  core add anything?") and (b) a fresh 26w trailing beta computed from the
  truncated weekly frame, ≥20 trailing weeks (mirror rule), intersection of
  rankable names ("does window length matter?"). Baseline outcomes do NOT
  change SUPPORTED/NOT SUPPORTED; failing (a) or (b) adds the pre-registered
  verbatim card line: *"A simpler {12M-window / 26-week trailing} beta
  ranked as well or better (paired p ≥ 0.05); the {multi-window core /
  longer window} adds no measured edge."*

### E2 — Tool A/C down-beta-core VALIDITY in future gold-down weeks (`validation_e2`)
- **Rank at t:** reconstructed `down_beta_core` (weighted median).
- **Outcome:** OLS down-beta over forward gold-down weeks. Fold floor ≥ 8
  forward down-weeks; **per-ticker floor ≥ 8 usable down-weeks** (raised
  from 6: an n=6 slope has se ≈ 2 beta units — pure noise rows).
- **Gates (redesigned — review proved the v1 median-IC ≥ 0.5 gate sat ABOVE
  the measured noise ceiling of ≈ 0.18–0.35 median: the experiment was
  designed to fail):**
  1. mean fold IC > 0, one-sided **NW-t > 3**;
  2. IC > 0 in ≥ **70%** of folds;
  3. tercile-portfolio forward down-beta spread ≥ **0.35** beta units with
     one-sided t > 2 (calibration: true down-beta tercile spread ≈ 1.35 ×
     autocorrelation ≈ 0.56 → expectation ≈ 0.75; gate = ~half).
- **Baseline:** paired t vs fresh 26w trailing down-beta (≥8 trailing
  down-weeks mirror rule).
- **Verdict conditionality (stated on card):** applies to forward halves
  with ≥8 gold-down weeks (~95% of history; skipped folds reported).

### E3 — Tool C downside composite (`validation_e3`) — ORIENTATION PINNED
- **Rank at t:** the real Tool C downside score reconstructed PIT — exact
  call chain (no invented weights; the composite is an UNWEIGHTED mean of
  fragility-oriented percentiles): slice panel to fold weeks →
  `build_tool_a_outputs_from_metrics` + `compute_volatility_diagnostics`
  on the slice (NOT all 1,345 weeks) → truncate weekly frame to ≤ t →
  `build_gold_regime_frame` + `compute_relative_behavior_metrics` →
  `build_tool_c_output_frame` with PIT-reconstructed `score_eligible`,
  `confidence_score`, `down_beta_core`, preserving
  `MIN_DOWNSIDE_COMPONENTS=3` sinking. **Parity test:** reconstruction at
  the latest as-of reproduces live `tool_c_latest.parquet` downside scores.
  Pre-2008 folds run a reduced composite (rel-vs-GDX/GDXJ components not yet
  accrued) exactly as the live tool would have — per-fold component coverage
  reported.
- **Outcome:** **per-week MEAN** down-capture vs GDX over forward gold-down
  weeks (mean, not sum — sum confounds coverage with behavior). Higher =
  held up better.
- **ORIENTATION (the v1 BLOCKER):** HIGH downside score = MOST FRAGILE.
  **Registered direction: IC(downside_score, down_capture) < 0**; spread
  gate: top-score-tercile minus bottom-score-tercile down-capture **< 0**.
  **Sign canary (CI):** a synthetic always-resilient ticker must land at the
  LOW-score end and produce the registered-direction contribution; asserted
  end-to-end in the validation module.
- **Gates:** 1. mean IC < 0, one-sided NW-t > 3 (on −IC); 2. IC < 0 in
  ≥ 70% of folds; 3. tercile spread < 0 with one-sided t > 2 (magnitude
  descriptive).
- **Baseline:** paired t vs the down_beta_core-only ranking
  (consistently oriented: compare |IC| improvements on the SAME outcome) —
  failing adds the verbatim line *"the single down-beta component ranked as
  well as the 6-component composite."*

### E3b — Tool C upside composite twin (`validation_e3b`)
Mirror of E3: upside score (HIGH = most upside capture per page claim —
orientation verified from code at build time + sign canary), outcome =
per-week mean up-capture vs GDX over forward gold-UP weeks (up-weeks are
never scarce: ≥8 in 100% of historical windows), gates mirrored in the
registered direction, baseline = up_beta_core-only.

## 3. Verdict vocabulary (binding strings)

- **SUPPORTED (exploratory — survivor-only universe)** — all gates pass.
  The qualifier lives INSIDE the headline string. VALIDATED is reserved for
  post-dead-miner-registry confirmatory reruns and cannot appear in v1.
- **PARTIAL** — some gates pass; the card lists each gate pass/fail.
- **NOT SUPPORTED** — gates fail and the outcome was measurable (split-half
  ceiling ≥ 0.30).
- **INCONCLUSIVE — outcome unmeasurable at this horizon** — gates fail AND
  median split-half < 0.30.
- **ACCRUING (first verdict expected {date})** — forward-only signals.
- Baseline-failure verbatim lines per §2. Tested-vs-untested enumeration
  per §0 is mandatory on every card. NOT SUPPORTED ships as prominently as
  SUPPORTED.

## 4. Canaries (CI, all numeric)

1. label-as-feature → |IC| ≈ 1 trips inadmissibility;
2. shuffled ranks: **20 fixed-seed shuffles, at most 2 may show |t| ≥ 2**
   (single-shuffle criterion is ~5% flaky by construction);
3. time-reversal contrast: contaminated rank (built from forward-window
   data) must beat the honest rank by **ΔIC ≥ 0.15** AND the harness must
   emit `contaminated=True` which the Scorecard build refuses to publish;
4. sign-convention canaries for E3/E3b (synthetic resilient/fragile
   tickers);
5. eff_n guard: disjoint-grid t-path must use n_folds (h=26 on this grid
   raises);
6. **0.90 |IC| alarm semantics for persistence experiments (E1a):** the
   absolute alarm does NOT auto-void; it halts publication pending audit,
   documented in the run meta — the binding admissibility test for
   persistence classes is the time-reversal contrast (3).

## 5. E4 — forward accrual protocol (pinned; no forking paths)

| Signal | Vintage FIELD (verified non-null in store) | Outcome (13w horizon) | Accrual start | First verdict (20 disjoint 13w windows ≈ 5y) |
|---|---|---|---|---|
| Tool B health rank | `fundamental_check_score` (NOT `tool_b_score` — that column is null legacy) | 13w forward alpha vs GDX, rank IC | 2026-04-22 (backfill) | **~2031-04** |
| Tool D resilience | `tool_d_quality_score` (orientation pinned from code at build + sign canary) | 13w forward per-week mean down-capture vs GDX | 2026-06-05 | **~2031-06** |
| Option residual skew | `skew_residual_signal` | 13w forward down-capture vs GDX | 2026-06-08 | **~2031-06** |
| Option IV percentile | `iv_percentile_cross_sectional` | 13w forward realized-vol percentile | 2026-06-08 | **~2031-06** |

Rules: horizon = **13 weeks** (26w would push first verdicts to ~2036 — a
product decision made HERE, not after data accrues); N counts **completed
DISJOINT windows only** (episode rule), never raw weekly rows; weekly dedup
= last vintage per W-FRI period; a vintage week enters the record only if
≥15 names AND ≥80% of the trailing-4-week median cross-section (the panel's
leading edge is routinely partial); contract test asserts each pinned field
is non-null in the live store. The card shows accrued N and the computed
first-verdict date — never a verdict early.

## 6. The tool that ships

`golden_vector/lab/validation.py` (compute → run-stamped
`scorecard_latest.parquet` + meta via atomic writes; rebuild =
`python -m golden_vector.lab.validation`) + `/scorecard` page (render-only;
one rank column; static-scan guardrail cloned from /lab; D2 help popovers
per claim). Scorecard artifacts intentionally live OUTSIDE the model-state
manifest (research artifacts, matching the /lab dial precedent); provenance
= variant ledger + run-stamped meta.

## 7. Execution order (banked)

1. ✅ spec v1 → 4-lens adversarial design review (49 findings) → this v2;
2. register `validation_e1a/e1b/e2/e3/e3b/e4_protocol` in the ledger;
3. build validation module + canaries + tests → verification fleet on the
   implementation;
4. run once; bank artifacts + verdicts;
5. Scorecard page; ship via milestone workflow.

## 8. Material v1→v2 changes (audit trail)

- E3/E3b orientation pinned (v1 gates were SIGN-INVERTED vs the real score
  — a working tool would have read NOT SUPPORTED);
- E1 re-targeted from raw 12M delta (ρ≈0.30 to the page rank) to the
  weighted-median **core** columns the product headlines, split into
  stability (E1a) + validity (E1b); composite/gamma/asymmetry enumerated
  untested;
- E2 gates rebuilt around tercile portfolios (v1 median-IC ≥ 0.5 was above
  the measured noise ceiling ≈ 0.18–0.35 — designed to fail);
- t-stat path pinned to n_folds + NW lag-1 (the lab evaluator's n/h
  correction would have voided every t-gate at eff_n≈1.7);
- W-FRI week_period join keying + grid hygiene (holiday-split fragments);
- one-sided tests declared; m=5 family; honest α arithmetic;
- INCONCLUSIVE verdict + split-half noise ceiling as mandatory output;
- SUPPORTED-not-VALIDATED cap with survivor qualifier inside the headline;
- baselines: paired t (fold-win counting passed under the null 56% of the
  time); naive-baseline framing corrected ("window length", not
  "machinery" — the 12M delta IS a trailing beta);
- E3 mean (not sum) down-capture; per-ticker down-week floor 8; reduced
  pre-2008 composite disclosed; parity tests vs live artifacts;
- E4 fully pinned (real field names — `tool_b_score` is null legacy;
  13w horizon; honest ~2031 first-verdict dates printed);
- canaries made numeric; code-vintage caveat + panel run id into ledger.
