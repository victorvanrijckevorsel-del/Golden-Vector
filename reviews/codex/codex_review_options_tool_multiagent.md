# Multi-Agent Review - Options Tool Logic And Code

Verdict: NEEDS CHANGES

This was a read-only review of the option stack behind Option Trading, option signals, Candidate Finder option inputs, option refresh/artifact publishing, and the ticker detail option panel. I did not inspect private manual portfolio data and did not edit implementation code.

Review method:

- Local first-hand code review of the ingestion, artifact, hedge, serve, Candidate Finder, and model-state paths.
- Five parallel explorer lenses: data/artifacts, candidate selection/liquidity, signal math, serve/UI boundary, and tests/performance.
- Focused option test baseline: `python -m pytest @option_test_files -q` passed: 146 passed in 190.95s.
- Broader combined option + Candidate Finder test attempt timed out after 124s before producing a result.

## What Is Strong

- The biggest earlier architecture problem is mostly fixed: the serve layer no longer scans raw option chains for the main option UI. `load_option_trading_data()` resolves persisted option artifacts through model-state, and `raw_options_by_ticker` is empty on the read path (`golden_vector/serve/option_trading_data.py:459`, `golden_vector/serve/option_trading_data.py:560`).
- Candidate selection now lives in backend modules (`golden_vector/hedge/options_liquidity.py`, `golden_vector/hedge/option_horizon_selection.py`), with thresholds mostly sourced from `config/hedge_readiness.yaml`.
- Option signals are also backend-built and persisted (`golden_vector/hedge/option_signals.py:103`), not recomputed in the renderer.
- The schema bump to option artifact v3 is explicit and fail-loud in the reader (`golden_vector/contracts/option_artifacts.py:14`, `golden_vector/serve/option_trading_data.py:630`).
- Market-hours stale-signal behavior has a real fail-closed concept via `publish_blockers` (`golden_vector/hedge/option_signals.py:153`, `golden_vector/cli.py:1929`).

## High Findings

### H1 - Derived option feature rows are mutable sidecar state, not manifest-checked

`_append_feature_rows()` rewrites per-ticker feature history files under `data/output/options/features` (`golden_vector/ingestion/options_phase.py:452`). The current options manifest records raw chain snapshots and hashes, but not the derived feature file paths or hashes (`golden_vector/ingestion/persist_options.py:115`). Later, the option artifact builder loads feature rows by ticker from those mutable files (`golden_vector/hedge/option_artifact_sources.py:95`, `golden_vector/hedge/option_artifact_sources.py:106`).

Why this matters: the manifest can point to immutable raw chains while the selected candidates and signals are built from mutable, stale, corrupted, or manually overwritten feature files. That violates the "one coherent current-state pointer" rule.

Fix: persist a run-stamped all-ticker option features artifact for each options run, include its path, schema version, and sha256 in the options manifest/model-state, and load that exact checked artifact. Short-term guard: if a manifest snapshot has no matching feature row for `refresh_run_id`, fail loud instead of silently skipping that ticker.

### H2 - Option artifact publish is not all-or-nothing

`run_option_artifacts_outcome()` writes all option artifacts/latest aliases first (`golden_vector/cli.py:1978`), then persists option signal history (`golden_vector/cli.py:1983`). But `persist_option_signal_history()` can raise after the artifacts are already written, for example through the shrink guard (`golden_vector/hedge/option_signals.py:193`). `persist_option_artifact_frames()` also writes latest aliases one artifact at a time (`golden_vector/ingestion/persist_option_artifacts.py:34`, `golden_vector/ingestion/persist_option_artifacts.py:55`).

Why this matters: a failed option artifact run can leave `*_latest.parquet` aliases ahead of the current model-state manifest. A later model-state publish discovers option artifacts from the mutable latest aliases (`golden_vector/app/model_state.py:622`), so failed work can leak into a future "current" state.

