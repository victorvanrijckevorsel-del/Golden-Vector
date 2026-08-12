# Overnight run 2026-08-11→12 — bundled self-review record

**Scope reviewed:** every commit of the run (`eb6c261` Gate A, `06b5b5e` Gate B,
`c1ab14f` Gate C, `691ea63` rebuild, `ef7f0fb` M2/M3a) against the Codex
consolidated review's requirements. One bundled pass per Victor's instruction,
after per-gate targeted tests and before the single full-suite gate.

## Verified first-hand during the review pass

| Check | Result |
|---|---|
| C6 resolver on the REAL rebuilt artifact | Yahoo EV/EBITDA / fwd-P/E / leverage: 20/61 available; excluded rows carry real reasons (`CURRENCY_BASIS_MISMATCH` 19, `MISSING` 11, `STALE` 7). Our View unaffected (60/61). Manual mining fields keep 60/61 with basis "Our View mining assumption" under Yahoo mode. |
| Yahoo Tool D isolation on real data | 90 available rows before → 0 after, all with the exact approved reason. |
| Rebuild diff vs Codex's predictions | Match exactly: Tool C 57/61 rates changed (THX.L 12.28→5.26, TXG 23.75→18.75, CDE 28.57→24.71); WDO.TO flips the 15% screen as the review's worked example predicted. |
| Lab parity test | Red between Gate A and rebuild (expected, recorded in the Gate A commit); green again at the rebuilt artifact. |
| Real-data render smoke | All three new sections render gracefully against the live tree; loaders correctly report `PENDING_FIRST_PUBLISH` because tonight's ticker-page run is standalone/non-authoritative — the honest designed state until the real refresh publishes. |
| ruff | `ruff check golden_vector tests` — all checks passed. |

## Findings from the pass (and what was done)

1. **FIXED during run** — stage summary omitted the fx_attribution row count (cosmetic, fixed
   in `691ea63`).
2. **NOTED, deliberate** — layer1 still requires `sustaining_capex_musd` for completeness even
   though C1 removed every consumer. Kept so the rebuild diff stayed attributable to the
   formula alone; recorded in plan §16 for a deliberate decision later.
3. **NOTED, refinement** — the C6 Yahoo financial gate uses the rolled-up
   `financial_data_status`, which requires ALL dual-source official fields OK. Codex's text
   allows per-relevant-field granularity (EV/EBITDA needs only net debt + EBITDA). Current
   behavior fails CLOSED (safe: excluded + reasoned, never admits a bad row) but excludes more
   Yahoo rows than the minimum. Candidate refinement, not a correctness bug.
4. **NOTED, cosmetic** — a rejected-POST re-render of the ticker page omits the three new
   sections (route only passes `ticker_page_data` on GET). Error redisplay only; next M3 lane
   should thread it through.
5. **NOTED** — the model-state manifest still names the pre-fix generation. All new/rebuilt
   artifacts exist under `latest` aliases but the manifest-first loaders honestly refuse them
   until a real refresh publishes. This is the designed standalone semantics; the mandatory
   real refresh (Codex final gate 4) closes it.

## Remaining before Phase One acceptance (for Victor)

1. ONE real `python main.py refresh` at this pin (market hours for option v4), publishing the
   coherent five-artifact generation.
2. M4 batched browser/real-JS pass.
3. Remaining M3 lanes: mock-v3 page reorder + legacy section removals, gold-dial JS rework,
   options section rebuild, score builder, composite-prose sweep.
4. Deferred C10/C12/C13 + the C8 framework (plan §16, Victor-approved deferrals).
