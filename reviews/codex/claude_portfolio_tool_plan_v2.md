# Plan v2 — Portfolio tool (a Portfolio tab on the engine we already own)

**Author:** Claude Code (Opus 4.8)
**Status:** revised after a 5-lens design panel + **first-hand code verification** + Emanuel's locked decisions. Ready for Codex review → build. **Sequencing: build after the option-signals market-hours validation.**
**Data:** `data/manual/portfolio/ibkr_positions_*.csv` (IBKR export) + `data/manual/holdings/holdings.yaml` (canonical). **Gitignored / sensitive — never commit, never print the account number or exact values.**

---

## 0. The reframe (the most important change from v1) — most of this ALREADY EXISTS

v1 read like a from-scratch build. It isn't. The `hedge/` engine — already served at **`/hedge-readiness`** — does ~70% of it. Verified in code:

| Plan feature | Already built (verified) |
|---|---|
| Aggregate gold-drop loss scenario | `compute_portfolio_totals()` → `PortfolioTotalsData.scenario_rows` (`hedge/portfolio_totals.py:60`), each row = gold_pct_change, portfolio_value_at_scenario, loss_$, loss_% |
| Per-holding resolution + exclusions | `HoldingResolved` + `holdings_excluded_from_totals` / `downside_model_skipped` / `hedge_cost_skipped` lists |
| Current total value, hedge cost by protection | `PortfolioTotalsData.current_total_value`, `hedge_cost_by_protection` |
| Proxy-short ranking + basis-risk labels | `map_proxy_hedges()` (`hedge/proxy_hedge.py:30`) |
| Down-beta ranking + put P&L | `hedge/sensitivity_ranking.py` |
| Gold-stress slider | Tool D (live) |
| Per-name currency + FX-to-USD + staleness flags | `normalize/prices_usd.py` (emits MISSING_FX / STALE_FX) — **computed, but NOT yet wired into per-position notional (see §2)** |

**Rule for the build:** every section maps to an existing function and *re-presents* it. Do **not** re-derive betas, scenario math, hedge sizing, or proxy ranking — reuse the engine. New code is only: the currency/FX wiring (§2), the composition/coverage view, loss-attribution sort, the reconciliation line, and the charts. This honors the repo's no-duplication rule.

---

## 1. What it is
A **Portfolio tab** — Emanuel's real book through every lens we built — with **hedging as one section**, not a hedging tool. ~£270k of small/mid gold miners across AUD/CAD/GBP, mostly without liquid single-name options (GDX/GDXJ is the main hedge path). It answers the one question a concentrated single-sector book actually has: **"If gold drops, how much do I lose, which names cause most of it, and is the cheapest hedge worth it right now?"** — with every uncovered / estimated / FX-stale / cost-basis-missing cell **explicitly flagged**, never silently zeroed.

---

## 2. The two genuinely-NEW build items (also the two biggest correctness risks)

These are the only hard new work, and the plan must treat them as unbuilt:

1. **Per-position currency / FX.** `Holding` (`hedge/holdings.py:13`) has **only** `ticker / shares / dollar_exposure`, and `exposure_usd()` **assumes the value is already USD**. The book is AUD/CAD/GBP. Build: add a `currency` to the holding model (or join it from the universe), and convert each position local→USD using the FX the `normalize/` layer already fetches, carrying the FX as-of date + staleness. Until this is real, the total and every hedge size are wrong.
2. **Pence (GBX) guard.** There is **no pence handling anywhere** in the codebase (verified). LSE small-caps (AAZ.L, EDV.L, PAF.L…) quote in **pence**; if the feed tags them "GBP" but the price is pence, every LSE line is **100× too big, silently** — no error, just a plausible total skewed toward UK names. Add a validated, tested pence-vs-pound assertion before any total renders.

**Consequence — the reconciliation line is FIRST on the page:**
> "Golden Vector computed total = $X  ·  your IBKR account value = $Y  ·  difference = Z"

The IBKR account value is the one ground-truth total we have. If they don't match within tolerance, nothing derived (pie, exposure, hedge size) is trustworthy — and this single check catches the pence bug, FX errors, and any unmapped ticker at once. Build this before anything that depends on the total.

---

## 3. v1 sections (the killer features, in order)

1. **Reconciliation line** (computed total vs IBKR total) — top of page.
2. **Composition + coverage:** total in **USD** (base currency, locked), the AUD/CAD/GBP split, a sorted per-holding **weight table**, the FX as-of date, and a **coverage banner naming the uncovered small-caps explicitly** (reuse `holdings_excluded_from_totals` / `downside_model_skipped` so nothing is silently dropped).
3. **Concentration in two blunt numbers:** "top holding = N% of book; top 3 = M%." (One line; high decision-impact for a small-cap book.)
4. **Gold-drop loss with attribution:** "if gold falls 20%, you lose ~$X (Y% of NAV); these 3 names drive half of it" — reuse `scenario_rows`; the only new bit is ranking `HoldingResolved` by `current_notional × down_beta_core`. Flagged **"linear estimate — a real crash is likely worse"** (down-beta is a normal-period OLS slope; juniors gap and de-rate non-linearly in a crash).
5. **Effective gold exposure as TWO lines:** measured (covered names, real per-name `down_beta_core`) vs **estimated** (uncovered at one *documented* default miner beta, value + source stated). Never blended into one fake-precise figure. Size the estimated slice loudly.
6. **Resilience overlay** (Tool D slider): "at $2,500 gold, these 3 holdings stop covering interest" — denominator stated as **"% of covered holdings (which is N% of book)"**, never "% of book."
7. **GDX/GDXJ hedge card** — the one route most of the book can execute. short notional = effective exposure ÷ GDX's own gold-down-beta; # puts = notional ÷ (price × 100); "is GDX cheap to hedge now" from the option signals; one FX note (USD instrument). **Prereq: persist GDX/GDXJ's own gold-down-beta from the same Tool A estimator** — without it the sizing and the overshoot multiple are arithmetically invalid. Note the basis risk: GDX (large-cap basket) under-covers high-beta small-caps, so the hedge is structurally a bit small — say so.
8. **P&L = greyed "add cost basis to enable" card** (locked: disabled for now). Explicitly labelled **"not since-purchase P&L"**; never shows 0, never the IBKR period (Prior-Price→Price) move.
9. **One synthesis line at the top:** most-concentrated name · biggest gold-loss driver · cheapest hedge right now. A beginner needs the conclusion, not six panels to assemble.

