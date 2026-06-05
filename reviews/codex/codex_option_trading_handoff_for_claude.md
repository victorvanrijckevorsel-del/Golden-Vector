# Codex Handoff: Option Trading UI, Refresh, Proxy, And Performance Questions

## Purpose

This document summarizes the option-trading work Codex just built and the problems encountered, so Claude can review the architecture and think about a better next design. The main open question is performance and data-flow: the page works, but the first load is heavy because the WSGI request path still computes too much from cached option-chain files.

## Recent Commits

- `bf008bb` - Refine option candidate selection
- `5240368` - Add option trading refresh workflow
- `6531092` - Show benchmark ETF option liquidity measurement
- `0328a47` - Add option ETF proxy fallback
- `2023018` - Harden option trading refresh context

## What Was Built

### 1. Candidate Selection Redesign

The option candidate model was simplified around what Emanuel asked for:

- Removed 30d from the displayed horizons.
- Display horizons are now 60d, 90d, and 120d.
- Each horizon can show four user-facing slots:
  - Put Near-ATM
  - Put Directional
  - Call Near-ATM
  - Call Directional
- Near-ATM means OTM only, roughly 0-5% OTM.
- Directional means OTM only, preferred 15-20% OTM, allowed 12-22% OTM when liquidity is better.
- Watch rows can still be displayed as context, but are not considered usable.

Main files:

- `golden_vector/hedge/options_liquidity.py`
- `golden_vector/serve/option_trading_data.py`
- `golden_vector/serve/detail_panels.py`
- `config/hedge_readiness.yaml`

### 2. Option Trading Overview And Detail UI

The Option Trading overview now shows:

- Stock price, so the user can compare strike vs current stock price.
- Put and call status.
- Cached snapshot date.
- Cached Liquidity Check for:
  - Benchmark ETFs
  - Single-stock miners
- Tradable / Watch / No-trade counts.
- A refresh button.

The ticker detail page now shows:

- Cached options snapshot date.
- Source: cached Yahoo Finance option-chain data via `yfinance`.
- Risk-free rate.
- Refresh control.
- Current stock price.
- Candidate matrix with OTM, mid, bid/ask, spread, OI, volume, delta, tier, Yahoo chain link, and note.
- Yahoo chain link per expiry.
- Sizing calculator for tradable contracts only.

Important current behavior:

- Watch rows remain visible, but they show `-` instead of a Select link.
- Watch rows do not create scenario bundles.
- A typed URL selecting a Watch bucket produces no scenario table.

### 3. Refresh Button

Added a local UI refresh workflow:

- POST route: `/option-trading/refresh`
- Status file: `data/runs/ui_refresh_status.json`
- Logs under: `data/runs/ui_refresh_logs/`
- Background child runner: `golden_vector.serve.option_refresh`
- Command run by the button:
  - `python main.py update-data --options`

Important limitation:

- `update-data --options` refreshes foundation/raw inputs and options.
- It does not rerun Tool A or Tool B.
- Therefore, after a UI refresh, option chains can be fresh while Tool A beta and Tool B fundamentals remain older.

This was hardened in `2023018` by adding visible mixed-refresh warnings.

### 4. Mixed-Refresh Warning

The UI now warns when the options run id differs from Tool A or Tool B snapshot refresh ids.

Example warning from current local data:

```text
Refresh context is mixed: options snapshot uses 20260601T135914Z-update-data-f555b2fe; Tool A uses 20260424T140753Z-update-data-6175c3fb; Tool B uses 20260424T140753Z-update-data-6175c3fb. Scenario betas and fundamentals may lag the option chains. Run python main.py refresh to realign the full model outputs.
```

This appears on both:

- `/option-trading`
- `/ticker/<TICKER>?lens=option-trading`

Main files:

- `golden_vector/hedge/option_trading.py`
- `golden_vector/serve/option_trading_data.py`
- `golden_vector/serve/overview_option_trading.py`
- `golden_vector/serve/detail_panels.py`

### 5. Benchmark ETF Liquidity And Proxy Fallback

GDX/GDXJ are now supported as benchmark ETF option vehicles when they exist in the cached option snapshot.

What was added:

- Benchmark ETF liquidity measurement row.
- GDX/GDXJ option detail pages only under the option lens.
- `/ticker/GDX?lens=option-trading` can render when GDX exists in the latest option snapshot.
- `/ticker/GDX` without the option lens remains 404.
- ETF proxy fallback section can appear on single-stock detail pages when the selected single-name contract is missing.

Important current local-data state:

- Current cached snapshot shows Benchmark ETFs = 0 measured contracts.
- That means GDX/GDXJ option chains are not present in the current cached latest options snapshot.
- Proxy alternatives stay hidden until a fresh options run fetches benchmark ETF chains successfully.

Latest hardening:

- Proxy gating now only requires benchmark ETF contracts to be Tradable.
- It no longer compares ETF median spread against the broad single-stock miner median.

Main files:

- `golden_vector/serve/option_trading_data.py`
- `golden_vector/serve/detail_panels.py`
- `golden_vector/serve/detail_page.py`
- `golden_vector/serve/workspace.py`

## Problems Encountered

### 1. Page Loads Were Slow

The biggest issue Emanuel noticed was that `/option-trading` and option detail pages took a long time to load, especially after I restarted local servers several times.

Likely cause:

