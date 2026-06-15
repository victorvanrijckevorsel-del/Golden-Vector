# Spec — Portfolio Store Schema v2 (build-ready) — for Codex confirm

**Author:** Claude (dev-vic)
**Date:** 2026-06-15
**Status:** REVISED from `claude_portfolio_schema_v2_plan.md` after Codex review (`codex_review_portfolio_schema_v2_plan.md`, verdict NEEDS CHANGES). This is the tightened, field-level spec to confirm before any code.
**Hard rule:** no write to `manual_lots.json` until this ships, is reviewed, and the atomic writer (step 6) lands.

> I verified all three of Codex's HIGH findings first-hand and they are correct — this spec fixes each. One Codex NIT is wrong: `scripts/test_fast.ps1` **does** exist (shipped at `261b905`); Codex reviewed a stale checkout. Verification wording is reworded per Codex regardless.

---

## 0. Decisions carried from the Codex review (all accepted)

- **Base currency:** keep **USD internally** (all existing `*_usd` plumbing stays) and compute a **GBP presentation in the backend** (pipeline). Serve renders persisted fields only — **no FX arithmetic in serve** (fixes the plan's "display-layer conversion" wording, MEDIUM-5).
- **Out-of-universe holdings:** a **portfolio-only instrument registry** (value but don't run Tool A/B/C/D), not extra universe rows.
- **Dual listings (SRB + SBI):** store as **two source lots** mapped to canonical `SRB.L`, each keeping its `raw_broker_symbol` + `cost_currency`; aggregate for analytics, keep source lines for reconciliation.
- **Cost FX:** reuse `merge_fx_asof` (`normalize/calendar.py:26`); do not write a second aligner.

**Two product confirmations still needed from Emanuel:** (a) GBP is the presentation base he wants; (b) genuinely-manual single buys keep a real `buy_date`, while imported snapshot rows use a `cost_basis_as_of_date` (the export date) instead of a fabricated buy date.

---

## 1. Store schema v2 (`manual_lots.json`)

Bump `PORTFOLIO_STORE_SCHEMA_VERSION` **1 → 2** (`models.py:11`). Per-lot fields:

| Field | v1 | v2 | Notes |
|---|---|---|---|
| `id`, `ticker`, `shares`, `note`, `created_at`, `updated_at` | ✓ | ✓ | unchanged |
| `buy_price` + `buy_currency` | ✓ | **removed** | replaced below; `buy_currency` was the *quote* ccy, which is now derived from the universe (`info.currency`) — storing it risked drift |
| `cost_basis_total` | — | **NEW** | total cost in `cost_currency`; per-share derived (`cost_basis_total / shares`) |
| `cost_currency` | — | **NEW** | currency the cost basis is recorded in (e.g. `GBP`); must be in `ALLOWED_PORTFOLIO_CURRENCIES` |
| `raw_broker_symbol` | — | **NEW** | provenance (e.g. `EDVl`, `SBI`) |
| `source_name` | — | **NEW** | `manual` \| `snowball` |
| `source_file` | — | **NEW (nullable)** | e.g. `Snowball Holdings.csv` |
| `cost_basis_as_of_date` | — | **NEW** | snapshot/export date for imports; for manual lots = `buy_date` |
| `buy_date` | ✓ | **optional** | real acquisition date for manual single buys; null for snapshot imports |

**Quote currency is NOT stored** — derived at valuation from `info.currency` (universe).

### Read-time migration (v1 → v2), LOW-1
- In `_parse_store_payload` (`manual_store.py:150`): when `schema_version == 1`, migrate **in memory** to typed v2 lots — `cost_basis_total = shares*buy_price`, `cost_currency = buy_currency`, `raw_broker_symbol = ticker`, `source_name = "manual"`, `source_file = null`, `cost_basis_as_of_date = buy_date`. **Do not rewrite the file on read.**
- Write v2 to disk **only** on an explicit save/import/edit path, **after** a timestamped backup of `manual_lots.json` under the gitignored `data/manual/portfolio/`.
- Keep strict rejection of malformed/unknown versions and malformed v2 fields. Tests: v1→v2 read yields identical behaviour for existing data; malformed v2 rejected; **no silent rewrite on read**.

`PortfolioLot`/`LotInput` (`models.py:28-52`): replace `buy_price`/`buy_currency` with `cost_basis_total`/`cost_currency` (+ derived `cost_per_share` property in `cost_currency`) + the provenance/as-of fields. Update `_serialize_lot`/`_parse_lot` (`manual_store.py:164-203`).

## 2. Valuation & P&L (the math) — fixes HIGH-1

For each lot, with `quote_currency = info.currency`:

- **Value (unchanged path):** scaled `current_price` (quote ccy, pence→pounds via existing `price_scale_factor`/`minor_unit_adjusted`, `valuation.py`) × `shares` = `value_quote`; `value_usd = value_quote × fx(quote→USD)`.
- **Cost (NEW):** `cost_usd_at_current_fx = cost_basis_total × fx(cost_currency→USD)` — the cost leg uses the **cost-currency** FX, not the quote FX. (Today `cost_usd_at_current_fx` reuses the quote FX, `pipeline.py:598`; this is the core change.)
- **Base P&L:** `pnl_usd_at_current_fx = value_usd − cost_usd_at_current_fx` (correct across currencies).
- **Local P&L:** `pnl_local` / `pnl_fraction_local` are populated **only when `cost_currency == quote_currency`**; otherwise **null/suppressed** (the page must not show AUD-value-minus-GBP-cost). This is the HIGH-1 fix.
- **GBP presentation (backend, MEDIUM-5):** compute `value_gbp`, `cost_gbp_at_current_fx`, `pnl_gbp_at_current_fx` in the pipeline via FX→GBP. Serve renders these; it never converts.

All conversions go through the same FX-as-of lookup (§3), gated on `qa.max_fx_staleness_days`; missing/stale cost FX → degraded (`STALE_FX`), excluded from confident totals (reuse `analytics.py:21,465-468`).

## 3. Backend FX lookup for the cost leg — fixes HIGH-2

`build_portfolio_artifacts` loads `LatestFoundationSnapshot` (`latest_data.py:22`), which today exposes gold/equity/market snapshots but **not** a general FX history; the manifest only carries `raw_fx_snapshot_path` (`latest_data.py:62`, the `raw_fx.parquet`).

- Add a checked path that reads `raw_fx.parquet` from the manifest and returns a per-currency `currency → USD` as-of series for the snapshot date, via `merge_fx_asof` (`normalize/calendar.py:26`) — the same helper `prices_usd.py`/`market_snapshot.py` already use.
- Prefer extending `LatestFoundationSnapshot` with `fx_histories` (per-currency) so valuation has both quote-ccy and cost-ccy FX from one source; reuse, don't duplicate.
- Fail-loud if the cost currency's FX is missing/stale → degrade that line, never silently value at 1.0.

## 4. Artifact schema bump — fixes HIGH-3

Bump `PORTFOLIO_SCHEMA_VERSION` **5 → 6** (`models.py:10`). Update column lists (`pipeline.py:50-134`):

- **`LINE_COLUMNS`:** add `quote_currency`, `cost_currency`, `cost_basis_total`, `raw_broker_symbol`, `source_name`, `cost_basis_as_of_date`, `value_gbp`, `cost_gbp_at_current_fx`, `pnl_gbp_at_current_fx`; `pnl_local`/`pnl_fraction_local` become nullable; drop `buy_currency` (replaced by `quote_currency`+`cost_currency`); keep `cost_usd_at_current_fx`/`pnl_usd_at_current_fx`.
- **`POSITION_COLUMNS`:** replace single `currency` with `quote_currency` (+ `cost_currency` when uniform across the position's lots, else `MIXED`); add the `*_gbp` trio.
- **`SUMMARY_COLUMNS`:** add `total_value_gbp`, `total_cost_gbp_at_current_fx`, `total_pnl_gbp_at_current_fx`.
- **Currency splits (MEDIUM-4):** `currency_split_json` (keyed by `buy_currency`, `pipeline.py:656`) → **two** fields: `quote_currency_split_json` (market-value exposure by trading ccy) and `cost_currency_split_json` (cost basis by cost ccy). Update page copy (`portfolio_page.py:144`).
- **Reader/model-state:** old artifacts render the **calm stale-schema page** until a portfolio rebuild/refresh; update reader schema tests (`reader.py`).

## 5. Snowball importer v2 (still read-only) — fixes MEDIUM-3

- Interpret Snowball `Currency` as **`cost_currency`**, not quote currency.
- For a mapped ticker: carry `quote_currency = info.currency` separately; validate `cost_currency ∈ ALLOWED_PORTFOLIO_CURRENCIES`.
- **Remove `currency_model_gap` blocking on cost≠quote.** New blocking/degrade reasons: unsupported `cost_currency`, or **missing cost-currency FX** for the snapshot date.
- Keep the company-name-consistency guard (review F3) and a cost/share **scale sanity** check vs the latest quote (review F4).
- Replace the fabricated `buy_date="2026-06-15"` (`snowball_import.py:241`) with `cost_basis_as_of_date = Snowball export date` + `source_name="snowball"` + `raw_broker_symbol`.
- Result: AUD-quoted + GBP-cost rows (`AAR.AX`, `WAF.AX`, `CLA.AX`) move from BLOCKED to **representable**, proven by re-running the dry-run (no store write).

## 6. UI (manual entry) — fixes MEDIUM-2

In `portfolio_page.py` (form `:508`, JS `:605`): show the ticker's **quote currency read-only**; capture **`cost_currency`** separately; label the amount **"Cost per share"** (or accept `cost_basis_total` for imported rows). The JS no longer forces one currency to equal the quote. Serve renders/validates shape only; all FX/derivation stays in the backend.

## 7. The atomic, reconciling writer (step 6, after 1–5) — review F1

- Replaces the **whole** portfolio in one transaction (temp file + atomic rename; a mid-write failure leaves the old store intact).
- First emits a **private** reconciliation artifact (under gitignored `data/manual/portfolio/`, **not** committed reviews) classifying **adds / removes / changes** vs the current store, with `raw_broker_symbol`, `cost_currency`, and **blocked/out-of-universe** holdings listed — for explicit human signoff. A currently-held position missing from Snowball is shown as a **removal**, never silently dropped (LOW-2; the existing `reconciliation.py` export lacks these fields).
- Never partial-writes; never writes the import-ready subset alone.

## 8. Tests

- Migration: v1 store → v2 in memory, behaviour identical for existing data; malformed v2 rejected; no silent rewrite on read.
- Valuation: lot with `cost_currency=GBP`, quote `AUD` → `cost_usd` via GBP→USD FX, `value_usd` via AUD→USD FX, `pnl_usd` correct; `pnl_local` is **null**; plus a control lot where cost==quote keeps local P&L.
- GBP presentation fields computed in backend and present in artifacts.
- Stale/missing cost FX → degraded status, excluded from confident totals.
- Artifact schema: v6 columns present; v5 artifacts render the calm stale page.
- Importer v2: AUD+GBP row → representable (not `currency_model_gap`); unsupported cost ccy / missing FX → blocked; name + scale guards.
- Pence `.L`: cost in pounds + scaled price → consistent P&L (no 100× regression).
- Writer: all-or-nothing; reconcile diff lists adds/removes/changes; no silent drops.

## 9. Verification

Targeted `tests/test_portfolio_*` + the new migration/valuation/importer tests, then the full gate (serial or the `scripts\test_fast.ps1` fast lane, which exists as of `261b905`) before any merge. Re-run the Snowball dry-run to confirm the AUD rows become representable and the report reconciles to the full book.

## 10. Build sequence (Codex's revised order, accepted)

1. **This spec** (field/column definitions) — Codex confirm.
2. **Backend FX lookup** — expose cost-currency FX from `raw_fx.parquet` via `merge_fx_asof`.
3. **Store migration + valuation** — v1→v2 lots; cost USD/GBP separate from quote value; suppress local P&L on mismatch.
4. **Artifact schema bump** — `PORTFOLIO_SCHEMA_VERSION` 5→6 + columns + calm stale handling + reader tests.
5. **Snowball dry-run v2** — currency = cost currency; prove AUD rows representable; still no store write.
6. **Atomic full-replacement writer + reconciliation signoff.**

Do not reach step 6 before 1–5 exist (or the AUD majority of the book can't be represented and a partial write would drop positions).

## 11. Open questions for Codex (confirm pass)

1. Field shapes in §1 (especially `cost_basis_total` + derived per-share, dropping stored `buy_currency` in favour of universe-derived `quote_currency`) — agree, or keep `buy_price` per-share instead of a total?
2. §3 — extend `LatestFoundationSnapshot` with `fx_histories`, vs a standalone manifest-FX helper. Preference for the cleaner integration point?
3. §4 — is bumping `PORTFOLIO_SCHEMA_VERSION` to 6 with calm-stale rendering sufficient, or do any consumers need a hard migration of persisted artifacts on disk?
4. Any remaining consumer of `buy_currency`/`cost_local`/single `currency` semantics (serve, `m4_artifacts.py`, exports, model-state) that this field set would still break?
5. Is suppressing local P&L (null) for mixed-currency lots the right UX, or should the page show base/GBP P&L with an explicit "local P&L n/a (cost ≠ quote currency)" note?

---

## ADDENDUM — Codex confirm folded in (FINAL, build-ready)

Codex confirm verdict: **READY WITH MINOR CHANGES** (`codex_review_portfolio_schema_v2_spec.md`). All clarifications below are accepted and verified first-hand against the code; this addendum supersedes the looser wording above where they conflict. **Emanuel confirmed GBP is the presentation base.**

- **A1 (reword the hard rule).** The rule is: *do not overwrite/replace the real `manual_lots.json` from Snowball, and do not auto-rewrite v1 on read.* Normal manual add/edit/delete **remains allowed** after v2 ships, and the **first v2 write of any kind makes a timestamped backup** of the existing store first. (Supersedes the §0/§1/§7 "no write until the writer lands" phrasing, which only ever meant the Snowball full-replace.)
- **A2 (input contract).** Canonical store field is **`cost_basis_total`** (in `cost_currency`). The **manual form accepts `cost_per_share`** and the backend converts to total **at the validation boundary** (`validate_lot_input`); the **Snowball importer writes the total directly**. Tests assert both paths so a per-share value can never be stored as a total.
- **A3 (GBP formulas + status).** FX is `base_currency → USD`, so GBP uses the reciprocal `gbp_to_usd`: `value_gbp = value_usd / gbp_to_usd`, `cost_gbp_at_current_fx = cost_usd_at_current_fx / gbp_to_usd`, `pnl_gbp_at_current_fx = value_gbp − cost_gbp_at_current_fx`. If GBP FX is missing **only for presentation**, keep USD valuation valid and set the GBP fields null + a presentation warning. If **GBP is the cost currency** and GBP FX is missing, **degrade the line** (cost USD can't be computed).
- **A4 (registry before the real writer).** Insert a step: implement **portfolio-only instrument handling** (ETFs/non-miners value but don't run Tool A/B/C/D), **or** make the writer **fail closed** while any non-cash Snowball row is unrepresented, unless Emanuel gives an explicit one-time exclusion. The atomic full-replace writer is **not** built until every Snowball row is representable or explicitly excluded — otherwise "replace the whole book" is dishonest.
- **A5 (leg-specific FX status).** Add a backend-owned `fx_issues_json` (or leg-specific `line_status_reason`) distinguishing **quote FX / cost FX / GBP-presentation FX**. Tests: stale **cost** FX excludes P&L; stale **presentation-only** FX does **not** invalidate USD totals.
- **A6 (raw_fx read detail).** Read `raw_fx.parquet` via the manifest, **validate** columns (`base_currency`, `date`, `fx_rate_to_usd`, `source_symbol`; `fx_pair` present), **split into `{base_currency: frame}`**, then `merge_fx_asof` (`normalize/calendar.py:26`). Do **not** infer currency from file names. (Verified: `standardize.py:74-101` keys FX by `base_currency`.)
- **A7 (source enum, NIT).** `source_name` ∈ {`manual`, `snowball`, `hl`, `ibkr`, `unknown`} (future-proof; tests pin the known values).

### Codex's open-question answers (accepted)
Store `cost_basis_total` canonical (UI converts per-share→total at the boundary); drop stored `buy_currency`, derive quote from the universe; extend `LatestFoundationSnapshot.fx_histories` (not a one-off reader); bump to v6 + calm-stale + **rebuild artifacts** (no hard on-disk migration); suppress local P&L on mixed-currency with the explicit "local P&L n/a (cost ≠ trading currency)" note. Consumer grep set: `manual_store.py`, `models.py`, `pipeline.py`, `m4_artifacts.py`, `portfolio_page.py`, `snowball_import.py`, `reconciliation.py`, `reader.py`, `model_state.py`, `tests/test_portfolio_*`.

### FINAL build sequence (two reviewed checkpoints, then a gated decision)
- **Checkpoint 1 — schema + valuation spine:** `LatestFoundationSnapshot.fx_histories` (A6); v2 store read-migration + backup-on-first-write (A1/A2); v6 artifacts + columns + calm-stale handling; backend USD **and** GBP fields (A3); leg-specific FX status (A5); tests. **No Snowball writer.**
- **Checkpoint 2 — Snowball dry-run v2:** Snowball currency = cost currency; name + scale guards; prove AUD/GBP rows representable; **still read-only**.
- **Then decide** portfolio-only registry (A4) vs the atomic writer — and **do not build the real writer** until every Snowball row is representable or explicitly excluded.

Each checkpoint ships through build → self-review → Codex code review → verify, and `manual_lots.json` is never replaced from Snowball until the final, signed-off, all-or-nothing writer.
