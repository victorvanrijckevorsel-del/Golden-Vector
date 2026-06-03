# Plan: Option Trading Tab (Workspace UI for the put/call tool) — v1

**Author:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Date:** 2026-06-02
**Status:** for Codex review before implementation
**Builds on:** M1.5 (shipped) — the hedge-readiness engine + `build_hedge_readiness_sections()` / structured dataclasses.
**Supersedes the current approach:** the in-progress `serve/hedge_readiness_page.py` re-parses `latest.md` with a regex. v1 replaces that with a structured-data UI (see §0.5).

## Emanuel's locked choices (this plan implements exactly these)
1. **A tab called "Option Trading."**
2. **Optionable-only list** — show only tickers that actually have listed options (~half the 64-ticker universe).
3. **Filterable list**, click a row → **detail**, "similar to Tool A and B."
4. **Detail = a new panel on the existing per-ticker detail page** (alongside Tool A / Tool B), not a separate page.
5. **Both puts AND calls** in the detail.
6. **Default sort = gold-downside sensitivity** (`down_beta_core`, descending).
7. **Interactive hedge input** (enter $ / quantity → recomputed scenarios).

---

## 0. The simplest thing that could work
> **Add an "Option Trading" nav tab served at `/option-trading`, rendering a sortable/filterable DataTable of the optionable subset (sorted by `down_beta_core`), built from the M1.5 structured dataclasses — not from re-parsed markdown. Clicking a row opens the existing `/ticker/<T>` detail page, which gains an "Option Trading" panel showing that ticker's put AND call candidate grids + scenarios. Add one interactive form on that panel ($ to hedge / quantity) that re-POSTs and recomputes scenarios server-side via `compute_scenario_bundle`. Calls require a new `build_candidate_call_grid` (symmetric to the put grid) since M1.5 only built puts.**

---

## 0.5. CRITICAL — replace the markdown re-parse approach
The current `serve/hedge_readiness_page.py` reads `latest.md` and rebuilds HTML with a regex markdown parser. That throws away the structured data and defeats the reason M1.5 split `report.py` into `build_hedge_readiness_sections()` + emitter. v1 **retires that path**:
- The Option Trading tab and detail panel consume `HedgeReadinessSections` / candidate dataclasses **directly** (call the builder, render HTML from typed data).
- The regex markdown renderer is deleted (or kept only as a clearly-labelled "raw report" fallback link, not the primary surface).

If we don't do this, the tab can never have sortable tables, filters, or the interactive form — markdown-in-a-box can't.

---

## 1. Current state (workspace architecture — verified)
- **Server/routing** (`serve/workspace.py`): GET `/`, `/tool-a`, `/tool-b`, `/hedge-readiness`, `/static/...`, `/ticker/<T>`; POST `/ticker/<T>/{company,reporting,verification,note}`. New routes slot in here.
- **Nav tabs** via `_page_shell(..., active_nav=...)` (`page_shell.py`). Existing navs: combined, tool-a, tool-b, hedge_readiness.
- **Overview pages**: `overview_tool_a.py` / `overview_tool_b.py` render DataTables from `WorkspaceState`. The Option Trading overview mirrors these.
- **Detail page** (`detail_page.py`): renders Tool A + Tool B **panels** (`detail_panels.py`) + edit forms (`detail_forms.py`) for one ticker, data pulled from `WorkspaceState` indexed by ticker. New Option Trading panel is added here.
- **Forms**: `<form method="post" action="/ticker/<T>/<action>">` → handled in `workspace.py` → re-render. The hedge input reuses this exact pattern.
- **DataTables**: client-side sort/filter/search already wired for Tool A/B tables (`static/`). Reuse for the optionable list.

