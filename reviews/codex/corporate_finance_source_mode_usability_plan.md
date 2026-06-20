# Corporate Finance Source Mode Usability Plan

## Goal

Improve usability wherever Golden Vector shows Corporate Finance / fundamentals
numbers.

The user should be able to answer these questions quickly:

1. What is Golden Vector's decision value?
2. What does Yahoo Fundamentals say?
3. If a Yahoo value is calculated, exactly which Yahoo fields produced it?
4. If the selected source changes the inputs, how do the checks, ranks,
   verdicts, candidates, and resilience outputs change?

This is not a one-page display toggle. The same finance numbers appear on
several pages, so the behavior must extend the existing shared fundamentals
system.

## Product Rule

Default view: `Our View`

Alternate view: `Yahoo Fundamentals`

`Our View` means the value Golden Vector currently uses for Corporate Finance
decisions after applying the existing resolution rules: manual value where
present, otherwise approved backend fallback data.

`Yahoo Fundamentals` means the normalized Yahoo statement/fundamentals layer.
The code currently calls this layer `official`; the UI should not expose that
word as the main label. Use `Yahoo Fundamentals`.

The selected source mode must recompute every displayed metric, check, rank,
verdict, filter result, candidate result, and resilience output that depends on
source-switchable finance/fundamentals inputs.

This is not cosmetic. Do not show Yahoo fundamentals beside an Our View rank,
verdict, candidate result, or resilience result unless the output is explicitly
labelled as `Our View`.

It does not mean every market-derived field changes. Gold price, share price,
market cap, option data, beta data, and non-fundamental market snapshots stay
unchanged unless a declared formula uses them as a component.

## Existing System To Extend

Do not build a second fundamentals source path.

The code already has a large part of this feature:

| Existing code | What it already does |
|---|---|
| `golden_vector/fundamentals/resolution.py` | `resolve_fundamental_layers()` resolves `official_value/status/source` and `our_view_value/status/source` per field. Reuse this. |
| `golden_vector/screening/pipeline.py` | Tool B already builds Our View and Official/Yahoo layers, including `ev_ebitda_our_view`, `ev_ebitda_official`, `leverage_our_view`, `leverage_official`, `enterprise_value_musd_our_view`, `enterprise_value_musd_official`, and `_differs` flags. |
| `golden_vector/screening/pipeline.py` and `golden_vector/screening/ranking.py` | Per-source score/rank/summary already exist for fundamentals: `fundamental_check_score_official`, `fundamental_check_rank_official`, `fundamental_check_summary_official`, `fundamental_checks_passed_official`, and `fundamental_checks_total_official`. |
| `golden_vector/serve/overview_tool_b.py` | The page already renders comparison cells and has `rank_by=our_view/official`, `differences_only`, `divergent_field_count`, and `max_divergence_pct`. |
| `compute_tool_b_in_memory()` | This is already the shared request-level recompute hook used by scenario/gold-dial views. Extend this hook instead of adding serve-side finance math. |

Therefore the implementation is:

- rename the visible `Market` label to `Yahoo Fundamentals`,
- treat `fundamentals_source=our|yahoo` as a thin product-facing alias over the
  existing `rank_by` / `official` machinery,
- keep backward compatibility for existing `rank_by=official` links,
- reuse existing `{metric}_our_view`, `{metric}_official`, and `{metric}_differs`
  columns,
- add the missing backend pieces listed below.

## Real Gaps To Build

