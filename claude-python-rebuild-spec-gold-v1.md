# Claude Rebuild Spec — Gold Tool v1 → Python Product

## Document purpose
This file is the **implementation context pack** for rebuilding the original tool in Python (with Claude Code) in a cleaner, more reliable architecture.

It focuses on:
1. What the original v1 tool was trying to do.
2. How its logic/workflow was structured.
3. What went wrong at the conceptual/data-design level.
4. What minimum raw-data foundation is required before building analytics/UI.

It intentionally avoids Excel/VBA-specific implementation errors and instead captures **product + data architecture lessons**.

---

## Scope and source artifacts

### Primary tool (v1 to be rebuilt)
- `Gold_Tickers_Historical_Prices_Final_WORKING2_EDITED_v3.xlsm`

### Raw-data rebuild foundation (reference for proper architecture)
- `Gold_RawData_Foundation_v9.xlsx`

### What this spec does *not* include
- Detailed internals of friend’s separate file `Gold_Mining_Screening_Updated_18Feb2026`.
- Reason: prior project discussion did not establish enough validated model logic from that file; we should not invent behavior.

---

## 1) Product intent of v1 (what it was built to achieve)

The v1 tool is a gold-equity sensitivity and ranking system designed to answer:

- Which gold-related equities behave as stronger/weaker exposure to gold moves?
- How does sensitivity differ by time horizon?
- Which names look more attractive when combining sensitivity, convexity-like behavior, and stability?
- How can a user quickly screen, rank, and compare candidates?

### User-facing capabilities in v1
1. **Universe-level ranking** of tickers.
2. **Mode + horizon controls** (e.g., DELTA/GAMMA mode and 5D→3Y horizons).
3. **Profile/screener filtering** by delta, gamma proxy, stability, regime.
4. **Single-name deep-dive** with comparator and horizon-aware snapshots.
5. **Decision framing** (score/verdict/action-style labels).

---

## 2) Verified sheet structure of v1

Workbook tabs observed in `...v3.xlsm`:

1. `Company_DeepDive`
2. `Profile_Screener`
3. `Dashboard_ClearView`
4. `Tickers_And_Source`
5. `Historical_Prices_Daily`
6. `Gold_Delta_By_Horizon`
7. `Sensitivity_Profile`
8. `Summary_Dashboard`
9. `Ranked_View`
10. `Ticker_Currency_Map_USD`
11. `FX_Daily_USD`
12. `Gold_Delta_By_Horizon_USD`
13. `Sheet1` (non-core / likely leftover)

This confirms v1 evolved into a hybrid state: original analytics + later USD-related additions.

---

## 3) Logical workflow of v1 (conceptual)

## Stage A — Universe + source registry
- Maintain ticker universe and company mapping.
- Track source status/quality per ticker.

## Stage B — Daily prices ingestion
- Pull daily historical prices for each ticker.
- Store a unified time-series table.

## Stage C — Horizon returns construction
For each ticker and each horizon (5D/10D/15D/1M/3M/6M/12M/18M/24M/30M/3Y):
- Compute equity return (`EqRet_h`).
- Compute benchmark gold return (`GoldRet_h`).

## Stage D — Gold sensitivity layer
- Compute `GoldDelta_h = EqRet_h / GoldRet_h`.
- Aggregate/derive profile metrics (core delta, delta bucket, gamma proxy, stability, skew/regime tags).

## Stage E — Decision layer
- Convert profile metrics into ranking signals and decision labels.
- Present shortlists and avoid-lists.

## Stage F — UX surfaces
- Dashboard for quick ranking.
- Screener for conditional filtering.
- DeepDive for pairwise/benchmark comparison.

---

## 4) Key metrics and definitions to preserve in Python

### Core identities
- **Horizon equity return**: `EqRet_h = P_t / P_(t-h) - 1`
- **Horizon gold return**: `GoldRet_h = G_t / G_(t-h) - 1`
- **Gold sensitivity**: `GoldDelta_h = EqRet_h / GoldRet_h`

### Interpretation classes (product concept)
- Delta magnitude classes (e.g., low/moderate/high sensitivity)
- Convexity-like proxy (`Gamma_Proxy` concept)
- Stability score (consistency/robustness across horizons)
- Composite profile tag / decision score

### Important rule
These labels must be deterministic transforms of underlying numeric fields (no hidden/manual drift).

---

## 5) Non-code project mistakes that mattered (and must be avoided)

This is the most important section for the rebuild.

## 5.1 Currency normalization came too late
**Problem**
- Mixed listing currencies existed in the universe (US/UK/CA/AU/etc.).
- Sensitivity comparisons were built before a strict, explicit currency-normalization contract was locked.

**Impact**
- Cross-name comparability was unreliable.
- Some apparent sensitivity differences may have included FX effects, not equity-vs-gold behavior.

**Python rebuild rule**
- Define canonical return currency (USD) at architecture day zero.
- No derived analytics allowed unless upstream currency state is validated.

## 5.2 Time-horizon contract was not frozen early enough
**Problem**
- Multiple horizons were added/iterated while parts of the stack were still moving.

**Impact**
- Inconsistent dependencies and interpretation drift across screens.

**Python rebuild rule**
- Freeze a horizon set + naming contract in schema config before analytics code.
- Use a single `horizons.yaml` (or equivalent) consumed by every compute step.

## 5.3 Analytics/UI built before raw data model was fully governed
**Problem**
- High-level scoring/ranking/dashboarding advanced before robust raw data governance was complete.

**Impact**
- Rework cycles, trust issues in outputs, and fragile downstream logic.

