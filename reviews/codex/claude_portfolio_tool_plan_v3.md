# Plan v3 — Portfolio tool (build spec; supersedes v2)

**Author:** Claude Code (Opus 4.8)
**Status:** build spec. Supersedes v2 after a 4-critic gap analysis + first-hand code verification. **Verdict that drove v3: v2 was NOT build-ready** — it rested on a partly-broken foundation (a live pence bug in the shared layer, an FX double-conversion trap, a non-existent GDX beta, unmodelled cash). v3 pins those down so Codex builds from an unambiguous spec.
**Sequencing:** clear the §2 blockers (foundation) FIRST, then build the tab (mostly presentation). After the option-signals market-hours validation.
**Data:** `data/manual/portfolio/ibkr_positions_*.csv` + `data/manual/holdings/holdings.yaml` — SENSITIVE, gitignored, never commit/print account number or values.

---

## 0. The reframe (unchanged from v2)
A **Portfolio tab** that **re-presents the existing `hedge/` engine** (served at `/hedge-readiness`): `compute_portfolio_totals()` (gold-drop scenario + coverage/exclusion tracking + hedge cost), `map_proxy_hedges()` (proxy ranking), `sensitivity_ranking.py` (down-beta + put P&L), Tool D gold-stress slider. **Reuse, do not re-derive.** New code = the §2 foundation fixes + composition/coverage + the reconciliation + the charts.

## 1. What it is
Emanuel's real ~£270k book (≈11 small/mid gold miners across AUD/CAD/GBP, mostly no liquid single-name options) through every lens we built, hedging as ONE section. It answers: **"If gold drops, how much do I lose, which names cause most of it, and is the cheapest hedge worth it now?"** — every uncovered/estimated/stale/missing cell flagged, never silently zeroed.

---

## 2. BLOCKERS — clear these before/early in the build (the foundation)

