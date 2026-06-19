# Codex Review - Phase 2 Tool A 2Y/5Y Windows Plan

Date: 2026-06-19

Verdict: **NEEDS CHANGES**

The architecture call is right: keep 2Y/5Y as display windows, not scoring windows. The plan is not yet safe to build because it does not explicitly prevent display-window rows from leaking into Tool A confidence, eligibility counts, and rank-adjacent fields.

## Findings Table

| Severity | Finding | Evidence | Required plan change |
|---|---|---|---|
| P0 | Display rows will leak into scoring-adjacent fields if the plan simply appends 2Y/5Y rows to `structural_window_metrics`. | `golden_vector/model/pipeline.py:382` builds `eligible_frame` from every `ELIGIBLE` window in the group. That frame feeds `eligible_structural_window_count`, `positive_delta_window_count`, `confidence_score`, and `determine_score_eligibility` at `pipeline.py:427-438`. `_compute_confidence_score` then divides by `len(scoring_config.structural_windows)` while counting all eligible rows at `pipeline.py:771-793`. Weighted medians are protected by `weight_map`, but confidence/counts are not. | Add an explicit `scoring_window_ids = set(app_config.scoring.structural_windows)` filter in output assembly. Use a scoring-only frame for all core values, confidence, eligibility, counts, anchor/explanations, and normalization blockers. Use display rows only to populate the new persisted display columns. |
| P1 | The config/status policy for 2Y/5Y is missing. | `ConfidenceThresholds.minimum_observations_for_window()` only supports 6M/12M/3Y and raises for anything else (`golden_vector/contracts/config_models.py:1034-1042`). `compute_structural_window_metrics()` calls that map for every computed window (`golden_vector/model/structural.py:400-409`). `_window_offset()` can handle generic `Y` windows, but the observation policy cannot. | Add a central display-window policy, including minimum observations and regime observations for 2Y/5Y, without adding scoring weights. This is what makes `window_status_5y` meaningful for AAUC.TO and other short-history names. |
| P1 | The touch list is incomplete around contracts and manifest-backed readers. | Live `tool_a_latest.parquet` currently has 59 columns and only 6M/12M/3Y. Live `benchmark_betas_latest.parquet` is schema version 8 and only carries 6M/12M/3Y per-window betas. `portfolio.reader` enforces `BENCHMARK_BETA_COLUMNS` and `PORTFOLIO_SCHEMA_VERSION`. `model_state` records columns automatically but only after a rebuild. | Add `PORTFOLIO_SCHEMA_VERSION` bump for benchmark betas, update `BENCHMARK_BETA_COLUMNS`, and require a current-state manifest smoke/contract check proving `tool_a`, `tool_a_structural_metrics`, and `benchmark_betas` expose the new columns through the manifest-backed path. Tool A has no explicit schema version, so column-contract tests are the guard there. |
| P1 | Serve/detail touch points are broader than `serve/windows.py` plus the detail switcher. | Detail routing/window constants live in `golden_vector/serve/workspace_state.py` (`_STRUCTURAL_WINDOWS`, `_WINDOW_WEEKS`, `_WINDOW_COLORS`) and are imported by charts/detail code. `_WINDOW_WEEKS` would fall back to 52 weeks for 2Y/5Y volatility recomputes if not updated. `golden_vector/model/benchmark_comparison.py` maps only 6M/12M/3Y/CORE. `golden_vector/serve/detail_panels.py:1306` hardcodes the structural window table loop. | Expand the plan to update all window registries and labels in one pass: `serve/windows.py`, `serve/workspace_state.py`, charts, `detail_panels`, `benchmark_comparison`, `format_helpers`, `column_help`, and all fixtures/tests that assume exactly three windows. |
| P2 | Existing overview mute logic needs status-name alignment before relying on it for 5Y scarcity. | `serve/windows.py:72-80` treats `status in ("", "OK")` as reliable, but Tool A output writes `window_status_* = "ELIGIBLE"` for usable windows. Detail volatility suppression correctly checks for `ELIGIBLE`, but the overview reliability helper currently mutes eligible windows too. | Make the plan include a small serve fix/test: `ELIGIBLE` is reliable when R^2/weeks pass, while `LOW_OBSERVATION`, `INELIGIBLE`, missing values, and weak R^2 stay muted/suppressed. |

## Option A vs B Call

**Recommend Option B.** 2Y/5Y should be display-only windows unless Victor explicitly wants to revalidate the Tool A rank.

Why:

- Option A would require new weights, new confidence behavior, new anchor rules, and a rank revalidation. That is too much blast radius for a display request.
- `_build_vectorized_window_data()` and `_window_offset()` are already generic enough for `2Y` and `5Y`; the blocker is config policy, not beta math.
- `model/scoring.py` itself does not read window ids. It scores the already-built core fields.
- The real risk is in `model/pipeline.py`, where core aggregates, confidence, eligibility, and counts are assembled before `model/scoring.py` ranks them.

So Option B is clean only if the implementation creates a hard boundary:

- `structural_windows = ["6M", "12M", "3Y"]` remain the official scoring windows.
- `structural_display_windows = ["2Y", "5Y"]` are computed and persisted.
- Display rows never change `tool_a_score`, `tool_a_rank`, `confidence_score`, `confidence_label`, `score_eligible`, `eligible_structural_window_count`, `positive_delta_window_count`, `anchor_window_id`, or any core beta/delta/gamma/asymmetry field.

## Direct Answers

1. **Is Option B correct and clean?**

Yes, but the current plan is missing the most important implementation guard. `structural.py` can be extended to compute display windows without changing `model/scoring.py`, but `_build_tool_a_outputs()` must filter back to official scoring windows before computing confidence, eligibility, counts, and core fields.

2. **Is the touch list complete?**

No. Add:

- Pipeline scoring-frame filter in `golden_vector/model/pipeline.py`.
- 2Y/5Y observation and regime thresholds in config models and `config/scoring.yaml`.
- `ToolAOutput` and `TOOL_A_OUTPUT_COLUMNS` additive display columns.
- Benchmark betas schema bump and reader tests.
- `model_state` manifest acceptance proving new columns are visible through current-state resolution.
- `model/benchmark_comparison.py` 2Y/5Y suffix/label mappings.
- `serve/workspace_state.py` constants, `_WINDOW_WEEKS`, colors, chart/detail consumers.
- `serve/format_helpers.py` numeric field sets and `serve/column_help.py` text.
- Candidate Finder and Tool C no-change regression tests, because they consume core fields only.
- Live-column parity check: old columns and rank fields remain identical, new display columns are additive.

3. **Is the rank-parity guard right, and where should it live?**

Yes. Put the load-bearing unit test in `tests/test_tool_a_pipeline.py`, because that is where display-window leakage can actually happen. Build outputs from the same synthetic structural metrics twice:

- baseline with 6M/12M/3Y only;
- candidate with extra 2Y/5Y rows appended.

Then rank both and assert exact equality for the rank/scoring fields, including `tool_a_score`, `tool_a_rank`, `confidence_score`, `confidence_label`, `profile_label`, `score_eligible`, `score_eligibility_reason`, `eligible_structural_window_count`, `positive_delta_window_count`, `structural_delta_core`, `structural_gamma_core`, `up_beta_core`, `down_beta_core`, `asymmetry_ratio_core`, `anchor_window_id`, and `volatility_anchor_window_id`.

Do not compare the whole dataframe blindly, because the new display columns intentionally change shape. Compare the protected fields exactly and separately assert the new columns exist.

4. **Is 5Y scarcity handling sufficient?**

The contract is right: use `window_status_5y`, week count, and null betas to degrade honestly. The plan is incomplete until the 5Y minimum-observation policy is explicit. Otherwise a ticker with roughly 2.8 years of data can be marked eligible if 5Y accidentally reuses a 3Y threshold.

Serve should not hide the 5Y selector globally. It should show the selector, mute/suppress per ticker when `window_status_5y != "ELIGIBLE"`, and show the week/status context. Detail volatility already follows that pattern; overview reliability needs the `ELIGIBLE` status fix noted above.

5. **Labels and anchor**

Show `12M` as **1Y** in the UI, but keep `12M` as the canonical internal id and persisted suffix.

Do not rename columns to `*_1y` and do not change the canonical anchor to 2Y/5Y. Keep:

- config anchor: `structural_anchor_window = "12M"`;
- persisted columns: `*_12m`;
- URL alias: `1Y -> 12M`;
- display label: `12M -> 1Y`;
- explanations/detail labels/charts/tables use the display label helper.

Changing the anchor would reopen scoring/explanation behavior and defeat the point of Option B.

## Blocking List Before Build

1. Add the scoring-only frame/filter to the plan and tests so 2Y/5Y cannot affect rank, confidence, eligibility, counts, anchors, or core fields.
2. Add central 2Y/5Y observation/regime thresholds; do not rely on 3Y defaults.
3. Expand the contract/touch list for benchmark schema version, manifest-backed current-state verification, serve/detail constants, benchmark comparison, format/help text, Candidate Finder no-change tests, and live-column parity.
4. Fix the overview reliability status check to treat `ELIGIBLE` as usable and non-eligible 5Y windows as muted/suppressed.

After those changes, the plan is sound to build as Option B.
