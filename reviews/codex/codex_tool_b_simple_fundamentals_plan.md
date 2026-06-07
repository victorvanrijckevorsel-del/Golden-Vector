# Tool B Simple Fundamentals Plan

Status: DRAFT FOR CLAUDE REVIEW

Author: Codex

Product decision: Tool B should stop emitting internal price-target scenarios. It should become a simple fundamentals and financial-resilience view built from observable market data, company inputs, and straightforward gold-price economics.

## 1. Why This Change

Emanuel's product direction is clear: Golden Vector should mainly show numbers that are easy to trust and explain. The current Tool B target-price block does the opposite. It publishes fields such as `Peer P/E Target`, `Peak P/E Target`, `Peer FCF Target`, `Peak FCF Target`, `Best Target Price`, and `Best Upside %`. These are not market data, not analyst targets, and not directly observable facts. They are internal valuation assumptions from configured size-bucket benchmarks.

The current implementation also lets that internal target math influence ranking through `best_upside_pct -> compute_tool_b_score(...)`. That means a hidden valuation assumption can change Tool B rank, Combined rank, Candidate Finder criteria, and Tool D context. This is a product-trust problem, not just a wording problem.

The new rule:

- No price-target scenarios in the main product.
- No `best upside` helper.
- No ranking score driven by target-price upside.
- Keep only simple, explainable financial metrics and explicit pass/fail checks.

## 2. Current Dependency Surface

The target-price logic currently appears in these areas:

| Area | Current dependency |
|---|---|
| Tool B pipeline | `golden_vector/screening/pipeline.py` imports `compute_target_prices`, emits target/upside fields, and feeds `best_upside_pct` into `compute_tool_b_score`. |
| Target math | `golden_vector/screening/targets.py` computes `adjusted_peer_pe`, `adjusted_peak_pe`, four target prices, four upside percentages, `best_target_price_usd`, and `best_upside_pct`. |
| Tool B score | `golden_vector/screening/verdicts.py` uses `best_upside_pct` for 30% of `tool_b_score`. |
| Tool B ranking | `golden_vector/screening/ranking.py` ranks by `tool_b_score`. |
| Tool B UI | `golden_vector/serve/overview_tool_b.py` renders the four target-price scenarios and explanatory copy. |
| Detail page | `golden_vector/serve/detail_panels.py` includes `best_upside_pct` in the Corporate Finance snapshot. |
| Candidate Finder | `config/candidate_finder.yaml` exposes `Best upside %` and the bullish-call preset uses it. |
| Tool D | `golden_vector/model/tool_d.py` re-exports `best_upside_pct` as context. |
| Combined layer | `golden_vector/combined/join.py`, `golden_vector/combined/pipeline.py`, and `golden_vector/combined/ranking.py` carry `best_upside_pct` / `tool_b_score`. |
| Contracts | `golden_vector/contracts/data_models.py` documents target/upside fields. |
| Config | `config/screening_params.yaml` contains `peer_benchmarks`, only needed for removed target math after this change. |

## 3. Keep vs Remove

### Remove From Published Outputs and UI

Remove these fields from Tool B output, Combined output, Candidate Finder, Tool D context, workspace detail pages, and tests:

| Field | Reason |
|---|---|
| `adjusted_peer_pe` | Only supports target-price math. |
| `adjusted_peak_pe` | Only supports target-price math. |
| `target_price_peer_pe` | Internal valuation scenario. |
| `target_price_peak_pe` | Internal valuation scenario. |
| `target_price_peer_fcf` | Internal valuation scenario. |
| `target_price_peak_fcf` | Internal valuation scenario. |
| `upside_peer_pe_pct` | Derived from removed target. |
| `upside_peak_pe_pct` | Derived from removed target. |
| `upside_peer_fcf_pct` | Derived from removed target. |
| `upside_peak_fcf_pct` | Derived from removed target. |
| `best_target_price_usd` | Misleading headline. |
| `best_upside_pct` | Misleading headline and hidden ranking input. |

### Keep

Keep these because they are simple and explainable:

