# Claude Code Review — Phase 0 Scaffold Findings

**Reviewer**: Claude Code
**Date**: 2026-04-22
**Target**: Phase 0 scaffold on branch `dev-vic`
**Cross-checked against**: `AGENTS.md`, `CLAUDE.md`, `golden_vector_master_plan.md`, `claude-python-rebuild-spec-gold-v1.md`, `codex-full-briefing.md`
**Mode**: Read-only. Tests executed to verify correctness. No code changes.

**Test results**: 8/8 tests pass. `python main.py foundation` runs successfully and produces valid metadata.

---

## 1. Findings

### P2-1: `cli.py` missing from the `golden_vector/` package — lives at top level of `golden_vector/`

**File**: `golden_vector/cli.py`

**What it does**: The CLI module sits directly inside `golden_vector/` rather than inside `golden_vector/app/`. This is fine architecturally, but the master plan's repo structure (Section 4) doesn't list `cli.py` at all. The master plan shows `golden_vector/app/` as the home for application plumbing.

**Why it matters**: Low impact. The placement is reasonable — CLI is the entry point, not internal app plumbing. But someone following the master plan's folder listing wouldn't know where routing lives.

**What should change**: Either move `cli.py` into `golden_vector/app/cli.py`, or update the master plan's repo structure to show `golden_vector/cli.py`. No functional change needed — this is a documentation alignment issue.

---

### P2-2: `UniverseTicker.currency` defaults to `"USD"` — could hide missing currency declarations

