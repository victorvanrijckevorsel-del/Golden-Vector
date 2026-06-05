# Build Brief — Tool C + Tool D (M3), both symmetric

**For:** Codex (implementation agent)
**Author:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Date:** 2026-06-04
**Source plan:** `reviews/codex/claude_tool_c_d_plan_v4.md` (READ IT for the full architecture, math, schema, and batch order — this brief does NOT repeat all of it).
**Status:** APPROVED TO BUILD. Codex reviewed v4 (`codex_review_tool_c_d_plan_v4.md`, "READY WITH MINOR CHANGES"); all six findings are resolved and locked below. Build to the v4 plan **as amended by the "Locked resolutions" section here** — where this brief and the plan differ, this brief wins.

---

## How to work (the rhythm)
- Build in the **three batches** from v4 §4: **Batch 1 Tool C → Checkpoint A**, **Batch 2 Tool D → Checkpoint B**, **Batch 3 Finder wiring + docs → Checkpoint C**.
- Continuous build; **deep self-review after every step, deeper at each checkpoint**; log progress to `reviews/codex/codex_tool_c_d_progress.md`.
- **One commit per step**, plus one self-review-fixes commit per batch. **No `git push`** (Emanuel pushes).
- Tests gate every step. No live data in tests. No hard-coded universe size.
- **Stop and report at Checkpoints A / B / C**, and on any genuine blocker.

---

## Locked resolutions (Codex's 6 findings — build to these exactly)