- The UI does not call Yahoo on page load.
- It reads cached files, but the first request does a lot of local work:
  - Read latest options manifest.
  - Read many cached Parquet chain files.
  - Read Tool A and Tool B snapshots.
  - Normalize option chains.
  - Add Black-Scholes deltas.
  - Scan bid/ask, OI, volume, IV, moneyness, and liquidity.
  - Build put and call slots for every optionable ticker.
  - Build scenario bundles.
  - Build benchmark liquidity measurement.
- This is cached in memory after first load, but only inside the current server process.
- I started fresh servers on several new ports, so the cache was cold repeatedly.
- Many Python processes from old local servers and test runs were still running, making the desktop slower.

Evidence:

- Focused option tests passed quickly enough: `48 passed in 32.56s`.
- Full test suite eventually passed: `642 passed in 523.71s`.
- Earlier full-suite attempts timed out only because the desktop was busy and the default timeout was too short.
- Browser load on a fresh port took noticeable time, then rendered correctly.

### 2. Too Much Work Happens In The Request Path

The WSGI app is still doing analytics-ish preparation at page-request time. That is the main architectural weakness.

The option page should ideally read a prepared UI artifact, not compute the candidate grid on demand.

Potential better direction:

- During `update-data --options`, precompute:
  - option candidate slots
  - accepted candidate grids
  - benchmark liquidity summary
  - overview rows or a close-to-render-ready data package
- Persist those as Parquet/JSON under `data/output` or `data/runs/<run_id>/`.
- The UI should then only read the latest prepared artifact.

This would make page load faster and more predictable.

### 3. Refresh Button Scope May Be Confusing

The button says "Refresh cached options data", and it runs:

```text
python main.py update-data --options
```

That is accurate for options and foundation data, but it does not rerun:

- Tool A
- Tool B
- Hedge report
- Candidate Finder output

The mixed-refresh warning now makes this visible, but Claude should consider whether the product should instead have:

- A cheap "Refresh options data only" button.
- A heavier "Refresh full model" button.
- A clear status banner explaining what is stale and what is fresh.

### 4. Benchmark ETF Proxy Depends On Fresh Cached Data

The proxy feature is implemented, but with current cached data the Benchmark ETF measurement is zero. This is probably because the latest local options snapshot was created before GDX/GDXJ option-chain fetches were added, or before a successful refresh included them.

Open question:

- Should the UI show a stronger prompt when Benchmark ETFs = 0, such as "Run Refresh cached options data to fetch GDX/GDXJ chains"?
- Should the refresh status specifically report whether GDX/GDXJ were fetched?

### 5. Watch Rows Are Useful But Risky

Emanuel wants "good candidates" and does not want to be nudged into untradable contracts.

Current compromise:

- Watch rows remain visible for context.
- Watch rows are not selectable.
- Watch rows are not modeled.

Claude should decide whether Watch rows should remain visible in the primary matrix or be hidden behind a disclosure. Hiding them may make the page cleaner.

## Tests And Verification Already Run

After latest fixes:

- `python -m pytest tests/test_option_trading_data.py tests/test_option_trading_detail_panel.py tests/test_option_trading_overview.py tests/test_option_trading_routes.py tests/test_option_refresh.py -q`
  - `48 passed`
- `python -m compileall golden_vector`
  - passed
- `git diff --check`
  - passed
- `python -m pytest -q`
  - `642 passed in 523.71s`
- `python -m ruff check golden_vector tests`
  - not available in this environment: `No module named ruff`

Browser checks:

- `/option-trading` showed:
  - refresh button
  - mixed-refresh warning
  - Benchmark ETFs row = 0 measured contracts
  - Single-stock miners liquidity row
- `/ticker/AEM?lens=option-trading&side=call&horizon=60&bucket=near_atm#option-sizing` showed:
  - mixed-refresh warning
  - Watch row with `-` instead of Select
  - no scenario table for Watch-selected URL

## Questions For Claude

Please think holistically, not just as a patch review.

1. Should option candidate grids be precomputed and persisted during `update-data --options`?

2. If yes, what is the clean artifact boundary?
   - Raw option chains stay as snapshots.
   - Feature rows stay as options features.
   - Candidate slots and UI summary could become a separate "option_trading_latest" artifact.

3. Should the refresh button remain options/foundation only, or should there be a full-model refresh option?

4. Should Watch rows remain visible in the main matrix, or move behind "show rejected/watch contracts"?

5. Should Benchmark ETF proxy support have a stronger explicit freshness check, especially when GDX/GDXJ are absent?

6. Should the WSGI app warm the option cache on startup, or is precomputing enough?

7. Are there too many concepts now in the option page?
   - candidate matrix
   - sizing calculator
   - refresh
   - mixed-refresh warning
   - proxy fallback
   - liquidity check
   Claude should consider if the page should be split into "candidate finder" vs "ticker contract detail".

## Suggested Next Design Direction

The strongest practical next step is probably:

1. Add an option-trading prepared artifact written by the options phase.
2. Make the UI read that artifact instead of scanning chains in the request.
3. Keep raw chain scanning functions pure and testable.
4. Keep the mixed-refresh warning.
5. Consider a second full-model refresh action later, but do not overload the options-only button unless Emanuel explicitly wants the slower full pipeline.

This should solve the slow first-load problem without changing the analytical behavior.
