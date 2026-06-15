# Codex review request — Portfolio Schema v2, Checkpoint 1 increments 1 & 2

**Author:** Claude (dev-vic)
**Date:** 2026-06-15
**Spec:** `reviews/codex/claude_portfolio_schema_v2_spec.md` (FINAL, you confirmed READY WITH MINOR CHANGES)
**Scope of THIS review:** the first two increments of Checkpoint 1 only — the FX foundation and the store v1→v2 migration. **Not** valuation/GBP/artifacts/UI/importer/writer (those are increments 3–6 + Checkpoint 2, deliberately not built yet).

## Commits to review (on `dev-vic`)

| Commit | Increment | Files |
|---|---|---|
| `fcb368e` | 1 — per-currency FX foundation | `golden_vector/normalize/calendar.py`, `golden_vector/app/latest_data.py`, `tests/test_fx_histories_split.py` |
| `31f16b5` | 2 — lot model + store v1→v2 migration | `golden_vector/portfolio/models.py`, `golden_vector/portfolio/manual_store.py`, `tests/test_portfolio_store_v2.py` |

Diff: `git diff cce7599..31f16b5 -- golden_vector/normalize/calendar.py golden_vector/app/latest_data.py golden_vector/portfolio/models.py golden_vector/portfolio/manual_store.py tests/test_fx_histories_split.py tests/test_portfolio_store_v2.py`

## Design context (so you don't flag intentional gaps)

This is the **expand** phase of an expand→migrate→contract migration. Increment 2 **adds** the v2 fields (`cost_currency`, `cost_basis_total`, `raw_broker_symbol`, `source_name`, `source_file`, `cost_basis_as_of_date`, `cost_per_share`) **alongside** the legacy `buy_price`/`buy_currency`, which stay until increments 3–6 migrate every consumer (valuation, artifacts, serve), then drop in the contract phase. So the build is intentionally green with old + new fields coexisting. Nothing values the cost-currency leg yet (increment 3).

`manual_lots.json` is **untouched**; the real store only migrates to v2 on the next explicit edit, after a backup.

## What was built

**Increment 1 — FX foundation (additive):**
- `split_fx_histories_by_base_currency(raw_fx)` (`calendar.py`): validates `base_currency/date/fx_rate_to_usd/source_symbol`, groups by `base_currency` (upper-cased), output feeds the existing `merge_fx_asof`. USD absent by construction (rate 1.0); consumers must fail/degrade for any other missing currency.
- `LatestFoundationSnapshot.fx_histories` (defaulted) + `load_latest_foundation_snapshot(include_fx_histories=False)` reading `raw_fx.parquet` via the manifest's `raw_fx_snapshot_path`. Default False → existing callers unaffected.

**Increment 2 — store v1→v2:**
- `PORTFOLIO_STORE_SCHEMA_VERSION` 1→2; `_parse_store_payload` accepts **both**.
- v1 lots **migrate in memory on read** (`_parse_lot`): `cost_currency=buy_currency`, `cost_basis_total=shares*buy_price`, `raw_broker_symbol=ticker`, `source_name="manual"`, `cost_basis_as_of_date=buy_date`. v2 lots read their fields directly.
- **No rewrite on read** (A1). First explicit write persists v2 after a **one-time timestamped backup** of the pre-v2 store (`_backup_pre_v2_store`).
- `add_lot`/`edit_lot` share `_lot_from_input` (no duplicated construction).
- `cost_per_share` property falls back to `buy_price` when `cost_basis_total` is None.

## What I'd like you to scrutinise (verify against the code, don't trust this summary)

1. **Migration correctness & safety:** is the v1→v2 derivation right for every realistic v1 lot? Any edge case (missing/zero fields, odd currencies, NaN) where `_parse_lot` would now behave differently than before for a *valid* v1 lot?
2. **A1 — no silent rewrite on read:** confirm `load_lots` never writes; the file stays v1 until an explicit add/edit/delete.
3. **Backup logic:** `_backup_pre_v2_store` backs up once when on-disk version != 2 (including malformed JSON → `existing_version=None` → it still backs up). Is that the behaviour you want? Any atomicity/concurrency concern with the backup + the atomic write?
4. **Additive safety:** the new `PortfolioLot` fields and `LatestFoundationSnapshot.fx_histories` are defaulted/last; do any positional constructors or serializers break? (I checked the keyword constructors in `test_cli_tool_*`.)
5. **FX split contract:** does the split output actually satisfy `merge_fx_asof`/`build_fx_lookup` for the cost leg I'll wire in increment 3? Is uppercasing the `base_currency` key safe vs how `info.currency`/cost currencies are cased elsewhere?
6. **Expand-phase risk:** keeping `buy_price`/`buy_currency` AND `cost_*` in parallel — any place where the two could be read inconsistently before the contract phase removes the old ones?
7. Anything that would make increment 3 (valuation cost-ccy + GBP, suppress local P&L on mismatch, leg-specific FX status) harder or unsafe given these shapes.

## Tests / checks I ran

- `pytest tests/test_fx_histories_split.py` → 4 passed.
- `pytest tests/test_portfolio_store_v2.py` → 4 passed (v1→v2 migration, no-rewrite-on-read, backup+v2-on-add_lot, v2 round-trip with distinct cost currency, version rejection).
- `pytest tests/test_portfolio_m1.py tests/test_portfolio_totals.py tests/test_portfolio_snowball_import.py` → 52 passed (consumers unaffected).
- `ruff check` on all touched files → clean.

## Deliverable

Findings to `reviews/codex/codex_review_portfolio_v2_increments_1_2.md`, severity-tagged with `file:line` evidence. If the migration could lose or corrupt any existing lot, mark it **HIGH**. If it's solid, say so plainly and I'll proceed to increment 3.

## Out of scope (not built yet — please don't flag as missing)

Valuation cost-currency + GBP fields; suppressing local P&L on currency mismatch; v6 artifact columns + calm-stale reader; the UI cost-currency form; the Snowball importer v2; the atomic full-replacement writer. All sequenced in the spec §10 / addendum.
