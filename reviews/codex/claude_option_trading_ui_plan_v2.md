# Plan: Option Trading Tab (Workspace UI) — v2

**Author:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Date:** 2026-06-02
**Status:** for Codex re-review (v1 graded NEEDS CHANGES — `codex_review_claude_option_trading_ui_plan.md`)
**Supersedes:** `claude_option_trading_ui_plan.md` (v1)
**Builds on:** M1.5 engine (`build_hedge_readiness_sections`, `compute_scenario_bundle`, `black_scholes_call_price`).

## v2 changelog — every Codex v1 finding addressed
| Codex finding | Resolution in v2 |
|---|---|
| **1 (P1)** cache contract vague / keyed too narrowly | §2d: a **dedicated** option-trading data module (not the full report builder), composite cache key over **all** upstream run_ids (options manifest + Tool A + Tool B), explicit invalidation, missing-manifest behavior, and separate overview-row vs per-ticker-detail builders. |
| **2 (P1)** call side needs a generic candidate model | §2e: introduce a generic **`OptionCandidate`** (with `option_type`) replacing the put-shaped types; rename `down_beta_used → gold_beta_used`; generalize breakeven/skip messages; `build_candidate_grid(option_type=…)`. Done as the **first step of v1b**. |
| **3 (P1)** OD-1 not deferrable | §2a: **RESOLVED** — tab = "has any listed options" (`tier != none`); each row carries explicit **per-side status** (`put_status`, `call_status` ∈ available/thin/none). Handles the call-only / put-only edges. |
| **4 (P1)** interactive form wrong HTTP shape | §2h: the calculator becomes a **GET query** on the detail page (bookmarkable, no mutation), explicit **mode selector** (contracts XOR budget) so there's no precedence ambiguity, full validation rules, identical budget→contracts math for puts/calls, no-persistence tests. |
| **5 (P2)** detail nav / active state undesigned | §2g: URL `/ticker/<T>?lens=option-trading#option-trading`, `active_nav="option_trading"`, panel anchored/scrolled-to, invalid-lens fallback to default. |
| **6 (P2)** markdown retirement vs nav inconsistent | §0.5: **redirect** `/hedge-readiness → /option-trading`, remove the "Hedge Report" nav entry and the regex renderer; raw report available only as a download link to `latest.md`. One nav entry. |
| **7 (P2)** puts/calls mixed without info design | §2g: detail uses **segmented "Downside puts" / "Upside calls"** sections; overview keeps downside-sensitivity sort with the call figure clearly labelled a **context column** (+ an `up_beta_core` context column), never presented as a call ranking. |
| **8 (P2)** milestone too broad | §4: split into **v1a** (tab + optionable overview + put detail from structured data, retire markdown) and **v1b** (generic candidate model + calls + calculator), each with checkpoint-level acceptance. |

OD-1/OD-2/OD-3 are all resolved in §2a — no open decisions remain.

---

## 0. The simplest thing that could work
> **v1a:** a native "Option Trading" nav tab at `/option-trading` showing a sortable/filterable DataTable of the optionable subset (sorted by `down_beta_core`), built from a **dedicated backend option-trading data layer** (not re-parsed markdown, not the full report builder). Clicking a row opens `/ticker/<T>?lens=option-trading`, which gains a **put** Option Trading panel. Redirect the old markdown page here.
> **v1b:** generalize the candidate engine to `OptionCandidate`, add **call** candidates (leveraged bullish-gold bet, scaled by `up_beta_core`), render a segmented Downside/Upside detail, and add a **GET-query sizing calculator** (contracts or budget) that recomputes scenarios **server-side**.

---

## 0.5. Markdown page — retire it (resolves finding 6)
- **Delete** the regex markdown renderer in `serve/hedge_readiness_page.py`.
- **Redirect** `GET /hedge-readiness → /option-trading` (301/302) so existing links/bookmarks survive. Test the redirect.
- Remove the "Hedge Report" nav entry. The CLI still writes `latest.md`; expose it only as a **"Download raw report"** link (serves the file), not a parsed page.
- One canonical place for the put/call tool: the **Option Trading** tab.

---

## 1. Current state (verified)
**Workspace** (`serve/`): live server. GET `/`, `/tool-a`, `/tool-b`, `/hedge-readiness`, `/ticker/<T>`; POST `/ticker/<T>/{company,reporting,verification,note}` (these **mutate + redirect**). Detail page renders Tool A/B **panels** + forms from `WorkspaceState`, returns `active_nav="combined"`. DataTables (client-side sort/filter/search) already wired for Tool A/B overviews.

