# Program A — Tool Validation Pre-Registration Spec (v1, 2026-06-12)

**Goal:** measure whether each Golden Vector tool's RANKING does what it
claims, out of sample, walk-forward — then ship the verdicts as a living
"Scorecard" page. Nulls are shippable. This document is written BEFORE any
compute; gates here are binding. Experiments register in the variant ledger
before running (`data/lab/variant_ledger.jsonl`); no re-runs without a new
registered variant and a raised multiplicity bar.

## 0. What each tool actually claims (claim fidelity)

| Tool | The product claim (what a user relies on) | Honest testability |
|---|---|---|
| Tool A Gold Sensitivity | "This ranking tells you which miners are MORE/LESS geared to gold, and it holds going forward" — a *stability/validity* claim, NOT an alpha claim | ✅ Backtestable (price-only, PIT panel exists 2000→now) |
| Tool C Gold Downside | "Top-ranked names hold up better than bottom-ranked when gold falls" — a *conditional behavior* claim | ✅ Backtestable (all 6 components price-based, reconstructable PIT) |
| Tool B Corporate Finance | "High scores = financially healthier companies" | ❌ NOT backtestable: manual fundamentals have ONE vintage (no history). Forward-only |
| Tool D Resilience | "High rank = survives gold stress better" | ❌ Same single-vintage problem. Forward-only |
| Candidate Finder presets | "Bull/Bear presets select fitting names" | ❌ Bull = 6/7 fundamentals criteria → forward-only. Price criteria are covered by E1/E2/E3 |
| Option signals (skew, IV) | "Residual skew / IV rank inform option entries" | ❌ 3 as-of dates exist. Forward-only (vintage clock started 2026-06-08) |

**Look-ahead refusal (binding):** we could fabricate Tool B/D backtests by
scoring history with TODAY's fundamentals. We refuse: those tools enter the
Scorecard as "forward track record accruing since 2026-06" with an expected
first-verdict date. This refusal is itself a Scorecard feature.

## 1. Shared design (all backtest experiments)

- **As-of grid:** W-FRI weekly panel; experiment as-ofs every **26 weeks**
  (disjoint forward windows → per-fold outcomes are serially independent;
  no overlap correction needed in the t-stat).
- **Forward horizon:** 26 weeks (t+1 .. t+26), label strictly forward.
- **Universe at t:** tickers with an ELIGIBLE 12M window at t
  (`window_status`), week_count ≥ existing config floor, and (for
  GDX-relative outcomes) `gdx_log_ret` present. Fold skipped if
  cross-section < 15 names.
- **Caveats carried on every result:** survivor-only universe (today's 62
  names; no dead-miner records yet → all results labeled EXPLORATORY per
  decision D2); weekly W-FRI basis; USD basis.
- **Data:** `tool_a_structural_latest.parquet` (185,895 rows; per ticker ×
  week × {6M,12M,3Y}: structural_delta, up_beta, down_beta, gamma,
  asymmetry_ratio, r_squared, week_count, window_status — PIT by
  construction) + `build_weekly_return_frame` (stock/gold/GDX/GDXJ weekly
  log returns; GDX era starts 2006-05).
- **Engine:** existing `lab/` machinery — evaluation.py rank IC/quantile
  spread, ledger registration, leakage canaries extended per §4.
- **Multiplicity:** 3 registered experiments in this program. Gates demand
  t > 3 (per-fold-mean basis), which survives Bonferroni m=3 at α=0.01.
  Any follow-up variant raises m and must say so in its verdict.

## 2. The experiments

### E1 — Tool A: does the gold-beta ranking hold forward?
- **Rank at t:** cross-sectional rank of `structural_delta` (12M window) from
  the PIT panel.
- **Forward outcome:** realized beta over t+1..t+26 = OLS slope of weekly
  stock log-returns on gold log-returns (≥ 20 of 26 weeks present, else
  ticker dropped from that fold).
- **Metrics:** per-fold Spearman rank IC; top-tercile minus bottom-tercile
  mean forward beta (terciles by rank at t).
- **Pre-registered PASS gates (all must hold):**
  1. median fold IC ≥ 0.50;
  2. t > 3 on the fold-IC series (mean/std·√n, folds disjoint);
  3. IC > 0 in ≥ 80% of folds;
  4. mean tercile spread ≥ 0.5 beta units.
- **Baselines (reported alongside, existential):**
  - random ranking (must be ≈ 0 — sanity);
  - **naive trailing beta**: rank by raw 26w realized beta over t−26..t.
    Tool A must achieve fold-IC ≥ naive's in ≥ 50% of folds — else the
    structural machinery adds nothing over a one-line trailing beta.
