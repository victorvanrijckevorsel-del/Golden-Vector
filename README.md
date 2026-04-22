# Golden Vector

A Python engine for gold-stock sensitivity analysis and valuation screening.

Quick architecture map: [docs/golden_vector_architecture_map.md](C:/Users/Emanuel/code/Golden-Vector/docs/golden_vector_architecture_map.md)

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
  - stores slow-moving manual mining inputs in a local SQLite store at `data/manual/screening/manual_screening.sqlite3`
  - supports direct in-tool edits through `manual-data` and `manual-note` commands
  - can import/export support CSV files when needed for migration or backup
  - computes Layer 1 robustness checks, Layer 2 valuation metrics, target prices, verdicts, and Tool B score/rank
  - publishes both full-history and latest-snapshot CSV/parquet exports under `data/output/tool_b/`
- a thin local workspace layer that:
  - starts with `python main.py workspace`
  - gives a browser-based local view for Tool B company inputs and stock notes
  - shows the latest Tool A and Tool B snapshot side by side for each stock
  - relies on stable latest Tool A / Tool B snapshot files for fast local inspection

Runtime model:
- `update-data` is the explicit refresh step for Yahoo-backed market data
- `foundation` remains as a legacy alias for the same refresh step
- `tool-a` uses the latest validated local market-data snapshot by default
- `tool-b` uses the latest validated local market-data snapshot plus local manual inputs by default
- `compare-horizons` uses the latest validated local market-data snapshot by default
- `workspace` bootstraps the local Tool B store if needed, then serves a thin local UI for manual inputs, notes, and latest outputs
- Combined is no longer part of the active backend and will return later only as a side-by-side compare view

Tool A notes:
- names with `regime_tag = "INVERSE"` are visible in the output but intentionally remain unranked
- Tool A ranking uses dense ranking within each `as_of_date`

Tool B notes:
- Tool B now reads from the local manual-data store at `data/manual/screening/manual_screening.sqlite3`
- legacy support CSV files under `data/manual/screening/` are optional compatibility/import-export paths for the core Tool B support tables, not the primary workflow
- initialize the local manual-data store explicitly with `python main.py manual-data init` before first Tool B use
- `manual-data show` now includes record timestamps for the core manual tables
- `manual-data export-csv` backs up existing support CSV files before overwrite
- stock notes remain in the SQLite store and are not part of the support CSV export path
- Tool B ranking uses dense ranking within each `as_of_date` and `gold_price_assumption`
- per-stock follow-up notes live in the same local store and are managed through `manual-note`
- `workspace` is now the easiest day-to-day way to review and edit Tool B manual inputs locally

## Usage

```bash
python main.py update-data
# legacy alias:
python main.py foundation
python main.py tool-a
python main.py manual-data init
python main.py tool-b --gold-price 4000
python main.py workspace
python main.py manual-data export-csv
python main.py manual-data set-company --ticker NEM --production-oz 6000000 --aisc-usd-per-oz 1300
python main.py manual-data set-verification --ticker NEM --field-name production_oz --verification-status VERIFIED
python main.py manual-note add --ticker NEM --note "Recheck after the next production report" --tag FOLLOW_UP
python main.py compare-horizons --ticker NEM --horizons 5D,10D,45D,3M
```
