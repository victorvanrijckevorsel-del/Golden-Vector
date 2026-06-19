# Codex review - Gold Sensitivity refocus plan

Review target: `reviews/codex/claude_gold_sensitivity_refocus_plan.md`

Verdict: **NEEDS CHANGES** before build. The strategic redirect is sound, but the plan has a blocking scope mismatch around the proposed 6M / 1Y / 2Y / 3Y / 5Y selector and a few tooltip implementation details that should be pinned before coding.

## Findings

| severity | area | issue | why | fix |
|---|---|---|---|---|
| HIGH | Horizon selector | The plan says Tool A is "presentation/serve only" while also choosing 2Y and 5Y as required selector windows. | Current `tool_a_latest.parquet` stores only 6M, 12M, and 3Y columns. `ScoringConfig` actively validates `structural_windows` as exactly `["6M", "12M", "3Y"]`; pipeline outputs, data models, benchmark comparison, detail switcher, and tests are also hard-coded to those three. | Split A into two steps: A1 = serve-only selector for 6M / 1Y / 3Y; A2 = model/schema/config/test extension for 2Y / 5Y. Do not call the full five-window A selector cheap. |
| HIGH | Gold Downside (C) | C cannot honestly expose the same horizon selector until new persisted C window fields exist. | `tool_c_latest.parquet` has `down_beta_core`, `up_beta_core`, `downside_volatility_52w`, hit rates, tail metrics, and relative-behavior counts, but no `down_beta_6m/12m/2y/3y/5y`, R2, weeks, or window status. `golden_vector/model/tool_c.py` prepares only Tool A core beta fields. | Add a Tool C model/output contract first: fixed-window down/up betas, R2, week counts, status/confidence, and thin-data handling. Then wire C UI. |
| MED | Tooltips | Cell-level `i` buttons can break exact dropdown filters/sorting if added directly inside table text. | Filter options are derived from raw row values, but DataTables filters rendered cell text with exact regex. A visible button whose text is `i` can make `LOW_LINKAGE` render/search as `LOW_LINKAGEi`. | Make a categorical cell helper that emits clean `data-search` and `data-order` values, or otherwise keeps the button out of the searchable/sortable text. Add a render-level test for Profile/Confidence/Volatility filters after value help is added. |
| MED | Tooltips | "Show the value i on cell hover" is not zero-CSS with the current classes. | Existing `.help-icon` is always visible and styled for headers. The popup/panel JS is reusable, but hover-only cell visibility needs a wrapper/class and likely small CSS. | Either accept always-visible value icons, or explicitly allow a tiny CSS addition for hover/focus visibility. Preserve keyboard/touch access; do not make help hover-only. |
| MED | Trust signal | The new "Gold-link (R2)" column is right, but it should not imply a hard truth cutoff by itself. | Current data has very low-link names: 3Y R2 examples include CG 0.006, PRU 0.011, TXG 0.013. Some ranked names also sit near the weak/moderate boundary, so the page needs both R2 banding and existing eligibility/profile context. | Show R2 band plus weeks/window status. Use `LOW_LINKAGE`/rank-ineligible state where applicable; avoid a confident beta display for weak-fit names. |
| LOW | GDXJ reference row | GDXJ should be included, but only when its same-window benchmark beta is available and status OK. | The detail comparison code already handles GDX and GDXJ as same-window benchmarks and excludes degraded benchmark rows. Table reference rows should follow the same rule. | Add both GDX and GDXJ reference rows, with the same horizon, same formulas, and a clear benchmark/non-rank styling. |

## Factual confirmations

| claim | confirmation |
|---|---|
| Tool A stores per-window betas | Confirmed. `data/output/tool_a/tool_a_latest.parquet` has `up_beta_6m/12m/3y`, `down_beta_6m/12m/3y`, `r_squared_6m/12m/3y`, `weeks_6m/12m/3y`, and `window_status_6m/12m/3y`. |
| Tool A already supports 2Y / 5Y | Not confirmed. It does not. Current output columns, `TOOL_A_OUTPUT_COLUMNS`, `ToolAOutputRow`, `benchmark_comparison.py`, `workspace_state._STRUCTURAL_WINDOWS`, and detail-page tests are all 6M/12M/3Y shaped. |
| Tool C stores windowed downside betas | Not confirmed. `tool_c_latest.parquet` has no windowed beta/R2/week/status fields. Tool C currently joins Tool A core beta fields plus relative-behavior, hit-rate, tail, and rank fields. |
| Value-level tooltips can reuse machinery | Mostly confirmed. `ColumnHelp`, `help_icon()`, and `help-popover.js` already provide a click panel with meaning/formula/read-more through `data-help-*`. A value glossary plus `help_value()` can reuse this transport. The build still needs clean table search/sort attributes and accessibility tests. |
| Tool B / Tool D are not horizon-window tools | Confirmed for historical windows. `tool_b_latest.parquet` and `tool_d_latest.parquet` have no 6M/12M/3Y-style columns. Tool B/D have gold-price scenario/stress controls, but those are not trailing historical horizons. |

