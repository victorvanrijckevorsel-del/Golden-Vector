# Plan v4 — Portfolio tool (final build spec; supersedes v3)

**Author:** Claude Code (Opus 4.8), reconciled with Codex's v3 review (`codex_review_claude_portfolio_plan_v3.md`, NEEDS CHANGES — **adopted**).
**Status:** build spec. The big change vs v3 is architectural: **build a first-class `portfolio/` compute layer**, do NOT lean on the hedge-readiness markdown/report engine.
**Sequencing:** foundation (§7 order) first, then the tab. After the option-signals validation + the LSE re-run.

---

## 0. Reconciliation — what changed from v3 and why

Codex graded v3 NEEDS CHANGES. I verified the two load-bearing claims first-hand and **agree**:
- `compute_portfolio_totals` is orchestrated **inside the markdown-report builder** (`hedge/report.py:260` `build_hedge_readiness_sections` → `:341` calls it amid candidate grids + speculation sections → `:210` renders markdown → `latest.md`). It also takes the limited `Holding` model (unique ticker, no currency, no cash, no lines) and already works in USD. So v3's "re-present the existing hedge engine" points the dependency the wrong way.
- My B7 git risk was overstated: `data/output/` (`.gitignore:16`) and `data/manual/portfolio|holdings/` (`:22-23`) **are** ignored. The real leak is the **served** `/hedge-readiness/latest.md` endpoint + no non-loopback guard.

**Decision:** adopt Codex's architecture — a dedicated, data-first `golden_vector/portfolio/` package that **reuses the underlying primitives** (the Tool A estimator, the scenario math) but is typed, persisted as artifacts, manifest-integrated, and serve-reads-only. The markdown report can later read the portfolio artifacts (dependency inverted).

