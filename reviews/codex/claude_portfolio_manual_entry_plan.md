# Plan — Portfolio M1: manual position entry + P&L (the new first milestone)

**Author:** Claude Code (Opus 4.8)
**Status:** for review → build. This is **M1 of the portfolio tool** and a dependency of everything in plan v4 — it gets the real book (with cost basis) into the system. Builds on the v4 architecture (`golden_vector/portfolio/` package, artifacts, manifest, privacy).
**Why first:** manual entry of buy price + date supplies the **cost basis the IBKR export lacks**, which **turns real P&L on** (no more greyed stub) and lets Emanuel use the tool immediately.
**Locked decisions (Emanuel):** each buy is its **own line** (lots, blended to average cost) · **manual entry only** for v1 (IBKR auto-import is a later convenience) · **P&L enabled**.

---

## 1. What M1 is (scope — keep it lean)
Add / edit / delete your positions by hand, and see, per stock and for the book: **shares, average cost, current value, and P&L.** That's it. The heavier analytics (gold-drop scenario, hedge sizing, correlation, charts) are **later milestones** that build on this foundation — M1 is the data-entry + P&L core.

## 2. Data model — buy lines (lots)
One record per purchase (a "lot"):
- `id` — stable unique id (for edit/delete).
- `ticker` — a universe ticker (dropdown). Unknown tickers are rejected with "not in universe — add it first" (the add-to-universe flow we used for Astral/Celsius), never silently accepted.
- `shares` — float > 0.
- `buy_price` — float > 0, in `buy_currency`.
- `buy_currency` — the listing currency (default from the ticker's exchange; editable for the listing you actually bought on).
- `buy_date` — a real date, not in the future.
- `note` — optional.
- `created_at` / `updated_at` — audit.

A **position** = all lots for one ticker, grouped: `total_shares = Σ shares`, `avg_cost_local = Σ(shares×buy_price)/Σ shares`. This is exactly v4's broker-line → position model with `source = "manual"` and cost-basis fields populated.

## 3. Storage (private, auditable)
A dedicated manual store under the already-gitignored `data/manual/portfolio/` (e.g. `manual_positions.yaml`/JSON, or reuse the existing `manual_store` / SQLite pattern if it fits — prefer reuse over a new format). Requirements: **stable ids, atomic writes, schema-validated on read/write, never logs raw values.** Keep the legacy `holdings.yaml` for the hedge report untouched; the portfolio layer reads this new store.

## 4. The write path (the one architecture exception — handled cleanly)
Everywhere else the serve layer reads-only. Manual entry needs writes, so:
- Endpoints on the Portfolio tab: `GET` (table + forms), `POST` add, `POST .../{id}/edit`, `POST .../{id}/delete`.
- Each write: **validate → write the manual store (atomic) → run the portfolio compute → redirect to the view.**
- **No analytics inline in the request handler.** The write triggers the **portfolio pipeline** (reads the *already-persisted* market data + the manual store, writes the portfolio artifacts) — it is **cheap and does NOT hit Yahoo** (the daily refresh handles prices). The page then **reads the artifacts**, keeping the read path clean and consistent with v4.
- Validation (fail-loud, friendly messages): known ticker; shares & price > 0; valid, non-future date; allowed currency.

## 5. P&L (now enabled) — honest and simple
- **Primary, per position (intuitive):** `cost_local = Σ(shares×buy_price)`, `value_local = total_shares × current_local_price`, `P&L_local = value_local − cost_local` (and %). This is the "you bought at X, it's now at Y, you're up Z%" number, in the stock's own currency — no FX confusion.
- **Book level:** total value + total cost converted to **USD** (base) at current FX, with the per-currency split.
- **FX nuance, stated not hidden:** a single USD P&L blends the stock move and the AUD/CAD/GBP move since purchase. v1 leads with **local P&L per position** (clean) + a USD book total; an **FX-aware USD P&L** (cost at buy-date FX) is a labelled refinement, not v1. Current price comes from the pence-corrected snapshot; show the price's as-of date.

## 6. UI (a Positions section in the Portfolio tab)
- A **grouped positions table** (one row per stock): ticker · total shares · avg cost · current price · current value · **P&L (local) · P&L %** — sortable; each row **expandable to its individual buys (lots)**.
- **Add buy** form: ticker (dropdown) · shares · buy price · currency (default from ticker) · date · optional note.
- **Edit / delete** per lot (edit pre-fills the form; delete confirms). Both re-validate + recompute.
- Empty state: a calm "add your first position" with the form — never a fake number.
- Plain-English labels, formulas on hover, consistent with the other tabs.

## 7. Architecture fit (v4)
- `golden_vector/portfolio/manual_store.py` — CRUD + validation for the lots (or reuse the existing manual-store pattern).
- `golden_vector/portfolio/models.py` — lot + position models (v4).
- `golden_vector/portfolio/pipeline.py` — reads the manual store + persisted snapshot/FX, groups lots → positions, computes value + P&L, writes `portfolio_positions` + `portfolio_summary` artifacts (schema_version, manifest-registered, fail-loud stale → 503).
- `serve/portfolio_page.py` — reads the artifacts for display; the add/edit/delete endpoints write via `manual_store` + trigger the pipeline. Behind `portfolio_enabled` + the **non-loopback bind refusal** (v4 B7) — this page shows real money.
- Reuses the shared currency/unit (pence) + FX helpers from v4; no duplicate logic.

## 8. Tests
1. Add a buy → stored with a stable id, retrievable. 2. Multiple lots same ticker → grouped into one position with correct blended avg cost + summed shares. 3. Edit a lot → values + P&L update; delete → removed + recompute. 4. Validation rejects: shares/price ≤ 0, future date, unknown ticker, bad currency — with friendly errors, no partial write. 5. P&L math: known lots + a known current price → expected local P&L and %. 6. Atomic write: a failed write leaves the prior store intact. 7. Privacy: the store stays in the gitignored path; no values in logs; page hidden when `portfolio_enabled` is false; non-loopback bind refused. 8. Read path: the positions page reads artifacts, doesn't parse the store inline.

## 9. Out of scope for M1 (later milestones, on this foundation)
Gold-drop scenario + beta-contribution, GDX hedge card, resilience overlay, correlation, value-over-time chart, the IBKR auto-import, FX-aware USD P&L. M1 = enter the book by hand + see holdings, cost, value, P&L.

## 10. Self-review
Smallest honest thing that delivers immediate value: Emanuel's real book in the tool, by hand, with **P&L turned on** (the original ask), built as the v4 `portfolio/` foundation so the analytics milestones drop straight on top. Per-buy lots (his choice) give honest blended cost; manual-only (his choice) keeps v1 small. The one new pattern — a write path — is contained to a validated, atomic, fail-loud manual store with a cheap no-network recompute, so the read path and privacy posture stay intact.
