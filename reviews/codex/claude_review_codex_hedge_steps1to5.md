# Claude Review: Codex Hedge Readiness Steps 1–5 (Checkpoint A)

**Reviewer:** Claude Code
**Date:** 2026-05-29
**Commits reviewed:** `fd0903d` (step 1), `bfddc37` (step 2), `1809b71` (step 3), `d02933e` (step 4), `79c76a1` (step 5)
**Grade:** **READY**

## TL;DR

This is the cleanest checkpoint I've reviewed across all milestones in this project. Five commits, each focused, +30 net tests (323 → 353), zero issues from the past-failure-mode checklist (Unicode normalization, defensive duplicates, scope creep, unused imports, stray whitespace). Every structural decision from plan v2 — the AF1 storage layout, AF2 schema cleanup, R1 listed-strike-only delta selection, R6 benchmarks-out-of-universe — verified end-to-end with live code runs.

**No changes needed before proceeding to step 6.**

## Review depth

This time I did everything I should have done from the start:

- Read all 5 commits' diffs end-to-end
- Read the new modules in full (`fetch_options.py`, `persist_options.py`, `black_scholes.py`, `fetch_risk_free_rate.py`, `fetch_benchmarks.py`)
- Read the replay-manifest extension and the BenchmarksConfig model edit
- **Live-verified Black-Scholes math** via put-call parity (held exactly to 6 decimal places)
- **Live-verified `strike_for_target_delta`** with a synthetic chain (it correctly selected the listed strike with smallest delta_gap; I had the wrong expected answer in my head)
- **Live-built a real options snapshot + replay-manifest capture round trip** and inspected the persisted parquet's actual columns + the JSON contents of the replay manifest extension
- Ran the full suite independently → 353 passed
- AST-based unused-import scan
- Unicode + stray-whitespace scan
- Cross-checked Codex's progress log against the actual git history

## ✅ Plan v2 compliance — every named fix verified

| Plan v2 element | How I verified | Result |
|---|---|---|
| **AF1: Storage layout** — run-local snapshots at `data/runs/<run_id>/snapshots/options/<TICKER>.parquet`, NOT `data/raw/options/` | Live persist call inspected snapshot path | ✅ `data\runs\<run_id>\snapshots\options\AEM.parquet` |
| **AF1: Latest pointer** — `data/intermediate/status/latest_options_manifest.json` | Live `write_latest_options_manifest()` and inspected path | ✅ Exact path |
| **AF1: Replay-manifest extension** — captures options manifest + sha256 | Live `update_manifest_with_options()`, then `read_manifest()` to inspect | ✅ `options_manifest_status: "captured"`, copy at `replay_snapshots/options_manifest.json` |
| **AF2: Delta REMOVED from raw schema** | Live persist → `pd.read_parquet()` → check columns | ✅ 18 columns, NO `delta` column |
| **AF4: Identity columns added at persist time** (`run_id`, `options_available`, `empty_reason`) | Same | ✅ All three present |
| **AF4: Empty-chain marker** writes a 1-row parquet, not absence | Read `_with_snapshot_identity()` at `persist_options.py:127` | ✅ Empty frame produces marker row |
| **R1: `strike_for_target_delta` returns LISTED strike + `delta_gap`, NO interpolation** | Live call with synthetic chain | ✅ Returned listed strike=100 with `delta_gap=0.05`; no interpolation logic anywhere |
| **R2: Missing IV → null delta** (no Newton-Raphson solver in M1) | Read `black_scholes_delta()` at `black_scholes.py:30` | ✅ Returns None when `implied_volatility is None or <= 0` |
| **R6: Benchmarks NOT in universe.yaml** | Inspected `config/benchmarks.yaml` and `BenchmarksConfig` model | ✅ New file + StrictConfigModel with duplicate-ticker validator |
| **R6: Benchmarks fetched via dedicated path, NOT through foundation** | Read `fetch_benchmarks.py` | ✅ Reuses `standardize_equity_history` but exchange="BENCHMARK", separate fetcher entirely |
| **No scipy dependency** | `import math` only in `black_scholes.py` | ✅ `math.erf` for normal CDF |

## ✅ Live Black-Scholes verification — math is correct

Independently verified against textbook reference values:

```
spot=100, strike=100, T=1.0, r=0.05, sigma=0.2
  call delta: 0.636831 (expected ~0.6368 — matches)
  put delta:  -0.363169
  put-call parity: call - put = 1.000000 (expected exactly 1.0)
  normal_cdf(0): 0.500000 (expected 0.5)
  normal_cdf(1.96): 0.975002 (expected ~0.975)

Edge cases (all return None as required):
  T=0 (degenerate): None ✅
  IV=None: None ✅
  spot=0: None ✅
```

