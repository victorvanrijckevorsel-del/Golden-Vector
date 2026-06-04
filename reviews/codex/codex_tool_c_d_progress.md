# Tool C / Tool D Build Progress

## Batch 1 - Tool C

### Step 1 - Config and paths

- Added Tool C and Tool D config contracts with safe defaults for direct `AppConfig` tests.
- Added `config/tool_c.yaml` with hit-rate event thresholds and `config/tool_d.yaml` with the stressed gold assumption.
- Registered both config files in `EXPECTED_CONFIG_FILES` so replay manifests retain them.
- Added Tool C and Tool D intermediate/output path properties.
- Added focused config validation tests.

Self-review notes:

- The Tool C hit-rate thresholds live in YAML and validation enforces down/up ordering.
- Defaults avoid breaking unit tests that instantiate `AppConfig` directly.
- Replay coverage is inherited from `expected_config_paths`; the existing replay test now verifies the expanded list.

### Step 2 - Weekly return contract

- Added `golden_vector/features/weekly_returns.py`.
- Tool C stock/gold returns reuse `build_structural_weekly_series` so sampling stays aligned with Tool A.
- Benchmark ETF returns are joined by the same W-FRI `week_period` key and exposed as `gdx_log_ret` / `gdxj_log_ret`.
- Added unit tests for output columns, benchmark alignment, and incomplete-week dropping.

Self-review notes:

- Fixed a defensive issue where benchmark files without `return_basis_usd` could produce a non-Series basis.
- Kept benchmark columns fixed to the locked GDX/GDXJ output contract while allowing missing benchmark histories to surface as nulls.

### Early self-review correction - Tool C threshold shape

- Corrected Tool C config from a nested fractional threshold block to the locked top-level fields `downside_hit_rate_threshold_pct` and `upside_hit_rate_threshold_pct`.
- Kept fractional convenience properties on the config model so analytics code does not re-divide ad hoc.

### Step 3 - Gold regimes and relative behavior

- Added rolling gold regime classification with production defaults of 156 weeks and a 52-week warm-up.
- Added relative weakness/strength, hit-rate, and tail-average feature construction.
- Every relative/hit-rate/tail metric now carries its own event count and returns null when count is below `min_events`.

Self-review notes:

- Added `regime_rolling_weeks` and `regime_min_weeks` to Tool C config rather than hard-coding the rolling-regime rule.
- Relative GDX metrics use their own benchmark intersection count, so missing GDX history does not accidentally borrow the gold denominator.
- Fixed a test-only NumPy boolean identity assertion after the first focused run.

### Step 4 - Tool C model

- Added `golden_vector/model/tool_c.py`.
- Tool C now joins Tool A latest fields with relative behavior metrics and produces `tool_c_downside_rank` plus `tool_c_upside_rank`.
- Robust components are equal-weighted through the shared `oriented_percentile` helper; tail averages remain context only.
- Score-ineligible rows are sunk, and thin relative metrics are tagged without blocking the whole side when enough other robust components exist.

Self-review notes:

- Removed an over-strict first draft gate that made a thin hit-rate metric sink the full side; the intended behavior is exclude the thin metric and keep ranking if enough robust inputs remain.
- Added defensive creation of missing component columns so empty/missing relative metric inputs degrade to null ranks instead of a `KeyError`.

### Step 5 - Tool C persistence and provenance

- Added `persist_tool_c_outputs` with retained full output, per-run latest output, and stable latest aliases.
- Added replay manifest source snapshot support for Tool C and Tool D named sources.
- Tool C source assets are copied under `replay_snapshots/tool_c/`, hashed, and verified by `verify_manifest`.

Self-review notes:

- Kept Tool C persistence separate from generic Tool A/B persistence but reused the existing local write/latest helpers.
- Added a replay verification test so the manifest checks both copied source snapshots and the current source file hash.

### Step 6 - Tool C CLI

- Added `python main.py tool-c`.
- The runner loads latest foundation gold/equities, latest Tool A output, and cached benchmark histories, then writes Tool C outputs.
- Tool C source paths include Tool A latest, foundation raw gold, foundation USD equities, and any cached benchmark histories found.

Self-review notes:

- The CLI permits missing benchmark histories; those only remove benchmark-relative metrics and show through event counts/nulls.
- Added tests for parser registration and the runner's latest-local-input plumbing.

### Batch 1 self-review fixes

- Removed unused `minimum_observations` from Tool C config; the actual observation controls are `regime_min_weeks`, `regime_rolling_weeks`, and `min_events`.
- Fixed Tool C component percentile scoring so `score_eligible=false` Tool A rows are masked before percentiles are calculated, not merely sunk afterward.
- Changed relative-behavior regime joins to use only `week_period`; joining on `gold_log_ret` float equality was unnecessarily fragile.

Focused verification:

- `python -m pytest tests/test_config_loading.py tests/test_config_models.py tests/test_weekly_returns.py tests/test_gold_regime.py tests/test_relative_behavior.py tests/test_tool_c.py tests/test_persist_tool_c.py tests/test_cli_tool_c.py tests/test_replay_manifest.py`
- Result: 109 passed.

## Batch 2 - Tool D

### Step 0 - Tool B in-memory seam

- Confirmed `compute_tool_b_in_memory` is callable at arbitrary gold prices using already-loaded manual data and market snapshots.
- Added a contract test that verifies EBITDA changes with the gold price and no Tool B latest output is written.

Self-review notes:

- No Tool B extraction was needed; the existing in-memory seam is sufficient for Tool D.