**My one guardrail on top of Codex (keep it lean — Emanuel's "simplest thing that works"):** adopt the *shape*, but **stage** it for an 11-name book — don't build all 6 artifacts + 5 modules before anything renders, and extract **one** shared scenario/down-beta primitive so portfolio and hedge never fork two copies (no-duplication rule).

Where Codex and I now agree vs where I refine:

| Item | Codex | My position |
|---|---|---|
| First-class `portfolio/` package, not markdown reuse | P0 | **Agree** (verified) |
| Fix history pence path too + shared unit helper | P0 | **Agree** (I'd deferred history; the value chart needs it) |
| Split artifacts by grain + manifest + provenance | P0 | **Agree**, but **stage** them (lines/positions/summary/benchmark first; cash in summary; charts from positions) |
| Typed valuation boundary (no raw floats) | P1 B2 | **Agree** — strong |
| `benchmark_betas` first-class step | P1 B3 | **Agree** (already wanted it; this specifies it) |
| Reconciliation tolerances max($2, 5bps), not "tight cents" | P1 B5 | **Agree** — my cents gate was too brittle |
| BrokerLine→Position w/ company_id, ISIN, map confidence | P1 B6 | **Agree** |
| Gate the existing `/hedge-readiness` endpoint + non-loopback refusal | P1 B7 | **Agree** (my git framing was wrong) |
| Shared helper in `normalize/common`, not `portfolio/` | Arch | **Agree** |
| New: what-matters panel, data-issues panel, beta-contribution, coverage %, reconciliation CSV | Ideas | **Agree** — adopt all 5 |
| Overshoot = informational-only for v1 | Locked | **Agree** (matches Emanuel's "gated FYI") |
| Reuse the scenario primitive vs a 2nd copy | — | **My add:** extract ONE shared primitive; don't reimplement |

---

## 1. Architecture (the heart of v4)

### 1a. New package `golden_vector/portfolio/`
- **`models.py`** — `BrokerHoldingLine`, `CashLine`, `PortfolioPosition` (grouped, canonical), `PortfolioSummary`, `ReconciliationResult`.
- **`importer.py`** — parse the IBKR export + `holdings.yaml` into broker lines + cash lines. **No analytics.** Carries `source_file_sha256`, export as-of date, broker symbol/exchange/account-section/currency/quantity/price/value. Unmapped symbols surface as a loud "could not map" line, never dropped.
- **`valuation.py`** — value ONE line via the shared unit/FX helper. **Typed boundary (no raw floats):** inputs `quantity, price_local, price_currency, price_unit, fx_rate_to_usd, fx_source`; outputs `market_value_local, market_value_usd, price_source` + provenance. Makes double-conversion structurally impossible.
- **`pipeline.py`** — read current manifest artifacts (Tool A betas, Tool B/D, snapshot, FX, `benchmark_betas`), compute lines→positions→summary→charts→reconciliation, write artifacts. **Reuses** the shared scenario primitive (§1e), does not re-derive.
- **`reader.py`** — checked reads via `resolve_current_model_artifact_path` for the UI.

### 1b. Shared valuation/unit helper in `normalize/` (NOT under `portfolio/`)
One place for minor-unit (pence `GBp`) detection + local→USD, called by `standardize_market_snapshot` (done), `standardize_equity_history` (to do), AND portfolio valuation — so the pence rule exists **once**. Persist `feed_currency`, `price_scale_factor`, `minor_unit_adjusted` for audit.

### 1c. Manifest integration
Register portfolio artifacts in the model-state map (`app/model_state.py`); require `summary` + `positions` for completeness; resolve via `resolve_current_model_artifact_path`; `PORTFOLIO_ARTIFACT_SCHEMA_VERSION` → calm "run refresh" page (503) on mismatch. No custom pointer.

### 1d. Request path
`serve/portfolio_page.py` **reads artifacts only** — no CSV parsing, no correlation/scenario compute in serve. Mirrors the option readers; honors the architecture-foundations rule (avoids the earlier option-page slowdown).

### 1e. One shared scenario primitive (my guardrail)
Extract the gold-shock/down-beta math (`Σ notional_usd × max(0, down_beta × shock)` + exclusion handling) into a single shared function used by BOTH `compute_portfolio_totals` and the new portfolio pipeline — so the two never drift.

---

## 2. Artifacts (by grain — staged; keep lean)
**v1 ships:** `portfolio_lines` (broker/cash line grain), `portfolio_positions` (canonical company grain), `portfolio_summary` (one row per build), `benchmark_betas` (one row per benchmark). **Fold-in later:** cash lives in `summary.cash_by_currency` first (split to `portfolio_cash` only if it grows); `portfolio_charts` only if precompute is needed (11 names is tiny — derive from positions initially); `portfolio_reconciliation` as its own artifact (line + summary statuses).
Every artifact carries `schema_version, parent_refresh_id, snapshot_refresh_run_id, source_export_sha256, portfolio_source_version`. **Grain is explicit** so validation is simple and the UI degrades gracefully (summary renders even if charts are missing). Rename v3's ambiguous `portfolio_holdings` → `portfolio_lines`/`portfolio_positions`.

---

## 3. Foundation fixes (the old blockers, now inside the architecture)
- **B1 pence:** complete the **history path** via the shared helper (snapshot already fixed, commit `9d26270`). Persist the audit fields. Test: a `GBp` quote divided **once** — not zero, not twice.
- **B2 notional:** the typed valuation boundary (§1a). Stage-1 reconciliation uses **IBKR's own** market value + FX as truth; GV prices feed only drift + analytics.
- **B3 benchmark beta:** a `benchmark_betas` pipeline step reading `config/benchmarks.yaml`, reusing the Tool A structural series + estimator, persisting `benchmark_ticker, as_of_date, window_start/end, n_weeks, down_beta_core, up_beta_core, confidence_label, method_version, snapshot_refresh_run_id`. **Cards fail closed** if missing/low-confidence. Never add GDX/GDXJ to `universe.yaml`.
- **B4 cash:** NAV = Σ(equity USD) + Σ(cash USD); cash excluded from gold shock; **distinguish equity-weight vs NAV-weight everywhere** (a name can be 20% of equity but 12% of NAV — label which).
- **B5 reconciliation:** Stage 1 (broker's own positions/prices/FX/cash/NAV) **hard-gates** analytics on failure; Stage 2 (GV live-price drift) is a **soft fresh/stale/drifted label**, never a blocker. Tolerances **max($2, 5bps)** at account level. A `portfolio_reconciliation` artifact with line + summary statuses.
- **B6 broker lines:** keep `Holding` as the legacy hedge input; add `BrokerHoldingLine → PortfolioPosition` grouping on a stable `company_id`/canonical ticker (+ optional ISIN, mapping confidence) from `config/portfolio_symbol_map.yaml`. Raw lines stay visible/auditable. Don't rely on `.upper().strip()` alone.
- **B7 privacy:** gate **all** holdings-bearing routes — including the existing `/hedge-readiness/latest.md` — behind `portfolio_enabled`; **refuse non-loopback bind** when enabled; keep explicit ignore patterns for `data/manual/**/ibkr*.csv` + `*portfolio*.csv` (manual CSVs outside the ignored dirs are re-included by `!data/manual/**/*.csv`); a tracked-file scan test for account-number-like strings; no raw file paths or values in HTML/logs.

---

## 4. Product (v1 sections) — v3 set + Codex's panels
1. **"What matters today" panel** (top): NAV · cash % · largest position weight · modeled move at gold −10% · approx GDX hedge notional for a target protection. The five-number synthesis.
2. **"Data issues to fix" panel** (before analytics): unmapped lines · stale prices · missing FX · missing Tool B data · missing benchmark beta · reconciliation status. Suppress confident charts when coverage is low.
3. **Reconciliation line** (Stage 1 gates) with broker-statement date AND GV price date shown separately.
4. **Composition + coverage:** NAV in USD, currency split + cash slice, sorted weight table, coverage %, a **local-currency detail table** so Emanuel can tie out to his broker statement.
5. **Concentration:** top1 / top3 — **equity-weight and NAV-weight, both labeled.**
6. **Gold-drop loss + beta-contribution** by position (`notional × down_beta / total_beta_exposure`) — the actionable driver ranking. Flagged "linear estimate, real crash worse."
7. **Effective exposure:** measured / estimated / low-confidence buckets (never blended).
8. **Resilience overlay** (Tool D slider): "% of covered holdings (= N% of book)."
9. **GDX/GDXJ hedge card:** "**modeled hedge size**" (not "recommended"); fail-closed if no benchmark beta; IV context + FX note.
10. **P&L:** greyed "cost basis not imported yet" stub.
11. **Charts:** pie; **concentration ships first**; correlation **coverage-gated + a "largest paired exposures" table beside it**; **value-over-time** (needs the history pence fix; labeled "today's holdings valued backward — not profit/loss").
12. **Reconciliation CSV export** (raw broker line → canonical position).

---

## 5. Decisions — LOCKED (+ Codex refinements)
USD base **+ a local-currency detail table**. P&L disabled stub. Charts kept but **coverage-gated + precomputed**, concentration first. **Overshoot = informational-only for v1** (no single-name short sizing without borrow/gap data — Codex + Emanuel's gate align). GDX card labeled "modeled," not "recommended."

## 6. Honesty + hard rules
v3 §6 carries, plus: equity-weight vs NAV-weight always labeled; "modeled hedge size" never "recommended"; no portfolio score; currency normalization only safe once history + portfolio share the one unit/FX helper; fail loud on broker-import / schema-mismatch / missing benchmark beta / missing price unit / stale artifacts.

## 7. Build order
1. **Shared unit/FX helper** (`normalize/`) + **complete the history pence fix** + audit fields (+ tests).
2. **`benchmark_betas` step** + artifact + manifest (Tool A estimator over GDX/GDXJ).
3. **`portfolio/` package:** `importer` → `valuation` (typed) → broker-line→position **grouping** → **reconciliation** (two-stage).
4. **`portfolio/pipeline`:** compute summary/positions (+ charts) → persist artifacts → manifest + schema_version.
5. **`serve/portfolio_page.py`** (reads only) + nav entry + **privacy gates** (incl. `/hedge-readiness`) + **non-loopback bind refusal**.
6. **Sections:** what-matters + data-issues panels → composition → concentration → beta-contribution → resilience → GDX card → charts → reconciliation CSV.

## 8. Tests required before accept (Codex's list, adopted)
1. `GBp` snapshot **and** history divided **once**. 2. Duplicate company lines → one canonical position, both raw lines preserved. 3. Cash in NAV + concentration denominator, out of gold shock. 4. Reconciliation: broker totals pass; deliberate mismatch hard-fails analytics; GV drift labels but does not fail. 5. Benchmark beta produced without adding GDX/GDXJ to `universe.yaml`; missing artifact disables hedge sizing. 6. Privacy: disabled hides all portfolio pages/downloads; non-loopback bind refused; `/hedge-readiness/latest.md` can't leak values. 7. Manifest: portfolio artifacts resolve through immutable model-state paths. 8. Serve route reads no raw CSVs / computes no charts. 9. Stale schema → calm "run refresh", not 500.

## 9. Keep-it-lean guardrails (my addition)
- Ship `lines + positions + summary + benchmark_betas` first; cash in summary; charts from positions. Don't build 6 artifacts + 5 modules before anything renders.
- ONE shared scenario/down-beta primitive (§1e) — no second copy.
- Simplest honest version first; extra panels/charts are fast-follow.

## 10. Holdings inventory + symbol map
Carry v3 §10 verbatim (11 companies; only AAR.AX + CLA.AX were missing, now added; broker map; pence via the `GBp` tag; dual listings collapse to one position but sum both lines).