## 1a. Engine state from M1.5 (what we can reuse vs. must build)
| Need | Status |
|---|---|
| Put candidate grid (`build_candidate_put_grid`) | ✅ exists |
| Scenario P&L (`compute_scenario_bundle`), supports LONG_PUT **and** LONG_CALL | ✅ exists |
| Black-Scholes call price | ✅ exists |
| Sensitivity ranking (`down_beta_core`) | ✅ exists |
| Structured sections (`build_hedge_readiness_sections`) | ✅ exists |
| **Call candidate grid** (`build_candidate_call_grid`) | ❌ **must build** (symmetric to puts; target ~+0.25 delta calls) |
| **Call scenarios wired into a builder** | ❌ **must build** |
| Optionability flag per ticker (`optionability_tier`) | ✅ exists in options features |

---

## 2. Architecture & decisions

### 2a. The tab
- New nav **"Option Trading"**, `active_nav="option_trading"`, route `GET /option-trading`.
- New module `serve/overview_option_trading.py` (mirrors `overview_tool_a.py`).

### 2b. The optionable filter
- Show only tickers whose latest options features have `optionability_tier != "none"` (i.e., listed options exist).
- A UI toggle/filter for `directly_hedgeable` only (liquid) vs include `thin`.
- **Open decision OD-1 (below):** require BOTH put and call quotes present, or just "has any options"?

### 2c. The list (DataTable)
Default sort `down_beta_core` desc. Columns:
`Ticker · Down-β(core) · Up-β(core) · Confidence · IV %ile · Optionability · 60d Put @ gold −10% · 60d Call @ gold +10% · (link)`
Client-side search + column sort (DataTables). Server provides the rows as structured data from the sensitivity ranking + candidate grids; **no markdown**.

### 2d. The detail panel (on existing `/ticker/<T>`)
A new `_render_option_trading_panel(...)` added in `detail_page.py` after the Tool A/B panels. Contents:
- **Header context** for the ticker: down-β(core), confidence, IV %ile, implied move vs modeled downside (heuristic).
- **Put candidates** grid (30/60/90d) + P&L scenarios at gold {0, −5, −10, −15, −20}%.
- **Call candidates** grid (30/60/90d) + P&L scenarios at gold {0, +5, +10, +15, +20}% (bullish/gold-up thesis — **OD-2 RESOLVED: long calls = leveraged bullish-gold bet**). **Calls must scale the stock by `up_beta_core`, not `down_beta_core`** — miners move asymmetrically and Tool A computes both betas precisely for this reason. Frame calls explicitly as *speculation* (a call is not a hedge for a long-only holder) and note time-decay risk if gold stalls.
- **Interactive hedge form** (§2f).
- Data-quality notes carried through (stock-clamp, r=0 fallback, missing-candidate, etc.).

### 2e. Both puts and calls — the engine delta
- New `build_candidate_call_grid(...)` in `hedge/candidate_puts.py` (or a renamed shared module) — symmetric to the put grid, selecting calls nearest a target **positive** delta (e.g. +0.25).
- A new builder, e.g. `build_option_trading_detail(ticker, ...)`, returns a typed `OptionTradingDetailData` with both put and call `CandidateScenarioBundle`s. Puts use `compute_scenario_bundle(strategy=LONG_PUT, …, gold_scenarios=<negative>)` scaled by `down_beta_core`. Calls use `compute_scenario_bundle(strategy=OptionStrategy.LONG_CALL, …, gold_scenarios=<positive>)` scaled by **`up_beta_core`**.
- **Engine refinement (P2):** `compute_scenario_bundle`'s scaling beta is currently the param named `down_beta_core`. For the call path it must receive `up_beta_core`. Either (a) generalize the param to a neutral name (e.g. `gold_beta`) so the call path passes up-beta, or (b) document that the param is "the gold-beta to scale by" and pass `up_beta_core` for calls. Likewise the skip threshold should consider an up-beta minimum for calls. Prefer (a) — a clean rename — to avoid a misleading param name.
- Reuses all existing math (BS call price, `compute_strategy_pnl`). No new math, only new selection + wiring + the beta-param generalization.

