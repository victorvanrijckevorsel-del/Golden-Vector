# Codex Review - Claude Horizon Consistency

Scope reviewed:
- `git diff 75d1c36 claude-horizon`
- Integrated `dev-vic` detail switcher/source-mode behavior where Claude's window switcher and Codex's `fundamentals_source=yahoo` preservation meet.

## Position on Option B

I agree with Option B: keep Score, Confidence, and Profile as an explicitly labeled cross-window summary, not per-window values. The score is a robustness blend across the scoring windows, and confidence is about cross-window agreement. A per-window Score/Confidence/Profile would be a new methodology, not a truer rendering of the current model. The implementation labels this section as "Across scoring windows (6M / 1Y / 3Y)", which is the right call.

## Findings

### [MEDIUM] Detail-page resolver ignores the registry's `1Y` alias

File: `golden_vector/serve/detail_panels.py:1978`

`common/windows.py` now makes `1Y` a supported alias for canonical `12M`, but `_resolve_active_window` still checks only raw canonical ids in `_STRUCTURAL_WINDOWS`. On the integrated tree, `_resolve_active_window("1y", "6M")` returns `6M`, not `12M`. So a user-entered or linked `?window=1y` can silently fall back to the ticker's canonical anchor instead of showing the 1Y/12M horizon.

Concrete fix: route detail-window parsing through a registry helper that can distinguish "recognized alias" from "invalid". For example, add/export `resolve_window_or_none()` from `common/windows.py`, then make `_resolve_active_window("1y", "6M") == "12M"` while preserving the current invalid/missing fallback to the canonical anchor. Add a regression test for `1y` with a non-12M canonical anchor.

### [MEDIUM] Window topology is still duplicated outside the registry

Files:
- `golden_vector/model/benchmark_comparison.py:26`
- `golden_vector/model/benchmark_comparison.py:34`
- `golden_vector/contracts/config_models.py:1043`
- `golden_vector/contracts/config_models.py:1108`
- `golden_vector/contracts/config_models.py:1155`
- `golden_vector/contracts/config_models.py:1165`

The branch establishes `common/windows.py` as the one source of window ids, labels, scoring/display split, suffixes, weeks, and offsets, and the new registry docstring explicitly lists `model/benchmark_comparison._WINDOW_COLUMN_SUFFIX/_WINDOW_LABEL` as prior duplication. Those maps are still active. `contracts/config_models.py` also still hard-codes the same ids/splits in validation paths.

This is not about moving `minimum_observations_*` values into the registry; those thresholds should stay in config. The issue is that config and benchmark comparison should derive their allowed ids/suffixes/splits from the registry so a future window change cannot drift across layers. A current visible symptom is that `benchmark_comparison.py` still labels `12M` as `12-month`, while the registry says the display label is `1Y`.

Concrete fix: in `benchmark_comparison.py`, import `window_suffix` and the registry display label helper instead of `_WINDOW_COLUMN_SUFFIX/_WINDOW_LABEL`; keep only a special `CORE` case if that non-structural label is still needed. In `config_models.py`, build default `structural_windows` / `structural_display_windows` and validators from `SCORING_WINDOWS`, `DISPLAY_WINDOWS`, and `ALL_WINDOWS`; implement `minimum_observations_for_window()` by deriving the configured field name via `window_suffix(window_id)` and `getattr`. Add tests that config defaults and validators match the registry constants.

### [LOW] The detail page still renders raw `12M` in visible labels

File: `golden_vector/serve/detail_panels.py:1050`

The switcher tab renders `12M` as `1Y`, but several visible detail-page labels still use the raw canonical id: `Active window: 12M`, `Structural Delta (12M)`, `Volatility Diagnostics (12M)`, the structural table `12M (Anchor)`, and scatter/up-down-beta hints. That contradicts the stated "12M renders as 1Y" behavior and makes the page use two names for the same horizon.

Concrete fix: compute `active_window_label = WINDOW_LABELS.get(active_window, active_window)` once in `_render_tool_a_panel` and use registry display labels in all visible text. Keep the canonical id only for column lookups, query params, and internal comparisons. In `_render_structural_window_table`, render `WINDOW_LABELS.get(window_id, window_id)` in the visible cell while preserving the canonical id in data attributes if needed. Update tests that still expect visible `12M` text to expect `1Y`.

## Verified

- No HIGH findings.
- The core horizon behavior is sound: the detail page descriptive metrics now follow all five windows, and Score/Confidence/Profile are clearly labeled as cross-window.
- The 2Y/5Y volatility path now uses `_WINDOW_WEEKS` sourced from the registry, so I do not see a 52-week fallback reintroduced for those windows.
- The merged `dev-vic` `_render_window_switcher` preserves `fundamentals_source=yahoo` across window changes, and `render_detail_page()` passes `financials_source` into the switcher.
- Focused integrated tests passed in `C:\Users\Emanuel\code\GV-horizon`: `python -m pytest tests/test_windows_registry.py tests/test_workspace_horizon_switcher.py::test_detail_page_is_horizon_consistent_with_no_silent_mixing tests/test_windows.py tests/test_config_models.py -q` -> 129 passed.
