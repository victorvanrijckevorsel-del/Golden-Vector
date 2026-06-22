# Codex Review - Horizon Consistency Plan

Reviewed plan: `reviews/codex/claude_horizon_consistency_plan.md`

Code inspected:

- `golden_vector/model/pipeline.py`
- `golden_vector/model/scoring.py`
- `golden_vector/model/labels.py`
- `golden_vector/model/structural.py`
- `golden_vector/model/tool_c.py`
- `golden_vector/serve/windows.py`
- `golden_vector/serve/workspace_state.py`
- `golden_vector/serve/detail_panels.py`
- `golden_vector/serve/overview_tool_a.py`
- `golden_vector/serve/overview_tool_c.py`
- `golden_vector/contracts/config_models.py`
- `golden_vector/contracts/data_models.py`
- `golden_vector/portfolio/analytics.py`
- `golden_vector/portfolio/benchmark_betas.py`
- `golden_vector/serve/candidate_finder_data.py`
- `golden_vector/model/candidate_finder.py`

## Findings

### P1 - Per-window Score/Confidence/Profile is a bigger methodology change than section 3b says

Claude's section 3b says `compute_tool_a_score` is a weighted sum of one window's `{delta, gamma, asymmetry, confidence}`. The score function itself is a weighted sum, but the inputs currently are not one-window inputs. `_build_tool_a_outputs` first filters to configured scoring windows, computes weighted-median `*_core` values, computes `delta_stability_score` across those windows, then computes one `confidence_score`, one eligibility flag, one profile, and one score from the aggregate/core values (`golden_vector/model/pipeline.py:403`, `golden_vector/model/pipeline.py:441`, `golden_vector/model/pipeline.py:447`, `golden_vector/model/pipeline.py:459`, `golden_vector/model/pipeline.py:465`, `golden_vector/model/pipeline.py:530`, `golden_vector/model/pipeline.py:538`). `determine_score_eligibility` also requires at least two eligible structural windows, which is explicitly cross-window (`golden_vector/model/labels.py:60`, `golden_vector/model/labels.py:75`). `_compute_confidence_score` uses coverage, mean/min fit, sign agreement, stability, and regime readiness across the scoring-window set (`golden_vector/model/pipeline.py:805`, `golden_vector/model/pipeline.py:815`, `golden_vector/model/pipeline.py:843`).

Concrete fix: before coding, define the new per-window methodology explicitly:

- `confidence_score_{w}` must be computed only from that window's own status, R2, regime availability, normalization status, and any approved window-local inputs.
- `score_eligible_{w}` must not require "two eligible structural windows" unless it is intentionally renamed/labeled as a cross-window eligibility gate.
- `tool_a_score_{w}` should use `structural_delta_{w}`, `gamma_{w}`, `asymmetry_ratio_{w}`, `up_beta_{w}`, `down_beta_{w}`, and `confidence_score_{w}` only.
- `tool_a_rank_{w}` should rank `tool_a_score_{w}` within the same `as_of_date` cross-section.

If `delta_stability_score` remains in the confidence formula, then the score is not fully per-window. Either remove it from per-window confidence or expose it only as a separate cross-window diagnostic.

### P1 - Tool C is a stock-facing windowed page but is missing from the rollout

The plan says every stock-facing page should be horizon-consistent, but Tool C currently has a window selector and still uses core ranks/scores. The page docstring says the selected window changes displayed betas while downside/upside rank stays on `*_core` (`golden_vector/serve/overview_tool_c.py:37`, `golden_vector/serve/overview_tool_c.py:39`). Rendering confirms this: the page reads selected-window beta metrics via `window_metrics(row, active_window)` but renders unsuffixed `tool_c_downside_rank`, `tool_c_upside_rank`, `downside_hit_rate_10pct`, and `upside_hit_rate_10pct` (`golden_vector/serve/overview_tool_c.py:61`, `golden_vector/serve/overview_tool_c.py:69`, `golden_vector/serve/overview_tool_c.py:74`). The model contract also says Tool C's per-window columns are display-only and not scoring inputs (`golden_vector/model/tool_c.py:19`, `golden_vector/model/tool_c.py:80`, `golden_vector/model/tool_c.py:252`).

Concrete fix: either include Tool C in the phase plan with per-window Tool C scores/ranks, or remove/disable Tool C's structural window selector for this milestone and label its beta columns as display-only canonical context. The anti-mixing guardrail in section 5 must include Tool C or explicitly exempt it with a visible label.

### P1 - Profile cannot become per-window unless volatility context becomes per-window too

`determine_profile_label` depends not only on delta/gamma/asymmetry, but also on `confidence_label`, `residual_volatility_52w`, and `volatility_context` (`golden_vector/model/labels.py:90`, `golden_vector/model/labels.py:99`, `golden_vector/model/labels.py:133`). The pipeline currently computes volatility diagnostics once from a selected volatility anchor and writes unsuffixed `total_volatility_52w`, `residual_volatility_52w`, `downside_volatility_52w`, and `volatility_context` (`golden_vector/model/structural.py:937`, `golden_vector/model/structural.py:959`, `golden_vector/model/structural.py:990`, `golden_vector/model/pipeline.py:501`, `golden_vector/model/pipeline.py:509`). The detail page then recomputes non-canonical-window volatility in serve code (`golden_vector/serve/detail_panels.py:1828`, `golden_vector/serve/detail_panels.py:1854`, `golden_vector/serve/detail_panels.py:1872`), which conflicts with the plan's "serve reads persisted columns" rule.

