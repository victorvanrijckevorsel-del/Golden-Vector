# Codex Review — Click-To-Explain Rollout

Verdict: **APPROVE WITH CHANGES**

The click-to-explain architecture is sound: one registry owns the copy, `help_th()` centralizes header rendering, thresholds resolve from `AppConfig`, and the JavaScript transport reads backend-provided strings without doing analytics. The key corrected directions check out: Tool D resilience score is higher-better and sorted descending, Tool C downside remains higher-fragility/lower-resilience, Tool C upside is higher-upside, Tool A gamma/asymmetry now match the model math, Tool D survival distance uses selected `G`, and Tool B leverage uses the Layer 1 2.5x LTM threshold.

## Findings

| Severity | File:line | Finding | Why it matters | Fix |
|---|---:|---|---|---|
| **HIGH** | `golden_vector/serve/column_help.py:655` | `portfolio_gold_down_loss` says low- or negative-beta names still show a conservative loss, but the backend withholds them. | The copy says the risk estimate includes low/negative-beta rows. The actual path calls `compute_gold_shock_exposure()` from `golden_vector/portfolio/analytics.py:179`, and `golden_vector/model/gold_shock.py:60-68` floors negative beta to zero then returns `modelable=False` when effective beta is <= the configured minimum. `analytics.py:185-199` then blanks `gold_down_10_loss_usd` and buckets the row as `Low/negative beta`. This is a user-facing formula mismatch on a risk column. | Change the detail text to say only measured/publishable beta rows above the beta gate get a modeled loss; low/negative beta rows are withheld, not force-modeled. Keep the cap-at-position-value sentence. |
| **MEDIUM** | `golden_vector/serve/column_help.py:671` | `portfolio_position_status` overstates what the Status column covers. | The help says degraded status can mean price, beta, or Tool D missing/stale and that gold-loss and resilience are both held back. In code, `position_status` is built only from valuation-line statuses in `golden_vector/portfolio/pipeline.py:611` and `_combined_status()` at `pipeline.py:718`; beta issues are handled separately in `analytics.py:113-207`, and Tool D issues only set `resilience_bucket` / data issues in `analytics.py:222-243`. A row can have `position_status == OK` while beta or Tool D is missing. | Reword Status as a valuation-data status: price, FX, currency, and manual-input validity. Mention beta and Tool D are separate risk/resilience availability fields, not part of this status. |
| **MEDIUM** | `golden_vector/serve/column_help.py:650` | `portfolio_nav_weight` says NAV includes cash and hedges, but M1-M4 NAV currently does not. | `golden_vector/portfolio/analytics.py:267-271` explicitly sets `cash_value = 0.0` until the import milestone, and there is no actual hedge value in NAV. The page footnote at `golden_vector/serve/portfolio_page.py:92` correctly says NAV is entered stock positions until broker cash is imported, so the column help contradicts the page. | Reword to match current behavior: share of current entered-stock NAV; cash/hedges only once later import/hedge-value milestones exist. |
| **NIT** | `golden_vector/serve/static/help-popover.js:107` | The panel uses `role="dialog"` but does not move focus into the dialog or provide full dialog semantics. | Keyboard users can open and close it, and Escape returns focus, so this is not blocking. But a non-modal explanatory popup with focus remaining on the trigger is closer to a tooltip/popover than a dialog; some screen readers may expect dialog focus behavior. | Either use a less demanding role/ARIA relationship for a non-modal explanation, or add explicit non-modal dialog focus semantics. |
| **NIT** | `golden_vector/serve/overview_tool_d.py:313`, `golden_vector/model/tool_d.py:739` | `git diff --check` reports trailing whitespace / blank EOF in the reviewed diff. | Not behavior-changing, but this is easy hygiene to keep the branch clean. | Remove the trailing whitespace and extra EOF blank line. |

## Verified Clean

- `tool_d_quality_rank`: `model/tool_d.py:430-433` ranks `tool_d_quality_score` with `high_good=True`; `overview_tool_d.py:81-86` sorts descending; the explanation’s higher-is-more-resilient direction is correct.
- `tool_c_downside_rank`: `model/tool_c.py:162-168` builds downside weakness scores and ranks with `high_good=True`; `tests/test_tool_c.py:56-57` pins the most fragile row at 100. Claude was right not to invert it.
- `tool_c_upside_rank`: `model/tool_c.py:169-172` ranks upside score with `high_good=True`; `tests/test_tool_c.py:58-59` pins the strongest upside row at 100.
- `tool_a_gamma` and `tool_a_asymmetry`: `model/structural.py:517-526` computes gamma as down-beta minus up-beta and asymmetry as up-beta divided by down-beta; `model/scoring.py:35-68` rewards negative gamma and higher asymmetry.
- `tool_b_leverage`: `screening/layer1.py:66-70` uses Net Debt / LTM EBITDA, and `config/screening_params.yaml:14` sets the 2.5x threshold. The help no longer confuses this with Tool D’s 3.0x stressed-forward danger band.
- The click transport in `serve/static/help-popover.js` is safe from HTML injection (`textContent`) and prevents header sorting only when the icon itself is clicked.

## Checks Run

- `python -m pytest tests/test_column_help.py tests/test_tool_c.py tests/test_workspace_app.py -q` → **86 passed**.
- `ruff check ...` could not run because `ruff` is not installed in this environment.
- `git diff --check 2abbc74..2e5b946 -- ...` → failed only on the whitespace noted above.
