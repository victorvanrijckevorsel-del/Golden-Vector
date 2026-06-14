# Codex Review - Lab Data Storage And Calculation Efficiency

Verdict: NEEDS CHANGES BEFORE SCALING

This is a read-only engineering review focused on how the Lab/Scorecard data is
stored, loaded, and calculated. I did not change product code. The goal was to
answer: is this data spine efficient, safe, and clean enough to build on?

## Measurements

Local artifacts:

| Artifact | Rows | Parquet size | In-memory size | Notes |
|---|---:|---:|---:|---|
| `dial_cells_latest.parquet` | 1,260 | 0.095 MB | 0.27 MB | Small and well-shaped. |
| `dial_episodes_latest.parquet` | 434,442 | 4.9 MB | 50.5 MB | Fine on disk; full read per detail request is okay today but not free. |
| `dial_relstrength_latest.parquet` | 110,218 | 1.3 MB | 8.3 MB | Fine today. |
| `scorecard_latest.parquet` | 9 | 0.012 MB | 0.004 MB | Trivial. |

Serve/read timings:

| Path/helper | Average local read time |
|---|---:|
| `load_dial_cells(paths, horizon=13, bucket="gold_down")` | ~0.013 s |
| `load_ticker_curve(paths, ticker="AEM", horizon=13, benchmark="GDX")` | ~0.086 s |
| `load_scorecard_data(paths)` | ~0.007 s |

Build timings from cached local data:

| Step | Time |
|---|---:|
| Read 65 normalized histories + gold + GDX/GDXJ | ~0.46 s |
| Build weekly return frame | ~1.78 s |
| Build one shared forward panel for all horizons `[4,8,13,26]` | ~12.96 s |
| Build current `dial_cells_latest` path | ~196.0 s |
| Single `build_episode_frame(13w, GDX)` | ~25.8 s |

The key point: the persisted outputs are small and serve-time reads are fast.
The inefficient part is the publisher/build path.

## Findings

### HIGH 1 - The Lab build recomputes the same episode math many times

Evidence:
- `golden_vector/lab/conditional_dial.py:670-672` builds cells, episodes, and
  relstrength separately.
- `build_dial_cells_wide` calls `build_episode_frame` inside nested
  horizon/benchmark loops at `golden_vector/lab/conditional_dial.py:447-460`.
- `build_episode_artifact` then calls `build_episode_frame` again inside the
  same horizon/benchmark loops at `golden_vector/lab/conditional_dial.py:389-402`.
- `build_episode_frame` itself calls `build_forward_return_panel(...)` and
  `_gold_forward_simple(...)` every time at
  `golden_vector/lab/conditional_dial.py:257-266`.

Why it matters:
The cells table has only 1,260 rows, but it took ~196 seconds to build. The
reason is not output size; it is repeated calculation. The same forward labels
are computed once for the cells, then again for the episode artifact, and
benchmark/gold forward returns are recomputed for every ticker/horizon/benchmark
combination.

Concrete fix:
Change the Lab publisher to use one calculation spine:

1. Build `weekly` once.
2. Build one multi-horizon forward panel once:
   `build_forward_return_panel(weekly, horizons_weeks=DIAL_HORIZONS_WEEKS)`.
3. Build one multi-horizon gold-forward panel once.
4. Build one long-form `episodes` artifact from those panels.
5. Derive `cells` from the already-built `episodes`, not from `weekly`.
6. Derive `relstrength` separately because it is a different measure.

The target contract should be: "episode math is computed once; all Lab views and
aggregates consume that same episode table." Add a parity test proving the new
cells equal the current cells.

### HIGH 2 - Benchmark and gold forward returns are recomputed per ticker even though they are calendar-level series

Evidence:
- `golden_vector/lab/forward_returns.py:39-48` loops per ticker and computes
  GDX/GDXJ forward returns inside each ticker group.
- `golden_vector/lab/conditional_dial.py:286-310` loops per ticker and computes
  gold forward returns inside each ticker group.
- In the weekly frame, benchmark and gold returns are the same calendar series
  repeated for each ticker.

