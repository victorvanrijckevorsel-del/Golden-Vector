# Live Smoke Report - 2026-04-22

This report captures the first meaningful live-data smoke pass on the rebuilt Golden Vector engine.

## Scope

This pass covered:

1. repo-local Python environment setup
2. live `foundation` run against Yahoo data
3. live `tool-a` run against Yahoo data
4. first real Tool B starter-data import from the screening workbook
5. live `tool-b` run against real manual inputs plus live market snapshots
6. first real live `combined` run
7. hardening fixes required by real output behavior
8. full regression test run after those fixes

## Environment Result

A repo-local virtual environment now exists at:

- `venv/`

Dependencies were installed from:

- [requirements.txt](C:/Users/Emanuel/code/Golden-Vector/requirements.txt)

This removes the previous blocker where live runs depended on a partially configured global Python install.

## Live Foundation Result

Run:

- `20260422T161500Z-foundation-07976c7d`

Outcome:

- overall status: `WARN`
- raw QA: `PASS`
- normalization QA: `WARN`

Main real-world finding:

- `DPM.TO` has incomplete FX-normalized coverage because Yahoo did not provide enough matching CADUSD history for the full equity history window.

Concrete normalization warning:

- `DPM.TO`: `5674 of 7860` rows normalized successfully
- missing FX rows: `2186`

What this means:

- the shared backbone works on live data
- the warning is honest and non-blocking
- the data-quality gate is doing the right thing by showing the coverage gap instead of hiding it

## Live Tool A Result

Latest successful runs:

- original live proof: `20260422T165851Z-tool-a-66e61783`
- post-optimization validation: `20260422T180603Z-tool-a-959a6bc1`

Outcome:

- overall status: `WARN`
- warning source: inherited normalization warning from `DPM.TO`
- Tool A output status: `PASS`
- horizon QA: `PASS`

Key output volumes:

- horizon rows: `463815`
- pass horizon rows: `433788`
- fail horizon rows: `30027`
- Tool A output rows: `42165`
- score-eligible Tool A rows: `30756`
- ranked Tool A rows: `30756`

Performance result:

- earlier live Tool A runtime: about `20 minutes`
- post-refactor live Tool A runtime: about `4 minutes 47 seconds`

## Tool A Snapshot

Latest `as_of_date`:

- `2026-04-22`

Latest ranked snapshot:

| Rank | Ticker | Tool A score | Regime | Core delta |
|---|---|---:|---|---:|
| 1 | `DPM.TO` | 87.9449 | `STABLE_BETA` | 3.5769 |
| 2 | `KGC` | 87.5280 | `STABLE_BETA` | 3.1767 |
| 3 | `FRES.L` | 87.2814 | `CONVEX_STABLE` | 4.5174 |
| 4 | `AEM` | 75.0410 | `STABLE_BETA` | 1.9483 |
| 5 | `NEM` | 68.6080 | `DECAYING` | 1.6432 |
| 6 | `FNV` | 55.8577 | `DECAYING` | 1.1414 |
| 7 | `BTG` | 53.0401 | `DECAYING` | 1.0997 |
| 8 | `GOLD` | 27.4279 | `LOW_LINK` | 0.4337 |

## Live Tool B Result

Latest successful run:

- `20260422T173735Z-tool-b-e158c29c`

Outcome:

- overall status: `WARN`
- Tool B output status: `WARN`
- Tool B output rows: `8`
- ranked Tool B rows: `4`
- incomplete Tool B rows: `4`

Why the warning exists:

- only the first four manual screening rows were populated with real source data
- the remaining four Tool B names stay honestly `INCOMPLETE`

Starter names populated from the screening workbook:

- `NEM`
- `GOLD` (mapped from workbook ticker `B` for Barrick)
- `AEM`
- `KGC`

Latest Tool B snapshot:

| Rank | Ticker | Verdict | Confidence | Tool B score | Layer 1 | Forward P/E |
|---|---|---|---|---:|---|---:|
| 1 | `GOLD` | `WATCHLIST` | `ESTIMATED` | 72.0 | `FAIL` | 0.2981 |
| 2 | `AEM` | `SCREEN_OUT` | `ESTIMATED` | 44.0 | `FAIL` | 16.5114 |
| 2 | `KGC` | `SCREEN_OUT` | `ESTIMATED` | 44.0 | `FAIL` | 10.5081 |
| 2 | `NEM` | `SCREEN_OUT` | `ESTIMATED` | 44.0 | `FAIL` | 12.8378 |

## Live Combined Result

Latest successful run:

