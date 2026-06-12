# Predictive Lab — Groundwork Notes (Stage 2, 2026-06-12)

Source: 3-agent groundwork fleet (`wf_792a4f05-b11`, ~277k tokens) — data census,
research→spec digestion, reusable-components survey — plus the prior research corpus
(`claude_predictive_layer_research.md`, `claude_predictive_layer_ideas.md`,
`codex_predictive_layer_and_backtest_ideas.md`, `codex_review_predictive_layer.md`).

## Headline verdicts

1. **The flagship is fully feasible on existing data.** All price fetchers use
   `period="max"` with atomic overwrite — full untruncated daily series (gold 25.8y;
   US miners to 1973; median ticker ~5,700 rows). Point-in-time views = slice
   `date <= t`. The structural-beta machinery is **already point-in-time by
   construction** (one row per ticker × weekly as-of × window via prefix sums; a
   185k-row panel over 1,361 weekly dates exists on disk).
2. **Natural backtest window: mid-2006 → now** (GDX starts 2006-05, AUD FX 2006-05;
   GDXJ from 2009-11). US-only analyses can go much deeper.
3. **Not backtestable (confirmed):** fundamentals (1 fetch vintage, no release dates),
   option signals (3 as-of dates), hedge signatures. These are **forward-test only**
   — which makes the F1 vintage recorder genuinely urgent: every un-snapshotted week
   is lost forever.
4. **🔴 LIVE BUG found by the survey (M0-1, fix immediately):** GDX/GDXJ benchmark
   histories are standardized to *local*-price columns
   (`ingestion/fetch_benchmarks.py:39-48` via `standardize.py:50-68`) but
   `build_weekly_return_frame` reads only `return_basis_usd`/`adj_close_usd`/`close_usd`
   (`features/weekly_returns.py:141-152`) → **`tool_c_latest.parquet` has 0 non-null
   `rel_weakness_vs_gdx_pct` / `rel_strength_vs_gdx_pct` rows today.** This silently
   nulls Tool C's benchmark-relative metrics in the live product, and every Lab
   alpha-vs-GDX label until fixed.

## The locked spec (converged across all docs)

- **Reframe (enforced by CI kill-list):** never predict gold. Predict relative,
  cross-sectional miner behaviour conditional on a *user-chosen* gold scenario.
  Gold-side data only as regime/conditioning/abstention variables. A test asserts no
  code path derives a "current scenario bucket" from realized gold.
- **Flagship — beta-gap nowcast:** weekly, per miner:
  `beta_gap = fast_effective_beta(26w EW, James-Stein-shrunk by its own SE) − slow_structural_beta(Tool A 156w)`,
  regime-split up/down. PRIMARY deliverable: calibrated nowcast of next-26w effective
  beta. **Pass gate (exact):** beat BOTH static-beta-persists AND raw-fast-beta-persists
  on next-26w-beta MAE by ≥10%, t>3, in ≥70% of walk-forward folds, no hidden
  deterioration in low-liquidity names. Built as a gated **experiment** (Codex HIGH);
  dial betas are replaced only after the gate passes. Alpha question is an
  explicitly-allowed-to-null secondary.
- **Spine — Conditional Dial analog table:** for a user-chosen gold 60d scenario
  bucket: P(beat GDX), median alpha, 10–90% range per PIT cohort; pure counting +
  empirical-Bayes shrinkage; Wilson intervals; raw N AND effective N shown; tail
  cells say "insufficient history", never a number.
- **Evaluation (admissibility conditions, not options):** walk-forward only;
  purge+embargo for overlapping labels; episode-based honest N; three leakage
  canaries (label-as-feature, shuffled labels, forward-shifted features) that the
  engine must CATCH in CI; variant ledger (sha256-registered configs BEFORE compute;
  deflated Sharpe reads n_trials from the ledger); t>3 bar; IC + quantile spread +
  hit rate vs six naive baselines + per-signal existential baselines.
- **Architecture:** backend-only data product — new sibling package
  (per components survey: imports app/common/contracts/features/model, never serve);
  run-stamped immutable artifacts + manifest integration; Lab page renders persisted
  artifacts only. Candidate Finder integration architecturally gated for later.

## Decisions D1–D6 (defaults adopted; Emanuel can override)