## Dimension answers

**1. Strategic soundness**

Sound. Leading with validated contemporaneous up/down beta is the right product call. The parked capture/convexity/Phase 5 layer may still be useful as research, but it is not the first screen for "which miners react to gold?" Keeping it parked rather than deleted preserves optionality without confusing the user.

**2. Table redesign**

Mostly sound. A scannable table led by stable 3Y beta, recent 12M-vs-3Y shift, R2/trust, Gamma, Asymmetry, Confidence, Profile, and Volatility is useful and honest. Dropping the opaque "Gold Sensitivity Score" from the main decision surface matches the repo rule against invented composite scores.

Two guardrails: the recent-shift arrow must be labeled as a noisy directional hint, not a trend forecast; and low-R2 or low-window-status rows must sort/display as weak evidence, not just carry a small warning.

**3. Horizon selector**

Correct principle, wrong A effort estimate. Fixed windows are the right scope; custom ranges should stay out because they invite window-shopping and would push regression into the request path.

Build split should be:

1. Tool A serve-only: 6M / 1Y / 3Y, where 1Y is `12M`.
2. Tool A model/schema extension: add 2Y / 5Y through centralized config, output columns, benchmark beta columns, detail switcher, tests, and current-state contracts.
3. Tool C model/schema extension: persist windowed down/up betas, R2, week counts, status/confidence, then add C selector.

Data availability: current 6M is usable in the latest run (62/62 rows eligible, 26 weeks, 14 up-gold weeks, 12 down-gold weeks, no missing split betas). 5Y is not universal: among current Tool A tickers, `AAUC.TO` has about 2.8 years and `THX.L` about 5.0 years of USD-equity history, so 5Y needs explicit unavailable/thin handling.

**4. Value-tooltip system**

Directionally correct. A central value glossary is the right UI source of truth, but it should be populated from or kept consistent with `golden_vector/model/labels.py` and `golden_vector/model/explanations.py`, because those files define/describe labels like `LOW_LINKAGE`, `FRAGILE`, `DEFENSIVE`, `HIGH_DOWNSIDE_RISK`, and confidence states.

Implementation requirements:

- Use `help_icon()`/`data-help-*` rather than new popup JS.
- Escape glossary content through the existing helper.
- Keep table sorting/filtering clean with `data-search`/`data-order`.
- Keep value help reachable by keyboard/touch; hover-only would regress mobile.

**5. Honesty / architecture**

The intended architecture is sound if the selector only reads persisted fields. Do not compute new betas in `/tool-a` or `/tool-c` request handlers. Any 2Y/5Y A or windowed C work must publish persisted artifacts and update the model-state/current-state contract.

Thin downside data is currently not an issue for the latest 6M Tool A run, but the design still needs to display week counts/status because this can change with newer or shorter-history tickers.

**6. Missing items**

- Add tests for value-help cells with DataTables filters.
- Add a backend/window resolver shared by Tool A overview, detail page, and benchmark comparison instead of another hard-coded window list.
- Add explicit copy that C downside ranks are descriptive risk reads, not forecasts.
- Decide whether the main Tool A table defaults to 3Y even if the current canonical anchor remains `12M`; this is a product choice and should be named.

## GDXJ reference-row call

Yes: include GDXJ beside GDX. It is especially useful because many junior miners should compare against the junior-miner ETF, not only broad GDX. The reference rows must be same-window, clearly styled as benchmarks, excluded from miner ranks/counts, and hidden/degraded if benchmark status is not OK.

## Final verdict

**NEEDS CHANGES** before build.

Blocking list:

1. Correct Tool A scope: 6M / 1Y / 3Y is presentation-only; 2Y / 5Y is model/schema/config/test work.
2. Correct Tool C scope: no selector until windowed C beta/R2/week/status fields are persisted.
3. Pin the value-tooltip cell contract so it does not break DataTables filtering/sorting and remains accessible on touch/keyboard.

After those changes, the plan is sound to build.