| Gap | Required fix |
|---|---|
| Per-source verdict | Add `screening_verdict_official` in the model where official checks/rank are already produced. Do not derive it in serve. |
| Source-selectable in-memory Tool B | Add `finance_source: Literal["our", "yahoo"] = "our"` to `compute_tool_b_in_memory()`. The default must preserve current behavior. Yahoo mode should materialize active Tool B outputs from the official/Yahoo layer while keeping flat comparison columns for back compatibility. |
| Calculation provenance | Add provenance/components to the fundamentals mapping layer. The UI popover cannot be built from current mapped fields because components and matched Yahoo line-item labels are discarded. |
| Unified metric object | Build a structured metric object alongside existing flat columns. Do not replace the flat schema in the first pass. |
| Candidate Finder source label/recompute | Candidate Finder must call the same source-aware recompute path and label results, for example `Candidate result: Yahoo Fundamentals`. |
| Corporate Resilience source recompute | Tool D must use the selected source for source-switchable finance inputs, not manually read Our View fields while labelling the result Yahoo. |
| Historical fundamentals | Add separate history artifacts and a merge store. Do not overload the current latest official fundamentals artifact. |

## Source Mode Contract

Use one internal parser for the product-facing URL mode:

- accepted URL values: `our`, `yahoo`,
- default: `our`,
- unknown values fall back to `our`,
- display labels: `Our View`, `Yahoo Fundamentals`,
- compatibility: `rank_by=official` maps to `fundamentals_source=yahoo`.

Suggested URL state:

- `?fundamentals_source=our`
- `?fundamentals_source=yahoo`

The selected source should carry across related links where practical, without
dropping existing query state such as search, sort, ticker filters, gold-price
overrides, scenario settings, tab/lens selection, or horizon/window parameters.

If Claude's horizon-consistency work creates `golden_vector/serve/url_helpers.py`
first, reuse it. If this work creates it first, it must support both
`fundamentals_source=` and future/parallel `window=` parameters.

## Recompute Rule

When the active source is `Our View`, the main output is the existing decision
view.

When the active source is `Yahoo Fundamentals`, the backend must recompute the
active output from Yahoo/official fundamentals wherever those fields drive the
result.

Examples:

- Corporate Finance checks, score, rank, summary, and verdict must reflect the
  active source.
- Candidate Finder eligibility, score/order, and finance-derived columns must
  reflect the active source when they depend on Corporate Finance or Corporate
  Resilience fundamentals.
- Corporate Resilience outputs must reflect the active source for
  source-switchable finance/fundamental fields.
- Ticker detail snapshots must use the same selected-source metric model as the
  overview pages.

This recompute is request/view-level unless a separate command explicitly
persists it. Clicking a source-mode control must not write latest parquet
aliases or promote model-state artifacts.

Persisted Tool B remains the Our View decision artifact unless a separate
product decision changes that contract.

## Display Behavior

| Active source mode | Main value shows | Orange alternate value shows |
|---|---|---|
| `Our View` | Recomputed value/check/rank/verdict/result using Our View inputs | Yahoo Fundamentals value/result, only if different and comparable |
| `Yahoo Fundamentals` | Recomputed value/check/rank/verdict/result using Yahoo inputs | Our View value/result, only if different and comparable |

Do not show an orange alternate when:

- values are equal after numeric normalization,
- the alternate source is missing,
- the metric does not have two comparable sources.

If the active source value is missing but the alternate source exists:

- show the active value as missing,
- show the alternate value in orange with an explicit source label,
- do not silently substitute the alternate source into the main value.

Use explicit labels:

- `Yahoo Fundamentals: 790`
- `Our View: 820`
- `Yahoo value missing`
- `Calculated from Yahoo fields`

Avoid vague labels:

- `Different`
- `Mismatch`
- `Risky`
- `Market disagreement`

Formatting rules:

- compare numbers after backend numeric normalization,
- use metric-aware tolerances,
- format units consistently (`MUSD`, `x`, `%`, `$ / oz`),
- compare ratios on the final numeric ratio, not formatted strings.

## Yahoo Calculation Provenance

The previous version of this plan used `netDebt` as if Golden Vector already
fetched and selected a direct Yahoo net debt field. The code does not currently
do that.

Current mapper behavior:

- `net_debt_musd` is calculated as `total_debt - cash`,
- `total_debt` comes from a direct total-debt line if available,
- otherwise `total_debt` is calculated as `long_term_debt + current_debt`,
- if cash is missing, cash is assumed zero and `statement_scale` records
  `absolute_to_usd_millions_cash_missing_assumed_zero`,
