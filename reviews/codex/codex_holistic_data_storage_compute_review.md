# Holistic Data Storage And Compute Review

Verdict: GOOD FOUNDATION, NOT YET BEAUTIFUL

The current Golden Vector architecture is much stronger than a typical local prototype: it uses run-stamped Parquet artifacts, a current-state manifest, backend computation, schema contracts in many places, and stage timings. For a local-first analytics tool with roughly 60-70 tickers, this file-backed artifact lake is the right base. I would not rewrite it into a single SQL database now.

But it is not yet as clean, safe, and efficient as it should be. The main gaps are not one-off bugs; they are data-spine issues: stale/incomplete local artifacts after schema changes, a few non-atomic writes, some request-time scenario computation, duplicated historical outputs, privacy-sensitive replay snapshots, and stored datasets that are not being used enough.

## Scope Checked

I inspected the current local data layout, model-state manifest, artifact schemas and sizes, refresh/status behavior, performance profile, portfolio storage, option storage, fundamentals storage, shared Parquet/atomic helpers, and serve-layer computation boundaries.

I did not inspect sensitive manual portfolio source files. I only checked generated artifact schemas/counts and code paths.

## Current Data Architecture

Golden Vector currently works like a local data lake:

- `data/raw/` stores fetched market/foundation data.
- `data/intermediate/` stores normalized/foundation state and status manifests.
- `data/output/` stores tool outputs and latest aliases.
- `data/runs/` stores replay manifests and per-run snapshots.
- `data/manual/` stores user-entered local/private data.
- `data/intermediate/status/latest_model_state.json` is the central current-state pointer.

That is the right architecture for this stage. It is easy to inspect, easy to back up, works offline, and avoids running a database service. Parquet is also a good storage format for the analytical tables.

The important thing is that the manifest, not the `*_latest` aliases, must be treated as the source of truth. The code mostly follows this now.

## What Is Strong

The best parts of the current architecture are:

- Immutable run-stamped artifacts exist alongside convenience latest aliases.
- The model-state manifest resolves current artifacts through immutable paths and rejects missing/unusable/non-immutable references in `golden_vector/app/model_state.py`.
- Required Parquet reads have a checked reader with schema validation in `golden_vector/common/parquet.py`.
- Most heavy analytics now run in backend pipelines rather than directly in request handlers.
- The refresh pipeline has an all-or-nothing shape: foundation, Tool A/B/C/D, option artifacts, portfolio, then final model-state publish.
- Option carry-forward is defensive: old option artifacts are only reused after path, hash, schema, and source checks.
- Performance instrumentation is now useful. `python main.py perf-profile` showed the cached compute path is not the bottleneck: Tool A cached path was about 14s and option artifact compute about 5s.

This is a solid base to build on. The main recommendation is not "replace it"; it is "tighten it and catalog it."

## High-Severity Findings

### H1. The current local data state is stale/incomplete after schema changes

`python main.py status` currently reports an incomplete model state. The local Tool B output is stale against the newer schema, and portfolio artifacts reference an older refresh id than foundation. That means the current UI can render, but its cross-tool state should not be trusted until a successful refresh regenerates the artifacts.

This is not a code design failure by itself; it is an operational risk after large schema work. The product needs a clear "data is from the previous version, refresh required" state everywhere, and milestone work should finish with a refresh or a documented "stale until refresh" handoff.

Concrete fix: after schema migrations, fail closed with a friendly page and make the status banner prominent. Do not let old artifacts silently feed rankings.

### H2. Manual portfolio storage accepts non-finite numeric values

`golden_vector/portfolio/manual_store.py:185` writes JSON with `json.dumps(...)`, and `_positive_float` at `golden_vector/portfolio/manual_store.py:203` checks `<= 0` but does not reject `NaN` or infinity. In Python, `float("nan") <= 0` is false, so a bad value can pass validation.

The downstream valuation path has some degradation guards, but the source-of-truth manual store should not accept non-finite values at all.

Concrete fix: reject non-finite shares/prices at input validation using `math.isfinite`, and serialize JSON with `allow_nan=False`.

### H3. Replay snapshots duplicate private/manual databases many times

`golden_vector/app/replay_manifest.py:315` and the SQLite backup path around `golden_vector/app/replay_manifest.py:334` snapshot manual databases into `data/runs/`. I saw many run-level `.sqlite3` files. This is useful for replay, but it creates a privacy and retention problem because private manual data can be copied many times locally.

