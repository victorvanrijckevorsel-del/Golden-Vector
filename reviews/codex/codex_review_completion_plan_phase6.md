# Codex Review - Completion Plan Phase 6

**Reviewed plan:** `reviews/codex/claude_completion_plan_portfolio_and_tool_d.md`  
**Verdict:** READY WITH CHANGES

The full plan is directionally sound and Phase 6 belongs after Phases 0-1. The product decisions are mostly right: fold option P&L into Option Trading, keep the CLI markdown report, and stop letting `score_eligible` hide a valid downside context row. But Phase 6 is not build-ready as written. A few items imply artifacts or one-place changes that do not quite match the current code. Tighten those before implementation.

## High-Severity Findings

### 1. Item #24 says "persisted put-P&L output", but no standalone persisted P&L artifact exists

The backend scenario math exists and is consumable, but it is not a separate persisted output. `OptionTradingDetailData` carries `put_bundles`/`call_bundles` (`golden_vector/hedge/option_trading.py:121-140`), and those bundles are computed on demand from persisted candidate artifacts in `build_option_trading_detail` (`golden_vector/hedge/option_trading.py:242-275`). The current detail page already renders the selected sizing scenario table in `_render_option_sizing_result` (`golden_vector/serve/detail_panels.py:798-860`). The older M1.5 speculation section also builds `scenario_bundles` in memory (`golden_vector/hedge/speculation_section.py:155-168`), not as a persisted parquet. Fix the plan wording: either explicitly reuse `compute_scenario_bundle` over persisted selected candidates, or add a new persisted scenario artifact. I recommend the former; it preserves the backend-computed / serve-reads-only rule because the computation remains in `golden_vector/hedge/option_trading.py`, while serve only renders `OptionSizingResult`. The test should assert the Option Trading detail page renders the scenario table from a persisted candidate artifact, not from raw chain scans.

### 2. Item #23 is underspecified because the 300% IV ceiling exists in more than one path

The configurable candidate cap is already in `config/hedge_readiness.yaml:18-19` and `HedgeReadinessConfig` (`golden_vector/contracts/config_models.py:118-119`, validation at `golden_vector/contracts/config_models.py:249-256`). It is enforced in candidate/liquidity paths via `OptionLiquiditySettings.max_implied_volatility` (`golden_vector/hedge/options_liquidity.py:73-74`, `golden_vector/hedge/options_liquidity.py:955-961`) and `option_quote_is_tradable` (`golden_vector/features/options_chain.py:239-249`). Separately, option signals hard-code the same cap at `golden_vector/hedge/option_signals.py:341`, so changing only candidate YAML will still silently remove high-IV contracts from the signal-area chart data. Fix: split "candidate tradability" from "data-quality flag". Put all IV bounds and the extreme-IV warning threshold in validated config, including the signal-area filter. High IV should be surfaced with a flag like `extreme_iv`/`lottery_like`, not dropped, unless it is missing/zero/obviously corrupt. Tests must cover selected candidates, contract metrics/quote flags, and option-signal frames.

### 3. Item #25 is not a one-place change today

The direct speculation ranking exclusion is in `golden_vector/hedge/sensitivity_ranking.py:121-156`, especially `is_rankable = score_eligible and down_beta is not None` at `golden_vector/hedge/sensitivity_ranking.py:156`. That is the clean place to implement the "rank with note" behavior for the Sensitivity / speculation ranking. But Candidate Finder also masks Tool A criteria when `score_eligible` is false (`golden_vector/model/candidate_finder.py:299-301`). The plan says "speculation ranking" but could be read as "all discovery rankings." Fix the plan to scope this precisely: change `hedge.sensitivity_ranking` first; do not globally disable score eligibility in Tool A, Tool C, lenses, or Candidate Finder. If Candidate Finder later needs the same behavior for a specific bearish/downside preset, add a criterion-level config field such as `honor_score_eligible: false` for that criterion only.

## Medium-Severity Findings

### 4. Item #22 is feasible, but the exact artifact names and render path must be corrected

The chart data is persisted and loaded today, but the plan uses shortened names. The real artifacts are `option_skew_curve_points`, `option_oi_strike_points`, and `option_signal_history_points` (`golden_vector/contracts/option_artifacts.py:19-22`). They are written by `build_option_artifact_frames` (`golden_vector/hedge/option_artifact_frames.py:81-84`) and loaded into `OptionTradingData` (`golden_vector/serve/option_trading_data.py:80-83`, `golden_vector/serve/option_trading_data.py:480-483`). The exact reader/path should be: `GET /ticker/{ticker}?lens=option-trading`, `build_option_trading_detail_data`, `_with_option_signal_payloads`, then `_render_option_trading_panel` (`golden_vector/serve/detail_page.py:99-104`, `golden_vector/serve/option_trading_data.py:217-230`, `golden_vector/serve/detail_panels.py:220-265`). Current UI only renders the signal card and a small name-vs-sector skew table (`golden_vector/serve/detail_panels.py:232-349`), not the three charts. Fix the plan to name those exact artifacts/readers so the build does not accidentally scan raw chains.

