# Codex — review the Phase 2 build plan (2Y/5Y Tool A windows) before build

**You are Codex, reviewing a model-layer build plan — not code yet.** Read
`reviews/codex/claude_phase2_tool_a_windows_plan.md`. This adds 2Y/5Y beta windows to the (already
shipped) Gold Sensitivity page; it touches **validated scoring code**, so review the design before I
build. Phase 1 (the serve refocus) is live on `main`.

## The decision to vet
The per-window beta math is driven by `ScoringConfig.structural_windows` — the SAME list the score/
rank consumes (it also keys `minimum_observations_<w>`, `StructuralWindowWeights`, the anchor, and
confidence). The plan's **Option B** keeps `structural_windows = [6M,12M,3Y]` (rank untouched) and adds
a separate `structural_display_windows = [2Y,5Y]` computed+persisted for display only.

## Verify first-hand + answer
1. **Is Option B (decoupled display windows) correct and clean**, or is there a reason 2Y/5Y should be
   full scoring windows? Check `model/structural.py` (`compute_structural_window_metrics`,
   `_build_vectorized_window_data`) — can it compute the display windows without routing them into
   `model/scoring.py`? Confirm scoring reads only `structural_windows`.
2. **The touch list** (config / structural / `ToolAOutputRow` + `TOOL_A_OUTPUT_COLUMNS` / benchmark
   betas builder / `serve/windows.py` + detail switcher / tests / artifact rebuild) — complete? missing
   anything (current-state contract, schema_version bump, candidate_finder, parity to live columns)?
3. **The rank-parity guard** (rank byte-identical before/after) — is that the right load-bearing test,
   and where should it live?
4. **5Y data scarcity** (AAUC.TO ≈2.8y, THX.L ≈5.0y) — is `window_status_5y` thin/unavailable handling
   sufficient, and does the serve mute logic already cover it?
5. **Labels/anchor** — reconcile showing 12M as "1Y" across overview+detail; keep 12M as the canonical
   anchor, or change it?

## Deliverable
Write `reviews/codex/codex_review_phase2_tool_a_windows_plan.md`: findings table + the Option-A-vs-B
call + answers above + verdict **SOUND TO BUILD** or **NEEDS CHANGES** (blocking list). Recommend; do
not edit the plan or code.
