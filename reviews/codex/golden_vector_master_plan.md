# Golden Vector Master Plan

> Note: the runtime model and Combined product direction in this document are partially superseded by [product_runtime_redesign_plan.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/product_runtime_redesign_plan.md). Use that redesign plan as the current source of truth for:
> - explicit `update-data` refresh behavior
> - local-first Tool A / Tool B usage
> - de-scoping the old Combined backend in favor of a later side-by-side compare view

## 1. Title and Intent

This is the north-star implementation plan for Golden Vector. The product goal is simple: identify gold stocks that both move with gold and look fundamentally attractive, using a Python engine that is auditable, deterministic, and safe against mixed-currency mistakes.

Non-negotiable rules:

- No analytics on mixed currencies.
- No ad-hoc horizons in official scores.
- No composite scores before QA gates pass.
- No hidden or manual label overrides.
- Every transformation must be testable, versioned, and auditable.

## 2. Product Structure

| Product mode | Purpose | Inputs | Outputs |
| --- | --- | --- | --- |
| Tool A: Golden Vector | Measure gold sensitivity and behavior | Equity prices, FX, gold | Delta, stability, gamma proxy, Tool A score, Tool A rank |
| Tool B: Screening Tool | Measure valuation and robustness at a chosen gold price | API data plus manual mining inputs | Layer 1 result, valuation metrics, target prices, Tool B verdict |
| Combined View | Find names that pass both engines | Published Tool A output + published Tool B output | Combined score, combined verdict, merged dashboard |

Rules:

- Tool A must run on its own.
- Tool B must run on its own.
- Combined View consumes published outputs; it must not mix internal logic across the two tools.
- V1 is engine-first: CLI orchestration, Parquet outputs, CSV exports, QA summaries, and deep-dive reports. A richer web UI is planned later, not required for v1.

## 3. End-State Architecture

| Layer | Responsibilities |
| --- | --- |
| Shared backbone | Config loading, universe registry, raw ingestion, shared market snapshots, QA, logging, run metadata, Parquet persistence |
| Tool A layer | USD conversion, date alignment, returns, gold delta, stability, gamma proxy, labels, ranking |
| Tool B layer | Manual-data loading, shared market snapshot consumption, Layer 1 robust screen, Layer 2 earnings model, target prices, verdicts |
| Combined layer | Join Tool A and Tool B outputs, compute combined score and verdict, expose partial coverage |
| Serve layer | Dashboard tables, screener tables, deep-dive tables, horizon comparison outputs, sensitivity outputs, QA summaries |

Tool B market-data policy:

- Tool B does not own a separate market-data fetch path.
- Tool B consumes a shared market snapshot produced by the backbone.
- Phase 1 fetches the raw quote snapshot inputs needed for Tool B: latest share price, market cap, and shares outstanding.
- Phase 2 normalizes that snapshot into a canonical USD market snapshot using the same FX rules as Tool A.
- Tool B therefore depends on successful Phase 1 and Phase 2 for market data, plus manual screening inputs for mining-specific fields.

Runtime commands for the first implementation:

| Command | Purpose |
| --- | --- |
| `python main.py foundation` | Raw ingestion plus QA only |
| `python main.py tool-a` | Build Tool A from successful foundation data |
| `python main.py tool-b --gold-price 4000` | Build Tool B for one explicit gold-price scenario |
| `python main.py combined --gold-price 4000` | Orchestrate a compatible Tool A + Tool B run, then join them |
| `python main.py compare-horizons --ticker NEM --horizons 5D,10D,3M` | Exploratory comparison only; writes a comparison table to stdout and optionally CSV; must not affect official scores |

## 4. Repo Structure Target

```text
golden_vector/
  cli.py
  app/
  config/
  contracts/
  ingestion/
  normalize/
  features/
  screening/
  combined/
  serve/
  qa/
data/
  raw/
  intermediate/
  output/
  manual/
  runs/
reviews/
  codex/
  codex/milestones/
tests/
main.py
```

Placement rules:

- `golden_vector/` holds product code.
- `data/raw/` holds canonical raw market data.
- `data/intermediate/` holds normalized and feature-level tables.
- `data/output/` holds published Tool A, Tool B, and Combined outputs.
- `data/manual/` holds versioned manual mining inputs.
- `data/runs/<run_id>/` holds metadata, logs, QA summaries, and audit artifacts.
- `reviews/codex/` holds planning documents, reviews, and milestone handoffs.

