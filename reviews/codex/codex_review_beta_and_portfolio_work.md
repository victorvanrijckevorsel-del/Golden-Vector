# Codex Review - beta comparison and portfolio work

Scope reviewed: `39a0a3b..main` (`6c27619`, `99cb765`, `80ba2dd`, `a61e343`, `7d61988`).

Reviewer stance: adversarial code review. I read the request file first, then inspected the diff and current tree firsthand. I did not edit product code.

## Findings

### HIGH - Snowball apply-writer is not wired to any write path

The new module builds `PortfolioLot` objects, but the shipped CLI still exposes only the dry-run command. There is no `--apply`, no `--confirm-write`, no diff preview, and no call into the portfolio store writer. That means the "apply-writer" milestone does not actually provide a way to apply the combined Snowball + HL position set.

Refs:
- `golden_vector/cli.py:418` - command help still says the Snowball command "never overwrites the manual portfolio store".
- `golden_vector/cli.py:441` - only `--print` is added; no apply/confirm flags.
- `golden_vector/cli.py:763` - `run_portfolio_import_snowball` only builds a dry-run and writes a report.
- `golden_vector/cli.py:808` - explicitly prints "No portfolio store was changed."
- `golden_vector/portfolio/snowball_apply.py:165` - `build_combined_gold_lots` returns lots but does not write, diff, or reconcile against the existing store.

Concrete fix: add a real apply path behind two explicit flags, for example `portfolio-import-snowball --apply` to preview the exact replacement diff and `--confirm-write` to write. The write path should load current lots, build a full reconciliation plan, print added/removed/changed shares and cost basis, preserve required existing metadata, then call a public store replacement helper that performs an atomic write and backup. Add tests proving `--apply` alone writes nothing, `--apply --confirm-write` writes, and blocked/review-unresolved rows cannot silently disappear.

### MEDIUM - HL ISA sales reduce shares but not cost basis

`parse_hl_isa_gold_lots` nets purchases minus sales for share count, but it keeps gross purchase cash paid as the remaining cost basis. If the HL history contains any sale for an in-scope name, the remaining shares get overstated cost and understated P&L.

Refs:
- `golden_vector/portfolio/snowball_apply.py:97` - purchase rows add shares.
- `golden_vector/portfolio/snowball_apply.py:100` - purchase rows add gross cost.
- `golden_vector/portfolio/snowball_apply.py:105` - sale rows are handled.
- `golden_vector/portfolio/snowball_apply.py:106` - sale rows subtract shares only.
- `golden_vector/portfolio/snowball_apply.py:118` - emitted `cost_gbp` is still gross purchase cost.

Concrete fix: either parse a current HL cost-basis/current-holding export instead of reconstructing from trade history, or implement explicit FIFO/average-cost sale accounting so sales remove both shares and the matching cost basis. Add a test with a purchase followed by a partial sale and assert the remaining cost basis is reduced.

### MEDIUM - Snowball buy dates and backup semantics do not match the reviewed plan

The reviewed plan says Snowball is a holdings snapshot, so existing `buy_date` should be preserved where a ticker already exists, and every apply should be reversible with a versioned backup. The implemented builder does not accept current lots, so it cannot preserve existing buy dates, and the existing `_write_lots` helper only backs up pre-v2 stores, not every overwrite of a current v2 real-money store.

Refs:
- `golden_vector/portfolio/snowball_apply.py:194` - every import-ready Snowball row gets `buy_date=snowball_as_of`.
- `golden_vector/portfolio/snowball_apply.py:214` - merged SRB.L also gets `buy_date=snowball_as_of`.
- `golden_vector/portfolio/snowball_apply.py:12` - module doc says the apply is reversible via versioned backup.
- `golden_vector/portfolio/manual_store.py:273` - `_write_lots` is the only atomic writer.
- `golden_vector/portfolio/manual_store.py:286` - `_backup_pre_v2_store` backs up only old-schema stores.
- `golden_vector/portfolio/manual_store.py:303` - current v2 stores return without backup.

