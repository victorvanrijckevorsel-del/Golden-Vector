# Shared-Spine Holistic Audit Fixes Review

Date: 2026-06-15
Branch reviewed: `dev-vic`
Commit reviewed: `6a3c98b`

## Verdict

APPROVE WITH CHANGES

The spine sweep is mostly correct and behavior-preserving where intended. The two intentional behavior changes look sound: `^IRX` is fetched only through the options phase and is correctly converted from percent to decimal before Black-Scholes consumers see it, and the Option Trading put/call ladders now follow `hedge_readiness.default_scenarios` with a safe sign mirror for calls.

One medium issue remains: the scorecard reader says the meta file is the atomic pointer, but if that meta file is corrupt/unreadable it silently falls back to `scorecard_latest.parquet` and can serve a mutable alias as "legacy" data. That is exactly the class of stale/torn-read behavior the change is meant to prevent.

## Checks Run

- `python -m pytest -q`
- Result: `1193 passed in 1139.35s (0:18:59)`

Note: an earlier 15-minute run timed out before completion. The 30-minute run above passed.

## Findings

| Severity | File:line | What is wrong | Why it matters | Concrete fix |
|---|---:|---|---|---|
| MEDIUM | `golden_vector/serve/scorecard_data.py:45-51` | Corrupt scorecard metadata is treated as empty metadata, so the loader falls back to `scorecard_latest.parquet` and can return `available=True` with `legacy_schema_assumed=True`. I verified this with a temp fixture: `{broken` meta plus a valid latest parquet returns available instead of failing closed. | The new reader's whole purpose is to make `scorecard_latest_meta.json` the atomic pointer. Missing run-stamped metadata for a true pre-manifest artifact can be a legacy fallback, but an existing corrupt meta file is not legacy - it is a broken current-state pointer. Falling back to the mutable alias reopens a stale/torn-read path. | Distinguish absent meta from corrupt meta. If the meta path exists but JSON/OSError parsing fails, return `ScorecardData(available=False, error_status="META_CORRUPT")` or `CORRUPT` and do not read the latest alias. Keep latest fallback only when the meta file is absent or when a readable legacy meta lacks `run_stamped_artifact`. Add a test with corrupt meta plus valid latest alias. |
| NIT | `golden_vector/serve/scorecard_data.py:38-43`, `golden_vector/serve/scorecard_data.py:49-51` | The comment says fallback to latest happens only when meta lacks the run-stamped entry, but the code also falls back when meta cannot be parsed because the exception handler resets `meta = {}`. | This is not just wording: the comment states the invariant reviewers will trust. Today it hides the corrupt-meta behavior above. | After the code fix, update the comment to state the exact fallback policy: absent/legacy readable metadata only, never corrupt metadata. |
| NIT | `6a3c98b` commit message / `reviews/codex/claude_spine_holistic_audit_and_fixes.md` | The record says no artifact rebuild is required because changes are reader/serve/constant/config-shape only. That is mostly true for current 2026 data, but the `fetch_risk_free_rate` change is an ingestion behavior change and old option artifacts from a sub-1% `^IRX` regime would keep the bad rate until an options refresh. | The commit message itself notes pre-fix snapshots need an options refresh, so the later "No artifact rebuild required" sentence is too broad. | Reword the record to: no immediate schema rebuild is required; option artifacts only need refresh if they were produced from a low-rate `^IRX` snapshot affected by the old magnitude heuristic. |

## Verified OK

### Risk-Free Rate Unit Change

- `golden_vector/ingestion/fetch_risk_free_rate.py:22-41` fetches `^IRX` from Yahoo history and now divides by 100 unconditionally.
- `golden_vector/ingestion/options_phase.py:106-109` is the fetch entry point; it stores the fetched decimal in the options manifest and summary.
- Downstream consumers such as `golden_vector/features/options_chain.py:103-123` and scenario pricing receive the persisted decimal rate. I did not find a path that feeds an already-decimal persisted value back into `fetch_risk_free_rate`.
- The new test at `tests/test_fetch_risk_free_rate.py:26-37` correctly covers the low-rate bug: `0.50` percent becomes `0.005`, not `0.50`.

### Option Trading Scenario Ladder