## 5. Public Interfaces and Contracts

### Config files

| File | Purpose | Required contents |
| --- | --- | --- |
| `config/universe.yaml` | Shared universe registry | ticker, company, exchange, currency, jurisdiction tier, active flag, Tool A enabled, Tool B enabled |
| `config/horizons.yaml` | Horizon control | core horizons, custom-horizon validation rules, display order, grouping |
| `config/qa.yaml` | Data and pipeline gates | fetch rules, coverage thresholds, near-zero gold threshold, warn vs fail behavior |
| `config/scoring.yaml` | Tool A scoring policy | weights, eligibility rules, delta bucket thresholds, stability thresholds, gamma thresholds |
| `config/screening_params.yaml` | Tool B policy | gold-price scenarios, Layer 1 thresholds, peer benchmarks, jurisdiction discounts, verdict thresholds |

Config rules:

- All configs are version-controlled.
- Config hashes are stored in run metadata.
- Any business rule expected to change over time belongs in config, not only in code.

### Manual input files

Tool B manual datasets live in `data/manual/screening/`:

- `company_inputs.csv`
- `source_verification.csv`
- `reporting_calendar.csv`

Manual-data rules:

- Missing values remain missing.
- Missing required values produce `INCOMPLETE`, not invented numbers.
- Verification status must flow into Tool B confidence fields.

### Canonical dataset contracts

| Dataset | Key fields | Required fields beyond keys |
| --- | --- | --- |
| Raw equity daily | `ticker`, `date` | open/high/low/close local, adjusted close local, volume, currency, exchange, source, source symbol, fetched timestamp |
| Raw FX daily | `base_currency`, `date` | quote currency `USD`, standardized pair, `fx_rate_to_usd`, source, source symbol, fetched timestamp |
| Raw gold daily | `date` | gold symbol, close USD, adjusted close USD if supplied, source, source symbol, fetched timestamp |
| Market snapshot | `ticker`, `snapshot_date` | share price local, currency, FX to USD, share price USD, market cap USD, shares outstanding, source, source run id |
| USD equity daily | `ticker`, `date` | close USD, adjusted close USD, FX rate, FX pair, price basis, coverage flag, normalization run id |
| Horizon metrics long table | `ticker`, `as_of_date`, `horizon_id` | horizon mode, unit, value, start date, end date, equity return, gold return, gold delta, coverage flag, coverage reason, official scoring eligible, feature run id |
| Tool A output | `ticker`, `as_of_date` | core delta, delta bucket, gamma proxy, stability score, regime tag, Tool A score, Tool A rank, score eligible, coverage summary, source run id |
| Tool B output | `ticker`, `as_of_date`, `gold_price_assumption` | layer1 pass, layer1 fail reasons, forward PE, EV/EBITDA, FCF yield, screening verdict, confidence, best target price, best upside pct, source run id |
| Combined output | `ticker`, `as_of_date`, `gold_price_assumption` | Tool A score, screening verdict, combined score, combined verdict, join status, coverage summary, Tool A run id, Tool B run id, combined run id |

Contract rules:

- Raw tables preserve Yahoo output semantics.
- Tool A returns default to adjusted-close-based USD series.
- V1 corporate-actions handling is explicit: use Yahoo adjusted-close prices as the canonical return basis. No separate corporate-actions dataset is required for v1, and the chosen price basis is logged in run metadata.
- FX tables always standardize to "USD value of one local-currency unit".
- Tool B consumes the shared market snapshot rather than fetching its own prices independently.
- Combined output joins published Tool A and Tool B outputs only.
- If only one side is available, emit a row with `join_status = PARTIAL` and no combined score.

Tool B `as_of_date` semantics:

- For Tool B, `as_of_date` means the market snapshot date used for share price, FX rate, market cap, and shares outstanding.
- Manual mining inputs are treated as current reference inputs for that run and keep their own source dates in the verification tables.

### Tool B Formula Authority

The authoritative Tool B formulas are defined in `codex-full-briefing.md` Appendix A. That appendix is the source of truth for Layer 1, Layer 2, target-price scenarios, and verdict logic.

The implementation must follow these formula groups:

