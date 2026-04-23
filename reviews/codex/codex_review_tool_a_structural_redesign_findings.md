# Codex Review: Tool A Structural Redesign

Date: 2026-04-23

Scope:
- Read-only review only
- No application code changes
- Reviewed the structural Tool A redesign against:
  - [ssrn-3172514.pdf](C:/Users/Emanuel/code/Golden-Vector/ssrn-3172514.pdf)
  - [Gold_Framework_Implementation_Guide.docx](C:/Users/Emanuel/code/Golden-Vector/Gold_Framework_Implementation_Guide.docx)
  - current source, tests, workspace presentation, and live Tool A artifacts

Verification run during review:

```powershell
& 'C:\Users\Emanuel\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest tests/test_tool_a_pipeline.py tests/test_tool_a_scoring.py tests/test_labels.py tests/test_cli_tool_a.py tests/test_workspace_app.py tests/test_persist_tool_a.py
```

Result:
- `20 passed`

## 1. Findings Ordered P0 To P3

### [P1] Tool A is using partial current-week data as if it were a full weekly close, and it future-dates the official snapshot

Where:
- [golden_vector/model/structural.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/structural.py:486)
- [golden_vector/model/structural.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/structural.py:489)

What is wrong:
- `_last_trading_day_per_week()` groups rows into `W-FRI`, keeps the last row in the bucket, then stamps `as_of_date` with the bucket end date (`Friday`) rather than the actual last trading date.
- That means a mid-week refresh can produce a latest weekly row whose:
  - `stock_week_date` is Wednesday or Thursday
  - but `as_of_date` is the coming Friday
- The structural regressions then treat that partial week as a normal weekly observation.

Why this matters:
- This is not just a labeling issue.
- It means the official structural delta / gamma / volatility calculations can include a partial-week return as if it were a full weekly close.
- That weakens the mathematical meaning of the weekly model and makes the latest snapshot look more current than the underlying data really is.

Concrete evidence from the live artifacts:
- [data/runs/20260423T111640Z-tool-a-25003370/metadata.json](C:/Users/Emanuel/code/Golden-Vector/data/runs/20260423T111640Z-tool-a-25003370/metadata.json) reports `snapshot_as_of_date = 2026-04-22`
- [data/output/tool_a/tool_a_latest.csv](C:/Users/Emanuel/code/Golden-Vector/data/output/tool_a/tool_a_latest.csv) reports `as_of_date = 2026-04-24`
- The live weekly series for `NEM` ends with:
  - `stock_week_date = 2026-04-22`
  - `gold_week_date = 2026-04-22`
  - `as_of_date = 2026-04-24`

Why I consider this blocking:
- The whole redesign is supposed to make Tool A more rigorous and closer to the guide.
- The guide explicitly frames the model around weekly closes.
- A partial-week observation being silently promoted into a weekly close undermines the official metric layer.

### [P1] Low-observation windows still feed the official core delta/gamma/asymmetry and confidence

Where:
- [golden_vector/model/structural.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/structural.py:290)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:273)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:285)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:289)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:503)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:521)

What is wrong:
- `compute_window_metric()` still calculates `structural_delta`, `gamma_value`, and `asymmetry_ratio` for windows marked `LOW_OBSERVATION`.
- Later, `_build_tool_a_outputs()` builds `delta_values`, `gamma_values`, and `asymmetry_values` from all configured windows, not just `ELIGIBLE` ones.
- The weighted medians, delta stability, and sign consistency can therefore be influenced by windows that were already declared too thin for official use.

Why this matters:
- The redesign says the official model is structural-first and should rely on the official windows cleanly.
- In the current code, a thin 3Y window can still influence:
  - `structural_delta_core`
  - `structural_gamma_core`
  - `asymmetry_ratio_core`
  - `delta_stability_score`
  - `confidence_score`
- That weakens the meaning of `ELIGIBLE` and makes the official core metrics less trustworthy than they look.

Why I consider this a real bug:
- The code already distinguishes `ELIGIBLE` vs `LOW_OBSERVATION`.
- Once that distinction exists, the official core metrics should not quietly aggregate the ineligible values back in.

### [P1] Normalization problems are only partly enforced, and blocked rows still look high-confidence and fully classified

Where:
- [golden_vector/model/labels.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/labels.py:53)
- [golden_vector/model/labels.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/labels.py:71)
- [golden_vector/model/labels.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/labels.py:82)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:300)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:332)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:362)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:408)