- `HedgeReadinessConfig.default_scenarios` is validated as put-side signed returns `<= 0` at `golden_vector/contracts/config_models.py:537-545`.
- `golden_vector/serve/option_trading_data.py:177-184` threads `app_config.hedge_readiness.default_scenarios` into the detail builder.
- `golden_vector/hedge/option_trading.py:272-291` uses that tuple for puts and derives the call ladder via `tuple(-move + 0.0 for move in put_gold_scenarios)`.
- `golden_vector/hedge/scenarios.py:220-231` rejects positive put scenarios, so invalid direct caller input still fails.
- `tests/test_option_trading_data.py:398-423` uses a non-default ladder and pins `0.0` rather than `-0.0`.

### Scorecard Run-Stamped Happy Path

- `golden_vector/lab/scorecard.py:261-265` writes a run-stamped parquet, updates the latest alias, then writes meta with `run_stamped_artifact`.
- `golden_vector/serve/scorecard_data.py:51` resolves via `meta["run_stamped_artifact"]` when present.
- `tests/test_lab_scorecard.py:146-184` covers torn latest alias with good meta.
- `tests/test_lab_scorecard.py:187-232` covers valid-but-stale latest alias with good meta.
- Normal live data has `data/lab/scorecard_latest_meta.json` pointing to `scorecard_20260612T173337Z.parquet`.

### Shared Option Multiplier

- `golden_vector/common/options.py:9` is the single `OPTION_CONTRACT_MULTIPLIER`.
- Imports in `hedge/scenarios.py`, `hedge/option_trading.py`, `hedge/portfolio_totals.py`, and `portfolio/m4_artifacts.py` do not create a circular import.
- Replacing `100.0` with int `100` does not change arithmetic results in the checked sites; Python promotes to float where needed.

### Percent-To-Fraction Consolidation

- `golden_vector/common/numeric.py:38-47` matches the old screening/manual heuristic: values `> 1.0` become percent-scaled, values `<= 1.0` remain fractions.
- The field-gated `manual_store._normalize_numeric_value` path still only applies the heuristic to `royalty_rate` and `tax_rate`.
- The `value == 1.0` boundary remains unchanged: it stays `1.0`, which is important for the screening override validation that rejects discounts `>= 100%`.

### Options Chain Numeric Coercion

- `golden_vector/features/options_chain.py:10-11` now aliases to `common.numeric`.
- I compared ordinary scalar cases against the old `pd.to_numeric(..., errors="coerce")` behavior. The documented `"1_000"` widening is the only normal scalar difference I found. `as_int("inf")` still raises, as it did before.
- Feed/parquet paths normalize option columns with `pd.to_numeric` before these helpers see row scalars, so the underscore widening is not reachable on real Yahoo option data.

### Tool C Dead Knob Removal

- `rolling_volatility_weeks` is gone from `config/tool_c.yaml` and `ToolCConfig`.
- Code search found no in-repo runtime reader for the deleted field.
- The 96 historical `data/runs/**/replay_snapshots/configs/tool_c.yaml` copies still contain it, but replay verification reads hashes and source snapshots, not `ToolCConfig.model_validate` on those old YAML files. That matches the audit record.

### Note Count Extraction

- `golden_vector/serve/overview_helpers.py:18-24` contains the single `note_counts_by_ticker` helper.
- Tool A and Tool B call it at `golden_vector/serve/overview_tool_a.py:39` and `golden_vector/serve/overview_tool_b.py:132`.
- The helper preserves the old `notes.groupby("ticker").size().to_dict()` behavior.

### Day-Count Constants

- `golden_vector/features/options.py:230-236` now uses named constants while preserving the same `252 / 365.25` calculation.

## Sibling / Deferred Items

- I agree `detail_panels` per-request OLS should stay deferred as a dedicated model/persistence change. It is real debt, but fixing it properly requires a Tool A artifact/schema change rather than a local cleanup.
- I agree EV/EBITDA unification should be a careful separate extraction because Tool D has a documented cap and net-cash guard that must not be accidentally flattened into Tool B semantics.
- I agree broad guardrail-token broadening should remain deferred. The current per-surface guardrails are safer than banning broad tokens like `.groupby(` everywhere, which would catch legitimate display-only grouping.
- One sibling worth carrying forward: the scorecard reader should probably share a small "resolve run-stamped artifact from meta, absent-legacy fallback, corrupt-meta fail-closed" helper with the lab dial reader once the corrupt-meta fix is made. Do not add another bespoke version.