### B1 — Pence (GBp) bug, fixed at the SOURCE (not the importer) ⚠️ live bug
**What:** Yahoo serves LSE prices in **pence**; `ingestion/standardize.py:144` reads the raw price into `share_price_local` with no ÷100, and `currency` is stamped `"GBP"` from config. Then `normalize/market_snapshot.py:69` does `share_price_usd = share_price_local × fx` and `:73` `market_cap_usd = share_price_usd × shares` → **~100× too big** for the 6 LSE names (AAZ, ALTN, EDV, MTL, PAF, SRB). Consumed by `screening/layer2.py` (Tool B) and `hedge/portfolio_totals.py`. **Tool A betas are unaffected (returns are scale-invariant); level metrics are wrong today.**
**Fix:** in ingestion, key on the feed's own currency tag. `yfinance` reports pence as `GBp` (verified: `CLA.L` → `currency='GBp'`). When the tag is `GBp`/`GBX`, divide the extracted price by 100 and normalise the currency code to `GBP`; record a `pence_adjusted: bool` flag on the snapshot. (Bonus: use Yahoo's own `marketCap` field for non-USD names instead of recomputing from price×shares, which double-exposes the unit error.)
**Then:** re-run the full pipeline so `share_price_usd`/`market_cap_usd` are corrected; **audit whether Tool B size-buckets/EV ratios shifted for the 6 LSE names** (they will — that's the fix landing). Test: a 39-pence input → ~$0.49 USD, not ~$49.

### B2 — Pin the canonical notional formula (stop the FX double-conversion)
**What:** the engine's `current_stock_price` is **already USD** (`share_price_usd`, or option underlying falling back to `adj_close_usd`), but IBKR `shares` are **local-listing** counts. "Convert local→USD" on top of an already-USD price double-applies FX (~1.5× off on AUD).
**Fix:** the one formula is **`notional_usd = local_share_count × local_price × fx_rate_to_usd`** (local price + the normalize layer's `fx_rate_to_usd`/`fx_source_date`/`fx_staleness_days`). Prefer the **IBKR export's own local price** as the authoritative current price; fall back to Tool A/B USD only if absent. **Do NOT reuse `compute_portfolio_totals`'s USD `current_stock_price` for valuation.** Test with a known AUD line.

### B3 — Compute & persist GDX/GDXJ gold-down-beta (before the hedge card)
**What:** GDX/GDXJ are **benchmarks only** (`config/benchmarks.yaml`), never run through the Tool A estimator as subjects (`pipeline.py` iterates `universe.tickers`). But the hedge card sizes `short notional = effective exposure ÷ GDX gold-beta` and computes the overshoot multiple from it — dividing by a number that doesn't exist.
**Fix:** add a **benchmark-beta step** that runs the **existing** Tool A structural estimator over GDX/GDXJ USD weekly returns vs gold and persists `down_beta_core` + `confidence` + `n_weeks` into a `benchmark_betas` artifact. **Do NOT add GDX to `universe.yaml`** (it would pollute Tool A/B/C/D rankings). The portfolio step READS this artifact. If it can't be computed, the hedge card says **"GDX hedge size unavailable"**, never divides by a default. Note the window (benchmarks fetched `period=max` vs universe 1y weekly) and quantify the basis-risk (small-cap effective beta ÷ GDX beta) rather than just mentioning it.

### B4 — Model cash in NAV
**What:** the IBKR export carries AUD/CAD/GBP/USD **cash**; the engine sums equities only. So "computed total" (equities) ≠ "IBKR account value" (equities + cash) — the reconciliation fails by exactly the cash amount every run, and every "% of book" denominator is wrong.
**Fix:** **NAV = Σ(equity notional_usd) + Σ(cash_usd by currency)**, each cash line FX-normalised the same way. Show cash as its own pie slice. **Exclude cash from the gold-drop scenario** (zero gold beta) but include it in NAV. State explicitly whether concentration weights are over equities-only (recommended for "composition") or NAV — and label which is which.

### B5 — Two-stage reconciliation (the trust gate, done right)
**What:** computed-vs-IBKR conflates (a) mapping/pence/FX-tag bugs, (b) live-vs-export **price** drift, (c) live-vs-export **FX** drift into one number — can't tell a real pence bug from normal drift.
**Fix:**
- **Stage 1 (gates the page):** re-value using **IBKR's OWN per-line prices and OWN FX** from the export, sum, assert it matches the IBKR account total to a **tight tolerance (cents)**. This isolates the symbol map, pence ÷100, dual-listing summation, and cash inclusion with **zero drift**. On breach: `status = MISMATCH`, grey the derived sections behind a red banner, **do not crash**; name the offending line.
- **Stage 2 (does NOT gate):** Golden-Vector-priced total vs IBKR, difference labelled **"price/FX drift since export (DD/MM HH:MM)"**, not "error".
- Parse the export's per-line price, FX, and **export timestamp**; show both as-of dates at top. Pin which export field is the target (NetLiquidation / account total); hold non-position rows (cash sweeps, fee lines) aside in a visible "excluded — not a holding" list.

### B6 — Dual listings as broker LINES → value → group by company
**What:** Serabi (SRB.L + SBI/CAD) and Celsius (CLA.AX + CLA.L/pence) map to one universe ticker, but `load_holdings` (`holdings.py:48`) **raises on duplicate ticker**, and you can't sum share counts across currencies.
**Fix:** model holdings as **broker lines** `(broker_symbol, currency, pence_flag, shares)`; value each to USD **independently** (own price × own FX × own pence guard); then **GROUP BY universe ticker and SUM the USD values** into one synthetic holding (use `dollar_exposure` mode for merged lines — there is no single share count). Keep both lines visible in the per-line artifact. Tests: SRB.L(GBP)+SBI(CAD) and CLA.AX(AUD)+CLA.L(pence) each → one summed-USD concentration entry.

### B7 — Privacy: the rendered output is the real attack surface
**What:** `/hedge-readiness/latest.md` already emits real `current_total_value` + per-name `Exposure: {money}` straight off disk; host defaults to loopback but has no guard against LAN binding, no auth. The new `portfolio_summary` artifact holds real values; `.gitignore` line 19 `!data/manual/**/*.csv` **re-includes** CSVs under `data/manual`, so a portfolio artifact in the wrong dir gets git-tracked.
**Fix:** (1) write all portfolio artifacts under an **already-ignored** path and add an **explicit `.gitignore`** line in the same step that creates the writer; add a test/CI guard that no portfolio file is tracked and no committed file contains the account-number pattern. (2) Add a **fail-loud guard** refusing to bind to a non-loopback host when holdings are present (unless an explicit override env var), and a `portfolio_enabled` flag gating any holdings-bearing render. (3) The portfolio step logs **counts/tickers only**, never values or the account number.

---

## 3. v1 sections (killer features — refined)
1. **Reconciliation line** (Stage 1 gates) at the very top, with both as-of dates.
2. **Composition + coverage:** NAV in **USD**, the AUD/CAD/GBP split (+ cash slice), sorted per-holding **weight table**, FX as-of, and a **coverage banner naming uncovered names explicitly** (reuse `holdings_excluded_from_totals` etc.).
3. **Concentration:** "top holding = N% ; top 3 = M%" (state the denominator).
4. **Gold-drop loss + attribution:** reuse `scenario_rows`; rank `HoldingResolved` by `notional_usd × down_beta_core`; flag **"linear estimate — a real crash is likely worse."**
5. **Effective gold exposure in 2–3 lines:** measured (covered) / **estimated** (default beta) / **low-confidence** (see §6) — never blended.
6. **Resilience overlay** (Tool D slider): "% of **covered** holdings (= N% of book)".
7. **GDX/GDXJ hedge card** (needs B3): sizing + IV-cheap/expensive from option signals + FX note; short-circuits to "unavailable" if the GDX beta is missing.
8. **P&L = greyed "add cost basis to enable"** card; labelled "not since-purchase P&L"; never 0, never the IBKR period move.
9. **One synthesis line** at top: most-concentrated name · biggest gold-loss driver · cheapest hedge now.

## 4. Charts (all three kept — built honestly)
- **Holdings pie** (weights + currency + cash slice).
- **Correlation heatmap** + a "your 3 most-correlated pairs" line + the "in a selloff these go to ~1.0 together" caveat; covered-only, labelled.
- **Value-over-time line** — relabelled precisely: **"indicative value of TODAY'S holdings if held unchanged over this window — not your actual historical portfolio value."** Value each point with that date's price **and** that date's FX (the normalize layer carries dated FX). Source: Σ over covered holdings of shares × dated USD price from the persisted Tool A weekly series; gap/flag STALE_FX weeks, don't silently plot. State covered-only %. Upgrades to true P&L when cost basis exists.

## 5. Decisions — LOCKED (Emanuel)
USD base · P&L disabled (greyed stub) · all 3 charts kept (honest) · overshoot single-name hedge = **gated FYI behind the GDX card** (hard tradability gate via `sensitivity_ranking`'s `is_rankable`/`optionability_tier=='none'`→NOT TRADABLE; "loses if gold rises" warning; None-beta names never shown as confident shorts).

## 6. Honesty refinements (should-fix)
- **Third beta bucket:** "covered but **low-confidence**" gated on the existing `confidence_score` (reuse proxy_hedge's 0.70 floor — don't invent one). Sub-floor → separate caveated line, excluded from the confident headline. Mark sub-0.10-beta / flat-held names "not modeled — shown flat, not crash-proof". Tag **CLA as copper-gold — gold beta noisy/mixed.**
- **FX-flat caveat:** "gold shock applied to USD-return betas, which include historical gold/FX co-movement; we don't decompose the currency channel." Test: a pure-FX change with gold unchanged → zero modeled loss.
- **Mixed-currency gate (hard rule #1):** every resolved holding must carry currency + `fx_rate_to_usd` + `fx_as_of` + `pence_flag` before entering any total; **fail loud** (raise, not zero) on notional-without-FX; one authoritative FX snapshot+as-of shown once.

## 7. Architecture
All math at refresh (extend the hedge step or a `portfolio` CLI step), persisted; serve **reads-only** (a `load_portfolio_data()` reader — forbid calling `compute_portfolio_totals` in the request path, mirror `_read_option_artifact_frames`). `PORTFOLIO_ARTIFACT_SCHEMA_VERSION` stamped + read; **503 on mismatch**; registered in the model-state manifest + alignment check. **One shared valuation helper** (`normalize/holdings_valuation.py`: `to_usd(local_value, currency, fx_rate, is_pence)` + `detect_pence` on the `GBp` tag) called from BOTH importer and portfolio compute — no divergent copies. The tab is **new HTML** (a Portfolio nav entry + `/portfolio` handler + `serve/portfolio_page.py` mirroring `overview_tool_d.py`) — there is no markdown→HTML renderer; do not ship a `.md` dump.

## 8. Artifact schemas + config (so Codex doesn't invent fields)
- **`config/portfolio_symbol_map.yaml`** — list of `{broker_symbol, broker_currency, universe_ticker, is_pence}` (centralised, per §10 table).
- **`portfolio_holdings`** (per broker line, pre-collapse): `broker_symbol, universe_ticker, feed_currency, shares, local_price, pence_flag, fx_rate_to_usd, fx_source_date, fx_staleness_days, notional_usd, down_beta_core, beta_source, covered, exclusion_reason`. **`currency` is REQUIRED per line from the broker feed**, validated vs `SUPPORTED_CURRENCIES`, **not** joined from the universe ticker (CLA's GBP London line maps to CLA.AX=AUD — joining would mis-tag it). Add nullable `cost_basis`/`purchase_date` now so P&L lights up later without re-import.
- **`portfolio_summary`** (book level): `schema_version, run_id, as_of_date, export_as_of_date, base_currency, computed_total_usd, ibkr_reported_total_usd, reconciliation_diff_usd/_pct/_status, cash_by_currency, nav_usd, currency_split_usd, top1/top3_weight_pct, gdx_down_beta, default_miner_beta (+source+count), covered_pct_of_book`.
- **`default_miner_beta`** = median of **covered-holdings** `down_beta_core` (not universe-wide), shown on the page with value+source+count; a held name uses it iff `down_beta_core is None OR (≤0.10 AND low confidence)`.

## 9. Build order
1. **B1 pence fix at source** → re-run → audit Tool B LSE names.
2. **B3 benchmark-beta step** (GDX/GDXJ gold-down-beta artifact).
3. **Importer**: broker lines + currency + pence guard + dual-listing collapse (B2 formula, B6 grouping); populate `holdings.yaml`/artifact from the IBKR export. Shared valuation helper.
4. **B4 cash + B5 two-stage reconciliation** → the reconciliation line.
5. Composition/coverage/concentration → exposure (3 buckets) → resilience overlay.
6. **GDX hedge card** + overshoot gated FYI.
7. Charts (pie, correlation+caveat, value-over-time honest).
8. P&L greyed stub + synthesis line. **B7 privacy guards + gitignore + schema-version 503** woven throughout.
Tests: pence 39p→$0.49; AUD notional; Serabi/Celsius merges; cash in NAV not in scenario; FX-only change → 0 loss; None-beta never a confident short; artifact-not-tracked + no-account-number guards; stale-schema 503.

## 10. Holdings inventory + broker map (verified 2026-06-08)
Book ≈ 11 companies; only 2 were missing (AAR.AX Astral, CLA.AX Celsius — now added to `universe.yaml`, data confirmed). Map (IBKR symbol → universe): `l` suffix = LSE (`ALTNl`→ALTN.L, `EDVl`→EDV.L, `PAFl`→PAF.L); bare LSE (`AAZ`,`MTL`,`SRB`)→`.L`; AUD→`.AX`; **dual listings collapse to one universe entry but BOTH lines sum** (Serabi `SRB`+`SBI`/CAD → SRB.L; Celsius `CLA`/AUD + `CLA`/GBP → CLA.AX). Pence detectable via Yahoo's `GBp` tag (CLA.L confirmed). Pence does **not** affect existing Tool A betas (returns-based); it does affect Tool B level metrics (B1).

## 11. Self-review
v3 is the build spec v2 wasn't: it pins the foundation v2 assumed was done. The 7 blockers are code-verified, not theoretical — B1 is a **live bug** in the shared layer (caught before building on it). The honesty discipline, engine reuse, and locked decisions from v2 survive; what changed is the spec now has exact formulas (notional, NAV, two-stage reconcile), an explicit GDX-beta prerequisite, a dual-listing data model, named artifact schemas, and the privacy guards. Get the §2 foundation honest and reconciled first; then the tab is mostly presentation.
