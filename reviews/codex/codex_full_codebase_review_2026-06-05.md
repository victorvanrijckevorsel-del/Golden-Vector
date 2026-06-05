# Codex Full Codebase Review - 2026-06-05

## Verdict

**Overall: strong foundation, not yet clean enough to call mature infrastructure.**

The big architecture direction is now right: analytics mostly compute in refresh/pipeline code, persisted artifacts are the normal serving input, the current model-state manifest is the central coherence pointer, Tool C/D reuse the intended shared math seams, and Option Trading no longer scans raw chains in the UI request path.

The most important remaining work is not another feature. It is hardening the data spine so it fails loudly, removing transitional duplicate freshness logic, and reducing the size of the orchestration/UI modules before they become too expensive to reason about.

## Checks Run

| Check | Result |
|---|---:|
| `python -m compileall -q golden_vector` | PASS |
| `git diff --check` | PASS |
| `python -m pytest -q` | PASS - `752 passed in 616.24s` |
| `python -m ruff check .` | NOT AVAILABLE - `No module named ruff` |
| `python -m mypy golden_vector` | NOT AVAILABLE - `No module named mypy` |

The working tree had no tracked source changes before this review file. There are many existing untracked review/data/artifact files in the checkout.

## What Is Working Well

The repository now has a clear layered shape: `ingestion` collects and persists, `features` computes reusable primitives, `model`/`screening` build Tool A/B/C/D outputs, `hedge` owns option/hedge domain logic, `serve` renders the local workspace, and `app` holds config, paths, manifest, replay, and run lifecycle infrastructure.

The current-state manifest work is a major improvement. `golden_vector/app/model_state.py` writes an atomic pointer, snapshots foundation/options manifests to immutable files, resolves tool artifacts through run-stamped outputs, checks alignment, and exposes a shared alignment summary. The tests prove important behavior such as immutable reads after mutable aliases change and fault-injection keeping the old coherent manifest intact.

Option Trading is in a much better architecture than the earlier UI-time chain scan. `golden_vector/hedge/option_artifact_builder.py`, `golden_vector/hedge/option_artifact_frames.py`, and `golden_vector/serve/option_trading_data.py` now put the heavy option scan and candidate construction behind persisted artifacts, with the UI reading the artifact set through the model-state manifest.

Tool C and Tool D are directionally sound. Tool C uses `oriented_percentile` and the shared weekly-return path. Tool D reuses `compute_tool_b_in_memory(...)` at arbitrary gold prices and does not read Tool B's trailing leverage column for stressed leverage. That is the right seam for future gold-stress views.

The test suite is substantial. The strongest areas are manifest coherence, refresh fault behavior, option artifact persistence, Candidate Finder ranking/data joins, Option Trading routes/data, Tool C/D, and pruning safety.

## Findings

### P1 - Current-model Parquet reads can still fail silently into empty data

`read_current_model_parquet(...)` resolves through the model-state manifest, but then catches any read error and returns `pd.DataFrame()` (`golden_vector/app/model_state.py:140`, `golden_vector/app/model_state.py:154`). That is dangerous for a manifest-selected current artifact: a corrupt Tool A/B/C/D Parquet can look like "no rows" rather than "the current build is broken." This conflicts with the architecture rule "fail loud on bad data." Optional side artifacts can be best-effort, but current required artifacts need a checked-read path, ideally through `read_required_parquet(...)`, with a clear UI/status error shape.

### P1 - The CLI is still a god module and is carrying too much business logic

`golden_vector/cli.py` is over 2,800 lines and contains parser construction, command handlers, refresh orchestration, status rendering, replay verification formatting, Candidate Finder output, Tool C/D source loading, and manual-data command logic (`golden_vector/cli.py:100`, `golden_vector/cli.py:447`, `golden_vector/cli.py:1057`, `golden_vector/cli.py:1224`, `golden_vector/cli.py:2560`, `golden_vector/cli.py:2781`). This is the highest maintainability risk in the repo. The code works and tests are green, but every new operational command increases the chance of duplicated reads, duplicated status logic, and hidden coupling. The absolute improvement is to split commands into small modules with one shared status/reporting data model.

### P1 - Alignment/freshness has one source of truth, but old fallback copies still exist

