# Plan: M3 — Tool C + Tool D (v4) — both symmetric

**Author:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Date:** 2026-06-04
**Status:** for Codex's final review before a build brief.
**Supersedes:** `claude_tool_c_d_plan_v3.md`. Folds in the two redesigns:
- `claude_tool_c_symmetric_design.md` — Tool C is now **symmetric** (downside + upside ranks).
- `claude_tool_d_gold_stressed_scorecard_design.md` — Tool D is now a **gold-price-calibratable quality scorecard** (symmetric).
All of v3's resolved findings (provenance, percentile-helper reuse, config registration, weekly-series reuse, eligibility, descriptive-not-predictive, thin-data flagging) carry forward unchanged.

## What v4 changes vs v3
| v3 | v4 |
|---|---|
| Tool C = downside-only ranking | **Tool C = symmetric**: a downside rank (put targets) **and** an upside rank (call targets) |
| Tool D = "margin collapse at gold −10/−20" | **Tool D = single tunable gold price → EBITDA + EBITDA-derived ratios recompute → quality rank**, symmetric (up or down gold), reusing Tool B's earnings engine |
| `oriented_percentile` "to be built" | **Already built** by the Candidate Finder (`features/percentile_ranks.py`) — Tool C/D **reuse it** |

## Emanuel's locked decisions
- **Tool C: both upside and downside** (two ranks).
- **Tool D: a single tunable gold price** (not a fixed −10/−20 table); metrics shown **separately** and watch them move with gold (EBITDA, and the EBITDA-derived ratios net-debt/EBITDA and EV/EBITDA); a **gold-stressed quality scorecard usable for up- or down-gold**.
- **Tool D OD-A (resolved):** quality-score weighting = **equal across components, config-driven.**
- **Tool D OD-B (resolved):** the "% EBITDA change" reference = **vs current spot gold.**
- **Data confirmed:** 61/63 miners have AISC, production, net debt, EBITDA, cash cost, reserve life. No new data needed.

---

## 0. The simplest thing that could work
> Two CLI ranking pipelines that mirror Tool A/B. **Tool C** reads `tool_a_latest.parquet` + weekly-resampled foundation equities + gold + GDX/GDXJ and computes **symmetric** behavior metrics (relative weakness/strength, hit-rates, [flagged tails]) → a **downside rank** and an **upside rank** + tags. **Tool D** reads `tool_b_latest.parquet` + the manual store and, **at a user-chosen gold price G**, reuses Tool B's earnings engine to recompute EBITDA(G), gold-sensitive leverage = net_debt/EBITDA(G), EV/EBITDA(G), margins, and a **quality rank at G** + tags — symmetric. Both reuse the shared `oriented_percentile` helper. Both ranks become Candidate Finder criteria (Tool D's parameterized by G). Honest: descriptive not predictive; thin metrics flagged; provenance snapshotted+hashed.

---

## 1. Current state (verified 2026-06-04)
- **Consume, not re-derive:** Tool A latest (betas incl. `down_beta_core`/`up_beta_core`/`asymmetry_ratio_core`, `downside_volatility_52w`, `confidence_score`, `score_eligible`); Tool B latest (`market_cap_musd`, `forward_*`, `ev_ebitda`, `fcf_yield`, `leverage`, targets/upside, `gold_price_assumption`); manual store (AISC, production, net_debt, ebitda_ltm, cash_cost, reserve_life — 61/63 populated).
- **Reuse:** `model/structural.build_structural_weekly_series` (Tool C weekly series — same convention as the betas); `features/percentile_ranks.oriented_percentile` (already built); Tool B's `screening/layer1.py` + `layer2.py` earnings functions (Tool D, at a chosen gold price).
- **Available:** GDX/GDXJ price history (benchmarks) + now option chains; gold history; spot gold (foundation).

---

## 2. Architecture