- `ebitda_ltm_musd` is calculated as `operating_income + D&A`,
- reported EBITDA is currently used only as a reconciliation check, not as the
  selected mapped value,
- `_find_value()` currently returns only a numeric value and discards the
  matched Yahoo line-item label.

The provenance model must match these real branches first.

Required provenance states:

| State | Meaning |
|---|---|
| `yahoo_reported_component` | A component such as total debt came from a direct Yahoo line item. |
| `calculated_from_yahoo_fields` | The metric was calculated from multiple Yahoo fields. |
| `cash_missing_assumed_zero` | Net debt used debt minus zero cash because cash was missing. This must not look like a clean calculation. |
| `reconciled_with_reported_field` | A reported field existed and was used as a validation cross-check, for example reported EBITDA. |
| `reported_field_diverged` | The reported cross-check field diverged beyond tolerance. |
| `missing_yahoo_inputs` | Required Yahoo components were missing. |
| `mixed_formula` | The final displayed metric combines Yahoo fundamentals with non-Yahoo inputs such as market cap. |

Required mapper changes:

- extend `_MappedField` with optional structured `components`,
- make `_find_value()` return both the numeric value and the matched
  `line_item_original`,
- capture component value, normalized value, statement currency, value status,
  and matched Yahoo label,
- preserve existing `statement_scale` and add clearer status/origin metadata
  rather than replacing it,
- include provenance for at least `net_debt_musd`, `ebitda_ltm_musd`,
  `da_musd`, `interest_expense_musd`, `enterprise_value_musd`, `leverage`, and
  `ev_ebitda`.

Only add a true direct `netDebt` or direct-selected `EBITDA` path if the fetcher
and mapper are explicitly extended to fetch and normalize those fields. If both
a direct Yahoo field and component calculation exist later, the backend must own
the precedence rule and expose any material direct-vs-component divergence in
the popover.

## Calculation Popover

Any displayed Yahoo value calculated from multiple components gets an `i`
button.

The popover should show:

- formula,
- source state,
- Yahoo fields used,
- matched Yahoo line-item labels,
- component values in the same normalized unit shown on the page,
- final calculated value,
- missing components or fallback behavior,
- statement period, currency, freshness, and value status where useful.

Example for current net debt behavior:

`Net Debt = Total Debt - Cash`

| Component | Matched Yahoo line item | Value |
|---|---|---:|
| Total debt | `Total Debt` | 1,070 MUSD |
| Cash | `Cash And Cash Equivalents` | -250 MUSD |
| Net debt | calculated | 820 MUSD |

Example when total debt is reconstructed:

`Net Debt = Long-term debt + Current debt - Cash`

| Component | Matched Yahoo line item | Value |
|---|---|---:|
| Long-term debt | `Long Term Debt` | 950 MUSD |
| Current debt | `Current Debt` | 120 MUSD |
| Cash | `Cash And Cash Equivalents` | -250 MUSD |
| Net debt | calculated | 820 MUSD |

Example for a mixed formula:

`EV/EBITDA = (Market Cap + Net Debt) / Forward EBITDA`

| Component | Source | Value |
|---|---|---:|
| Market cap | market snapshot | 4,062.5 MUSD |
| Net debt | Yahoo calculated | -270.0 MUSD |
| Forward EBITDA | Tool B model using active source inputs | 565.0 MUSD |
| EV/EBITDA | calculated | 6.72x |

Do not calculate formulas in the UI. Serve code renders backend-provided metric
metadata only.

## Unified Metric Object

Build this alongside the existing flat columns, not as a replacement.

Minimum fields:

| Field | Purpose |
|---|---|
| `metric_id` | Stable key, for example `net_debt_musd`. |
| `label` | Clear display title. |
| `unit` | `MUSD`, `x`, `%`, `$ / oz`, etc. |
| `precision` | Display precision. |
| `our_value` | Our View value. |
| `yahoo_value` | Yahoo Fundamentals value. |
| `active_value` | Value for selected source mode. |
| `alternate_value` | Value to show in orange when different. |
| `differs` | Backend-computed comparison flag. |
| `comparison_tolerance` | Tolerance used for `differs`. |
| `active_result_source` | `our` or `yahoo`. |
| `is_display_source_switchable` | False for non-fundamental fields. |
| `depends_on_source_mode` | True when downstream results must recompute. |
| `recompute_status` | `computed`, `not_applicable`, `missing_input`, or `unsupported`. |
| `our_source` | Manual, official fallback, calculated, etc. |
| `yahoo_source` | Yahoo reported component, calculated Yahoo, mixed formula, etc. |
| `yahoo_value_origin` | One of the provenance states above. |
| `formula` | Human-readable formula. |
| `components` | Rows for the calculation popover. |
| `freshness` | Statement date, fetched date, stale status. |

Start with the metrics that already have flat comparison columns and the load
bearing calculated fields:

- `net_debt_musd`,
- `ebitda_ltm_musd`,
- `enterprise_value_musd`,
- `leverage`,
- `ev_ebitda`,
- `da_musd`,
- `interest_expense_musd`.

## Surfaces In Scope

| Surface | Required behavior |
|---|---|
| Corporate Finance tab (`/tool-b`) | Extend the existing rank/comparison controls. Rename visible `Market` to `Yahoo Fundamentals`. Add source-mode alias, active-source recompute, official verdict, active/alternate comparison cells, and provenance popovers. |
| Ticker detail - Latest Corporate Finance Snapshot | Use the same metric metadata/renderer as Tool B where possible. Do not keep a separate hand-rendered interpretation of the same numbers. |
| Candidate Finder | Recompute finance-dependent candidate rows from the active source. Preserve unrelated option/beta/gold signals. Label result source clearly. |
| Corporate Resilience / Tool D | Recompute source-switchable finance inputs from the active source. Tool D currently reads several financial fields from `manual_data`; this must be reconciled so Yahoo mode is not just a label on Our View inputs. |
| Future finance metric displays | Use the same parser, metric object, and renderer. |

## Corporate Finance Implementation

Phase 1 should start on Tool B because most of the system already exists there.

Tasks:

1. Rename visible `Market` labels in Tool B comparison/rank controls to
   `Yahoo Fundamentals`.
2. Add `fundamentals_source` URL parsing as the product-facing name.
3. Preserve old `rank_by=official` links by mapping them to
   `fundamentals_source=yahoo`.
4. Add `screening_verdict_official` to the Tool B model/schema beside the
   existing official score/rank/summary columns.
5. Add `finance_source` to `compute_tool_b_in_memory()`.
6. Make Yahoo mode materialize active Tool B rows from the official/Yahoo layer
   for request-level views.
7. Keep persisted Tool B outputs backward compatible and defaulted to Our View.
8. Add shared rendering for active value plus orange alternate.
9. Add calculation popovers from backend metric metadata.

`differences_only` remains a separate filter. It should not become the source
toggle.

## Ticker Detail Snapshot

Apply the same source-mode renderer to `Latest Corporate Finance Snapshot`.

The important rule is consistency: if Tool B says the active source is Yahoo
Fundamentals, the detail snapshot for the same ticker must not show an Our View
rank/verdict beside Yahoo values.

Do not refactor unrelated Tool A detail panels during this work. Claude's
horizon-consistency work owns the Tool A/detail window panels; this plan owns
the Latest Corporate Finance Snapshot region.

## Candidate Finder

Candidate Finder must use the same source-aware Tool B recompute hook.

Rules:

- source mode affects only finance/fundamentals-dependent candidate logic,
- option, beta, liquidity, gold-price, and non-fundamental signals should not be
  recomputed unless they explicitly depend on the selected fundamentals source,