- `20260422T181107Z-combined-3616e48a`

Outcome:

- overall status: `WARN`
- combined output status: `WARN`
- full combined rows: `42165`
- complete joined rows: `4`
- partial joined rows: `42161`
- ranked combined rows: `4`

What this means:

- the combined engine works end to end on live data
- only the latest four Tool B-populated names are complete combined rows
- older Tool A history remains partial until more Tool B manual inputs are populated

Latest combined snapshot:

| Rank | Ticker | Combined verdict | Combined score | Tool A score | Tool B score | Tool B verdict |
|---|---|---|---:|---:|---:|---|
| 1 | `KGC` | `GOLD_BETA_ONLY` | 65.7640 | 87.5280 | 44.0 | `SCREEN_OUT` |
| 2 | `AEM` | `GOLD_BETA_ONLY` | 59.5205 | 75.0410 | 44.0 | `SCREEN_OUT` |
| 3 | `NEM` | `GOLD_BETA_ONLY` | 56.3040 | 68.6080 | 44.0 | `SCREEN_OUT` |
| 4 | `GOLD` | `REVIEW` | 49.7139 | 27.4279 | 72.0 | `WATCHLIST` |

## Hardening Done During This Pass

### 1. Repo-local runtime was fixed

What changed:

- created `venv/`
- installed dependencies from `requirements.txt`

Why it matters:

- live runs and tests are now reproducible from the repo

### 2. Horizon-return engine was optimized

What changed:

- replaced the slow row-by-row DataFrame lookup pattern in [returns.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/returns.py) with indexed and vectorized horizon evaluation

Why it matters:

- live `tool-a` now completes on real data instead of effectively hanging

### 3. Tool A scoring gate was corrected

What changed:

- [labels.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/labels.py) now treats real coverage failures differently from analytically excluded horizons like near-zero gold-return windows

Why it matters:

- the latest Tool A snapshot now produces meaningful ranks instead of leaving all names unscored

### 4. Gamma runtime warning was removed

What changed:

- [gamma.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/gamma.py) now returns `0.0` when `gold_delta` is constant, instead of relying on a correlation call that emits runtime warnings

Why it matters:

- live output is cleaner and more deterministic

### 5. Tool A profile construction was vectorized

What changed:

- [model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py) no longer loops group-by-group through every `(ticker, as_of_date)` slice
- the core counts, median delta, MAD-based stability, and gamma statistics are now built from grouped aggregates
- [model/scoring.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/scoring.py) now ranks eligible rows in one grouped pass instead of looping date by date

Why it matters:

- live Tool A became fast enough to make the full combined run practical

### 6. Tool B starter inputs were populated from the source workbook

What changed:

- [company_inputs.csv](C:/Users/Emanuel/code/Golden-Vector/data/manual/screening/company_inputs.csv) now has real starter values for `NEM`, `GOLD`, `AEM`, and `KGC`
- [source_verification.csv](C:/Users/Emanuel/code/Golden-Vector/data/manual/screening/source_verification.csv) now records what is verified versus estimated for those starter rows
- [reporting_calendar.csv](C:/Users/Emanuel/code/Golden-Vector/data/manual/screening/reporting_calendar.csv) now has real next reporting dates for those starter rows

Why it matters:

- Tool B and Combined can now produce the first real merged output instead of being almost entirely `INCOMPLETE`

## Test Status After Hardening

Full suite result:

- `130 passed`

Command used:

```powershell
.\venv\Scripts\python.exe -m pytest
```

## Remaining Real-World Gaps

1. Tool B manual coverage is still thin
   - only `NEM`, `GOLD`, `AEM`, and `KGC` have real populated manual rows so far
   - `BTG`, `FNV`, `DPM.TO`, and `FRES.L` still remain `INCOMPLETE`

2. Combined coverage is still mostly partial
   - the combined pipeline works, but only the latest four names can currently rank as true complete rows

3. Tool A is much faster but not yet optimized for repeated scenario sweeps
   - the main blocker is solved, but caching or reuse of validated intermediate outputs would still help for repeated exploration

## Best Next Step

The most valuable next milestone is:

1. expand real Tool B manual coverage to the remaining names
   - next suggested names: `BTG`, `FNV`, `DPM.TO`, `FRES.L`
2. rerun live `tool-b` and `combined`
3. improve explainability on the published outputs
   - short reason strings for why a name ranked where it did
4. consider lightweight caching or reuse for repeated live scenario runs

That will move the project from "first real merged product output" to "broader live coverage and more decision-ready outputs."