Concrete fix: move active-window volatility diagnostics into the model/persisted artifact. Add per-window volatility fields such as `total_volatility_{w}`, `residual_volatility_{w}`, `downside_volatility_{w}`, and `volatility_context_{w}` if Profile is truly per-window. Then remove the serve-side OLS/volatility recompute and make detail/overview render the persisted active-window fields. If volatility is deliberately fixed at 52w, then Profile is not fully per-window and must be labelled that way.

### P2 - The registry phase is not a pure no-behavior refactor if config validation is widened immediately

Section 4 says Phase 1 is registry + redirected imports + widened config validators with no behavior change. The current config deliberately restricts scoring windows to exactly `6M`, `12M`, `3Y`, keeps `2Y`/`5Y` disjoint as display windows, restricts scoring weights to exactly those three windows, and restricts the anchor to `6M`, `12M`, `3Y` (`golden_vector/contracts/config_models.py:1099`, `golden_vector/contracts/config_models.py:1106`, `golden_vector/contracts/config_models.py:1115`, `golden_vector/contracts/config_models.py:1151`, `golden_vector/contracts/config_models.py:1173`, `golden_vector/contracts/config_models.py:1190`). `config/scoring.yaml` also defines only three scoring windows today.

Concrete fix: split Phase 1 into two phases:

1. Registry extraction only: move labels/suffixes/weeks/aliases into one shared structural-window registry while preserving the current scoring/display split and validation behavior.
2. Scoring migration: only after per-window score/confidence/profile columns exist, widen config validation and update `config/scoring.yaml` so any newly scored windows come from centralized config, not hardcoded code paths.

This keeps the spec rule intact: no ad-hoc horizons, only centralized config.

### P2 - Persisted Tool A contract/versioning is underplanned

The plan says to bump schema/method version, but the current Tool A latest artifact is column-list driven and `persist_tool_a_outputs` does not write a Tool A schema/version column or artifact-specific method version (`golden_vector/model/pipeline.py:50`, `golden_vector/ingestion/persist.py:223`). `ToolAOutput` also models the current unsuffixed score/confidence/profile contract, plus 2Y/5Y display-only fields (`golden_vector/contracts/data_models.py:158`, `golden_vector/contracts/data_models.py:209`, `golden_vector/contracts/data_models.py:216`). Many downstream readers still consume unsuffixed core fields: Portfolio reads `down_beta_core`, `confidence_label`, and `score_eligible` (`golden_vector/portfolio/analytics.py:140`); Candidate Finder joins Tool A as-is (`golden_vector/serve/candidate_finder_data.py:488`) and gates configured Tool A fields by unsuffixed `score_eligible` (`golden_vector/model/candidate_finder.py:18`, `golden_vector/model/candidate_finder.py:302`); hedge/option modules also consume unsuffixed fields.

Concrete fix: add an explicit Tool A artifact contract migration:

- introduce `schema_version` and/or `method_version` for Tool A output rows or artifact metadata,
- decide whether unsuffixed fields remain canonical/core compatibility fields or are deprecated,
- add suffixed per-window fields without breaking current downstream readers,
- add reader tests proving legacy consumers either keep using labelled canonical basis or switch to active-window fields intentionally.

### P2 - Per-window rank needs cross-section metadata to stay explainable

`rank_tool_a_outputs` ranks within `as_of_date` (`golden_vector/model/scoring.py:106`), while `persist_tool_a_outputs` publishes the latest row per ticker, not necessarily one common global date. That per-ticker-latest behavior is intentional and tested for lagged tickers (`tests/test_persist_tool_a.py:124`). This means the overview can contain ranks computed from different as-of-date cross-sections when one ticker's latest weekly row lags.

Concrete fix: when adding `tool_a_rank_{w}`, also expose the rank basis clearly: `rank_as_of_date_{w}`, eligible peer count, and perhaps `rank_basis_window_{w}`. Add a test where one ticker lags by one week and make the rendered label unambiguous. Do not let a 5Y rank appear as if it came from the same cross-section as every other ticker if the underlying `as_of_date` differs.

### P2 - Cross-horizon metrics are okay to keep, but they must be blocked from per-window score inputs

Keeping `delta_stability_score` and the Exploratory Horizon Ladder as labelled cross-horizon diagnostics is right. The ladder already tells the user it is tactical context and does not drive the Gold Sensitivity score (`golden_vector/serve/detail_panels.py:1931`). However, `delta_stability_score` currently flows into `confidence_score` (`golden_vector/model/pipeline.py:447`, `golden_vector/model/pipeline.py:459`, `golden_vector/model/pipeline.py:834`), and `confidence_score` flows into `tool_a_score` (`golden_vector/model/pipeline.py:530`). That is not just a display label issue.

Concrete fix: keep `delta_stability_score` visible as `Cross-window delta stability`, but remove it from any per-window `confidence_score_{w}` / `tool_a_score_{w}` formula unless the user explicitly accepts a score that is partly cross-window. If it remains an input, the score label must say so, which contradicts the locked decision that Score is per-horizon.

## Answers To Claude's Review Questions

1. Per-window Score/Rank is directionally sound and respects the spec only if the windows come from centralized config/registry. But the current confidence, eligibility, and profile methods are cross-window, so section 3b must be expanded before implementation.
2. The registry design kills much of the duplication, but misses Tool C as a first-class windowed surface and must keep structural windows separate from exploratory return horizons. Do not merge `features/horizons.py` into the structural-window registry; label that as a separate axis.
3. Cross-horizon metrics should be kept and labelled. They must not feed per-window scores unless the label says the score is mixed-horizon.
4. Main extra risks are Tool C leakage, volatility/profile methodology, Tool A artifact versioning, and rank cross-section explainability.
5. Build sequence is close, but safest order is: registry-only refactor with no validator widening, explicit methodology/contract update, per-window scoring/persistence, serve reads, then cross-surface rollout and guardrail tests.
