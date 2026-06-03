# Plan: M3 — Tool C + Tool D + wire Tool C into the Option Trading tab (v3)

**Author:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Date:** 2026-06-03
**Status:** for Codex re-review (v2 graded NEEDS CHANGES — `codex_review_claude_tool_c_d_plan_v2.md`)
**Supersedes:** `claude_tool_c_d_plan_v2.md`. Scope decisions unchanged (Tool C + Tool D; CLI-first then wire Tool C into the tab; honest thin-data handling). v3 fixes **data-consistency, provenance, and rank-definition** gaps.

## v3 changelog — every Codex v2 finding resolved
| Codex v2 finding | Resolution |
|---|---|
| **1 (P1) Tool D gold-price baseline mixes Tool B's assumption gold with a fresh spot** | §2g: Tool D stress runs from **current spot** (the honest "from today" downside), but the row **surfaces both** `spot_gold_usd_per_oz` *and* `tool_b_gold_price_assumption` + `gold_baseline_source`/`_date`, and **labels Tool B context columns** as computed under the assumption gold. The headline fragility metrics (`breaks_even_at_gold_usd` = AISC, `headroom_to_breakeven_pct`) are **baseline-independent**. No hidden mixing. |
| **2 (P1) UI wire-in needs a freshness gate, not just a cache key** | §5: Tool C is the tab's default sort **only if `tool_c.source_tool_a_run_id == current Tool A run id`**; otherwise fall back to down-beta with a visible "Tool C ranking is stale" note. The composite cache key also gains the Tool C run id. Tested both ways. |
| **3 (P1) Tool D can pair new manual data with an older Tool B snapshot** | §2h: Tool D's **own** margin+leverage block is computed entirely from **one live manual-store snapshot** (internally consistent). It records that snapshot's hash and **compares it to the hash Tool B used**; on mismatch it tags `tool_b_context_stale` and surfaces both as-of dates, so the re-exported Tool B context is never silently mixed. |
| **4 (P1) Rank formulas underspecified (esp. Tool D direction)** | §2f: explicit **component tables per tool** with raw metric, risk direction (which end is risky / which to invert), and a **missing-value renormalization rule** + minimum-components gate. No generic percentile can rank the wrong end. |
| **5 (P2) Provenance must be hash/snapshot-level, not path-level** | §3: Tool C/D **snapshot + hash** their consumed assets into the run's `replay_snapshots/` area (reusing the existing `_snapshot_config`/`_snapshot_manual_database` machinery) and `verify_manifest` validates them — not just record mutable `latest.parquet` paths. |
| **6 (P2) Weekly-return convention + columns + early-window** | §2c/§3: **reuse `model/structural.build_structural_weekly_series`** — the same weekly **log-return** series Tool A's betas are built on — instead of inventing a convention. Pins columns and the < min-history behavior. Guarantees Tool C is consistent with Tool A (Codex risk #1). |
| **7 (P2) refresh/status don't cover Tool C/D** | §6: extend `python main.py refresh` to run `tool-c`/`tool-d` after Tool B (config-gated, default on) and `status` to report their presence + whether their source run matches current Tool A/B. The staleness gate (finding 2) is the safety net. |
| **Note — OD-1/2/3 are load-bearing** | All three **resolved** in §2a (no open decisions left into Batch 2). |

---

## 1. Current state (re-verified 2026-06-03)
- **Tool A** `tool_a_latest.parquet` — betas, vols, confidence, `score_eligible`. Re-exported, not recomputed.
- **Tool A's weekly engine** `model/structural.build_structural_weekly_series` produces `stock_weekly_log_return` + `gold_weekly_log_return` (`structural.py:99,207-215`). **Tool C reuses this** so its gold-regime + relative-weakness sit on the same series as the betas.
- **Tool B** `tool_b_latest.parquet` — context (`leverage`, `fcf_yield`, `screening_verdict`, `gold_price_assumption`, `missing_manual_fields`). **Does NOT persist AISC/production/net_debt** → Tool D must read those from the manual store.
- **Manual store** `screening/manual_data.py` (read-only) — AISC, production, net_debt, ebitda_ltm. Already hashed into replay provenance (`replay_manifest._snapshot_manual_database`).
- **Benchmarks** persisted (`paths.benchmarks_dir` + run-local) — GDX/GDXJ weekly available.
- **Spot gold** latest foundation raw-gold snapshot.
- **Replay** is snapshot+hash level (`replay_manifest.py:24,66-74`, `verify_manifest`). Tool C/D mirror this.
- **Wire-in target** Option Trading ranks by `down_beta_core` (`option_trading.py:142-143,174`; `sensitivity_ranking.py:52-58`); the loader already keys on options + Tool A/B refresh ids (`option_trading_data.py:189,293`).

