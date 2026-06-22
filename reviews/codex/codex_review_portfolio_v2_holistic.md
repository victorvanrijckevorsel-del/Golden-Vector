# Codex Review - Portfolio Schema v2 Holistic

Verdict: **NEEDS CHANGES before the writer / real Snowball import milestone**

The core v2 spine is much stronger than the earlier checkpoints: strict v2 parsing is in place, v1 read-migration is read-only, cost-currency FX is backend-only, same-currency cost now uses `cost_basis_total`, aggregate cost/P&L is all-or-null for missing cost legs, and stale cost/GBP FX is bounded. I did not find a remaining generic partial-cost fake-gain path in the new all-or-null aggregation.

Two high-severity findings remain: stale quote FX is still used for USD P&L, and the Snowball dry-run report path can overwrite the real portfolio store if pointed at it. Both should be fixed before any real portfolio import workflow is trusted.

## Review Method

I used three parallel read-only reviewer agents and then verified/refuted their findings locally:

- Money / aggregation / FX reviewer.
- Store migration / Snowball dry-run safety reviewer.
- Artifact / serve / model-state consistency reviewer.

Local focused tests run:

```powershell
$files = Get-ChildItem tests -Filter 'test_portfolio_*.py' | ForEach-Object { $_.FullName }
python -m pytest @files tests/test_fx_histories_split.py -q
```

Result: **82 passed**. I also reproduced the stale-quote-FX issue with an inline synthetic valuation; no private portfolio data was printed.

## Findings

