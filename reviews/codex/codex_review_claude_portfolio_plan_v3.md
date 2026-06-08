# Codex Review - Portfolio Tool Plan v3

Grade: NEEDS CHANGES

This plan has the right product instinct: do not invent a separate portfolio model when the hedge-readiness work already computes many of the useful views, keep USD as the base currency, and make reconciliation/privacy explicit before showing real money. I would not build it yet. The current v3 still leans too hard on a hedge-readiness markdown/report engine that was not designed as a portfolio data API, and it under-specifies the currency/unit spine that will make or break a portfolio tab. The clean fix is not a large rewrite, but it is architectural: add a real persisted portfolio compute layer, plug it into the current model-state manifest, and let both the UI and any markdown report read from those artifacts.

## Severity-Ordered Findings

### P0 - The plan should not "re-present the existing hedge engine" as the portfolio engine

`golden_vector/hedge/portfolio_totals.py` is a useful scenario helper, but it is not a portfolio valuation layer. It accepts the old `Holding` model, assumes each holding is already a unique ticker, and computes notional as either `dollar_exposure` or `shares * current_stock_price` (`golden_vector/hedge/portfolio_totals.py:61`, `golden_vector/hedge/portfolio_totals.py:92`, `golden_vector/hedge/portfolio_totals.py:322`). It has no line-level broker model, no cash, no source price/FX fields, no reconciliation state, no privacy status, and no artifact-shaped output. The markdown report builder also rebuilds candidate grids and calls `compute_portfolio_totals` as part of report section construction (`golden_vector/hedge/report.py:260`, `golden_vector/hedge/report.py:293`, `golden_vector/hedge/report.py:340`). That is the wrong dependency direction for a portfolio tab. Concrete fix: create a small `golden_vector/portfolio/` package with pure compute/persistence/reader modules, and let `hedge/report.py` optionally reuse the persisted portfolio artifacts later. Do not have the workspace call report-section code or markdown code to build portfolio data.

Suggested package split:

- `golden_vector/portfolio/models.py`: broker line, cash line, grouped position, summary, reconciliation result.
- `golden_vector/portfolio/importer.py`: parse IBKR/manual files into broker lines, no analytics.
- `golden_vector/portfolio/valuation.py`: value one broker line using a shared price-unit/FX helper.
- `golden_vector/portfolio/pipeline.py`: read current manifest artifacts, compute portfolio lines/positions/summary/charts, write artifacts.
- `golden_vector/portfolio/reader.py`: checked reads through the model-state manifest for the UI.

### P0 - The pence fix is only half done; portfolio history will still be wrong

The plan correctly notices the LSE pence problem, and the market snapshot path now uses Yahoo's case-sensitive `GBp`/`GBX` style tags to divide minor-unit quotes by 100 (`golden_vector/ingestion/standardize.py:144`, `golden_vector/ingestion/standardize.py:218`). That case-sensitive keying is the right idea because `GBp` and `GBP` mean different units. But the history path still stores raw OHLC values as local major units without any minor-unit scaling, and USD normalization simply multiplies those local prices by FX (`golden_vector/normalize/prices_usd.py:72`, `golden_vector/normalize/prices_usd.py:91`). If the Portfolio tab ships a value-over-time chart while history remains in pence for LSE names, the chart can be 100x wrong even though the latest snapshot is fixed. Concrete fix: move the unit-scale logic into one shared valuation/price-unit helper and apply it to both `standardize_market_snapshot` and `standardize_equity_history` before any portfolio chart work. Persist `feed_currency`, `price_scale_factor`, and `minor_unit_adjusted` or equivalent fields so later audits can explain why a price was divided by 100.

### P0 - The artifact model is under-specified for real portfolio values

The repository now has a strong current-state pattern: immutable artifacts are resolved through `resolve_current_model_artifact_path` (`golden_vector/app/model_state.py:78`), the manifest publishes required artifacts (`golden_vector/app/model_state.py:41`), and alignment is centralized (`golden_vector/app/model_state.py:646`). Portfolio should plug into this. The plan's `portfolio_holdings` and `portfolio_summary` sketches are not enough because they mix raw broker lines, canonical grouped positions, cash, reconciliation, and chart data. Concrete fix: define separate artifacts before coding:

- `portfolio_lines`: one row per broker/security/cash line, with broker symbol, raw currency, raw quantity, raw market value, raw FX, source line id, and reconciliation fields.
- `portfolio_positions`: grouped canonical universe ticker rows used for analytics, with company/group id, notional USD, weight, Tool A/B/C/D joins, and data-quality gates.
- `portfolio_cash`: cash lines by currency, included in NAV but excluded from gold shock.
- `portfolio_summary`: NAV, invested value, cash, coverage, top weights, data status, reconciliation status.
- `portfolio_charts`: precomputed chart points for value, concentration, and correlation/relationship views.
- `benchmark_betas`: GDX/GDXJ beta artifact, separate from the universe.

Every artifact should carry `schema_version`, `parent_refresh_id`, `snapshot_refresh_run_id`, `source_export_hash`, and `portfolio_source_version`. The UI should not calculate these from raw holdings files.

### P1 - B2's notional formula is right only with a stricter typed boundary

The pinned formula `local_share_count * local_price * fx_rate_to_usd` is correct if `local_price` is already in the major local unit and `fx_rate_to_usd` is local-to-USD. The risk is that the current hedge helper already works in USD (`share_price_usd` fallback at `golden_vector/hedge/portfolio_totals.py:345`), while IBKR export values may be broker-local, broker-base, or already USD depending on the column. That is how double conversion happens. Concrete fix: do not pass raw floats around. Add typed valuation inputs with explicit fields: `quantity`, `price_local`, `price_currency`, `price_unit`, `fx_rate_to_usd`, `fx_source`, `market_value_local`, `market_value_usd`, and `price_source`. Stage 1 reconciliation should use IBKR's own market value and FX as the truth for the imported statement; Stage 2 should compare Golden Vector's live/snapshot price to the broker value as a drift label, not as a hard blocker.

### P1 - B3 benchmark beta should be a first-class benchmark artifact, not an add-on in proxy mapping

The plan is right that GDX/GDXJ should not pollute `config/universe.yaml`; `config/benchmarks.yaml` already contains active GDX/GDXJ benchmarks. But the current proxy fallback deliberately has no beta for benchmark rows (`proxy_down_beta=None` in `golden_vector/hedge/proxy_hedge.py:168`). If GDX is used for sizing or overshoot logic, "no beta" is not acceptable. Concrete fix: create a `benchmark_betas` pipeline step that reads benchmark price history and gold history, reuses the same structural weekly-series and estimator code as Tool A, and persists one row per benchmark. The schema should include `benchmark_ticker`, `as_of_date`, `window_start`, `window_end`, `n_weeks`, `down_beta_core`, `up_beta_core`, `confidence_label`, `method_version`, and `snapshot_refresh_run_id`. If the benchmark beta artifact is missing or low-confidence, the UI should disable GDX-sizing cards rather than quietly using a default.

### P1 - B5 needs stricter separation between import reconciliation and live-price drift

The two-stage reconciliation idea is correct, but it needs a harder boundary. Stage 1 should answer: "Did we parse the broker statement correctly?" using broker-provided positions, broker prices, broker FX, broker cash, and broker total NAV. If this fails, portfolio analytics should be disabled and the UI should show import issues. Stage 2 should answer: "How far has the Golden Vector current price moved from the broker statement price?" This should be a soft freshness/drift label, not a failure, because live market prices legitimately move. Concrete fix: add a `portfolio_reconciliation` artifact with line-level statuses and a summary status. Use tolerances that reflect statement rounding, for example max($2, 5 bps) at the account level and a per-line tolerance for small rounding differences. The plan's "tight cents" gate is too brittle unless the exported fields are proven to be exact to cents after parsing.

### P1 - B6 requires a new broker-line model; do not stretch the old `Holding`