---

## 2. Architecture

### 2a. Decisions locked (incl. resolved ODs)
| Decision | Choice |
|---|---|
| Scope | Tool C + Tool D; Tool C wired into the tab (Phase 2). |
| Weekly convention | **Reuse Tool A's `build_structural_weekly_series`** (weekly log returns). No new convention. |
| Scoring | Percentile + risk tags; explicit per-component direction (§2f); robust signals drive the rank, thin tail metrics flagged-only. |
| Tool D gold baseline (**OD resolved**) | Stress from **current spot**; surface spot **and** Tool B's `gold_price_assumption`; breakeven metrics are baseline-independent. |
| Tool D eligibility | Component-wise: margin ranks when AISC+production+spot exist; leverage suppressed (null+tag) when debt missing or stress EBITDA ≤ 0; Tool B verdict = context only. |
| Provenance | Snapshot + hash consumed assets; `verify_manifest` validates. |
| **OD-1** rolling regime window | **156w (3y)**, with a 52-week warm-up minimum (weeks before that excluded from event counts, not treated as non-down). |
| **OD-2** rank weights | **Equal** across present robust components, renormalized for missing (§2f). |
| **OD-3** tab default sort | **Auto-default to Tool C rank when fresh** (source Tool A matches), else down-beta fallback + note. |
| refresh/status | `refresh` runs tool-c/tool-d after Tool B (config-gated, default on); `status` reports them + staleness. |

### 2b. Module layout
As v2 §2b, with: `features/weekly_returns.py` becomes a **thin adapter** over `model/structural.build_structural_weekly_series` (per-ticker) plus gold/benchmark weekly log-return series — it does **not** invent a resample. `app/replay_manifest.py` gains `update_manifest_with_tool_c/_tool_d` that **copy+hash** sources. `cli.py` extends `refresh`/`status`. Phase-2 edits to `serve/option_trading_data.py`, `hedge/option_trading.py`, `hedge/sensitivity_ranking.py`.

### 2c. Weekly series + gold regime (consistent with Tool A)
- Per ticker, obtain `stock_weekly_log_return` and `gold_weekly_log_return` via `build_structural_weekly_series` (same inputs Tool A uses: normalized equities `adj_close_usd`, raw gold). Benchmark (GDX/GDXJ) weekly log returns built identically from the persisted benchmark snapshots.
- **Gold regime:** on `gold_weekly_log_return`, within a rolling 156-week window (≥52-week warm-up), classify weeks ≤ 10th / 20th percentile → `gold_in_worst_{10,20}pct`. Weeks inside the warm-up are excluded from all event counts.

### 2d. Tool C schema
Identity + `source_tool_a_run_id`. Inherited from Tool A (re-export): `score_eligible/_reason, weeks_12m, down_beta_core, up_beta_core, asymmetry_ratio_core, downside_volatility_52w, r_squared_12m, confidence_score/label`.
Inherited (plain-beta context — see academic note §2j): also re-export `structural_delta_core` (the **symmetric** gold beta) so the UI can show plain beta **next to** down-beta.
**Robust (drive rank):** `rel_weakness_vs_gold_pct`(+count), `rel_weakness_vs_gdx_pct`(+count, intersection-based), `downside_hit_rate_10pct`(+count).
**Thin (shown, flagged, NOT in rank):** `tail_avg_return_worst10pct`/`worst20pct`, each with its own `*_event_count` and `*_confidence_flag` (`high/medium/low/insufficient`).
**Rank/explain:** `tool_c_percentile_rank` (eligible subset; NaN otherwise), `tool_c_risk_tags`, `tool_c_explanation`, `missing_inputs`.