Concrete fix: add a privacy-aware retention policy for replay snapshots. At minimum, document what is copied, protect it from git, and prune old manual snapshots separately from analytical artifacts. Long term, consider hashing/redacting sensitive fields in replay metadata and keeping the manual source-of-truth as the only private data store unless a replay explicitly needs a copy.

## Medium-Severity Findings

### M1. One foundation manifest write is not atomic

Most important writes use shared atomic helpers, but `golden_vector/app/latest_data.py:75` writes the latest foundation manifest with `manifest_path.write_text(...)`. That can leave a torn/partial JSON file if the process is interrupted.

Concrete fix: replace it with the shared `atomic_write_text` helper. This is small, low risk, and matches the rest of the architecture.

### M2. Optional empty-on-error readers are useful but dangerous if reused incorrectly

`golden_vector/app/model_state.py:199` has a read helper that returns an empty frame on read failure, and `golden_vector/common/parquet.py:29` has `read_optional_parquet`. Optional reads are fine for non-critical panels, but they become dangerous when a required artifact accidentally uses them.

Concrete fix: audit each caller and classify every artifact as required or optional in one artifact catalog. Required user-facing analytics should use checked reads and fail loud. Optional decorative/context panels may degrade calmly.

### M3. Some computation still happens in serve/request paths

Most logic is now backend-computed, but there are still exceptions:

- `golden_vector/serve/candidate_finder_data.py:950` computes scenario Tool B/Tool D sources for gold-dial requests.
- `golden_vector/serve/overview_tool_b.py` and `golden_vector/serve/overview_tool_d.py` run in-memory scenario overrides.
- `golden_vector/serve/detail_panels.py:1496` computes active-window volatility in the serve layer.
- `golden_vector/serve/lenses.py:59` and nearby functions compute older lens scores in serve.

The gold-dial scenario recomputes are a conscious product tradeoff and may be acceptable if measured and cached. The active-window volatility and lens logic are less defensible: they are analytics, not rendering.

Concrete fix: move reusable scenario computation into backend service/model modules, keep serve as orchestration/rendering only, and either persist active-window diagnostics or remove them if they are no longer product-critical.

### M4. Tool A structural storage is large and duplicated

`data/output/tool_a` is the largest output area, around 715 MB locally. The structural metrics latest file alone is roughly 185,838 rows and 11 MB, and older run-stamped copies accumulate.

This is not currently a performance disaster, but it is the main storage growth risk. Tool A structural history is useful, so do not delete it blindly.

Concrete fix: define retention by artifact type. Keep recent run-stamped structural outputs, keep the current manifest-protected one, and consider a chart-friendly derived artifact for UI history. If ad hoc historical analysis becomes common, consider DuckDB over Parquet rather than changing the entire storage engine.

### M5. Convenience CSV writes are not atomic

`golden_vector/ingestion/persist.py:326` writes CSVs directly with `frame.to_csv(...)`. These CSVs are not the authoritative manifest artifacts, so the risk is lower than Parquet, but partial CSVs are still possible.

Concrete fix: add an atomic CSV writer using the same temp-file-to-replace pattern.

### M6. Old Combined output artifacts remain after the product was removed

`data/output/combined/` still exists and holds old artifacts, including large old CSVs. Combined was removed from the product, so these files are confusing and wasteful.

Concrete fix: add a safe cleanup/archive step for deprecated output families. Do not delete automatically without a retention rule, but mark the directory as deprecated and move/prune it once no retained model state references it.

## Data We Are Not Using Well Enough

### Options data is the biggest underused asset

The system now stores rich option data:

- `option_contract_metrics_latest.parquet`: about 11,302 rows.
- `option_oi_strike_points_latest.parquet`: about 602 rows.
- `option_skew_curve_points_latest.parquet`: about 432 rows.
- `option_signal_history_points_latest.parquet`: currently small, because history has only started.

Today the UI uses this for candidate selection, signal summary, skew curve, and OI-by-strike. That is only the first layer.

Better future uses:

- Liquidity stability by ticker, expiry, and moneyness.
- Put/call open-interest and volume ratios by horizon.
- Multi-day skew change, not just latest skew.
- "Is this contract usually tradable?" based on repeated snapshots.
- Backtests of candidate-selection rules.
- A "liquidity reliability" score separate from directional signal.
- Sector-relative option stress over time, especially vs GDX/GDXJ.

This data is perishable and valuable. Keeping full chains was the right choice.

### QA and fetch-status data should be surfaced better

The system stores useful health data:

- `fetch_status_latest.parquet`: about 128 rows.
- `qa_results_latest.parquet`: about 265 rows.
- `normalization_qa_results_latest.parquet`: about 63 rows.

