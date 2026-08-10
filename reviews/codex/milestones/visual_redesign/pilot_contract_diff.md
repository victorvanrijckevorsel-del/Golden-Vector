# Phase 3 semantic contract diff — baseline vs contracts_after_phase3.json

Generator: `tests/tools/redesign_baseline_contracts.py` over the same fixture-backed
apps as Phase 0. 31 routes; route sets identical; statuses and content types identical.

Every differing field falls into exactly four classes, all intended or pre-existing:

1. **Navigation class strings** (all routes): `nav-tab` / `nav-tab active` →
   `nav-link` (+ `aria-current`). The extractor's computed `active` boolean is
   IDENTICAL before/after on every route — active-state logic is preserved,
   only the class vocabulary changed (Phase 2 shell).
2. **Flash class strings** (pilot routes): `flash` / `flash flash-warning` →
   `flash notice notice-<tone>` per plan 10.5. The extracted TEXT of every
   flash is byte-identical. Tones applied: CF screen warning → warning; Lab
   not-built → warning; Lab drilldown missing-episodes → warning; Tool B Yahoo
   view → info; Portfolio saved → success.
3. **Unmigrated shared banner**: the Portfolio "Model build state needs
   attention" flash keeps bare `class="flash"` — `model_state_banner` is
   migrated with the shared-status work in Phases 4–5, not in the pilots.
4. **Fixture nondeterminism, not UI**: Portfolio lot ids
   (`/portfolio/lots/<uuid>/…` form actions) and the model-state
   `generated_at_utc` timestamp differ because the extraction fixture rebuilds
   artifacts per run. Form/control STRUCTURE is identical.

No form control, table, heading, help-count, or route-status delta exists
anywhere else. Verdict: **presentation-only, contract-preserving**.