| # | Question | Default adopted (Codex compromise unless noted) |
|---|---|---|
| D1 | Label store scope | Multi-label (raw, alpha vs GDX+GDXJ, regimes, drawdown, quintiles) WITH mandatory contamination diagnostics |
| D2 | Survivorship gate | Schema-first; results labeled exploratory(survivor-only) vs confirmatory; hard gate only when coverage measured |
| D3 | M1 foundation size | Codex's minimum honest foundation; full PBO/block-conformal/Trust-Strip deferred to ship-live milestone |
| D4 | Gold conditioning boundary | One written rule: regime columns (trend/vol/real-rate/flows) and abstention gates allowed; gold-return TARGETS banned; no current-bucket-from-realized-gold |
| D5 | Skill ML wording | "No flexible ML in live decision surfaces; diagnostic ML behind red-team report only" |
| D6 | Faff/Chan 0.75 | Mark unverified; do not quote as fact |

Open for Emanuel (D7): the final pick of first builds. Converged shortlist adopted:
M0 spine → walk-forward harness → Conditional Dial table → beta-gap experiment →
price-only residual-momentum baseline.

## Reuse map (from components survey)

| Component | Verdict |
|---|---|
| `features/returns.py` horizon returns (every as-of date, coverage flags) | REUSE-AS-IS (forward returns = trailing at t+h; ~20-line helper) |
| `model/structural.py` weekly PIT beta panel (prefix sums, 6M/12M/3Y) | REUSE-AS-IS for those windows |
| Arbitrary windows (26w EW fast beta) | REUSE-WITH-PARAM — min-obs lookup hardwired to 6M/12M/3Y (`config_models.py:795-804`); pass explicit ints |
| `load_latest_foundation_snapshot` bulk load | REUSE-AS-IS (one call: gold + 62 histories) |
| `features/horizons.py` as-of window resolver | REUSE-AS-IS |
| Tool C conditional-on-gold (regimes, tail behavior) | REUSE-WITH-PARAM — truncate weekly frame per as-of; do NOT fork the math |
| `replay_manifest` | Provenance only — lab runs record foundation sha + config hash |
| Prediction scoring (IC/MAE/spread) | REIMPLEMENT thin in lab/ from existing primitives (compute_regression, oriented_percentile, weighted_median) |

## Known caveats to encode in outputs from day 1

- **Survivorship:** only today's 62 survivors have histories; no membership history.
  v1 results carry an explicit survivor-only caveat (D2 labeling).
- **Regime thresholds:** `gold_regime.py` includes the current week in its own rolling
  quantile — fine descriptively; the Lab must use strictly-prior thresholds when
  conditioning predictions.
- **FX floor:** 21 non-US tickers unusable in USD before their FX series start
  (CAD 2003-09, GBP 2003-12, AUD 2006-05); inclusion rules must respect
  `normalization_status == OK`.
- **Weekly W-FRI grid** is the zero-cost as-of grid; daily betas would be new code —
  not needed for the flagship.
- **Operational:** full option-chain snapshots live in prunable `data/runs/` dirs —
  archive them to a protected location before pruning eats the only perishable
  dataset (ties to the keep-full-chain decision).
- ARMN.parquet empty + 4 stale tickers (FNV/FRES.L/GOLD/NGD) — exclude or refresh.

## Build plan (M0 → M1, this stage)

- **M0-1 🔴 fix benchmark USD returns** + contract test asserting non-null
  rel-vs-GDX columns (live Tool C bug).
- **M0-2 `golden_vector/lab/` package:** `schemas.py` (feature/label/prediction/
  backtest-result contracts + variant ledger entry), `vintages.py` (F1 append-only
  weekly PIT vintage recorder for Tool B/D/option-signal/hedge fields — **start the
  clock now**), `ledger.py` (sha256 variant registry).
- **M0-3 weekly-return + forward-return artifact** built from existing machinery.
- **M1-1 walk-forward engine** (`walk_forward.py`): expanding-window folds on the
  W-FRI grid, purge+embargo, episode-N accounting.
- **M1-2 evaluation** (`evaluation.py`): rank-IC, MAE vs baselines, quantile spread,
  hit rate — industry-standard only.
- **M1-3 leakage canaries as CI tests** (the three rigged inputs must be caught).
- Then (next chunk): Conditional Dial analog table + beta-gap experiment run.

## Build log — 2026-06-12 (M0 + M1 shipped)

All of M0-1/M0-2/M0-3/M1-1/M1-2/M1-3 are BUILT, tested, and committed on dev-vic:

- **M0-1 ✅ benchmark USD fix is live.** `_price_basis` gained a currency-guarded
  fallback (only when ALL USD basis columns are null AND the frame's currency is
  uniformly USD → use `adj_close_local`/`close_local`). Verified against real cached
  GDX: 5,046/5,046 basis rows (was 0). Rebuilt Tool C offline:
  `rel_weakness_vs_gdx_pct` / `rel_strength_vs_gdx_pct` now **62/62 non-null**
  (was 0/62). Three contract tests incl. a non-USD negative case.