### 5. Item #22 overpromises an IV-rank sparkline

`option_signal_history_points` exists, but `_history_points_frame` currently sets `iv_rank` to `None` for every row (`golden_vector/hedge/option_signals.py:712-733`). That means an "IV-rank sparkline" is not available yet as real data. The build can render a history chart for `skew_residual_60d`, `atm_iv_60d`, and `iv_rv_ratio`, with a calm "limited history / IV rank not available yet" state. If Emanuel really wants IV-rank history now, that is an extra backend computation step and test, not just a renderer.

### 6. Item #26 must not delete the hedge report comparison module

"Compare View" is ambiguous. The old workspace side-by-side compare view is deferred documentation, but the hedge-readiness CLI/report uses `golden_vector/hedge/comparison.py` and the `comparison` section in `golden_vector/hedge/report.py`. The plan also says the CLI markdown report stays. Fix item #26 to say: close only the old workspace pair/side-by-side compare-view backlog references; do not remove `hedge.comparison`, CLI `--comparison-sort-by`, or the markdown comparison section.

### 7. Item #27 bundles three different milestones under "small nits"

Moving option policy to YAML is a real config/contract migration; Yahoo outage behavior is a data-quality/fail-closed change; adding `ruff` + `mypy`/`pyright` is repo-wide tooling. They should be split:

- #27a: option-candidate policy config migration: OTM ranges, bucket gates, lottery thresholds, IV hard/soft bounds, implied-vs-modeled verdict thresholds.
- #27b: single-vendor outage behavior: define full-outage vs per-ticker outage, whether publish fails closed or publishes visible FAIL rows, and no live-vendor tests.
- #27c: lint/type baseline: add `ruff` first with minimal config; add `mypy` or `pyright` only if the baseline is scoped and non-disruptive.

There is no `pyproject.toml` and `requirements.txt` currently only lists runtime/test dependencies, not `ruff`, `mypy`, or `pyright` (`requirements.txt:1-9`). Treating all three as one small item risks a noisy, unreviewable diff.

## Low-Severity Findings / Nits

### 8. Phase 6 ordering should be adjusted

Do #27a before #23 if the IV cap and lottery flags are moving into config anyway. Then do #23 against that config. Do #22 after #23, because chart data quality will otherwise still reflect the old IV filter. #24 can be done after #22/#23. #25 is independent and can be first if it is kept strictly inside `hedge.sensitivity_ranking`.

Recommended Phase 6 order:

1. #25 rank-with-note in `hedge.sensitivity_ranking`.
2. #27a option policy config migration.
3. #23 IV cap/high-IV flag behavior.
4. #22 render option-signal charts from persisted frames.
5. #24 improve/surface the Option Trading scenario block and document hedge-page retirement.
6. #26 docs cleanup for the old workspace compare view.
7. #27b/#27c as separate hardening/tooling commits.

### 9. The plan should add artifact schema/column tests for the chart frames

The artifacts are in the option artifact name list, but the plan should require focused tests that the three chart frames carry the columns the renderer consumes. This protects against the same producer/consumer drift that previously broke Candidate Finder joins. Suggested tests: `option_skew_curve_points` has ticker/horizon/delta/side/iv/liquidity columns; `option_oi_strike_points` has ticker/strike/side/OI/volume/DTE/expiry; `option_signal_history_points` has ticker/as_of/skew/atm_iv/iv_rv fields.

### 10. Retiring the hedge web page is the right product call

I agree with the decision. `/hedge-readiness` already redirects to `/option-trading` (`golden_vector/serve/workspace.py:112-113`), while `/hedge-readiness/latest.md` still serves the CLI markdown download behind the portfolio gate (`golden_vector/serve/workspace.py:115-129`). That is the right shape: one interactive Option Trading surface, one downloadable detailed markdown report. The plan should say "retain the markdown download route" explicitly, not just "keep the CLI report."

### 11. The `score_eligible` product decision is right, with narrow scope

For speculation, Emanuel wants "show me downside behavior even if the official Tool A composite score is withheld." That is reasonable. But the official score gates remain important elsewhere. The note should say "score withheld; downside beta shown for context" and the row should not get a Tool A score. This keeps the honesty bar intact.

## Whole-Plan Coherence

The full plan remains coherent if the above edits are made. Phase 0 and Phase 1 are still the correct prerequisites. Phase 6 can run after those because it touches option/discovery surfaces, not portfolio valuation. The only direct contradiction is item #24's "persisted output" wording and item #26's ambiguous "Compare View" wording. Fix those before coding.

## Final Verdict

**READY WITH CHANGES.**  

Do not start implementation until the plan is patched for:

1. exact option artifact/render path names for #22;
2. IV cap changes across candidate, liquidity, feature, and signal paths for #23;
3. scenario output wording for #24;
4. narrow `score_eligible` scope for #25;
5. compare-view wording that protects the CLI report comparison;
6. splitting #27 into config migration, outage behavior, and lint/type tooling.

After those edits, the plan is buildable and the product direction is sound.
