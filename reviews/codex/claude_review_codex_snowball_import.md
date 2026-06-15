# Claude review — Codex Snowball portfolio dry-run importer

**Reviewer:** Claude (dev-vic)
**Date:** 2026-06-15
**Verdict:** **APPROVE the read-only dry-run as a safe first step. Do NOT write the import yet — a versioned portfolio schema upgrade is required first.** Codex's core conclusions are correct and I verified them first-hand. The importer is conservative and the mappings are right; the open risks are all about the *future* write path.

> Privacy note: this file is committed. I have deliberately kept all position quantities and cost figures OUT of it — the private numbers stay in the gitignored `data/manual/portfolio/snowball_import_dry_run_report.md`.

---

## How I reviewed (first-hand, not from Codex's report)

Read in full: `snowball_import.py`, the `portfolio-import-snowball` CLI command (`cli.py:758-799`), `tests/test_portfolio_snowball_import.py`, the handoff, the private dry-run report, `common/strings.py`, `pipeline.build_ticker_info` (`pipeline.py:141`), `manual_store.validate_lot_input` (`manual_store.py:108-147`), and `config/universe.yaml`.

Independently verified:
- **All 9 ticker→currency mappings** against `universe.yaml` directly (not via the importer).
- The store's **currency reject path** (`manual_store.py:127`).
- **Privacy** via `.gitignore`, `git check-ignore`, and `git ls-files`.
- **HL's structure** via stdlib `zipfile` (openpyxl isn't installed).

---

## Answers to your 8 questions

**1. Is Snowball the current source of truth and HL audit/history only? — YES (verified).**
HL `*.xlsx` sheets are `ISA Transactions` (~330 rows), `Stocks & Shares Transactions` (~70), `Trade analysis` (~342), `Summary` (~55), `Legacy` (~37) — a transaction ledger. Snowball is 23 one-row-per-holding current positions, and its **share counts match the existing store** (e.g. the combined Serabi lines = the store's SRB.L share count). Snowball is the clean current snapshot; HL is history/audit. (HL's `Summary` sheet could later serve as a secondary cross-check of current holdings, but it is not the primary source.)

**2. Is the dry-run conservative enough? — Yes, for a read-only step.**
It blocks aggressively, writes only the gitignored report, never touches `manual_lots.json`, and the store validator is an independent backstop. Caveats below (hardcoded date; no name guard; scale check).

**3. Are the broker-symbol mappings correct? — Yes, all verified against `universe.yaml`:**
`EDVl→EDV.L`, `PAFl→PAF.L`, `ALTNl→ALTN.L`, `AAZ→AAZ.L`, `MTL→MTL.L`, `SRB→SRB.L` (GBP); `AAR→AAR.AX`, `WAF→WAF.AX`, `CLA→CLA.AX` (AUD); `SBI→SRB.L` (manual alias). The lowercase-`l`→`.L` rule, the unique-base rule, and the SBI alias are sound. The dual Serabi rows (`SRB` exact + `SBI` alias) both resolve to `SRB.L` and are correctly flagged **REVIEW** (`multiple_source_rows_same_ticker`), not silently merged. The lowercase-only `l` check correctly distinguishes LSE `EDVl` from US `GOOGL` (uppercase L → not an LSE candidate → unmapped/blocked).

**4. Is blocking non-GBP quote-currency rows correct under the current schema? — YES.**
`validate_lot_input` (`manual_store.py:127`) hard-rejects `buy_currency != info.currency`. Writing a GBP cost basis against an AUD-quoted ticker would corrupt P&L/exposure. Blocking is the right conservative call, and the importer + the store validator block it twice (defense in depth).

**5. Should the next step be a schema upgrade before writing? — YES, required.** See "Schema upgrade" below. Without it, the AUD/CAD majority of the book cannot be represented.

**6. Privacy / gitignore risks? — Clean.** See "Privacy" below.

**7. Are the tests sufficient? — Good happy-path coverage; several gaps to close before import.** See "Tests to add".

**8. Safest implementation plan? — See "Safest implementation plan".**

---

## Findings

