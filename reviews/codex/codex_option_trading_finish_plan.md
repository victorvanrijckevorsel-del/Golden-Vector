# Option Trading Finish Plan

**Author:** Codex
**Date:** 2026-06-04
**Purpose:** turn the remaining Option Trading recommendations into a concrete finish plan.
**Status:** planning only. Updated after Claude review F1-F5.

## 1. Current State

The Option Trading tool now has the core single-name candidate redesign:

- Ticker detail option lens shows stock price, cached snapshot context, put/call tabs, and selectable candidates.
- Display horizons are now the practical bands around 60d, 90d, and 120d.
- 30d tactical contracts were removed from the primary candidate flow.
- Candidate buckets were simplified to near-ATM and directional.
- Junk contracts are no longer supposed to appear as normal suggestions.
- Yahoo chain links exist so the user can inspect the real listed expiry.
- The UI uses cached Yahoo/yfinance data only; it is not live execution pricing.

This is a good base, but the tool is not "finished" yet because it still lacks three practical pieces:

1. A visible data-refresh workflow.
2. Measured GDX/GDXJ option liquidity.
3. A clear fallback when single-name options are too thin.

Those three pieces are the recommended finish scope for Option Trading v1.

## 2. Product Goal

The finished v1 should answer:

> "For this gold-stock ticker, what are the sensible listed put/call contracts I can inspect, and if the single-name chain is too thin, is there a more liquid gold-miner proxy I should look at instead?"

The tool should not say:

- "Buy this."
- "This is the best trade."
- "This option is definitely liquid now."
- "This hedge amount is correct for your portfolio."

It should say:

- "This is a cached screening candidate."
- "Here is the stock price, strike, expiry, moneyness, mid price, spread, OI, volume, and Yahoo chain link."
- "This is tradable/watch/no-trade based on cached bid/ask and liquidity checks."
- "Single-name options are too thin here."
- "GDX/GDXJ proxy liquidity has been measured, and here is what the data says."

## 3. Finish Scope

### In Scope For Option Trading v1

1. Real options/market-snapshot refresh button and status.
2. GDX/GDXJ option-chain ingestion verification/completion.
3. GDX/GDXJ liquidity measurement against miner single-name chains.
4. Proxy fallback display when a single-name chain is too thin.
5. Final UI cleanup around data freshness, source labeling, and "screening only" language.
6. Tests and docs for the above.

### Out Of Scope For Option Trading v1

1. Full in-app Yahoo-style option-chain browser.
2. Broker integration or executable quotes.
3. Volatility-surface modeling.
4. Backtesting option-selection performance.
5. Recommendation/trade-decision thresholds.
6. Auto hedge sizing.
7. Portfolio hedge calculator.
8. Tool C/Tool D ranking integration.
9. Public put-call ratio or option-flow signal.

These can be future milestones, but they should not block finishing the Option Trading tab.

## 4. Core Design Decisions

### Decision 1 - Refresh Means "Update Options/Market Snapshot", Not "Live Quote"

The Option Trading refresh button should update the cached market/options snapshot shown on the page. It should not silently run the whole analytics stack or rebuild Tool A/Tool B. If the implementation reuses an existing command, it must be scoped to the market-data/options phase, for example an explicit options-snapshot refresh or `update-data --options` without `tool-a`, `tool-b`, or the full operational `refresh` command.

The UI must not imply that prices are live executable quotes.

Recommended label:

```text
Refresh cached options data
```

Recommended status text:

```text
Last cached options snapshot: 2026-06-01
Screening only - verify bid/ask on Yahoo or broker before trading.
```

### Decision 2 - Refresh Should Be A Background Job

The WSGI UI should not freeze while the update runs. Add a small local background-job layer:

- one active refresh at a time
- status: idle, running, succeeded, failed
- started_at, finished_at, latest_run_id, error_summary
- visible status in the UI
- duplicate clicks should return "already running"
- Windows-safe detached subprocess handling
- stale-running recovery if the process dies or the web worker restarts