Fix: write option artifacts to run-stamped/staging paths first with `publish_latest_aliases=False`; persist signal history before alias flips or include it in the same staged publish; only flip aliases and publish model-state after every option artifact and history write succeeds. Add a fault-injection test forcing `persist_option_signal_history()` to raise and assert previous aliases/current manifest remain unchanged.

### H3 - A ticker can disappear from the options manifest after a per-ticker pipeline failure

Inside `run_options_ingestion_phase()`, snapshot persistence and feature computation are inside one try block (`golden_vector/ingestion/options_phase.py:145`). The raw snapshot record is appended only after feature computation succeeds (`golden_vector/ingestion/options_phase.py:196`). If feature computation fails after snapshot persistence, the exception path increments error counts and continues (`golden_vector/ingestion/options_phase.py:180`), but the manifest omits that ticker entirely.

Why this matters: downstream readers cannot distinguish "ticker errored" from "ticker was not part of this run." That is dangerous for a screening tool because absence looks clean.

Fix: append a manifest record, or an explicit failed snapshot/error marker, before feature computation. For non-FAIL runs, enforce `len(manifest.snapshots) == options_ticker_count`. Add a regression where `_compute_feature_row()` raises after snapshot persistence.

### H4 - "Strict" selected candidates can be labelled tradable even when the global tier would call them watch

Global tradable spread is 20% (`config/hedge_readiness.yaml:24`), but strict Near-ATM allows 25% (`config/hedge_readiness.yaml:39`) and strict Directional allows 35% (`config/hedge_readiness.yaml:45`). `_liquidity_tier()` would classify spreads above 20% as `watch` (`golden_vector/hedge/options_liquidity.py:965`, `golden_vector/hedge/options_liquidity.py:980`). But `_slot_for_bucket()` forces strict selected candidates to `liquidity_tier="tradable"` (`golden_vector/hedge/options_liquidity.py:589`, `golden_vector/hedge/options_liquidity.py:594`).

Why this matters: Candidate Finder and UI filters trust `candidate.liquidity_tier == "tradable"` (`golden_vector/hedge/option_availability.py:6`). A 25-35% spread contract can be presented as a tradable candidate.

Fix: either require strict candidate acceptance to include `metric.liquidity_tier == "tradable"`, or validate that all strict spread caps are `<= option_liquidity_tradable_spread_pct`. Prefer preserving the metric's actual tier instead of overriding it. Add a regression with a 30% directional spread.

### H5 - Activity "confirmation" is not open-interest confirmation

`_activity_metrics()` computes OI change (`golden_vector/hedge/option_signals.py:639`, `golden_vector/hedge/option_signals.py:645`), but `CONFIRMS_DOWNSIDE` and `CONFIRMS_UPSIDE` use only same-day `volume / open_interest` and side dominance (`golden_vector/hedge/option_signals.py:654`, `golden_vector/hedge/option_signals.py:672`). A high-volume day can be closing trades or churn, not new positioning.

Why this matters: the UI can tell Emanuel that option activity confirms a downside/upside signal when the data only shows volume relative to OI, not an actual build in open interest.

Fix: either require same-side positive `oi_change_valid` plus positive OI change for "CONFIRMS_*", or rename the lane to "Volume pulse" and stop using it as confirmation. If the latter, update labels, help text, and tests so the UI is honest.

## Medium Findings

### M1 - Standalone option-artifact builds can publish mixed-run artifacts

`run_option_artifacts_outcome()` loads latest options, Tool A, and Tool B outside model-state (`golden_vector/cli.py:1883`, `golden_vector/hedge/option_artifact_sources.py:42`). If these latest aliases come from different refreshes, the builder continues and the mismatch becomes only a context warning (`golden_vector/hedge/option_artifact_builder.py:98`, `golden_vector/hedge/option_artifact_builder.py:442`).

Why this matters: selected option candidates combine current option chains with potentially stale betas/fundamentals. That breaks the "one coherent current state" rule.

