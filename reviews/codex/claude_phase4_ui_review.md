# Phase 4 review record — /lab/dial Behaviour panel (serve)

Date: 2026-06-17
Method: adversarial multi-agent workflow (3 dimensions — serve-correctness, serve-honesty/no-arith,
tests-edge — each finding independently verified). 14 agents, 11 confirmed findings (1 HIGH).

## Resolutions

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | HIGH | Null archetype round-trips from Parquet as float `nan` (truthy) -> renders a confident bold "nan" box (unconfirmed/thin shown as settled) | `_row_for_keys` now normalizes NaN -> None for every loaded behaviour field; the renderer also uses a NaN-safe `_present()` guard for the archetype badge. Regression test feeds a real `float('nan')` row and asserts no "nan" box + the abstain branch fires. |
| 2 | MED/LOW | `_load_behaviour` discarded per-frame `_load_frame` statuses -> a corrupt/missing frame under a valid meta read as an evidence gap ("no history") | Per-frame statuses aggregated: any non-None -> `behavior_status = "CORRUPT"` (whole panel degrades to the rebuild hint). Test corrupts one frame under a valid meta and asserts CORRUPT. |
| 3 | MED | Capture multiples (down/up/convexity) shown confidently even when `capture_status` is THIN/INVALID | The capture card now reads `capture_status`; a non-OK status shows a "⚠ a side is too thin or invalid to rely on" caveat. Test added. |
| 4 | LOW/NIT (×2) | Convexity (a difference of two multiples) rendered with a "×" suffix | New `_beh_signed` formats it as a signed number (e.g. `+2.28`); test asserts `convexity <strong>+1.50</strong>`. |
| 5 | MED/LOW | Peer card showed raw overlapping event count as bare `N=` (overstates evidence) | Now shows `~N independent episodes` from the persisted `peer_effective_n` (the page's effective-N convention). |
| 6 | NIT | 13w archetype box beside 8w peer/trend cards without explanation | Added a one-line hint that the box is grounded at the default capture horizon, independent of the page look-ahead. |
| 7,8,9 | MED/LOW | Tests passed by accident (no positional/convexity/peer-direction asserts); no THIN-status test; no LOADER tests (staleness fail-closed, off-default-horizon selection, corrupt frame) | Rewrote `test_lab_behaviour_panel.py`: positional capture/peer asserts, convexity assert, NaN regression, thin-caveat, MISSING/STALE/CORRUPT degrade, and real loader tests (capture@13 vs peer/trend@page-horizon selection, stale-hash fail-closed, missing meta, corrupt-frame). |

## Verified live (port 8766)
- CMM.AX (confirmed CONVEX): box + "Takes 0.28× of gold's fall · 2.57× of its rise · convexity +2.28".
- AAUC.TO (THIN_DOWN): "not enough independent history to place a box" + thin caveat; no nan-box.
- ALK.AX (unconfirmed): "DEAD_WEIGHT (not confirmed by the independent-episode cross-check)"; no nan-box.

ruff clean; panel + guard + curve tests green; full suite gating before commit.
