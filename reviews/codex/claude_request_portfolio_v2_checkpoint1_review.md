# Codex review request — Portfolio Schema v2, Checkpoint 1 (schema + valuation spine)

**Author:** Claude (dev-vic)
**Date:** 2026-06-15
**Spec:** `reviews/codex/claude_portfolio_schema_v2_spec.md` (FINAL + addendum, you confirmed READY WITH MINOR CHANGES)
**Scope of THIS review:** the **valuation + artifact** half of Checkpoint 1 — increments 3 & 4 — which is new since you last reviewed. Increments 1 & 2 (FX foundation + store v1→v2 migration) were already reviewed by you (`codex_review_portfolio_v2_increments_1_2.md`) and all findings fixed in `5bfcb3b`; re-check only if you want.
**Not in scope (intentionally not built):** the UI cost-currency form (inc 5), the currency-split rename (inc 6), the Snowball importer v2, the atomic full-replacement writer (Checkpoint 2+). Don't flag these as missing.

> Context: the current portfolio holdings are **fake placeholders** (Emanuel confirmed). This whole effort replaces them, via a later wipe-and-replace import, once the spine is safe.

## Commits to review (on `dev-vic`)

| Commit | Increment | What |
|---|---|---|
| `af5d838` | 3a | `fx_rate_to_usd_asof()` — resolve one currency's →USD rate as-of a date |
| `531a126` | 3b | **multi-currency valuation** in `_value_lot`: cost via cost-currency FX, USD+GBP P&L, local-P&L suppression, leg-specific FX status |
| `0abfb71` | 4 | **v6 artifacts**: bump `PORTFOLIO_SCHEMA_VERSION` 5→6, surface v2 fields in LINE/POSITION/SUMMARY, calm-stale |

Diff to read: `git diff 5bfcb3b..0abfb71 -- golden_vector/portfolio/pipeline.py golden_vector/portfolio/models.py golden_vector/app/latest_data.py golden_vector/normalize/calendar.py tests/test_portfolio_valuation_v2.py tests/test_portfolio_artifacts_v6.py tests/test_fx_histories_split.py`

## Design context (so intentional choices aren't flagged)

Expand→migrate→contract. This is the **expand** phase: the legacy `buy_price`/`buy_currency` and the artifact `currency`/`cost_local`/`currency_split_json` columns **still coexist** with the new v2 fields and are dropped only in the contract phase (after the serve/UI migration). The build is intentionally green with old + new side by side. The change is **behavior-preserving for the current single-currency (fake) data** — only a distinct-cost-currency lot takes the new path, and none exist yet.

## The money-critical things to scrutinise (verify against the code, don't trust this)

1. **`_value_lot` cost leg (`pipeline.py` ~456+):** cost → USD now uses the **cost currency's** FX (`fx_rate_to_usd_asof` on the threaded `foundation.fx_histories`), not the quote FX. Same-currency reuses the snapshot quote rate; USD = 1.0; otherwise an as-of lookup. Is the as-of date right (I use the snapshot/current date, matching the existing `at_current_fx` semantics)? Any lot where the old vs new cost_usd would differ for *valid same-currency* data?
2. **Local P&L suppression:** `pnl_local`/`pnl_fraction_local` are null when `cost_currency != quote_currency` (line level), and the **position** frame suppresses local P&L when a position's lots are distinct/mixed cost currency (`cost_ccys != {quote}`). Correct, and does it correctly stay populated for same-currency positions?
3. **GBP presentation (backend):** `value_gbp = value_usd / gbp_to_usd`, `cost_gbp = cost_usd / gbp_to_usd`, `pnl_gbp = value_gbp − cost_gbp`, where `gbp_to_usd` reuses the quote rate when quote is GBP, the cost rate when cost is GBP, else an as-of lookup. **No FX arithmetic in serve** — all in the pipeline. Is the reciprocal right and the GBP-when-cost-is-GBP shortcut sound?
4. **Leg-specific FX status:** missing **cost** FX → `MISSING_COST_FX` (degrades, excludes P&L); missing **GBP-presentation** FX → recorded in `fx_issues` only, **does not** degrade USD (per spec A5). Verify the degrade/no-degrade split is exactly that.
5. **Version bump 5→6 + calm-stale:** old artifacts now raise `PortfolioStaleSchemaError` (reader unchanged) → the existing calm stale page. Any consumer (`m4_artifacts`, `model_state`, serve, exports, reconciliation) that breaks on the new columns or the bump rather than failing calm?
6. **FX threading:** `build_portfolio_artifacts` loads `include_fx_histories=True`; the loader is **graceful** when an older manifest lacks `raw_fx_snapshot_path` (empty histories → GBP/cost legs degrade per-line rather than aborting the build). Is per-line degrade the right call vs fail-loud here?
7. **`_missing_value`** now sets `quote_currency`/`cost_currency` from the lot; the other v2 line fields come from `value.lot.*`. Anything inconsistent for a missing/INVALID line?

## Tests I ran

- `tests/test_portfolio_valuation_v2.py` (4): same-ccy preserved, distinct GBP/AUD cost FX, missing cost FX degrades, missing GBP presentation does NOT degrade USD.
- `tests/test_portfolio_artifacts_v6.py` (3): LINE/POSITION/SUMMARY surface v2 columns; position suppresses local P&L on distinct cost ccy; GBP totals.
- `tests/test_fx_histories_split.py` (6) incl. `fx_rate_to_usd_asof` backward/exact/before/empty + mixed-case split.
- Portfolio + workspace-portfolio + model-state suites green (89 portfolio/FX + 23 page/model-state). **Full `-n 4` suite run as the gate before handing this over** (result recorded with the handoff).
- `ruff check` on all touched files → clean.

## Deliverable

Findings → `reviews/codex/codex_review_portfolio_v2_checkpoint1.md`, severity-tagged with `file:line`. If any path produces a mathematically wrong cost/P&L for a real (current or future Snowball) lot, mark it **HIGH**. If the spine is solid, say so and I'll proceed to Checkpoint 2 (Snowball dry-run v2).