### 2a. Decisions locked
| Decision | Choice |
|---|---|
| Tool C | Symmetric: `tool_c_downside_rank` + `tool_c_upside_rank`. |
| Tool D | Single tunable gold price `G`; reuse Tool B earnings engine; gold-sensitive leverage = net_debt/forward_EBITDA(G); symmetric quality scorecard + `tool_d_quality_rank` (at G). |
| Percentile | Reuse the single shared `oriented_percentile` (no new helper). |
| Scoring | Percentile + tags; thin metrics flagged & excluded from ranks; descriptive not predictive. |
| Tool D weighting | Equal across components, config. |
| Tool D % EBITDA change | vs current spot gold. |
| Provenance | Snapshot + hash consumed sources; `verify_manifest` validates. |
| Eligibility | Tool C: rank requires enough robust metrics present; ineligible → flagged, sunk. Tool D: score requires AISC+production+spot for the margin/EBITDA block; leverage null+tagged when net_debt missing or EBITDA(G) ≤ 0; Tool B verdict is context only. |

### 2b. Module layout
```
golden_vector/
  features/
    weekly_returns.py     # NEW — thin adapter over build_structural_weekly_series (per-ticker) + gold/benchmark weekly log-returns
    gold_regime.py        # NEW — classify worst-N% AND best-N% gold weeks (rolling 156w, ≥52w warm-up)
    relative_behavior.py  # NEW — relative weakness (down weeks) AND relative strength (up weeks) vs gold & GDX
    percentile_ranks.py   # REUSE (already exists) — oriented_percentile
  model/
    tool_c.py             # NEW — symmetric behavior ranking (downside + upside)
    tool_d.py             # NEW — gold-stressed quality scorecard at a chosen gold price
  ingestion/
    persist_tool_c.py     # NEW — parquet + latest pointer + artifacts (mirror persist_tool_a)
    persist_tool_d.py     # NEW
  screening/layer1.py, layer2.py  # REUSE (Tool D calls the earnings model at gold price G; thin extraction if not callable standalone)
  app/{paths,config,replay_manifest}.py  # EDIT — output dirs, register configs, update_manifest_with_tool_c/_tool_d (copy+hash sources)
  contracts/config_models.py  # EDIT — ToolCConfig + ToolDConfig
  cli.py                 # EDIT — `tool-c`; `tool-d --gold-price <G>`; extend refresh/status
  serve/candidate_finder_data.py + config/candidate_finder.yaml  # EDIT — add Tool C/D ranks as criteria
config/ tool_c.yaml, tool_d.yaml   # NEW
tests/ test_weekly_returns, test_gold_regime, test_relative_behavior, test_tool_c, test_tool_d,
       test_persist_tool_c/d, test_cli_tool_c/d, fixtures
```

### 2c. Tool C — symmetric behavior ranking
Per ticker, over the same weekly log-return series Tool A uses; gold regimes = worst-N% (down) and best-N% (up) gold weeks (rolling 156w, ≥52w warm-up; per-metric post-intersection event counts).

**Downside block (put targets):** `down_beta_core` (re-export), `downside_volatility_52w` (re-export), `rel_weakness_vs_gold_pct`(+count), `rel_weakness_vs_gdx_pct`(+count), `downside_hit_rate_10pct`(+count), `tail_avg_return_worst10/20pct`(+count, **flagged, NOT in rank**). → `tool_c_downside_rank` (0–100 percentile of equal-weighted robust components) + tags (`steep_down_beta`, `persistent_relative_weakness`, `frequent_deep_drops`, `thin_history`, `low_confidence`, `score_ineligible`).

**Upside block (call targets):** `up_beta_core` (re-export), `rel_strength_vs_gold_pct`(+count), `rel_strength_vs_gdx_pct`(+count), `upside_hit_rate_10pct`(+count), `tail_avg_return_best10/20pct`(+count, **flagged, NOT in rank**). → `tool_c_upside_rank` + tags (`steep_up_beta`, `persistent_relative_strength`, `frequent_strong_rallies`, `thin_history`, `low_confidence`).

**Asymmetry context:** re-export `asymmetry_ratio_core`; surface that a high-downside/low-upside name is a put target and vice-versa. Plain-English `tool_c_explanation` per side.

