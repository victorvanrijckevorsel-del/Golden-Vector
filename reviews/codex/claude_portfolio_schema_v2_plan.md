# Plan — Portfolio Store Schema v2 (cost currency ≠ quote currency)

**Author:** Claude (dev-vic)
**Date:** 2026-06-15
**Status:** PROPOSED — for Codex review before any code
**Blocks:** a safe Snowball import (see `reviews/codex/claude_review_codex_snowball_import.md`)
**Hard rule:** no write to `manual_lots.json` until this ships and is reviewed.

---

## 1. The problem (precise)

Snowball reports every holding's **cost basis in GBP** (the user's base/broker currency), but many holdings are **quoted in AUD/CAD/USD** (e.g. `AAR.AX`, `WAF.AX`, `CLA.AX`). The current lot store ties cost to the quote currency:

- `manual_store.py:127` — `validate_lot_input` rejects `buy_currency != info.currency` (the ticker's universe currency).
- `models.py:41` — `cost_local = shares × buy_price`, implicitly in `buy_currency`, which must equal the quote currency.

So today the store can only express "cost is in the same currency the stock trades in." A GBP cost on an AUD stock can't be represented, which is why only 5 of 23 Snowball rows are import-ready and why a partial write would drop real positions (review finding **F1**).

## 2. What already exists — REUSE, don't rebuild

Grepped first (per the no-duplication rule); the multi-currency machinery is already here:

- **FX local→USD:** `valuation.py:73` `market_value_usd = market_value_local × fx_rate_to_usd`; cost likewise → `cost_usd_at_current_fx` (`pipeline.py:598,650,663`). `LineValuation` (`models.py:64-82`) already carries `fx_rate_to_usd`, `value_usd`, `cost_usd_at_current_fx`.
- **Pence→pounds (the GBp trap) is already handled:** `price_scale_factor` + `minor_unit_adjusted` (`models.py:80-81`, `pipeline.py:454-455`). So `.L` cost in pounds is already consistent with scaled prices.
- **FX source:** `normalize/prices_usd.py` + `fx_history` + `qa.max_fx_staleness_days` (used in `benchmark_betas.py:76-79`). The same FX history that gives quote→USD can give GBP→USD.
- **Store versioning + migration hook:** `_parse_store_payload` (`manual_store.py:150-154`) checks `schema_version != PORTFOLIO_STORE_SCHEMA_VERSION` (currently `1`, `models.py:11`). The upgrade path bolts on here.

**Implication:** v2 is an *extension* (one cost-currency dimension + a second FX lookup for the cost side), not a new FX system.

## 3. The simplest thing that could work (proposed first)

**Option A — additive `cost_currency` (recommended starting point).**

- Add one optional field to the lot: `cost_currency` (defaults to `buy_currency`).
- Keep `buy_price` + `buy_currency`, but redefine: `buy_currency` = the **quote** currency (still validated `== info.currency`); `buy_price`×`shares` = cost **in `cost_currency`**.
- Valuation: compute `cost_usd = cost_in_cost_currency × fx(cost_currency→USD)` (new lookup), reusing the existing `fx_history`. `value_usd` is unchanged (price→USD via the quote-currency FX).
- `pnl_usd = value_usd − cost_usd`. P&L is now correct when cost currency ≠ quote currency.

Migration (v1→v2): every existing lot gets `cost_currency = buy_currency` → **identical behaviour for current data** (cost ccy == quote ccy today), so nothing regresses.

- **Pros:** smallest diff; backward-compatible; reuses all FX + pence handling; unblocks Snowball.
- **Cons:** `buy_currency`/`buy_price` semantics get subtle (price is in cost ccy, currency field is quote ccy). Acceptable short-term; clean it in Option B if we like it.

### Considered and rejected (so we don't take the *too*-simple path)
**Option D — convert GBP cost → quote currency at import, no schema change.** Rejected: Snowball gives only a current GBP cost-basis aggregate with **no per-lot purchase date/rate**, so converting GBP→AUD at any single FX rate fabricates a cost basis and corrupts P&L. The whole point is that the cost is genuinely in GBP.

## 4. The cleaner target (Option B — optional, after A proves out)

Restructure the lot to remove the overloading:

- `ticker` (canonical) · `shares` · `cost_total` + `cost_currency` (replaces `buy_price`/`buy_currency`; per-share derived) · `raw_broker_symbol` · `snapshot_date` · `source_file`.
- `quote_currency` comes from the universe (not stored per lot).
- Replace the `buy_currency == quote` rule with `cost_currency ∈ ALLOWED_PORTFOLIO_CURRENCIES`.

Bigger blast radius (model, store, `validate_lot_input`, the serve lot forms `portfolio_page.py`, analytics, tests), so it's a follow-up, not the first step.

## 5. Open decision for Codex/Emanuel — base currency

Today the base is **USD** (`value_usd`, `nav_value_usd`, …) and `cost_usd_at_current_fx` uses **current** FX (P&L already blends FX moves). Emanuel is a **GBP** investor with a GBP cost basis. Options:

- **(i) Keep USD base internally, add a GBP presentation** for the user-facing P&L/NAV. Least churn (all `*_usd` plumbing stays); display-layer conversion to GBP. **My lean.**
- **(ii) Switch base to GBP.** More faithful to the user, but touches every `*_usd` field/artifact — large, risky, and not required to fix the cost-currency bug.

Recommend (i) now; revisit (ii) only if the USD framing confuses the GBP-native reports.

## 6. Migration & safety

- Bump `PORTFOLIO_STORE_SCHEMA_VERSION` 1→2; add an explicit upgrade branch in `_parse_store_payload` that fills `cost_currency=buy_currency` (and, for Option B, `raw_broker_symbol=ticker`, `snapshot_date=buy_date`).
- **Back up `manual_lots.json`** (timestamped copy under the gitignored `data/manual/portfolio/`) before the first v2 write.
- Keep all existing validation backstops (allowed currencies, positive values, future-date guard).

## 7. The atomic, reconciling writer (the F1 guard — most important)

Only after §3–§6 land:

- The importer becomes a writer that **replaces the whole portfolio in one transaction**: write to a temp file + atomic rename; never a partial write.
- Before writing, print/persist a **reconciliation diff** vs the current store — adds / removes / share-or-cost changes — for explicit human signoff. A position that exists today but is missing/blocked in Snowball must be surfaced as a **removal**, never silently dropped.
- **Out-of-universe holdings** (ETFs `SGLN`/`COPG`/`URNP`/`NUCG`/`COPP`, plus `GOOGL`/`TMC`/`NXE`/`KP2`/`KEFI`): either a portfolio-only instrument registry that values but doesn't run Tool A/B/C/D, or `portfolio_only` universe rows. Until then they stay out — but the diff must state plainly that NAV is incomplete without them (they're a large share of the book).
- Enforce the review's guards: company-name consistency on the symbol map, and a cost/share sanity bound vs the latest quote (scale/pence guard).

