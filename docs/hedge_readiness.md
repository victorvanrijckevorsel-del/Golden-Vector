# Hedge Readiness

Hedge Readiness is the local CLI report for the downside-product line. It is built for two
related workflows:

- **Portfolio protection:** if the holdings file has positions, the report shows modeled
  downside, candidate listed puts, hedge-cost estimates, and proxy hedges where direct options
  are not usable.
- **Speculative put discovery:** even with no holdings, the report still ranks the universe and
  shows candidate puts so the user can ask, "If I buy X puts and gold drops, what could this be
  worth?"

The report is not a trade ticket and it does not recommend one contract. It shows data, model
assumptions, and skipped-input reasons so the user can decide what deserves follow-up.

## Workflow

Refresh the local data and options snapshots:

```powershell
python main.py update-data
```

Render the markdown report:

```powershell
python main.py hedge-readiness
```

The report is written to:

```text
data/output/hedge_readiness/<YYYYMMDD>_<run_id>.md
data/output/hedge_readiness/latest.md
```

`latest.md` is a copy of the newest report for quick inspection. The run-specific file is the audit trail.

## Workspace Option Trading Tab

The local workspace exposes the same structured options data at:

```text
/option-trading
```

This is the primary UI for the put/call workflow. The old `/hedge-readiness` page redirects to
the tab; the raw markdown report is still downloadable from `/hedge-readiness/latest.md`.

The tab lists optionable gold stocks, sorted by Tool A downside sensitivity. Each row separates:

- **Downside puts:** modeled with `down_beta_core` and gold scenarios at 0%, -5%, -10%, -15%, and -20%.
- **Upside calls:** modeled with `up_beta_core` and gold scenarios at 0%, +5%, +10%, +15%, and +20%.

Calls are shown as leveraged bullish-gold speculation, not as hedges and not as the ranking basis.
Clicking a ticker opens:

```text
/ticker/<TICKER>?lens=option-trading
```

The ticker detail panel shows candidate puts, candidate calls, scenario tables, and a GET-only
sizing calculator. The calculator does not save trades or mutate local data. It has two modes:

- **Contracts:** directly set the number of standard 100-share option contracts.
- **Budget:** treat the dollar amount as premium spend, then buy `floor(budget / (mid * 100))`
  contracts and show leftover cash.

Invalid side, horizon, quantity, or budget inputs fall back to safe defaults and render a note on
the page instead of raising an error.

## CLI Reference

```powershell
python main.py hedge-readiness `
  --ranking-sort-by down_beta_core `
  --comparison-sort-by pnl_per_dollar_premium_minus10 `
  --ranking-max-tickers 5 `
  --speculation-max-tickers 3 `
  --quantity 10
```

| Flag | Purpose |
|---|---|
| `--ranking-sort-by` | Sort field for the Sensitivity Ranking. Current supported value: `down_beta_core`. |
| `--comparison-sort-by` | Sort field for the Cross-ticker Comparison View. |
| `--ranking-max-tickers` | Maximum rows to show in the Sensitivity Ranking. |
| `--speculation-max-tickers` | Maximum ticker blocks to show in Speculation Candidates. |
| `--quantity` | Number of option contracts used in scenario net P&L. |

If a flag is omitted, the report uses `config/hedge_readiness.yaml`.

Useful comparison sort choices include `pnl_per_dollar_premium_minus10`, `breakeven_gold_pct`,
and P&L columns. Quote and P&L-per-share columns remain per-share option values; net P&L applies
quantity times the standard 100-share multiplier.

## Options Phase

`update-data` runs the hedge-readiness options phase by default. That phase:

- fetches listed Yahoo option chains for every active universe ticker
- writes run-local snapshots under `data/runs/<run_id>/snapshots/options/`
- writes `data/intermediate/status/latest_options_manifest.json`
- appends one derived feature row per ticker under `data/intermediate/options_features/`
- fetches hedge-side benchmarks from `config/benchmarks.yaml`
- records the options manifest in the run replay manifest

If the normal market-data refresh is needed but options should be skipped, use:

```powershell
python main.py update-data --no-options
```

The run metadata records that the options phase was intentionally skipped. The hedge-readiness
report continues to use the last successful `latest_options_manifest.json` until options are
refreshed again.

## Holdings File

The report can run without a holdings file. In that case it shows cross-sectional hedge readiness only and skips portfolio-only sections.

To enable position-aware exposure and premium-vs-downside cards, create:

```text
data/manual/holdings/holdings.yaml
```

Format:

```yaml
version: 1
holdings:
  - ticker: NEM
    shares: 500
  - ticker: AEM
    dollar_exposure: 50000