### 2d. Tool D — gold-stressed quality scorecard (at a chosen gold price G)
Inputs: Tool B latest + manual store + spot gold; the **gold price `G`** (CLI flag / UI slider; default = current spot).
Reuse Tool B's earnings model at `G` (don't reimplement royalty/cash-cost/DA/tax):
```
forward_EBITDA(G)        via layer2 earnings model at gold=G
margin_per_oz(G) = G − AISC ;  headroom_to_breakeven_pct(G) = (G − AISC)/G ;  breaks_even_at_gold_usd = AISC
leverage_stressed(G) = net_debt / forward_EBITDA(G)      ← gold-sensitive (NOT trailing ebitda_ltm)
ev_ebitda(G)         = (market_cap + net_debt) / forward_EBITDA(G)
ebitda_pct_change_vs_spot = (forward_EBITDA(G) − forward_EBITDA(spot)) / forward_EBITDA(spot)   (null+tag if spot EBITDA ≤ 0)
```
**Schema (per ticker, at G):** identity + `source_tool_b_run_id` + `gold_price_used` + `spot_gold_usd`; re-exported Tool B context (`market_cap_musd, screening_verdict, confidence, fcf_yield, reserve_life_years, cash_cost_usd_per_oz, best_upside_pct`); the gold-parametrized block above; `tool_d_quality_rank` (0–100 percentile of equal-weighted components — margin/headroom, leverage_stressed, ev_ebitda(G), optionally FCF yield); `tool_d_tags` (`margin_negative_at_G`, `leverage_undefined_at_G` [EBITDA≤0 → null ratio + tag, never inf], `thin_margin_at_G`, `deleveraging_strongly`, `missing_aisc/production/debt`, `screen_out_context` [informational only]); `tool_d_explanation`; `missing_inputs`.
**Symmetric:** the same engine at a high G shows strength (margin expansion, deleveraging); at a low G shows fragility. One tool, both theses.
**Label:** "simplified gold-economics model" (production×(G−costs) ignores hedging/by-products/grade/ramp); the quality rank is **descriptive, not a valuation or a forecast.**

### 2e. Provenance
`compute_tool_c/d` copy consumed assets into `run_dir/replay_snapshots/` and store SHA hashes (reuse the existing snapshot helpers), and `verify_manifest` validates them — not just record mutable `latest.parquet` paths. Tool C sources: tool_a latest, foundation equities + raw gold, benchmark snapshots. Tool D sources: tool_b latest, manual-store DB, foundation raw gold.

### 2f. Shared percentile helper
Both tools use the **existing** `features/percentile_ranks.oriented_percentile` (the same one the Candidate Finder uses). Do NOT add a second percentile implementation.

### 2g. Config
Add `tool_c.yaml` + `tool_d.yaml` + `ToolCConfig`/`ToolDConfig`, and **register both in `app/config.py::EXPECTED_CONFIG_FILES`** (validated + hashed into provenance), with tests.

### 2h. Candidate Finder wiring (the payoff)
Add as config criteria in `candidate_finder.yaml` (the registry is config-driven): `tool_c_downside_rank`, `tool_c_upside_rank`, `tool_d_quality_rank`. The bearish lens uses downside + (low-G) quality; the bullish lens uses upside + (high-G) quality. **Tool D's rank is parameterized by G** — decide whether the Finder uses Tool D at a fixed gold (spot) or exposes the gold dial (v1: use spot; gold-dial-in-finder is a later enhancement). Load the new parquet fields in `candidate_finder_data.py`.

---

## 3. Math (with the v4 specifics)
- **3a Weekly regimes:** weekly gold log-return; rolling 156w (≥52w warm-up); week ≤ 10th/20th pct → down regime; ≥ 90th/80th pct → up regime.
- **3b Relative behavior:** down — % of down-regime weeks `stock_ret < gold_ret` (and vs GDX, intersection range); up — % of up-regime weeks `stock_ret > gold_ret` (and vs GDX). Each carries its own event count.
- **3c Hit-rates:** down — % of down-regime weeks `stock_ret ≤ −10%`; up — % of up-regime weeks `stock_ret ≥ +10%`.
- **3d Tails (flagged, not in rank):** mean stock return in worst/best 10–20% gold weeks; null when events < `min_events`; confidence flag.
- **3e Tool D at G:** §2d formulas; reuse Tool B layer functions; leverage uses forward EBITDA(G); EBITDA %-change vs spot.
- **3f Ranks:** `oriented_percentile` of the equal-weighted **robust** components within the eligible subset; ineligible → NaN, flagged, sunk. (Same orientation/eligibility discipline as the Candidate Finder.)

