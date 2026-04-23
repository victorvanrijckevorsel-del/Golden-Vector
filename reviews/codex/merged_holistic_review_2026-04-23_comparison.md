# Merged Holistic Review Comparison — 2026-04-23

Sources:
- [claude_review_holistic_repo_check_2026-04-23_findings.md](claude_review_holistic_repo_check_2026-04-23_findings.md)
- [codex_review_holistic_repo_check_2026-04-23_findings.md](codex_review_holistic_repo_check_2026-04-23_findings.md)

Both reviewers ran the suite during their pass: **159 tests passed** in both runs.

Final verdicts diverge:
- **Claude**: `READY WITH MINOR CHANGES`
- **Codex**: `NOT READY`

The disagreement is mostly framing. Both reviewers agree on the same five problem areas; codex weights provenance/trust higher because of the workspace's silent degrade pattern, claude weights data-loss-risk higher because of the workspace company-form null bug. Both are right.

---

## 1. Common Findings

### CF-1 — Tool B `latest` alias missing → workspace silently blank

| Reviewer | Priority |
|---|---|
| Claude | P0 |
| Codex | P1 |

**Status: confirmed, blocking.** Both reviewers verified that `data/output/tool_b/tool_b_latest.parquet` and `tool_b_latest.csv` are absent from the live filesystem despite run-suffixed Tool B outputs existing. The workspace renders blank Tool B cells without warning.

Codex extends this into a broader principle: latest-alias absence should produce a strong UI warning, not a silent empty render. Claude focuses on the immediate fix (regenerate the alias). Both fixes are needed.

**Fix now:**
1. Make the workspace surface a strong warning when `tool_a_latest.parquet` or `tool_b_latest.parquet` is missing.
2. Regenerate the Tool B alias by running `python main.py tool-b --gold-price 4000`.

### CF-2 — Workspace start-up still mutates the manual store

| Reviewer | Priority |
|---|---|
| Claude | P1 |
| Codex | P2 |

