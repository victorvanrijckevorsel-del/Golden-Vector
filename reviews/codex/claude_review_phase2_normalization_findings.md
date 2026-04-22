# Claude Code Review — Phase 2 Normalization Findings

**Reviewer**: Claude Code
**Date**: 2026-04-22
**Target**: Phase 2 normalization layer on branch `dev-vic`
**Cross-checked against**: `AGENTS.md`, `CLAUDE.md`, `golden_vector_master_plan.md`, `claude-python-rebuild-spec-gold-v1.md`, `codex-full-briefing.md`
**Mode**: Read-only. Tests executed. No code changes.

**Test results**: 31 passed, 4 failed. The 4 failures are real bugs documented below.

---

## 1. Findings

### P0-1: Market snapshot normalization crashes on non-USD tickers — column name collision

**Files**: [market_snapshot.py:44-52](golden_vector/normalize/market_snapshot.py#L44-L52), [calendar.py:42-48](golden_vector/normalize/calendar.py#L42-L48)

**What happens**: When `normalize_market_snapshots_to_usd` processes a non-USD snapshot, it calls `merge_fx_asof`. The snapshot DataFrame already contains a column `fx_rate_to_usd` (from the `MarketSnapshot` data model, set to `None`). The FX lookup also has a column `fx_rate_to_usd`. Pandas `merge_asof` resolves this collision by renaming both to `fx_rate_to_usd_x` and `fx_rate_to_usd_y`. After the merge, the code at line 52 tries to access `normalized["fx_rate_to_usd"]` — which no longer exists.

**3 tests fail because of this**:
- `test_normalize_market_snapshots_converts_non_usd_and_derives_market_cap`
- `test_normalize_market_snapshots_flags_missing_fx`
- `test_normalize_market_snapshots_flags_invalid_share_price`

**Why it matters**: This is a crash, not a silent error. Tool B cannot normalize any non-USD market snapshot. Since the universe includes CAD, GBP, AUD, ZAR, and SEK tickers, this blocks Tool B for the majority of the universe.

**Root cause**: The equity normalization path in `prices_usd.py` doesn't have this bug because the raw equity frame doesn't have an `fx_rate_to_usd` column — it only gets added by the merge. But the `MarketSnapshot` model includes `fx_rate_to_usd` as an input field (since it might come pre-populated from the API), creating the collision.

**What should change**: Either:
- (a) Drop the `fx_rate_to_usd` column from the snapshot frame before calling `merge_fx_asof`, then use the merged result. Or:
- (b) Rename the pre-existing column before the merge (e.g., `fx_rate_to_usd_input`) and use the merged FX rate as canonical. Or:
- (c) In `merge_fx_asof`, add `suffixes=("_input", "")` to `merge_asof` so the FX lookup column keeps the clean name.

Option (a) is simplest. The input `fx_rate_to_usd` on `MarketSnapshot` is always `None` at this point anyway (it gets populated by the normalization itself).

---

### P1-1: `RunContext.write_json` stores absolute paths in artifacts — test assertion fails

**File**: [run_context.py:63-64](golden_vector/app/run_context.py#L63-L64)

**What happens**: `self.artifacts.append(target.name)` stores just the filename (e.g., `config_summary.json`). But the test at [test_run_context.py:40](tests/test_run_context.py#L40) asserts `"config_summary.json" in metadata["artifacts"]`. The test is failing, which means the actual stored value is a full path: `data/runs/<run_id>/config_summary.json`.

Looking at the code more carefully: `target = self.run_dir / file_name`, then `target.name` should return just the filename. But the test is seeing the full relative path. This suggests `write_json` was changed at some point to store relative paths instead of just names.

**Test failure**: `test_run_context_writes_metadata_and_artifacts` — asserts `config_summary.json` but finds a full path in the artifacts list.

**Why it matters**: This is a test/code mismatch. Either the test expectation is wrong or the artifact storage changed without updating the test. The audit trail still works — the artifact path is just stored differently than the test expects. But a failing test is a failing test.

**What should change**: Align the test with the actual behavior. If `artifacts` stores relative paths, update the assertion. If it should store filenames only, fix `write_json`.

---

### P2-1: FX forward-fill has no staleness limit — a months-old FX rate could be used silently

**Files**: [calendar.py:42-48](golden_vector/normalize/calendar.py#L42-L48)

**What the code does**: `merge_asof` with `direction="backward"` — for each equity date, it picks the most recent FX rate on or before that date. There's no maximum lookback window.

**Why it matters**: If FX data has a gap (e.g., the last available CAD/USD rate is from 3 months ago), the normalization will silently use a 3-month-old rate for all subsequent dates. The `normalization_status` will be `"OK"` because an FX rate *was* found — it's just stale.

Codex's own review flagged this as a residual risk: "The FX alignment rule currently forward-fills with no explicit staleness threshold."

**What should change**: Add a configurable staleness threshold (e.g., max 5 trading days). If the FX rate used is older than the threshold, set `normalization_status` to `"STALE_FX"` instead of `"OK"`. This doesn't need to block normalization — just flag it for downstream QA. The threshold could live in `config/qa.yaml`.

---

### P2-2: `_currency_from_equity_frame` returns `"USD"` for empty frames — misleading default

**File**: [prices_usd.py:108-110](golden_vector/normalize/prices_usd.py#L108-L110)

**What the code does**: If the equity frame is empty, returns `"USD"` as the currency. This is used by `normalize_equity_histories_to_usd` (line 46) to look up the FX history: `fx_histories.get(_currency_from_equity_frame(frame), pd.DataFrame())`.

**Why it matters**: For an empty frame, the caller will look up `fx_histories["USD"]`, which probably doesn't exist (USD tickers don't need FX). The result is an empty FX history passed to `normalize_equity_history_to_usd`, which returns an empty DataFrame — so no actual bug occurs. But the logic is misleading: the function claims the currency is "USD" when it's actually unknown.

**What should change**: Return `None` or raise when the frame is empty, rather than defaulting to "USD". The caller at line 46 already handles empty frames gracefully (the normalization produces an empty result), so this is about code clarity, not a runtime bug.

---

### P2-3: `_multiply_if_present` is duplicated across two modules

**Files**: [prices_usd.py:135-136](golden_vector/normalize/prices_usd.py#L135-L136) and [market_snapshot.py:86-87](golden_vector/normalize/market_snapshot.py#L86-L87)

Also: `_missing_or_non_positive` is duplicated across [prices_usd.py:139-145](golden_vector/normalize/prices_usd.py#L139-L145), [market_snapshot.py:90-96](golden_vector/normalize/market_snapshot.py#L90-L96), and [raw_quality.py:247-253](golden_vector/qa/raw_quality.py#L247-L253) — three copies.

**Why it matters**: If the behavior of either function needs to change (e.g., handling `inf` values), all copies must be updated. As the codebase grows, this becomes a maintenance risk.

**What should change**: Move both to a shared utility module (e.g., `golden_vector/normalize/utils.py` or `golden_vector/app/utils.py`).

---

### P2-4: No test for multi-day equity history with mixed FX availability

**File**: `tests/test_prices_usd.py`

**What's tested**: Single-row equity frames with exact-date FX, backward-fill FX, missing FX, missing return basis, and mixed currencies. All single-row tests.

**What's missing**: A multi-row test where some dates have FX and others don't. For example: 5 equity dates, FX available for 3 of them. This would test that `normalization_status` is set correctly per-row (some `"OK"`, some `"MISSING_FX"`) within a single ticker's history.

**Why it matters**: The real data will have gaps. A single-row test can't catch bugs in per-row status assignment when batch-processing a full time series.

**What should change**: Add a multi-row test with partial FX coverage and verify per-row statuses.

---

### P3-1: `normalize_equity_histories_to_usd` silently skips tickers with unknown currencies

**File**: [prices_usd.py:43-48](golden_vector/normalize/prices_usd.py#L43-L48)

**What the code does**: For each ticker, it calls `fx_histories.get(_currency_from_equity_frame(frame), pd.DataFrame())`. If the currency isn't in `fx_histories`, it passes an empty DataFrame as the FX history. This results in all rows getting `MISSING_FX` status.

**Why it matters**: This is actually correct behavior — the downstream QA should catch tickers with all-MISSING_FX rows. But there's no log message or warning when a ticker's currency has no FX history at all. The failure is silent until QA runs.

**What should change**: Add a `logger.warning` when a ticker's currency has no FX history in the provided dict. Not a status change — just observability.

---

### P3-2: `MarketSnapshot` model allows pre-populated `share_price_usd` and `market_cap_usd`

**File**: [data_models.py:51-61](golden_vector/contracts/data_models.py#L51-L61)

**What the code does**: Both fields are `float | None`. The normalization code at [market_snapshot.py:54-59](golden_vector/normalize/market_snapshot.py#L54-L59) uses a `.where` pattern: it keeps the existing `market_cap_usd` if already populated, otherwise derives it from `share_price_usd * shares_outstanding`.

**Why it matters**: If a `MarketSnapshot` arrives with a pre-populated `market_cap_usd` from the API, the normalization will keep it even if it was computed in a different currency or at a different FX rate. This could break the "all math in USD" guarantee if the API-provided market cap uses a different rate than the normalization layer.

**What should change**: Document the policy: either always derive `market_cap_usd` from `share_price_usd * shares_outstanding` (ignoring API value), or always trust the API value when present. Currently the behavior is "trust API if present, derive if not" — which should be an explicit decision, not an implicit fallback.

---

### P3-3: Equity normalization tests don't verify `return_basis_local` fallback logic

**File**: `tests/test_prices_usd.py`

**What the code does at** [prices_usd.py:60-63](golden_vector/normalize/prices_usd.py#L60-L63): `return_basis_local` is set to `adj_close_local` if available, otherwise falls back to `close_local`. This is the foundation for Tool A's return calculations.

**What's tested**: The tests provide both `adj_close_local` and `close_local` in every test case. No test verifies the fallback: what happens when `adj_close_local` is `None` but `close_local` is present? Does `return_basis_local` correctly fall back to `close_local`?

**What should change**: Add a test where `adj_close_local = None` and `close_local = 10.0`, and verify `return_basis_local = 10.0` and `return_basis_usd = 10.0 * fx_rate`.

---

## 2. Residual Risks

| Risk | Likelihood | Impact | Notes |
|------|-----------|--------|-------|
| P0-1 column collision blocks all non-USD Tool B normalization | Certain | High | Bug confirmed by test failure. Must fix before wiring into pipeline. |
| Stale FX rates used silently for long gaps | Medium | High | No staleness limit. Fine for daily data with small gaps, dangerous for multi-week gaps. |
| `market_cap_usd` from API might use different FX than normalization layer | Low | Medium | Only matters if yfinance provides market cap in a different currency. Needs policy decision. |
| Multi-row normalization edge cases untested | Medium | Medium | Single-row tests pass, but batch behavior with partial coverage is untested. |

---

## 3. Final Verdict

**Verdict: `NOT READY`**

The normalization layer has one P0 bug that crashes on non-USD market snapshots (3 test failures), and one P1 test failure in the run context. These must be fixed before this layer is safe to wire into the pipeline.

The core equity normalization path (`prices_usd.py`) is well-designed and its tests pass cleanly. The mixed-currency protection is correctly implemented — it fails fast with a clear error. The FX alignment via `merge_asof` with backward fill is a sound approach. The `return_basis_local` fallback (adj_close → close) is the right design for handling Yahoo's adjusted-close behavior.

**To reach READY**:

1. **Fix P0-1**: Resolve the `fx_rate_to_usd` column collision in `market_snapshot.py` before the merge — drop or rename the pre-existing column. Verify all 3 snapshot tests pass.
2. **Fix P1-1**: Align `test_run_context.py` assertion with actual artifact storage behavior.
3. After those two fixes, re-run all 35 tests — expect 35/35 passing.

The P2 findings (stale FX, misleading default, code duplication, missing multi-row test) should be addressed before Phase 3 but don't block fixing and re-testing the normalization layer.