| Field | Plain-English meaning |
|---|---|
| `share_price_usd` | Current normalized share price. |
| `market_cap_musd` | Market value of equity. |
| `shares_outstanding` if already available downstream | Share count used for per-share ratios. |
| `production_oz` | Annual gold production input. |
| `aisc_usd_per_oz` | All-in sustaining cost. |
| `cash_cost_usd_per_oz` | Cash operating cost if available. |
| `cash_margin_usd_per_oz` | Gold price minus AISC. |
| `margin_pct` | Cash margin divided by gold price. |
| `forward_revenue_musd` | Production times gold price. |
| `forward_ebitda_musd` | Simple forward EBITDA estimate. |
| `forward_net_income_musd` | Simple forward net income estimate. |
| `forward_eps` | Forward net income per share. |
| `forward_pe` | Share price divided by forward EPS. |
| `enterprise_value_musd` | Market cap plus net debt. |
| `ev_ebitda` | Enterprise value divided by forward EBITDA. |
| `sustainable_fcf_musd` | Estimated sustainable free cash flow. |
| `fcf_yield` | Sustainable FCF divided by market cap. |
| `net_debt_musd` | Net debt from manual/company data. |
| `leverage` | Net debt divided by EBITDA. |
| `reserve_life_years` | Reserve life input. |
| `jurisdiction_tier` | Simple country-risk bucket. |
| `screening_verdict` | Keep, but explain it as rule-based status, not target-price valuation. |
| `confidence` | Manual-data confidence. |

### Add or Persist

Some simple metrics are already computed but not persisted in Tool B. Persist them so UI and Candidate Finder do not recompute them in request handlers:

| Field | Source |
|---|---|
| `cash_margin_usd_per_oz` | Already computed in `evaluate_layer1`. |
| `margin_pct` | Already computed in `evaluate_layer1`. |
| `enterprise_value_musd` | Add to `compute_layer2_metrics` as `market_cap_musd + net_debt_musd`. |
| `debt_to_mktcap` | Move from Candidate Finder request-time derivation into Tool B output. |
| `ebitda_to_mktcap` | Move from Candidate Finder request-time derivation into Tool B output. |
| `revenue_to_mktcap` | Move from Candidate Finder request-time derivation into Tool B output. |
| `netincome_to_mktcap` | Move from Candidate Finder request-time derivation into Tool B output. |

## 4. Ranking and Score Decision

Current `tool_b_score` should not survive in its current form because it is 30% driven by `best_upside_pct`.

Recommended replacement:

- Introduce `fundamental_checks_passed`.
- Introduce `fundamental_checks_total`.
- Introduce `fundamental_check_score` as `100 * passed / total`.
- Rename UI label from `Corporate Finance Score` to `Fundamental Checks %`.
- Use `fundamental_check_score` only as a transparent sorting helper.

The check list should be built from explicit visible checks:

| Check | Rule |
|---|---|
| Data complete | Manual and market inputs complete enough for Tool B. |
| AISC check | AISC is at or below configured max. |
| Margin check | Margin percentage is at or above configured minimum. |
| FCF yield check | FCF yield is at or above configured minimum. |
| Reserve life check | Reserve life is at or above configured minimum. |
| Leverage check | Net debt / EBITDA is at or below configured max and EBITDA is positive. |
| Forward P/E check | Forward P/E is positive and below the watchlist cutoff. |

Important: this is still a derived number, but it is not a valuation target. It is a count of visible checks, so it can be explained as "5 of 7 checks passed."

Alternative Claude should challenge: remove all Tool B score/rank fields entirely and let users sort by the raw metrics. This is cleaner philosophically but larger because the Combined layer currently expects a Tool B score. My recommendation is to use the transparent check score for now, then decide later whether the Combined score should also be removed.

## 5. Implementation Steps

### Step 1: Add Regression Guards Before Deleting

Purpose: make the intended product contract executable.

Tests to add or update first:

- Tool B output should not contain any target/upside fields after the migration.
- Candidate Finder config should not expose `best_upside`.
- Tool D output should not contain `best_upside_pct`.
- Tool B score replacement should not accept or reference `best_upside_pct`.
- A stale artifact with old target columns should not silently drive UI logic.

This step can initially land as updated expectations inside the same implementation commit if strict test-first is too awkward, but the final test suite must enforce the new contract.

### Step 2: Extract Size Bucket or Remove It

`determine_size_category(...)` currently lives in `golden_vector/screening/targets.py`. If Tool B still wants to show a simple market-cap bucket, move this helper to a neutral file such as `golden_vector/screening/size.py` and rename the output to `market_cap_bucket`.

If Emanuel does not need the bucket, remove it entirely. My recommendation: keep `market_cap_bucket` because "large/mid/small/micro" is easy to explain, but make it clear it is not a peer valuation model.

### Step 3: Remove Target Computation From Tool B

Change `golden_vector/screening/pipeline.py`:

- Remove `compute_target_prices` import and call.
- Remove all target/upside fields from `TOOL_B_OUTPUT_COLUMNS`.
- Add persisted simple metrics from Layer 1 / Layer 2.
- Replace `tool_b_score` / `tool_b_rank` with `fundamental_check_score` / `fundamental_check_rank`, or keep a short-lived `tool_b_score` alias only if needed for compatibility. If an alias is kept, it must equal `fundamental_check_score` and must be documented as transitional.

Preferred final schema:

- `fundamental_check_score`
- `fundamental_check_rank`
- `fundamental_checks_passed`
- `fundamental_checks_total`
- `fundamental_check_summary`

Avoid a second implementation of existing checks. Extend `evaluate_layer1(...)` to emit explicit check statuses while it already evaluates the same thresholds, and add a small verdict/valuation helper for the forward P/E check instead of duplicating that rule elsewhere.

### Step 4: Replace Tool B Ranking

Change `golden_vector/screening/ranking.py`:

- Rank by `fundamental_check_score` descending, not `tool_b_score`.
- Tie-break deterministically by `screening_verdict`, `margin_pct`, `fcf_yield`, `leverage`, and ticker if needed.
- Keep missing/incomplete rows at the bottom.

If `tool_b_rank` is retained for compatibility, rename it in UI to `Fundamental Rank`. Preferred schema is `fundamental_check_rank`.

### Step 5: Remove Target Config

Change config only after code no longer consumes target math:

- Remove `peer_benchmarks` from `config/screening_params.yaml`.
- Remove `PeerBenchmark` and `peer_benchmarks` validation from `golden_vector/contracts/config_models.py`.
- Update config tests/fixtures.

Do not remove threshold config such as `layer1_thresholds` or `verdict_thresholds`; those still support simple pass/fail checks.

Also rename override-form labels that currently say "target" but actually mean cutoffs:

- `Fwd P/E Target (<)` -> `Strong P/E cutoff (<)`.
- `FCF Yield Target (% >=)` -> `Minimum FCF yield (%)`.

### Step 6: Update Tool B UI

Change `golden_vector/serve/overview_tool_b.py`:

- Rewrite opening copy to: "Corporate Finance shows company fundamentals and simple gold-price economics. It does not produce price targets."
- Remove all Peer/Peak target columns.
- Add sections/columns for:
  - Market facts: share price, market cap, enterprise value.
  - Operating facts: production, AISC, reserve life, jurisdiction tier.
  - Gold-price economics: gold price assumption, margin per oz, margin %, revenue, EBITDA.
  - Balance sheet: net debt, net debt / EBITDA, debt / market cap.
  - Cash generation: sustainable FCF, FCF yield.
  - Simple valuation: forward P/E, EV/EBITDA.
  - Checks: `fundamental_check_summary`, verdict, confidence, missing fields.

Keep the table dense. Do not add a long explanatory essay to the page.

### Step 7: Update Detail Pages

Change `golden_vector/serve/detail_panels.py`:

- Remove `best_upside_pct` from the Corporate Finance snapshot.
- Add the clearest simple fields instead:
  - `share_price_usd`
  - `market_cap_musd`
  - `cash_margin_usd_per_oz`
  - `margin_pct`
  - `fcf_yield`
  - `leverage`
  - `forward_pe`
  - `ev_ebitda`
  - `fundamental_check_summary`

