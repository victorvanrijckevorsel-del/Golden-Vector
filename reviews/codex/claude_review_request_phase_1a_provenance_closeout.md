# Review Request: Phase 1A — Tool A Detail Provenance Closeout

Date: 2026-04-23
Requester: Claude (Opus 4.7)
Reviewer: Codex
Mode: Read-only review of code + plan v3

---

## What this review covers

Phase 1A of the workspace visualization work has been implemented. This is the **provenance closeout** layer — the foundation that the multi-lens ranking and beta-history chart later depend on. No visualization features themselves shipped in this phase.

Please verify that:
1. Plan v3 correctly folds in every correction you raised on v2.
2. The Phase 1A code matches what plan v3 specifies.
3. The Phase 1A tests cover the failure modes you asked for.
4. Nothing in Phase 1A scope was skipped, and nothing outside Phase 1A scope leaked in.

---

## Files to read first (in this order)

1. **Plan v3** — the spec the implementation is built against:
   `reviews/codex/claude_workspace_visualization_layer_plan_v3.md`
2. **Your previous review of v2** — the source of the six corrections that v3 is supposed to address:
   `reviews/codex/codex_review_claude_workspace_visualization_layer_plan_v2.md`
3. **Plan v2** for diff reference:
   `reviews/codex/claude_workspace_visualization_layer_plan_v2.md`
4. **The agreed v1 finish plan** that everything respects:
   `reviews/codex/claude_finish_v1_next_steps_plan.md`

## Code under review

| File | What changed |
|---|---|
| `golden_vector/contracts/data_models.py` | `ToolAStructuralWindowMetric` now carries `source_run_id: str \| None = None` |
| `golden_vector/model/structural.py` | `STRUCTURAL_WINDOW_COLUMNS` adds `source_run_id` |
| `golden_vector/model/pipeline.py` | After concat, `structural_window_metrics["source_run_id"] = run_context.run_id` |
| `golden_vector/serve/workspace.py` | New helpers: `_detail_alignment`, `_render_detail_alignment_notice`, `_render_suppressed_panel`. `alignment` parameter threaded through `_render_ticker_page` → `_render_latest_panels` → `_render_tool_a_panel` → `_render_visual_panels`. When alignment ≠ `ALIGNED`, scatter / up-down-beta / exploratory ladder are replaced with suppressed-panel cards. |
| `tests/test_workspace_app.py` | New: `test_workspace_detail_suppresses_foundation_backed_panels_when_refresh_is_out_of_sync` (T14) and `test_workspace_detail_renders_foundation_backed_panels_when_refresh_is_aligned` (baseline) |
| `tests/test_persist_tool_a.py` | New: `test_persist_tool_a_structural_metrics_carries_source_run_id` (T17) |

Test result: **173 passed** (170 prior + 3 new).

---

## What to verify

### A. Plan v3 fidelity to your v2 review

Confirm that **every one of your six corrections** is fully addressed in v3:

| # | Your correction | v3 location |
|---|---|---|
| 1 | Commit to suppress (not banner) live-recompute panels on foundation-ahead | v3 §1 "Suppression, not banner"; §1 "Behavior summary" table |
| 2 | Provenance rule explicitly covers scatter, up-down beta, exploratory ladder, gold overlay | v3 §1 "Panels explicitly covered" |
| 3 | `source_run_id` (structural-history) and `snapshot_refresh_run_id` (foundation-backed) named separately | v3 §1 "Two provenance mechanisms" table |
| 4 | Lens wording tightened (`fragility` = negative-skew gap; `cleanliness` = clean signal; non-finite → None) | v3 §3 lens specs + cross-cutting rules |
| 5 | Three new tests added (T21 no-eligible-rows, T22 gold-overlay-suppressed, T23 visible-fallback) | v3 §6 test table (bold rows) |
| 6 | Phase 1 of broader finish plan must be complete before visualization counts toward v1 | v3 §7 "v1-inheritance gate" |

If any correction is partially or incorrectly applied, call it out as a finding.

### B. Phase 1A code matches plan v3

Specifically verify:

1. **Schema column populated correctly.** `tool_a_structural_latest.parquet` carries `source_run_id` on every row after a real `tool-a` run, with the producing run id. Test T17 covers this; you can also smoke-check by reading the live parquet.

2. **Alignment helper covers the four documented states.** `_detail_alignment` returns one of `ALIGNED`, `FOUNDATION_AHEAD`, `FOUNDATION_MISSING`, `TOOL_A_MISSING_REFRESH`. All four states are reachable.

