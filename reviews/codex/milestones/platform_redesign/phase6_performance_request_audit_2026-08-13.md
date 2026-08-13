# Phase 6 performance and request-path audit — 2026-08-13

## Verdict

- **No steady-state render regression above the 10% gate was established.** With the
  ticker-page generation already loaded, `/ticker/NEM` rendered in a median **0.4019 s**, versus
  the recorded Phase 1 median **0.3919 s** (**+2.55%**).
- The current local files are not a coherent post-contract generation: `gold_response` is
  `CORRUPT` because it lacks the five new persisted `spot_*` columns, and `downside_context` is
  `MISSING`. The reader therefore correctly refuses to cache the generation
  (`serve/ticker_page/data.py:193-195`). Natural repeated requests reread and validate the large
  persisted frames and currently take about **1.11 s**. A coherent refresh plus a natural
  same-process remeasurement remains a release gate.
- **No new fetch, write, model computation, or analytics path was introduced in ordinary GET
  handlers.** The only new GET endpoint, `/api/data-status`, reads persisted status/manifest data
  and formats a market-calendar age. Existing mutations remain behind explicit POST routes.

No source-code change was made for this audit.

## Method

The committed baseline is
[`phase1_baseline.md`](phase1_baseline.md). It contains comparable historical measurements only
for `/ticker/NEM` in Our View and Yahoo mode. The same in-process WSGI method was repeated here:

1. `ProjectPaths.discover()`, `load_app_config`, 61 active Tool B tickers, and
   `create_workspace_app` against local persisted data;
2. one untimed warm-up followed by five timed requests in the same process;
3. response length measured from the returned UTF-8 bytes;
4. no browser, network, external API, server process, or full test suite.

For a stronger code-only comparison, detached baseline commit `c7e90db` was rendered against the
**same current read-only intermediate/output/raw/run data** and a disposable copy of the current
manual SQLite store. A profiler pass was then run once per code version. Temporary worktree and
measurement scripts were removed after evidence capture.

## Comparable ticker result

| Measurement | Our View bytes | Our View median | Yahoo bytes | Yahoo median |
|---|---:|---:|---:|---:|
| Recorded Phase 1, then-current data | 448,715 | 0.3919 s | 440,411 | 0.7643 s |
| Detached `c7e90db`, current data | 516,231 | 0.3922 s | 509,516 | 0.8500 s |
| Current code, current incoherent data, natural requests | 566,678 | 1.1052 s | 565,141 | 1.1165 s |
| Current code, same generation already loaded | 566,678 | 0.4019 s | 565,141 | 0.6878 s |

Interpretation:

- The raw historical payload increase is **+26.29%** Our View and **+28.32%** Yahoo, but it mixes
  code changes with months of changed persisted data and added product sections; it is not a
  redesign-only comparison.
- Against baseline code on the **same current data**, the payload increase is **+9.77%**, below
  the 10% investigation threshold. SVG content accounts for +19,625 bytes and tables for +21,017
  bytes; embedded JSON changed only marginally.
- Natural current timing is **+181.83%** against baseline code on the same data. Profiling traced
  this to the deliberately disabled generation cache, not to HTML assembly: current requests made
  16 Parquet reads; `load_ticker_page_data` took ~0.647 s under profiling, including
  `load_performance_series` (~0.278 s, 332,948 rows) and `load_research_series` (~0.236 s, 62,986
  rows).
- Seeding the already-validated generation in the process cache — the steady state after a valid
  coherent publication — reduced Our View to **0.4019 s**, **+2.49%** versus detached baseline code
  on the same data and **+2.55%** versus the recorded Phase 1 median. Yahoo was **10.01% faster**
  than the recorded Phase 1 median.

This simulated cache hit is diagnostic evidence, not a substitute for the release smoke. The
final refresh must produce `OK` `gold_response` and `downside_context` states, then the five-request
natural measurement must be repeated without touching the internal cache.

## Current-only overview snapshot

The Phase 1 evidence has no historical numbers for these routes, so no regression percentage is
claimed:

| Route | Status | Bytes | Five-request median |
|---|---|---:|---:|
| `/tool-a` | 200 | 114,365 | 0.0267 s |
| `/tool-c` | 200 | 40,928 | 0.0131 s |
| `/option-trading` | 200 | 45,643 | 0.1640 s |

All three are small compared with the ticker page. Tool A's payload is table-dominated (107,808
table bytes), which is expected for its 61-name analytical grid.

## Request-path audit

### Diff and static evidence

- Added-line scan across all 44 changed `golden_vector/serve` files since `c7e90db` found no new
  `compute_*`, `execute_*`, fetch, persist, Parquet/CSV write, subprocess, portfolio mutation, or
  manual-store mutation call. The only matches were persisted field names `fetch_status` /
  `fetch_message` and a comment about an existing upsert.
- Tool A (`serve/overview_tool_a.py:89`) and Tool C (`serve/overview_tool_c.py:36`) read resolved
  rows, format cells, and build URLs; they contain no fetch, persistence, or model call.
- Option Trading overview (`serve/overview_option_trading.py:96`) renders the already-built
  overview/signal frames. Its JSON parsing selects a backend-stamped horizon status; the focused
  raw-chain fault test confirms no option-chain scan occurs in the serve path.
- Ticker-page data (`serve/ticker_page/data.py:167`) reads and validates persisted artifacts and
  keeps a generation cache. It does not publish or mutate them.
- `/api/data-status` is a GET at `serve/workspace.py:184`. Its builder reads the latest successful
  manifest and refresh status (`serve/data_status.py:71-72`) and formats completed market-close
  age (`serve/data_status.py:185`); it performs no market-data fetch or analytical rebuild.

### Explicit mutation boundaries

The workspace still has intentional mutations, but they are not ordinary page reads:

- portfolio lot changes require POST (`serve/workspace.py:249-291`);
- refresh launch requires POST (`serve/workspace.py:307-322`);
- company/reporting/verification/note writes live under the ticker POST branch
  (`serve/workspace.py:703-963`).

These are existing product actions or the explicit refresh endpoint named in scope. GET routes for
Tool A, Tool C, Option Trading, ticker detail, and data status remain read/render-only.

## Verification

Focused request-path/static suite: **19 passed in 2.40 s**. It covered:

- the repository-wide serve analytics-token sweep;
- Tool B, Tool D, ticker Options, Compare, charts, metric-formula, Candidate Finder, and ticker-page
  no-arithmetic guards;
- the fault test forbidding raw option-chain scans on detail requests;
- all data-status tests.

## Release follow-up

After the one final coherent refresh, verify:

1. `gold_response`, `downside_context`, and the other ticker-page artifact states are `OK`;
2. `_DATA_CACHE` retains the generation after the first request;
3. five `/ticker/NEM` requests after one warm-up remain within 10% of **0.3919 s**, or any excess
   is investigated from a fresh profile;
4. response bytes remain near the same-data comparison and any growth above 10% is attributed to
   a named section rather than waived as “more UI.”