The first version can be simple and local-file backed. It does not need Celery, Redis, a database queue, or a new service. Emanuel runs Windows, so do not design this around POSIX `fork` behavior. The child process should be detached enough to survive the request returning, and stale locks must clear if the child process disappears.

### Decision 3 - GDX/GDXJ Must Be Measured Before Being Used As A Proxy

The research and prior plans are clear: GDX/GDXJ are probably more liquid, but the product must not claim this until our cached chains prove it.

So the build order matters:

1. Verify whether GDX/GDXJ option chains are already ingested.
2. Finish ingestion only if missing or partial.
3. Run the same liquidity engine on them.
4. Compare them against the miner universe.
5. Only then show them as proxy alternatives.

### Decision 4 - GDX/GDXJ Are Option Vehicles, Not Normal Gold-Stock Screen Rows

GDX and GDXJ should be first-class option vehicles in the Option Trading tool, but they should not accidentally become normal Tool A/Tool B screened mining companies.

Implementation should keep this distinction explicit:

- `universe` tickers: gold stocks screened by Tool A/Tool B.
- `option_vehicle` tickers: extra symbols used for options, currently GDX and GDXJ.

### Decision 5 - Proxy Fallback Is Informational, Not A Recommendation

If AEM has weak single-name options, the ticker detail page can show:

```text
Single-name options look thin for this horizon. GDX/GDXJ may be cleaner sector-level vehicles, but they do not track AEM one-for-one.
```

It should not say:

```text
Use GDX instead.
```

The overview should stay compact. It can show a status/count such as "tradable", "watch", or "no liquid candidate", but it should not pitch proxy alternatives row-by-row.

## 5. Proposed Build Steps

### Step 0 - Freeze Current Option Candidate Redesign

Before adding new scope, finish the current candidate-redesign work cleanly:

- Review the current uncommitted option-related diff.
- Run the focused option/candidate tests.
- Commit the current redesign once green.
- Do not mix refresh/GDX work into that commit.

Acceptance:

- Current Option Trading candidate UI remains working.
- AEM/NEM detail pages load.
- 60/90/120 horizons remain visible.
- No 30d primary candidates.
- No half-spread-cost column in the main candidate table.
- `is_usable_candidate()` remains strict: only `tier == "tradable"` counts as usable.
- A Watch-only ticker is not counted as usable by the Candidate Finder.
- The Candidate Finder tier-aware regression test is green before committing this redesign as frozen.

### Step 1 - Add Refresh Job State

Add a small refresh-status module that records:

- current status
- active job id
- child process id if available
- started_at
- finished_at
- command run
- latest run id if available
- error summary if failed

Storage recommendation:

```text
data/runs/ui_refresh_status.json
```

The file is local runtime state, not analytical output. It should be written defensively with a temp file then rename.

Acceptance:

- Status can be read when no file exists.
- Status survives process restart.
- Corrupt status file degrades to a visible "unknown/failed to read status" state, not a crash.
- If status says "running" but the child process is gone, the next status read recovers to failed/unknown instead of staying running forever.
- A killed mid-run process is represented as a non-running failed/unknown state on the next read.

### Step 2 - Add Refresh Trigger Endpoint

Add a WSGI route that starts the scoped options/market-snapshot refresh command in the background.

Default command intent:

```text
refresh latest market/options snapshot used by Option Trading
```

Implementation rule: do not wire this button to the full operational `python main.py refresh` command, and do not rerun Tool A/Tool B from this button. If the existing CLI does not expose a clean options-snapshot command, add one or wrap the existing foundation/options phase explicitly.

Rules:

- If a refresh is already running, do not start another.
- Spawn a detached child process, not a request-thread worker.
- Use Windows-compatible subprocess flags so the job is not tied to the WSGI request lifecycle.
- Capture stdout/stderr to a log file.
- Update the status file on success/failure.
- Redirect back to the page the user came from.
- Never hide failures.

Acceptance:

- Clicking refresh starts exactly one job.
- A second click while running reports "already running".
- On failure, the UI shows failed status and a short error summary.
- No paid API calls are added.

### Step 3 - Add Refresh UI

Add the button and status display in two places:

1. `/option-trading` overview.
2. Ticker detail option lens, near the cached snapshot/source line.

UI requirements:

- Button text: "Refresh cached options data".
- Show last options snapshot date.
- Show job status.
- Show "screening only" source language.
- Disable or visually mark the button while running.

Acceptance:

- User can see where the data came from.
- User can update cached data without using the terminal.
- UI never says "live price" or "real-time quote".

Checkpoint A:

- Stop after Step 3.
- Demonstrate that refresh status and the UI button work.
- Show running/succeeded/failed behavior from the local UI or tests.

### Step 4 - Verify Or Complete GDX/GDXJ Option-Chain Ingestion

First reconcile the current state in `golden_vector/ingestion/options_phase.py`. The current code already has benchmark ETF option-target concepts, so this step must verify whether GDX/GDXJ chains are fully cached, manifested, and replay-audited before adding code.

If ETF option chains are already ingested correctly, this step is "verify and test." If they are missing or partial, finish the ingestion phase so GDX and GDXJ are fetched as option-chain symbols, not just benchmark price histories.

Configuration should make these explicit:

```yaml
option_vehicle_tickers or benchmark_tickers:
  - GDX
  - GDXJ
```

Rules:

- Persist their option chains like universe tickers.
- Record them in the options manifest.
- Record source assets in the replay manifest.
- Keep per-symbol failures isolated.
- Do not add GDX/GDXJ to Tool A/Tool B company rankings by accident.

Acceptance:

- Current ingestion behavior is documented before changes.
- A cached run can contain GDX and GDXJ options.
- Missing GDX/GDXJ options do not break the whole universe.
- Replay manifest knows where those option-chain assets came from.
- GDX/GDXJ remain option vehicles or benchmark ETFs, not normal Tool A/Tool B company rows.

### Step 5 - Measure ETF Liquidity Versus Miner Chains

Add a small diagnostics layer that compares option liquidity for:

- GDX
- GDXJ
- optionable miner universe

Metrics:

- median relative spread by side/horizon/bucket
- median open interest
- median volume
- count of tradable candidates
- count of watch candidates
- count of no-trade candidates
- latest snapshot date

Do not overbuild the stats. The purpose is simple: prove whether the ETF chains are materially cleaner than the miner chains.

Acceptance:

- The output can say "GDX/GDXJ liquidity measured".
- The UI/report can show whether ETF liquidity is actually better.
- If the data does not prove better liquidity, the UI does not present ETF proxy as cleaner.

Checkpoint B:

- Stop after Step 5.
- Report whether GDX/GDXJ option chains were already present or had to be completed.
- Show the measured ETF liquidity summary versus miner single-name chains.

### Step 6 - Surface GDX/GDXJ As Option Vehicles

Add GDX and GDXJ as browsable rows in `/option-trading`.

They should:

- use the same candidate engine
- use the same put/call tabs
- use the same horizon bands
- show stock/ETF price
- show Yahoo chain links
- be clearly labeled as ETFs/sector vehicles

Acceptance:

- User can open `/ticker/GDX?lens=option-trading` and `/ticker/GDXJ?lens=option-trading` or equivalent vehicle detail pages.
- They do not appear as normal Tool A/Tool B mining-company outputs unless explicitly supported.

### Step 7 - Add Single-Name Proxy Fallback On Detail Pages

When a stock has no sensible liquid candidate for a selected side/horizon:

1. Say the single-name chain is thin.
2. Show GDX/GDXJ proxy candidates only if measured liquidity supports them.
3. Show basis-risk language.
4. Keep shares as a simple non-option alternative.

Example copy:

```text
No sensible liquid AEM put was found for this horizon in the cached chain.
GDX/GDXJ are sector ETFs, not AEM. They may be more liquid, but they carry basis risk.
```