The plan correctly flags the duplicate-ticker problem. The existing `Holding` loader rejects duplicate tickers (`golden_vector/hedge/holdings.py:47`) and allows exactly one of shares or dollar exposure (`golden_vector/hedge/holdings.py:69`). That is right for the old YAML report and wrong for a broker statement. Broker data needs multiple lines per company, multiple currencies, cash, and sometimes multiple broker symbols mapping to one canonical ticker. Concrete fix: keep `Holding` as a legacy hedge-readiness input and add a separate `BrokerHoldingLine -> PortfolioPosition` grouping flow. The grouping key should be a stable `company_id` or canonical universe ticker from `portfolio_symbol_map.yaml`, while the line artifact preserves raw broker symbol, exchange, account section, currency, quantity, price, and value.

### P1 - B7 privacy is correctly ranked but misses an existing leak path

The plan's privacy concern is real. `.gitignore` already ignores `data/manual/portfolio/` and `data/manual/holdings/` (`.gitignore:21`), and `data/output/` is ignored (`.gitignore:16`), so the immediate tracked-file risk is lower than the plan implies. The bigger gap is that the workspace currently serves `data/output/hedge_readiness/latest.md` directly at `/hedge-readiness/latest.md` (`golden_vector/serve/workspace.py:107`), and that report can include real holdings from `load_holdings` (`golden_vector/hedge/report.py:196`). The server also defaults to loopback but does not reject a non-loopback host (`golden_vector/serve/workspace.py:545`). Concrete fix: gate all portfolio/holdings-bearing routes, including the existing markdown download, behind `portfolio_enabled`; reject `0.0.0.0` or non-loopback binds when portfolio is enabled; and add tests that no account values or raw account identifiers appear in logs, HTML, markdown, tracked files, or review artifacts. Keep explicit `.gitignore` patterns for `data/manual/**/ibkr*.csv`, `data/manual/**/*portfolio*.csv`, and any portfolio export formats even though the main folders are ignored.

## Blocker-by-Blocker Review

### B1 - Pence / LSE valuation

Verdict: correct blocker, incomplete fix. The case-sensitive `GBp` detection is right, and I would not make it case-insensitive. The missing piece is a shared price-unit primitive and history-path coverage. Fix the history path before the Portfolio value-over-time chart, not later. Also persist evidence fields (`feed_currency`, `minor_unit_adjusted`, `scale_factor`) because "why was this divided by 100?" must be auditable for a real portfolio screen.

### B2 - Notional formula / double conversion

Verdict: correct blocker, but the plan needs stronger contracts. Use IBKR statement values for import reconciliation and Golden Vector prices only for live drift and analytics. Do not reuse `compute_portfolio_totals` for valuation because it already assumes USD prices. The cleanest fix is a typed valuation helper whose signature makes double conversion impossible: it should require both a raw currency and a value currency, and it should return both local and USD values plus provenance.

### B3 - GDX/GDXJ beta without universe pollution

Verdict: correct blocker, but it should be its own artifact-producing stage. Reusing the Tool A estimator is right; copying Tool A output by adding GDX/GDXJ into the universe is wrong. The benchmark beta stage should read `config/benchmarks.yaml`, compute benchmark betas using the same structural series/estimator primitives as Tool A, write `benchmark_betas_{run_id}.parquet`, register it in the model-state manifest, and make downstream cards fail closed when it is missing.

### B4 - Cash in NAV, not in gold shock

Verdict: correct and important. Cash must be included in NAV and concentration weights but excluded from gold beta/shock exposure. The plan should also distinguish "equity weight" from "NAV weight" everywhere. For example, a stock can be 20% of equity exposure but 12% of NAV if the account holds cash. Both are useful; mixing them silently would be misleading.

### B5 - Two-stage reconciliation

Verdict: correct direction, needs a clearer gate. Stage 1 parse/reconcile should hard-fail analytics when the statement cannot be trusted. Stage 2 Golden Vector live-price drift should never hard-fail; it should label prices as fresh, stale, or drifted. Store both as artifacts so the UI does not recompute the same answer.

### B6 - Dual listings and broker lines

