# Plan — Snowball apply-writer (load real gold-universe positions into the portfolio store)

For review by: Emanuel (go-ahead required — touches real money) + Codex.
Author: Claude. Status: PLAN ONLY (no code, no write yet).
Scope decision (Emanuel): **gold-universe names now, non-universe (ETFs / Alphabet / Anglo …) later.**

## Goal
Turn the existing read-only Snowball dry-run into an `--apply` path that loads the
import-ready gold-universe positions into `data/manual/portfolio/manual_lots.json`, so a
full refresh then yields the actual portfolio P&L. Real-money data: gitignored, never
committed, atomic write + versioned backup, and a human-approved diff before any write.

## What exists vs what's missing
- EXISTS: `build_snowball_dry_run` (parse + map + classify), `_write_lots` (atomic write
  + `_backup_pre_v2_store` versioned backup), schema v2 (`cost_currency` /
  `cost_basis_total` separate from quote currency), per-lot CRUD.
- MISSING: the bridge that converts import-ready rows → `PortfolioLot`s and writes them
  (the dry-run "never overwrites the manual portfolio store"). This plan builds that.

## Rows in scope (from the current dry-run; verify live at build time)
- 8 IMPORT_READY: EDV.L, CLA.AX, AAZ.L, PAF.L, WAF.AX, MTL.L, ALTN.L, AAR.AX.
- 1 from REVIEW (merge): SRB + SBI → one **SRB.L** lot (4,391 + 4,566 = 8,957 shares;
  cost £14,997.41 + £16,167.04 = £31,164.45). Both rows are the same company (Serabi Gold)
  → a deterministic merge, not a guess.
- → **9 gold-universe lots** total. The 13 blocked ETFs/non-gold rows are out of scope.

## The two decisions that matter (with recommendations)

### D1 — buy_date (Snowball has none)
`PortfolioLot.buy_date` is required, but Snowball is a *holdings snapshot* (no purchase
dates; the report notes "HL stays as the transaction/history source").
- **Recommendation:** for a ticker already in the store, **preserve its existing
  `buy_date`** (the 9 import-ready tickers all already exist in the store, so every
  buy_date is preserved). For any genuinely new ticker, use the Snowball export date and
  flag it. Set `cost_basis_as_of_date` = Snowball export date on every lot.
- **Why safe:** P&L = current market value − `cost_basis_total`; it does **not** depend on
  buy_date, so cost/P&L are exact regardless. buy_date only drives "held since" display,
  and preserving it loses nothing.

### D2 — full-replacement vs current 11 lots
Current store = 11 lots across 9 gold tickers (some tickers have >1 lot). The import is one
lot per ticker.
- **Recommendation:** **wipe-and-replace** the gold-universe lots with the 9 Snowball lots
  (Snowball = source of truth for shares + cost basis, per "upload all real positions").
  Cost bases will change (e.g. CLA.AX £21,832 vs current £32,568; AAR.AX £1,363 vs £1,800).
  The automatic versioned backup (`manual_lots.backup-v{n}-{stamp}.json`) preserves the old
  state for rollback. (If any current lot is a non-gold/ETF ticker it stays untouched — but
  per the store aggregate, all 9 current tickers are gold-universe.)

## Build (apply path)
1. `golden_vector/portfolio/snowball_import.py` (or a new `snowball_apply.py`): a pure
   function `build_snowball_apply_plan(dry_run, current_lots, *, as_of_date)` →
   `(new_lots: list[PortfolioLot], diff)` where each new lot maps:
   `ticker=mapped_ticker, shares, cost_basis_total=cost_basis, cost_currency=source_ccy
   (GBP), buy_price=cost_basis/shares, buy_currency=GBP, buy_date=<preserved-or-as_of>,
   raw_broker_symbol=raw_symbol, source_name="snowball", source_file=<csv name>,
   cost_basis_as_of_date=as_of`. SRB.L is the merged row.
2. `golden_vector/cli.py`: add `--apply` to `portfolio-import-snowball`. Without `--apply`
   = today's dry-run (unchanged). With `--apply`: build the plan, **print the diff**
   (per-ticker: shares old→new, cost old→new, adds/drops), and **require a second explicit
   confirm flag** (e.g. `--confirm-write`) so `--apply` alone only previews. On confirm →
   `_write_lots(new_lots)` (atomic + backup).
3. Never write to a `.json` path that isn't the store; reuse the existing path guards.

## Tests
- Apply-plan mapping: import-ready row → PortfolioLot with correct cost_basis_total /
  cost_currency / buy_price / preserved buy_date.
- SRB.L merge: SRB + SBI → one lot, shares + cost summed.
- Full-replacement diff: current gold lots → Snowball lots (cost basis changes surfaced).
- Safety: `--apply` without `--confirm-write` writes nothing; a backup is created on write;
  blocked/review-unmerged rows are excluded.
- buy_date preserved for existing tickers; cost_basis_as_of_date stamped.

## Sequence after build
1. `--apply` preview → show Emanuel the exact diff. 2. On his "write it" → apply (atomic +
backup). 3. Full refresh (stocks + options) — **paid Yahoo API, needs authorization**, ideally
in US market hours for live option chains. 4. Read actual P&L on the portfolio page.

## Safety summary
Real-money, gitignored, never committed. Two-step apply (preview → confirm). Automatic
versioned backup. P&L-correct regardless of the buy_date question. Out-of-scope rows
(ETFs/non-gold) untouched and deferred.
