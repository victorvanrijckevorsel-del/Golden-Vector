# Codex Handoff — Snowball Portfolio Import Dry Run

## What Was Built

I added a read-only Snowball holdings importer:

- `golden_vector/portfolio/snowball_import.py`
- CLI command: `python main.py portfolio-import-snowball`
- tests: `tests/test_portfolio_snowball_import.py`

The command parses `data/manual/portfolio/Snowball Holdings.csv`, maps broker symbols to Golden Vector tickers, compares against the existing `manual_lots.json`, and writes a private markdown dry-run report. It does **not** overwrite `manual_lots.json` and does **not** rebuild portfolio artifacts.

Private detailed report for first-hand review:

`data/manual/portfolio/snowball_import_dry_run_report.md`

That file is intentionally under `data/manual/portfolio/` because it contains position quantities and cost basis.

## Real Dry-Run Result

Command run:

`python main.py portfolio-import-snowball`

Result:

- 23 Snowball rows parsed
- 10 mapped to current Golden Vector tickers
- 5 import-ready under today’s single-currency lot schema
- 2 require review
- 16 blocked
- no portfolio store changed

## Main Finding

Snowball’s `Currency` column is `GBP` for every row. For several non-GBP listings, this appears to be broker/base cost basis, not the security’s quote currency. Today `manual_lots.json` stores one `buy_currency` and the validator requires it to equal the ticker’s configured quote currency. Therefore, forcing this file into the current store would either reject many holdings or silently record GBP cost basis as AUD/CAD/USD cost basis. That would corrupt P&L and exposure.

## What Claude Should Cross-Check

1. Review `golden_vector/portfolio/snowball_import.py` for mapping logic and conservative blocking.
2. Read the private dry-run report in `data/manual/portfolio/snowball_import_dry_run_report.md`.
3. Confirm whether the next architecture step should add separate fields for:
   - quote/trading currency
   - cost basis currency
   - cost basis total
   - broker/source symbol
   - canonical ticker
4. Confirm dual-listing handling before any write path:
   - same company may appear through more than one broker symbol/listing
   - the current one-ticker/one-currency lot model is not enough for those cases
5. Confirm out-of-universe holdings should either be:
   - added to the universe as inactive/portfolio-only rows, or
   - supported by a separate portfolio-instrument registry so they can value but not run Tool A/B/C/D.

## Tests

`python -m pytest tests/test_portfolio_snowball_import.py -q`

Result: `3 passed`.

## Recommendation

Do not replace `manual_lots.json` yet. The safe next milestone is a portfolio store schema upgrade that separates cost currency from quote currency and records the raw broker symbol. After that, Snowball can become the source of truth for current positions, with HL retained as transaction/history evidence.
