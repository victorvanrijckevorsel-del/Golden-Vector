# Claude review — Codex FINAL source-mode (`codex-source-mode` @ `66c5815`)

**Scope:** `git diff 75d1c36..66c5815` (main feature `0f93d95` + review-fix `66c5815`); +2820 / −171 across 31 files.
**Method:** first-hand reads of every attack area + a 9-agent adversarial sweep (1 of 3 raw findings survived verification) + an independent run of the affected suite.
**Verdict: APPROVED — correct and ready to integrate.** One MEDIUM provenance-display nit (edge case), no hard blockers. The high-risk failure modes I attacked for are NOT present.

## The one finding

### F1 (agent-HIGH → Claude-assessed MEDIUM) — missing-cash doesn't show its "subtracts 0.0" formula line
`fundamentals/mapper.py` `_assumed_zero_component` (cash-missing path in `_map_net_debt`). When cash is missing, the component is built with `contribution_musd=0.0` / `formula_sign=1`; the provenance renderer guard `if contribution and contribution != value:` (`serve/fundamentals_provenance.py:~172`) is falsy for `"0.0"`, so the "subtracts X MUSD in formula" line is omitted. Present-cash correctly shows "subtracts 200 MUSD".
- **Why only MEDIUM, not HIGH:** the cash component IS still shown and explicitly marked `MISSING_ASSUMED_ZERO`, so the user is told cash was treated as zero — the computed net debt is correct and the role is disclosed; only the redundant "subtracts 0.0" formula line is missing for this edge case. Not wrong behavior; minor completeness gap.
- **Fix (Codex's, good):** in the missing-cash branch set `contribution_musd=-0.0` (stringifies distinctly) or render the contribution line unconditionally when the component participates in the formula. Trivial.

(The other 2 raw findings from the sweep were refuted on verification.)

## Attack-list results (all clear unless noted)

**1. Source-mode correctness — PASS.** `materialize_tool_b_finance_source` (`screening/pipeline.py`) **fails loud** (`ToolBStaleSchemaError`) when required `_official` columns are missing — no silent yahoo→our fallback. For `yahoo` it copies the genuinely pipeline-recomputed `_official` columns into the active ones (recompute, not relabel). Candidate Finder / Tool D recompute via `compute_tool_b_in_memory(finance_source=...)` (real recompute). `fundamentals_source=yahoo` is preserved through the window switcher, option-trading links, sizing forms, Back link, and save redirects (review-fix added these in `detail_panels.py`/`detail_page.py`/`detail_forms.py`). Source switch stays independent of the gold scenario.

**2. Tool B invariants — PASS.** `screening_verdict_official` is now produced (closing the gap from my plan review); `YAHOO_FINANCE_SOURCE_COLUMN_MAP` covers verdict, rank, checks (layer1/layer2), and all derived metrics. Incomplete rows (missing manual inputs) get `INCOMPLETE` verdict + `None` rank in the official path too (`pipeline.py:~427-428,497,531`), so Yahoo mode does not score incomplete rows. The stale guard requires both `_official` and `_our_view` columns (schema contract test added).

**3. Tool D semantics — PASS.** `finance_source` is threaded `ToolDExecutionInputs → compute_tool_d_outputs →` the internal Tool B recomputes. Production / AISC / sustaining-capex stay manual (correct — they are manual mining inputs, not source-switchable); debt/interest follow the selected source, so Yahoo Tool D uses Yahoo debt/interest (no manual fallback). Scenario/Yahoo provenance reflects the transient recompute, not the persisted Our-View run.

**4. Provenance — PASS (except F1).** Net debt discloses direct-total-debt vs split long+current; cash is a positive balance carrying `sign=-1` + `contribution_musd` (subtraction explained); interest is `value_origin="sign_normalized_yahoo_component"` (sign disclosed); zeros render (`is not None`, not truthiness); manual-only tax rate is not mislabeled as Yahoo-derived.

**5. Historical raw fundamentals — PASS.** Prior history resolves through the **published manifest + checksum** (`load_latest_fundamentals_fetch_manifest`, raises on checksum mismatch) — not a blind latest alias. Restatements tracked via `row_hash` identity (`HISTORY_IDENTITY_COLUMNS`). `period_type` in the raw schema; annual mapper stays annual-only. v1→v2 read-compatibility via defaults. (Restatement-preservation merge logic is the area I'd most want one more targeted test on — see residual risk.)

**6. Detail page / shared UI — PASS.** The window switcher (mine) and source toggle (Codex's) render together coherently and preserve each other's state. **No accidental edits in Claude-owned Tool A / window-label / scorecard / structural-table regions** — verified by diffing `detail_panels.py`; Codex touched only the agreed switcher source-preservation, its own snapshot panel, and option-trading link preservation. The shared `_render_window_switcher` integrated cleanly with my 5-window/"1Y" rewrite.

## Independent verification
- My independent run of the affected suite (candidate_finder_data/page, fundamentals_fetch/provenance, tool_b_pipeline/schema_contract, tool_d, workspace_app) = **184 passed** — green. Codex reported full suite **1488 passed, 1 skipped**, ruff + `git diff --check` clean.

## Residual risk
- **F1** (cosmetic, edge case) — fix is trivial.
- **Historical restatement preservation (5a):** the manifest/checksum path is solid; I'd add one explicit test that a changed value for an existing period is *kept as a new observation* (not overwritten) before relying on long-run history. Not a blocker for the source-mode current-view feature.
- This review covers behavior + architecture; it is not a live UI walkthrough — recommend the real-data screenshot at integration (Yahoo toggle × window switcher on one detail page).

**Bottom line:** integrate it. Fix F1 (1-line) when convenient; add the restatement test before the historical feature is surfaced in UI.
