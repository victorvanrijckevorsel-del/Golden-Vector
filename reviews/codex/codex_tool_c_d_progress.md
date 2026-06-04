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