- candidate score/order must not silently remain Our View when the displayed
  finance fields are Yahoo Fundamentals,
- add source labels such as `Candidate result: Yahoo Fundamentals`,
- carry `fundamentals_source` in links to ticker detail.

If any finance-dependent candidate calculation cannot be recomputed in Yahoo
mode, show `Unavailable in Yahoo Fundamentals mode` for that result rather than
reusing Our View.

## Corporate Resilience / Tool D

Tool D is part of this feature because it repeats and depends on Corporate
Finance fundamentals.

Pre-existing bug confirmed and fixed in code:

- `ToolDExecutionInputs` did not carry `official_fundamentals`,
- Tool D's internal `compute_tool_b_in_memory()` calls therefore used empty
  official fundamentals,
- the fix is to carry `official_fundamentals` into Tool D and pass it into all
  internal Tool B recomputes.

Further source-mode work still needed:

1. Add a `finance_source` parameter to Tool D request-level compute.
2. Ensure Tool D's source-switchable finance inputs come from the active
   resolved layer.
3. Audit fields currently read from `manual_data` in `_build_tool_d_row()`,
   especially `net_debt_musd`, `interest_expense_musd`, `sustaining_capex_musd`,
   and any future source-switchable fields.
4. Do not relabel non-fundamental resilience values as Yahoo Fundamentals.
5. If a Yahoo-mode resilience output cannot be computed because Yahoo inputs are
   missing, mark it unavailable instead of reusing Our View.

## Historical Yahoo Fundamentals

Yahoo/yfinance can provide prior annual and quarterly statement periods, but
coverage is limited and ticker-dependent. A local AEM probe on 2026-06-20 with
installed `yfinance==1.3.0` returned 5 annual periods and 7 quarterly periods
for income statement, balance sheet, and cashflow.

Current Golden Vector status:

- raw Yahoo statement storage preserves each returned `period_end`,
- the fetcher currently fetches annual statements only,
- the mapped official artifact is latest-period only via `_latest_statement_rows`,
- `FETCHED_FUNDAMENTALS_COLUMNS` already contains `period_type`,
- `RAW_FUNDAMENTALS_STATEMENTS_COLUMNS` does not contain `period_type`.

Do not overload `fetched_fundamentals_latest.parquet`. Keep it as the current
decision artifact used by Tool B and source-mode recompute.

Add separate historical artifacts, for example:

- `fetched_fundamentals_history_latest.parquet`,
- run-stamped `fetched_fundamentals_history_latest_<source_run_id>.parquet`.

Required before quarterly fetch:

- add `period_type` to `RAW_FUNDAMENTALS_STATEMENTS_COLUMNS`,
- infer/store `ANNUAL` or `QUARTERLY` in raw statement rows,
- bump `RAW_FUNDAMENTALS_STATEMENTS_SCHEMA_VERSION`,
- key raw rows by
  `ticker + yahoo_symbol + statement_type + period_type + period_end + line_item_original`.

Suggested mapped historical key:

`ticker + field_name + period_type + period_end`

Historical store requirements:

- fetch only when history is missing, stale by config, or explicitly requested,
- normalize rows into stable keys,
- compute stable `row_hash`,
- append/update only new or changed period rows,
- preserve old rows when Yahoo later returns a shorter history window,
- record `first_seen_at_utc`, `last_seen_at_utc`, and `last_changed_at_utc`,
- record per-ticker coverage such as annual period range and quarterly period
  range,
- use a separate historical refresh cadence such as
  `fundamentals.history_refresh_interval_days`.

Historical trend UI is a later feature. Do not build historical EV/EBITDA,
historical scores, or historical ranks until point-in-time market cap, FX, gold
price, and universe rules are defined.

## Data Integrity Rules

- No mixed currencies without explicit normalization.
- Yahoo statement values must use the existing fundamentals mapping and
  currency/scale normalization.
- Popovers should show normalized values in the same unit as the page.
- Missing Yahoo components remain missing unless a fallback is explicitly
  labelled.
