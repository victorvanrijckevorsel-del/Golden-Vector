# Codex review request — FULL HOLISTIC review of the new Portfolio (schema v2)

**Author:** Claude (dev-vic)
**Date:** 2026-06-16
**Ask from Emanuel:** a full holistic review of the entire new portfolio. **Please use agent / multi-agent work if your harness supports it** — fan out per dimension and adversarially verify findings (refute each before it counts), the way Claude's money-audit did.

## Scope — the whole portfolio as it now stands

Review `golden_vector/portfolio/` end-to-end plus its touch points, not just the diff:
- `models.py`, `manual_store.py`, `pipeline.py`, `valuation.py`, `snowball_import.py`, `analytics.py`, `reader.py`, `m4_artifacts.py`, `benchmark_betas.py`
- `golden_vector/normalize/calendar.py` (FX helpers), `golden_vector/app/latest_data.py` (FX threading), `golden_vector/serve/portfolio_page.py`
- `tests/test_portfolio_*`, `tests/test_fx_histories_split.py`

Change context (the whole schema-v2 effort on `dev-vic`): `git diff main..HEAD -- golden_vector/portfolio golden_vector/normalize/calendar.py golden_vector/app/latest_data.py golden_vector/serve/portfolio_page.py tests/test_portfolio_* tests/test_fx_histories_split.py`. Full suite is green (**1229**), ruff clean.

## What schema v2 does (one paragraph)

The portfolio holdings on the tool today are **fake placeholders** (Emanuel confirmed); this work makes the tool able to load his real Snowball broker export. The core change: a holding's **cost currency** (the GBP he paid) is separated from its **trading/quote currency** (AUD/CAD/USD). Cost converts to USD via the *cost* currency's FX; P&L is computed in USD **and GBP** (his base) in the backend; local P&L is suppressed when the currencies differ; the store migrates v1→v2 in memory with a backup; artifacts bump to v6 with calm-stale; and a **read-only** Snowball dry-run classifies which rows are import-ready. No writer exists yet — `manual_lots.json` is never modified.

## Prior review passes (please BUILD ON these, don't redo)

1. Codex reviewed the **plan** and the **spec** (`codex_review_portfolio_schema_v2_plan.md`, `..._spec.md`) → NEEDS CHANGES then READY; all folded into `claude_portfolio_schema_v2_spec.md` (FINAL + addendum).
2. Codex reviewed **increments 1–2** (`codex_review_portfolio_v2_increments_1_2.md`) and **Checkpoint 1 / increments 3–4** (`codex_review_portfolio_v2_checkpoint1.md`) → all findings fixed.
3. Claude ran a **6-dimension adversarial agent money-audit** → 16 confirmed (incl. a live NaN fake-gain); HIGHs + quick MEDIUM fixed; the rest recorded in **`reviews/codex/claude_portfolio_v2_money_audit_findings.md`** (read this — it lists exactly what's fixed vs deferred).

So the spine has had **3 passes**. The holistic review is to catch what's left — especially **cross-cutting / interaction** defects and anything the per-piece passes missed.

## Where to look hardest (money-critical)

- **Aggregation invariants:** the all-or-null discipline (position + summary + the new per-currency splits) — can any path still publish a partial cost beside a full value (a fake gain), via NaN, missing FX, mixed currency, or an unvalued lot?
- **FX correctness:** cost-currency leg + GBP presentation via `fx_rate_to_usd_asof` with the new `max_staleness_days` gate; the quote leg via the snapshot. Any wrong/sign-inverted/stale rate, or a pence/pounds (GBp) scale slip, reaching P&L?
- **Migration safety:** v1→v2 in-memory migration, strict-v2 parse, backup-on-first-write, edit-block on imported lots, the both-paths `cost_currency` validation. Any path that loses, mis-migrates, or bricks the store, or auto-writes the real file?
- **Snowball dry-run:** cost-currency interpretation, the guards (unsupported cost ccy, name mismatch), per-currency totals, and that it is strictly read-only.
- **Consistency across layers:** do `pipeline` artifacts, `analytics`, `m4_artifacts` (reconciliation export), `reader`, and `serve` agree on what each column means for a v2 cross-currency lot? (Mislabels are the main residual risk.)

## Known-deferred (please confirm/prioritise rather than just re-flag)

These are recorded as deferred to the **writer milestone** (the writer isn't built):
- **Reconciliation EXPORT** (`m4_artifacts.RECONCILIATION_EXPORT_COLUMNS`) still carries the legacy cost legs; needs cost/quote-currency + USD/GBP columns. Matters most when the writer emits the human-signoff diff.
- **v2 round-trip:** `_parse_lot` parses legacy `buy_price/buy_currency/buy_date` unconditionally; a genuine v2 (importer) lot can't round-trip without them. Fix = make them optional on the model (quote derived from the universe) at the writer milestone.
- **F4 cost/share scale (pence/pounds 100×) guard** in the Snowball importer — needs the latest scaled quote threaded in; do it before the writer values the cost leg.

## Out of scope (not built — don't flag as missing)

The out-of-universe instrument registry and the atomic full-replacement writer (the step that actually loads the real holdings). Those are the next milestone, behind a human-approved diff.

## Deliverable

Findings → `reviews/codex/codex_review_portfolio_v2_holistic.md`, severity-tagged with `file:line`. Mark **HIGH** anything that can publish wrong/fake P&L or lose/corrupt store data. If you ran agents, say what dimensions you fanned out and what survived refutation. If the portfolio is sound, say so plainly and I'll proceed to the writer milestone.
