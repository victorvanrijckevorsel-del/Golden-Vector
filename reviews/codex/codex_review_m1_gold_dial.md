# Codex Review - M1 Gold Dial

Verdict: READY WITH CHANGES

Reviewed branch `origin/m1-gold-dial` in the existing throwaway worktree at `.claude/worktrees/m1-gold-dial`, commits `d4cc7ee` and `993f955`, against base `39074f1`. Full suite confirmed: `907 passed in 376.31s`.

## MEDIUM

1. Tool B accepts non-finite scenario gold prices and can render them as live scenarios. `parse_query_overrides` converts URL values with `float(raw)` and only rejects `< 0` or `<= 0`; `nan` and `inf` pass those checks (`golden_vector/serve/screening_overrides.py:90`, `golden_vector/serve/screening_overrides.py:96`, `golden_vector/serve/screening_overrides.py:109`). The CLI path has the same shape: `run_tool_b` only checks `float(gold_price) <= 0` before starting the run and `resolved_gold_price <= 0` before computing (`golden_vector/cli.py:1757`, `golden_vector/cli.py:1860`). I confirmed `/tool-b?gold_price=nan` and `/tool-b?gold_price=inf` return `200 OK` with `Scenario active`. This does not overwrite the latest alias because scenario isolation is working, but it violates the fail-closed honesty contract: the page can claim a live scenario for a malformed price and produce NaN/Inf-derived model rows. Fix by sharing the finite-positive validation already used by Tool D (`golden_vector/serve/overview_tool_d.py:318`, `golden_vector/serve/overview_tool_d.py:326`; model-level equivalent at `golden_vector/model/tool_d.py:741`) or moving that primitive to a common numeric helper, then add tests for Tool B URL overrides and CLI `--gold-price nan/inf`.

## NIT

2. The CLI help text still describes the removed config-gold fallback. `refresh --gold-price` says the Tool B step defaults to `screening_params.default_gold_price_assumption` (`golden_vector/cli.py:209`), and `tool-b --gold-price` says it defaults to the config default or first configured scenario (`golden_vector/cli.py:315`). The implementation now correctly defaults canonical Tool B to the latest daily gold close (`golden_vector/cli.py:1818`, `golden_vector/cli.py:1849`), so this is help-text drift, not a runtime bug. Update the help text so operators do not think config gold can still become the canonical run price.

3. `ScreeningParamsConfig.resolve_gold_price` still documents and implements the old fallback chain (`golden_vector/contracts/config_models.py:893`). It is no longer used by the M1 canonical Tool B path, and the serve guardrail correctly keeps `resolve_gold_price` out of `overview_tool_b.py` (`tests/test_workspace_app.py:1997`). Still, leaving this method with the old "Tool B can always run" semantics is a future footgun. Either rename/comment it as a legacy/scenario helper or retire it once no remaining non-M1 callers need it.

## Verified Checks

- Fail-closed canonical ordering is correct. `run_tool_b` loads the foundation and resolves spot gold before calling `execute_tool_b_pipeline`; if spot is missing and no explicit scenario price was supplied, it finalizes the run and returns before persistence (`golden_vector/cli.py:1807`, `golden_vector/cli.py:1824`, `golden_vector/cli.py:1836`, `golden_vector/cli.py:1873`). Persistence only happens inside `execute_tool_b_pipeline` after row construction (`golden_vector/screening/pipeline.py:77`) and then through `persist_tool_b_outputs` (`golden_vector/screening/pipeline.py:78`).

- Scenario isolation is implemented correctly for normal finite prices. `run_refresh` refuses `--gold-price` before acquiring the refresh lock or running any stage (`golden_vector/cli.py:2920`). Custom `tool-b --gold-price` sets `publish_latest_aliases=False` (`golden_vector/cli.py:1853`) and `persist_tool_b_outputs` only writes `tool_b_latest.*` when that flag is true (`golden_vector/ingestion/persist.py:301`). The pipeline still writes run-stamped scenario artifacts, which is the right audit trail (`golden_vector/ingestion/persist.py:280`).

- The serve boundary is mostly sound. `/tool-b` calls `compute_tool_b_in_memory` for live overrides and otherwise renders the persisted frame (`golden_vector/serve/overview_tool_b.py:283`). It does not contain the obvious EV/EBITDA, debt, margin, or coalesce/fallback formulas, and the guardrail test covers those forbidden tokens (`tests/test_workspace_app.py:1986`). The remaining arithmetic is display/control logic such as percent formatting and comparing the selected price to spot for labels.

- The dial snap-back behavior is covered and works for recompute failures. The rendered gold price is derived from the frame actually displayed (`golden_vector/serve/overview_tool_b.py:100`), and recompute exceptions return the persisted frame with `recompute_active=False` (`golden_vector/serve/overview_tool_b.py:362`). The regression test breaks the recompute input and verifies no `Scenario active` banner plus a spot-valued dial (`tests/test_workspace_app.py:2204`).

- The test helper defaults are acceptable. `tool_b_output_row` now creates a coherent spot row by default (`tests/helpers.py:62`), while stale-schema coverage explicitly removes spot provenance columns and checks the schema guard (`tests/test_tool_b_schema_contract.py:33`). I did not find a test that now passes for the wrong reason because of those defaults.

- Deferring a `ToolBScenarioBundle` is acceptable for M1. The returned DataFrame carries `gold_price_used`, `spot_gold_usd`, `spot_gold_date`, and `gold_price_basis` (`golden_vector/screening/schema.py:39`), and both persistent and in-memory paths share `_build_tool_b_rows` (`golden_vector/screening/pipeline.py:160`, `golden_vector/screening/pipeline.py:272`). A bundle may be useful in Tier 3 when Official vs Our View introduces more provenance axes, but it is not needed for the current gold dial.