---

## 4. Charts (Emanuel kept all three — built honestly)

- **Holdings pie** — position weights (+ a currency slice AUD/CAD/GBP). Cheap, useful. ✅
- **Correlation heatmap** — KEPT per Emanuel. Made honest: a blunt **"your 3 most-correlated pairs are X/Y/Z"** line on top, and a caveat that **in a gold selloff these names move toward ~1.0 together regardless of the calm-period number** (so a "0.4" pair is *not* safe diversification). Covered names only — label it.
- **Value-over-time line** — KEPT per Emanuel, built honestly given P&L is disabled: it shows **market value over time** (covered holdings, reconstructed from the weekly price history we already fetch), labelled **"market value — covered holdings (X% of book) — not profit/loss."** When cost basis is later added, the same chart upgrades to a true **P&L-over-time** line and the greyed P&L card lights up. It must label the covered-only coverage so it never implies the whole book.

---

## 5. Decisions — LOCKED (Emanuel, this session)
1. **Charts:** keep all three (pie + correlation + value/P&L-over-time), built with the honesty treatments in §4.
2. **P&L:** disabled for now — greyed "add cost basis to enable" card. (Revisit by importing an IBKR Trades/Lots report or adding `cost_basis`/`purchase_date` to `holdings.yaml` later.)
3. **Base currency:** **USD** (with a GBP-thinking note on the hedge FX mismatch).
4. **Overshoot single-name hedge:** **gated FYI behind the GDX card** — re-sort `sensitivity_ranking.py`, annotate each candidate with overshoot-multiple-vs-GDX + Tool D fragility + a **hard tradability gate** (greyed out unless liquid options or a documented borrow), reframed "put where options exist, else GDXJ," with a blunt **"this LOSES if gold rises"** warning. Default every candidate to NOT TRADABLE; replicate `proxy_hedge.py`'s None-beta guard so an unmeasured name never surfaces as a confident "short this ~1.8×."
5. **Default miner beta** (uncovered names): define explicitly + show it on the page (e.g. median covered down-beta or GDX's gold-down-beta) — load-bearing, not a hidden constant.

---

## 6. Honesty traps to design around (non-negotiable)
- **Never** show the IBKR period P&L (Prior-Price→Price, sitting right in the CSV) as if it were since-purchase. The disabled card says so explicitly.
- **Pence/pound 100×** fails silently — guard + test it.
- Every **"%"** states its denominator (whole book vs covered book).
- The gold-crash loss number is **optimistic** (linear normal-period beta) — flag it.
- Estimated (uncovered) betas are a **separate labelled line**, never averaged into the confident headline (respects "no opaque composite").
- The overshoot hedge is a **directional bet** that loses if gold rises, on often-untradable names — gate + warn, never lead with it.
- Same-currency FX round-trips (e.g. GBP→USD with one as-of date) must be identity-preserving; pin the gold scenario to **gold-only with FX held flat** so "gold falls 20%" isn't conflating a currency move.

---

## 7. Backend / architecture (single source of truth)
- All portfolio math at refresh (extend the existing hedge step or a `portfolio` CLI step), **persisted as a `portfolio_summary` artifact** (+ `portfolio_holdings` per-name) with `schema_version` + run identity + a fail-loud stale guard, consistent with the other artifacts. The serve layer **reads and renders only** — no portfolio arithmetic in the request path.
- **Reuse, don't re-derive:** scenario + totals from `compute_portfolio_totals`; proxy ranking from `map_proxy_hedges`; down-beta ranking from `sensitivity_ranking`; resilience from Tool D; FX + currency + staleness from `normalize/prices_usd.py`. The portfolio tool is an **aggregation + presentation layer**, not new financial formulas (new math is limited to currency conversion, loss attribution, and the reconciliation check).

---

## 8. Build order
1. **Currency/FX + pence guard + the reconciliation line** (get the total honest first — everything else is worthless until it reconciles to IBKR).
2. **Composition + coverage + concentration** (pure aggregation; the daily-open page).
3. **Gold-drop loss + attribution + effective-exposure two-line + resilience overlay** (re-present the engine).
4. **GDX hedge card** (persist GDX gold-down-beta first) + **overshoot gated FYI**.
5. **Charts** (pie, correlation-with-caveat, value-over-time honest).
6. **P&L greyed stub** + the top synthesis line.
Persist the artifact; serve reads only; fail-loud stale guard. Tests: pence 100× assertion, reconciliation tolerance, denominator labels, None-beta proxy guard.

---

## 9. Self-review
v2 is grounded in **verified code**, not aspiration: the hedge engine already does the scenario/totals/proxy/coverage work (`/hedge-readiness`), so this is a Portfolio **tab** that re-presents it + closes the two real gaps (per-position currency/FX, pence guard) behind a reconciliation-to-IBKR gate. Emanuel kept all three charts; they're built to tell the truth about what they show until cost basis exists. Decisions locked in §5; honesty traps in §6 are the acceptance bar. No duplication, backend-computed + persisted, honest about every gap.