### 2f. Interactive hedge input (server-side recompute)
- A `<form method="post" action="/ticker/<T>/option">` on the panel with inputs: **quantity** (contracts) and/or **dollar amount to hedge**, plus strategy (put/call) and horizon.
- POST handled in `workspace.py` → recompute `compute_scenario_bundle(quantity=…)` (and share-based sizing from `portfolio_totals` math for a $ amount) → re-render the detail page with results (flash-style, like the existing forms).
- **No client-side math** — the Python math is the single source of truth. Optional progressive enhancement (JS) is out of scope for v1.

### 2g. Data path & freshness (OD-3)
The panel/list need structured option data per request. Options:
- **(a) Compute live** on page load via `build_hedge_readiness_sections()` / `build_option_trading_detail()` — true reuse of the seam, always fresh, but ~24 tickers × candidate grids per request (cache in `WorkspaceState`).
- **(b) Persist structured sections** (parquet/JSON) when the CLI runs; UI loads them — fast, but adds a "stale until you re-run the CLI" caveat.
- **Recommendation:** (a) with a per-process cache keyed on the options-manifest `refresh_run_id` (compute once per data refresh, reuse across requests). Confirm in OD-3.

### 2h. Reuse, not re-parse
All rendering consumes typed dataclasses. The markdown emitter stays for the CLI; the UI gets HTML from the same builders. (Retires §0.5.)

---

## 3. Mock (layout intent)

```
NAV:  [ Combined ] [ Tool A ] [ Tool B ] [ Option Trading ] [ Hedge Report ]

/option-trading  — "Option Trading"
  [search] [filter: directly-hedgeable only ▢] [filter: confidence ≥ …]
  ┌────────────────────────────────────────────────────────────────────┐
  │ Ticker│Down-β│Up-β│Conf│IV%ile│Option.│60d Put@-10%│60d Call@+10%│   │
  │ KGC   │1.85  │1.21│high│45th  │direct │ +$4.50/c   │ +$3.10/c    │ → │
  │ NEM   │1.42  │1.18│high│38th  │direct │ +$13.20/c  │ +$9.80/c    │ → │
  └────────────────────────────────────────────────────────────────────┘   (sortable/filterable)

/ticker/NEM  (existing page; NEW panel appended)
  [Tool A panel] [Tool B panel]
  ── Option Trading ─────────────────────────────────────────────
  Down-β(core) 1.42 (high) · IV %ile 38th · implied move 60d ±5.8% vs modeled −14.2% (model > market, heuristic)
  PUTS  | Horizon | Strike | Mid | Break. | P&L -5% | -10% | -20% |
        | 60d     | 142    |2.20 | -2.1%  | +$2.75  |+13.2 |+34.1 |
  CALLS | Horizon | Strike | Mid | P&L +5% | +10% | +20% |
        | 60d     | 152    |2.40 | +$1.90  |+8.4  |+22.0 |
  [ Hedge:  $ amount [____]  or quantity [__] contracts  · strategy (put/call) · horizon ]  [Recompute]
  → recomputed scenarios shown here
```

---

## 4. Order of operations (phased — value lands incrementally)

| Phase | Steps | Why this order |
|---|---|---|
| **P0 — Tab + list (puts only first)** | (1) `overview_option_trading.py` + `/option-trading` route + nav. (2) Optionable filter from `optionability_tier`. (3) DataTable from sensitivity-ranking structured data, default sort `down_beta_core`. (4) Retire/relabel the markdown page (§0.5). | Gets the tab live from structured data; proves the no-markdown path. |
| **P1 — Detail put panel** | (5) `_render_option_trading_panel` with put candidates + scenarios on `/ticker/<T>`, from `build_hedge_readiness_sections` filtered to the ticker. | Click-through works for puts. |
| **P2 — Calls engine + panel** | (6) `build_candidate_call_grid` + tests. (7) `build_option_trading_detail` returning puts+calls. (8) Add call grid + (positive-gold) scenarios to the panel and a "60d Call @ +10%" list column. | The "both puts and calls" requirement; isolates the new engine work. |
| **P3 — Interactive hedge input** | (9) Hedge form + `POST /ticker/<T>/option` → server recompute → re-render. | Highest-interaction piece, last. |
| **P4 — Polish** | (10) data-quality notes surfaced, empty-states (no options / no candidates), styling in `workspace.css`, docs. | |