Why it matters:
With 65 tickers, this repeats the same benchmark/gold rolling-window work many
times. The measured single all-horizon forward panel took ~13 seconds; the
current nested episode path pays this cost repeatedly.

Concrete fix:
Compute calendar-level forward returns once per horizon for:

- gold forward simple return;
- GDX forward return;
- GDXJ forward return.

Then merge those calendar-level labels onto each ticker's stock forward return
by `week_period`. Keep the existing `reindex_contiguous_weeks` discipline for
stock returns so halted/missing ticker weeks still produce correct NaNs.

This should preserve the math while removing a large amount of repeated
rolling-window work. Gate it with old-vs-new parity on `alpha`, `beat`,
`gold_bucket`, and the final cells.

### HIGH 3 - Dial artifacts are latest-only, unlike the Scorecard's run-stamped pattern

Evidence:
- `golden_vector/lab/conditional_dial.py:594-597` defines only latest filenames:
  `dial_episodes_latest.parquet`, `dial_cells_latest.parquet`,
  `dial_relstrength_latest.parquet`, and `dial_meta.json`.
- `golden_vector/lab/conditional_dial.py:674-676` writes only those latest
  aliases.
- `golden_vector/lab/scorecard.py:238-242` already writes a run-stamped
  `scorecard_{stamp}.parquet` plus `scorecard_latest.parquet`.

Why it matters:
The Lab is becoming the evidence/explanation layer for whether the tools work.
If the dial artifacts are overwritten in place, it is harder to reproduce a
specific Scorecard/Lab screen later. The code keeps a variant ledger, but not
the exact artifact version produced from that ledger at a given time.

Concrete fix:
Adopt the Scorecard pattern for dial artifacts:

- write `dial_cells_{stamp}.parquet`, `dial_episodes_{stamp}.parquet`,
  `dial_relstrength_{stamp}.parquet`;
- also write the latest aliases for easy serving;
- make `dial_meta.json` include the run-stamped filenames and input hashes.

This does not require putting Lab artifacts into the product model-state
manifest. It simply makes Lab research artifacts reproducible.

### MEDIUM 1 - The build has no timing/row-count diagnostics in metadata

Evidence:
- `golden_vector/lab/conditional_dial.py:702-720` writes schema, config,
  rows, cells, episodes, and relstrength counts, but not per-step seconds.
- The actual bottleneck was only visible after manual timing.

Why it matters:
The repo already learned this lesson on Tool A: real stage timings must be
recorded by the pipeline, not reconstructed later from ad-hoc profiling.
Without timings, a slow Lab build can hide again.

Concrete fix:
Add `stage_timings` to `dial_meta.json`, for example:

- `read_inputs_seconds`
- `build_weekly_seconds`
- `build_forward_panel_seconds`
- `build_episodes_seconds`
- `build_cells_seconds`
- `build_relstrength_seconds`
- `write_artifacts_seconds`

Also record `rows_built` and `rows_persisted` where useful. This is cheap and
would have revealed the 196-second cells build immediately.

### MEDIUM 2 - Serve-time full-artifact reads are acceptable today but should have a scale threshold

Evidence:
- `golden_vector/serve/lab_curve_data.py:222-236` reads the full 434k-row
  episode artifact and filters in memory for one ticker/horizon/benchmark.
- `golden_vector/serve/lab_curve_data.py:283-291` reads the full relstrength
  artifact and filters in memory.
- Local timing is acceptable today: ticker curve load is ~0.086 seconds.

Why it matters:
This is not a current blocker. But if the universe, horizons, or history length
grow, full-artifact reads per request will become noticeable. The artifact is
already 50 MB in memory despite being only 4.9 MB on disk.

Concrete fix:
Keep the current simple reader until it crosses a measured threshold. Add a
comment/metadata threshold such as: "If detail load exceeds 250 ms p95 or
episode artifact exceeds 2 million rows, partition by ticker or use parquet
predicate filters." Do not prematurely add a database.

If/when needed, the simplest next step is not a new database; it is partitioned
Parquet or PyArrow filters by `ticker`, `horizon_weeks`, and `benchmark`.

