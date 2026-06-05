# Codex Review - Tool C/D Plan v4

Grade: READY WITH MINOR CHANGES

The architecture is sound enough to build. The current codebase already has the required seams: Tool B can recompute at an arbitrary gold price through `compute_tool_b_in_memory`, Tool A's weekly convention is reusable through `build_structural_weekly_series`, `oriented_percentile` exists, and GDX/GDXJ benchmark histories are configured and persisted. The findings below are plan-tightening items, not reasons to redesign the milestone.

## Findings

### P1 - Candidate Finder's Tool D gold-price semantics are internally inconsistent

The plan says the bearish lens uses downside plus low-G quality and the bullish lens uses upside plus high-G quality, then immediately says v1 should use Tool D at spot and defer the Finder gold dial (`reviews/codex/claude_tool_c_d_plan_v4.md:111`, `reviews/codex/claude_tool_c_d_plan_v4.md:140`, `reviews/codex/claude_tool_c_d_plan_v4.md:154`). Current Candidate Finder criteria are static `source_field` entries (`golden_vector/contracts/config_models.py:712`, `golden_vector/contracts/config_models.py:715`) loaded from static config (`config/candidate_finder.yaml:4`), so there is no natural place today for "low-G" or "high-G" ranks unless Tool D persists separate parameterized outputs. Lock the build brief to one v1 behavior: Candidate Finder consumes the latest spot Tool D rank only, while low/high-G Finder ranking remains explicitly future work. Otherwise the UI can silently rank on a gold assumption the user cannot see or change.

### P1 - Tool D must pin the exact Tool B reuse path to avoid false incompletes and wrong leverage

The key prerequisite is present: `compute_tool_b_in_memory` accepts `gold_price_assumption` (`golden_vector/screening/pipeline.py:177`), chains `evaluate_layer1` into `compute_layer2_metrics` (`golden_vector/screening/pipeline.py:291`, `golden_vector/screening/pipeline.py:296`), and the override test proves revenue/EPS/P-E move when gold changes (`tests/test_screening_overrides.py:250`). The plan correctly says stressed leverage is `net_debt / forward_EBITDA(G)` and not trailing EBITDA (`reviews/codex/claude_tool_c_d_plan_v4.md:93`). The implementation brief should make that impossible to misread because the existing Tool B `leverage` field comes from trailing `ebitda_ltm_musd` (`golden_vector/screening/layer1.py:75`, `golden_vector/screening/layer1.py:79`, `golden_vector/screening/pipeline.py:337`), and a direct call to `compute_layer2_metrics` without first injecting layer1 output will mark rows incomplete due to missing `sustainable_fcf_musd` (`golden_vector/screening/layer2.py:24`, `golden_vector/screening/layer2.py:37`, `golden_vector/screening/layer2.py:45`). Specify that Tool D either calls `compute_tool_b_in_memory` twice, at G and spot, or exactly reproduces the pipeline's layer1-then-layer2 row merge. Add a contract test that stressed leverage never uses the existing Tool B `leverage` column.

### P2 - Tool C's benchmark weekly adapter needs an explicit output contract

Reusing Tool A's weekly convention is the right decision: `build_structural_weekly_series` does last-trading-day-per-W-FRI weeks, drops incomplete current weeks, and computes stock/gold weekly log returns (`golden_vector/model/structural.py:99`, `golden_vector/model/structural.py:174`, `golden_vector/model/structural.py:190`, `golden_vector/model/structural.py:207`). GDX/GDXJ are feasible because benchmark histories are configured (`config/benchmarks.yaml:2`) and persisted through the benchmark fetch path (`golden_vector/ingestion/options_phase.py:350`, `golden_vector/ingestion/options_phase.py:367`, `tests/test_options_phase.py:50`). The plan's `weekly_returns.py` adapter should still define a concrete contract: one row per ticker/week with ticker, gold, GDX, and GDXJ returns aligned by the same `week_period`; separate intersection counts for each benchmark; and skip-with-tag below `min_events`. Without that, relative weakness/strength vs GDX can drift from Tool A's weekly convention even while the stock/gold part is correct.

### P2 - Tool D's quality-rank components are not fully locked

The plan locks equal weighting in config (`reviews/codex/claude_tool_c_d_plan_v4.md:22`, `reviews/codex/claude_tool_c_d_plan_v4.md:49`) but the schema still says the rank uses margin/headroom, stressed leverage, EV/EBITDA(G), and "optionally FCF yield" (`reviews/codex/claude_tool_c_d_plan_v4.md:97`). Optional components change the denominator, eligibility, and rank comparability between runs. Before coding, the build brief should pin the default `tool_d.yaml` component list, direction for each component, and missing-input behavior. If FCF yield is included, it should be clearly marked as the G-price recomputed layer1 FCF yield, not the spot Tool B field re-exported as context.

### P3 - Tool C hit-rate thresholds should be config, not constants

The symmetric metric set is directionally sound: downside rank for put candidates, upside rank for call candidates, tails surfaced but excluded from rank (`reviews/codex/claude_tool_c_d_plan_v4.md:80`, `reviews/codex/claude_tool_c_d_plan_v4.md:84`). The fixed +/-10% weekly hit rates (`reviews/codex/claude_tool_c_d_plan_v4.md:118`) may be sparse after 156-week rolling regimes and GDX intersections, especially for lower-volatility names. Put the hit-rate thresholds in `tool_c.yaml` and require event counts in the output. That keeps the first implementation honest and makes later tuning possible without code edits.

### P3 - Tool D should store the spot-gold date, not only the spot price

Tool D compares EBITDA(G) with EBITDA(spot) and copies raw gold into replay snapshots (`reviews/codex/claude_tool_c_d_plan_v4.md:88`, `reviews/codex/claude_tool_c_d_plan_v4.md:95`, `reviews/codex/claude_tool_c_d_plan_v4.md:102`), but the schema only names `spot_gold_usd` (`reviews/codex/claude_tool_c_d_plan_v4.md:97`). Add `spot_gold_date` or `spot_gold_as_of_date` to the Tool D output and provenance. This matters when a manual store, market snapshot, and gold close are not all from the same date.

## Checks Against The Requested Risks

- Tool B arbitrary gold-price reuse: yes, available through the in-memory Tool B seam and already covered by a gold-price override test.
- Symmetric Tool C metric set: sound, with event counts and config-driven thresholds needed to prevent sparse metrics from looking stronger than they are.
- `oriented_percentile` reuse: yes, the helper exists and has the correct high-good/low-good orientation contract (`golden_vector/features/percentile_ranks.py:8`, `golden_vector/features/percentile_ranks.py:17`).
- `build_structural_weekly_series` reuse: yes for stock/gold convention parity; the benchmark side needs a precise adapter contract.
- Scope: still implementable as one milestone if the three batches remain checkpointed. I would not split M3 unless Tool D-in-Finder gold dial is pulled into v1, which would make persistence and UI semantics larger than the current plan.

## Additional Notes

No source-code implementation changes are recommended before the plan is tightened. The main build-brief change is to remove ambiguity, not to add more features.