Verdict: correct blocker, under-modeled. "Group by company" is right for analytics, but the raw line model must remain visible and auditable. Add a symbol-map schema with raw broker symbol, broker exchange/currency, optional ISIN, canonical universe ticker/company id, and mapping confidence. Do not rely only on ticker strings; dual listings and local symbols make plain `.upper().strip()` too weak for real broker data.

### B7 - Privacy

Verdict: correct blocker, but expand it to existing hedge-readiness outputs. Portfolio privacy is not just the new tab. The old markdown report endpoint and old holdings YAML path are already enough to expose real values locally if the server is bound too widely. Add route-level privacy gates, non-loopback bind refusal when portfolio data is enabled, explicit ignore patterns, and a simple tracked-file scan test for account-number-like strings.

## Architecture Review

### Where the portfolio compute should live

I would not extend the `hedge-readiness` CLI/report step as the primary portfolio engine. That step is report-first: it loads options state, builds report sections, renders markdown, and writes `latest.md` (`golden_vector/hedge/report.py:175`). A Portfolio tab needs data-first behavior: compute once during refresh, persist typed artifacts, serve read-only. Add a new portfolio pipeline step, either as `python main.py portfolio` for focused rebuilds and as part of `python main.py refresh` for normal operation. The hedge report can later read the same artifacts if it wants portfolio totals.

### Artifact schemas

The v3 schemas are in the right spirit but too compressed. Do not put raw lines, grouped positions, cash, reconciliation, and chart points into one `portfolio_holdings` table. That creates the same confusion the plan is trying to avoid. Use separate artifacts with explicit grain:

- line grain: one broker line or cash line.
- position grain: one canonical company/ticker after grouping.
- summary grain: one row per portfolio build.
- chart grain: one row per date/ticker/metric or precomputed chart point.
- benchmark grain: one row per benchmark beta.

This also makes schema validation simpler and gives the UI clean fallbacks: if charts are missing but summary is valid, the tab can still render the summary.

### Shared valuation helper

The shared helper is the right idea, but it should not live only under portfolio if market snapshot and historical price standardization also need it. Put the unit-scale and FX-value rules in a shared normalization/common location, then have snapshot, history, and portfolio all call it. Otherwise the pence bug gets fixed three times with slightly different behavior.

### Manifest integration

Portfolio should follow the existing manifest pattern, not add a custom pointer. Register portfolio artifacts in the model-state artifact map, require the summary/positions artifacts for portfolio completeness, and include their refresh ids in `_alignment`. The UI should load them through `resolve_current_model_artifact_path`, just like newer options readers do.

### Request path

The Portfolio tab should not parse CSVs, scan raw histories, compute correlations, or build hedge scenarios inside `serve/workspace.py`. It should only read checked artifacts and render. This matches the repository's architecture-foundations rule and avoids repeating the earlier option-page slowdown.

## Locked Decisions

### USD base

I agree with USD as the portfolio base. It is the simplest way to compare holdings across Australia, London, Canada, and the US. The UI should still show raw local currency fields in a detail table so Emanuel can reconcile against his broker statement.

### P&L disabled stub

I agree. P&L without cost basis is fake precision. Use a calm disabled section: "Cost basis not imported yet." Do not infer cost basis from first seen price or historical price.

### Keep all three charts

I would keep them only if they are coverage-gated and precomputed. The value-over-time chart is blocked by the history pence fix. The concentration chart is high value and should ship first. The correlation heatmap is easy to overbuild and hard for a beginner to act on; if kept, also show a simpler "largest paired exposures" table beside it.

### Overshoot hedge gated behind GDX

I agree with the GDX gate. I would go further and make single-name short/overshoot hedge suggestions informational only for v1. Shorting individual miners needs borrow availability, borrow cost, and gap-risk caveats that the system does not have. A GDX/GDXJ hedge-sizing card is safer and easier to explain.

## New Ideas Worth Adding