- Layer 1 gates:
  - `AISC_Flag = AISC <= aisc_threshold`
  - `CashMargin = GoldPriceAssumption - AISC`
  - `MarginPct = CashMargin / GoldPriceAssumption`
  - `Margin_Flag = MarginPct >= margin_threshold`
  - `SustainableFCF = (CashMargin * Production - SustainingCapex) / 1e6`
  - `FCFYield = SustainableFCF / MarketCap`
  - `FCF_Flag = FCFYield >= fcf_yield_threshold`
  - `ReserveLife_Flag = ReserveLife >= reserve_life_threshold`
  - `Leverage = NetDebt / EBITDA` only when `EBITDA > 0`; otherwise leverage fails
- Layer 2 metrics:
  - `ForwardRevenue = GoldPriceAssumption * Production / 1e6`
  - `ForwardEBITDA = (GoldPriceAssumption - CashCosts) * Production / 1e6 - ForwardRevenue * RoyaltyRate` when `CashCosts > 0`
  - otherwise use the source-model fallback `ForwardEBITDA = (GoldPriceAssumption - AISC * 0.7) * Production / 1e6 - ForwardRevenue * RoyaltyRate`
  - `ForwardNetIncome = (ForwardEBITDA - DA - Interest) * (1 - TaxRate)`
  - `ForwardEPS = ForwardNetIncome / Shares`
  - `ForwardPE = SharePriceUSD / ForwardEPS` only when `ForwardEPS > 0`
  - `EV_EBITDA = (MarketCap + NetDebt) / ForwardEBITDA` only when `ForwardEBITDA > 0`
- Target prices:
  - peer P/E
  - 2011 peak P/E
  - peer FCF yield
  - 2011 peak FCF yield
  - peer EV/EBITDA
  - 2011 peak EV/EBITDA
- Verdict rules:
  - `STRONG_CANDIDATE` requires `Layer1 = PASS` and positive `ForwardPE` below the strong-candidate threshold
  - `WATCHLIST` requires positive `ForwardPE` below the watchlist threshold
  - `SCREEN_OUT` is the default for complete but unattractive rows
  - `INCOMPLETE` is used when required inputs are missing or invalid

### Tool B Confidence Contract

`confidence` is an enum with exactly three values:

- `VERIFIED`: all required manual inputs are present and marked verified in the source-verification table
- `ESTIMATED`: all required manual inputs are present, but one or more are estimated or unverified
- `INCOMPLETE`: one or more required manual inputs are missing

## 6. Horizon System

There are exactly two horizon modes.

### Core horizons

Initial core set:

- `5D`
- `10D`
- `15D`
- `1M`
- `3M`
- `6M`
- `12M`
- `18M`
- `24M`
- `30M`
- `3Y`

Rules:

- Defined in `config/horizons.yaml`.
- Used for official Tool A scoring and ranking.
- Changing official horizons requires a config change and a versioned rerun.

### Custom horizons

Examples:

- `7D`
- `45D`
- `9M`
- `2Y`

Rules:

- Validated at runtime from a supported grammar: positive integer + `D`, `M`, or `Y`.
- Stored with `horizon_mode = custom`.
- Allowed in exploratory reports and comparisons.
- Excluded from official Tool A scores unless promoted into `config/horizons.yaml`.

### Interpretation rules

- Day horizons are trading-day based.
- Month and year horizons are calendar-offset based, then resolved to the nearest valid prior trading date.
- Every horizon record must store actual `start_date` and `end_date`.
- If a valid start date cannot be resolved, the row is emitted with `coverage_flag = FAIL`.
- Official scoring can use only `horizon_mode = core` rows with successful coverage.

## 7. Historical Data Strategy

Source policy:

- Data source: Yahoo Finance via `yfinance`
- Equities: fetch `period=max`
- FX: fetch `period=max`
- Gold: fetch `period=max`

Storage policy:

- First run is a full backfill.
- Raw and intermediate tables are cached locally in Parquet.
- V1 implementation uses a full re-fetch on each foundation run.
- Incremental refresh is deferred until the backfill path is stable.
- Run metadata records symbol, fetch depth, last available date, and config hash.

Overlap policy:

- Score calculations only use periods where equity, FX, and gold overlap.
- Older periods with incomplete overlap must be flagged as limited coverage.
- The system must never imply that all tickers are comparable across all periods.

Temporary defaults chosen now:

| Topic | Default |
| --- | --- |
| Gold benchmark symbol | `GC=F` |
| FX normalization target | USD per one local-currency unit |
| Return price basis | Adjusted close |
| Tool B scenario set | `3000, 3500, 4000, 4500, 5000` USD per oz |