Acceptance:

- No forced bad single-name option.
- ETF proxy appears only after ETF options are cached and measured.
- Proxy display does not prescribe a trade or hedge amount.
- Proxy suggestion appears on ticker detail pages only.
- Overview shows compact candidate status/counts only, not row-level proxy suggestions.

### Step 8 - Final UX Polish

Clean the Option Trading pages so they are simple:

- one compact data-source line
- refresh button and status
- stock/ETF price always visible
- put/call side toggle
- 60/90/120 candidate cards or rows
- mid price only in the main view
- bid/ask and detail available nearby
- Yahoo chain link for each expiry
- no long caveat paragraphs
- no P&L/share columns in overview
- no "level" or unclear labels

Acceptance:

- Beginner can understand what the page is showing.
- Advanced user can inspect the contract details.
- Page does not look like a dense data dump.

Checkpoint C:

- Stop after Step 8.
- Show `/option-trading`, one liquid ticker, one thin ticker, and one GDX/GDXJ vehicle page.
- Confirm proxy fallback appears only in the ticker-detail decision point.

### Step 9 - Tests And Verification

Add focused tests for:

- refresh status read/write
- duplicate refresh protection
- stale-running recovery when a child process is gone
- refresh route success/failure behavior
- GDX/GDXJ config loading
- GDX/GDXJ option-chain manifest inclusion
- ETF liquidity diagnostic calculations
- proxy fallback appears only when measured and eligible
- proxy fallback hidden when ETF data is missing or not better
- overview/detail pages show refresh state and snapshot date

Manual browser checks:

- `/option-trading`
- `/ticker/AEM?lens=option-trading`
- `/ticker/NEM?lens=option-trading`
- GDX/GDXJ option vehicle pages
- one thin single-name case
- one liquid ETF case

## 6. Completion Criteria

Option Trading v1 is done when:

1. The user can refresh cached options/market-snapshot data from the UI.
2. The user can see when the option data was last refreshed.
3. GDX/GDXJ option chains are cached and audited.
4. GDX/GDXJ liquidity is measured, not assumed.
5. Thin single-name options do not produce forced bad candidates.
6. Proxy alternatives are shown only when the data supports them.
7. The UI stays clear, compact, and beginner-readable.
8. Tests cover the new refresh, ETF, and proxy behavior.
9. No recommendation language or hedge sizing sneaks into v1.

## 7. Future Milestones After V1

### Future A - Portfolio Hedge View

This should load Emanuel's holdings, normalize currencies, estimate portfolio gold-downside exposure, and show possible GDX/GDXJ put scenarios. It is useful, but it is bigger than finishing the Option Trading tab.

Build after v1 if Emanuel wants the product to answer:

> "How could I hedge my actual portfolio?"

### Future B - Tool C / Tool D Integration

Tool C/D can later help rank which stocks deserve attention before opening the Option Trading page. This should not block the option UI.

### Future C - Full Option Chain Browser

Only build this if Yahoo links are not enough. It is not needed for v1.

### Future D - Backtesting

Useful for validating selection rules, but not needed before the tool becomes usable.

### Future E - Better Market Data

If execution-grade option quotes become necessary, yfinance is not enough. That would require a proper options data provider or broker feed and should be a separate paid-data decision.

## 8. Recommended Next Action

Build only after the current candidate redesign is frozen with the F1 Candidate Finder guard verified. Then implement in three checkpoints:

1. Checkpoint A: refresh job state, trigger endpoint, and UI.
2. Checkpoint B: GDX/GDXJ ingestion reconciliation and measured ETF liquidity.
3. Checkpoint C: detail-page proxy fallback and final UX polish.

Locked answers from review:

1. Refresh button is options/market-snapshot scoped, not a full analytics rebuild.
2. GDX/GDXJ remain separate option vehicles or benchmark ETFs, not normal universe companies.
3. Proxy fallback belongs on ticker detail pages; overview stays compact.
4. Portfolio hedge stays out of v1.