**Python rebuild rule**
- Enforce sequence: raw foundation → validated features → scoring → UI.
- Hard gate promotion between layers.

## 5.4 Metric taxonomy drift (label/data mismatch)
**Problem**
- At times, displayed classes/labels diverged from underlying delta/profile calculations.

**Impact**
- Decision layer looked coherent but could conflict with base math.

**Python rebuild rule**
- Make all labels pure computed functions with versioned rules.
- Add assertion tests: label consistency must be 100%.

## 5.5 Model state mixing (legacy + patch layers)
**Problem**
- As improvements were added, old and new logic coexisted in partially overlapping forms.

**Impact**
- Hard to determine single source of truth.

**Python rebuild rule**
- Use explicit data contracts and versioned transformations.
- Deprecate old fields/tables formally, never implicitly.

---

## 6) Minimum raw-data foundation required before full rebuild

Use `Gold_RawData_Foundation_v9.xlsx` as guidance for the minimal pre-analytics stack.

### Required base entities (must exist and be validated)
1. **Company master / universe registry**
2. **Ticker-source registry** (status + provenance)
3. **Local-currency equity daily prices**
4. **Ticker-to-currency map**
5. **Daily FX to USD**
6. **Daily gold benchmark in USD**
7. **USD-converted equity daily prices**
8. **Corporate actions dataset (splits/dividends)**
9. **Data quality checks and error logs**
10. **Schema/data dictionary freeze**
11. **Refresh control + run status**
12. **(Optional but prepared) rates data for future factors/risk modeling**

### v9 reference tabs observed
- `Company_Master`
- `Ticker_Source_Registry`
- `Equity_Daily_Local`
- `FX_Daily_USD`
- `Gold_Daily_USD`
- `Ticker_Currency_Map`
- `Equity_Daily_USD`
- `Corporate_Actions`
- `Data_Quality_Checks`
- `Refresh_Errors_Log`
- `Raw_Data_Dictionary`
- `Schema_Freeze_v1`
- `Data_Fetch_Status`
- `Refresh_Control`
- plus support/meta tabs (calendar, model params, query/m-code, build state, rates)

### Foundation gate (must pass before feature engineering)
- Coverage thresholds met for equity, FX, gold.
- Currency map complete for active universe.
- No critical missing FX in evaluation windows.
- Corporate actions handling policy explicit.
- Reproducible refresh run with deterministic outputs.

---

## 7) Recommended Python architecture (practical)

## 7.1 Layers
1. **ingestion/**
   - fetch universe, prices, FX, gold, actions
2. **normalize/**
   - harmonize schema, date alignment, currency conversion
3. **features/**
   - returns, deltas, stability, convexity proxies
4. **model/**
   - scoring, classes, decision tags
5. **serve/**
   - CLI/API/UI outputs (tables, charts, reports)
6. **qa/**
   - data tests, metric consistency tests, regression snapshots

## 7.2 Data contracts
- Use typed schemas (Pydantic/Polars schema checks).
- Version every derived dataset.
- Persist both intermediate and final tables (Parquet preferred).

## 7.3 Deterministic pipeline
- One command builds from raw to ranked outputs.
- Every run writes metadata: run id, source timestamps, row counts, fail counts.

---

## 8) Proposed build sequence for Claude Code

1. **Implement raw foundation first** (equity local, FX USD, gold USD, currency map, quality logs).
2. **Implement USD equity conversion + return engine** with strict tests.
3. **Implement horizon analytics** (`EqRet_h`, `GoldRet_h`, `GoldDelta_h`) for frozen horizon list.
4. **Implement profile metrics** (stability, convexity proxy, regime tags).
5. **Implement ranking/scoring policy** as configurable rules.
6. **Implement outputs**:
   - dashboard table endpoint
   - screener endpoint
   - deep-dive endpoint
7. **Add acceptance suite** using known historical snapshots and invariants.

---

## 9) Acceptance criteria for the rebuilt product

The Python rebuild is “done” when:

1. Cross-currency comparability is correct by design (USD canonical path enforced).
2. Horizon metrics are reproducible and consistent across all product views.
3. Labels/classifications always match underlying numeric rules.
4. End-to-end refresh is deterministic and logged.
5. Ranking/deep-dive outputs are explainable from persisted intermediate tables.
6. Architecture supports adding the friend’s screening model later via explicit interface contracts.

---

## 10) Integration note for the separate friend model

We eventually want both tools to work together, but do this only after the core engine above is stable.

Recommended approach:
- Treat friend model as **external model module**.
- Define interface contract first:
  - required inputs,
  - output scores/signals,
  - confidence/coverage fields,
  - update cadence.
- Only then merge into combined ranking/decision surface.

This avoids contaminating core architecture with unverified assumptions.

---

## 11) Hard rules Claude should follow during rebuild

1. Do not implement analytics on mixed currencies without explicit normalization.
2. Do not add new horizons ad hoc; modify only through centralized config.
3. Do not compute composite scores before raw data QA gates pass.
4. Do not allow hidden/manual label overrides.
5. Keep every transformation testable, versioned, and auditable.

---

## 12) Summary for Claude (one paragraph)

Rebuild v1 as a USD-canonical, horizon-consistent, test-first analytics pipeline that reproduces the intent of dashboard/screener/deep-dive decision support, while fixing prior architecture mistakes: late currency normalization, moving horizon definitions, analytics before data governance, and label-metric drift. Use the v9 raw-data foundation pattern as the mandatory precondition layer, then implement deterministic feature/scoring services with strict invariants and explainable outputs.