Fix: before publishing standalone option artifacts, require options `refresh_run_id` to match Tool A/B `snapshot_refresh_run_id`s unless explicitly carrying forward a prior good option state. Add a stale Tool A/B fixture that asserts no latest aliases are advanced.

### M2 - Most-liquid defaults are selected from all tradable contracts, not candidate-backed contracts

`rank_expiry_liquidity()` filters by ticker, side, and DTE window, then aggregates all tradable contracts in the expiry (`golden_vector/hedge/option_horizon_selection.py:70`, `golden_vector/hedge/option_horizon_selection.py:83`). The chosen horizon is stamped on the overview artifact (`golden_vector/hedge/option_artifact_frames.py:303`) and then used by the detail page default (`golden_vector/serve/option_trading_data.py:126`).

Why this matters: a very liquid expiry can win even if its liquid contracts are outside the Near-ATM or Directional candidate buckets. The detail page can default to a "most liquid" window where there is no usable selected candidate for the requested bucket.

Fix: select most-liquid defaults from accepted `OptionCandidateSlot` rows, or filter metrics through the same bucket-fit and strict candidate gates before voting. Stamp the actual candidate-backed horizon/expiry.

### M3 - Overview P&L context can use a different horizon from the detail page default

`build_option_trading_overview()` defaults `preferred_horizon_days` to the signal horizon (`golden_vector/hedge/option_trading.py:182`). Put/call context P&L uses that one horizon (`golden_vector/hedge/option_trading.py:467`, `golden_vector/hedge/option_trading.py:478`). Most-liquid put/call horizons are stamped later in `option_artifact_frames.py` (`golden_vector/hedge/option_artifact_frames.py:76`, `golden_vector/hedge/option_artifact_frames.py:277`).

Why this matters: the overview can show context P&L for 90d while the ticker detail opens on a 180d/230d most-liquid default. One `context_horizon_days` also cannot honestly describe side-specific put and call defaults.

Fix: compute overview context P&L after most-liquid selection using side-specific horizons, or label the overview P&L as signal-horizon-only and add separate `put_context_horizon_days` / `call_context_horizon_days`.

### M4 - Option freshness can say OK while artifact alignment is only WARN

The option freshness domain returns `OK` when required artifacts are usable and on the current schema (`golden_vector/app/model_state.py:1269`, `golden_vector/app/model_state.py:1280`). Alignment warnings are computed separately (`golden_vector/app/model_state.py:993`, `golden_vector/app/model_state.py:1005`).

Why this matters: status/UI callers can say "option data is current" while the model-state alignment layer knows the artifacts are mismatched.

Fix: make option freshness depend on the same coherence gate used by `_alignment_summary()`. If artifacts are usable but misaligned, surface `MISALIGNED`, `CARRIED_FORWARD`, or `UNAVAILABLE`, not `OK`.

### M5 - Candidate Finder gold scenarios still run analytics in GET requests

The workspace route parses `gold_price` and calls `load_candidate_finder_data(..., scenario=...)` (`golden_vector/serve/workspace.py:122`). That path loads foundation/manual/fundamentals and recomputes Tool B and Tool D inside the request (`golden_vector/serve/candidate_finder_data.py:964`, `golden_vector/serve/candidate_finder_data.py:1001`, `golden_vector/serve/candidate_finder_data.py:1026`).

Why this matters: this violates the backend-computes/serve-renders rule. It is also a performance trap as the user experiments with the gold dial.

Fix: move Candidate Finder scenarios into persisted run-stamped artifacts or a background/on-demand build endpoint. The UI should select/read a persisted scenario result.

### M6 - Option detail page still recomputes scenario ladders in request path

The ticker route calls `build_option_trading_detail_data()` (`golden_vector/serve/workspace.py:513`), which calls `build_option_trading_detail()` and computes scenario bundles for selected candidates (`golden_vector/serve/option_trading_data.py:165`, `golden_vector/hedge/option_trading.py:272`, `golden_vector/hedge/option_trading.py:292`).

