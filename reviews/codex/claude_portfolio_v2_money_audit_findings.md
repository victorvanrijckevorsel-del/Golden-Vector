# Portfolio schema-v2 — multi-agent money audit (findings + remediation)

**Date:** 2026-06-15
**Method:** 6-dimension adversarial workflow (review → refute each finding). 19 raw → **16 confirmed**. Several reproduced live.
**Branch:** dev-vic. The current portfolio data is fake placeholder, to be wiped-and-replaced; these are spine-correctness defects.

## Fixed in this pass (HIGH money-correctness + the quick MEDIUM)

| Sev | Finding | Fix |
|---|---|---|
| HIGH | **NaN cost basis → fabricated aggregate gain** (live). Non-finite `cost_basis_total` → `cost_usd = NaN`, passed `is not None` guards, dropped by `sum_optional_floats` → full value beside zero cost = fake gain, status OK. | `_value_lot` resolves `cost_basis` via `optional_finite_float`; non-finite → `cost_usd=None` + `INVALID_COST_BASIS` (degrade); `LineValuation.cost_local` nullable; position/summary already null on missing cost. Regression in `test_portfolio_artifacts_v6.py`. |
| HIGH | **Cost/GBP FX has no staleness bound** — only the quote leg was age-gated; a stale-but-present cost rate valued P&L silently. | `fx_rate_to_usd_asof(..., max_staleness_days=)`; the cost + GBP legs pass `max_fx_staleness_days` → stale → None → cost leg degrades (`MISSING_COST_FX`), GBP presentation nulls (no USD degrade). Regression in `test_portfolio_valuation_v2.py`. |
| HIGH | **Mixed cost-currency `cost_local`/`avg_cost_local` summed without conversion** (GBP+AUD added), mislabeled with the quote currency. | Position `cost_local`/`avg_cost_local` are NA unless every lot's cost ccy == quote ccy and each local cost is finite (the USD/GBP legs carry cross-currency cost). Regression added. |
| HIGH | **v1→v2 migration could brick the store** — a v1 lot with a blank/unsupported currency migrated unvalidated, then re-serialized as strict-v2-invalid → whole store unreadable. | `cost_currency ∈ ALLOWED` is now validated on **both** parse paths → a bad v1 lot fails loud on first read. Regression in `test_portfolio_store_v2.py`. |
| MEDIUM | **inf shares/cost passed Snowball validation → IMPORT_READY** (`inf <= 0` is False). | `_parse_snowball_frame` uses `optional_finite_float` for shares + cost → inf → BLOCKED, excluded from payloads. Regression in `test_portfolio_snowball_import.py`. |

Verification: 76 portfolio/FX tests + 36 in the touched suites green; ruff clean.

## Deferred (with reason / where)

| Sev | Finding | Plan |
|---|---|---|
| MEDIUM | **Currency-split panel coalesces missing cost/P&L to 0.0** (bucket shows full value vs zeroed cost). | Fold into **increment 6** (currency splits rework: per-bucket all-or-null + quote/cost split). |
| MEDIUM | **Snowball `total_cost_basis` sums mixed currencies, hard-labels GBP, includes blocked rows.** | Next snowball pass: per-cost-currency breakdown over import-ready rows; drop the hardcoded GBP. |
| MEDIUM | **v2 strict parse hard-requires legacy `buy_price`/`buy_currency`/`buy_date`** → a v2-shaped (importer) lot can't round-trip. Latent (no writer yet). | **Writer milestone**: make those legacy fields optional on the model (quote derived from the universe) so a genuine v2 lot round-trips without a fabricated buy date. |
| MEDIUM | **Per-lot table mislabels v2 cost total with the quote currency.** Serve-only. | With the serve/UI pass (increment 5/6): label cost with `cost_currency` (already on the line frame). |
| MEDIUM | **Reconciliation export omits v2 columns** (mislabeled/blank for cross-currency lots). Latent. | `m4_artifacts`: add cost/quote currency + USD/GBP legs to `RECONCILIATION_EXPORT_COLUMNS`. |
| MEDIUM | **Snowball F4 cost/share scale (pence/pounds 100×) guard absent** (spec-mandated). Read-only today. | **Writer milestone** (needs the latest scaled quote threaded in): implement the F4 ratio check before the atomic writer values the cost leg. |
| LOW | **Snowball reconciliation table reports quote-currency cost for v2 lots.** Read-only dry-run, latent. | Key `_existing_positions` by cost currency + aggregate `cost_basis_total`. |

The deferred items are either serve-display, latent-until-the-writer, or folded into the next increment; none can publish a fake gain or write the real store today.
