# Golden Vector

A Python engine for gold-stock sensitivity analysis, valuation screening, and combined ranking.

## Setup

```bash
python -m venv venv
venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

## Current Status

The repo now includes:

- a package scaffold under `golden_vector/`
- repo-level YAML configs under `config/`
- a CLI entrypoint in `main.py`
- run metadata and audit-log plumbing
- baseline tests for config, registry, run metadata, and raw QA
- a Phase 1 foundation pipeline that fetches:
  - raw equity history
  - raw FX history
  - raw gold history
  - raw Tool B market snapshots
- raw-data persistence to Parquet
- raw QA summaries and fetch-status outputs
- a Phase 2 normalization layer that:
  - converts equity histories into USD
  - normalizes Tool B market snapshots into USD
  - persists normalized parquet outputs under `data/intermediate/`
  - writes normalization QA summaries
- a Phase 3 horizon layer that:
  - computes long-format Tool A horizon returns from USD-normalized prices
  - writes horizon QA summaries
  - supports custom horizon comparison without changing official scoring config
- an initial Phase 4 Tool A output layer that:
  - computes core delta, stability, gamma proxy, regime tags, and Tool A score eligibility
  - writes published Tool A output parquet files under `data/output/tool_a/`
  - ranks eligible names by `as_of_date`
  - publishes both full-history and latest-snapshot CSV/parquet exports for downstream use
- a Phase 6 Tool B layer that:
  - loads manual mining inputs from `data/manual/screening/`
  - creates blank manual CSV templates automatically if they are missing
  - computes Layer 1 robustness checks, Layer 2 valuation metrics, target prices, verdicts, and Tool B score/rank
  - publishes both full-history and latest-snapshot CSV/parquet exports under `data/output/tool_b/`
- a Phase 7 combined layer that:
  - joins published Tool A and Tool B outputs by `ticker`, `as_of_date`, and gold-price scenario
  - emits partial rows when only one side is currently usable
  - computes combined score, combined verdict, and combined rank only when both sides are compatible
  - publishes both full-history and latest-snapshot CSV/parquet exports under `data/output/combined/`

The `foundation` command now runs the shared backbone through raw ingestion, raw QA, USD normalization, and normalization QA. `tool-a` now runs that backbone plus horizon returns and the Tool A metric/ranking layer. `tool-b` now runs the shared backbone plus manual screening/valuation. `combined` now orchestrates Tool A and Tool B under one run and publishes the merged view. `compare-horizons` runs exploratory horizon comparisons for one Tool A ticker.

Tool A notes:
- names with `regime_tag = "INVERSE"` are visible in the output but intentionally remain unranked
- Tool A ranking uses dense ranking within each `as_of_date`

Tool B notes:
- `data/manual/screening/company_inputs.csv` is intentionally blank starter data; the tool will mark missing manual fields as `INCOMPLETE`, not invent them
- Tool B ranking uses dense ranking within each `as_of_date` and `gold_price_assumption`

Combined notes:
- `join_status = COMPLETE` means both Tool A and Tool B published compatible scores for that row
- `join_status = PARTIAL` means only one side was usable, or one side was present but not score-compatible yet
- combined score currently uses a simple 50/50 average of Tool A score and Tool B score as the v1 default
- combined verdict reads Tool B `confidence`, but v1 does not yet downweight the verdict automatically when confidence is `ESTIMATED`; read both fields together

## Usage

```bash
python main.py foundation
python main.py tool-a
python main.py tool-b --gold-price 4000
python main.py combined --gold-price 4000
python main.py compare-horizons --ticker NEM --horizons 5D,10D,45D,3M
```
