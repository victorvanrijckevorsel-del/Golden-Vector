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
- an official structural Tool A layer that:
  - builds weekly USD-normalized structural samples from the normalized market-data snapshot
  - computes structural delta, regime-split gamma, explicit asymmetry, confidence, and volatility diagnostics for the fixed official windows `6M`, `12M`, and `3Y`
  - writes published Tool A output parquet files under `data/output/tool_a/`
  - writes structural window metrics under `data/output/tool_a/`
  - ranks eligible names by `as_of_date`
  - publishes both full-history and latest-snapshot CSV/parquet exports plus plain-English explanation fields for downstream use
- a Phase 6 Tool B layer that:
  - stores slow-moving manual mining inputs in a local SQLite store at `data/manual/screening/manual_screening.sqlite3`
  - supports direct in-tool edits through `manual-data` and `manual-note` commands
  - can import/export support CSV files when needed for migration or backup
  - computes Layer 1 robustness checks, Layer 2 valuation metrics, target prices, verdicts, and Tool B score/rank
  - publishes both full-history and latest-snapshot CSV/parquet exports under `data/output/tool_b/`
- a thin local workspace layer that:
  - starts with `python main.py workspace` (requires the local Tool B manual-data store; the workspace no longer auto-creates it)
  - gives a browser-based local view for Tool B company inputs and stock notes
  - shows the latest structural Tool A and Tool B snapshot side by side for each stock
  - includes structural Tool A explanation cards, official window tables, and exploratory horizon context
  - surfaces a warning when a stable latest Tool A / Tool B alias is missing or when Tool A and Tool B reference different foundation refresh runs
  - relies on stable latest Tool A / Tool B snapshot files for fast local inspection

Runtime model:
- `update-data` is the explicit refresh step for Yahoo-backed market data
- `foundation` remains as a legacy alias for the same refresh step
- `tool-a` uses the latest validated local market-data snapshot by default
- `tool-b` uses the latest validated local market-data snapshot plus local manual inputs by default
- `compare-horizons` uses the latest validated local market-data snapshot by default
- `workspace` requires the local Tool B store (run `manual-data init` first) and then serves a thin local UI for manual inputs, notes, and latest outputs. It will not silently create or seed the store on start.
- Combined is no longer part of the active backend and will return later only as a side-by-side compare view

Tool A notes:
- official Tool A scoring is now structural-first and uses only `6M`, `12M`, and `3Y`
- the horizon-return ladder remains available only as exploratory context and does not drive the official score
- rows blocked by trailing normalization issues remain visible, but the official Tool A score is withheld
- low-linkage names can still appear in the output, but they are intentionally left unranked when structural delta is too weak
- Tool A ranking uses dense ranking within each `as_of_date`
- gamma is published as `down_beta − up_beta` per anchor window. **Negative gamma is the favorable case** (up-gold sensitivity exceeds down-gold sensitivity); positive gamma is treated as fragility. The workspace cards label this as `Gamma (Down-Up)` to make the convention visible.

Tool B notes:
- Tool B now reads from the local manual-data store at `data/manual/screening/manual_screening.sqlite3`
- legacy support CSV files under `data/manual/screening/` are optional compatibility/import-export paths for the core Tool B support tables, not the primary workflow
- initialize the local manual-data store explicitly with `python main.py manual-data init` before first Tool B use
- `manual-data show` now includes record timestamps for the core manual tables
- `manual-data export-csv` backs up existing support CSV files before overwrite
- stock notes remain in the SQLite store and are not part of the support CSV export path
- Tool B ranking uses dense ranking within each `as_of_date` and `gold_price_assumption`
- per-stock follow-up notes live in the same local store and are managed through `manual-note`
- Tool B published outputs now carry `snapshot_refresh_run_id`, `snapshot_as_of_date`, `snapshot_normalization_status`, `fx_staleness_days`, and the FX policy (`max_staleness_days`, `block_on_stale_fx`) so the published rows can be audited and the workspace can detect mixed-refresh views
- `workspace` is now the easiest day-to-day way to review and edit Tool B manual inputs locally
- the workspace company form treats blank numeric fields as "leave alone" (no-op). To clear a field, use `python main.py manual-data set-company --ticker <T> --clear-fields <field>`.

## Usage

### Daily flow (the short version)

```bash
python main.py refresh        # update-data -> tool-a -> tool-b in one command
python main.py status         # one-screen operational summary
python main.py workspace      # browse + edit in the browser
```

`refresh` chains the three pipeline steps and prints `status` at the end.
If any step fails, it stops early and prints the partial status.
Useful flags:
- `--gold-price 4500` to override the config default for this run only
- `--skip-tool-b` to refresh foundation + Tool A only (handy when manual data is incomplete)

`tool-b` now reads the gold-price assumption from
`config/screening_params.yaml` (`default_gold_price_assumption: 4000`) when
`--gold-price` is omitted, so `python main.py tool-b` works without a magic number.

`status` reports:
- foundation snapshot freshness, status, and refresh-run id
- Tool A row / ranked / withheld counts
- Tool B row / scored / INCOMPLETE counts and the gold-price assumption used
- whether the three artifact families share the same refresh-run id
- per-ticker manual-data coverage (full / partial / blank)

### Individual commands (still supported)

```bash
python main.py update-data
# legacy alias:
python main.py foundation
python main.py tool-a
python main.py manual-data init
python main.py tool-b                     # uses config default_gold_price_assumption
python main.py tool-b --gold-price 4000   # explicit override
python main.py workspace
python main.py manual-data export-csv
python main.py manual-data set-company --ticker NEM --production-oz 6000000 --aisc-usd-per-oz 1300
python main.py manual-data set-verification --ticker NEM --field-name production_oz --verification-status VERIFIED
python main.py manual-note add --ticker NEM --note "Recheck after the next production report" --tag FOLLOW_UP
python main.py compare-horizons --ticker NEM --horizons 5D,10D,45D,3M
```