Why this matters: there is no raw chain scan, so this is bounded, but it is still analytics in serve. If more scenario rows, strategies, or candidates are added, this will drift back toward request-time computation.

Fix: persist per-candidate scenario ladders during option artifact build. Request-time code should only pick the selected persisted ladder and apply trivial quantity/budget scaling.

### M7 - Candidate Finder can turn corrupt current artifacts into partial rankings

`_read_optional_parquet()` catches read failures and returns an empty frame plus a warning (`golden_vector/serve/candidate_finder_data.py:946`, `golden_vector/serve/candidate_finder_data.py:951`). For manifest-resolved Tool A/C/D artifacts, that means a corrupt current artifact can still render a 200 page with sparse rankings.

Why this matters: a warning banner is not enough when a required current model artifact is corrupt. The ranking can look usable but be missing whole dimensions.

Fix: use checked required reads for manifest-resolved artifacts and render a friendly 503/fail-loud page. Keep optional-empty behavior only for explicit legacy/no-manifest transition paths.

### M8 - UI cache miss reads the full per-contract artifact even though serve does not use it

`_read_option_artifact_frames()` loops over every `OPTION_ARTIFACT_NAMES` entry (`golden_vector/serve/option_trading_data.py:619`), including `option_contract_metrics` (`golden_vector/contracts/option_artifacts.py:16`). The loaded `OptionTradingData` uses candidate slots, selected candidates, overview, liquidity, candidate finder inputs, and signal frames, but not raw per-contract metrics (`golden_vector/serve/option_trading_data.py:517`).

Why this matters: `option_contract_metrics` is likely the largest option artifact. First page load after cache expiry pays a cost for data it does not render.

Fix: split "serve-required option artifacts" from "diagnostic/build artifacts." Load only the frames the screen consumes, while still validating required diagnostic artifacts through manifest metadata when needed.

### M9 - OI chart artifact advertises OI change but always writes it unavailable

`OI_STRIKE_POINT_COLUMNS` includes `oi_change` and `oi_change_valid` (`golden_vector/hedge/option_signals.py:47`), but `_oi_strike_points_frame()` hardcodes `oi_change=None` and `oi_change_valid=False` (`golden_vector/hedge/option_signals.py:982`). The renderer then displays only open interest and volume (`golden_vector/serve/option_signal_charts.py:120`).

Why this matters: the artifact contract implies the tool can show OI change, but the chart cannot. This also weakens the "activity confirmation" lane.

Fix: join prior contract metrics into the per-strike artifact and render delta OI, or remove the fields until implemented.

### M10 - Black-Scholes assumes zero dividend/carry

`black_scholes_delta()`, `black_scholes_put_price()`, and `black_scholes_call_price()` use spot, strike, time, risk-free rate, and IV only (`golden_vector/features/black_scholes.py:17`, `golden_vector/features/black_scholes.py:51`, `golden_vector/features/black_scholes.py:80`). Deltas feed strike selection (`golden_vector/features/options_chain.py:95`) and scenario values feed option P&L (`golden_vector/hedge/scenarios.py:163`).

Why this matters: for dividend-paying miners/ETFs and long-dated options, zero carry can bias deltas and call/put values.

Fix: either add a persisted dividend/carry input per ticker or use a forward-price model. If unavailable, disclose clearly: "Black-Scholes assumes zero dividend yield/carry."

### M11 - Raw chain and feature reads lack concrete schema contracts

Raw option chain snapshots are checked for sha256, then read without required columns (`golden_vector/hedge/option_artifact_sources.py:88`). Feature snapshots are also read without a required feature schema/version (`golden_vector/hedge/option_artifact_sources.py:107`).

Why this matters: malformed required inputs can fail later as generic compute errors, or interact with the missing-feature-row behavior above.

Fix: pass `required_columns=RAW_OPTIONS_COLUMNS` for chain snapshots and define a centralized required options feature schema/version.

### M12 - Optionability can disagree with selected-candidate reality

