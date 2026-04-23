# Claude Holistic Review Fix Implementation — 2026-04-23

Reviewer + implementer: Claude (Opus 4.7, 1M context)
Branch: `dev-vic`
Inputs:
- [claude_review_request_holistic_repo_check_2026-04-23.md](reviews/codex/claude_review_request_holistic_repo_check_2026-04-23.md)
- [claude_review_holistic_repo_check_2026-04-23_findings.md](reviews/codex/claude_review_holistic_repo_check_2026-04-23_findings.md)
- [codex_review_holistic_repo_check_2026-04-23_findings.md](reviews/codex/codex_review_holistic_repo_check_2026-04-23_findings.md)
- [merged_holistic_review_2026-04-23_comparison.md](reviews/codex/merged_holistic_review_2026-04-23_comparison.md)

Final test result after the implementation: **170 passed in 11.90s.** Live smoke check: `python main.py tool-b --gold-price 4000` succeeded and re-published the missing alias; `python main.py tool-a` re-ran cleanly and the live FNV row no longer contradicts its rank.

---

## What I changed and why

### 1. Workspace company form: blank numeric fields are now treated as no-op

[golden_vector/serve/workspace.py:162-179](golden_vector/serve/workspace.py#L162-L179)

The previous handler submitted every form field including blanks; `_coerce_form_numeric("")` returned `None`; `upsert_company_input` UPDATEd every column. The numeric form fields are pre-filled with current values, so a normal save round-trips correctly — but any field that was *intentionally* blanked by the user (or accidentally cleared during editing) overwrote whatever was in the DB with `NULL`.

**New behavior:** blank numeric fields are skipped before the upsert. To clear a field, use `python main.py manual-data set-company --ticker <T> --clear-fields <field>`. Documented in README.

This is a defensive change rather than a critical-data-loss bug fix — my original review overstated the magnitude. The form's pre-fill mechanism preserved data in normal cases. But the new behavior is more forgiving and matches the CLI semantics.

### 2. Workspace no longer mutates the manual store on start

[golden_vector/cli.py:1038-1062](golden_vector/cli.py#L1038-L1062)

Replaced the `bootstrap_manual_screening_data` call with a `manual_store_exists` check. If the store is missing, the workspace prints `manual-data init` instructions and exits 1. This matches the `tool-b` CLI path and closes the "open the UI = mutate persistent state" hole that codex (P2) and I (P1) both flagged.

### 3. Tool A `build_delta_explanation` no longer contradicts the official rank

[golden_vector/model/explanations.py:8-50](golden_vector/model/explanations.py#L8-L50) and [golden_vector/model/pipeline.py:417-424](golden_vector/model/pipeline.py#L417-L424)

The previous code unconditionally checked `anchor_delta < minimum_rankable_structural_delta` and emitted "not shown enough weekly gold linkage … to earn an official rank." But scoring uses `structural_delta_core` (the weighted median across windows), not the anchor. Codex's live evidence: `FNV` had `structural_delta_12m = 0.9997` (anchor) but `structural_delta_core = 1.108`, was ranked 7, and still got the "doesn't earn a rank" explanation.

**New behavior:**
- If `score_eligibility_reason == "UNACCEPTABLE_NORMALIZATION_STATUS"` → withheld message (unchanged).
- If `score_eligibility_reason == "LOW_LINKAGE_STRUCTURAL_SIGNAL"` → "doesn't earn a rank" message, with the **core** delta value cited (not the anchor).
- Otherwise → describe the anchor delta with the `delta_bands` thresholds (low / moderate / moderately high / high) without claiming anything about ranking.

The function signature now takes `structural_delta_core` and the call site passes it.

### 4. Asymmetry component score: no more 0.5 free credit when `down_beta is None`

[golden_vector/model/scoring.py:49-69](golden_vector/model/scoring.py#L49-L69)

Previously: `if down_beta is None: return 0.5 if up_beta > 0 else 0.0`. With `weights.asymmetry = 0.15` that was up to 7.5 score points awarded purely for the absence of evidence. New behavior: 0.0 unless we have both up- and down-beta. The clean-asymmetry case (`up > 0, down ≤ 0`) still returns 1.0.

### 5. Tool B output now carries snapshot/refresh/normalization provenance

Five files touched:
- [golden_vector/contracts/data_models.py](golden_vector/contracts/data_models.py) — new fields on `ToolBOutput`
- [golden_vector/screening/pipeline.py](golden_vector/screening/pipeline.py) — pipeline accepts `snapshot_refresh_run_id` and `snapshot_as_of_date` kwargs, captures per-row `snapshot_normalization_status` and `fx_staleness_days` from the normalized snapshot, and writes the new columns
- [golden_vector/cli.py](golden_vector/cli.py) — `run_tool_b` passes the foundation snapshot's refresh id and as-of date
- [golden_vector/serve/workspace.py](golden_vector/serve/workspace.py) — Tool B small-table now displays the new fields

New columns on every published Tool B row:
- `snapshot_refresh_run_id` — the foundation refresh that produced the prices
- `snapshot_as_of_date` — actual data date, not wall-clock
- `snapshot_normalization_status` — per-ticker, e.g. `OK`, `STALE_FX`
- `fx_staleness_days` — observed staleness for that row's price
- `fx_policy_max_staleness_days` and `fx_policy_block_on_stale_fx` — the active FX policy at the time the row was produced

This addresses codex's Cx-2 ("Tool B drops normalization/refresh provenance at the published-output boundary") and lets the workspace detect mixed-refresh views.

### 6. Workspace warns on missing aliases and mixed-refresh views

[golden_vector/serve/workspace.py:496-559](golden_vector/serve/workspace.py#L496-L559)

A new `_render_provenance_warnings` notice appears on the overview page when:
- `tool_a_latest.parquet` is missing → "Tool A latest output is missing. Run `python main.py tool-a`…"
- `tool_b_latest.parquet` is missing → "Tool B latest output is missing. Run `python main.py tool-b --gold-price <X>`…"
- Tool A's `snapshot_refresh_run_id` does not match the foundation manifest's `refresh_run_id`
- Tool B's `snapshot_refresh_run_id` does not match the foundation manifest's `refresh_run_id`
- Tool A and Tool B reference different snapshot refresh runs

The notices live in the same `flash` panel style as existing notices, so they are visually consistent.

### 7. Manual store reads now apply schema migrations

[golden_vector/screening/manual_store.py:138-141](golden_vector/screening/manual_store.py#L138-L141)

Discovered during the smoke check: the live SQLite was created with an older schema and was missing `created_at_utc` / `updated_at_utc` columns. `_create_schema` (which runs `ALTER TABLE … ADD COLUMN … IF NOT EXISTS`-style migrations) was only called from upsert/import paths, not from the read-only `load_store_tables`. So `tool-b`, `manual-data show`, and `workspace` all crashed for a user with an older store.

Fix: `load_store_tables` now calls `_create_schema(connection); connection.commit()` before reading. This is idempotent and matches the existing migration pattern. Users with older stores can now read without first running an upsert.

---

## Tests added

| Test | What it covers |
|---|---|
| `tests/test_explanations.py::test_build_delta_explanation_does_not_claim_no_rank_when_score_is_eligible` | FNV regression: anchor < threshold but core ≥ threshold |
| `tests/test_explanations.py::test_build_delta_explanation_calls_out_low_linkage_when_score_is_withheld` | Withheld-low-linkage path uses core value |
| `tests/test_explanations.py::test_build_delta_explanation_withholds_when_normalization_blocked` | Normalization-block path is unchanged |
| `tests/test_explanations.py::test_build_delta_explanation_describes_high_delta_for_eligible_row` | Standard high-delta path still works |
| `tests/test_tool_a_scoring.py::test_compute_asymmetry_component_score_returns_zero_when_down_beta_is_missing` | No more 0.5 free credit |
| `tests/test_tool_a_scoring.py::test_compute_asymmetry_component_score_still_rewards_clean_negative_down_beta` | Clean asymmetry case still scores 1.0 |
| `tests/test_tool_b_pipeline.py::test_tool_b_pipeline_builds_complete_row_when_manual_inputs_are_present` (extended) | Provenance fields on every output row |
| `tests/test_workspace_app.py::test_workspace_overview_warns_when_tool_b_latest_alias_is_missing` | Missing-alias warning |
| `tests/test_workspace_app.py::test_workspace_overview_warns_when_tool_a_and_tool_b_reference_different_refreshes` | Mixed-refresh detection |
| `tests/test_workspace_app.py::test_workspace_company_post_preserves_unfilled_fields` | Defensive form behavior |
| `tests/test_workspace_app.py::test_workspace_detail_surfaces_score_withheld_notice` | Score-withheld notice surfaces normalization summary |
| `tests/test_cli_workspace.py::test_run_workspace_fails_cleanly_when_manual_store_is_missing` | Workspace requires existing store |
| `tests/test_cli_workspace.py::test_run_workspace_starts_when_manual_store_exists` | Replaces the prior bootstrap test |

All tests pass: **170 passed in 11.90s** before the smoke check, same after.

## Docs updated

- [README.md](README.md) — workspace requires `manual-data init` first; gamma convention sentence (`down − up`, negative is favorable); Tool B provenance columns listed; company-form blank-as-no-op behavior documented.
- [docs/golden_vector_architecture_map.md](docs/golden_vector_architecture_map.md) — test count updated from 151 to 170 with a more accurate description.

## Live smoke check

1. `python main.py tool-b --gold-price 4000` — re-published the missing stable alias. New `tool_b_latest.csv` has 43 columns (was 37). Every row carries `snapshot_refresh_run_id = 20260422T231323Z-foundation-1b5162fd`, `snapshot_as_of_date = 2026-04-22`, `snapshot_normalization_status = OK`, `fx_staleness_days = 0`, `fx_policy_max_staleness_days = 5`, `fx_policy_block_on_stale_fx = False`. Tool B verdicts produced: 1 WATCHLIST (GOLD), 3 SCREEN_OUT (AEM, KGC, NEM), 4 INCOMPLETE (BTG, DPM.TO, FNV, FRES.L) — the four INCOMPLETE rows are the names with no manual data, as expected.
2. `python main.py tool-a` — re-ran successfully. The live FNV row now reads `score_eligible = True`, `tool_a_rank = 7`, `delta_explanation = "Moderate structural delta means the stock has shown a meaningful weekly link to gold in the 12M anchor window, but not exceptional torque."` — no contradiction. The previous "doesn't earn a rank" text is gone.
3. Pytest suite remained green throughout.

## What I deliberately did not fix

These were items in my review or codex's that I judged not worth fixing in this pass:

- **Layer 2 `0.7` magic constant** (Claude C-3): worth moving to config but not blocking. Touching it now would change Tool B numerics for users without manual cash_cost data; that needs a separate, focused change.
- **`combined/` and legacy `features/{delta,gamma,stability}.py` modules** (Claude C-5): dormant code, archive in a later cleanup pass.
- **Foundation signature doesn't hash full QA section** (Claude C-6): the most-affecting QA fields are already hashed; rest is a nice-to-have.
- **Conceptual gap with the Guo / Leung / Ward paper** (Claude C-7, codex echoes implicitly): single-factor regression, static long windows, no Kalman smoothing. This is a modeling pass, not a fix-up pass.
- **Tool A detail page recomputes from current foundation snapshot** (codex Cx-3): the workspace now warns when the snapshot ids don't match (option a in the merged plan). The bigger change — pin detail computation to the published row's `snapshot_refresh_run_id` — would need to read the per-run snapshot from `data/runs/<id>/snapshots/`, which is a larger refactor. Defer until needed.

## Net effect on the merged-review verdicts

- Codex's three blocking concerns:
  1. Workspace mixing/silently losing published outputs → **addressed** (provenance warnings + Tool B provenance fields + workspace requires existing store).
  2. Tool A explanations contradicting score logic → **addressed** (`build_delta_explanation` rewritten + dedicated regression tests).
  3. Tool B dropping FX/refresh provenance at the published-output boundary → **addressed** (six new columns, workspace surfacing).
- Claude's top-3 priorities:
  1. Company form null bug → **addressed** (defensive, blank = no-op).
  2. Tool B alias missing + workspace mutation → **addressed** (live alias regenerated; workspace no longer auto-creates store).
  3. Gamma convention documentation → **addressed** (README sentence).

After these changes I would shift the verdict from `NOT READY` (codex) / `READY WITH MINOR CHANGES` (Claude) to **`READY WITH MINOR CHANGES`** with the deferred items above as the next backlog.