What is wrong:
- `determine_score_eligibility()` only blocks `MISSING_RETURN_BASIS`.
- `MISSING_FX` and `STALE_FX` remain visible in `normalization_issue_summary`, but they do not downgrade eligibility or confidence.
- Even when a row is blocked, the pipeline still gives it:
  - `confidence_label`
  - `profile_label`
  - plain-English explanations
  - a summary explanation that reads as if the signal is valid

Concrete live evidence:
- In [data/output/tool_a/tool_a_latest.csv](C:/Users/Emanuel/code/Golden-Vector/data/output/tool_a/tool_a_latest.csv), `FRES.L` is:
  - `score_eligible = False`
  - `score_eligibility_reason = UNACCEPTABLE_NORMALIZATION_STATUS`
  - `confidence_label = HIGH`
  - `profile_label = CONVEX`
  - summary explanation = `Convex. Confidence is high...`

Why this matters:
- This directly contradicts the user-facing intent of the redesign.
- If the row is structurally invalid for scoring because normalization is not acceptable, it should not still present itself as a clean, high-confidence convex signal.
- This is especially important because the user explicitly called out FX robustness as non-negotiable.

My view:
- This is not just a UI wording issue.
- The model currently computes and explains a structurally invalid signal too confidently.

### [P2] The confidence layer is mathematically tidy but operationally too weak to be a real trust signal

Where:
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:496)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:512)
- [golden_vector/model/pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/pipeline.py:521)
- [config/scoring.yaml](C:/Users/Emanuel/code/Golden-Vector/config/scoring.yaml)

What is wrong:
- The confidence formula is simple and deterministic, which is good.
- But in practice it saturates quickly:
  - `R^2 >= 0.30` gets full fit credit
  - sign consistency is binary
  - there is no explicit penalty for thin up/down regime splits
  - normalization problems do not flow into confidence
- In the live latest Tool A output, all 8 rows are labeled `HIGH` confidence, including the blocked row.

Why this matters:
- The confidence layer is supposed to help the user judge trustworthiness.
- Right now it mostly says `HIGH` for everything that survives basic structure.
- That reduces the value of the explanation layer and makes the confidence badge look stronger than it really is.

My view:
- This is not a P1 code bug by itself.
- It is a real modeling weakness, and it will matter to end users because they will read `HIGH` as "safe to trust".

### [P2] The structural math has weak direct unit coverage, so the most important bugs slipped past the test suite

Where:
- [tests/test_tool_a_pipeline.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_tool_a_pipeline.py)
- [tests/test_tool_a_scoring.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_tool_a_scoring.py)
- [tests/test_labels.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_labels.py)
- [tests/test_workspace_app.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_workspace_app.py)

What is missing:
- No direct unit tests for:
  - `_last_trading_day_per_week()`
  - `build_structural_weekly_series()`
  - `compute_window_metric()`
  - `compute_volatility_diagnostics()`
  - explanation generation under blocked or inconsistent states
- The current tests are mostly:
  - pipeline happy paths
  - ranking
  - labels
  - workspace rendering with mocked output

Why this matters:
- The P1 bugs above all pass the current tests.
- That tells me the suite is good as a workflow check, but still too weak at the math boundary that matters most in this redesign.

### [P3] The top-level docs still describe the old Tool A model

Where:
- [README.md](C:/Users/Emanuel/code/Golden-Vector/README.md:41)
- [docs/golden_vector_architecture_map.md](C:/Users/Emanuel/code/Golden-Vector/docs/golden_vector_architecture_map.md:64)

What is wrong:
- The README still says Tool A computes `core delta, stability, gamma proxy, regime tags`
- The architecture map still says `tool-a` runs `horizons + Tool A scoring`

Why this matters:
- The implementation has moved meaningfully.
- Anyone reviewing the repo using those docs will build the wrong mental model of what Tool A now is.

This is not a correctness blocker, but it does make review and future maintenance harder.

## 2. Conceptual Alignment With The Guo / Leung / Ward Paper

### What is improved
- The redesign is meaningfully closer to the paper than the old horizon-first model.
- Improvements that move in the right direction:
  - weekly return framing
  - regression-based structural delta
  - explicit up-gold vs down-gold regime split
  - explicit asymmetry
  - keeping volatility as diagnostic rather than a main score factor

