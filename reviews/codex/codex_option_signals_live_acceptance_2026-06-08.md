# Option Signals Live Market-Hours Acceptance - 2026-06-08

## Result

Live market-hours refresh succeeded.

- Command: `python main.py market-hours-refresh`
- Guard result: `RUN - 11:28 ET is inside market hours`
- Parent refresh id: `20260608T152845Z-refresh-3f75ec4a`
- Model state: `COMPLETE`
- Refresh alignment: `OK`
- Option artifact source run: `20260608T153040Z-option-artifacts-08f50478`

## Artifact Checks

Persisted artifacts resolved through the current model-state manifest:

| Artifact | Rows | Schema |
|---|---:|---:|
| `option_signal_summary` | 62 | 2 |
| `option_skew_curve_points` | 432 | 2 |
| `option_oi_strike_points` | 559 | 2 |
| `option_signal_history_points` | 10 | 2 |
| `option_candidate_slots` | 288 | 2 |
| `option_trading_overview` | 24 | 2 |

Signal summary distribution:

| Field | Distribution |
|---|---|
| `data_quality_label` | `SPARSE` 39, `OK` 10, `STALE_QUOTES` 8, `LOW_LIQUIDITY` 5 |
| `direction_label` | `UNAVAILABLE` 43, `NEUTRAL` 10, `DOWNSIDE` 8, `UPSIDE` 1 |
| `activity_label` | `N/A` 43, `QUIET` 12, `NO_BULLISH_CONFIRMATION` 5, `CONFIRMS_DOWNSIDE` 1, `CONFIRMS_UPSIDE` 1 |
| `cost_label` | `LIMITED_HISTORY` 62 |

Benchmarks published correctly:

| Ticker | Data quality | Direction | Candidate | Activity | 60d skew |
|---|---|---|---|---|---:|
| GDX | `OK` | `NEUTRAL` | `NEUTRAL` | `QUIET` | -2.9 vol pts absolute |
| GDXJ | `OK` | `NEUTRAL` | `UPSIDE` | `NO_BULLISH_CONFIRMATION` | -3.2 vol pts absolute |

Example single-name rows that populated with real values:

| Ticker | Quality | Direction | Activity | 60d residual | Coverage | Contracts |
|---|---|---|---|---:|---:|---:|
| CDE | `OK` | `DOWNSIDE` | `QUIET` | +8.7 vol pts | 100% | 15 |
| B | `OK` | `DOWNSIDE` | `QUIET` | +5.7 vol pts | 100% | 43 |
| NEM | `OK` | `NEUTRAL` | `QUIET` | +0.9 vol pts | 100% | 27 |
| TXG | `LOW_LIQUIDITY` | `UPSIDE` | `CONFIRMS_UPSIDE` | -9.2 vol pts | 75% | 4 |

Expected first-live-run behavior mostly appeared:

- `IV-rank` is unavailable / `LIMITED_HISTORY` because clean signal history starts now.
- `OI-change` was valid for several rows because this workspace already had prior cached option snapshots. That differs from a truly empty first run, but is not a bug.

## Workspace Render Checks

Rendered through the WSGI workspace app:

| Route | Status | Result |
|---|---|---|
| `/option-trading` | `200 OK` | Overview rendered and consumed option-signal filters/columns. |
| `/ticker/AEM?lens=option-trading` | `200 OK` | Signal card rendered; live skew table rendered; no stale-schema or missing-snapshot page. |
| `/ticker/GDX?lens=option-trading` | `200 OK` | Benchmark signal card rendered with sector skew. |

## Findings To Tune Before Calling This Fully Decision-Ready

1. **AEM has live contracts but no 60d headline direction.** AEM has `data_quality_label=OK`, 45 signal-area contracts, 98% signal-area quote coverage, and populated 90d/120d skews, but `iv_skew_60d` is null. The signal headline therefore says `UNAVAILABLE`. The skew-curve artifact has real 60d put/call IV points, so the issue is not missing option data; it is the headline's dependence on the precomputed `iv_skew_60d` summary field. Recommended fix: choose the best available liquid signal horizon for the headline, or compute headline skew directly from the signal-area 25-delta points instead of only `options_features.iv_skew_60d`.

2. **Most single-name rows still fail closed.** This may be economically correct for illiquid gold-miner options, but the user experience should make it explicit. Current counts are 39 `SPARSE` and 43 `UNAVAILABLE` direction labels out of 62 rows. Recommended fix: show coverage counts prominently, default the overview to signal-ready rows, and/or separate "no usable option signal" names from the actual signal candidates.

3. **IV/RV reads look numerically suspect.** Several rows show `iv_rv_ratio` near `0.00x` despite plausible listed IVs. Cost is currently `LIMITED_HISTORY`, so it is not driving labels yet, but the displayed reason says things like `IV/RV is 0.00x realized`. Recommended fix: audit IV/RV units before trusting the Cost lane.

4. **OI-by-strike is persisted but not visibly rendered as a chart/section.** The `option_oi_strike_points` artifact has 559 rows, and AEM has real strike-level OI/volume rows, but the detail page only renders the signal card and name-vs-sector skew table. Recommended fix: add the OI-by-strike visualization or table promised by the plan.

5. **History store only has 10 rows after this publish.** That is expected because the retained clean history starts now. Keep the scheduler running before using IV-rank as a real signal.

## Bottom Line

The live market-hours publish worked: benchmark rows did not fail-close, artifacts persisted with schema v2, and the workspace rendered real signal-card data. The signal layer is now operational, but the live acceptance run exposed practical tuning work before the UI is good enough for decision use: headline horizon fallback/direct skew computation, clearer sparse coverage UX, IV/RV unit audit, and rendering the OI-by-strike artifact.