```

Each holding must set exactly one of `shares` or `dollar_exposure`, and each ticker can appear
only once. The loader does not auto-create this file, and it fails loudly on malformed entries so
exposure is not silently misread.

## Report Sections

The report renders these sections in order:

1. **Header:** benchmark moves and implied-vs-modeled-downside heuristic verdicts.
2. **Snapshot Summary:** run id, dates, optionability counts, holdings count, CLI/config
   parameters, context alignment, and risk-free-rate status.
3. **Sensitivity Ranking:** universe-wide Tool A down-beta ranking with 60-day listed-put P&L at a gold -10% scenario.
4. **Portfolio Totals:** only when holdings exist; aggregate portfolio value, modeled downside, and hedge-cost estimates.
5. **Held Positions:** only when holdings exist; per-position candidate puts and scenario tables.
6. **Speculation Candidates:** universe-level candidate put blocks, independent of holdings.
7. **Cross-ticker Comparison View:** flat sortable candidate table across tickers and horizons.
8. **Proxy Hedges:** only when held tickers are not directly hedgeable.
9. **Sources / Run Summary:** manifest paths, source row counts, and run parameters.

## Sensitivity Ranking Walkthrough

Sensitivity Ranking is the fastest way to see which names have the largest modeled downside
response to a gold drop. It sorts by Tool A `down_beta_core`, then attaches:

- `up_beta_core` for context
- confidence label and score
- cross-sectional IV percentile when options features exist
- 60-day listed-put P&L/share at the configured gold scenario
- notes explaining missing options, missing candidates, score ineligibility, or missing beta

This section is deliberately close to the future Tool C user experience: a universe-wide downside
ranking with visible sample/data caveats, not a hidden composite score.

## Portfolio Totals Walkthrough

Portfolio Totals appears only when the holdings file has at least one position.

For share-based holdings, current notional is:

```text
shares * current_stock_price
```

For dollar-exposure holdings, current notional is the supplied `dollar_exposure`. That lets the
report model portfolio downside even when no share count is known.

Hedge-cost estimates are stricter. They need:

- a resolved current stock price
- a usable 60-day candidate put
- a candidate mid price
- enough down-beta signal to model downside

If those inputs are missing, the report still counts notional where possible and adds a skipped reason instead of inventing a hedge cost.

## Scenario Math

The scenario engine is strategy-generic. The code supports:

- long put
- short put
- long call
- short call

M1.5 surfaces **long put** scenarios in the CLI report. The generic strategy layer exists so
future put/call workflows can reuse the same tested P&L rules instead of reimplementing option
math in each report section.

The stock move model is linear:

```text
modeled_stock_down_pct = max(0, down_beta_core * abs(gold_move_pct))
modeled_stock_price = max(0, current_stock_price * (1 - modeled_stock_down_pct))
```

At-expiry values use intrinsic option value. Current quote-style values use Black-Scholes with the listed implied volatility.

## Risk-free-rate Fallback

The options phase tries to fetch the risk-free rate from the 13-week T-bill source. If that fetch fails, the report does not collapse.

- Delta selection uses a `0%` fallback so candidate selection and optionability can still run.
- Black-Scholes mark-to-market values also use `0%`, but sections that show those current values disclose the fallback.
- Sensitivity Ranking expiry P&L does **not** show a rate fallback note because expiry intrinsic
  value does not depend on the risk-free rate.

## Recovery Notes

If `python main.py hedge-readiness` says there is no options snapshot, run:

```powershell
python main.py update-data
```

If Yahoo options are temporarily unreliable but the foundation refresh is still needed, run:

```powershell
python main.py update-data --no-options
```

That keeps Tool A and Tool B refreshes moving while preserving the last successful hedge-readiness options snapshot for reporting.

If the report shows `Analytical context alignment | WARN |` or `UNKNOWN`, the options snapshot is
newer than the latest Tool A or Tool B output, or the older output does not carry a refresh id.
Run the normal analytical steps again before using the report for decisions:

```powershell
python main.py tool-a
python main.py tool-b
python main.py hedge-readiness
```