## 4. Order of operations (batched; checkpoints = stop & report)
**Build sequence:** features → model → persist+provenance → CLI → Finder wiring. Tests gate each step; no hard-coded universe size.
- **Batch 1 — Tool C:** `weekly_returns` (reuse structural builder) → `gold_regime` (both tails) → `relative_behavior` (weakness+strength) → `model/tool_c.py` (two ranks + tags, reuse `oriented_percentile`) → `persist_tool_c` + provenance → `tool-c` CLI. Tests incl. skip paths, GDX-intersection, thin-tail flagging, both ranks. → **CHECKPOINT A** (sample rows; both ranks; asymmetry examples).
- **Batch 2 — Tool D:** *Step 0:* confirm Tool B's `layer1/layer2` earnings functions are callable at an arbitrary gold price (thin extraction if not). Then `model/tool_d.py` (gold dial; EBITDA(G), leverage_stressed(G), ev_ebitda(G), margins, quality rank, tags; reuse Tool B engine) → `persist_tool_d` + provenance → `tool-d --gold-price G` CLI → extend `refresh`/`status`. Tests incl. EBITDA≤0 null+tag, leverage-undefined, margin-negative, gold-dial recompute, equal-weight rank. → **CHECKPOINT B** (sample scorecard at two gold prices; show EBITDA/leverage/EV-EBITDA moving).
- **Batch 3 — Candidate Finder wiring + docs:** add the three ranks to `candidate_finder.yaml` + load them in `candidate_finder_data.py` (with the contract test covering them); docs for Tool C/D + the gold dial + the descriptive/thin-data caveats. → **CHECKPOINT C** (completion report).

One commit per step + a self-review-fixes commit per batch. No `git push`.

## 5. Acceptance criteria
- `tool-c` produces both `tool_c_downside_rank` and `tool_c_upside_rank` (+ tags, explanation, event counts); thin tails flagged + excluded from ranks; weekly series from the structural builder.
- `tool-d --gold-price G` produces EBITDA(G), **gold-sensitive** leverage = net_debt/EBITDA(G), EV/EBITDA(G), margins/headroom, EBITDA %-change vs spot, and `tool_d_quality_rank` (equal-weighted, config) + tags; EBITDA≤0 → leverage null + `leverage_undefined_at_G`; symmetric (sensible at high and low G).
- Both reuse the single `oriented_percentile`; ineligible names → NaN rank, flagged, sunk (not bottom-ranked artificially).
- Provenance: consumed assets snapshotted+hashed and validated by `verify_manifest`; both yamls in `EXPECTED_CONFIG_FILES`.
- Candidate Finder gains the three ranks as criteria (contract test confirms they resolve); bearish lens can rank by downside + Tool D, bullish by upside + Tool D.
- `refresh`/`status` cover Tool C/D. Full suite green; no live data in tests; no hard-coded universe size.

## 6. Out of scope
- The gold dial *inside* the Candidate Finder (v1 uses Tool D at spot). 
- Combined A+B+C+D overview page.
- z-scores; backtesting; new fetchers; ADR mapping; recommendation language.

## 7. Risks for the reviewer
1. **Tool B engine reuse:** confirm `layer1/layer2` can compute forward EBITDA at an arbitrary gold price standalone (Batch 2 Step 0). This is the key technical prerequisite.
2. **Weekly convention parity** with Tool A's betas (reuse `build_structural_weekly_series`).
3. **GDX history shorter than ticker history** → intersection counts; skip-with-tag below `min_events`.
4. **Symmetric ranks share a percentile helper** — confirm one implementation, oriented per side.
5. **Tool D quality rank is descriptive** — must not read as valuation/forecast; "simplified model" label visible.
6. **Eligibility independence:** a Tool-A-ineligible name with good Tool D inputs still gets a Tool D rank (and vice-versa).

## 8. Open items
- **OD-C (technical):** is Tool B's earnings model callable at an arbitrary gold price outside the full pipeline? (Batch 2 Step 0 resolves it.)
- Tool D-in-Finder gold parameter (v1 = spot; dial later) — confirm acceptable.

## 9. Build rhythm
After Codex review + green-light: continuous build, **deep self-review after every step, deeper at each checkpoint** (log to `reviews/codex/codex_tool_c_d_progress.md`); one commit per step + a self-review-fixes commit per batch; **no `git push`**; stop at Checkpoints A/B/C and on any genuine blocker.