- **M0-2 ✅ `golden_vector/lab/`:** `ledger.py` (sha256 variant registry,
  `n_trials` from the ledger only, `require_registered` admissibility gate) and
  `vintages.py` (long-format append-only PIT recorder, first-write-wins per
  `(vintage_date, source, ticker, field)`). **The clock started 2026-06-12:**
  first vintage = 11,608 rows across 5 sources (tool_b 3131, tool_d 2829,
  tool_d_spot 2829, option_signal_summary 2294, option_trading_overview 525).
  Hooked into the end of `_run_refresh_unlocked` (best-effort: a vintage failure
  can never fail a refresh).
- **M0-3 ✅ `forward_returns.py`:** strictly-forward h-week labels
  (`rolling(h).sum().shift(-h)` = weeks t+1..t+h), complete-window-only (NaN in
  window → NA label, never a partial sum), alpha vs GDX/GDXJ. No gold-return
  labels by construction.
- **M1-1 ✅ `walk_forward.py`:** expanding folds on the W-FRI grid, purge =
  label horizon between train end and test start, `effective_n` = weeks/horizon,
  `assert_no_label_overlap` invariant.
- **M1-2 ✅ `evaluation.py`:** per-date Spearman rank IC + t-stat on
  episode-adjusted N, MAE, hit rate, quantile spread, `mae_improvement_pct` for
  the ≥10% flagship gate, and a **leakage alarm** (mean |IC| > 0.90 ⇒
  inadmissible).
- **M1-3 ✅ canaries:** label-as-feature trips the alarm; shuffled labels show
  no skill; a forward-shifted feature (built through the real label pipeline) is
  caught. 19 new tests, all green.
- **Full gate: 1035 passed, 0 failed** (the earlier 19-failure capture was the
  stale pre-N5-fix run). Adversarial 5-lens verification fleet launched over the
  lab package (leakage/stats, label construction, PIT semantics, benchmark-fix
  blast radius, test quality) — findings to be fixed serially before ship.

Next chunk: Conditional Dial analog table + beta-gap experiment (registered in
the variant ledger BEFORE compute), then Stage 0 ship fold-in (live refresh +
merge to main).

## Verification + ship record — 2026-06-12

**The 5-agent verification fleet died on the session limit (352k tokens, no
verdicts — an empty findings list from dead agents is NOT a clean bill).
Verification redone first-hand in the main loop:**

- Purge math proven on a tiny grid (gap 4w > 3w label reach, every fold).
- W-FRI period strings sort chronologically across year boundaries (proven
  1999→2026); groupby/sort on strings is safe.
- `_forward_sum` covers exactly t+1..t+h; NaN anywhere in the window ⇒ NA
  (pandas `min_periods=window` counts non-NaN — verified).
- Canary 2 not seed luck: 0/20 random shuffles trip |t|≥2.
- `_price_basis` has exactly ONE production caller (benchmark-only path);
  every other grep hit is the unrelated `gold_price_basis`. Real GDX/GDXJ:
  currency uniformly 'USD', 0 nulls, no `*_usd` cols — fallback fires only
  as designed.
- Refresh vintage hook sits after the last failure return ⇒ records only on
  full success.
- Real-data contiguity: 0 calendar gaps across all 65 tickers — but the
  invariant is now ENFORCED in `build_forward_return_panel` (reindex; missing
  week ⇒ NA labels, never a stretched window) + regression test.
- `_melt_snapshot` hardened for non-scalar values; vintage re-run on real
  stores = perfect no-op (idempotency proven).

**Live refresh smoke (2026-06-12 05:14 UTC):** Tools A–D green at fresh gold
$4212 (Tool C 54/54 ranked both directions — the benchmark fix live).
Vintages +231 rows in the real path. Options stage BLOCKED by design (market
closed; GDX=SPARSE/GDXJ=LOW_LIQUIDITY publish blocker; fail-closed kept prior
state; pages show the unavailable notice). **One refresh during US options
market hours (14:30–21:00 UTC) is needed to mint v3 option artifacts.**
Portfolio step skipped because `config/portfolio.yaml` has `enabled: false`
(pre-existing); alignment WARN about stale portfolio artifacts is the
manifest being honest, not a regression.

**Final gates: full suite 1036 passed / 0 failed.** Shipping dev-vic → main.