Concrete fix: pass current lots into the apply-plan builder and preserve existing `buy_date` per ticker where intended. Add a dedicated apply backup, e.g. `manual_lots.backup-apply-{stamp}.json`, before replacing any current v2 store. Test both buy-date preservation and backup creation on a v2 overwrite.

### MEDIUM - New required portfolio/benchmark columns were added without a schema bump or reader backfill

This range adds required columns to `POSITION_COLUMNS` and `BENCHMARK_BETA_COLUMNS`, but `PORTFOLIO_SCHEMA_VERSION` remains `7`. Existing v7 artifacts without these columns can still look like current-schema artifacts to model-state inspection, then fail later in the portfolio reader as missing columns. This is exactly the kind of persisted-artifact contract drift the repo rules warn about.

Refs:
- `golden_vector/portfolio/pipeline.py:126` - adds `avg_cost_gbp` to required position columns.
- `golden_vector/portfolio/pipeline.py:127` - adds `pnl_fraction_gbp` to required position columns.
- `golden_vector/portfolio/benchmark_betas.py:41` - adds `down_beta_6m`.
- `golden_vector/portfolio/benchmark_betas.py:46` - adds the per-window benchmark beta column set.
- `golden_vector/portfolio/models.py:10` - schema version is still `7`.
- `golden_vector/app/model_state.py:795` - model state records columns but does not validate these artifact-specific required columns.

Concrete fix: either bump `PORTFOLIO_SCHEMA_VERSION` and update stale-schema tests/artifacts, or make these fields backward-compatible by filling missing optional columns in the reader before validation. Given these are now render/read contract fields, I recommend a schema bump plus a test that an old v7 artifact without the new columns is rejected with an actionable refresh message.

### MEDIUM - Benchmark comparison ignores benchmark artifact status

The benchmark artifact carries `benchmark_status` and `benchmark_status_reason`, but the comparison resolver uses GDX/GDXJ rows whenever per-window beta cells are finite. A benchmark marked `LOW_CONFIDENCE`, `UNAVAILABLE`, or otherwise degraded can still appear as a clean comparable marker with no warning.

Refs:
- `golden_vector/portfolio/benchmark_betas.py:243` - benchmark status is computed.
- `golden_vector/portfolio/benchmark_betas.py:258` - low confidence becomes `LOW_CONFIDENCE`.
- `golden_vector/model/benchmark_comparison.py:133` - `_benchmark_betas` loops every benchmark row.
- `golden_vector/model/benchmark_comparison.py:143` - it reads beta values without checking status.
- `golden_vector/serve/detail_panels.py:1686` - rendered copy says GDX/GDXJ and the stock are directly comparable.

Concrete fix: carry `benchmark_status` into `BetaMarker` and either exclude non-OK benchmarks from the marker list or render them with an explicit degraded label/reason. Add a test where GDX has a finite beta but `benchmark_status="LOW_CONFIDENCE"` and assert it is not shown as a clean benchmark.

### MEDIUM - Serve layer still clamps backend-resolved marker positions, and the guardrail would not catch it

The model layer already clamps marker positions in `_position`. `_build_beta_strip_svg` clamps again with `min/max`, so a backend bug that returns an out-of-range position would be silently hidden by the serve layer. The guardrail test only forbids a few percentile/rank tokens and `sorted(`, so this duplicated position math is currently allowed.

Refs:
- `golden_vector/model/benchmark_comparison.py:84` - backend `_position` owns the clamp.
- `golden_vector/model/benchmark_comparison.py:92` - backend returns a clamped 0..1 position.
- `golden_vector/serve/charts.py:124` - serve defines `px`.
- `golden_vector/serve/charts.py:125` - serve clamps with `min(1.0, max(0.0, pos))`.
- `tests/test_benchmark_comparison.py:284` - guardrail tokens do not include this min/max clamp.
- `tests/test_benchmark_comparison.py:288` - guardrail only checks `sorted(` in charts.