| Severity | Location | Finding | Why It Matters | Fix |
|---|---|---|---|---|
| HIGH | `golden_vector/portfolio/pipeline.py:466`, `golden_vector/portfolio/pipeline.py:472`, `golden_vector/portfolio/pipeline.py:527`, `golden_vector/portfolio/pipeline.py:847` | Stale quote FX is flagged but still used to publish USD value, USD cost, and USD P&L. A non-USD line with `fx_staleness_days > max_fx_staleness_days` gets `line_status = STALE_FX`, but `value_major_unit_price()` still values it with the stale quote FX and summary P&L is still published. | This can show real-looking USD P&L from a stale quote-currency FX rate. That violates the rule Emanuel has pushed repeatedly: degraded data must be flagged **and excluded**, not flag-only. | For non-USD stale quote FX, keep local value if useful, but null `value_usd`, `cost_usd_at_current_fx`, `pnl_usd_at_current_fx`, GBP presentation, and all aggregates that depend on them. Add a regression with stale CAD/AUD quote FX proving line, position, summary, hedge exposure, and currency split do not publish USD P&L. |
| HIGH | `golden_vector/cli.py:429`, `golden_vector/cli.py:770`, `golden_vector/portfolio/snowball_import.py:127` | `portfolio-import-snowball --report` can overwrite `data/manual/portfolio/manual_lots.json`. The CLI help promises the dry-run never overwrites the manual portfolio store, but `--report` accepts any path and `write_snowball_dry_run_report()` writes Markdown there directly. | This is a real store-corruption path. A typo or bad command can replace the JSON store with a Markdown report, with no validation and no portfolio backup. | Refuse report paths equal to `manual_lots.json`, any existing `.json` under the manual portfolio dir, and ideally anything outside the private manual portfolio report directory unless explicitly whitelisted. Use atomic write for the report and add a test that `--report .../manual_lots.json` fails and leaves the store byte-identical. |
| MEDIUM | `golden_vector/app/model_state.py:70`, `golden_vector/app/model_state.py:999`, `golden_vector/portfolio/reader.py:52` | M4 portfolio artifacts are recorded/read but excluded from model-state alignment. `PORTFOLIO_ARTIFACTS` includes hedge sizing, correlations, value history, and reconciliation export, but `PORTFOLIO_ALIGNMENT_ARTIFACTS` excludes them. | The status/alignment banner can say portfolio alignment is OK while the page reads stale M4/export artifacts from another foundation run. | Include all portfolio artifacts that `load_portfolio_data()` requires in alignment, or create an explicit secondary alignment group for M4 artifacts and surface warnings centrally. Add a fixture with stale `portfolio_hedge_sizing` or `portfolio_value_history` proving alignment warns. |
| MEDIUM | `golden_vector/portfolio/m4_artifacts.py:73`, `golden_vector/portfolio/m4_artifacts.py:327`, `golden_vector/portfolio/m4_artifacts.py:367` | The reconciliation export still drops v2 currency context. It exports `buy_currency`, `cost_local`, `value_local`, and local P&L but omits `quote_currency`, `cost_currency`, USD/GBP cost/P&L fields, and `fx_issues_json`. | For a GBP-cost / AUD-quoted row, the CSV can contain local value and local cost that are different currencies without enough context to tell. This is already listed as deferred, but it must be a writer blocker because the writer milestone depends on a human-signoff reconciliation. | Promote this from "later tidy-up" to a required writer precondition. Add quote/cost currency, `cost_basis_total`, USD/GBP legs, and FX issues to `RECONCILIATION_EXPORT_COLUMNS`; add a GBP-cost/AUD-quote regression. |
| MEDIUM | `golden_vector/portfolio/manual_store.py:71`, `golden_vector/portfolio/manual_store.py:87`, `golden_vector/serve/workspace.py:234` | Imported/distinct-cost lots are protected from legacy edit, but not legacy delete. `edit_lot()` blocks non-manual or distinct-cost lots; `delete_lot()` deletes any matching lot and the workspace route exposes it. | Once real imported rows exist, the old manual page can delete them one-by-one even though editing is explicitly blocked until the v2 UI arrives. This is user-initiated, not silent corruption, but it is inconsistent with the safety posture. | Either block delete for imported/distinct-cost lots until the v2 UI/writer exists, or require a separate explicit imported-lot delete path with clearer copy. Add a regression that an imported distinct-cost lot survives the legacy delete route. |
| MEDIUM | `golden_vector/portfolio/snowball_import.py:98`, `golden_vector/portfolio/snowball_import.py:279`, `golden_vector/portfolio/snowball_import.py:315` | Snowball dry-run still has no cost/share scale sanity guard. It blocks unsupported currency, bad numbers, and name mismatches, but it does not compare cost-per-share against a current scaled quote to catch pence-vs-pounds or 100x scale mistakes. | This is known deferred, but it is exactly the class of bug that inflated LSE prices earlier. It must exist before the real writer can value imported rows. | Writer milestone should thread current quote/snapshot data into the dry-run/import analysis and flag extreme cost/share-to-price ratios. The guard should be advisory/review unless the ratio is clearly impossible. |
| MEDIUM | `golden_vector/portfolio/snowball_import.py:243`, `golden_vector/portfolio/snowball_import.py:247`, `golden_vector/portfolio/snowball_import.py:249` | `candidate_manual_lot_payloads()` emits only `IMPORT_READY` rows. That is fine for a preview list, but unsafe if reused by a future full-replacement writer because REVIEW/BLOCKED rows disappear. | This can recreate the original partial-import trap: replacing a full broker book with only the easy rows. | Rename/scope this helper as preview-only, or make the writer consume a complete reconciliation object that carries ready/review/blocked/removal rows and refuses replacement until every current holding is explicitly accounted for. |
| MEDIUM | `golden_vector/portfolio/pipeline.py:873`, `golden_vector/portfolio/pipeline.py:896` | Portfolio summary `as_of_date` uses the latest snapshot date even when totals contain older per-ticker snapshots. | A mixed-date book can display `2026-06-10` while part of NAV/P&L uses `2026-06-05`. This is not a fake gain by itself, but it mislabels the basis of the whole book. | Store `as_of_date_min`, `as_of_date_max`, and/or `snapshot_date_status = MIXED` when dates differ. Render the range on the page. |
| LOW | `golden_vector/serve/column_help.py:636`, `golden_vector/serve/column_help.py:640` | Portfolio help text still says Avg Cost and P&L are local-currency numbers without explaining that they are intentionally blank for cross-currency cost lots. | The backend correctly suppresses those fields for mixed cost/quote currency, but the help text still describes the old behavior. | Update copy: local Avg Cost/P&L only appears when cost currency equals trading currency; otherwise use USD/GBP P&L. |

## Confirmed Solid

- v1 -> v2 migration is read-only and safe for valid v1 rows; no rewrite on read.
- Strict v2 parsing is fixed: missing v2 money/provenance fields are rejected rather than backfilled from v1 fields.
- Backup-on-first-v2-write exists for valid pre-v2 stores.
- Snowball `Currency` is now interpreted as cost currency, not quote currency.
- Same-currency P&L now uses canonical `cost_basis_total`, not legacy `shares * buy_price`.
- Missing/non-finite cost basis and missing cost FX no longer produce aggregate fake gains.
- Cost FX and GBP presentation FX use `fx_rate_to_usd_asof(..., max_staleness_days=...)`.
- Serve mostly renders persisted artifacts; I did not find portfolio ratio/P&L arithmetic reimplemented in `serve/portfolio_page.py`.

## Deferred Items To Treat As Writer Blockers

These were already known, but the holistic review confirms they are not optional if the next milestone writes real holdings:

- Reconciliation export v2 context (#4 above).
- v2 model round-trip without legacy `buy_price` / `buy_currency` / `buy_date` when the real writer creates true v2 rows.
- Snowball cost/share scale guard (#6 above).
- Full-replacement writer must consume a complete reconciliation object, not `candidate_manual_lot_payloads()` alone.
