# Ticker page rebuild — plan

- **Date:** 2026-08-11 · **Branch:** dev-vic (fresh from main @0e1ac5e)
- **Ask (Victor):** "When I go on a ticker page I want to really get something out of it — navigate it easily, play with numbers easily, see the options (put/call) easily, and the trend of the interest."
- **Scope (confirmed by Victor):** THIS page only — `/ticker/<T>`. One page showing the ticker's FULL profile including options. Not a cross-surface milestone. Other pages are only touched where they'd otherwise break.
- **Page job (Victor's answer):** both jobs, user-switchable — the toggle changes which block LEADS; both blocks are always complete and always present.
- **Trends (Victor's answer):** all four — put/call OI ratio, total open interest, IV + IV-vs-realised, implied move + skew.

## 1. What the page is today (verified, not remembered)

- **Options are not on it.** The default lens renders `_render_option_trading_link_panel` (`detail_panels.py:389-428`): an `<h2>Option Trading</h2>`, one hint sentence, and a link. Zero option data. Real option content only exists at `?lens=option-trading`, which REPLACES the gold-sensitivity panels. Two half-pages.
- **Ordered research-first:** window switcher → gold-sensitivity metrics → structural window table → scatter → up/down beta → beta comparison → volatility diagnostics → horizon ladder → rebased overlay → corporate finance → (options link) → inputs/reporting/verification/notes. ~15 panels, all expanded, no verdict summary.
- **Controls available today:** beta window (6M/1Y/2Y/3Y/5Y), fundamentals source (our/Yahoo), option sizing (budget/side/horizon, option lens only). **No gold-price dial** — that exists on Tool B, Tool D and Candidate Finder but not here.
- **No trend charts.** Option charts are snapshots only (skew by strike, OI by strike) plus one signal-history line.
- **Speed is no longer a reason to split:** default lens ~45ms warm, option lens ~200-320ms warm (post-2026-08-11 perf work). Merging costs ~200ms — affordable.

## 2. The data that already exists and is unused

`data/intermediate/options_features/<TICKER>.parquet` — one row per as-of date, growing daily from the scheduled refreshes. NEM: **64 rows, 2026-06-01 → 2026-08-10**. Columns include `total_open_interest`, `put_call_oi_ratio_total`, `put_call_oi_ratio_otm`, `total_volume`, `atm_iv_60d/90d`, `iv_skew_60d/90d`, `implied_move_60d/90d`, `iv_rv_ratio_60d`, `realized_vol_60d`, `iv_percentile_cross_sectional`.

**Data-quality trap (must be handled or the charts lie):** same-day duplicates exist (2026-08-10 has 3 NEM rows) and at least one is a PARTIAL capture (`total_open_interest` 354,079 vs the same day's 534,406). Charted naively that draws a fake 33% collapse.

**Architecture consequence:** `options_features` is NOT manifest-registered (checked `latest_model_state.json`). Canon says readers resolve through the manifest and nothing computes in a request path, so the page cannot read these files directly.

## 3. Backend work (must land first)

**New published artifact `option_interest_history`** — one row per (ticker, as-of date), run-stamped, manifest-registered, built by a small pipeline step that:
1. reads the per-ticker options_features files;
2. **dedupes same-day rows** — keep the last run of each day;
3. **excludes/flags partial captures** — a row whose contract count or total OI is a large negative outlier vs its own recent level is marked `capture_status != "OK"` and is EXCLUDED from the plotted series (per canon: degraded data is excluded, not merely flagged), with the exclusion count exposed so the page can say "2 partial captures excluded";
4. emits the display-ready columns the page needs, INCLUDING backend-resolved direction/change (`put_call_ratio_change_30d`, `direction` ∈ rising/falling/flat, `series_quality`) so serve does zero arithmetic.

Threshold for "partial capture" lives in config, once.

## 4. Page design

### 4.1 One page, no content gate
Options ALWAYS render. `?lens=` survives as an **emphasis toggle only** (Victor: "both, user-switchable"): it reorders which block leads and which is auto-expanded — it never hides content. Every existing `?lens=option-trading` link still works and still lands on the options block (`#option-trading` anchor preserved).

### 4.2 Layout (top → bottom)

1. **Control bar (sticky):** ticker + company + last price · **gold-price dial** · beta window · fundamentals source · lens toggle. One row, one place for every knob. All server round-trips (~45-300ms — no new JS deps).
2. **Verdict band:** four cards, each linking to its section — *Gold reaction* (down-beta + gold-link strength), *Resilience* (Tool D status + breakeven gold), *Options* (liquidity verdict + put/call ratio + direction), *Your position* (holding + P&L, or "not held"). Every card labelled with its basis (window, gold price used, as-of date).
3. **Lead block** — Options first (trade lens) or Gold reaction first (research lens).
4. **OPTIONS BLOCK** (always present):
   - **Puts | Calls side by side** — best candidate per side (strike, expiry, premium), IV, spread, open interest, liquidity verdict, backend-selected "most liquid" window.
   - **Interest trends — four sparkline cards** (current value + direction + range), each expanding to a full chart: put/call OI ratio · total OI · IV with IV-vs-realised · implied move with skew. Each carries its as-of date and any "N partial captures excluded" note.
   - **Sizing calculator inline**, prefilled from the selected side/horizon.
   - Snapshot charts (skew by strike, OI by strike) collapsed by default.
5. **GOLD REACTION BLOCK:** up/down beta, gold-link strength, the existing charts. Deep research (structural window table, scatter, horizon ladder, volatility diagnostics) collapsed by default.
6. **CORPORATE FINANCE BLOCK:** existing snapshot, unchanged content.
7. **The connector line** (the point of the whole page): *"Gold −10% → NEM −14.2% (down-beta 1.42, 1Y) → your 45d £5,000 put position +£3,180."* One sentence linking the gold dial, the beta, and the sizing calculator — all three tools on one line. Every input labelled; renders only when all three parts resolve, otherwise says which is missing.
8. **YOUR INPUTS:** company inputs, reporting, verification, notes — collapsed by default.

### 4.3 Usability rules
- Every section opens with one plain-English line saying what it tells you.
- Section nav reduced from 8+ anchors to the 5-6 real blocks.
- Collapsed sections use the existing `disclosure` component (region focus sync already fixed 2026-08-11).
- "Back to top" affordance on long sections.
- No truncation anywhere ("+X more" is banned product-wide).

## 5. Guardrails (non-negotiable)
- No new dependencies; server-rendered round-trips only.
- No arithmetic/ranking/fallback resolution in serve — the new artifact carries display-ready values and direction.
- No invented composite scores; industry-standard metrics only.
- Every gold-dependent number labelled with `gold_price_used` + basis + date.
- Degraded/partial data excluded from the plotted series and from confident headlines, not just flagged.
- Static guardrail test for the new serve surface (clone the serve-arithmetic scan).

## 6. Risks
- **Page length.** Adding options to a page that already has 15 panels only works if collapse discipline is real; the verdict band + reduced nav are what make it navigable.
- **Load cost.** Unifying adds ~200ms/view. Acceptable; the option loader is already cached and sha-verification is stat-gated.
- **The connector line is the highest-value and highest-risk element** — it multiplies three separately-sourced numbers. It must be computed backend-side with every input labelled, or it becomes the next unlabelled-assumption bug.

## 7. Suggested sequence
1. `option_interest_history` artifact + dedupe/partial-capture rules + tests (backend).
2. Unify the page (options always render; lens = emphasis only), preserving every existing URL/anchor contract.
3. Verdict band + control bar + gold dial on this page.
4. Options block: puts|calls side-by-side + sizing inline.
5. Four interest-trend charts.
6. Connector line.
7. Collapse/nav/usability pass + guardrail tests + one browser gate.
