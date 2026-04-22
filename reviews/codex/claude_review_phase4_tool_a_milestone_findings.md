# Claude Code Review — Tool A Phase 4 Milestone Findings

**Reviewer**: Claude Code
**Date**: 2026-04-22
**Target**: Tool A end-to-end path on branch `dev-vic`
**Cross-checked against**: `AGENTS.md`, `CLAUDE.md`, `golden_vector_master_plan.md`, `claude-python-rebuild-spec-gold-v1.md`, `codex-full-briefing.md`, Codex's own Phase 4 review
**Mode**: Read-only. Tests executed. No code changes.

**Test results**: 65/65 tests pass. All Phase 2 bugs from the prior review have been fixed (market snapshot column collision resolved, run context artifact test fixed, multi-row partial FX test added, adj_close fallback test added).

---

## 1. Findings

### P2-1: Tool A score penalizes negative deltas but does not differentiate inverse-gold names in ranking output

**Files**: [delta.py:33-36](golden_vector/features/delta.py#L33-L36), [labels.py:33-34](golden_vector/model/labels.py#L33-L34), [scoring.py:10-19](golden_vector/model/scoring.py#L10-L19)

**What the code does**: `compute_delta_component_score` returns `0.0` for `core_delta <= 0`. `determine_score_eligibility` returns `(False, "NON_POSITIVE_CORE_DELTA")` for negative deltas. `compute_tool_a_score` returns `None` when not eligible. `determine_regime_tag` returns `"INVERSE"`.

**Why it matters**: This correctly excludes inverse-gold names from scoring and ranking — they get `score_eligible = False`, `tool_a_rank = None`, `regime_tag = "INVERSE"`. This is the right behavior per the master plan.

However, a user looking at the output table sees inverse names mixed in with insufficient-data names (both unranked, both `score = None`). There's no way to distinguish "this stock moves opposite to gold" from "we don't have enough data" without checking `regime_tag` or `score_eligibility_reason`. This is a UX concern, not a correctness bug.

**What should change**: Consider adding an `inverse_flag: bool` column to the Tool A output, or documenting that `regime_tag = "INVERSE"` is the way to identify these names. Not blocking — P3 if anything — but worth noting for the serve layer.

**Revised severity**: P3.

---

### P2-2: `compute_horizon_returns_for_ticker` iterates every `as_of_date × horizon` combination — O(n×h) per ticker

**File**: [returns.py:46-57](golden_vector/features/returns.py#L46-L57)

**What the code does**: For every date in the overlap frame and every horizon, it calls `_compute_row`. With `period=max` data (potentially 5000+ trading days) and 11 core horizons, this is ~55,000 rows per ticker. For 61 tickers, that's ~3.35 million rows computed one-by-one via `_compute_row` with individual DataFrame lookups.

**Why it matters**: This will be slow on the full 61-ticker universe. Each `_compute_row` call does a `overlap.loc[overlap["date"] == pd.Timestamp(start_date)]` scan. The current test data is tiny (6 dates × 1 horizon) so this isn't visible in tests.

**What should change**: Not a correctness issue. For v1 this may be acceptable if runtime is under a few minutes. If it's too slow on real data, vectorize the return computation using `shift()` for day horizons and a pre-built date-mapping index for month/year horizons. Flag for Phase 8 hardening if needed.

---

### P2-3: `_combine_statuses` treats any unknown status string as `"PASS"`

**File**: [cli.py:643-649](golden_vector/cli.py#L643-L649)

**What the code does**: Checks for `"FAIL"` and `"WARN"`, otherwise returns `"PASS"`. If a stage returns `"NOT_IMPLEMENTED"` or any typo like `"FIAL"`, it would be treated as `"PASS"`.

**Why it matters**: The `run_placeholder` function returns status `"NOT_IMPLEMENTED"`. If `_combine_statuses` ever receives this (it doesn't today, because placeholders return early), it would be treated as PASS. More importantly, any future status values would silently pass.

**What should change**: Add a guard: if any status is not in `{"PASS", "WARN", "FAIL"}`, raise or treat as `"FAIL"`. Defensive, low-effort.

---

### P2-4: No test for gamma proxy with all-identical gold absolute returns

**File**: `tests/` (missing test)

**What the code does at** [gamma.py:24-25](golden_vector/features/gamma.py#L24-L25): If `gold_abs_return.nunique() < 2`, returns `0.0`. This handles the edge case where all gold returns are identical (correlation is undefined).

**What's missing**: No test exercises this path. The existing tests only cover the general case (test_tool_a_pipeline with varied gold returns). A regression test for identical gold returns would protect this branch.

**What should change**: Add a test with identical `gold_return` values across all horizons and verify `gamma_proxy == 0.0`.

---

### P2-5: Tool A ranking is per-`as_of_date` but there's no test with multiple `as_of_date` values

**File**: [scoring.py:37-53](golden_vector/model/scoring.py#L37-L53), `tests/test_tool_a_pipeline.py`

**What the code does**: `rank_tool_a_outputs` groups by `as_of_date` and ranks within each group. The test only uses a single `as_of_date` (`2026-01-31`).

**Why it matters**: With real data, the output will have many `as_of_date` values (one per trading day). The ranking must be independent per date — a stock ranked #1 on Monday shouldn't affect rankings on Tuesday. This logic looks correct in the code but has no test coverage.

**What should change**: Add a test with two `as_of_date` values where the ranking order differs between dates. Verify ranks are computed independently.

---

### P3-1: `determine_regime_tag` uses `scoring_config.stability_thresholds` and `gamma_thresholds` — added since Phase 0

**File**: [labels.py:43-78](golden_vector/model/labels.py#L43-L78), [config/scoring.yaml](config/scoring.yaml)

**What I checked**: The `scoring.yaml` now includes `stability_thresholds` and `gamma_thresholds` (not present in the Phase 0 scaffold). The config model was updated to include `StabilityThresholds` and `GammaThresholds` classes. Tests `test_stability_thresholds_must_be_ordered` and `test_gamma_thresholds_must_be_ordered` validate them.

**Assessment**: Good addition. The thresholds are configurable, validated (weak_max < strong_min, negative_max < positive_min), and used deterministically. Regime tags are pure functions of numeric inputs + config thresholds. This satisfies the hard rule: "no hidden label overrides."

---

### P3-2: `official_scoring_eligible` is correctly gated on `horizon.mode == "core"` — custom horizons cannot leak

**File**: [returns.py:166](golden_vector/features/returns.py#L166)

**What I checked**: In `_compute_row`, the line `"official_scoring_eligible": horizon.mode == "core"` ensures only core horizons can be scoring-eligible. Near-zero gold returns also set this to `False`. The downstream `execute_tool_a_profile_pipeline` filters on `official_scoring_eligible` before computing metrics.

**Assessment**: This is correct and well-tested (`test_compute_horizon_returns_marks_custom_horizons_not_official`). Custom horizons cannot affect official scores.

---

### P3-3: Hard gates are correctly implemented — Codex's P1 fixes verified

**Files**: [cli.py:290-326](golden_vector/cli.py#L290-L326) (raw QA gate, normalization QA gate), [cli.py:336-356](golden_vector/cli.py#L336-L356) (horizon QA gate)

**What I checked**: Three gate tests exist and pass:
- `test_run_tool_a_stops_before_phase3_when_raw_qa_fails` — horizon pipeline is never called
- `test_run_tool_a_stops_before_phase3_when_normalization_qa_fails` — horizon pipeline is never called
- `test_run_tool_a_stops_before_scoring_when_horizon_qa_fails` — profile pipeline is never called

**Assessment**: The gates are strict. No scoring can happen after an upstream failure. This directly addresses the v1 lesson: "no analytics before data governance."

---

### P3-4: `compare-horizons` correctly gates on normalization QA

**File**: [cli.py:507-539](golden_vector/cli.py#L507-L539)

**What I checked**: The `compare-horizons` command checks raw QA, normalization existence, and normalization QA status before computing anything. It logs explicit notes: "Custom horizons are exploratory only and do not change official scores."

**Assessment**: Correct. Exploratory output is properly guarded and explicitly labeled.

---

### P3-5: Tie handling in ranking uses `method="dense"`

**File**: [scoring.py:50-51](golden_vector/model/scoring.py#L50-L51)

**What the code does**: `eligible_scores.rank(method="dense", ascending=False)`. Dense ranking means if two stocks tie at rank 1, the next stock is rank 2 (not 3).

**Why it matters**: This is a reasonable choice for a screening tool — it doesn't inflate rank numbers. But it's not explicitly documented. If the user expects standard competition ranking (1, 1, 3), they'll be surprised.

**What should change**: Document the ranking method in the output or config. No code change needed unless the user prefers a different method.

---

## 2. Residual Risks

| Risk | Likelihood | Impact | Notes |
|------|-----------|--------|-------|
| Performance on full 61-ticker universe with max history | Medium | Medium | ~3.3M rows computed row-by-row. May take minutes. Acceptable for v1 CLI but should be monitored on first real run. |
| Stability score and gamma proxy are meaningful only with sufficient data | Low | Low | Already gated: stability requires ≥2 points, gamma requires ≥2 points with varied gold returns. Insufficient data → `None` → ineligible. |
| `_combine_statuses` could silently pass unknown statuses | Low | Medium | Only matters if new status strings are introduced without updating the function. |
| Regime tags depend on subjective threshold choices | Medium | Low | Thresholds are in config and validated. Calibration will need tuning after real data inspection. Explicitly flagged in master plan as "confirm later." |

---

## 3. Final Verdict

**Verdict: `READY WITH MINOR CHANGES`**

The Tool A implementation is solid. The end-to-end path from shared backbone through horizon returns to metric/scoring/ranking is internally coherent and well-gated. All 65 tests pass. The key architectural properties hold:

- **Mixed-currency protection**: equity frames must contain exactly one currency; USD normalization is enforced before any analytics.
- **Horizon protection**: custom horizons are tagged `mode="custom"` and `official_scoring_eligible=False` at the return computation level. They cannot leak into scoring.
- **Hard gates**: raw QA → normalization QA → horizon QA → scoring. Each gate is tested with a dedicated test that verifies the downstream stage is never reached.
- **Deterministic labels**: all regime tags and score eligibility decisions are pure functions of numeric inputs + config thresholds. No hidden overrides.
- **Audit trail**: every run writes metadata, config summary, QA summaries, and persists horizon metrics and Tool A outputs to Parquet.

The P2 findings are improvement items, not blockers:
- **P2-2** (performance): monitor on first real run, vectorize if needed
- **P2-3** (`_combine_statuses` guard): one-line defensive fix
- **P2-4, P2-5** (missing edge-case tests): add before Phase 8 hardening

This milestone is safe to build on for Tool B (Phase 6) and Combined View (Phase 7).