### 2e. Tool D schema
Identity + `source_tool_b_run_id` + `manual_data_hash` + `tool_b_manual_data_hash` + `tool_b_context_stale` (bool). Inherited from Tool B (context, **labeled assumption-gold**): `share_price_usd, market_cap_musd, screening_verdict, confidence, leverage, fcf_yield, missing_manual_fields, gold_price_assumption`.
**Baseline:** `spot_gold_usd_per_oz, gold_baseline_source, gold_baseline_date`.
**Margin block (from manual store + spot):** `aisc_usd_per_oz, production_oz, aisc_to_spot_ratio, aisc_universe_percentile, estimated_margin_per_oz_{current,minus10,minus20}, estimated_annual_ebitda_{current,minus10,minus20}_musd, breaks_even_at_gold_usd(=aisc), headroom_to_breakeven_pct`.
**EBITDA %-change (null+tag when current EBITDA ≤ 0):** `ebitda_pct_change_{minus10,minus20}`.
**Leverage block (null+tag when debt missing or stress EBITDA ≤ 0):** `net_debt_musd, net_debt_to_ebitda_{current,minus10,minus20}`.
**Rank/explain:** `tool_d_percentile_rank, tool_d_risk_tags, tool_d_explanation, missing_inputs`.

### 2f. Rank definitions (explicit — resolves finding 4)
For each tool: convert each present component to a 0–100 percentile within the eligible subset **after orienting it so higher = more risk**, average the present components with equal weight **renormalized over those present**, then take the percentile of that average as the published rank. A ticker needs at least the minimum number of present components or it is flagged low-confidence and gets `NaN` rank (not bottom).

**Tool C (higher = more downside risk), min 3 of 4 present:**
| Component | Orientation |
|---|---|
| `down_beta_core` | higher = riskier (direct) |
| `downside_volatility_52w` | higher = riskier (direct) |
| `rel_weakness_vs_gold_pct` | higher = riskier (direct) |
| `downside_hit_rate_10pct` | higher = riskier (direct) |
Tail-loss metrics are **excluded** from the rank (thin-data policy); `rel_weakness_vs_gdx_pct` is shown but not in the rank in v1 (GDX history shorter → thinner; revisit later).

**Tool D (higher = more fragile), min 2 components present; margin and leverage are separately gated:**
| Component | Orientation | Gate |
|---|---|---|
| `aisc_to_spot_ratio` | higher = riskier (direct) | needs AISC + spot |
| `headroom_to_breakeven_pct` | **invert** (lower = riskier) | needs AISC + spot |
| `ebitda_pct_change_minus10` | **invert** (more negative = riskier) | needs AISC + production + spot **and** current EBITDA > 0 |
| `net_debt_to_ebitda_minus10` | higher = riskier (direct) | needs net_debt **and** stress EBITDA > 0; else null + `leverage_undefined_under_stress` |
Missing components are dropped and weights renormalized over present ones; a name with only the margin block still ranks (on margin), tagged that leverage was unavailable.

### 2g. Tool D gold baseline (resolves finding 1)
- Stress scenarios use **current spot** (`gold_baseline_source="foundation_spot"`, with date). The row also carries Tool B's `gold_price_assumption` and clearly labels the Tool B context columns as computed under that assumption — both bases visible, never silently merged.
- `breaks_even_at_gold_usd = aisc_usd_per_oz` and `headroom_to_breakeven_pct = (spot − aisc)/spot` are baseline-independent and are the **headline** fragility signals.

### 2h. Tool D manual-data consistency (resolves finding 3)
- Tool D computes its entire margin+leverage block from **one** live manual-store read (internally consistent).
- It records `manual_data_hash` and compares to the `tool_b_manual_data_hash` Tool B recorded; on mismatch sets `tool_b_context_stale=True` and the explanation notes "Tool B context predates current manual edits." Tool D's own numbers are always current.

### 2i. Risk tags
Tool C: `steep_down_beta, persistent_relative_weakness, frequent_deep_drops, high_tail_loss`(informational, no rank weight)`, thin_history, low_confidence, score_ineligible`.
Tool D: `thin_margin, breakeven_within_15pct, high_leverage_after_stress, leverage_undefined_under_stress, current_margin_negative, ebitda_pct_change_undefined, missing_aisc/production/debt, screen_out_context`(informational)`, tool_b_context_stale`.