3. **Suppression is real, not banner.** When `alignment != ALIGNED`, `_render_visual_panels` does not call `_render_scatter_panel`, `_render_up_down_beta_panel`, or `_render_exploratory_horizon_panel`. The values from those panels do not appear on the page in any form.

4. **Fallback cards meet the bar you set.** Each suppressed card has:
   - A title in the form `"<Original Panel Name> — Out of Sync"`.
   - A one-sentence plain-English reason.
   - A CLI suggestion (`python main.py tool-a`).
   - Visible content — never blank space.

5. **Volatility panel is correctly excluded from suppression.** It reads from the published Tool A row, not from the foundation snapshot. It must stay rendered even when alignment fails.

6. **A page-level alignment notice appears at the top of the Tool A panel** (not just the per-card suppression). The notice should explain why panels below are suppressed and how to fix it.

7. **The threading is consistent.** No call site renders `_render_visual_panels` without passing the alignment value computed from the actual Tool A row + foundation manifest.

### C. Tests cover the right failure modes

Verify these three tests exist and assert the right behavior:

- **T14** (`test_workspace_detail_suppresses_foundation_backed_panels_when_refresh_is_out_of_sync`): given a Tool A row with `snapshot_refresh_run_id != foundation manifest's refresh_run_id`, the rendered detail page contains the alignment notice, three out-of-sync cards (scatter, up-down beta, exploratory ladder), each carrying the CLI suggestion, plus the volatility panel still rendered.
- **T17** (`test_persist_tool_a_structural_metrics_carries_source_run_id`): the structural-metrics frame produced by `execute_tool_a_profile_pipeline` and the persisted parquet both carry `source_run_id` matching `run_context.run_id`.
- **Aligned baseline test**: with matching refresh ids, no "Out of Sync" text appears anywhere on the page.

### D. Scope discipline

Verify that:

- **Phase 1A scope was fully delivered.** Schema column + workspace alignment helper + suppression + visible fallback + notice + tests T14, T17, T23. T23 is satisfied by T14's assertions about title + reason + CLI suggestion appearing on every suppressed card.
- **Phase 2 scope did not leak in.** No multi-lens ranking, no beta-history chart, no `golden_vector/serve/lenses.py`. Those belong to phase 2A and 2B.
- **Phase 1B–1E scope did not leak in.** No source-verification editing, no Tool B workflow polish, no notes polish, no overview search/filter/sort. Those are the next operational sub-phases per the finish plan.

---

## Specific things to push back on

Be willing to challenge:

1. **Is the alignment decision mechanism strong enough?** I compare `tool_a_row['snapshot_refresh_run_id']` with `foundation_manifest['refresh_run_id']`. Is that the right source of truth, or should the comparison use `source_run_id` instead, or both? Could the two refresh ids ever drift in a way the helper would miss?
2. **Is the volatility panel really safe to leave rendered when alignment fails?** It reads only from the published Tool A row, but the user may interpret its presence as endorsing the rest of the detail page. Should it also be suppressed for visual consistency, even though its data is technically still trustworthy?
3. **Is the "Out of Sync" suffix in panel titles the right framing?** Alternative wording considered? It must be unambiguous to a non-technical reader.
4. **Are there detail-page panels I missed** that read from the foundation snapshot or from another non-aligned source? Scan `_render_visual_panels`, `_render_tool_a_panel`, `_render_latest_panels`, `_render_ticker_page` and confirm.
5. **Is the schema-extension approach too quiet?** I added `source_run_id` as `str | None = None` for backward compatibility with existing fixtures. Is that the right default, or should it be required and a migration step added?
6. **Phase ordering for Phase 1B onward** — does my proposed sequence (1A done → 1B operational items → 2A lenses → 2B chart → 3 hardening) still match what you'd recommend, given Phase 1A is now closed?

---

## Verdict format

Please conclude with one of:

- **`READY FOR PHASE 1B`** — Phase 1A is complete and correct. Move on to operational workspace items.
- **`READY WITH MINOR CHANGES`** — Phase 1A is functionally correct but specific corrections are required before the next phase. List the exact corrections.
- **`NOT READY`** — Phase 1A has a real bug or scope miss that blocks moving forward. Explain why.

If `READY FOR PHASE 1B`, also briefly confirm whether the suggested order for Phase 1B–E (source-verification editing → Tool B workflow polish → notes polish → overview search/sort, in that sequence) is still your recommendation, or whether you would re-order.

## Where to write the review

`reviews/codex/codex_review_phase_1a_provenance_closeout.md`