**Engine (M1.5):** `build_candidate_put_grid` (puts only; filters `option_type=="P"`), `CandidatePut`, `CandidateScenarioBundle.candidate: CandidatePut` with `down_beta_used`, put-shaped breakeven; `compute_scenario_bundle` supports `LONG_CALL` but its scaling-beta param is named `down_beta_core`; `black_scholes_call_price` exists. `optionability_tier` is **put-driven** (`directly_hedgeable` needs all target-horizon put IVs).

**Data sanity (Codex-verified, latest local):** 60 feature rows, **22 optionable**, 21 directly-hedgeable, 1 thin — and that thin row has a 60d **call** IV but **no** 60d put IV. The row model must represent per-side availability.

---

## 2. Architecture

### 2a. Decisions locked
| Decision | Choice |
|---|---|
| Tab | "Option Trading", `active_nav="option_trading"`, `GET /option-trading`. |
| **OD-1 optionable filter** | Tab includes any ticker with **listed options** (`optionability_tier != "none"`). Each row shows explicit **`put_status`** and **`call_status`** (`available`/`thin`/`none`). A UI filter narrows to "directly-hedgeable" and/or "put available"/"call available". **No requirement that both sides exist.** |
| **OD-2 calls** | **Long calls = leveraged bullish-gold bet**, scaled by **`up_beta_core`**, positive-gold scenarios. Framed as **speculation** (not a hedge), with time-decay caveat shown at the P&L table. |
| **OD-3 data freshness** | Live-compute via a dedicated builder, **cached on a composite key of all upstream run_ids** (§2d). |
| Detail location | A **panel** on the existing `/ticker/<T>` page (alongside Tool A/B), reached via `?lens=option-trading`. |
| Calculations | **100% backend (Python).** The browser does only display-level sort/filter/search (DataTables). See §2b. |
| Sizing calculator | **GET query**, compute-only, no persistence (§2h). |

### 2b. Backend-vs-frontend separation (all math in the backend)
**Hard rule:** every financial number is computed in Python and passed to the renderer as a finished value. The frontend performs **zero** financial calculation.

```
BACKEND (Python)                                   FRONTEND (HTML/JS)
─────────────────────────────────────────         ─────────────────────────
hedge/        ← option math & selection            DataTables only:
  option_trading.py  (builders, pure)                - sort pre-computed columns
  candidate_puts.py → OptionCandidate, grids         - text search / filter rows
  scenarios.py       compute_scenario_bundle         - toggle visible filters
serve/                                              NO Black-Scholes, NO P&L,
  option_trading_data.py (load + cache)             NO sizing math in JS.
  overview_option_trading.py (row → HTML)
  detail_panels.py  _render_option_trading_panel
  workspace.py      routes (GET only for this tab)
```
- The sizing calculator recomputes **server-side** on each GET (re-renders with new numbers). No JS recompute, so Python stays the single source of truth (no risk of a JS Black-Scholes drifting from the Python one).
- DataTables sorting/filtering operates on already-rendered numeric cells — display only.

### 2c. File tree
```
golden_vector/
  hedge/
    candidate_puts.py        # EDIT (v1b) — generalize to OptionCandidate + build_candidate_grid(option_type=…)
    scenarios.py             # EDIT (v1b) — rename down_beta_used→gold_beta_used; param down_beta_core→gold_beta; per-type breakeven/skip
    option_trading.py        # NEW — pure builders: overview rows + per-ticker detail (no I/O, takes frames in)
  serve/
    option_trading_data.py   # NEW — load frames + composite-key cache; calls hedge/option_trading builders
    overview_option_trading.py  # NEW — render the optionable DataTable
    detail_panels.py         # EDIT — add _render_option_trading_panel (segmented puts/calls + calculator)
    detail_page.py           # EDIT — lens routing, active_nav, anchor
    workspace.py             # EDIT — /option-trading route, /hedge-readiness redirect, lens/calculator query handling
    page_shell.py            # EDIT — add nav entry; remove "Hedge Report"
    hedge_readiness_page.py  # DELETE (regex renderer) — replaced by redirect
    static/workspace.css     # EDIT — panel + segmented-control styling
tests/  test_option_trading_data.py, test_option_trading_overview.py,
        test_option_trading_panel.py, test_candidate_grid_calls.py,
        test_option_trading_routes.py (redirect + GET calculator + no-mutation)
```