Confirm later:

- Validate whether `GC=F` remains the best Yahoo symbol after live testing.
- Validate whether an additional fallback gold symbol is needed.

## 8. Full Phased Roadmap

| Phase | Goal | Deliverables | Dependencies | Done when |
| --- | --- | --- | --- | --- |
| 0 | App skeleton and standards | package structure, config loader, contracts, paths, logging, run metadata, baseline tests | none | commands boot, configs validate, run folders and metadata work |
| 1 | Raw ingestion and QA gate | Yahoo client, equity/FX/gold fetchers, raw quote snapshot fetcher, raw standardization, raw Parquet persistence, fetch status, QA summary | Phase 0 | one command writes raw tables and blocks downstream on fail |
| 2 | USD normalization and date alignment | FX resolver, inverse-pair handling, USD equity series, normalized market snapshot, currency-map checks, alignment logic | successful Phase 1 | each active Tool A ticker has a clear USD-normalization outcome and Tool B market snapshot fields are available in USD |
| 3 | Horizon engine and returns | horizon parser, core horizon loader, custom-horizon validator, return engine, long-format horizon table | successful Phase 2 | core and custom horizons compute correctly with actual start/end dates |
| 4 | Golden Vector metrics | gold delta, stability score, gamma proxy, regime tags, score-eligibility logic | successful Phase 3 | Tool A metrics exist in stable intermediate tables and remain testable |
| 5 | Tool A standalone outputs | dashboard, screener, deep-dive, horizon comparison outputs, Tool A ranking and labels | successful Phase 4 | Tool A runs independently and publishes usable outputs |
| 6 | Tool B standalone outputs | manual-data loader, Layer 1, Layer 2, scenario target prices, Tool B verdicts, confidence handling | successful Phase 1 and Phase 2 plus manual inputs | Tool B runs independently and incomplete manual data yields `INCOMPLETE` |
| 7 | Combined View | join contract, combined score logic, combined verdict logic, merged outputs | successful Tool A and Tool B outputs | combined outputs consume published outputs and expose partial coverage |
| 8 | Hardening and acceptance | regression snapshots, end-to-end fixtures, deterministic reruns, release docs | all prior phases | repeated runs on frozen inputs match expected outputs |

## 9. Failure Rules and QA Gates

Run statuses:

- `PASS`
- `WARN`
- `FAIL`

Rules:

- `FAIL` blocks dependent downstream stages.
- `WARN` is visible in logs and outputs but may continue.
- `PASS` is safe to consume.

Hard gates:

1. No downstream analytics if raw QA fails.
2. No USD normalization if the currency map is incomplete for active Tool A names.
3. No Tool A scoring before FX coverage and gold coverage checks pass.
4. No Tool B verdict if required manual inputs are missing.
5. No combined score unless Tool A and Tool B publish compatible outputs.

Mandatory QA checks:

- fetch success by symbol
- empty datasets
- duplicate rows
- invalid dates
- invalid currencies
- missing gold history
- missing FX history
- inverse FX handling
- missing start dates for horizon windows
- near-zero gold-return windows
- incomplete manual mining inputs
- partial joins in the combined layer

Special handling:

- Near-zero gold-return rows are emitted but flagged as not eligible for official delta scoring using a threshold in `config/qa.yaml`.
- Default near-zero threshold for v1: `abs(gold_return) < 0.005`, meaning 0.5 percent.
- Short-history tickers remain in the universe and stay visible in exploratory outputs, but may be ineligible for official scoring.

Tool B computational guardrails:

- If `shares_outstanding` is zero or missing, emit `INCOMPLETE` and skip EPS-based calculations.
- If `forward_net_income <= 0`, set `forward_pe = N/A`; the ticker cannot be `STRONG_CANDIDATE` or `WATCHLIST`.
- If `forward_ebitda <= 0`, set `ev_ebitda = N/A`; leverage fails and EV/EBITDA target prices are `N/A`.
- If `forward_fcf <= 0`, keep the numeric FCF yield if computable, but mark FCF-based target prices as `N/A`.
- If `cash_costs_usd_oz` is missing or non-positive, use the documented fallback `AISC * 0.7` from the source model.

## 10. Testing and Acceptance

### Unit tests

Must cover:

- config loading
- universe parsing
- FX normalization
- horizon parsing
- return calculation
- gold delta calculation
- stability score
- gamma proxy
- Layer 1 formulas
- Layer 2 formulas
- label generation
- score eligibility rules