Each step one commit; self-review gate after each phase (same rhythm as M1.5); checkpoints after P1, P2, P3. No `git push`.

## 5. Acceptance criteria (v1)
- "Option Trading" nav tab loads `/option-trading`; lists **only** optionable tickers; default sort `down_beta_core` desc; client-side search + sort + the directly-hedgeable filter work.
- The list and detail are rendered from **structured dataclasses**, not re-parsed markdown (grep: no markdown-regex on the option-trading path).
- Clicking a ticker opens `/ticker/<T>` with an **Option Trading panel** showing put **and** call candidate grids + scenarios.
- The hedge form recomputes scenarios **server-side** for a given quantity/$ and re-renders.
- Empty states handled: ticker with no options, no 60d candidate, r=0 fallback note shown when applicable.
- Full suite green (new tests for `build_candidate_call_grid`, the option-trading builder, the route, and the POST handler). No live Yahoo.

## 6. Out of scope (v1)
- Spread strategies, Greeks beyond delta, vol-skew (still constant-IV).
- Saving/persisting hedge inputs (the form is compute-only; no trade journal — that's M4).
- Multi-week "what changed" comparison.
- Client-side JS recompute (server-side only in v1).
- Foreign-listing ADR mapping (those have no options → simply excluded by the optionable filter).

## 7. Risks for the reviewer
1. **Live-compute cost (OD-3):** building candidate grids for ~24 tickers per request could be slow; the cache keyed on `refresh_run_id` is load-bearing — confirm it.
2. **Detail-page coupling:** the detail page currently pulls only Tool A/B from `WorkspaceState`; adding option data means `WorkspaceState` must load options features + candidate grids (or compute on demand). Define the data source cleanly to avoid bloating `WorkspaceState`.
3. **Calls direction (OD-2):** if calls use positive-gold scenarios, the panel mixes a gold-down (puts) and gold-up (calls) frame on one screen — must be labelled unambiguously.
4. **Markdown-page retirement:** ensure nothing else links to the old `/hedge-readiness` regex page once replaced, or keep it as a clearly separate "raw report" link.

## 8. Open decisions to confirm (please answer before P2/P3)
- **OD-1 — Optionable filter strictness:** "optionable" = has any listed options (`tier != none`), or require **both** put and call quotes present? *(Recommend: tier != none, with a directly-hedgeable filter toggle.)*
- **OD-2 — What do calls represent? ✅ RESOLVED (2026-06-02):** long calls = **leveraged bullish bet on gold** (positive-gold scenarios, scaled by `up_beta_core`), the symmetric counterpart to the puts. Framed as *speculation* (not a hedge for a long-only holder), with time-decay caveat. See §2d/§2e.
- **OD-3 — Data freshness:** live-compute-with-cache (always fresh) vs persist-on-CLI-run (faster, can be stale)? *(Recommend: live-compute cached on `refresh_run_id`.)*

---

## Why this plan is shaped this way
- **Reuses the M1.5 seam** instead of re-parsing markdown — that's the whole reason the builder/emitter refactor exists.
- **Matches Tool A/B patterns** (overview DataTable + per-ticker panel + POST form) so it feels native and reuses infra.
- **Phases the two heavy asks** (calls engine, interactivity) after the tab is already live and useful, so value lands early and risk is isolated.
- **Server-side math** keeps one source of truth (no JS re-implementation of Black-Scholes).
