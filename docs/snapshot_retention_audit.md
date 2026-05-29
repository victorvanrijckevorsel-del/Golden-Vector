# Snapshot Retention Audit

Date: 2026-05-28
Updated: 2026-05-29 after the replay manifest milestone

## Summary

Golden Vector already retains the main analytical snapshots needed to inspect historical Tool A, Tool B, combined, and foundation outputs. The original remaining gap was not missing parquet snapshots; it was replay metadata. That gap is now closed for new runs from the replay-manifest milestone forward: every new run writes `replay_manifest.json` and `replay_snapshots/` in its run folder. Historical runs created before this milestone are not backfilled, because using today's code/config/manual data would create false provenance.

Use `python main.py verify-replay <run-id-or-path>` to verify a retained run. For old run folders with no replay manifest, the command returns success with a clear "run predates replay manifests" message.

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

For historical runs before the replay-manifest milestone, the latest foundation manifest is a moving pointer at `data/intermediate/status/latest_foundation_manifest.json`. It records the current latest foundation snapshot and points to run-local parquet files, but the manifest itself was not copied into every run folder as an immutable `foundation_manifest.json`.

Historical pre-manifest runs have `metadata.json`, `config_summary.json`, status summaries, and an artifact list. These are useful audit breadcrumbs, but they are summaries. They do not contain the full loaded application config, full scoring config, full universe config, exact code revision, or manual-data database snapshot.

`RunContext.record_artifact()` records artifact paths in metadata. It does not copy mutable artifacts into the run folder. This is fine for historical parquet files that already include the run ID in their filename, but weaker for mutable pointers such as `*_latest.parquet`, `latest_foundation_manifest.json`, and any local manual-data store state used by Tool B.

Historical Tool A and Tool B runs record the `snapshot_refresh_run_id` they consumed through `foundation_snapshot_summary.json` and the run notes. That ties outputs back to a foundation run, but deterministic replay still depends on the referenced foundation run folder, the summarized config hash, the current codebase, and the current manual-data history unless those were separately preserved.

New runs from the replay-manifest milestone forward preserve those replay inputs directly:

- `replay_manifest.json` records manifest version, run id, command, start time, Git state, config snapshots, manual-data snapshot, and consumed foundation run when applicable.
- `replay_snapshots/configs/*.yaml` stores immutable copies of the expected application config files.
- `replay_snapshots/manual_screening.sqlite3` stores the manual Tool B SQLite state when the store exists at run start.
- `replay_snapshots/foundation_manifest.json` stores the immutable foundation manifest consumed by Tool A, Tool B, and compare-horizons runs.
- `verify-replay` checks snapshot integrity and reports drift against the current checkout when that context is available.

## Backtesting Readiness

Historical analysis is ready for "what did the outputs say at run time?" questions. The retained Tool A/B output parquet files and run-local foundation snapshots are enough to inspect past scores, structural metrics, latest market snapshots, and normalized historical price inputs for retained runs.

Deterministic replay is still only partially ready for historical pre-manifest runs. To exactly reproduce one of those older runs later, the project would also need immutable per-run replay metadata:

- full loaded config or a content-addressed copy keyed by `combined_config_hash`
- exact Git commit or code version
- full foundation manifest copied into the producing run folder
- manual-data store snapshot or immutable manual-data version reference for Tool B
- external data-source/version notes where relevant

For new replay-manifest runs, the missing replay metadata is retained. A future predictive-model or backtest runner can treat the replay manifest as the run-level provenance envelope, while still adding model-specific provenance such as model artifact hashes, feature snapshot hashes, hyperparameters, training window, and random seed.

## Replay Manifest Status

The recommended future fix from the original audit has been implemented for new runs. Do not backfill old run folders; `verify-replay` deliberately reports those as "run predates replay manifests" instead of manufacturing provenance from today's files.

Remaining future work is not another retention layer. It is stricter replay use:

- keep `verify-replay` as the human integrity check for retained runs
- add model-specific provenance only when predictive models are introduced
- avoid backfilled or placeholder manifests for older runs

