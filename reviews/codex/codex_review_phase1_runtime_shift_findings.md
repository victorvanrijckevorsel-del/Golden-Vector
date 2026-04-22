# Codex Review: Phase 1 Runtime Shift

## Scope

Review of the new explicit refresh plus local-first runtime changes introduced in:

- [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py)
- [golden_vector/app/latest_data.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/app/latest_data.py)
- [golden_vector/ingestion/persist.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/ingestion/persist.py)

## Findings

### P1. The manifest points analysis at mutable "latest" files instead of immutable refresh artifacts

The first implementation wrote a latest-foundation manifest, but it still told Tool A and Tool B to read generic latest paths such as `market_snapshot_latest.parquet`. That is unsafe because a failed later refresh can overwrite those latest aliases while the old manifest still exists, which means the app can silently read a mixed snapshot from different runs.

Why it matters:

- this is a correctness and trust issue
- local-first analysis must be tied to a stable refresh snapshot
- otherwise a failed refresh can poison the current local data without updating the manifest

Fix direction:

- the manifest should point to immutable run-specific snapshot files
- Tool A and Tool B should read exactly the artifacts produced by the recorded refresh run

### P1. The local snapshot loader is heavier and more failure-prone than necessary

The first implementation always loaded all normalized equity histories even for commands that do not need them. `tool-b` only needs normalized market snapshots, but it still paid the cost of reading all equity histories and could fail because of an unrelated missing equity artifact.

Why it matters:

- slower normal runs
- broader failure surface than necessary
- violates the new product goal of local-first, lightweight daily usage

Fix direction:

- make the loader selective
- load only the data needed by each command
- `tool-a`: gold history + selected equity histories
- `tool-b`: normalized market snapshots only
- `compare-horizons`: gold history + one ticker history only

### P2. The local snapshot path does not validate compatibility with the current universe/currency setup

The first implementation would accept the latest local snapshot if the manifest existed and the files were present. But it did not verify that the current configured active universe still matched the refresh that produced the local snapshot.

Why it matters:

- a ticker could be added, removed, disabled, or have its currency changed after refresh
- the app could then use stale normalized data without explicitly forcing a refresh

Fix direction:

- store a foundation input signature in the manifest
- validate that the current active foundation universe matches that signature before allowing local analysis
- fail cleanly and instruct the user to rerun `update-data`
