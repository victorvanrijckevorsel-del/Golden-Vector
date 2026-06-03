# Plan: Candidate Finder — multi-criteria weighted screener across all tools (v1)

**Author:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Date:** 2026-06-03
**Status:** for Codex review before any code
**What it is:** the capstone that ties Tool A / Tool B / options (and later Tool C / Tool D) together. The user picks the criteria that matter, sees the top-N by each, and gets a **weighted blended ranking with a score** to surface the 1-3 best candidates — for *any* thesis (bearish puts or bullish calls).

## Emanuel's locked design decisions (this plan implements exactly these)
1. **No chat / NLP in v1** — a **point-and-click screener builder** (pick criteria, set ascending/descending, set top-N per category).
2. **No single obvious winner across lists** → the tool computes a **blended ranking + score**, **equal-weight by default**, with **user-adjustable weight dials** that re-rank.
3. **Options = a YES/NO hard filter** (has listed puts/calls), so non-tradeable names can be excluded up front.
4. **Both directions** — bearish (put) and bullish (call) lenses; per-criterion ascending/descending sets "which end is good."
5. **Missing data → spread the weight across the stock's present criteria, and flag it clearly** ("scored on 4 of 5").
6. **"Equity" = market cap** (confirmed) — so Debt/Equity, EBITDA/Equity, Revenue/Equity = ÷ market cap; computable now, no new data.
7. **Curated criteria list** (confirmed below), config-driven so any future metric plugs in.

---