### L1 — Candidate Finder consumes **spot Tool D only** in v1 (resolves Codex P1 #1)
The Finder's criteria are static `source_field` entries from static config — there is no mechanism in v1 for "low-G" vs "high-G" parameterized ranks.
- **Lock:** the Candidate Finder reads **the latest Tool D rank computed at spot gold, full stop.** It does NOT recompute Tool D at a per-lens gold price.
- Tool D persists **one** `tool_d_quality_rank` per run (at the run's gold price). The Finder consumes the **spot run's** rank as a plain `source_field` criterion, exactly like a Tool A/B field.
- The bearish (put) lens and bullish (call) lens may both reference `tool_d_quality_rank`, but it is the **same spot-gold rank** for both — do NOT invent low-G/high-G Finder variants.
- **The per-lens gold dial inside the Finder is explicit FUTURE work** — out of scope for M3. Note it as a future enhancement in the docs (Batch 3) and in `reviews/codex/codex_tool_c_d_progress.md`.
- Rationale: never let the Finder rank on a gold assumption the user can't see or change.

### L2 — Pin the exact Tool B reuse path for Tool D (resolves Codex P1 #2)
This is the one that prevents wrong leverage and false "incomplete" rows.
- **Use the in-memory Tool B seam:** call `compute_tool_b_in_memory(..., gold_price_assumption=G)` — do **not** call `compute_layer2_metrics` directly (calling layer2 without first injecting layer1 output marks rows incomplete via missing `sustainable_fcf_musd`).
- Tool D calls the Tool B seam **twice per run: once at the chosen gold price `G`, once at spot** — `G` gives the stressed block, spot gives the `ebitda_pct_change_vs_spot` reference (v4 OD-B = vs current spot).
- **Stressed leverage must be computed by Tool D itself** as `net_debt / forward_EBITDA(G)`. It must **never** read Tool B's published `leverage` column (that is trailing `net_debt / ebitda_ltm` — NOT gold-sensitive).
- **Required contract test:** assert Tool D's `leverage_stressed_at_G` is derived from forward EBITDA(G) and is **not equal to / not sourced from** Tool B's trailing `leverage` column (e.g., pick a name where trailing and forward EBITDA differ, assert the stressed leverage tracks forward EBITDA when `G` changes and the trailing column does not).
- If `compute_tool_b_in_memory` is somehow not cleanly callable standalone at arbitrary `G`, that is **Batch 2 Step 0** — do the thin extraction first, then proceed. (Codex confirmed the seam exists at `golden_vector/screening/pipeline.py:177` and a gold-override test already proves revenue/EPS/P-E move — so this should be a green light, not an extraction.)

### L3 — `weekly_returns.py` has an explicit output contract (resolves Codex P2 #3)
Define the adapter's output precisely so the GDX/GDXJ side can't drift from Tool A's weekly convention:
- **One row per (ticker, week)**, keyed by the **same `week_period`** that `build_structural_weekly_series` produces (last-trading-day-per-`W-FRI`, incomplete current week dropped).
- Columns: `ticker`, `week_period`, `stock_log_ret`, `gold_log_ret`, `gdx_log_ret`, `gdxj_log_ret` — all aligned on that one `week_period`.
- **Separate intersection event counts** per benchmark: `n_weeks_gold`, `n_weeks_gdx`, `n_weeks_gdxj` (a stock may have more overlap with gold than with GDX, whose history is shorter).
- Each downstream metric uses **its own** benchmark's intersection range and carries its own count; **skip-with-tag** (null + `thin_history`) when a metric's events `< min_events`.
- Reuse `build_structural_weekly_series` for the stock/gold side — do not re-resample.

### L4 — Lock Tool D's quality-rank components (resolves Codex P2 #4)
No "optional" components — optional members change the denominator/eligibility/comparability between runs.
- **`tool_d_quality_rank` = `oriented_percentile` of the equal-weighted blend of exactly these THREE components**, computed at `G`:
  1. `headroom_to_breakeven_pct(G)` — **high good** (margin cushion).
  2. `leverage_stressed(G)` = net_debt / forward_EBITDA(G) — **low good**.
  3. `ev_ebitda(G)` = (market_cap + net_debt) / forward_EBITDA(G) — **low good**.
- **FCF yield is NOT in the rank.** Show it as a **context column only** (re-exported from Tool B at spot, labeled as context). This removes the ambiguity Codex flagged. (If a future version adds it to the rank, it must be the **G-recomputed** layer1 FCF yield, not the spot field — but that is out of scope for M3.)
- Pin all three **directions** in `tool_d.yaml` (high/low good) so the orientation is config, not code.
- **Missing-input behavior (per component, deterministic):** if a component is null for a name (e.g. `leverage_undefined_at_G` because EBITDA(G) ≤ 0, or `missing_aisc`), that component drops out and the rank is computed on the **remaining present components, renormalized** — the same missing-data discipline the Candidate Finder uses. A name with **zero** rankable components → `tool_d_quality_rank = NaN`, flagged, sunk (not bottom-ranked). Record `missing_inputs` per row.

### L5 — Tool C hit-rate thresholds are config, not constants (resolves Codex P3 #5)
- Put the hit-rate thresholds in `tool_c.yaml`: `downside_hit_rate_threshold_pct` (default `-10`) and `upside_hit_rate_threshold_pct` (default `+10`). Also keep `min_events` there.
- **Every hit-rate (and every relative-behavior metric) must output its event count** in the parquet (e.g. `downside_hit_rate_10pct` paired with `downside_hit_rate_n`). After 156-week rolling regimes intersected with GDX history, calm names can have very few events — the count keeps the metric honest and lets the threshold be tuned later without code edits.
- A metric whose events `< min_events` → null + `thin_history` tag, **excluded from the rank** (same as the tails).

### L6 — Tool D stores the spot-gold **date**, not just the price (resolves Codex P3 #6)
- Add `spot_gold_date` (a.k.a. `spot_gold_as_of_date`) to the Tool D output schema **and** to its provenance snapshot, alongside the existing `spot_gold_usd` and `gold_price_used`.
- Rationale: the manual store, the Tool B market snapshot, and the gold close may not share a date; recording the spot-gold date makes the `ebitda_pct_change_vs_spot` reference auditable and replayable.

---

## What is unchanged from v4 (do not re-litigate)
Everything else in `claude_tool_c_d_plan_v4.md` stands as written, in particular:
- **Tool C symmetric** — `tool_c_downside_rank` (put targets) + `tool_c_upside_rank` (call targets) + `asymmetry_ratio_core` context + per-side tags & explanation (v4 §2c, §3).
- **Tool D symmetric** — single tunable gold price `G`; reuse Tool B engine; gold-sensitive leverage; EBITDA / leverage / EV-EBITDA / margins recompute at `G`; symmetric quality scorecard (v4 §2d).
- **Reuse the single `oriented_percentile`** in `features/percentile_ranks.py` — do NOT add a second percentile implementation (v4 §2f).
- **Reuse `build_structural_weekly_series`** for the weekly convention (v4 §1, §2b).
- **Provenance:** snapshot + hash all consumed assets; `verify_manifest` validates; both new yamls registered in `app/config.py::EXPECTED_CONFIG_FILES` (v4 §2e, §2g).
- **Tails are flagged and excluded from the ranks**; descriptive-not-predictive language; "simplified gold-economics model" label on Tool D (v4 §2c, §2d).
- **CLI:** `tool-c`; `tool-d --gold-price <G>` (default = current spot); extend `refresh`/`status` (v4 §2b, §4).
- **Module layout, batch order, acceptance criteria, out-of-scope** — all as in v4 §2b, §4, §5, §6.

---

## Acceptance criteria (v4 §5, plus the six locks)
All of v4 §5, AND:
- **L1:** Candidate Finder references the spot Tool D rank as a static `source_field`; no per-lens gold recompute exists; future-dial noted in docs.
- **L2:** Tool D uses `compute_tool_b_in_memory` at `G` and at spot; a contract test proves stressed leverage tracks forward EBITDA(G) and never sources Tool B's trailing `leverage` column.
- **L3:** `weekly_returns` emits one row per (ticker, week) on a single `week_period` with gold/GDX/GDXJ returns + per-benchmark event counts; thin metrics skip-with-tag.
- **L4:** `tool_d_quality_rank` blends exactly the three locked components (equal-weight, config-directioned) with renormalized missing-data handling; FCF yield is context-only; zero-component names → NaN/sunk.
- **L5:** hit-rate thresholds + `min_events` are in `tool_c.yaml`; every hit-rate and relative metric outputs its event count; thin metrics excluded from ranks.
- **L6:** Tool D output and provenance include `spot_gold_date`.
- Full suite green; no live data in tests; no hard-coded universe size.

---

## Checkpoints (stop & report)
- **Checkpoint A (end of Batch 1, Tool C):** sample rows showing both ranks; an asymmetry example (high-downside/low-upside = put target, and the reverse); event counts visible; thin tails flagged & excluded.
- **Checkpoint B (end of Batch 2, Tool D):** a scorecard at **two different gold prices** showing EBITDA, leverage_stressed, and EV/EBITDA visibly moving; a `leverage_undefined_at_G` example (EBITDA ≤ 0 → null, never inf); the equal-weight three-component rank; `spot_gold_date` present.
- **Checkpoint C (end of Batch 3):** Finder resolves all three new criteria (contract test green); docs cover Tool C/D, the gold dial, the spot-only-in-Finder decision, and the descriptive/thin-data caveats.
