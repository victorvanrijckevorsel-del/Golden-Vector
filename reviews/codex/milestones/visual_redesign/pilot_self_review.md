# Phase 3 pilot self-review (2026-08-10)

Serious first-hand review of the six pilot migrations before continuing
autonomously (per the approved Q4 decision). Verdict at the end.

## What each pilot got

| Pilot | page_header | notices (10.5 tones) | table regions | buttons | other |
|---|---|---|---|---|---|
| Candidate Finder | yes (+lead) | screen warning → warning | top-list cards + both ranking tables (legacy `table-scroll` deleted) | Apply=primary, Reset=tertiary | Screen Builder heading → section_heading with action slot |
| Corporate Finance | yes (+lead incl. gold basis) | saved→success, override errors→danger, scenario/Yahoo→info | main comparison table | Apply=primary, Reset=tertiary | — |
| NEM detail | yes (+back-link class) | flash→success, error→danger | via containment fallback (see below) | 4 form submits classed | deep panels/lenses complete in Phase 5 |
| Option Trading | yes (+snapshot lead) | context warnings → warning | screening + liquidity tables | Apply=primary | Method details → shared disclosure; empty state shell |
| Lab overview | yes (+lead) | artifact broken→danger / absent→warning; caveat→info; thin banners→warning/info | dial table | Apply=primary | tone mapping consults existing status branches only |
| Lab drilldown | yes | broken→danger, unknown-scenario/empty→warning (no rebuild advice on URL typos, unchanged) | charts already semantic (Phase 1) | — | — |
| Portfolio | yes (+disabled empty-state) | flash→success, error→danger | 8 top-level tables wrapped | Add=primary, Save=secondary, Delete=danger, CSV=secondary | fixtures only; nested lots tables untouched (D11) |

## Documented component exceptions (before other pages copy them)
- **Candidate Finder builder criteria table**: form-layout table, narrow, stays
  inside `candidate-criteria-groups` without a region (a focusable scroll
  wrapper around form controls adds noise, width is bounded).
- **Portfolio nested lots tables**: inside the positions DataTable's rows —
  wrapping them is D11 restructuring territory, deferred post-Phase-8.
- **`model_state_banner` / option freshness box**: shared across every page;
  migrates with the Phases 4–5 status-strip work so all pages change at once.
- **Panel containment fallback** (`tables.css`): panels/`two-column` cells get
  `min-width:0; overflow-x:auto` so bare tables not yet region-wrapped can
  never push the page sideways. Verified safe for floating layers (help panel
  attaches to `<body>`). Phase 5 replaces reliance on it with real regions on
  the deep detail panels.

## Problems found during the gate, and what was done
1. **/ticker/NEM body overflow at ≤1024px** (334px at 400w): windows table,
   verification table, and >width form inputs. Fixed with the containment
   fallback + `table input/select { max-width:100% }`. Re-probed: 0px at all
   four widths. (Phase 0 baseline shows the pre-redesign page also overflowed —
   this is strictly better, not a regression.)
2. **D11 fired in the gate** (Portfolio DataTables alert): first run raced the
   MCP dialog queue; re-ran with the documented `window.alert` stub. Alert list
   captured as evidence; defect stays open by design.
3. **Contract diff**: clean — see `pilot_contract_diff.md` (four delta classes,
   flash text byte-identical, active-nav booleans identical).

## Checks against the plan's exit gate
- Reusable patterns established: header/notice/region/buttons/disclosure/empty state — yes, all six pilots share them.
- No body overflow at target widths: yes, after fix (0px on all six pilots × four widths, and at 200% zoom).
- Targeted route/form/query/DataTables/chart tests green: 227 + 174 + per-pilot suites, all green (see commit messages).
- Sanitized evidence: measurements JSON + 3 non-Portfolio screenshots; no Portfolio content committed.
- GET read-only: 0 of 18,253 artifact files changed across the whole browser gate.

## Honest residuals
- Detail deep panels rely on the containment fallback, not per-table regions (Phase 5 scope).
- `.two-column` overflow containment means very narrow columns scroll internally rather than stack below ~unknown widths; responsive stacking for two-column grids is Phase 6 hardening.
- Scorecard, Tool A/C/D not yet migrated (Phases 4–5) — they render fine on the dark shell via legacy aliases.

**Verdict: pilots match the approved guide and plan → continue autonomously to Phase 4.**