Concrete fix: remove the serve-side clamp and treat `pos` as a trusted backend contract, or validate and render an explicit unavailable marker if `pos` is outside `[0, 1]`. Strengthen the guardrail by inspecting `_build_beta_strip_svg` specifically and forbidding `min(`, `max(`, `sorted(`, `rank`, `quantile`, and local domain calculation in that function.

### LOW - Percentile suffixes render as `1th`, `2th`, and `3th`

The ordinal formatter always appends `th`, so low percentiles render as awkward user-facing text like `1th percentile`.

Refs:
- `golden_vector/serve/detail_panels.py:1593` - `_ordinal_percentile`.
- `golden_vector/serve/detail_panels.py:1598` - always formats `f"{int(round(percentile))}th percentile"`.
- `tests/test_benchmark_comparison.py:255` - render test checks only that "percentile" appears, not the actual suffix text.

Concrete fix: add an ordinal suffix helper for `st/nd/rd/th`, including 11/12/13 exceptions, or avoid ordinals and render `percentile: 1%`. Add a render-level assertion for 1st/2nd/3rd/11th.

### LOW - One-sided beta availability is rendered as "not in the scored miner universe"

If the subject has only an up beta or only a down beta for a window, the comparison object has a subject marker, but the renderer's lead text keys only off `subject.down_percentile`. A stock with a missing down beta but valid up beta will be described as "not in the scored miner universe", which is false.

Refs:
- `golden_vector/model/benchmark_comparison.py:208` - subject marker is created when either side is present.
- `golden_vector/serve/detail_panels.py:1666` - renderer requires `subject.down_percentile is not None`.
- `golden_vector/serve/detail_panels.py:1674` - otherwise it says the ticker is not in the scored universe.

Concrete fix: build the lead sentence per side. If down is missing and up is present, say the down comparison is unavailable and still show the up percentile. Add a resolver/render test with `down_beta_6m = NA` and valid `up_beta_6m`.

### LOW - `openpyxl` was added without a version floor

The new HL parser requires `openpyxl`, but `requirements.txt` adds it unpinned while every other dependency has at least a lower bound.

Refs:
- `requirements.txt:10` - `openpyxl` has no lower bound.
- `golden_vector/portfolio/snowball_apply.py:81` - parser explicitly uses `engine="openpyxl"`.

Concrete fix: set a version floor, for example `openpyxl>=3.1.0`, consistent with the rest of the requirements file.

## Verified

- The comparison resolver uses the selected window suffix consistently for subject, universe, and benchmark columns (`6M -> *_6m`, `12M -> *_12m`, `3Y -> *_3y`).
- The percentile implementation is inclusive of ties and excludes NA/inf via `optional_finite_float`; denominator counts finite universe rows only.
- The domain includes universe values plus subject and benchmark markers, so out-of-universe ETF markers can still be visible.
- Normal detail-page GET now loads `latest_tool_a` in `_load_workspace_state` and passes that frame into `_load_tool_a_detail`, avoiding the previous second Tool A parquet read on that route.
- Portfolio valuation uses the cost currency's FX for distinct-cost lots, suppresses local P&L when cost currency differs from quote currency, and computes GBP cost/P&L in the backend before the portfolio page formats it.

## Tests

- `.\venv\Scripts\python.exe -m pytest -q` - PASS, `1296 passed in 1379.29s (0:22:59)`.
- `.\venv\Scripts\python.exe -m ruff check golden_vector tests` - PASS, `All checks passed!`.

Note: the unqualified system-Python commands were not the usable repo environment on this machine: `python -m ruff ...` failed because `ruff` is not installed there, and `python -m pytest -q` timed out before completion. The virtualenv commands above are the verified results.