- Do not fill Yahoo mode from Our View inside a Yahoo calculation.
- If required Yahoo inputs are missing, downstream Yahoo-mode rank/verdict/result
  should be unavailable rather than silently copied from Our View.
- Request-level source toggles must not publish model-state artifacts or latest
  aliases.

## Labels Rule

Every label must be a metric name, source state, threshold, or concrete
calculation state.

Use:

- `EV/EBITDA`
- `Net Debt/EBITDA`
- `Yahoo Fundamentals`
- `Our View`
- `Yahoo differs from Our View`
- `Calculated from Yahoo fields`
- `Cash missing; assumed zero`
- `Official statement older than 540 days`

Avoid:

- `Attractive`
- `Cheap but risky`
- `High quality`
- `Bad data`
- `Market disagreement`

If a filter or badge uses a threshold, include the threshold in the label.

Examples:

- `EV/EBITDA below 5x`
- `Net Debt/EBITDA above 2.0x`
- `Official statement older than 540 days`

## Implementation Sequence

### Phase 0 - Correctness Pre-Step

Confirmed and fixed independently of the plan:

- Tool D must pass official fundamentals into its internal Tool B recomputes.

Add or keep a focused regression test proving all internal Tool D
`compute_tool_b_in_memory()` calls receive the official fundamentals frame.

### Phase 1 - Reframe Existing Tool B UI

1. Rename visible `Market` labels to `Yahoo Fundamentals`.
2. Add `fundamentals_source` parser/URL alias.
3. Keep `rank_by` backward-compatible but stop treating it as a separate product
   concept.
4. Preserve `differences_only` as a separate divergence filter.

### Phase 2 - Backend Source Hook

1. Add `screening_verdict_official`.
2. Add `finance_source` to `compute_tool_b_in_memory()`.
3. Ensure default `finance_source="our"` preserves existing tests and persisted
   outputs.
4. Ensure `finance_source="yahoo"` recomputes active Tool B outputs from the
   official/Yahoo layer.
5. Add parity tests proving old persisted Our View behavior is unchanged.

### Phase 3 - Provenance And Metric Object

1. Extend `_MappedField` with components/provenance.
2. Make `_find_value()` expose matched Yahoo labels.
3. Persist or expose enough component metadata for popovers.
4. Build the structured metric object alongside flat columns.
5. Add renderer tests for direct component, reconstructed debt, cash-missing, and
   mixed-formula cases.

### Phase 4 - Tool B Rendering

1. Render active value plus orange alternate from backend metric metadata.
2. Use Yahoo calculation popovers.
3. Make active-source sorting/filtering use the active value.
4. Verify persisted artifacts are unchanged by URL toggles.

### Phase 5 - Detail Snapshot

1. Use the shared source-mode metric renderer for Latest Corporate Finance
   Snapshot.
2. Preserve existing detail page state.
3. Coordinate with Claude's horizon work by not refactoring Tool A detail-panel
   regions.

### Phase 6 - Candidate Finder

1. Thread `fundamentals_source` into Candidate Finder data loading.
2. Recompute finance-dependent candidate logic from the active source.
3. Label candidate result source clearly.
4. Preserve unrelated signals.

### Phase 7 - Corporate Resilience

1. Add source mode to Tool D request-level compute.
2. Reconcile Tool D manual-data reads with active resolved finance fields.
3. Mark unsupported Yahoo-mode resilience outputs unavailable rather than mixed.

### Phase 8 - Historical Fundamentals Store

1. Add raw `period_type` and schema migration before quarterly fetch.
2. Add separate historical mapped artifact contract.
3. Build merge/upsert/row-hash store.
4. Preserve older rows when Yahoo returns less history.
5. Add config-driven historical refresh cadence.

## Tests

Add focused tests for:

- default mode is `Our View`,
- `rank_by=official` maps to `fundamentals_source=yahoo`,
- invalid `fundamentals_source` falls back to `Our View`,
- visible `Market` labels are replaced with `Yahoo Fundamentals`,
- `screening_verdict_official` is produced in the model,
- `finance_source="our"` preserves current Tool B output behavior,
- `finance_source="yahoo"` recomputes active checks/rank/verdict from Yahoo
  fundamentals,
- orange alternate appears only when values differ,
- missing active source does not silently substitute alternate source,
- calculation popover includes formula, components, matched Yahoo labels, units,
  and missing/fallback status,
- cash-missing net debt shows `cash_missing_assumed_zero`,
- EBITDA provenance records reported-field reconciliation,
- Candidate Finder source mode recomputes finance-dependent results,
- Tool D source mode recomputes source-switchable finance inputs,
- serve modules do not contain finance formula fragments,
- URL helpers preserve existing params including future/parallel `window=`,
- toggling source mode does not publish latest aliases or model-state artifacts,
- raw historical annual and quarterly rows with the same `period_end` remain
  distinct through `period_type`,
- historical merge preserves prior rows when Yahoo returns a shorter frame,
- unchanged historical fetches do not mark rows changed.

## Main Risks

| Risk | Mitigation |
|---|---|
| A second source-resolution path is created. | Reuse `resolve_fundamental_layers()` and existing `_our_view` / `_official` columns. |
| `fundamentals_source` and `rank_by` become two competing concepts. | Make `fundamentals_source` the product alias; keep `rank_by` only for compatibility. |
| Yahoo values show beside Our View ranks/verdicts. | Recompute active outputs or label unavailable. |
| Per-source verdict is derived in serve. | Add `screening_verdict_official` in the model/schema. |
| The plan assumes direct `netDebt` exists today. | Match current mapper branches first; only add direct fields if fetch/mapping is extended. |
| Popovers cannot explain calculations. | Capture components and matched Yahoo line-item labels in mapper output. |
| Tool D remains mixed-source. | Audit and replace source-switchable manual reads with active resolved fields. |
| Detail page and Tool B drift apart. | Use shared metric object/renderer for repeated finance metrics. |
| URL helper conflicts with Claude's horizon work. | One shared helper handles both `window=` and `fundamentals_source=`. |
| Historical annual and quarterly rows collide. | Add `period_type` to raw rows before quarterly fetch. |
| Historical artifact breaks current Tool B. | Keep latest official decision artifact separate from historical artifact. |

## Parallel Coding With Claude's Horizon Plan

Parallel coding is possible with guardrails.

Mostly separate areas:

- this plan: fundamentals, Tool B, Candidate Finder finance source, Tool D
  finance source, Yahoo history,
- Claude's horizon plan: Tool A scoring/windows and stock-facing horizon
  consistency.

Coordination points:

| File / area | Owner rule |
|---|---|
| `golden_vector/serve/detail_panels.py` | This plan owns `Latest Corporate Finance Snapshot` / `_render_latest_panels`; Claude owns Tool A detail panels and windowed score/explanation regions. Do not refactor each other's region. |
| `golden_vector/serve/url_helpers.py` | Whoever lands first creates one shared URL helper. The other reuses it. It must preserve both `window=` and `fundamentals_source=`. |
| Candidate/detail navigation links | Coordinate query-param preservation. |

Recommended workflow:

1. Small commits.
2. Rebase after either side touches `detail_panels.py` or URL helpers.
3. Integration check on a ticker detail page where both a horizon/window selector
   and a source selector can coexist.
4. Run focused Tool A/Tool B/Tool D/Candidate Finder tests before merging.

## Open Decisions For Victor

1. Should the orange alternate value appear as a separate column, a second line
   inside the value cell, or vary by page density?
2. In `Our View`, should an `i` button appear when Our View is using an
   official/Yahoo fallback, or only in `Yahoo Fundamentals` mode?
3. Should Candidate Finder have a global source toggle at the top, inherit the
   selected source from links, or both?
4. For dense tables, should the alternate value be always visible in orange or
   visible only when the user expands a row/cell?
