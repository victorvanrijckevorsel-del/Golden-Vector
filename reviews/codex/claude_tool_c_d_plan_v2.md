# Plan: M3 — Tool C + Tool D + wire Tool C into the Option Trading tab (v2)

**Author:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Date:** 2026-06-03
**Status:** for Codex review before any code
**Supersedes:** `claude_tool_c_d_plan.md` (v1, 2026-05-29, graded NEEDS CHANGES by Codex)
**Related:** `codex_review_claude_tool_c_d_plan.md` (the 7 risks + 3 findings v2 resolves), `codex_tool_c_d_ideas_and_critique.md`.

## Emanuel's locked scope decisions (this plan implements exactly these)
1. **Tool C AND Tool D together** in this milestone.
2. **CLI first, then wire Tool C into the Option Trading tab** (Phase 2, same milestone) — replace the tab's single `down_beta_core` sort with the richer Tool C score.
3. **Be honest when data is thin.** The headline rank is built on statistically robust signals; thin "worst-gold-week" tail metrics are still shown but clearly flagged low-confidence and do **not** silently drive the rank. A name with insufficient history gets an explicit `thin_history` / `low_confidence` tag instead of a falsely precise number.

---

## v2 changelog — what changed since v1 (and every Codex finding resolved)
| v1 issue (Codex) | Resolution in v2 |
|---|---|
| **Blocker — GDX/GDXJ benchmark history not persisted** | **Resolved by reality:** M1 now persists benchmarks (`options_phase._fetch_and_persist_benchmarks` → `paths.benchmarks_dir` + run-local `snapshots/benchmarks/`; manifest records `benchmark_snapshot_paths`). Tool C reads these. §1. |
| **Blocker — no weekly-return artifact at the named path** | **Pinned:** Tool C reads the **daily** normalized equities from `load_latest_foundation_snapshot` (`app/latest_data.py:77`, `normalized_equities_snapshot_path`) and **resamples to weekly itself** in a new `features/weekly_returns.py`. No phantom artifact. §1, §3. |
| **Risk 1 — event counts must be metric-local** | Each metric carries its **own** surviving event count after its data intersection; confidence flags are per-metric, never tool-global. §2f, §2c. |
| **Risk 4 — negative current margin / EBITDA %-change** | When current EBITDA ≤ 0, `ebitda_pct_change_*` are **null + tagged**, never a misleading %. §2d, §4d. |
| **Risk 5 / 7 — Tool D eligibility vs Tool B verdict** | One rule: **Tool B verdict is display context only.** Tool D ranks **margin** components when AISC+production+spot exist, and **separately suppresses leverage** components when debt or positive-stress-EBITDA is missing. No inheritance of Tool A eligibility; no disqualify-on-SCREEN_OUT. §2e. |
| **Risk 6 — net_debt/EBITDA divide-by-zero** | New tag `leverage_undefined_under_stress`; leverage ratios are **null** when stress EBITDA ≤ 0. Never emit inf / negative leverage / a rank contribution from an undefined ratio. §2d, §2e. |
| **Finding 1 — provenance underspecified** | Tool C/D explicitly record consumed source paths (Tool A/B `latest.parquet`, foundation snapshot, benchmark snapshots, manual store) into the replay manifest via a new `update_manifest_with_tool_c/d`, mirroring `update_manifest_with_foundation`. §3, §2a. |
| **Finding 2 — 64 vs 60 hardcoding** | No hard-coded universe size anywhere; tests assert against fixture sizes, not literals. §6. |
| **Finding 3 — config loader hook** | `config/tool_c.yaml` + `tool_d.yaml` are registered in `app/config.py::EXPECTED_CONFIG_FILES` so they're hashed into provenance. §2b, step 1. |
| **NEW — confidence/thin-data policy** | §2f: robust-signal headline rank; thin metrics shown + flagged, excluded from the rank. (Emanuel's directive.) |
| **NEW — UI wire-in** | §5: Phase 2 replaces the Option Trading ranking's `down_beta_core` sort with the Tool C score (read from `tool_c_latest.parquet`), with a graceful fallback to down-beta when Tool C output is absent. |

---

## 0. The simplest thing that could work
> **Two new CLI ranking pipelines that mirror Tool A/B exactly. Tool C reads `tool_a_latest.parquet` + weekly-resampled foundation equities + gold history + persisted GDX/GDXJ, and computes the downside signals Tool A doesn't already publish (relative weakness in gold-down weeks, downside hit-rate, and a *flagged* tail-loss). Tool D reads `tool_b_latest.parquet` + the manual store + spot gold, and computes margin-under-stress + leverage-under-stress. Output is parquet + percentile ranks + plain-English risk tags (NOT z-scores). Then Phase 2 wires Tool C's score into the Option Trading tab's ranking. Honest confidence flags throughout; thin metrics never drive the rank.**

---

## 1. Current state (verified 2026-06-03)
**Consumed, NOT re-derived:**
- **Tool A** `data/output/tool_a/tool_a_latest.parquet` — `down_beta_core/up_beta_core`, `asymmetry_ratio_core`, `downside_volatility_52w`, `r_squared_12m`, `weeks_12m`, `confidence_score/label`, `score_eligible/_reason`. Tool C re-exports + adds.
- **Tool B** `data/output/tool_b/tool_b_latest.parquet` — `share_price_usd`, `market_cap_musd`, `leverage`, `fcf_yield`, `sustainable_fcf_musd`, `screening_verdict`, `missing_manual_fields`. Tool D re-exports as context.
- **Manual store** `golden_vector/screening/manual_data.py` (read-only) — `aisc_usd_per_oz`, `production_oz`, `net_debt_musd`, `ebitda_ltm_musd`, etc.

**Now available (was the v1 blocker):**
- **Benchmarks:** `paths.benchmarks_dir` latest + run-local `snapshots/benchmarks/*.parquet`, recorded in the options manifest `benchmark_snapshot_paths`. ✓
- **Daily normalized equities:** `load_latest_foundation_snapshot` → `normalized_equities_snapshot_path`. Tool C resamples to weekly. ✓
- **Gold history:** foundation raw gold snapshot (weekly returns derived). ✓
- **Config registry:** `app/config.py::EXPECTED_CONFIG_FILES`. ✓
- **Wire-in target:** Option Trading ranks by `down_beta_core` in `hedge/option_trading.py` (sort `:142-143`, row `:174`) and `hedge/sensitivity_ranking.py` (`sort_by` `:52-58`). ✓

---

## 2. Architecture

### 2a. Decisions locked
| Decision | Choice |
|---|---|
| Scope | Tool C + Tool D this milestone; Tool C also wired into the tab (Phase 2). |
| Separate pipelines | Yes — parallel to Tool A/B; each reads its predecessor's `latest.parquet`. |
| Scoring | **Percentile ranks + risk tags**, not z-scores (Codex critique). |
| Confidence | Per-metric event counts; thin metrics flagged + excluded from the rank (§2f). |
| Weekly returns | Resample daily foundation equities in `features/weekly_returns.py` (no phantom artifact). |
| Tool D eligibility | Component-wise: margin ranks on AISC+production+spot; leverage suppressed when debt/positive-EBITDA missing; Tool B verdict is context only. |
| Provenance | Explicit source-path recording into the replay manifest (Finding 1). |
| Config hook | Register both yamls in `EXPECTED_CONFIG_FILES` (Finding 3). |
| User-facing names | "Downside Risk Ranking" (C), "Fragility Ranking" (D). |

### 2b. Module layout
```
golden_vector/
  features/
    weekly_returns.py       # NEW — resample daily normalized equities + gold to weekly aligned returns
    gold_regime.py          # NEW — worst-N% gold-week classification (rolling)
    relative_weakness.py    # NEW — stock vs gold/GDX during gold-down weeks
    margin_stress.py        # NEW — pure math: production × (gold − AISC) scenarios
    percentile_ranks.py     # NEW — cross-sectional percentile + risk tags
  model/
    tool_c.py               # NEW — orchestrate inputs → features → schema rows → persist
    tool_d.py               # NEW — same shape
  ingestion/
    persist_tool_c.py       # NEW — parquet + latest pointer + artifacts (mirror persist_tool_a)
    persist_tool_d.py       # NEW
  app/
    paths.py                # EDIT — tool_c/d output dirs + latest parquet paths
    config.py               # EDIT — register tool_c.yaml / tool_d.yaml
    replay_manifest.py      # EDIT — update_manifest_with_tool_c / _tool_d (source recording)
  contracts/config_models.py# EDIT — ToolCConfig + ToolDConfig
  cli.py                    # EDIT — tool-c / tool-d subcommands + dispatch
  hedge/
    sensitivity_ranking.py  # EDIT (Phase 2) — accept Tool C score as a sort key
    option_trading.py       # EDIT (Phase 2) — overview rank by Tool C score, fallback to down-beta
  serve/option_trading_data.py # EDIT (Phase 2) — load tool_c_latest if present
config/ tool_c.yaml, tool_d.yaml   # NEW
tests/  test_weekly_returns, test_gold_regime, test_relative_weakness, test_margin_stress,
        test_percentile_ranks, test_tool_c, test_tool_d, test_persist_tool_c, test_persist_tool_d,
        test_cli_tool_c, test_cli_tool_d, test_option_trading_tool_c_wire  # NEW
        fixtures/tool_c_inputs/, fixtures/tool_d_inputs/
```

### 2c. Tool C schema (`data/output/tool_c/tool_c_latest.parquet`)
Identity: `ticker, as_of_date, run_id, source_tool_a_run_id`. Inherited from Tool A (re-exported, not recomputed): `score_eligible, score_eligibility_reason, weeks_12m, down_beta_core, up_beta_core, asymmetry_ratio_core, downside_volatility_52w, r_squared_12m, confidence_score, confidence_label`.

**New (robust — drive the rank):**
- `rel_weakness_vs_gold_pct` + `rel_weakness_vs_gold_event_count` — % of gold-down weeks (worst 20%) the stock underperformed gold.
- `rel_weakness_vs_gdx_pct` + `rel_weakness_vs_gdx_event_count` — same vs GDX over the **intersection** date range (null + tag if intersection < min_events).
- `downside_hit_rate_10pct` + `downside_hit_rate_event_count` — % of gold-down weeks the stock fell ≥10%.

**New (thin — shown, flagged, NOT in the rank):**
- `tail_avg_return_worst10pct`, `tail_avg_return_worst20pct`, each with its own `*_event_count` and a per-metric `*_confidence_flag` (`high`/`medium`/`low`/`insufficient`). Null when events < `min_events`.

**Rank + explain:** `tool_c_percentile_rank` (0–100, eligible subset only; NaN for ineligible), `tool_c_risk_tags`, `tool_c_explanation`, `missing_inputs`.

### 2d. Tool D schema (`data/output/tool_d/tool_d_latest.parquet`)
Identity + `source_tool_b_run_id`. Inherited from Tool B (context): `share_price_usd, market_cap_musd, screening_verdict, confidence, leverage, fcf_yield, sustainable_fcf_musd, missing_manual_fields`.

**New (margin block — ranks whenever AISC+production+spot exist):** `aisc_usd_per_oz, production_oz, spot_gold_usd_per_oz, aisc_to_spot_ratio, aisc_universe_percentile, estimated_margin_per_oz_{current,minus10,minus20}, estimated_annual_ebitda_{current,minus10,minus20}_musd, headroom_to_breakeven_pct, breaks_even_at_gold_usd`.

**New (EBITDA %-change — null+tag when current EBITDA ≤ 0):** `ebitda_pct_change_minus10`, `ebitda_pct_change_minus20`.

**New (leverage block — suppressed when debt missing or stress EBITDA ≤ 0):** `net_debt_musd, net_debt_to_ebitda_{current,minus10,minus20}` (null when undefined).

**Rank + explain:** `tool_d_percentile_rank`, `tool_d_risk_tags`, `tool_d_explanation`, `missing_inputs`.

### 2e. Risk tags
**Tool C:** `steep_down_beta`, `persistent_relative_weakness` (rel_weakness_vs_gold_pct > threshold), `frequent_deep_drops` (downside_hit_rate_10pct high), `high_tail_loss` (flagged, informational — does not add rank weight), `thin_history`, `low_confidence`, `score_ineligible`.

**Tool D:** `thin_margin` (headroom_to_breakeven_pct < 15%), `breakeven_within_15pct`, `high_leverage_after_stress` (net_debt_to_ebitda_minus10 > threshold, only when defined), `leverage_undefined_under_stress` (stress EBITDA ≤ 0), `missing_aisc` / `missing_production` / `missing_debt`, `screen_out_context` (informational; never disqualifies).

**Rank:** percentile of the equal-weighted average of the **robust** component percentiles only (config weights, default equal). Ineligible names → NaN rank but still appear with tags + `missing_inputs`.

### 2f. Confidence / thin-data policy (Emanuel's directive — honest about weak data)
- Every event-based metric carries its **own** post-intersection event count.
- A per-metric flag: `insufficient` (< min_events → value null), `low` (< low_band), `medium`, `high`.
- The **headline rank uses only robust metrics** (relative weakness, hit rate, down-beta, downside vol). The thin **tail-loss** metrics are computed and displayed **with their flags** but contribute **zero** rank weight.
- If a ticker's robust metrics are themselves thin (short history), it gets `thin_history` + `low_confidence` tags and is **excluded from the percentile rank** (NaN), not placed artificially low.
- `tool_c_explanation` states in plain English when a number is low-confidence ("based on only 14 gold-down weeks — treat with caution").

---

## 3. Module summaries (key APIs)
- `features/weekly_returns.py` — `to_weekly_returns(daily: pd.DataFrame, *, price_col, date_col) -> pd.DataFrame` (W-FRI resample, close-to-close). Aligns ticker + gold + benchmark on common weeks.
- `features/gold_regime.py` — `identify_gold_down_regimes(*, gold_weekly, severities=(0.10,0.20), rolling_window_weeks=156) -> pd.DataFrame` (boolean masks per week).
- `features/relative_weakness.py` — `compute_relative_weakness(*, ticker_weekly, gold_weekly, benchmark_weekly|None, gold_down_mask) -> RelativeWeaknessResult` (per-metric pct + **per-metric event count**).
- `features/margin_stress.py` — `estimate_margin_under_stress(*, spot_gold, aisc, production, gold_scenarios=(1.0,0.9,0.8)) -> MarginStressResult` (None values + reasons when inputs missing; explicit negative-margin handling).
- `features/percentile_ranks.py` — `compute_percentile_rank(values, *, eligible_mask) -> pd.Series` (NaN for ineligible) + `assign_risk_tags(row, rules) -> list[str]`.
- `model/tool_c.py` — `compute_tool_c(*, paths, run_context, config) -> pd.DataFrame`: read Tool A latest + foundation (resample weekly) + gold + benchmarks → features → schema → persist → **record sources in replay manifest**.
- `model/tool_d.py` — `compute_tool_d(*, paths, run_context, config) -> pd.DataFrame`: read Tool B latest + manual store + spot gold → margin/leverage → schema → persist → record sources.
- `ingestion/persist_tool_c.py` / `persist_tool_d.py` — mirror `persist_tool_a`: full + latest parquet, latest pointer, artifacts.
- `app/replay_manifest.py` — `update_manifest_with_tool_c(run_dir, *, tool_a_path, foundation_snapshot_path, benchmark_paths)` and `_tool_d(..., tool_b_path, manual_store_path, foundation_snapshot_path)`.

---

## 4. The math (with v2 fixes)
- **4a Gold regime:** weekly gold return; within rolling 156w, classify week ≤ 10th/20th percentile → `gold_in_worst_{10,20}pct`.
- **4b Relative weakness (robust):** over worst-20% gold weeks, `% weeks ticker_return < gold_return`; same vs GDX over the **intersection** range; each returns its own event count.
- **4c Downside hit rate (robust):** over gold-down weeks, `% weeks ticker fell ≥ 10%`.
- **4d Tail loss (thin, flagged):** mean ticker return in worst-10%/20% gold weeks; null when events < `min_events` (config, default 8); flag `high` ≥15, `medium` ≥8, else `low/insufficient`. Not in the rank.
- **4e Margin stress:** `margin_per_oz_X = (spot × s) − aisc`; `ebitda_X = production × margin_per_oz_X / 1e6`. **If `ebitda_current ≤ 0` → `ebitda_pct_change_*` = null + tag.** `headroom_to_breakeven_pct = (spot − aisc)/spot × 100`.
- **4f Leverage stress:** `net_debt_to_ebitda_X = net_debt / ebitda_X` **only when `ebitda_X > 0` and net_debt present**; else null + `leverage_undefined_under_stress`.
- **4g Rank:** percentile within eligible subset of the equal-weighted average of robust component percentiles; tags from config; ineligible → NaN.

---

## 5. Phase 2 — wire Tool C into the Option Trading tab
Goal: the tab ranks by downside *risk* (Tool C), not just one beta — with a safe fallback.
- `serve/option_trading_data.py`: load `tool_c_latest.parquet` if present; add its `tool_c_percentile_rank` + tags to the per-ticker join (keyed on ticker; provenance: include Tool C run id in the composite cache key).
- `hedge/option_trading.py`: `OptionTradingRow` gains `tool_c_percentile_rank: float | None` and `tool_c_risk_tags`. **Default overview sort becomes Tool C rank desc when available, else `down_beta_core` desc** (current behaviour preserved when Tool C output is missing).
- `hedge/sensitivity_ranking.py`: allow `sort_by="tool_c_percentile_rank"` in addition to `down_beta_core`.
- Overview table: add a "Downside Risk" column (Tool C rank) + show the top 1–2 risk tags; keep down-beta as a context column. Calls/puts behaviour unchanged.
- Honest fallback note when Tool C output is absent ("Run `python main.py tool-c` to rank by downside risk; showing down-beta").
- Tests: tab ranks by Tool C when present; falls back cleanly when absent; cache invalidates on Tool C run id.

---

## 6. Order of operations (batched; checkpoints are review milestones)
**Build sequence rule:** config → pure features → persistence → model wrappers → CLI → UI wire-in. Tests gate every step; no hard-coded universe sizes.

**Batch 1 — config + pure features (no I/O)**
1. `tool_c.yaml` + `tool_d.yaml` + `ToolCConfig`/`ToolDConfig` + register in `EXPECTED_CONFIG_FILES`. Schema tests.
2. `features/weekly_returns.py` (resample + align). Tests on fixture daily series.
3. `features/gold_regime.py`. 4. `features/relative_weakness.py` (per-metric counts). 5. `features/margin_stress.py` (missing/negative/zero-production). 6. `features/percentile_ranks.py` (ineligible exclusion, tags, ties).
→ **Checkpoint A** (deep holistic review of the feature layer).

**Batch 2 — persistence + models + CLI**
7. `persist_tool_c` + `persist_tool_d` (tmp_path). 8. `model/tool_c.py` + provenance recording. 9. `model/tool_d.py` + provenance. 10. `tool-c` + `tool-d` CLI + dispatch; fail loudly if prerequisite Tool A/B output absent.
→ **Checkpoint B** (paste sample `tool_c_latest`/`tool_d_latest` rows; tag + eligibility tallies; manual smoke against real data).

**Batch 3 — UI wire-in + docs**
11. Phase 2 wire Tool C into `option_trading_data` + `option_trading` + `sensitivity_ranking` (fallback preserved). Tests. 12. Docs: "Tool C / Tool D" + the tab's new Downside-Risk ranking + the confidence/thin-data policy.
→ **Checkpoint C** (completion report).

One commit per step + a self-review-fixes commit per batch. No `git push`.

## 7. Acceptance criteria
- `python main.py tool-c` / `tool-d` produce the §2c/§2d schemas; fail loudly without their prerequisite Tool A/B output.
- Thin tail metrics are null+flagged below `min_events` and contribute **zero** rank weight; robust metrics drive the rank.
- Per-metric event counts are post-intersection (GDX-relative can differ from gold-relative).
- Tool D: margin block ranks whenever AISC+production+spot exist; leverage block null+tagged when debt missing or stress EBITDA ≤ 0; `ebitda_pct_change` null+tagged when current EBITDA ≤ 0; SCREEN_OUT never disqualifies.
- Percentile ranks exclude ineligible names (NaN), never bottom-rank them.
- Replay manifest records every consumed source path; both yamls are in `EXPECTED_CONFIG_FILES`.
- Phase 2: the Option Trading tab ranks by Tool C when present and **falls back to down-beta when absent**, with a visible note.
- Full suite green; no live external calls; no hard-coded universe size.

## 8. Out of scope
- Tool D in the UI (this milestone wires only **Tool C** into the tab; Tool D stays CLI for now).
- Combined `/` overview evolution to show A+B+C+D together.
- z-score composites; backtest framework; predictive scoring; new data fetchers; ADR mapping.

## 9. Risks for the reviewer to pry at
1. Weekly resampling convention (W-FRI close-to-close) vs how Tool A computed its weekly betas — confirm consistency so Tool C's relative-weakness aligns with Tool A's beta windows.
2. GDX history shorter than ticker history → intersection-based event counts; confirm the skip-with-tag threshold.
3. Spot-gold source for Tool D (latest foundation gold snapshot) — confirm the exact field/units (USD/oz).
4. Manual-store coverage: how many of the 60 have AISC+production? (Affects how much of Tool D's margin block is populated.)
5. Phase 2 cache key must include the Tool C run id, or the tab can show a stale ranking after a fresh `tool-c`.
6. Eligibility independence: a name Tool-A-ineligible but with good Tool D inputs should still get a Tool D rank.

## 10. Implementation guidance (build rhythm)
After Codex review + green-light, **build continuously to completion** (no stop-and-wait): **deep self-review after every step** (read your own staged diff hunk-by-hunk; `pytest -q` green; acceptance for that step; known failure modes); **deeper holistic review at each checkpoint** (architecture, data correctness, thin-data honesty, provenance, no regressions) written into `reviews/codex/codex_tool_c_d_progress.md`. **Stop only on a genuine blocker** (a plan instruction that's wrong/impossible, or a failure you can't resolve in ~15 min) — write it up and halt. One commit per step + one self-review-fixes commit per batch; no `git push`; no live data in tests.

## 11. Completion report (Checkpoint C)
File changes + line counts; deviations (file:line); sample `tool_c_latest`/`tool_d_latest` rows; risk-tag distribution across the universe; eligibility tally (C, D, both, neither); test deltas; edge cases → covering tests; each §9 risk → decision + location; the Phase-2 fallback demonstrated (tab with and without Tool C output); open questions.

## 12. Open decisions to confirm (before Batch 2)
- **OD-1:** rolling window for the gold-regime percentile — 156w (3y) as planned, or longer for stabler tails? *(Recommend 156w; thin-tail flagged anyway.)*
- **OD-2:** Tool C rank weights — equal across robust components, or weight relative-weakness highest? *(Recommend equal for v1.)*
- **OD-3:** does the tab's new headline sort default to Tool C rank automatically when present, or stay on down-beta with Tool C as an opt-in sort? *(Recommend auto-default to Tool C with down-beta fallback.)*