1. Add a "What matters today" panel with five plain numbers: NAV, cash %, largest position weight, modeled portfolio move at gold -10%, and approximate GDX hedge notional for a target protection level.
2. Add a "Data issues to fix" panel before analytics: unmapped broker lines, stale prices, missing FX, missing Tool B manual data, missing benchmark beta, and reconciliation failures.
3. Add "beta contribution" by position: `position_notional_usd * down_beta / total_beta_exposure`. This is more actionable than just position weight because it shows what drives downside gold exposure.
4. Add portfolio coverage metrics: percent of NAV covered by Tool A, Tool B, Tool D, option data, and benchmark hedge data. If coverage is low, suppress confident-looking charts.
5. Keep a simple exportable reconciliation CSV so Emanuel can inspect raw broker line -> canonical position transformations.

## Things To Cut Or Defer

1. Defer single-name overshoot hedge recommendations until borrow availability and shorting assumptions are modeled. Show only high-level sensitivity/risk if needed.
2. Defer P&L until cost basis import exists.
3. Defer any portfolio "score." The plan is good about avoiding opaque composites; keep it that way.
4. Defer correlation heatmap polish if the history pence fix or chart coverage takes longer. Concentration and beta contribution are higher value.

## Golden Vector Hard Rules / Honesty Bar

The plan can uphold the hard rules, but only after the fixes above:

- Currency normalization: not yet safe until history and broker valuation share the same unit/FX helper.
- No opaque composites: good. Keep portfolio as raw facts, checks, and scenario rows.
- Testable/versioned/auditable: not yet complete until portfolio artifacts have explicit schema versions, source hashes, manifest entries, and checked readers.
- Compute once, persist, serve reads: the plan says this, but reusing the markdown/report engine risks violating it. The portfolio tab should read artifacts only.
- Fail loud: required for broker import, schema mismatch, missing benchmark beta, missing price unit, and stale portfolio artifacts.

## Test Requirements Before Build Is Accepted

1. LSE pence snapshot and history test: a `GBp` quote is divided once, not zero times and not twice.
2. Broker import test with duplicate company lines: two raw lines map to one canonical position while preserving both line records.
3. Cash test: cash included in NAV and concentration denominator, excluded from gold-shock exposure.
4. Reconciliation tests: broker totals pass; deliberate mismatch hard-fails analytics; live GV price drift labels but does not hard-fail.
5. Benchmark beta tests: GDX/GDXJ beta artifact is produced without adding either ticker to `config/universe.yaml`; missing benchmark artifact disables hedge sizing.
6. Privacy tests: portfolio disabled hides all portfolio pages/downloads; non-loopback bind with portfolio enabled is refused; `/hedge-readiness/latest.md` cannot leak holdings values.
7. Manifest tests: portfolio artifacts resolve through immutable model-state paths, not mutable aliases.
8. Serve-layer test: portfolio route does not read raw CSVs or compute chart data.
9. Schema stale test: old portfolio artifacts show a calm "run refresh" page, not a 500.

## Nits And Smaller Corrections

1. `.gitignore` already protects `data/manual/portfolio/` and `data/manual/holdings/`, so the plan should state the remaining risk precisely: manual CSVs outside those directories are currently re-included by `!data/manual/**/*.csv` (`.gitignore:18`).
2. If the plan uses "portfolio holdings" as a table name, specify its grain. I would rename it to `portfolio_lines` or `portfolio_positions` to avoid ambiguity.
3. Add `source_file_sha256` for the imported statement, but do not store full local file paths in user-visible HTML.
4. Keep account number, broker account name, and personal identifiers out of artifacts unless there is a direct need. A stable salted hash is enough if account grouping is required later.
5. Do not call the GDX/GDXJ hedge "recommended" unless the data quality gates pass. Use "modeled hedge size" or "reference hedge size."
6. The UI copy should say "modelled from latest refresh" and show the broker statement date separately from the Golden Vector price date.
7. If `portfolio_enabled` is false, the page should still explain how to enable/import locally without showing any values or file paths.

## Bottom Line

The plan is close on product direction but not ready to build. The biggest change I recommend is to treat Portfolio as a first-class persisted data product, not a new presentation of a markdown report helper. Once the portfolio compute layer, shared valuation/unit helper, benchmark-beta artifact, reconciliation artifact, and privacy gates are specified, this becomes a much safer milestone to implement.