## 8. Tests

- Migration: v1 store payload upgrades to v2 with `cost_currency=buy_currency`; behaviour unchanged for existing data.
- Valuation: a lot with `cost_currency=GBP`, quote=AUD → `cost_usd` uses GBP→USD FX, `value_usd` uses AUD→USD FX, `pnl_usd` correct (with a control lot where cost ccy == quote ccy).
- Stale/missing cost-currency FX → degraded status (mirror the existing `STALE_FX`/`missing_fx` handling, `analytics.py:21,465-468`), excluded from confident totals.
- Writer: all-or-nothing (a mid-write failure leaves the old store intact); reconcile diff lists adds/removes/changes; never drops an existing position without signoff.
- Pence/`.L`: cost in pounds + scaled price → consistent P&L (guard against a 100× regression).

## 9. Verification

- Targeted: `tests/test_portfolio_*` + the new migration/valuation tests.
- Full suite green via the new fast lane (`scripts\test_fast.ps1`, ~3–4 min).
- Re-run the Snowball dry-run: after v2, the AUD rows should move from BLOCKED to import-ready (cost in GBP, quote in AUD), and the dry-run report should reconcile to the full book.

## 10. Open questions for Codex

1. **Option A vs B first?** I lean A (minimal, reversible) then B if the model proves out. Agree, or go straight to B?
2. **Base currency (§5):** keep USD internal + GBP display (i), or switch base to GBP (ii)?
3. **Out-of-universe (§7):** portfolio-only registry vs `portfolio_only` universe rows — which fits the existing universe/config model better?
4. **Dual listings (SRB+SBI→SRB.L):** store as two lots under the canonical ticker (each its own `cost_currency`), aggregated in analytics — agree?
5. **FX for cost:** reuse `fx_history`/`normalize/prices_usd.py` with the same `max_fx_staleness_days` gate for the cost-currency leg — any reason that path won't serve GBP→USD cleanly?
6. Any hidden consumers of `buy_currency`/`cost_local` semantics that Option A's redefinition would break (serve forms, m4 artifacts, exports)?

## 11. Sequence (each its own reviewed step)

1. Schema v2 + migration + valuation cost-currency leg (Option A) — tests + review.
2. (optional) Option B cleanup of the lot shape.
3. Out-of-universe instrument handling.
4. Atomic reconciling writer with signoff diff (turns the dry-run into a real import).
5. HL transaction-history importer (needs `openpyxl`) — separate audit artifact.

**Do not** reach step 4 before 1–3 exist, or the AUD majority of the book can't be represented and a partial write would drop positions.
