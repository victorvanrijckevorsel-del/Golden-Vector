# Codex Full Briefing — Golden Vector + Screening Tool

## Document purpose

This is your complete context pack. It contains everything you need to understand, build, and review the Golden Vector project. Read this before touching any code.

Claude Code (the implementation agent) prepared this briefing. You (Codex) will be coding parts of this tool and reviewing Claude Code's work. This document gives you the same level of understanding Claude Code has.

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [Repository layout and reference files](#2-repository-layout-and-reference-files)
3. [Tool A — Golden Vector (gold sensitivity engine)](#3-tool-a--golden-vector-gold-sensitivity-engine)
4. [Tool B — Screening Tool (fundamental valuation screener)](#4-tool-b--screening-tool-fundamental-valuation-screener)
5. [Integration plan — how the two tools combine](#5-integration-plan--how-the-two-tools-combine)
6. [Confirmed architecture decisions](#6-confirmed-architecture-decisions)
7. [Build sequence](#7-build-sequence)
8. [Hard rules](#8-hard-rules)
9. [Collaboration workflow](#9-collaboration-workflow)

---

## 1. Project overview

Golden Vector is a Python-based decision engine for gold stock portfolio construction. It combines two complementary analytical tools:

| | **Tool A — Golden Vector** | **Tool B — Screening Tool** |
|---|---|---|
| **Core question** | "How sensitively does this stock move when gold moves?" | "Is this stock cheap relative to its earnings power at a given gold price?" |
| **Method** | Price-based: historical equity returns vs gold returns across time horizons | Fundamental: forward earnings model at an assumed gold price |
| **Primary inputs** | Market prices (equity + gold + FX) — all via API | Mix of API data (prices, FX, market cap) and manual data (AISC, production guidance) |
| **Time dimension** | Multi-horizon (5D through 3Y) | Point-in-time snapshot, but with sensitivity across gold price assumptions |
| **Origin** | Emanuel's Excel/VBA tool (`Gold_Tickers_Historical_Prices_Final_WORKING2_EDITED_v3.xlsm`) | Friend's Excel tool (`Gold_Mining_Screening_Updated_18Feb2026 (1).xlsx`) |

**Combined value proposition**: "Which gold stocks are fundamentally cheap AND actually move with gold?" — a stock must pass both filters to be a top candidate.

Both tools must work independently (each is useful on its own) and together (combined ranking surface).

---

## 2. Repository layout and reference files

### Current repo location
- **GitHub**: `victorvanrijckevorsel-del/Golden-Vector` (private)
- **Local**: `C:\Users\Emanuel\code\Golden-Vector`
- **Branch strategy**: work on `dev-vic`, merge to `main` at milestones (see CLAUDE.md for full workflow)

### Key files to read

| File | What it is | Read priority |
|------|-----------|---------------|
| `CLAUDE.md` | Behavioral rules for Claude Code. Also contains hard rules for the project, git workflow, and collaboration protocol. | **Must read** |
| `claude-python-rebuild-spec-gold-v1.md` | Full implementation spec for Tool A (Golden Vector). Architecture, lessons learned, build sequence, v1 sheet structure, acceptance criteria. | **Must read** |
| `codex-full-briefing.md` | This file. Complete context for both tools and integration. | **Must read** |
| `Gold_Tickers_Historical_Prices_Final_WORKING2_EDITED_v3.xlsm` | Original v1 Excel tool for Golden Vector (reference only — do not replicate Excel quirks) | Reference |
| `Gold_RawData_Foundation_v9.xlsx` | Raw data foundation showing proper architecture pattern (reference for data layer design) | Reference |
| `Gold_Mining_Screening_Updated_18Feb2026 (1).xlsx` | Friend's screening tool (reference — fully analyzed below) | Reference |
| `main.py` | Empty entry point (placeholder) | — |
| `requirements.txt` | Current deps: yfinance, pandas, numpy, matplotlib, ta | — |

### Reference Excel file details

#### `Gold_RawData_Foundation_v9.xlsx` — tabs observed:
- `Company_Master` — universe registry
- `Ticker_Source_Registry` — status + provenance per ticker
- `Equity_Daily_Local` — local-currency daily prices
- `FX_Daily_USD` — daily FX rates to USD
- `Gold_Daily_USD` — daily gold benchmark prices
- `Ticker_Currency_Map` — ticker → listing currency
- `Equity_Daily_USD` — USD-converted equity prices
- `Corporate_Actions` — splits/dividends
- `Data_Quality_Checks` — QA gate
- `Refresh_Errors_Log` — error tracking
- `Raw_Data_Dictionary` — schema documentation
- `Schema_Freeze_v1` — frozen schema version
- `Data_Fetch_Status` — refresh run status
- `Refresh_Control` — pipeline control
- Plus support/meta tabs (calendar, model params, query/m-code, build state, rates)

#### `Gold_Tickers_Historical_Prices_Final_WORKING2_EDITED_v3.xlsm` — tabs observed:
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

---

## 3. Tool A — Golden Vector (gold sensitivity engine)

### What it does

For every gold mining stock in the universe, across multiple time horizons, it answers:
- How much does this stock move when gold moves? (sensitivity / delta)
- Is that sensitivity stable or noisy? (stability score)
- Does sensitivity increase when gold moves more? (convexity proxy / gamma)
- How does this stock's profile compare to others? (ranking)

### Core math

```
Equity return:      EqRet_h  = P_t / P_(t-h) - 1
Gold return:        GoldRet_h = G_t / G_(t-h) - 1
Gold sensitivity:   GoldDelta_h = EqRet_h / GoldRet_h
```

All returns computed in USD (canonical currency). No analytics permitted on mixed-currency data.

### Horizons (frozen set)

```
5D / 10D / 15D / 1M / 3M / 6M / 12M / 18M / 24M / 30M / 3Y
```

These are defined in a centralized config (e.g., `horizons.yaml`). No ad-hoc additions. Every compute step reads from this single source.

### Logical pipeline (6 stages)

**Stage A — Universe + source registry**
- Maintain ticker universe and company mapping
- Track source status/quality per ticker

**Stage B — Daily prices ingestion**
- Pull daily historical prices for each ticker via yfinance
- Pull daily FX rates (to USD) for each listing currency
- Pull daily gold benchmark price (USD)
- Store unified time-series tables

**Stage C — Horizon returns construction**
For each ticker × each horizon:
- Compute `EqRet_h` (equity return over horizon, in USD)
- Compute `GoldRet_h` (gold return over same horizon)

**Stage D — Gold sensitivity layer**
- Compute `GoldDelta_h = EqRet_h / GoldRet_h`
- Handle edge cases: near-zero gold returns, missing data windows
- Aggregate/derive profile metrics:
  - Core delta (central tendency of GoldDelta across horizons)
  - Delta bucket (low / moderate / high sensitivity)
  - Gamma proxy (convexity-like behavior — does delta increase when gold moves more?)
  - Stability score (consistency/robustness of delta across horizons)
  - Skew/regime tags

**Stage E — Decision layer**
- Convert profile metrics into ranking signals and decision labels
- All labels must be deterministic transforms of numeric fields (no hidden overrides)
- Present shortlists and avoid-lists

**Stage F — UX surfaces**
- **Dashboard**: quick universe-level ranking table
- **Screener**: conditional filtering by delta, stability, regime, etc.
- **Deep-dive**: single-name analysis with comparator and horizon-aware snapshots

### Profile metrics (to be computed)

| Metric | Description |
|--------|-------------|
| Core Delta | Central tendency of GoldDelta across horizons |
| Delta Bucket | Classification: low / moderate / high sensitivity |
| Gamma Proxy | Does delta increase disproportionately when gold moves more? |
| Stability Score | How consistent is delta across horizons? (low variance = stable) |
| Regime Tag | Behavioral classification derived from numeric profile |
| Composite Score | Weighted combination of above (configurable weights) |

### v1 mistakes that must not be repeated

1. **Currency normalization came too late** — sensitivity comparisons were built before strict USD conversion. Some apparent differences included FX effects, not equity-vs-gold behavior. **Fix**: USD canonical path enforced at architecture day zero. No derived analytics unless upstream currency state is validated.

2. **Horizon contract not frozen early enough** — horizons were added/iterated while downstream code was still moving. **Fix**: freeze horizon set in config before any analytics code. Single `horizons.yaml` consumed everywhere.

3. **Analytics/UI built before data governance** — scoring/ranking advanced before raw data was robust. **Fix**: enforce build sequence with hard gates between layers. Raw foundation must pass QA before feature engineering starts.

4. **Label/metric drift** — displayed labels diverged from underlying calculations. **Fix**: all labels are pure computed functions with versioned rules. Assertion tests enforce 100% label consistency.

5. **Model state mixing** — old and new logic coexisted. **Fix**: explicit data contracts, versioned transformations, formal deprecation.

---

## 4. Tool B — Screening Tool (fundamental valuation screener)

### What it does

For every gold mining stock, at a given assumed gold price, it answers:
- Can this company mine profitably? (cost/margin filter)
- What would it earn at this gold price? (forward earnings model)
- Is the stock cheap relative to peers? (valuation multiples)
- What's the upside if it re-rates to fair value? (target prices)

### Data inputs

#### API-sourced (automate in Python rebuild):
- Share price (local currency)
- FX rate to USD
- Market cap (USD)
- Shares outstanding
- Gold price (for current/live comparisons)
- LTM financial data where available (EBITDA, Net Income)

#### Manual input (must remain manual — mining-specific, not in standard APIs):
- Production guidance (oz) — from company press releases
- AISC ($/oz) — All-In Sustaining Cost, from company guidance
- Cash operating costs ($/oz)
- Royalty rate (%)
- Sustaining capex ($m)
- D&A ($m)
- Interest expense ($m)
- Tax rate (%)
- Reserve life (years)
- Net debt ($m)
- Jurisdiction tier (1/2/3)

The friend's tool currently has **61 tickers** with all fields hand-entered. Each field was manually sourced — there are dedicated verification sheets for AISC and production data with source URLs.

### Layer 1 — Robust Screen (pass/fail quality filter)

Takes a gold price assumption (currently $4,000/oz) and applies 5 binary gates:

| # | Check | Formula | Threshold (configurable) |
|---|-------|---------|--------------------------|
| 1 | AISC Flag | `AISC < threshold` | Default: $1,850/oz |
| 2 | Margin Flag | `(GoldPrice - AISC) / GoldPrice >= threshold` | Default: 50% |
| 3 | FCF Flag | `SustainableFCF / MarketCap >= threshold` | Default: 15% |
| 4 | Reserve Life | `ReserveLife >= threshold` | Default: 6 years |
| 5 | Leverage | `NetDebt / EBITDA <= threshold` | Default: 2.5x |

Where:
```
CashMargin = GoldPrice - AISC
SustainableFCF = (CashMargin × Production - SustainingCapex) 
FCFYield = SustainableFCF / MarketCap
```

A stock must pass ALL 5 gates to proceed. This is a survival/quality filter — "can this company actually make money mining gold at this price?"

### Layer 2 — Earnings Model (valuation engine)

For each stock, builds a forward earnings model:

```
Forward Revenue     = GoldPrice × ProductionGuidance
Forward EBITDA      = IF CashCosts > 0:
                        (GoldPrice - CashCosts) × Production - Revenue × RoyaltyRate%
                      ELSE:
                        (GoldPrice - AISC × 0.7) × Production - Revenue × RoyaltyRate%
Forward Net Income  = (EBITDA - D&A - Interest) × (1 - TaxRate)
Forward EPS         = NetIncome / Shares
Forward P/E         = SharePrice(USD) / EPS
EV/EBITDA           = (MarketCap + NetDebt) / EBITDA
Forward FCF         = SustainableFCF (from Layer 1)
FCF Yield           = FCF / MarketCap
```

### Peer benchmarks (size-based, configurable)

Companies are bucketed by market cap:

| Size | Market Cap Range | P/E 2026 | P/E 2011 Peak | EV/EBITDA 2026 | EV/EBITDA 2011 | FCF Yield 2026 | FCF Yield 2011 |
|------|-----------------|----------|---------------|----------------|----------------|----------------|----------------|
| Large | >$15B | 16x | 28.5x | 8x | 14x | 5% | 2% |
| Mid | $2-15B | 13x | 23x | 6.5x | 12x | 7.5% | 3.5% |
| Small | $500M-2B | 11.5x | 20x | 5.5x | 10x | 10% | 4.5% |
| Micro | <$500M | 10x | 18x | 4.5x | 9x | 12% | 5% |

**Important**: These benchmarks are currently referenced from "Operating Manual v2, Appendix B". Their exact source is not yet confirmed. They must be stored as configurable data, not hardcoded. The tool should support other historical reference periods beyond 2011.

### Jurisdiction risk discounts (configurable)

| Tier | Countries | Default Discount |
|------|-----------|-----------------|
| 1 | USA, Canada, Australia | 0% |
| 2 | Mexico, Peru, Brazil, South Africa | 15% |
| 3 | Mali, DRC, PNG, etc. | 30% |

Applied to peer multiples: `AdjustedPeerPE = PeerPE × (1 - TierDiscount)`

### Target price scenarios (6 methods)

For each stock, calculate "what should the price be if it traded at...":

| # | Scenario | Formula |
|---|----------|---------|
| 1 | Peer P/E (2026, size-adjusted, tier-discounted) | `AdjustedPeerPE × ForwardEPS` |
| 2 | 2011 Peak P/E (size-adjusted, tier-discounted) | `Adjusted2011PE × ForwardEPS` |
| 3 | Peer FCF Yield (2026, size-adjusted) | `SharePrice × (ActualFCFYield / PeerFCFYield)` |
| 4 | 2011 Peak FCF Yield (size-adjusted) | `SharePrice × (ActualFCFYield / 2011FCFYield)` |
| 5 | Peer EV/EBITDA (2026, size-adjusted, tier-discounted) | `(EBITDA × PeerEVEB × (1 - TierDiscount) - NetDebt) / Shares` |
| 6 | 2011 Peak EV/EBITDA (size-adjusted, tier-discounted) | `(EBITDA × 2011EVEB × (1 - TierDiscount) - NetDebt) / Shares` |

Each target price produces an upside percentage: `(TargetPrice - CurrentPrice) / CurrentPrice`

### Verdict logic

```
IF ForwardPE < 8x AND Layer1 = PASS  → ★ STRONG CANDIDATE
IF ForwardPE < 10x                    → ◆ WATCHLIST
ELSE                                  → ○ SCREEN OUT
```

The P/E threshold (8x) is configurable via `Summary & Parameters` sheet.

### Supporting data in the friend's tool

| Sheet | Purpose |
|-------|---------|
| **AISC Verification** | 61 rows, each with: source date, verified AISC (USD), status (verified/estimated), notes, source URL. This is hand-curated due diligence. |
| **Production Verification** | 61 companies, validated 2026 production guidance with source URLs. Total universe production: ~39.9M oz. |
| **Next Reporting Date** | Per-company upcoming financial and operational reporting dates with explicit sources. Tracks: next financial (explicit + placeholder), same period last year, next production update. |
| **Price Comparisons** | Live price vs 3 target prices (PE / FCF / EV/EBITDA) with gap percentages. Also tracks historical prices at specific dates since inception (Jan 23, 2026 onward). |
| **Top Performers** | Sorted/filtered view of Layer 2 results — same columns, just reordered by attractiveness. |
| **Live Prices** | Links to Google Sheets for live price feeds. Contains: ticker, GF ticker format, live price, currency, FX, USD price, shares, live market cap. |

---

## 5. Integration plan — how the two tools combine

### Philosophy

Both tools work independently. Each produces its own ranking/verdict. The combined surface merges them:

```
Golden Vector says:  "This stock MOVES with gold" (behavior filter)
Screening Tool says: "This stock is CHEAP"         (value filter)
Combined:            "Cheap AND moves with gold"   = best candidates
```

### Shared universe

Both tools operate on the **same ticker universe**. The universe is maintained in one place (a config/registry). Adding a new ticker makes it available to both tools. The universe should be easily extensible — adding a ticker should be a simple config change, not a code change.

### Current universe size

61 tickers across multiple exchanges and currencies:
- Exchanges: TSX, NYSE, ASX, LSE/AIM, JSE, and others
- Currencies: USD, CAD, GBP, AUD, ZAR, and others
- Company types: majors (Newmont, Barrick), mid-tiers, juniors, royalty/streaming companies

### Integration interface contract

The Screening Tool should be treated as an **external model module** that plugs into the Golden Vector architecture. Define the interface before merging:

| Field | Description |
|-------|-------------|
| `ticker` | Shared key — must match universe registry |
| `layer1_pass` | Boolean — passes all 5 fundamental gates |
| `screening_verdict` | Enum: STRONG_CANDIDATE / WATCHLIST / SCREEN_OUT |
| `forward_pe` | Forward P/E at assumed gold price |
| `ev_ebitda` | EV/EBITDA ratio |
| `fcf_yield` | Forward FCF yield |
| `target_prices` | Dict of 6 scenario target prices + upside % |
| `gold_price_assumption` | The gold price used for this run |
| `confidence` | Data quality indicator (verified vs estimated inputs) |

### Combined ranking surface (future)

Once both engines are stable, the combined view could show:

| Column | Source |
|--------|--------|
| Ticker, Company | Universe registry |
| Gold Delta (core) | Golden Vector |
| Stability Score | Golden Vector |
| GV Rank | Golden Vector |
| Forward P/E | Screening Tool |
| FCF Yield | Screening Tool |
| Screening Verdict | Screening Tool |
| Target Upside (best scenario) | Screening Tool |
| **Combined Score** | Weighted blend of both |
| **Combined Verdict** | Both filters applied |

### Sensitivity analysis

The Screening Tool should support running at **multiple gold price assumptions** in a single pass (e.g., $3,000 / $3,500 / $4,000 / $4,500 / $5,000) and showing how rankings change across price scenarios. This answers: "At what gold price does this stock become attractive / unattractive?"

---

## 6. Confirmed architecture decisions

These were discussed and confirmed with Emanuel:

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Canonical currency | USD | All analytics in USD. FX conversion happens before any math. |
| Data format | Parquet for intermediate storage | Fast, typed, versioned, compact |
| Config format | YAML for horizons, universe, parameters | Human-readable, versionable |
| Schema validation | Pydantic for data contracts | Typed, testable, self-documenting |
| Testing | pytest | Standard Python testing |
| API data source | yfinance | Already in requirements.txt. Covers: equity prices, FX, gold, market cap, shares |
| Manual data | YAML/CSV input files | For AISC, production guidance, and other mining-specific data not available via API |
| Historical periods | Configurable | Not limited to 2011 — should support any reference period |
| Peer benchmarks | Configurable data tables | Not hardcoded — stored in config, easily updatable |
| Jurisdiction discounts | Configurable | Tier definitions and discount percentages adjustable |
| Universe management | Single shared registry | One config defines the universe for both tools. Easy to add tickers. |
| Build priority | Golden Vector first | Core sensitivity engine built and tested before screening tool integration |

### Recommended Python architecture

```
golden_vector/
├── config/
│   ├── horizons.yaml          # Frozen horizon definitions
│   ├── universe.yaml          # Ticker universe + metadata (currency, exchange, jurisdiction tier)
│   ├── screening_params.yaml  # Screening thresholds, peer benchmarks, jurisdiction discounts
│   └── scoring.yaml           # Ranking weights and classification rules
├── ingestion/
│   ├── fetcher.py             # Pull equity prices, FX, gold via yfinance
│   └── quality.py             # Coverage checks, gap detection, error logging
├── normalize/
│   ├── fx.py                  # Currency conversion engine
│   ├── align.py               # Date alignment across time series
│   └── validate.py            # Schema validation (Pydantic contracts)
├── features/
│   ├── returns.py             # EqRet_h, GoldRet_h computation
│   ├── delta.py               # GoldDelta_h computation
│   ├── stability.py           # Stability score, consistency metrics
│   └── gamma.py               # Convexity proxy / gamma-like metrics
├── screening/
│   ├── layer1.py              # Robust screen (5 pass/fail gates)
│   ├── layer2.py              # Earnings model + valuation multiples
│   ├── targets.py             # 6 target price scenarios
│   ├── verdicts.py            # Screening verdict logic
│   └── manual_data.py         # Loader for manual inputs (AISC, production, etc.)
├── model/
│   ├── scoring.py             # Golden Vector composite scoring
│   ├── labels.py              # Deterministic label generation
│   └── ranking.py             # Combined ranking engine
├── serve/
│   ├── dashboard.py           # Ranked table output
│   ├── screener.py            # Filtered view output
│   ├── deepdive.py            # Single-name analysis
│   └── sensitivity.py         # Multi-gold-price sensitivity analysis
├── qa/
│   ├── data_tests.py          # Raw data quality tests
│   ├── metric_tests.py        # Metric consistency / label assertion tests
│   └── snapshots.py           # Historical regression snapshots
├── data/
│   ├── raw/                   # Raw Parquet files (prices, FX, gold)
│   ├── intermediate/          # USD-converted, returns, deltas
│   ├── output/                # Final ranked tables
│   └── manual/                # Manual input files (AISC, production CSVs)
├── main.py                    # Entry point — one command builds everything
└── requirements.txt
```

### Data contracts (Pydantic examples)

Every layer boundary should have a typed contract. Examples:

```python
# Raw price record
class EquityPrice:
    ticker: str
    date: date
    close_local: float
    currency: str
    source: str

# USD-converted price
class EquityPriceUSD:
    ticker: str
    date: date
    close_usd: float
    fx_rate: float
    fx_pair: str

# Horizon return
class HorizonReturn:
    ticker: str
    date: date
    horizon: str        # Must be from frozen horizon set
    equity_return: float
    gold_return: float
    gold_delta: float   # equity_return / gold_return

# Screening input (manual + API merged)
class ScreeningInput:
    ticker: str
    company: str
    exchange: str
    currency: str
    share_price_local: float
    fx_to_usd: float
    market_cap_usd: float
    shares_m: float
    production_guidance_oz: float    # Manual
    aisc_usd_oz: float              # Manual
    cash_costs_usd_oz: float | None # Manual
    royalty_rate_pct: float          # Manual
    sustaining_capex_m: float       # Manual
    da_m: float                     # Manual
    interest_m: float               # Manual
    tax_rate_pct: float             # Manual
    reserve_life_yrs: float         # Manual
    net_debt_m: float               # Could be API or manual
    ebitda_ltm_m: float             # Could be API or manual
    jurisdiction_tier: int           # Manual (1/2/3)
```

---

## 7. Build sequence

### Phase 1: Raw foundation (Golden Vector)
- Universe registry (YAML config with ticker, exchange, currency, jurisdiction)
- yfinance fetcher for equity prices, FX rates, gold price
- Parquet persistence for all raw time series
- Data quality gates: coverage thresholds, gap detection, currency map completeness
- **Gate**: no downstream code runs until this passes

### Phase 2: USD conversion + return engine
- FX conversion of all local-currency prices to USD
- `EqRet_h` and `GoldRet_h` computation for every ticker × horizon
- Strict tests: known price → known return, currency round-trip checks

### Phase 3: Horizon analytics
- `GoldDelta_h` computation for every ticker × horizon
- Edge case handling (near-zero gold returns, missing windows)

### Phase 4: Profile metrics
- Stability score (delta consistency across horizons)
- Convexity proxy (gamma-like behavior)
- Regime tags (deterministic, from numeric fields only)

### Phase 5: Ranking & scoring (Golden Vector)
- Configurable scoring policy (weights, thresholds in YAML)
- Decision labels as pure functions of numeric fields
- Assertion tests: labels always match underlying math

### Phase 6: Screening Tool integration
- Manual data input layer (YAML/CSV for AISC, production, etc.)
- Layer 1 robust screen (5 gates)
- Layer 2 earnings model + valuation multiples
- 6 target price scenarios
- Sensitivity analysis (run at multiple gold prices)
- Screening verdicts

### Phase 7: Combined surface
- Merged ranking from both engines
- Combined dashboard, screener, deep-dive
- Sensitivity analysis across gold prices showing both dimensions

### Phase 8: Output surfaces
- Dashboard (ranked table)
- Screener (filtered view)
- Deep-dive (single-name vs benchmark)
- Sensitivity report (multi-gold-price grid)

### Phase 9: Acceptance suite
- Historical snapshot tests against known values
- End-to-end deterministic run validation
- Label consistency assertions

---

## 8. Hard rules

These are non-negotiable. Violating any of these is a bug.

### Data integrity
1. **No analytics on mixed currencies** — every equity price must be USD-converted before any return/delta computation
2. **No ad-hoc horizons** — horizons are defined in `horizons.yaml` and consumed by every compute step. Adding a horizon means updating the config, not the code
3. **No composite scores before QA gates pass** — raw data foundation must be validated before feature engineering starts
4. **No hidden label overrides** — all labels are deterministic transforms of numeric fields. If a label says "STRONG CANDIDATE", you must be able to trace it back to exact numeric thresholds
5. **Every transformation must be testable, versioned, and auditable** — persist intermediate tables, log run metadata

### Build discipline
6. **Enforce build sequence** — raw foundation → validated features → scoring → UI. Hard gate promotion between layers
7. **Deterministic pipeline** — one command builds from raw data to ranked outputs. Every run writes metadata: run ID, source timestamps, row counts, fail counts
8. **No feature commits to `main`** — always work on `dev-vic`, merge via the workflow in CLAUDE.md

### Screening Tool specific
9. **Manual data fields stay manual** — do not invent values for AISC, production guidance, or other mining-specific fields. If data is missing, flag it, don't fill it
10. **Peer benchmarks are data, not code** — store in config files, not hardcoded in formulas
11. **Gold price assumption is explicit** — always logged, always traceable. Never use an implicit/default gold price without the user knowing

---

## 9. Collaboration workflow

### Roles
- **Claude Code** = implementation agent (builds on `dev-vic`)
- **Codex** = implementation agent and review agent (builds features, writes code, and reviews inside `reviews/codex/`)

### Workflow loop
1. Either Claude Code or Codex builds features or fixes on `dev-vic`
2. The implementing agent writes a milestone handoff in `reviews/codex/milestones/`
3. The other agent may audit and write a review file in `reviews/codex/`
4. Approved findings are fixed by whichever agent is carrying the next implementation step

### Parallel review rules
- Claude Code self-reviews independently BEFORE reading Codex's review
- Self-review is READ ONLY — no code changes while Codex is reviewing
- After both reviews done, merge into comparison table, then fix everything
- Only exception: code literally crashes the app and blocks the user

### About Emanuel (the user)
- Beginner founder. Explain decisions in plain English, avoid jargon.
- Learns fast but prefers understanding WHY before implementation.
- Values low-interruption execution — do the work, show results, don't over-ask.
- Expects structured output (tables, summaries, test results).
- Git user: Victor Van Rijckevorsel.

---

## Appendix A: Friend's tool — complete formula reference

### Layer 1 formulas (for one row, e.g., row 5)

```
Company        = VLOOKUP(ticker, ScreeningData, col2)
MarketCap      = VLOOKUP(ticker, ScreeningData, col7)
Production     = VLOOKUP(ticker, ScreeningData, col9)
AISC           = VLOOKUP(ticker, ScreeningData, col10)
AISC_Flag      = IF(AISC <= threshold, "PASS", "FAIL")
CashMargin     = GoldPrice - AISC
MarginPct      = CashMargin / GoldPrice
Margin_Flag    = IF(MarginPct >= threshold, "PASS", "FAIL")
SustFCF        = (CashMargin × Production - SustainingCapex) / 1e6
FCFYield       = SustFCF / MarketCap
FCF_Flag       = IF(FCFYield >= threshold, "PASS", "FAIL")
ReserveLife    = VLOOKUP(ticker, ScreeningData, col17)
RL_Flag        = IF(ReserveLife >= threshold, "PASS", "FAIL")
Leverage       = IF(EBITDA > 0, NetDebt / EBITDA, 0)
Leverage_Flag  = IF(Leverage <= threshold, "PASS", "FAIL")
PASS_ALL       = IF(ALL flags = "PASS", "PASS", "FAIL")
```

### Layer 2 formulas (for one row)

```
SizeCategory = IF(MktCap > 15000, "Large", IF(MktCap > 2000, "Mid", IF(MktCap > 500, "Small", "Micro")))
SharePriceUSD = LocalPrice × FXtoUSD
FwdRevenue = GoldPrice × Production / 1e6
FwdEBITDA  = IF(CashCosts > 0,
               (GoldPrice - CashCosts) × Production / 1e6 - Revenue × RoyaltyRate,
               (GoldPrice - AISC × 0.7) × Production / 1e6 - Revenue × RoyaltyRate)
FwdNetIncome = (EBITDA - DA - Interest) × (1 - TaxRate)
FwdEPS = NetIncome / Shares
FwdPE = SharePriceUSD / EPS
CurrentPE_LTM = IF(NetIncome_LTM > 0, MktCap / NetIncome_LTM, "")
PE_Flag = IF(FwdPE < PE_threshold, "PASS", "FAIL")
EV_EBITDA = (MktCap + NetDebt) / EBITDA

PeerPE = lookup by SizeCategory from benchmark table
TierDiscount = lookup by JurisdictionTier from discount table
AdjustedPeerPE = PeerPE × (1 - TierDiscount)
vsPeers = (FwdPE - AdjustedPeerPE) / AdjustedPeerPE

Peak2011PE = lookup by SizeCategory from benchmark table
AdjustedPeak2011PE = Peak2011PE × (1 - TierDiscount)
vs2011 = (FwdPE - AdjustedPeak2011PE) / AdjustedPeak2011PE

Verdict = IF(FwdPE < 8 AND Layer1 = PASS, "STRONG CANDIDATE",
          IF(FwdPE < 10, "WATCHLIST", "SCREEN OUT"))

TargetPrice_PeerPE = AdjustedPeerPE × EPS
Upside_PeerPE = (TargetPrice - CurrentPrice) / CurrentPrice

TargetPrice_2011PE = AdjustedPeak2011PE × EPS
Upside_2011PE = (TargetPrice - CurrentPrice) / CurrentPrice

FwdFCF = SustFCF (from Layer 1)
FwdFCFYield = FCF / MktCap
PeerFCFYield = lookup by SizeCategory
TargetPrice_FCF = SharePrice × (ActualFCFYield / PeerFCFYield)
Upside_FCF = (TargetPrice - CurrentPrice) / CurrentPrice

TargetPrice_FCF2011 = SharePrice × (ActualFCFYield / FCFYield2011)

PeerEVEB = lookup by SizeCategory
TargetPrice_EVEB = (EBITDA × PeerEVEB × (1 - TierDiscount) - NetDebt) / Shares
Upside_EVEB = (TargetPrice - CurrentPrice) / CurrentPrice

TargetPrice_EVEB2011 = (EBITDA × EVEB2011 × (1 - TierDiscount) - NetDebt) / Shares
```

---

## Appendix B: Current universe snapshot (61 tickers from friend's tool)

Tickers observed in Screening Data sheet (as of Feb 2026):

```
AAUC.TO, AAZ.L, AAU.L, AEM, AGI, ARMN, ASE.V, AU, AYA.TO,
BTG, BVN, CDE, CG, DPM.TO, EDV.L, EGO, ELD.TO, FRES.L,
FNV, GAU, GOLD, GFI, HGM.L, HMY, IAG, IMG.TO, JAG.TO,
K.TO, KGC, KNT.TO, LUG.TO, MAG, MKO.V, MMG.TO, MTL.L,
MUX, NGD, NEM, NUAG.V, OGC.TO, OR, PAAS, PAF.L, POG.L,
RRS.L, RSG.AX, SBSW, SBR.V, SRB.L, SSL.TO, TGZ.TO, THX.L,
TXG.TO, WAF.AX, WDO.TO, WPM, WGOLD.ST, TGR.AX
```

(Exact count and composition may vary — always read from the config as source of truth)

---

## End of briefing

Start with `CLAUDE.md`, then `claude-python-rebuild-spec-gold-v1.md`, then this file. Between the three documents you have full context. If something is ambiguous, flag it — don't invent behavior.