### Step 8: Update Candidate Finder

Change `config/candidate_finder.yaml`:

- Remove criterion `best_upside`.
- Remove it from the bullish-call preset.
- Add or use simpler replacements:
  - `margin_pct` high_good
  - `fcf_yield` high_good
  - `ev_ebitda` low_good
  - `leverage` low_good for bullish/quality views
  - `market_cap` high_good if liquidity/size matters

Important direction cleanup:

- Current config has `aisc` and `leverage` defaulting to `high_good` in some places because bearish/fragility screens want "more fragile." That is valid for bearish lenses, but the default Corporate Finance group should be clear:
  - AISC high is risky/fragile.
  - Leverage high is risky/fragile.
  - For bullish quality, low AISC and low leverage are better.

Candidate Finder should make the selected direction visible and user-controlled, but default presets should not imply high leverage is generally "good."

Also stop deriving market-cap ratios request-time if Tool B now persists them. Candidate Finder should consume the persisted Tool B fields through the model-state artifact.

### Step 9: Update Tool D

Change `golden_vector/model/tool_d.py`:

- Remove `best_upside_pct` from `TOOL_D_OUTPUT_COLUMNS`.
- Remove the re-export from `_build_tool_d_row`.
- Keep `fcf_yield` as context only if it is clearly from spot Tool B.
- Ensure Tool D quality rank still uses exactly the locked components: margin/headroom, stressed leverage, EV/EBITDA at G.

### Step 10: Update Combined Layer

Change `golden_vector/combined/join.py`, `golden_vector/combined/pipeline.py`, and `golden_vector/combined/ranking.py`:

- Remove `best_upside_pct`.
- Replace `tool_b_score` dependency with `fundamental_check_score`, or explicitly remove the Combined score if Claude/Emanuel choose the "no Tool B score" route.
- Rename labels in `golden_vector/serve/overview_combined.py` and `golden_vector/serve/workspace_state.py`.

Recommended compatibility route:

- Use `fundamental_check_score` as the Tool B leg of `combined_score`.
- Label the column `Fundamental Checks %`, not `Corporate Finance Score`.
- Keep `combined_score` as a ranking helper, but do not present it as a valuation forecast.

### Step 11: Update Contracts and Tests

Change `golden_vector/contracts/data_models.py`:

- Remove target/upside fields.
- Add simple metrics and check fields.

Update tests:

- `tests/test_screening_targets.py`: delete or replace with tests for `market_cap_bucket` and check scoring.
- `tests/test_screening_verdicts.py`: remove `best_upside_pct` score tests; add check-score tests.
- `tests/test_tool_b_pipeline.py`: assert new schema and no target fields.
- `tests/test_workspace_app.py`, `tests/test_workspace_datatables.py`, `tests/test_candidate_finder_*`, `tests/test_tool_d.py`, `tests/test_screening_overrides.py`, and combined-layer tests as needed.

Add one `rg`-style contract test or explicit schema test that fails if any removed target/upside fields return to Tool B artifacts.

### Step 12: Documentation and User-Facing Wording

Update relevant docs/reviews only where they describe current behavior. Historical review files should not be rewritten.

Add concise page copy:

> Corporate Finance shows company fundamentals and simple gold-price economics. It does not produce price targets.

Avoid long explanatory paragraphs in the UI.

## 6. Acceptance Criteria

Functional acceptance:

- Tool B page renders without Peer/Peak target columns.
- Candidate Finder no longer shows `Best upside %`.
- Detail pages no longer show `best_upside_pct`.
- Tool D no longer exports `best_upside_pct`.
- Combined page no longer labels any target-upside-driven Tool B score.
- Override form no longer uses confusing "target" wording for threshold cutoffs.

Schema acceptance:

- Current Tool B parquet has no columns matching:
  - `target_price_*`
  - `upside_peer_*`
  - `upside_peak_*`
  - `best_target_price_usd`
  - `best_upside_pct`
  - `adjusted_peer_pe`
  - `adjusted_peak_pe`
- `config/screening_params.yaml` no longer contains `peer_benchmarks`.
- `config/candidate_finder.yaml` no longer contains `best_upside`.

Architecture acceptance:

- Candidate Finder consumes persisted Tool B simple ratios instead of recomputing them request-time.
- No duplicate threshold logic is introduced. Layer 1 checks remain owned by `evaluate_layer1`; forward P/E check logic remains close to verdict logic.
- Readers fail clearly or show an actionable stale-schema message if old artifacts are loaded after the code migration.

Testing acceptance:

- Focused tests pass for Tool B pipeline, Tool B ranking, Combined join/ranking, Candidate Finder data/page/config/scoring, Tool D, workspace pages, and schema contracts.
- Full test suite should pass before committing implementation.
- A real local workspace screen check should verify `/tool-b`, `/candidate-finder`, `/tool-d`, `/`, and one ticker detail page.

## 7. Risks for Claude to Push On

1. Score replacement risk: Is `fundamental_check_score` acceptable, or should Tool B have no score at all? My recommendation is a transparent pass-rate for compatibility, but Claude should challenge whether that still violates Emanuel's "simple true numbers" goal.

2. Combined-layer risk: Combined score currently averages Tool A and Tool B score. If Tool B score becomes a pass-rate, the Combined score changes meaning. The UI must make this clear or hide the Combined score.

3. Duplicated-check risk: Adding explicit check columns can accidentally duplicate Layer 1 threshold logic. The plan should extend the existing Layer 1/verdict helpers rather than reimplementing the same checks elsewhere.

4. Stale-artifact risk: Existing local parquet artifacts will still contain old fields until the next refresh. Readers must not silently mix old target fields with new UI logic.

5. Candidate Finder direction risk: AISC/leverage can be "high_good" for bearish fragility screens but "low_good" for bullish quality screens. The UI/config must make direction visible so the same field is not interpreted as universally good.

6. Config-removal risk: Removing `peer_benchmarks` from the strict config model requires updating all config fixtures. Do it only after no code imports target math.

7. Product wording risk: Do not replace confusing target-price math with another opaque "quality score" essay. Keep UI text short and columns self-explanatory.

## 8. Out of Scope

- No new valuation model.
- No analyst-consensus targets.
- No live peer-comps calculation.
- No option-candidate rule changes.
- No Tool A math changes.
- No Tool C/D rank-method changes, except removing Tool B `best_upside_pct` context from Tool D.
- No scheduler or external data-vendor changes.

## 9. Proposed Implementation Checkpoints

Checkpoint A: Tool B schema and score migration.

- Target fields removed from Tool B pipeline.
- Simple metrics/check fields added.
- Tool B ranking changed.
- Focused Tool B tests pass.

Checkpoint B: Downstream wiring.

- Candidate Finder, Tool D, Combined, detail pages, and contracts updated.
- Focused downstream tests pass.

Checkpoint C: UI/docs/final verification.

- Tool B UI rewritten around simple metrics.
- Confusing override labels renamed.
- Schema/config cleanup complete.
- Full test suite and browser smoke checks complete.

## 10. Prompt for Claude Review

Please review `reviews/codex/codex_tool_b_simple_fundamentals_plan.md`.

Emanuel wants Tool B to stop publishing internal price-target calculations and focus on simple, explainable numbers. Review the plan for product clarity and implementation risk. Pay special attention to:

- whether `fundamental_check_score` should replace `tool_b_score` or whether Tool B should have no score at all;
- whether the Combined layer should keep a score after Tool B changes;
- whether the proposed simple metrics are enough to replace Peer/Peak target scenarios;
- whether the plan avoids duplicated threshold/check logic;
- whether stale old artifacts are handled safely;
- whether Candidate Finder directions for AISC/leverage remain clear.

Grade READY / READY WITH MINOR CHANGES / NEEDS CHANGES and save findings in the usual `reviews/codex/` pattern.