- **Period:** earliest panel date with eligible cross-section → last t with
  a complete forward window. Gold-only (no GDX needed).

### E2 — Tool A/C: does the DOWN-beta ranking predict behavior in future gold-down weeks?
- **Rank at t:** cross-sectional rank of `down_beta` (12M) from the panel.
- **Forward outcome:** realized down-beta over t+1..t+26 = OLS slope on the
  subset of forward weeks where gold's weekly log-return < 0. Fold requires
  ≥ 8 forward gold-down weeks AND ≥ 6 usable weeks per ticker, else skipped.
- **Metrics & gates:** same structure as E1 (median IC ≥ 0.50, t > 3, ≥ 80%
  folds positive, tercile spread ≥ 0.5).
- **Baseline:** naive trailing down-beta (t−26..t, gold-down weeks).

### E3 — Tool C: does the downside COMPOSITE rank forward-predict down-capture vs GDX?
- **Rank at t:** the actual Tool C downside score, reconstructed PIT: weekly
  frame truncated to ≤ t → existing `features/relative_behavior` components
  (rel_weakness vs gold/GDX/GDXJ, downside hit rate) + downside vol (52w
  trailing at t) + panel `down_beta` → through the existing Tool C
  composite/ranking function with live config weights. **No forked math** —
  parameterize/truncate the existing pipeline.
- **Forward outcome ("down-capture vs GDX"):** sum over forward gold-down
  weeks of (stock log-ret − GDX log-ret). Higher = held up better when gold
  fell. Same fold-skip rules as E2.
- **Metrics:** per-fold Spearman IC between downside score and forward
  down-capture; top-tercile minus bottom-tercile mean down-capture.
- **Pre-registered PASS gates:**
  1. mean IC > 0 with t > 3;
  2. IC > 0 in ≥ 70% of folds;
  3. tercile spread > 0 with t > 2 (magnitude reported descriptively, not
     gated — no defensible prior for its size).
- **Baseline:** down_beta-only ranking (E2's ranking) — the composite must
  achieve fold-IC ≥ the single-component baseline in ≥ 50% of folds, else
  the extra components add nothing.
- **Period:** GDX era (2006-05 →).

### E4 — Forward-accrual scaffolding (Tool B, Tool D, Finder presets, option signals)
Not a backtest. Build the protocol that turns weekly PIT vintages into an
accruing forward record:
- each scorecard build joins vintage snapshots (score at t) to realized
  forward outcomes as they complete;
- per signal: accrued N (weeks), current rank IC with CI, and "first
  verdict expected at N ≥ 20 independent observations";
- displayed honestly as ACCRUING, never as a verdict before N is reached.

## 3. Verdict vocabulary (what the Scorecard will say)

Per claim: **VALIDATED** (all gates pass) / **PARTIAL** (some gates; listed)
/ **NOT SUPPORTED** (gates fail) / **ACCRUING** (forward-only) — always with
N folds, the IC distribution, baselines, and the survivor-only caveat. A
NOT SUPPORTED verdict ships exactly as prominently as a VALIDATED one.

## 4. Leakage canaries (CI tests, must be caught before results are trusted)

1. label-as-feature: rank = forward realized beta → IC ≈ 1 must trip the
   inadmissibility alarm;
2. shuffled ranks at t → |t-stat| < 2;
3. time-reversal: rank at t computed from t+1..t+26 data (deliberately
   contaminated) must score dramatically higher than the honest rank — and
   the harness must label it contaminated, proving the honest path can't
   see the future.

## 5. The tool that ships (after research)

- `golden_vector/lab/validation.py` — computes E1–E3 + E4 accruals; persists
  run-stamped `scorecard_latest.parquet` + meta (variant hashes, gates,
  verdicts) via atomic writes; registered in the ledger.
- `/scorecard` workspace page (serve renders persisted verdicts only; one
  rank column; static-scan guardrail like /lab) with plain-English verdict
  cards + per-claim popovers using the D2 help layer.
- Rebuild command: `python -m golden_vector.lab.validation`.

## 6. Execution order (banked chunks)

1. this spec → adversarial design review (4-lens fleet) → fix → commit;
2. register E1/E2/E3 variants in the ledger;
3. build validation module + canaries + tests (verification fleet on the
   implementation);
4. run experiments once; bank artifacts + verdicts;
5. build Scorecard page; ship via milestone workflow.