### What still does not match the paper
- This is still not a literal paper implementation.
- The paper is fundamentally about:
  - option-like miner behaviour
  - dynamic implied leverage
  - two-factor replication (gold plus market equity portfolio)
  - time-varying loadings inferred more formally
- The current code is still a practical investor simplification:
  - one-factor gold regression
  - regime split by sign of gold return
  - no market-factor diagnostic in the official model
  - no dynamic state-space or Kalman-style machinery

### My verdict on paper alignment
- The redesign is directionally correct and much better than before.
- But it should be described as:
  - paper-inspired structural implementation
  - not "the paper implemented directly"

## 3. Conceptual Alignment With The Implementation Guide

### What now matches well
- Weekly log returns
- Regression beta for delta
- 6M / 12M / 3Y official windows
- up-gold vs down-gold beta split
- explicit asymmetry
- profile-oriented interpretation

### Where the current code still diverges from the guide
- The guide's classification logic is stricter on low delta:
  - `< 1.0` is effectively avoid or reject or screen out
- The current code still allows low-linkage positive-delta names to remain score-eligible and ranked
  - example: `GOLD` is `LOW_LINKAGE` but still ranked

### Where I disagree with the guide itself
- The guide is useful, but it is too threshold-heavy to be treated as pure truth.
- I would not blindly hard-code all of these as universal rules:
  - `R^2 > 0.30` as a hard truth gate
  - `delta < 1.0` as automatic universal rejection
- The paper suggests more nuance than the guide captures.

### My verdict on guide alignment
- The redesign is much closer to the guide than the previous Tool A.
- But the code is still combining:
  - guide-aligned structural logic
  - more permissive ranking and eligibility behavior
- That should either be tightened or explained explicitly.

## 4. FX / Normalization Assessment

### What is good
- Structural Tool A does use USD-normalized daily price history from the normalization layer.
- It does not recompute FX internally.
- Snapshot provenance is carried through:
  - `snapshot_refresh_run_id`
  - FX policy fields

### What is not good enough
- Normalization problems are not propagated strongly enough into:
  - confidence
  - profile labels
  - explanations
- `MISSING_FX` and `STALE_FX` are visible in the issue summary but not treated as first-class trust degraders.
- A normalization-blocked row can still present itself as a high-confidence convex profile.

### My verdict on FX robustness
- Better than the old system
- Not yet strong enough for the explicit FX safety bar the user asked for

## 5. Explanation And Dashboard / Workspace Assessment

### What is good
- The workspace now has the right overall shape:
  - official structural Tool A on top
  - exploratory horizon ladder clearly separated below
- The explanation fields are a real improvement.
- The metric cards and panels are directionally useful.

### What is still weak
- The explanation layer is only as trustworthy as the underlying gating.
- Right now it can overstate certainty because:
  - blocked rows still get confident summaries
  - low-quality windows still affect core metrics
  - confidence is too easy to max out

### My verdict on the workspace
- The presentation shape is good.
- The biggest remaining issue is not layout.
- It is that some of the displayed structural conclusions look cleaner and more trustworthy than the current math and gating really justifies.

## 6. Missing Tests / Residual Risks

### Tests I would add immediately
- Partial-current-week handling:
  - confirm incomplete weeks are either excluded or correctly dated to the actual last trading date
- Eligible-only aggregation:
  - confirm `LOW_OBSERVATION` windows do not affect official core metrics
- Normalization issue propagation:
  - confirm `MISSING_FX`, `STALE_FX`, and `MISSING_RETURN_BASIS` downgrade or block final interpretation consistently
- Explanation safety:
  - confirm blocked rows do not emit confident profile or summary text
- Volatility diagnostics:
  - direct tests on per-ticker trailing 52-week logic

### Residual conceptual risks
- Confidence remains too optimistic
- Low-linkage names are still rankable
- The model is still a one-factor structural simplification, not the paper in full

## 7. Final Verdict

`NOT READY`

Reason:
- The redesign is directionally strong and much closer to the intended framework.
- But the current official Tool A still has three issues that materially affect trust:
  1. partial-week data is being used as if it were full weekly data
  2. low-observation windows still leak into the official core metrics
  3. normalization-blocked rows can still look high-confidence and fully classified

I would fix those before treating this Tool A as fully trustworthy.