This is mostly used indirectly in banners/status. A beginner user needs a clear "why is this ticker missing or stale?" screen.

Concrete idea: add a Data Health page with ticker, source, last success, current error, stale age, QA failures, and whether that ticker is excluded from confident outputs.

### Official fundamentals are not useful until the current stale state is fixed

The code now has a good shape for fetched official fundamentals, raw statement storage, and official-vs-our-view comparisons. But the current local Tool B artifact is stale and there is no reliable current official-fundamentals artifact in the inspected local state.

Concrete fix: after the gold-dial/fundamentals branch is merged, run a full refresh/fetch-fundamentals cycle and verify the official-vs-our numbers populate. Until then, the comparison UI should fail closed.

### Tool A history could do more than show beta charts

Tool A structural history is expensive and valuable. It could also power:

- Change alerts: "down beta rising quickly."
- Stability checks: "this beta is unstable."
- Regime comparison: current vs 3-month/12-month structural behavior.
- Predictive research/backtesting labels.

Right now the data exists, but its higher-value derivative features are still limited.

### Portfolio data is useful but still early-stage

Portfolio artifacts now provide positions, summary, benchmark betas, hedge sizing, correlations, and value history for current holdings. That is good for M1-M4.

The main missing pieces are expected:

- Real broker import.
- Cash.
- FX-aware USD P&L.
- Lot-level realized/unrealized P&L over time.
- Corporate-action handling.

Do not overbuild this before import exists.

## Should This Be A Real Database?

Not yet.

For the current scale, Parquet plus a manifest is better than forcing everything into SQLite/Postgres. It is transparent, portable, fast enough, and easy to inspect.

The better next step is not "one database." The better next step is an artifact catalog:

- Artifact name.
- Owner pipeline.
- Schema version.
- Required vs optional.
- Privacy class.
- Retention policy.
- Freshness domain.
- Manifest key.
- Whether it is allowed to carry forward.
- Whether UI can render without it.

If option-history research or backtesting becomes much heavier, use DuckDB as a query layer over the existing Parquet files. That gives SQL-style querying without throwing away the current storage model.

## Compute And Performance Review

The current compute bottleneck is not local model math. The cached profile showed:

- Tool A cached path: about 14 seconds.
- Option artifact compute: about 5 seconds.
- Total cached profile: about 20 seconds.

The slow part of real refreshes is fetching external data, especially Yahoo/options. That means further optimization should focus on:

- Better refresh orchestration.
- Reusing stored data when markets are closed.
- Clear stale/fresh rules.
- Per-source retry and failure isolation.
- Avoiding unnecessary live fetches.

Do not spend time micro-optimizing vectorized local calculations unless real stage timings point there.

## Recommended Roadmap

### 1. Immediate hardening

- Regenerate local artifacts after the current schema changes.
- Reject NaN/infinity in manual portfolio store.
- Make the foundation manifest write atomic.
- Add atomic CSV convenience writes.
- Archive/prune deprecated Combined outputs safely.
- Define privacy-aware retention for replay snapshots of manual databases.

### 2. Add an artifact catalog

Create one central registry for artifacts and use it for readers, retention, status, and UI health. This would reduce a lot of scattered "is this optional/current/fresh?" logic.

### 3. Clean the serve boundary

Move remaining analytics out of serve, especially active-window volatility and old lens calculations. Keep only explicit, measured scenario recompute exceptions, ideally routed through backend service modules.

### 4. Use stored data more intelligently

Turn stored option chains, QA rows, and Tool A history into user-facing signals:

- option liquidity stability,
- option signal trend,
- data health drilldowns,
- Tool A beta trend/regime changes,
- official-vs-our fundamentals comparison once refreshed.

### 5. Consider DuckDB later

Use DuckDB only if cross-run option/fundamental/backtest queries become painful. It should query existing Parquet artifacts, not replace the manifest/data-lake design.

## Final Assessment

The system is built on the right foundation: local-first, auditable, manifest-backed artifacts. That is the correct choice for Golden Vector.

The weak spots are mostly around discipline at the edges: a few writes are still non-atomic, a few readers can silently empty, some logic still lives in serve, stale artifacts can survive big schema changes, and we store more option/QA/history data than we currently use.

So the answer is: the storage model is good, but the data governance layer is incomplete. The next senior-engineering move is not a rewrite. It is to add a clear artifact catalog, tighten validation/retention/privacy, and make the stored datasets work harder for the user.