---

### 2j. Academic grounding (from `research_academic_grounding_gold_model.md`)
The downside-ranking design is backed by the literature, with two framing rules baked in:
- **Down-beta is descriptive, not predictive.** Atilgan-Demirtas-Gunaydin (2020) and Levi-Welch-Karolyi (2020) show the down-beta *return premium* is fragile and that plain beta often predicts crashes at least as well. So Tool C presents the downside rank as **"how this miner behaved when gold fell" — a risk descriptor, NOT a forecast that high-down-beta names earn more.** The `tool_c_explanation` says this in plain English, and the UI shows **`structural_delta_core` (plain beta) alongside `down_beta_core`**.
- **Thin tail metrics stay flagged + out of the rank** (Yamai-Yoshiba 2002; Pitera-Schmidt 2020; Barendse et al. 2023): small-sample tail averages are biased toward *understating* risk. (Validated; our §2f already excludes them from the rank.)
- Optional future upgrade noted: a peaks-over-threshold / GPD tail estimate instead of the worst-N-week average. Not required for v1.

### 2k. Companion change to the shipped option tool (label only)
Per the convexity/operating-leverage evidence (Shahzad et al. 2021), add an **"approximate at extremes"** caveat to the −15% / −20% rows of the option scenario tables (`hedge/scenarios.py` output as rendered in `serve/detail_panels.py` / the markdown report): the linear `beta × gold%` factor is a small-move approximation and **operating leverage may worsen real downside beyond it** — which Tool D quantifies. Low-risk label change; do it alongside Batch 3.

## 3. Provenance (resolves finding 5)
`compute_tool_c` and `compute_tool_d`, after persisting, call `update_manifest_with_tool_c/_tool_d`, which **copy the consumed assets into `run_dir/replay_snapshots/` and store their SHA hashes**, reusing the existing snapshot helpers:
- Tool C sources: `tool_a_latest.parquet`, the foundation normalized-equities + raw-gold snapshots, the benchmark snapshots.
- Tool D sources: `tool_b_latest.parquet`, the manual-store DB (already supported via `_snapshot_manual_database`), the foundation raw-gold snapshot.
`verify_manifest` is extended to validate these hashes, exactly as it does for configs/manual/foundation/options today. Recording only mutable `latest.parquet` paths is **not** sufficient and is explicitly avoided.

## 4. Math (with v3 fixes)
As v2 §4, with: (a) weekly series via the structural builder (§2c); (b) per-metric intersection event counts; (c) tail-loss flagged-only; (d) `ebitda_pct_change_*` null+`ebitda_pct_change_undefined` when current EBITDA ≤ 0; (e) leverage null+`leverage_undefined_under_stress` when stress EBITDA ≤ 0 or debt missing; (f) ranks per §2f orientation + renormalization.

## 5. Phase 2 — wire Tool C into the tab (with freshness gate, resolves finding 2)
- `serve/option_trading_data.py`: load `tool_c_latest.parquet` if present; add Tool C run id to the composite cache key. Compute `tool_c_is_fresh = (tool_c.source_tool_a_run_id == current Tool A run id)`.
- `hedge/option_trading.py`: `OptionTradingRow` gains `tool_c_percentile_rank | None` + `tool_c_risk_tags`. **Default sort = Tool C rank desc only when `tool_c_is_fresh`; else `down_beta_core` desc** with a visible note: *"Tool C ranking is stale (built against an older Tool A run) — run `python main.py tool-c`; showing down-beta."* When Tool C output is absent, same down-beta fallback with a "run tool-c" note.
- `hedge/sensitivity_ranking.py`: accept `sort_by="tool_c_percentile_rank"`.
- Overview gains a "Downside Risk" column (Tool C rank) + top risk tags; down-beta stays a context column.
- Tests: fresh Tool C → ranks by it; stale Tool C → down-beta + note; absent → down-beta + note; cache invalidates on Tool C run id.