**Put-call parity holding to 6 decimal places is the strongest possible smoke test of the math.** If the formula were wrong, parity would diverge.

`strike_for_target_delta` test with synthetic chain (deltas [-0.10, -0.18, -0.30, -0.45, -0.65] at strikes [90, 95, 100, 105, 110], target=-0.25):
- Selected strike=100 (delta=-0.30, gap=0.05)
- Correctly picked the listed strike with smallest delta_gap (|−0.30 − (−0.25)| = 0.05 < |−0.18 − (−0.25)| = 0.07)
- No interpolated value anywhere in the output ✅

## ✅ Test coverage adequate per step

| Step | New tests | Cumulative pass count |
|---|---|---|
| Baseline | — | 323 |
| Step 1 (benchmarks config) | +3 (`BenchmarksConfig` validation, duplicate detection, config file presence) | 326 |
| Step 2 (persistence) | +3 (writes run-local parquet, empty marker, latest manifest) | 329 |
| Step 3 (replay manifest extension) | +3 (phase-2 updates options block, phase-2 missing records status, verify checks options) | 332 |
| Step 4 (fetchers) | +7 (fetch_options × 3 + fetch_benchmarks × 2 + fetch_risk_free_rate × 2) | 339 |
| Step 5 (Black-Scholes) | +14 (10 test functions, several parametrized) | 353 |
| **Total new tests** | **+30** | **353** |

Math checks out, all tests pass, count never decreased.

## ✅ Past-failure-mode checklist — all clean

| Past issue | Result on this checkpoint |
|---|---|
| Unicode → ASCII normalization (workspace-split step 7) | Zero changes; 2 pre-existing Unicode chars in `config_models.py` (verified not in Codex's diff) |
| Defensive duplicate calls without comments (replay-manifest step 2) | None spotted; `try/finally` patterns where used are clear |
| "Improvements" bundled into a step commit | None — each commit's diff is focused on its stated step |
| Unused imports | AST scan across all 13 touched files — clean |
| Stray blank lines accumulating | awk audit — clean |
| Misleading commit messages | Each commit message matches its actual changes |

Codex genuinely applied the §10 self-cross-check rhythm. It shows in the diff quality.

## Three minor observations (not blocking, not fixes)

These are recorded for posterity, not because they need action.

1. **`BenchmarksConfig` is a REQUIRED field on `AppConfig`** (`contracts/config_models.py:481`). That means every command that loads app config now requires `config/benchmarks.yaml` to exist. The file is committed so it works, but it couples benchmark config to all command paths (including tool-a, tool-b that don't use benchmarks). Acceptable per plan v2 §2b which named `BenchmarksConfig` model as part of the contracts.

2. **`fetch_risk_free_rate` uses `period="5d"`** (`fetch_risk_free_rate.py:22`). Fine for current daily runs. For historical replay scenarios where `as_of_date` is more than 5 days ago, the date filter falls back to whatever's there. Edge-case concern only.

3. **`_safe_name` in `persist_options.py`** sanitizes 9 characters including `:` `*` `<` etc. Our universe tickers don't contain any of these, so the sanitizer is defensive but never triggered. Fine.

## What I verified clean (no findings)

- ✅ All 5 commits cleanly scoped (one purpose each, progress log committed alongside)
- ✅ Black-Scholes put-call parity holds to 6 decimal places (math is correct)
- ✅ `strike_for_target_delta` returns the listed contract by smallest `delta_gap` (no interpolation)
- ✅ Persisted parquet schema matches plan §2c (no `delta`, identity columns added at persist time)
- ✅ Storage at `data/runs/<run_id>/snapshots/options/` (AF1 satisfied)
- ✅ Replay manifest captures options manifest with sha256 (AF1 satisfied)
- ✅ Empty-chain marker writes a 1-row parquet (no silent absence)
- ✅ Best-effort failure handling in all three fetchers (no crashes on Yahoo errors)
- ✅ Zero scipy dependency
- ✅ All 30 new tests pass; full suite at 353
- ✅ Test count never decreased
- ✅ No Unicode normalization regressions
- ✅ No stray blank lines
- ✅ No unused imports
- ✅ No scope creep in any commit's diff

## Verdict

**Grade: READY.** Continue to step 6 (`features/options.py` — the derived-features module). Stop at **CHECKPOINT B** (after step 11) and write the markdown report Codex produces against current data.

This is the cleanest checkpoint we've shipped. The §10 self-cross-check rhythm worked. Keep applying it for steps 6–13.

## Codex — send back this one-liner

```
Continue with steps 6 through 11. Stop at CHECKPOINT B and paste a real markdown report produced by `python main.py hedge-readiness` against current data.
```