### Integration tests

Must cover:

- foundation run from config to raw outputs
- normalization run from raw to USD outputs
- Tool A run from USD inputs to published Tool A outputs
- Tool B run from manual plus market inputs to published Tool B outputs
- combined run from standalone outputs to published combined outputs

### Regression and end-to-end tests

Must cover:

- fixed historical fixtures with expected returns
- fixed screening fixtures with expected valuation outputs
- stable labels for frozen inputs
- stable combined outputs for frozen inputs
- full small-universe pipeline
- deterministic reruns on frozen fixtures
- run metadata completeness

### Must-cover scenarios

- missing FX on required dates
- mixed-currency protection
- near-zero gold-return windows
- short-history equities
- custom horizons not affecting official scores
- Tool A working without Tool B
- Tool B working without Tool A
- combined join handling partial coverage cleanly

Acceptance criteria:

1. Tool A runs independently and is explainable from raw data to final score.
2. Tool B runs independently and is explainable from raw and manual inputs to final verdict.
3. Combined View joins published outputs without bypassing tool boundaries.
4. Official Tool A analytics are USD-normalized by design.
5. Official scoring uses only configured core horizons.
6. Custom horizons remain exploratory unless promoted into config.
7. Historical depth is fetched as deeply as Yahoo permits and coverage is exposed honestly.
8. Repeated runs on frozen inputs are deterministic.
9. Every label or verdict traces to exact numeric rules and persisted intermediates.
10. Every failure path is visible in logs and outputs.

## 11. Risks and Open Confirmations

### Assumptions chosen now

- Engine-first v1 is the correct delivery shape.
- The shared universe lives in `config/universe.yaml`.
- Market data comes from Yahoo Finance via `yfinance`.
- Canonical storage is Parquet.
- Tool A uses adjusted-close-based USD returns by default.
- Tool B manual inputs live in versioned CSV files.
- Tool B uses the shared normalized market snapshot from Phase 1 and Phase 2 rather than a separate snapshot fetch path.
- Combined runs orchestrate compatible Tool A and Tool B outputs under one umbrella run id.

### Confirm later, with defaults already chosen

| Topic | Temporary default | Why confirmation still matters |
| --- | --- | --- |
| Gold benchmark symbol | `GC=F` | Validate symbol quality and history depth on real runs |
| Peer benchmark source | configurable values in `config/screening_params.yaml` | Exact historical sourcing still needs confirmation |
| Return price basis | adjusted close | Corporate-actions behavior should be confirmed on real examples |
| Official score thresholds | conservative defaults in `config/scoring.yaml` | Final calibration should follow real data inspection |

### Known implementation risks

- Yahoo symbol coverage and history depth vary.
- Some equities and FX pairs will have patchy older histories.
- Manual mining inputs may be incomplete or slow to maintain.
- Full backfills may be heavy on the first run, so incremental refresh should follow quickly after the backfill works.

These risks are acceptable only if missing coverage stays visible and false confidence is blocked.

## 12. Milestone Plan

| Milestone | Target | Ship when | Likely git checkpoint |
| --- | --- | --- | --- |
| 1 | Foundation scaffold | commands boot, configs validate, run metadata and baseline tests pass | commit on `dev-vic` after plumbing tests pass |
| 2 | Raw market-data foundation | real run writes raw Parquet tables, fetch status, QA summaries | commit on `dev-vic` after small-universe raw run succeeds |
| 3 | USD normalization and horizon engine | USD series, core horizons, custom comparison horizons, return tests all pass | commit on `dev-vic` after return and horizon fixtures pass |
| 4 | Tool A usable | Tool A publishes dashboard, screener, deep-dive, and rank outputs | commit on `dev-vic` after Tool A acceptance tests pass |
| 5 | Tool B usable | Tool B publishes scenario-aware outputs and handles missing manual data cleanly | commit on `dev-vic` after manual-data and scenario tests pass |
| 6 | Combined View and hardening | combined outputs, full acceptance suite, deterministic reruns, operator docs | commit on `dev-vic` after full acceptance suite passes |

Milestone handoff convention:

- Every milestone produces a short handoff file under `reviews/codex/milestones/`.
- Each handoff states what was built, what was tested, known risks, and the exact next step.
- Claude and Codex both use those handoffs for review and continuation.
