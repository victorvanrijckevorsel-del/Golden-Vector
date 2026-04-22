# Codex Review - Phase 6 and 7 (Tool B + Combined)

Date: 2026-04-22  
Reviewer: Codex  
Mode: Read-only review. No implementation changes made in this pass.

## 1. Findings

### P1 - Tool B silently drops enabled tickers when the shared market snapshot is missing

Files:
- `golden_vector/screening/pipeline.py:105-123`
- `golden_vector/screening/pipeline.py:136-209`

Why it matters:
Tool B is supposed to be auditable and honest about missing inputs. Right now, if a Tool B ticker is active in `universe.yaml` but does not arrive in `normalized_market_snapshots` because of a fetch problem, normalization gap, or missing FX path, that ticker disappears from Tool B output entirely instead of producing an explicit `INCOMPLETE` row.

What is wrong:
The pipeline uses `snapshots` as the left side of the merge:

- snapshot rows are filtered first
- company inputs and reporting calendar are then left-joined onto those snapshot rows
- iteration only happens over the merged snapshot rows

That means missing-snapshot tickers are never represented in `tool_b_outputs`.

This creates two bad outcomes:
- row-level missingness is hidden inside upstream QA rather than visible in Tool B output
- `tool_b_output_row_count` can be smaller than `tool_b_enabled_ticker_count` without a per-ticker failure row

What needs to change:
Build Tool B from a base frame of all active Tool B tickers, then left-join normalized market snapshots, company inputs, and reporting-calendar data onto that base. Missing snapshot fields should produce explicit `INCOMPLETE` rows with clear failure reasons.

### P2 - The combined join does not validate key uniqueness before merging

Files:
- `golden_vector/combined/join.py:40-44`

Why it matters:
The combined layer is the first place where published Tool A and Tool B outputs are merged into one decision surface. If either upstream output ever contains duplicate join keys, this outer merge will silently create many-to-many expansions and inflate combined rows and ranks.

What is wrong:
`join_tool_outputs()` performs:

```python
tool_a_join.merge(
    tool_b_join,
    how="outer",
    on=["ticker", "as_of_date", "gold_price_assumption"],
)
```

There is no uniqueness assertion on either side first.

Upstream code currently tends to emit unique rows, but the combined layer should defend the contract explicitly because this is exactly where silent duplication becomes expensive and hard to notice.

What needs to change:
Before the merge, assert uniqueness for:
- Tool A: `ticker, as_of_date, gold_price_assumption`
- Tool B: `ticker, as_of_date, gold_price_assumption`

If duplicates exist, fail clearly instead of merging them.

### P2 - Manual template creation is one-time only and drifts when the universe expands

Files:
- `golden_vector/screening/manual_data.py:71-106`

Why it matters:
The repo now presents `data/manual/screening/*.csv` as starter templates for operators. That only works if those templates stay aligned with the active Tool B universe.

What is wrong:
`ensure_manual_screening_templates()` only creates files if they do not exist. Once the CSVs are present, it does not reconcile them against the current Tool B ticker list.

So if a new Tool B ticker is later added to `config/universe.yaml`:
- Tool B will still run
- the new ticker will likely show as incomplete
- but the operator will not get a new blank row in `company_inputs.csv` or `reporting_calendar.csv`

This weakens the “add a ticker by config change” workflow and makes the template convenience stale over time.

What needs to change:
When the files already exist, append missing active Tool B tickers to the template CSVs, or at minimum emit a clear warning listing which configured tickers are absent from the manual files.

### P3 - Combined conviction ignores Tool B confidence entirely

Files:
- `golden_vector/combined/ranking.py:24-49`

Why it matters:
`confidence` is a first-class Tool B output intended to distinguish verified inputs from estimated ones. The current combined verdict can label a name `HIGH_CONVICTION` even when the Tool B side is only `ESTIMATED`.

What is wrong:
`determine_combined_verdict()` uses:
- `screening_verdict`
- `tool_a_score`

It ignores:
- `confidence`
- `coverage_summary`

This is not a formula bug, but it is a meaningful product-quality gap. The combined view currently sounds more certain than the underlying data quality may justify.

What needs to change:
Either:
- incorporate `confidence` into combined verdict/score logic, or
- document explicitly that v1 combined verdicts are data-quality-blind and users must read `confidence` separately

## 2. Residual Risks

1. I could not execute `pytest` or the CLI in this shell because no usable Python launcher is exposed here. This review is static, not runtime-verified.
2. `tool-b` and `combined` currently accept any positive `--gold-price` value, even though `screening_params.yaml` defines an official scenario set. That may be acceptable for exploration, but it is still policy drift unless intentionally documented.
3. `LoadedManualScreeningData.missing_files` no longer reflects the original pre-template-creation missing state once `ensure_manual_screening_templates()` has run. The run summary preserves that information, but the returned manual-data object does not.
4. The combined command orchestrates Tool A and Tool B inside one umbrella run and passes output-shaped DataFrames directly into the combined pipeline. That is close to the intended architecture, but still slightly weaker than reading back the published outputs as the hard boundary.

## 3. Verdict

`READY WITH MINOR CHANGES`

The overall direction is sound. Tool B is now a real standalone engine, and the combined layer is materially implemented rather than scaffolded. The biggest issue I found is not formula correctness; it is coverage honesty. Tool B should not silently omit configured tickers when shared market-snapshot rows are missing. After that, the main gaps are defensive hardening around join uniqueness and better operational handling of template drift.