**File**: [config_models.py:18](golden_vector/contracts/config_models.py#L18)

**What the code does**: `currency: str = "USD"` — if a ticker entry in `universe.yaml` omits the currency field, it silently defaults to USD.

**Why it matters**: The master plan's hard rule #1 is "No analytics on mixed currencies." The rebuild spec's lesson #1 is "Currency normalization came too late." A ticker with a missing currency that defaults to USD when it's actually GBP or CAD would pass validation silently and produce wrong USD conversions downstream. The FX resolver would skip conversion (thinking it's already USD), and all returns for that ticker would be wrong.

Currently all 8 tickers in `universe.yaml` have explicit `currency` fields, so there's no active bug. But as the universe grows to 61+ tickers, a missing currency field would be silent and dangerous.

**What should change**: Make `currency` required (no default). Force every ticker to explicitly declare its listing currency. This is a one-line change: `currency: str` instead of `currency: str = "USD"`.

---

### P2-3: `UniverseTicker` does not validate currency codes

**File**: [config_models.py:24-27](golden_vector/contracts/config_models.py#L24-L27)

**What the code does**: The `uppercase_codes` validator uppercases `ticker` and `currency`, but doesn't validate that the currency code is a known/supported value.

**Why it matters**: A typo like `currency: UDS` (instead of `USD`) would pass validation. Downstream, the FX resolver would fail to find FX data for "UDS" and the ticker would either crash or silently produce no USD prices. The QA config has `block_on_missing_currency_map: true` which would catch this at runtime, but the error would be confusing ("missing FX for UDS") rather than clear ("unknown currency code UDS in universe config").

**What should change**: Add a validator that checks `currency` against a set of supported codes. At minimum: `{"USD", "CAD", "GBP", "AUD", "ZAR", "EUR", "SEK"}` (covering the known universe currencies). This fails fast at config load time with a clear message.

---

### P2-4: Core horizon format is not validated

**File**: [config_models.py:59-68](golden_vector/contracts/config_models.py#L59-L68)

**What the code does**: `core_horizons: list[str]` with a uniqueness check, but no format validation. Any string passes — `"FOREVER"`, `"5X"`, `"banana"`.

**Why it matters**: The master plan (Section 6) defines a strict grammar for horizons: "positive integer + D, M, or Y." Custom horizons have a `CustomHorizonValidation` model with `allowed_units` and min/max value. But core horizons bypass this entirely — they're just strings. If someone edits `horizons.yaml` and writes `"5d"` (lowercase) or `"1W"` (weeks), it would load without error but fail silently when the horizon parser tries to resolve dates in Phase 3.

**What should change**: Add a `field_validator` for `core_horizons` that verifies each entry matches the pattern `r"^\d+[DMY]$"`. This ensures core horizons follow the same grammar as custom horizons. It also catches case issues early.

---

### P2-5: `ScoreWeights` does not validate that weights sum to 1.0

**File**: [config_models.py:88-91](golden_vector/contracts/config_models.py#L88-L91)

**What the code does**: `core_delta: 0.5`, `stability: 0.3`, `gamma_proxy: 0.2`. No validation that they sum to 1.0.

**Why it matters**: If someone edits `scoring.yaml` and sets weights that sum to 0.7 or 1.3, the composite score would be silently scaled wrong. The score wouldn't be comparable across runs with different weight configs.

**What should change**: Add a `model_validator(mode="after")` that checks `abs(core_delta + stability + gamma_proxy - 1.0) < 1e-9`. Raise if weights don't sum to 1.0.

---

### P2-6: `build_test_paths` helper is duplicated across two test files

**Files**: [test_paths.py:6-19](tests/test_paths.py#L6-L19) and [test_run_context.py:8-21](tests/test_run_context.py#L8-L21)

**What the code does**: Identical `build_test_paths(root)` function copy-pasted in both files.

**Why it matters**: If the `ProjectPaths` fields change (new directory, renamed field), both copies need updating. As tests grow in Phase 1+, this will spread further.

**What should change**: Move to a shared `tests/conftest.py` fixture or a `tests/helpers.py` module.

---

### P3-1: No test for duplicate tickers in universe config

**File**: `tests/test_config_models.py`

**What exists**: Tests for empty tickers, empty horizons, missing peer benchmarks, and unknown keys. No test that duplicate tickers are rejected.

**Why it matters**: The `UniverseConfig.unique_tickers` validator (config_models.py:43-49) exists and should work, but it has no test. If the validator is accidentally removed or broken, nothing catches it.

**What should change**: Add a test that creates a universe with duplicate tickers and asserts `ValidationError` is raised.

---

### P3-2: No test for invalid jurisdiction tier

**File**: `tests/test_config_models.py`

**What exists**: The `valid_tier` validator (config_models.py:29-35) restricts to `{1, 2, 3}`, but no test exercises it.

**What should change**: Add a test with `jurisdiction_tier: 5` and assert rejection.

---

### P3-3: No test for invalid gold price scenarios (negative/zero/duplicate)

**File**: `tests/test_config_models.py`

**What exists**: The `valid_gold_price_scenarios` validator exists but has no test.

**What should change**: Add tests for `gold_price_scenarios: [-100]`, `[0]`, and `[3000, 3000]`.

---

### P3-4: `run_foundation` catches no exceptions — unhandled errors produce a stack trace

**File**: [cli.py:113-158](golden_vector/cli.py#L113-L158)

**What the code does**: `run_foundation` calls `load_app_config` and `RunContext.start` without try/except. If a config file is missing or invalid, the user sees a raw Python traceback.

**Why it matters**: For an engine-first v1 this is acceptable — the error message from Pydantic or FileNotFoundError is informative. But it means the run metadata never gets written on failure (no `status: FAIL` record), which breaks the audit trail for failed runs.

**What should change**: Not blocking for Phase 0 — but worth noting that Phase 1 should wrap the pipeline in a try/except that writes `status: FAIL` to run metadata before re-raising.

---

### P3-5: `data/runs/` will accumulate unbounded run directories

**File**: [run_context.py:42-45](golden_vector/app/run_context.py#L42-L45)

**What the code does**: Every `foundation`/`tool-a`/etc. invocation creates a new timestamped directory under `data/runs/`. No cleanup policy.

**Why it matters**: After many test runs during development, `data/runs/` will have hundreds of directories. Not a v1 problem, but worth noting.

**What should change**: Nothing for now. Could add a `--clean-runs` flag or a TTL-based cleanup later.

---

### P3-6: `data/` directory should be in `.gitignore`

**Files**: repo root

**What exists**: No `.gitignore` was observed in the scaffold. The `data/runs/`, `data/raw/`, etc. directories are created at runtime and will contain Parquet files, run logs, and metadata JSON.

**Why it matters**: Without `.gitignore`, `git add .` (or `git add -A`) would accidentally commit raw market data, run logs, and Parquet files to the repo. This could bloat the repo and potentially commit data that shouldn't be versioned.

**What should change**: Add a `.gitignore` with at minimum: `data/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`.

---

### P3-7: Universe only has 8 tickers — missing 53 from the full 61-ticker universe

**File**: `config/universe.yaml`

**What it has**: NEM, GOLD, AEM, KGC, BTG, FNV, DPM.TO, FRES.L

**Why it matters**: This is a reasonable starter set for testing (includes USD, CAD, and GBP currencies). The full 61-ticker universe doesn't need to be in the scaffold. But it's worth noting that the scaffold only covers 3 of the ~7 currencies in the full universe (no AUD, ZAR, SEK tickers yet). Phase 1 should test with at least one ticker per currency to validate FX handling early.

**What should change**: Nothing for Phase 0. Note for Phase 1: add at least one AUD (e.g., WAF.AX), ZAR (e.g., GFI or HMY), and SEK (WGOLD.ST) ticker before FX testing.

---

## 2. Residual Risks

| Risk | Likelihood | Impact | Notes |
|------|-----------|--------|-------|
| Currency default `"USD"` hides a missing declaration as the universe grows | Medium | High | P2-2 above. Most dangerous silent failure mode in the scaffold. |
| Horizon format not validated until Phase 3 parser is built | Low | Medium | Config loads fine, but a malformed horizon would fail late. |
| No `.gitignore` means accidental data commits during Phase 1 | Medium | Low | Easy to fix, but needs to happen before first real data fetch. |
| Tests don't exercise all validators | Low | Low | Validators exist and look correct on inspection. Missing tests are coverage gaps, not bugs. |

---

## 3. Final Verdict

**Verdict: `READY WITH MINOR CHANGES`**

The scaffold is solid. The architecture is clean: config-driven, Pydantic-validated, with run metadata and audit logging from day one. CLI routing matches the master plan's command set. Data contracts align with the master plan's dataset schemas. All 8 tests pass. The `foundation` command runs end-to-end and produces valid metadata.

The P2 findings are all "silent failure prevention" issues — they won't cause bugs today but create risk as the pipeline grows:

- **Fix before Phase 1**: P2-2 (currency default → make required) and P3-6 (.gitignore). These are the two that could cause real problems during data ingestion work.
- **Fix during Phase 1**: P2-3 (currency code validation), P2-4 (horizon format validation), P2-5 (weight sum validation). These tighten config safety before real data flows through.
- **Fix whenever convenient**: P2-1 (doc alignment), P2-6 (test helper dedup), P3-1 through P3-3 (missing validator tests).

None of these block starting Phase 1 work. The scaffold is a good foundation.