The model-state manifest now owns alignment via `_alignment(...)` and `summarize_model_state_alignment(...)` (`golden_vector/app/model_state.py:645`, `golden_vector/app/model_state.py:291`). However, Candidate Finder, CLI status, and Hedge Readiness still keep local fallback alignment logic for no-manifest compatibility (`golden_vector/serve/candidate_finder_data.py:537`, `golden_vector/cli.py:3025`, `golden_vector/hedge/report.py:1255`). The fallback may be necessary temporarily, but it is exactly the class of duplication that caused the I1-I3 retrofit. Once all normal local states have a model-state manifest, remove or centralize these fallback branches.

### P1 - Option candidate policy is partly hard-coded outside YAML/Pydantic config

The main horizon bands are configured in `config/hedge_readiness.yaml` (`option_dte_bands`) and validated in `HedgeReadinessConfig` (`golden_vector/contracts/config_models.py:91`). But important new selection rules live only as defaults in `OptionLiquiditySettings`: near-ATM OTM range, directional preferred/allowed OTM ranges, strict/watch spread/OI/premium gates, and lottery-like flags (`golden_vector/hedge/options_liquidity.py:76`). These are product policy, not implementation constants. Emanuel is actively tuning "what is a sensible option candidate"; those values must be visible in config, validated, hashed, and recorded as part of provenance.

### P1 - Static quality tooling is missing

`requirements.txt` includes runtime libraries and `pytest`, but no `ruff`, `mypy`, `pyright`, or equivalent. `python -m ruff check .` and `python -m mypy golden_vector` both failed because the tools are not installed. With modules like `cli.py`, `detail_panels.py`, `report.py`, `options_liquidity.py`, and `model_state.py` all large, tests alone will not catch unused helpers, accidental broad catches, wrong import boundaries, or slow drift in type expectations. Add `ruff` first with a narrow ruleset, then add type checking incrementally around contracts/config/model-state/option artifacts.

### P2 - Some serving paths still compute detail analytics request-time

The serve layer no longer computes the full model, which is good. But Tool A detail still rebuilds weekly series and latest horizon returns on each detail-page load (`golden_vector/serve/workspace_state.py:172`, `golden_vector/serve/workspace_state.py:182`, `golden_vector/serve/workspace_state.py:196`), and some window-specific visual diagnostics recompute from sliced weekly data (`golden_vector/serve/detail_panels.py:1402`, `golden_vector/serve/detail_panels.py:1431`). The comments show this was intentionally optimized from a much slower path. Still, the long-term rule should be "UI reads detail artifacts too." If detail pages become slow again, persist the detail-ready weekly/window/horizon slices during Tool A.

### P2 - Direct non-atomic writes remain for some published files

Most Parquet writes use `write_parquet_atomic(...)`, and the model-state manifest uses atomic text writes. Remaining direct writes include the latest foundation manifest (`golden_vector/app/latest_data.py:79`), CSV output aliases (`golden_vector/ingestion/persist.py:354`), and hedge report `latest.md` via direct `write_text` plus `shutil.copyfile` (`golden_vector/hedge/report.py:217`). These are lower risk than `latest_model_state.json`, but they are still public artifacts. Standardize all public writes through `atomic_write_text`, `atomic_write_file`, or a shared atomic CSV helper.

### P2 - Yahoo/yfinance remains the single fragile data vendor

The retry/throttle wrapper is a good start (`golden_vector/ingestion/collection_resilience.py:52`), and collection stats now flow into manifests. But the actual vendor layer is still a thin yfinance wrapper (`golden_vector/ingestion/yahoo_client.py:15`), and `fetch_fast_info(...)` catches all exceptions and returns `{}` (`golden_vector/ingestion/yahoo_client.py:51`). Options ingestion then depends on `fast_info` to determine underlying price (`golden_vector/ingestion/fetch_options.py:108`). This is acceptable for a local prototype, but not decision-grade. Before expanding option workflows further, add clearer user-visible vendor/freshness diagnostics and consider a future vendor abstraction with a second source for quotes/options.

### P2 - Large modules still hide too many responsibilities