| # | Severity | Location | Finding |
|---|---|---|---|
| F1 | **HIGH (future write)** | design / `candidate_manual_lot_payloads` | **Partial-import data-loss trap.** Only 5 of 23 rows are IMPORT_READY, and they are a *minority* of the book. Three AUD tickers you currently hold and that are in the universe (`CLA.AX`, `WAF.AX`, `AAR.AX`) plus `SRB.L` (REVIEW) are blocked. If a writer ever replaces `manual_lots.json` with the IMPORT_READY set, it would **silently delete real positions** and corrupt NAV/weights/Tool-D coverage. The write path must be **all-or-nothing over the full reconciled set**, never an import-ready-only partial write. |
| F2 | MEDIUM | `snowball_import.py:241` | **Hardcoded `buy_date="2026-06-15"`.** A current-holdings snapshot has no real acquisition date, and a literal date is already wrong on any other run day. Record the Snowball **snapshot/export date** as a cost-basis-as-of date (a new field), not a fake buy date. |
| F3 | MEDIUM | `_map_symbol` `snowball_import.py:315` | **No company-name consistency guard.** Mapping is symbol-only; a base/alias collision could map to the wrong company silently. Add a check that the mapped ticker's universe `company` reasonably matches the Snowball `Holdings' name`; mismatch → REVIEW. |
| F4 | MEDIUM | `_parse_snowball_frame:293` | **Currency check is string-equality only — no scale (pence/pounds) validation.** Safe *today* because `.L` tickers are universe-configured `GBP` and both the store and Snowball use pounds, but it would not catch a GBp↔GBP 100× mismatch. `universe.yaml:140` even notes CLA's London line is in pence. The writer should sanity-bound implied cost/share against the latest quote. This is the exact trap CLAUDE.md's "one normalize boundary for currency/pence/units/scale" rule targets. |
| F5 | LOW | data | **Cost-basis divergence (store vs Snowball).** For tickers present in both with matching share counts, the cost bases differ; some existing store costs look like placeholders (one AUD line ≈ `shares × 0.01`). Snowball is the better cost source (supports migration), but confirm Snowball costs are true broker base-currency average cost, and ensure existing AUD costs are not overwritten with GBP numbers. |
| F6 | LOW | `_map_symbol:331-339` | **`unique_base_symbol` heuristic** maps a bare base when exactly one universe ticker shares it (`AAR→AAR.AX`). Correct now; keep the `ambiguous→None` guard and consider also requiring exchange/currency plausibility so a future base collision can't mis-route. |
| F7 | LOW | env | **`openpyxl` is not installed.** HL is `.xlsx`; any HL audit/history importer needs `openpyxl` added to `requirements-dev`/runtime and parsing tests. (I read HL via stdlib `zipfile` for this review.) |
| F8 | NIT | `snowball_import.py:52` | `cost_per_share_source_currency` divides by `shares` unguarded; safe only because `shares<=0` is blocked upstream. Guard it if ever used outside IMPORT_READY rows. |
| F9 | NIT | `BROKER_SYMBOL_ALIASES:33` | Only one alias (`SBI→SRB.L`). Fine now, but as more dual listings appear this hand-map should become data-driven (a universe `aliases` field) rather than a code constant. |

## Verified clean (no action)

- **Mappings + currencies:** all 9 match `universe.yaml` exactly.
- **Read-only:** the CLI builds the dry-run and writes only the gitignored report; it never calls a store-write path (`cli.py:781-786`).
- **Store backstop:** `validate_lot_input` rejects any currency mismatch independently of the importer.
- **Privacy:** `data/manual/portfolio/` is gitignored (`.gitignore:26`); `git check-ignore` confirms the CSV, the HL `.xlsx`, and the dry-run report are all ignored; `git ls-files` shows none are tracked.
- **HL characterization:** transaction history (sheet names + row counts above).
- **Counts reconcile:** 23 parsed / 10 mapped / 5 ready / 2 review / 16 blocked all add up.
- **Conservative blocking + duplicate detection** behave as intended.

## Schema upgrade (the crux — answer to Q5/Q8)

Per lot, separate what is currently conflated into one `buy_currency`:

- `raw_broker_symbol` (e.g. `EDVl`, `SBI`) — provenance.
- `ticker` (canonical, e.g. `EDV.L`) — drives Tool A/B/C/D.
- `quote_currency` — the trading currency from the universe (values the current price).
- `cost_currency` — the currency the cost basis is recorded in (GBP here).
- `cost_basis_total` (+ `shares`) — derive cost/share in `cost_currency`.
- `source_file` + `snapshot_date` — audit + cost-as-of date.

Then **P&L/NAV need an FX step**: current value (quote_ccy) and cost (cost_ccy) must both convert to the portfolio base before subtracting. The portfolio already values multi-currency NAV (`portfolio_totals`); the cost side must use `cost_currency`, not assume cost == quote currency. Relax `manual_store.py:127` to "cost_currency may be any allowed currency; quote_currency comes from the universe" — but as a **versioned schema bump with migration**, not a silent loosening, and keep the allowed-currency/positive-value backstops.

- **Dual listings (SRB + SBI):** represent as two lots under the one canonical ticker, each with its own `cost_currency`/cost; aggregate by canonical ticker in analytics. Don't collapse at import.
- **Out-of-universe holdings** (ETFs `SGLN`/`COPG`/`URNP`/`NUCG`/`COPP`, plus `GOOGL`/`TMC`/`NXE`/`KP2`/`KEFI`): either a portfolio-only instrument registry that can *value* but not run Tool A/B/C/D, or universe rows flagged `portfolio_only`/inactive. Until then they stay blocked — but note they are a **large share of the book**, so NAV is materially incomplete without them.

## Privacy

- All three private files are gitignored **and** untracked (verified). The dry-run report correctly lives under the ignored directory.
- Keep holdings numbers out of any committed file (this review included). Private detail belongs only in the gitignored report.
- Watch-item: ensure any future "candidate `manual_lots.json`" output also writes under `data/manual/portfolio/` (ignored), never a tracked path.

## Tests to add before import

1. `unique_base_symbol` **ambiguous** (two universe tickers share a base) → `None`/BLOCKED.
2. Duplicate detection across two **distinct** raw symbols → same ticker (SRB + SBI) → both REVIEW.
3. Invalid shares / invalid cost / missing fields → BLOCKED.
4. Inactive universe ticker (`info.active is False`) → BLOCKED.
5. `GOOGL` (uppercase trailing L) does **not** trigger the LSE-candidate rule.
6. Empty-row skip.
7. (after F3) name-consistency mismatch → REVIEW.
8. (after F4) implied cost/share wildly off the quote → REVIEW/BLOCKED (pence/pounds guard).
9. (writer) all-or-nothing publish; full reconciliation that reports adds/removes/changes and **never drops** an existing store position without explicit signoff.

## Safest implementation plan (Q8)

- **Phase 0 — DONE:** read-only dry-run + gitignored report. ✓ (this PR)
- **Phase 1 — store schema v2 (versioned):** add the fields above + migrate the current `manual_lots.json`; relax the currency rule to `cost_currency`; keep validation backstops. Tests + Codex review.
- **Phase 2 — FX-aware cost in analytics:** convert `cost_currency`→base so P&L/NAV are correct for AUD/CAD lines (reuse `portfolio_totals` FX path).
- **Phase 3 — out-of-universe instruments:** registry or `portfolio_only` universe rows so ETFs/others value without polluting Tool A/B/C/D.
- **Phase 4 — turn the dry-run into a writer:** all-or-nothing publish; full reconcile vs the current store with a human-signoff diff (adds/removes/changes) **before** write; record `snapshot_date`; enforce the name + scale guards. Never partial-write.
- **Phase 5 — HL importer (needs `openpyxl`):** parse the transaction sheets for history/audit as a separate artifact — not the current-holdings source.

**Order rationale:** the schema + FX must exist before any write, or the AUD/CAD majority of the book cannot be represented; and the writer must reconcile the *full* set, or it silently drops positions (F1).

---

## Bottom line

The dry-run is a correct, conservative, privacy-safe first step, and Codex's analysis (Snowball=current, HL=history, schema upgrade needed) holds up to first-hand verification. Do **not** import yet. The single most important guard for the eventual writer is **F1**: replace the whole portfolio atomically against a reconciled, FX-aware, multi-currency schema — never write the import-ready subset on its own. `manual_lots.json` was not modified.