### MEDIUM 3 - Legacy 13w dial artifacts remain beside the new multi-horizon artifacts

Evidence:
- `data/lab/dial_table_13w_latest.parquet` and
  `data/lab/dial_table_13w_meta.json` still exist next to the new
  `dial_cells_latest.parquet` / `dial_episodes_latest.parquet` artifacts.
- Current serve code reads the new artifacts, but older tools/tests still
  reference the old `build_dial_table` compatibility path.

Why it matters:
This is not breaking the current page, but it increases confusion. A future
tool or reviewer can accidentally inspect the old artifact and think it is the
current Lab state.

Concrete fix:
Decide explicitly:

- If `dial_table_13w_latest` is now legacy-only, document it and stop writing
  it.
- If backward compatibility still needs it, put it under a clearly named legacy
  artifact or include a `superseded_by` note in its meta.

Do not delete local data silently, but add a migration/cleanup note.

### MEDIUM 4 - Scorecard storage is reproducible, but its reader is too trusting

Evidence:
- `golden_vector/lab/scorecard.py:238-242` writes a run-stamped scorecard and a
  latest alias.
- `golden_vector/serve/scorecard_data.py:31-57` reads the latest parquet and
  returns rows without a schema/version/required-column gate.

Why it matters:
The storage pattern is good. The read path is the weaker half. A stale or
partial scorecard artifact can be treated as available and render with missing
fields.

Concrete fix:
Add `schema_version` to the scorecard meta and a required-column check in
`load_scorecard_data`, same shape as the Lab curve reader. Return `STALE` or
`CORRUPT` and render a calm rebuild message.

### LOW 1 - Some build logic remains row-loop heavy, but it is secondary after removing duplicated forward panels

Evidence:
- `_dial_cells` loops over every `(ticker, bucket)` group at
  `golden_vector/lab/conditional_dial.py:175-223`.
- `_assign_bucket` is applied row-by-row at
  `golden_vector/lab/conditional_dial.py:280-282`.

Why it matters:
These loops are not the first bottleneck. The first bottleneck is repeated
forward-label computation. After fixing that, the groupby loop may be fine.

Concrete fix:
Do not start here. First build the episode spine once. If the build remains
slow, vectorize bucket assignment with `pd.cut` and `_dial_cells` with grouped
aggregations for `mean`, `count`, `median`, and quantiles.

## Architecture Recommendation

The right shape is:

```text
raw histories + gold + benchmarks
        |
        v
weekly return frame
        |
        v
single multi-horizon episode spine
        |
        +--> cells overview artifact
        +--> ticker detail dot chart artifact
        +--> evidence/count metadata

weekly return frame
        |
        +--> relative-strength artifact
```

The key principle: one backend-owned episode spine, many read-only views.

## What Is Already Good

- Serve reads are fast and mostly render-only.
- Artifact sizes are small today.
- The cells artifact has the right wide shape: one row per
  `(ticker, bucket, horizon)` with GDX rank and GDXJ comparison fields.
- Duplicate keys are clean:
  - `dial_cells`: no duplicate `(ticker, horizon_weeks, bucket)` keys.
  - `dial_episodes`: no duplicate `(ticker, horizon_weeks, benchmark, week_period)` keys.
- The storage choice of Parquet is appropriate. No database is needed for this
  scale yet.
- The Scorecard already uses a run-stamped + latest alias pattern.

## Fix Order

1. Refactor Lab build to compute one episode spine and derive cells from it.
2. Compute calendar-level gold/GDX/GDXJ forward returns once per horizon.
3. Add old-vs-new parity tests for episodes and cells.
4. Add per-step timings and row counts to `dial_meta.json`.
5. Add run-stamped dial artifacts plus latest aliases.
6. Add Scorecard schema/required-column reader guard.
7. Document or migrate the legacy `dial_table_13w_*` artifacts.
8. Only then consider partitioned Parquet/filtered reads if measured detail
   load becomes slow.

This is not a UI problem. The UI is mostly doing the right thing by reading
prepared artifacts. The main cleanup is to make the backend computation match
the architecture promise: compute the episode labels once, persist them once,
and derive every Lab view from that single source of truth.