## 0. The simplest thing that could work
> **A new "Candidate Finder" workspace tab (+ a CLI) that joins the latest Tool A / Tool B / options outputs by ticker, exposes a config-driven list of curated criteria, lets the user (a) optionally filter to optionable names, (b) pick criteria + direction + top-N, and (c) set weights. It shows the per-category top-N lists AND a blended weighted ranking where each criterion is turned into a 0-100 percentile (oriented to the user's chosen "good" direction) and averaged by weight — renormalized over the criteria a stock actually has. The blended score is labeled a "fit-to-your-criteria score, not a return prediction." Tool C / Tool D ranks plug in later as extra criteria via config.**

---

## 1. Current state — what data the criteria draw from (verified 2026-06-03)
All of these exist **today** (no Tool C/D required for v1):
- **Tool A** (`tool_a_latest.parquet`): `down_beta_core`, `up_beta_core`, `structural_delta_core` (plain gold beta), `confidence_score`, `downside_volatility_52w`, `score_eligible`.
- **Tool B** (`tool_b_latest.parquet`): `market_cap_musd`, `forward_revenue_musd` (= gold-assumption × production; confirmed computed in Layer 2), `forward_ebitda_musd`, `forward_net_income_musd`, `forward_pe`, `ev_ebitda`, `fcf_yield`, `leverage` (= **Net Debt / EBITDA** — note: NOT debt/equity), `screening_verdict`, `best_upside_pct`, `tool_b_score`.
- **Manual store** (read-only): `aisc_usd_per_oz`, `net_debt_musd`, `production_oz`.
- **Options features:** `optionability_tier` (→ has-options YES/NO), `iv_percentile_cross_sectional`, `iv_skew_60d`.
- **Derived in the screener (from the above, "equity"=market cap):** `debt_to_mktcap` (= net_debt/market_cap), `ebitda_to_mktcap` (forward EBITDA yield), `revenue_to_mktcap` (sales yield), `netincome_to_mktcap` (earnings yield).

**When Tool C / Tool D ship**, their composite ranks (`tool_c_percentile_rank`, `tool_d_percentile_rank`, `headroom_to_breakeven_pct`) become additional criteria — added as config entries, no rework.

---

## 2. Architecture

### 2a. Decisions locked
| Decision | Choice |
|---|---|
| Interaction | Screener-builder UI (no NLP); criteria + direction + top-N + weights. |
| Scoring | **Percentile-based blended score** (0-100 per criterion, weighted average), equal-weight default, user-adjustable. |
| Why percentile (not raw values) | You can't average AISC dollars with a beta. Percentiles make different-unit criteria comparable and avoid false precision (same approach as Tool C/D). |
| Options | YES/NO **hard filter**. |
| Other filters | Optional per-criterion min/max threshold (advanced) — soft by default, hard if set. |
| Direction | Per-criterion ascending/descending = which end is "good"; enables both lenses. |
| Missing data | Drop that criterion for that stock, **renormalize weights over present criteria**, flag count. |
| Honesty | Blended score = "fit to YOUR criteria," explicitly **not** a return forecast (Atilgan 2020 / Levi-Welch-Karolyi 2020 lesson — same as Tool C). |
| Criteria registry | **Config-driven** (`config/candidate_finder.yaml`) so any metric is added without code. |
| Equity denominator | Market cap. |

### 2b. The criteria registry (config-driven; v1 curated set)
Each criterion is a config entry: `id, label, source_field, group, default_direction (high_good|low_good), unit, available_now`. v1 set:

| Group | Criterion | Source | Default "good" |
|---|---|---|---|
| Sensitivity (A) | Down-beta | `down_beta_core` | high (put thesis) |
| Sensitivity (A) | Up-beta | `up_beta_core` | high (call thesis) |
| Sensitivity (A) | Gold beta (core) | `structural_delta_core` | high |
| Sensitivity (A) | Downside volatility | `downside_volatility_52w` | high = riskier |
| Quality (A) | Confidence | `confidence_score` | high |
| Fragility (B/manual) | AISC | `aisc_usd_per_oz` | high = fragile (put) / low = safe (call) |
| Leverage (B) | Net Debt / EBITDA | `leverage` | high = riskier |
| Leverage (derived) | Debt / market cap | `debt_to_mktcap` | high = riskier |
| Valuation (derived) | EBITDA / market cap (yield) | `ebitda_to_mktcap` | high = cheap |
| Valuation (derived) | Revenue / market cap | `revenue_to_mktcap` | high |
| Valuation (B) | EV/EBITDA | `ev_ebitda` | low = cheap |
| Valuation (B) | Forward P/E | `forward_pe` | low = cheap |
| Valuation (B) | FCF yield | `fcf_yield` | high = cheap |
| Upside (B) | Best upside % | `best_upside_pct` | high |
| Size (B) | Market cap | `market_cap_musd` | (either) |
| Options | IV percentile | `iv_percentile_cross_sectional` | low = cheaper puts/calls |
| Options | IV skew | `iv_skew_60d` | high = more crash-risk priced |
| Options | **Has options** | `optionability_tier != none` | **filter, not a rank** |
| *(future)* C/D | Downside-risk rank, Fragility rank, Headroom to breakeven | Tool C/D | added when built |

### 2c. The scoring math (the heart)
For a chosen set of criteria `C`, each with a user direction and a weight `wᵢ` (defaults equal, normalized so Σwᵢ = 1):
1. **Orient + percentile:** for each criterion `i`, compute each stock's **percentile rank (0-100)** among the stocks that *have* a value for `i`, oriented so the user's "good" end = 100. (If "low is good," invert.)
2. **Blended score:** for stock `s`, `score(s) = Σ_{i present for s} wᵢ·Pᵢ(s) / Σ_{i present for s} wᵢ` (renormalize over present criteria — the missing-data rule).
3. **Eligibility flag:** record `criteria_scored = (# present) / (# selected)`; if `< min_criteria_fraction` (config, e.g. 0.5), tag **low-confidence** and optionally sink.
4. **Rank** stocks by `score` descending → the blended ranking.
5. **Top-N per category** (separate view): sort by criterion `i`'s oriented value, take N.
6. **Cross-category tally:** for each stock, count how many selected categories it lands in the top-N of ("top-10 in 4 of 5").

### 2d. Filters
- **Options YES/NO** (primary): drop non-optionable names before ranking when on.
- **Optional per-criterion threshold** (advanced): e.g. "AISC ≥ $1,500" or "market cap ≥ $500M" as a hard gate. Off by default.

### 2e. The two views (matches your description)
- **View 1 — Per-category top-N lists:** "top 10 by AISC", "top 10 by down-beta", etc. (what you literally asked for first).
- **View 2 — Blended ranking:** one sortable table with the **score**, each stock's **per-criterion percentile**, the **top-N tally**, and the **criteria-scored flag**. This is the "who's best across everything" answer. Weight dials live here and re-rank live.
- **Preset lenses** (convenience): one click to set sensible directions for a **Bearish/put** thesis (down-beta high, AISC high, IV percentile low…) or a **Bullish/call** thesis (up-beta high, AISC low, balance-sheet strong, FCF yield high…). Fully tweakable after.

### 2f. Honesty / framing
- The blended score is labeled **"a fit-to-your-criteria score — it ranks how well each stock matches the criteria and weights *you* chose. It is NOT a prediction of returns."** (Same descriptive-not-predictive lesson as Tool C.)
- Missing-criteria stocks show the "scored on K of N" flag so a thin score is never mistaken for a complete one.
- Percentiles (not raw blended units) avoid false precision.

### 2g. Data layer
- A loader joins `tool_a_latest`, `tool_b_latest`, options features, manual store (and Tool C/D latest when present) **by ticker**, computes the derived market-cap ratios, and caches on a **composite provenance key** (all source run ids) — reuse the `option_trading_data.py` cache pattern.
- Pure scoring engine in `golden_vector/screening_finder/` (or `model/candidate_finder.py`) — takes the joined frame + a screen spec (criteria, directions, weights, filters, N) → returns ranked rows. No I/O in the scorer (testable).

### 2h. UI
- New tab **"Candidate Finder"** (`/candidate-finder`), `active_nav="candidate_finder"`.
- Builder controls: criterion checkboxes grouped by Sensitivity / Fragility / Valuation / Options; per-criterion direction toggle + weight slider; top-N selector; options-filter toggle; preset-lens buttons.
- Screen spec lives in the **URL query** (GET, no mutation — same pattern as the option calculator) so a screen is bookmarkable/shareable.
- Renders View 1 + View 2 with DataTables; all math server-side.

---

## 3. Module layout
```
golden_vector/
  model/candidate_finder.py        # NEW — pure scoring engine (percentiles, blend, tally, missing-data)
  features/percentile_ranks.py     # REUSE/share with Tool C/D (oriented percentile helper)
  serve/candidate_finder_data.py   # NEW — join latest outputs + derived ratios + cache + parse screen spec
  serve/candidate_finder_page.py   # NEW — render the builder + View 1 + View 2
  serve/workspace.py               # EDIT — /candidate-finder route
  serve/page_shell.py              # EDIT — nav entry
  contracts/config_models.py       # EDIT — CandidateFinderConfig (criteria registry, defaults, min-criteria)
  cli.py                           # EDIT — `candidate-finder` command (spec via flags/JSON → ranked parquet)
config/candidate_finder.yaml       # NEW — criteria registry + preset lenses + defaults
tests/  test_candidate_finder_scoring.py, test_candidate_finder_data.py,
        test_candidate_finder_routes.py, test_candidate_finder_config.py
```

## 4. Explicit formulas
- **Oriented percentile:** `Pᵢ(s) = 100 × rank_pct(valueᵢ(s) among present)`, inverted if direction = low-good. Ties → average rank. Missing → excluded from that criterion's percentile pool.
- **Blended score:** `score(s) = Σ_{i∈present(s)} wᵢ·Pᵢ(s) / Σ_{i∈present(s)} wᵢ`, `wᵢ` normalized over *selected* criteria; renormalized over *present* per stock.
- **Top-N tally:** `Σ_i 1[s ∈ topN(i)]`.
- **Criteria-scored:** `|present(s)| / |selected|`.

## 5. Mock
```
NAV: … [ Option Trading ] [ Candidate Finder ]

/candidate-finder        Preset: ( Bearish / Put )  ( Bullish / Call )   [☑ only optionable]
 Criteria (check, set direction, weight):
   ☑ Down-beta        [high▼]  w:[===|---] 0.25
   ☑ AISC (fragility) [high▼]  w:[===|---] 0.25
   ☑ Net Debt/EBITDA  [high▼]  w:[==|----] 0.20
   ☑ IV percentile    [low ▼]  w:[==|----] 0.15
   ☑ Down-vol         [high▼]  w:[==|----] 0.15      Top-N per category: [10]

 VIEW 1 — Top 10 by each criterion (tabs): [Down-beta] [AISC] [Net Debt/EBITDA] …
 VIEW 2 — Blended ranking
 | Rank | Ticker | Score | Down-β %ile | AISC %ile | Lev %ile | IV %ile | DownVol %ile | In top-10 of | Scored |
 | 1    | XYZ    | 81    | 95          | 88        | 70       | 60      | 90           | 4/5          | 5/5    |
 | 2    | ABC    | 76    | 80          | 92        | 65       | 55      | 78           | 3/5          | 4/5 ⚠ |
   ⚠ ABC scored on 4 of 5 (missing IV percentile — weight redistributed).
 "This score ranks fit to YOUR criteria/weights. It is not a prediction of returns."
```

## 6. Order of operations (batched)
**Build sequence:** config registry → pure scoring engine → data/join layer → CLI → UI. Tests gate every step.
- **Batch 1:** `candidate_finder.yaml` + `CandidateFinderConfig` + the pure scoring engine (`candidate_finder.py`) with percentile/blend/tally/missing-data + heavy unit tests (equal-weight, custom-weight, missing-data renormalization, direction inversion, ties). → **Checkpoint A.**
- **Batch 2:** data/join layer (latest outputs + derived market-cap ratios + cache) + `candidate-finder` CLI (spec → ranked parquet) + tests. → **Checkpoint B** (sample ranked output on real data).
- **Batch 3:** UI tab (builder controls, View 1 + View 2, preset lenses, options filter, URL-spec, honesty labels) + route + tests. → **Checkpoint C** (completion report + screenshots).

One commit per step; self-review per step; deeper review per checkpoint; no `git push`.

## 7. Acceptance criteria
- `/candidate-finder` tab: pick criteria + direction + top-N + weights; optional options-filter; preset bear/bull lenses.
- View 1 (per-category top-N) and View 2 (blended ranking with score, per-criterion percentiles, top-N tally, criteria-scored flag) both render, from structured data, server-side math only.
- Equal-weight default; changing weights re-ranks; percentiles oriented to the chosen direction.
- Missing data → weight renormalized + visible flag; never silently sinks a stock without a note.
- Derived market-cap ratios (debt/EBITDA/revenue/net-income ÷ market cap) computed correctly from Tool B + manual.
- Blended score labeled "fit-to-criteria, not a return forecast."
- Criteria registry is config-driven (adding one is a YAML edit); Tool C/D criteria slot in when present.
- Full suite green; no live data in tests.

## 8. Out of scope (v1)
- Natural-language / chat querying (possible later).
- Saving named screens to disk (URL-spec is shareable; a saved-screens store is a future add).
- Tool C/D criteria population (wired as config when those tools exist).
- Backtesting how these screens would have performed (separate, and the research warns screens decay).

## 9. Risks for the reviewer
1. **Percentile pool with missing data** — confirm percentiles are computed only over stocks that have the value, and the renormalization is correct so missing data neither helps nor unfairly sinks a stock.
2. **Direction semantics** — one source of truth for "high-good vs low-good" per criterion (config default + user override), applied consistently in both views.
3. **Derived-ratio correctness** — `debt_to_mktcap` etc. need market_cap > 0 guards; null when absent, not zero.
4. **Provenance/freshness** — cache key must include every source run id (A, B, options, manual, C/D) so the screen reflects the latest data.
5. **Honesty** — the score must not read as a return forecast; the "scored on K of N" flag must be impossible to miss.

## 10. Open decisions to confirm (before Batch 2)
- **OD-1:** default top-N (10? 15?) and default min-criteria-fraction for the low-confidence flag (e.g. 0.5).
- **OD-2:** include the optional per-criterion threshold filters in v1, or defer (keep v1 = options-filter + ranking only)? *(Lean: include simple min/max, it's cheap and you value filtering.)*
- **OD-3:** sequencing — build this **now on existing data** (Tool C/D ranks added later), or after Tool C/D? *(Lean: build now — it's the most useful piece, works on current data, and Tool C/D plug in as config later.)*

## 11. Relationship to Tool C/D (important)
This finder **overlaps** with Tool C/D by design: it can compute a downside/fragility ranking from raw metrics (down-beta, AISC) *itself*, so it doesn't need Tool C/D to be useful. The difference: Tool C/D are **curated, opinionated** rankings with bespoke metrics, tags, thin-data handling, and provenance; the finder is a **generic, user-driven** weighted ranker. They coexist — Tool C/D ranks become *high-level criteria* inside the finder. This is why the finder can ship first if desired.