## 6. Operational integration (resolves finding 7)
- `python main.py refresh`: after Tool B, run `tool-c` then `tool-d` (config flag `refresh.run_tool_c_d`, default true). Failures are non-fatal and reported (the tab's freshness gate keeps the UI honest regardless).
- `python main.py status`: report Tool C/D output presence, their `as_of_date`/run id, and **whether their source run matches the current Tool A/B** (so users see staleness at a glance).

## 7. Order of operations (batched; checkpoints = review milestones)
**Build sequence:** config → pure features (reusing the structural weekly builder) → persistence+provenance → model wrappers → CLI → refresh/status → UI wire-in. Tests gate every step; no hard-coded universe size.

- **Batch 1 (config + features):** 1 configs+models+register in `EXPECTED_CONFIG_FILES`; 2 `weekly_returns` adapter over `build_structural_weekly_series`; 3 `gold_regime`; 4 `relative_weakness` (per-metric counts); 5 `margin_stress` (missing/negative/zero); 6 `percentile_ranks` (oriented components, renormalization, ineligible NaN, tags). → **Checkpoint A.**
- **Batch 2 (persist + models + CLI + ops):** 7 `persist_tool_c/d`; 8 `model/tool_c` + provenance snapshot/hash; 9 `model/tool_d` + provenance + manual-staleness; 10 `tool-c`/`tool-d` CLI (fail loudly without prereq A/B); 11 extend `refresh`+`status`+`verify_manifest`. → **Checkpoint B** (sample rows; tag/eligibility tallies; manual smoke).
- **Batch 3 (UI wire-in + docs):** 12 Phase 2 with freshness gate + tests; 13 docs (Tool C/D + the tab's Downside-Risk ranking + thin-data + baseline policy). → **Checkpoint C** (completion report).

One commit per step + self-review-fixes commit per batch. No `git push`.

## 8. Acceptance criteria
- `tool-c`/`tool-d` produce §2d/§2e schemas; fail loudly without prereq Tool A/B output.
- Tool C weekly series come from `build_structural_weekly_series` (consistent with Tool A); per-metric event counts are post-intersection; tail metrics flagged-only and zero rank weight.
- Tool C/D ranks follow §2f orientation + renormalization; ineligible/under-min names get NaN rank, not bottom.
- Tool D surfaces both spot and Tool B assumption gold; breakeven metrics baseline-independent; EBITDA-%-change and leverage null+tagged when undefined; `tool_b_context_stale` set on manual-hash mismatch; SCREEN_OUT never disqualifies.
- Provenance: consumed assets snapshotted+hashed and validated by `verify_manifest`; both yamls in `EXPECTED_CONFIG_FILES`.
- Tab uses Tool C **only when its source Tool A run matches current**, else down-beta + visible note; cache keyed on Tool C run id.
- `refresh` runs C/D (config-gated); `status` reports their staleness.
- Full suite green; no live external calls; no hard-coded universe size.

## 9. Out of scope
Tool D in the UI; combined A+B+C+D overview; z-scores; backtest framework; predictive scoring; new fetchers; ADR mapping.

## 10. Risks for the reviewer
1. Confirm `build_structural_weekly_series` is callable per-ticker outside the full Tool A pipeline (inputs it needs), so reuse is clean rather than a copy.
2. Benchmark weekly series alignment when GDX history is shorter than ticker history (intersection counts; skip-with-tag below min).
3. Spot-gold field/units from the foundation raw-gold snapshot (USD/oz) for Tool D.
4. Manual-store coverage of AISC+production across the 60 (how much of Tool D's margin block populates).
5. `verify_manifest` extension must not break existing replay verification of prior runs.
6. refresh making C/D non-fatal vs the tab's freshness gate — confirm a failed `tool-c` during refresh leaves the tab on a correct down-beta fallback, not a half-written parquet.

## 11. Implementation guidance (build rhythm)
After Codex review + green-light, **build continuously to completion** (no stop-and-wait): **deep self-review after every step**; **deeper holistic review at each checkpoint** (data consistency with Tool A, thin-data honesty, provenance hashing, the UI freshness gate, no regressions) logged in `reviews/codex/codex_tool_c_d_progress.md`. **Stop only on a genuine blocker.** One commit per step + a self-review-fixes commit per batch; no `git push`; no live data in tests.

## 12. Open decisions
**None.** OD-1/2/3 resolved in §2a. The one item worth the reviewer's explicit nod: §2g's choice to anchor Tool D stress on **current spot** (with both gold bases surfaced) rather than Tool B's assumption gold.