### 2d. Data & cache layer (resolves finding 1)
**Module:** `serve/option_trading_data.py`. **Does not** call `build_hedge_readiness_sections` (that builds portfolio/proxy/speculation/comparison the tab doesn't need).

- **Inputs:** options features frame, raw chains, Tool A latest, Tool B latest, options manifest.
- **Builders (pure, in `hedge/option_trading.py`):**
  - `build_option_trading_overview(*, tool_a, options_features, candidate_grids, risk_free_rate, …) -> OptionTradingOverviewData` (list of rows).
  - `build_option_trading_detail(*, ticker, tool_a, tool_b, chain, risk_free_rate, sizing, …) -> OptionTradingDetailData` (put + call bundles for one ticker).
- **Single source for candidate grids (holistic correctness):** the data layer computes each optionable ticker's candidate grids **once** and feeds **both** the overview rows **and** the per-ticker detail from that same cached set. This guarantees the overview's "Put @ −10% (60d)" is the *identical* number shown on the detail page (no chance of two independent computations diverging) and avoids double work.
- **Cache:** module-level cache keyed on a **composite** of all upstream provenance:
  `key = (options_manifest.refresh_run_id, tool_a_run_id, tool_b_run_id)`.
  Recompute when **any** changes (fixes the "stale when Tool A/B change" hole). The cache holds the **per-contract** bundles (candidates + per-contract scenarios). The sizing calculator does **not** invalidate or re-key this cache — net P&L is linear in quantity, so sizing is applied as a cheap multiply at render time (§2h). Cache key is provenance-only.
- **Missing-manifest / no-data:** return an explicit empty `OptionTradingOverviewData(rows=[], reason="no options snapshot yet")`; the page shows the same "run the CLI" empty-state as today, never a stack trace.

### 2e. Generic option candidate model (resolves finding 2) — v1b, first step
Replace the put-shaped types with a generic model so calls don't "read like puts":
```python
@dataclass(frozen=True)
class OptionCandidate:
    option_type: Literal["P", "C"]
    ticker: str
    horizon_days: int
    expiration: str
    days_to_expiry: int
    strike: float
    bid: float | None; ask: float | None; mid: float | None
    open_interest: int | None; volume: int | None
    implied_volatility: float | None
    delta: float | None; delta_gap: float | None
    premium_pct_spot: float | None
    underlying_price: float
```
- `build_candidate_grid(*, option_type, target_delta, …)` — `option_type="P"` selects puts near −0.25Δ; `"C"` selects calls near +0.25Δ. **Back-compat:** the shipped CLI report (`report.py`) and its tests use `CandidatePut`/`build_candidate_put_grid`; keep `build_candidate_put_grid` as a thin wrapper returning `OptionCandidate`s **and** alias `CandidatePut = OptionCandidate` so the M1.5 report keeps working byte-for-byte. Update the renamed-field references (`down_beta_used → gold_beta_used`) in `report.py` and tests in the same step.
- `CandidateScenarioBundle.candidate: OptionCandidate`; rename `down_beta_used → gold_beta_used`.
- **Scaling beta param:** rename `compute_scenario_bundle(down_beta_core=…)` → `gold_beta=…`; puts pass `down_beta_core`, calls pass `up_beta_core`. Skip threshold `gold_beta_min_for_scenario` applies to whichever beta is used.
- **Breakeven** computed per type: put → gold-down % needed; call → gold-up % needed (`((strike+premium)/price − 1)/up_beta`). Skip/annotation messages parameterized by direction ("gold-down"/"gold-up").
- This refactor is **isolated as v1b step 1**, with the existing put tests updated to the renamed fields (behaviour for puts unchanged).

### 2f. Overview tab + row model (resolves findings 3, 7)
`OptionTradingRow`:
```
ticker, down_beta_core, up_beta_core, confidence_label, confidence_score,
iv_percentile_cross_sectional, optionability_tier,
put_status, call_status,                  # available | thin | none
pnl_put_at_minus10_60d,                    # downside context
pnl_call_at_plus10_60d,                    # upside context (v1b)
notes: list[str]                           # honest per-side notes
```
- **Default sort:** `down_beta_core` desc (the downside-sensitivity story).
- **Per-side status is derived from actual candidate availability** (does a usable put / call candidate exist at the target horizons), **not** from the put-driven `optionability_tier`. This is what correctly flags the call-only / put-only edge rows. `optionability_tier` is shown as separate liquidity context only.
- **Row dataclass evolution:** introduced in v1a with the put fields populated and the call fields (`call_status`, `pnl_call_at_plus10_60d`) present but `None`; v1b populates the call fields. One dataclass, no reshape between phases.
- The **call P&L column is explicitly a context column** ("Call @ gold +10% — context, not a call ranking"), with `up_beta_core` shown alongside so users don't misread the sort. (v1a renders put columns only; call columns become visible in v1b.)
- Client-side DataTables search/sort + filters: directly-hedgeable only, put-available, call-available.
- Empty/thin sides render as "—" with a note, never hidden.

### 2g. Detail panel, nav & lens (resolves findings 5, 7)
- **URL:** `/ticker/<T>?lens=option-trading` (optionally `#option-trading`). Invalid `lens` → default Tool A view (no error).
- When arrived via that lens: `active_nav="option_trading"`, the page **anchors/scrolls to** the Option Trading panel. The panel is always rendered on the detail page; the lens just sets nav + scroll focus (keeps it consistent with the Tool A/B panels always being present).
- **Panel layout:** segmented control / two clearly-labelled subpanels:
  - **Downside puts** — put candidate grid + P&L at gold {0,−5,−10,−15,−20}% (scaled by `down_beta_core`). Usable as hedge **or** speculation.
  - **Upside calls** *(v1b)* — call candidate grid + P&L at gold {0,+5,+10,+15,+20}% (scaled by `up_beta_core`). Labelled **"leveraged bullish speculation — not a hedge; loses to time decay if gold stalls."**
  - Shared header: down-β/up-β(core), confidence, IV %ile, implied-move-vs-modeled (heuristic), data-quality notes (stock-clamp, r=0 fallback, missing-candidate).

### 2h. Sizing calculator — GET, compute-only (resolves finding 4) — v1b
- **Shape:** GET query on the detail page, e.g.
  `/ticker/NEM?lens=option-trading&side=put&horizon=60&size_mode=contracts&quantity=5`
  or `&size_mode=budget&budget=5000`. Bookmarkable, survives refresh/back, **mutates nothing**.
- **Mode selector (XOR — no precedence ambiguity):**
  - `size_mode=contracts` → use `quantity` directly.
  - `size_mode=budget` → `contracts = floor(budget / (candidate.mid × 100))`; show contracts bought + leftover cash. **Identical mapping for puts and calls** (premium budget → contracts).
- **Validation:** `quantity` positive int; `budget` positive number; `side ∈ {put,call}`; `horizon ∈ target horizons`. Any invalid/missing → fall back to config defaults (`default_scenario_quantity`, 60d) and show an inline note. Never error.
- **Compute:** the per-contract scenarios come from the cached bundle (§2d); applying `quantity` is a **linear rescale** of net P&L done in Python at render time (no Black-Scholes recompute, no cache invalidation). `budget` mode first derives `contracts` then rescales identically. All arithmetic server-side; the response is fully-formed numbers.
- **No persistence:** add tests asserting a calculator GET writes nothing to disk/state (no parquet, no manifest, no WorkspaceState mutation).
- **Note:** "$ exposure to hedge" share-based sizing stays in the holdings/portfolio-totals surface (M1.5), **not** this per-ticker calculator — here `budget` means premium spend. This keeps the puts/calls dollar mapping identical and unambiguous.

---

## 3. Mock
```
NAV:  [ Combined ] [ Tool A ] [ Tool B ] [ Option Trading ]          (no "Hedge Report")

/option-trading
  [search] [☐ directly-hedgeable only] [☐ put available] [☐ call available]
  | Ticker│Down-β│Up-β│Conf│IV%ile│Put│Call│Put@-10% (60d)│Call@+10% (60d, context)│→ |
  | KGC   │1.85  │1.21│high│45th  │ ✓ │ ✓ │ +$4.50/c     │ +$3.10/c               │→ |
  | (sortable; default sort = Down-β desc; call column labelled "context, not a ranking")

/ticker/NEM?lens=option-trading        (existing page; anchors to this panel)
  [Tool A panel] [Tool B panel]
  ══ Option Trading ═════════════════════════════════════════
  Down-β 1.42 · Up-β 1.18 · conf high · IV %ile 38th · implied 60d ±5.8% vs modeled −14.2% (heuristic)
  ( Downside puts | Upside calls )            ← segmented control
  ▸ Downside puts:  | 60d | K142 | mid 2.20 | break −2.1% | -5% +2.75 | -10% +13.2 | -20% +34.1 |
  ▸ Upside calls (leveraged bullish speculation — not a hedge):
                    | 60d | K152 | mid 2.40 |              | +5% +1.9  | +10% +8.4 | +20% +22.0 |
  Sizing:  ( ◉ contracts [5]  ○ budget $[____] )  side(put/call) horizon(30/60/90)  [Recompute]
  → recomputed net P&L (server-side) shown here
```

## 4. Phases (resolves finding 8) — two reviewable deliveries, hard checkpoints

### v1a — native tab + optionable overview + put detail (replaces markdown)
| Step | Work | Checkpoint/acceptance |
|---|---|---|
| 1 | `serve/option_trading_data.py` + `hedge/option_trading.py` overview builder + composite-key cache + tests | data layer returns rows from structured data; cache invalidates on any upstream run_id change |
| 2 | `/option-trading` route + nav + `overview_option_trading.py` DataTable (put columns), default sort down-β, filters, empty/thin notes | **CHECKPOINT A:** tab live, optionable-only, sortable/filterable, from structured data (no markdown). |
| 3 | `_render_option_trading_panel` (puts) + `?lens=option-trading` nav/anchor on `/ticker/<T>` | put detail reachable from a row click |
| 4 | Retire markdown: delete renderer, redirect `/hedge-readiness`, remove nav entry, raw-report download link, tests | **CHECKPOINT B:** markdown path gone; one canonical tab. |

### v1b — generic candidates + calls + calculator
| Step | Work | Checkpoint/acceptance |
|---|---|---|
| 5 | Generalize to `OptionCandidate` + `build_candidate_grid` + scenario field/param renames; put tests updated (no behaviour change) | suite green; puts identical |
| 6 | `build_candidate_grid(option_type="C")` + call scenarios scaled by `up_beta_core`; call columns/context in overview; call subpanel in detail | **CHECKPOINT C:** calls render as a clearly-labelled bullish-speculation view. |
| 7 | GET sizing calculator (modes, validation, server recompute, no-persistence tests) | **CHECKPOINT D:** calculator works, mutates nothing, bookmarkable. |
| 8 | Polish: styling, empty-states, docs (dual gold-direction framing, calculator help) | suite green |

One commit per step; self-review gate after each checkpoint; no `git push`.

## 5. Acceptance criteria
- "Option Trading" tab lists **only** optionable tickers, with per-side `put_status`/`call_status`; default sort `down_beta_core` desc; search/sort/filters work; rendered from **structured dataclasses** (grep: no markdown regex on this path).
- `/hedge-readiness` redirects to `/option-trading`; no "Hedge Report" nav; regex renderer deleted; raw report available as a download link.
- Detail `/ticker/<T>?lens=option-trading` sets `active_nav="option_trading"`, anchors to the panel; invalid lens falls back cleanly.
- Detail shows segmented **Downside puts** (down-beta) and **Upside calls** (up-beta, labelled speculation).
- Sizing calculator is a **GET** that recomputes **server-side**, supports contracts XOR budget, validates inputs, and **persists nothing** (tested).
- **No financial math in the frontend** — verified in review: the only JS is DataTables (sort/filter/search on pre-computed numeric cells). Every P&L, candidate, breakeven, and sizing figure is produced in Python and passed to the renderer as a finished value.
- Full suite green; new tests for the data/cache layer, call grid, routes (redirect + calculator + no-mutation). No live Yahoo.

## 6. Out of scope (v1)
Spreads, Greeks beyond delta, vol-skew (still constant-IV), saving hedge inputs / trade journal (M4), multi-week comparison, client-side JS recompute, ADR mapping (excluded by the optionable filter), "$ exposure to hedge" sizing on this per-ticker calculator (lives in portfolio totals).

## 7. Risks for the reviewer
1. **Cache correctness:** the composite key must include every input that changes the numbers (options manifest + Tool A + Tool B run_ids, plus sizing inputs for the per-ticker cache). Confirm no input is missed.
2. **`OptionCandidate` migration churn:** renaming `CandidatePut`/`down_beta_used` touches scenarios + several tests. Isolate in v1b step 5; keep puts behaviour byte-for-byte.
3. **Detail-page data source:** the panel needs option data on `/ticker/<T>`; route it through `option_trading_data.py`, not by bloating `WorkspaceState`.
4. **Info design:** the call column/subpanel must read as *context/speculation*, never as a call ranking, given the downside-sorted overview.

## 8. Open decisions
**None.** OD-1/OD-2/OD-3 resolved in §2a. If the reviewer disagrees with the calculator's `budget = premium spend` semantics (§2h), that's the one place worth a second opinion.
```
