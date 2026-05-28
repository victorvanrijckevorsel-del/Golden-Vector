# Snapshot Retention Audit

Date: 2026-05-28

## Summary

Golden Vector already retains the main analytical snapshots needed to inspect historical Tool A, Tool B, combined, and foundation outputs. The remaining gap is not missing parquet snapshots; it is replay metadata. A future backtest can read historical outputs and the foundation snapshot used by current runs, but cannot always reconstruct the exact code/config/manual-data state that produced every historical run from the run folder alone.

## What Is Retained

Foundation update runs keep run-local raw and normalized snapshots under `data/runs/<run_id>/snapshots/`. The current update-data persistence code writes:

- `raw_equities.parquet`
- `raw_fx.parquet`
- `raw_gold.parquet`
- `usd_equities.parquet`
- `market_snapshots_usd.parquet`

The latest validated foundation manifest points to those run-local files instead of only pointing at mutable `latest` files. `golden_vector/app/latest_data.py` writes run-local snapshot paths into `latest_foundation_manifest.json`, and `load_latest_foundation_snapshot()` reads those paths back.

Tool A output retention is also in place. `data/output/tool_a/` keeps both historical full outputs and historical latest-row snapshots:

- `tool_a_output_<runid>.parquet`
- `tool_a_latest_<runid>.parquet`
- `tool_a_latest.parquet` as the latest pointer

Tool A structural metrics are retained separately in `data/intermediate/tool_a_structural/tool_a_structural_<runid>.parquet`, with `tool_a_structural_latest.parquet` as the latest pointer.

Tool B output retention is in place with the same pattern:

- `tool_b_output_<runid>.parquet`
- `tool_b_latest_<runid>.parquet`
- `tool_b_latest.parquet` as the latest pointer

Combined output retention also exists for the current combined output path:

- `combined_output_<runid>.parquet`
- `combined_latest_<runid>.parquet`

Filesystem spot check on 2026-05-28:

| Area | Evidence |
| --- | --- |
| Run directories | `data/runs/` contains 67 timestamped run folders, from 20260422 through 20260424. |
| Foundation runs | 8 update-data runs exist; 7 have a `snapshots/` directory. The early missing one appears to predate the current snapshot-retention implementation. |
| Recent foundation snapshot | `data/runs/20260424T140753Z-update-data-6175c3fb/snapshots/` contains raw gold, raw equities, raw FX, normalized equities, and normalized market snapshots. |
| Tool A | 19 historical `tool_a_latest_*.parquet` files and 19 historical `tool_a_output_*.parquet` files. |
| Tool B | 19 historical `tool_b_latest_*.parquet` files and 19 historical `tool_b_output_*.parquet` files. |
| Tool A structural metrics | 12 historical `tool_a_structural_*.parquet` files. |

## What Is Not Fully Retained

The latest foundation manifest is a moving pointer at `data/intermediate/status/latest_foundation_manifest.json`. It records the current latest foundation snapshot and points to run-local parquet files, but the manifest itself is not copied into every run folder as an immutable `foundation_manifest.json`.

Each run has `metadata.json`, `config_summary.json`, status summaries, and an artifact list. These are useful audit breadcrumbs, but they are summaries. They do not contain the full loaded application config, full scoring config, full universe config, exact code revision, or manual-data database snapshot.

`RunContext.record_artifact()` records artifact paths in metadata. It does not copy mutable artifacts into the run folder. This is fine for historical parquet files that already include the run ID in their filename, but weaker for mutable pointers such as `*_latest.parquet`, `latest_foundation_manifest.json`, and any local manual-data store state used by Tool B.

Tool A and Tool B runs record the `snapshot_refresh_run_id` they consumed through `foundation_snapshot_summary.json` and the run notes. That ties outputs back to a foundation run, but deterministic replay still depends on the referenced foundation run folder, the summarized config hash, the current codebase, and the current manual-data history unless those were separately preserved.

## Backtesting Readiness

Historical analysis is ready for "what did the outputs say at run time?" questions. The retained Tool A/B output parquet files and run-local foundation snapshots are enough to inspect past scores, structural metrics, latest market snapshots, and normalized historical price inputs for retained runs.

Deterministic replay is only partially ready. To exactly reproduce a historical run later, the project would also need immutable per-run replay metadata:

- full loaded config or a content-addressed copy keyed by `combined_config_hash`
- exact Git commit or code version
- full foundation manifest copied into the producing run folder
- manual-data store snapshot or immutable manual-data version reference for Tool B
- external data-source/version notes where relevant

## Recommended Future Fix

Do not add another snapshot layer. Instead, add a small immutable `replay_manifest.json` to each new run folder. It should copy the full loaded config or reference a content-addressed config copy, record the Git commit when available, copy the foundation manifest used by Tool A/Tool B/combined runs, and record the manual-data store version or snapshot path for Tool B. That keeps the current parquet retention model canonical while making future backtests reproducible.