`optionability_tier` is based on total open interest and core put-IV coverage (`golden_vector/features/options.py:247`, `golden_vector/features/options.py:260`). Selected candidates use stricter Near-ATM/Directional liquidity gates (`golden_vector/hedge/options_liquidity.py:711`).

Why this matters: a ticker can show `directly_hedgeable` while both put/call statuses say no liquid candidate. That may be technically explainable, but it reads contradictory.

Fix: rename the tier to describe chain coverage, or derive the user-facing "directly hedgeable" label from usable selected slots in the Options tool.

## Low / Nits

### L1 - Malformed latest options manifest is reported as missing

`_read_options_manifest()` catches all exceptions and returns `None` (`golden_vector/hedge/option_artifact_sources.py:136`). A corrupt JSON manifest is therefore reported like absence.

Fix: catch `FileNotFoundError` as missing; raise `ValueError` for malformed/unreadable JSON.

### L2 - Candidate Finder builder drops `gold_price` when applying custom filters

The gold scenario form preserves hidden query fields (`golden_vector/serve/candidate_finder_page.py:203`), but the main builder form starts with only `custom=1` and its own controls (`golden_vector/serve/candidate_finder_page.py:303`). Applying criteria can silently reset the gold scenario.

Fix: add hidden inputs for query fields not owned by the builder, especially `gold_price`.

### L3 - Option detail window tabs lose sizing state

`_render_window_switcher()` carries `window` and `lens`, but not `side`, `horizon`, `bucket`, `size_mode`, `quantity`, or `budget` (`golden_vector/serve/detail_panels.py:82`).

Fix: preserve the option sizing query state when the option lens is active.

### L4 - Skew curve table labels absolute delta as "Delta"

The backend selects by absolute delta buckets (`golden_vector/hedge/option_signals.py:940`), but the chart table labels the column `Delta` (`golden_vector/serve/option_signal_charts.py:83`).

Fix: label it `Abs Delta` or render signed put/call deltas.

### L5 - Cost-signal wording is too recommendation-like

Column help says `CHEAP favors buying options` (`golden_vector/serve/column_help.py:322`).

Fix: reword to: "CHEAP means options are low versus this model's IV/RV and history checks; it is not a trade recommendation."

### L6 - Midpoint helper is duplicated

`golden_vector/ingestion/fetch_options.py:268` duplicates midpoint logic already available in `golden_vector/features/options_chain.py:50`.

Fix: reuse the existing midpoint helper or move it to `golden_vector/common/options.py`.

## Suggested Fix Order

1. Fix the data spine first: run-stamped option feature artifact, all-or-nothing option artifact publish, and per-ticker error manifest coverage.
2. Fix user-facing candidate honesty: strict/tradable mismatch, most-liquid selection from candidate-backed contracts, and overview/detail horizon mismatch.
3. Fix signal interpretation: rename or harden activity confirmation, implement/render OI change or remove those fields.
4. Tighten serve boundaries and speed: persist option scenario ladders, avoid loading full contract metrics on UI cache miss, fail loud on corrupt Candidate Finder sources.
5. Clean up UI wording and minor query-state issues.

## Tests To Add

- Feature artifact contract: corrupt/missing per-run features fail loud; stale mutable feature file cannot feed current artifacts.
- Fault injection: `persist_option_signal_history()` raises after artifact frames are built; previous latest aliases and current model-state remain unchanged.
- Per-ticker options feature failure: manifest still has an explicit record/error for the ticker.
- Strict spread regression: a 30% directional spread cannot become `tradable`.
- Most-liquid regression: default window must have at least one accepted candidate slot for that side.
- Activity label regression: `CONFIRMS_*` requires positive OI build, or renamed volume-only labels are pinned.
- Candidate Finder corrupt artifact: manifest-resolved Tool A/C/D corruption returns friendly fail-loud page, not partial ranking.
- UI state: custom Candidate Finder criteria preserve `gold_price`; ticker window switcher preserves option sizing query state.