The biggest files are still very large: `golden_vector/cli.py`, `golden_vector/serve/detail_panels.py`, `golden_vector/hedge/report.py`, `golden_vector/hedge/options_liquidity.py`, `golden_vector/app/model_state.py`, `golden_vector/screening/manual_store.py`, and `golden_vector/contracts/config_models.py`. Large is not automatically wrong, but these modules combine multiple responsibilities: domain rules, formatting, IO, UI text, validation, and orchestration. The next improvement should be surgical extraction by responsibility, not a rewrite: command modules, status model, option policy config, report section renderers, and model-state artifact readers/builders.

### P2 - Candidate Finder reuses serve data code from CLI

The CLI command `candidate-finder` imports and calls `golden_vector.serve.candidate_finder_data` (`golden_vector/cli.py:81`, `golden_vector/cli.py:580`). The module is mostly data-side, but it lives under `serve`, which blurs the boundary and makes it easier for future CLI behavior to depend on UI-only assumptions. Candidate Finder data assembly should eventually move to a non-serve module, with `serve` only rendering pages and handling query strings.

### P2 - Full-refresh performance is still not guarded by tests or benchmarks

The suite has many unit and fixture tests, but there is no explicit performance gate for `/option-trading`, `/candidate-finder`, or Tool A detail page cold-load time. The progress log says fixture option loading became about 7x faster, but production 60-name timing still needed a real refresh measurement. Add lightweight regression tests or scripts that load the main pages from persisted fixture artifacts and fail when page construction crosses a conservative threshold.

### P3 - Optional readers are sometimes used for manifest-listed data

`read_optional_parquet(...)` is correctly useful for optional context, but some manifest-listed report inputs still degrade to empty frames (`golden_vector/hedge/report.py:984`, `golden_vector/hedge/report.py:999`). That may be an intentional "report best effort" behavior, but it should surface explicit source warnings in the rendered report whenever a manifest-listed chain or feature file is unreadable. Otherwise a report can look complete while silently omitting option data.

### P3 - Some duplicate helper shapes remain

The new `golden_vector/common` helpers are a real improvement, but the scans still show local helpers for formatting, numeric coercion, `_unique_strings`, ticker normalization, and optional Parquet reads across serve/model/hedge modules. Some are domain-specific and fine. The ones to target first are helpers that affect correctness: optional/current Parquet reads, alignment messages, ticker normalization, and atomic CSV/text writes.

### P3 - UI text and renderer size need product cleanup

The Option Trading page is clearer than before, but `detail_panels.py` still assembles a lot of explanatory copy and HTML inline (`golden_vector/serve/detail_panels.py:199`, `golden_vector/serve/detail_panels.py:617`). That makes the tool harder to tune for Emanuel's actual workflow. The next product pass should reduce explanatory paragraphs, make stock price/snapshot/expiry/candidate policy visible in compact places, and keep method/glossary details collapsed.

## What Should Absolutely Improve Next

1. **Make current-artifact reads fail loud.** Split required current reads from optional current reads. A manifest-selected Tool A/B/C/D/options artifact that is corrupt should produce a visible error, not an empty table.

2. **Split `golden_vector/cli.py`.** Move each command handler into a command module and make `cli.py` mostly parser + dispatch. This is the highest leverage cleanup before more milestones.

3. **Finish the manifest-only migration.** Keep no-manifest fallback only as a small shared compatibility layer, or remove it once local data is regenerated. Do not let each screen recompute freshness/alignment differently.

4. **Move all option-selection policy into config.** Near-ATM ranges, directional ranges, strict/watch OI/spread/mid gates, and lottery-like thresholds should live in `config/hedge_readiness.yaml` with Pydantic validation.

5. **Add static checks.** Add `ruff` with a conservative rule set first. Add type checking for config contracts, model-state, parquet contracts, and option artifact dataclasses after that.

6. **Persist or cache remaining detail-page computations.** Tool A detail should eventually be fully artifact-backed, especially if page load starts feeling slow again.

7. **Atomic-write all published outputs.** Foundation manifest, CSV aliases, and markdown latest files should use shared atomic helpers.

8. **Improve market-data diagnostics before adding more option features.** Keep using Yahoo for now if needed, but make stale/missing/partial vendor data unmistakable in status, manifest, and UI.

## Residual Risk

No failing tests or syntax errors were found. The risk is architectural drift: the project is now good enough to build on, but only if the data-spine rules are enforced ruthlessly. The most dangerous backslide would be adding the next feature by reading mutable latest aliases, computing in `serve`, or adding another local helper for freshness, numeric coercion, artifact reads, or option policy.