**Status: confirmed.** [`run_workspace`](golden_vector/cli.py#L1044-L1055) calls `bootstrap_manual_screening_data` which seeds rows for every active Tool B ticker. The `tool-b` CLI path was already fixed to require an existing store; the `workspace` path was missed.

**Fix now:** replace the bootstrap call with a `manual_store_exists` check; render a clean error page if missing.

### CF-3 — Tool A explanation can contradict the official score

| Reviewer | Priority | Live evidence |
|---|---|---|
| Claude | P0 (in prior Tool A review) | BTG/FRES.L "balanced" fallback (now fixed) |
| Codex | P1 (this review) | FNV anchor=0.9997 below threshold, core=1.108 above; row ranked but explanation says "doesn't earn a rank" |

**Status: partially fixed; one new instance still live.** Claude's prior Tool A review caught the BTG/FRES.L "balanced" fallback case, which has been fixed in `build_interaction_explanation`. Codex caught a *new* instance in `build_delta_explanation`: when the anchor window's delta is below `minimum_rankable_structural_delta` but the structural core is above, the explanation says "not enough linkage to earn an official rank" while the row IS ranked.

I verified live: `FNV` has `structural_delta_12m = 0.9997` (anchor window), `structural_delta_core = 1.108`, `score_eligible = True`, `tool_a_rank = 7`, but `delta_explanation = "Low structural delta means the stock has not shown enough weekly gold linkage in the 12M anchor window to earn an official rank."` — direct contradiction.

**Fix now:** rewrite `build_delta_explanation` to (a) check `score_eligibility_reason` first, (b) describe the anchor delta in band terms without claiming the row doesn't earn a rank, (c) only emit "doesn't earn a rank" when the row is actually score-withheld.

### CF-4 — Tests miss the failure modes most likely to hurt the live product

| Reviewer | Priority |
|---|---|
| Claude | P2 |
| Codex | P2 |

**Status: confirmed.** Both reviewers identified gaps:
- No workspace test for missing Tool B latest alias
- No workspace test for score-withheld notice rendering
- No workspace test for mixed-refresh detection
- No Tool A regression test for anchor-vs-core explanation contradiction
- No Tool B test for non-OK normalized snapshot
- (Claude only) no test that the company form preserves un-edited fields

**Fix now:** add the targeted tests as part of the implementation pass.

### CF-5 — Doc drift / stale messaging

| Reviewer | Priority |
|---|---|
| Claude | P3 |
| Codex | P3 |

**Status: confirmed.** Both reviewers note small inconsistencies:
- README says workspace bootstraps the store *and* tells users to run `manual-data init`
- Architecture map still says "151 passing tests" (now 159)
- Implementation guide (Gold_Framework_Implementation_Guide.docx) uses the old gamma sign convention; code now uses the new one with no documented bridge

**Fix now (small):** update the README workspace section to say "requires `manual-data init` first," and update the architecture map test count. The Implementation Guide is a Word doc — leave with a README pointer rather than touching the .docx.

---

## 2. Claude-only Findings

### C-1 — Workspace company form silently nulls all unfilled fields on every save

**Priority: P1 (confirmed by code re-read).** Not flagged by codex.

[`workspace.py:158-167`](golden_vector/serve/workspace.py#L158-L167) submits *every* numeric field including blanks; `_coerce_form_numeric("")` returns `None`; `upsert_company_input` UPDATEs every column with `None`. So editing one field and saving wipes the rest.

This is a real user-facing data-loss risk. The CLI version filters out `None` values; the workspace handler does not.

**Fix now:** drop fields whose form value is the empty string before passing to `upsert_company_input`. Same fix needed for the reporting form.

### C-2 — `compute_asymmetry_component_score` 0.5 free-credit fallback when `down_beta is None`

**Priority: P1.** [`scoring.py:56-59`](golden_vector/model/scoring.py#L56-L59). With `weights.asymmetry = 0.15`, this awards up to 7.5 score points from a missing-data fallback. Should be `0.0` with no free credit.

**Status: confirmed.** Fix now.

### C-3 — Layer 2 uses an undocumented `0.7` magic constant

**Priority: P2.** [`layer2.py:68-72`](golden_vector/screening/layer2.py#L68-L72). When `cash_cost_usd_per_oz` is missing, the code uses `aisc_usd_per_oz * 0.7` as the cash-cost basis for EBITDA. The 0.7 is not in config, not in tests, not in docs.

**Status: confirmed.** Fix later (move to config).

### C-4 — `_determine_snapshot_anchor_date` falls back to run-start UTC

**Priority: P2.** [`pipeline.py:321-333`](golden_vector/screening/pipeline.py#L321-L333). If the snapshot is empty, Tool B stamps rows with today's wall-clock date. Combined with mixed `as_of_date` per row, this confuses the workspace's "As Of" cell.

**Status: confirmed.** Fix later — easier to also cover via Tool B provenance changes.

### C-5 — `combined/` and `features/{delta,gamma,stability}.py` ship as importable code despite being de-scoped

**Priority: P3.** Codex doesn't flag this. **Defer** — these don't run in the live path; cleanup for later.

### C-6 — Foundation signature doesn't hash the full QA section

**Priority: P3.** Only `max_fx_staleness_days` and `block_on_stale_fx` are hashed. **Defer.**

### C-7 — Conceptual gap with Guo / Leung / Ward paper (single-factor, static window, no Kalman)

**Priority: P1 conceptual.** Codex makes the same conceptual point implicitly ("explanation layer is not fully aligned with scoring"). **Defer to a future modelling pass.** Not fixable in one sitting.

---

## 3. Codex-only Findings

### Cx-1 — Workspace can mix different refreshes on the same page

**Priority: P1.** Codex's strongest framing finding. The Tool A overview reads from `latest_tool_a` (which carries `snapshot_refresh_run_id`), Tool B from `latest_tool_b`, and the per-ticker Tool A detail recomputes structural data live from the *current* foundation snapshot — these can be three different refreshes.

**Status: confirmed.** Claude missed this framing. Adding a workspace-level provenance check that warns when the foundation manifest, the Tool A row, and the Tool B row don't all share the same `snapshot_refresh_run_id` is the right shape.

**Fix now:** add a `snapshot_refresh_run_id` column to Tool B output (it already exists on Tool A), then render a warning notice when the three sources disagree.

### Cx-2 — Tool B output drops normalization / refresh provenance at the published-output boundary

**Priority: P1.** The published Tool B output keeps only `source_run_id` (the Tool B run id), not `snapshot_refresh_run_id`, `snapshot_as_of_date`, or `normalization_status` from the underlying market snapshot. So a downstream consumer (or the workspace) cannot tell which foundation refresh produced the prices, nor whether normalization was clean.

**Status: confirmed.** Claude noted Tool B was provenance-thinner than Tool A but did not flag the specific missing fields with the same sharpness.

**Fix now:** add `snapshot_refresh_run_id`, `snapshot_as_of_date`, `normalization_status` (from the per-ticker market snapshot row) to the Tool B output schema. Update Pydantic contract, columns, persistence test, and workspace display.

### Cx-3 — Tool A detail page recomputes from current foundation snapshot, ignoring the published row's snapshot_refresh_run_id

**Priority: P1 (subset of Cx-1).** The detail page builds structural data live for the requested ticker but uses whatever foundation manifest is *currently* on disk, not the one the published Tool A row was actually produced against. If `update-data` ran but `tool-a` hasn't, the detail page can show different numbers than the headline row.

**Status: confirmed.** Hardest to fix cleanly without re-running Tool A. Two options:
- (a) Detect the mismatch and warn loudly: "Tool A latest output is older than the current foundation snapshot. Run `python main.py tool-a` to refresh."
- (b) Pin the detail computation to the same snapshot run id (requires loading the run-specific foundation snapshot, which is already preserved under `data/runs/<refresh_run_id>/snapshots/`).

**Fix now (option a):** detection + warning. Option b is a bigger lift; defer.

---

## 4. Implementation Plan

I'll execute in this order:

### Phase 1: real bugs that affect today's user
1. **C-1**: workspace company form null bug — change handlers to filter empty strings.
2. **CF-2**: stop workspace from mutating manual store — replace bootstrap with require-existing.
3. **CF-3**: rewrite `build_delta_explanation` so it can't contradict score eligibility (FNV case).
4. **C-2**: asymmetry 0.5 fallback → 0.0.

### Phase 2: provenance / UX
5. **Cx-2**: add `snapshot_refresh_run_id`, `snapshot_as_of_date`, `normalization_status` to Tool B output schema.
6. **CF-1 / Cx-1 / Cx-3**: workspace warns when stable aliases are missing AND when refresh ids don't match across foundation/ToolA/ToolB.

### Phase 3: tests
7. Add targeted tests:
   - Company form preserves un-edited fields
   - Workspace renders missing-Tool-B-alias warning
   - Workspace renders mixed-refresh warning
   - `build_delta_explanation` does not contradict score eligibility
   - `compute_asymmetry_component_score` returns 0.0 (not 0.5) when `down_beta is None`
   - Tool B output carries provenance fields

### Phase 4: doc updates
8. README: workspace requires `manual-data init` first; gamma convention sentence.
9. Architecture map: 159 tests.

### Phase 5: smoke check
10. Run full suite.
11. Run `python main.py tool-b --gold-price 4000` to regenerate the missing alias.
12. Verify workspace would render cleanly via the test infrastructure.

### Deferred
- C-3 (Layer 2 magic constant)
- C-4 (Tool B wall-clock fallback) — partially addressed by Cx-2 provenance work
- C-5 (legacy combined/ and features/ modules)
- C-6 (full QA section hashing)
- C-7 (paper alignment)

---

## 5. Bottom line

The two reviews are highly compatible. Codex frames the remaining issues as a **trust/provenance** problem; Claude frames them as a mix of **direct bugs + provenance + conceptual gaps**. Both are right.

After the Phase 1 + Phase 2 fixes plus regenerating the Tool B alias, the workspace will be:
- non-mutating on open
- non-data-losing on save
- explicit about missing or mixed-refresh outputs
- internally consistent between explanation text and score eligibility
- carrying enough provenance to audit Tool B downstream

That should be enough to move from `NOT READY` to `READY WITH MINOR CHANGES`.
