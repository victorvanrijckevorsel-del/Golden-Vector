# Complementary review of Phases 1–4 (post-Codex closure) — 2026-08-12

- Reviewer/decision-maker: Claude (per Victor's brief: complementary lenses only, authority to fix)
- Base reviewed: `d3b1a8a` (ranges 4d97fb9..c976b9d, ..ff5582d, ..ea9d44e, ..d3b1a8a)
- Method: three parallel first-hand review agents (cross-phase integration seams; complete user
  journeys + operational behavior against REAL artifacts; test quality + duplication) plus a
  direct screenshot judgment vs mock/original. Prior phase reviews used as the coverage map —
  their resolved findings were not re-litigated.
- Fixes: two sequential waves (A: 11 items, B: 16 items), each spec'd by the reviewer,
  implemented by a coding agent, diff-verified, then gated together: **772 passed** across the
  23 affected suites (0:07:03). Ruff clean.

## Deliberately NOT re-reviewed (already covered by prior rounds)
Phase-isolated correctness/edge cases, fault-injection matrix, fractional-dial mechanics,
sub-cent/count chart cases, browser viewport matrix, per-phase test counts — see
`phase1_review_merged.md`, `phase2_dual_source_gate.md`, `phase3_shared_ui_primitives.md`,
`phase4_ticker_reference_implementation.md`.

## Verdicts by lens
- **Dual-source data spine: clean under attack.** Composite-key selection verified at every
  serve reader; real manifest generation coherent (61+61 rows, schema v4, immutable, atomic);
  scheduled refresh proven to publish dual-source (19:32 artifact); stale rows excluded from
  ranks (all 12 stale-Yahoo tickers rank=nan); legacy v3 honest under the v4 reader.
- **Dial contract chain: clean** — every JS-read selector occurs exactly once in the real
  Phase 4 markup; payload arithmetic re-derived and reconciled exactly.
- **Currency chain: clean** — no inferred currency anywhere; price chart withheld without a
  declared basis.
- **Visual result vs mock: direction achieved** (identity/command bar, controls, density,
  truthful Yahoo hybrid basis, mobile semantic column).

## Findings fixed (27 items, waves A+B)
Severity mix: 1 P1 (missing producer→consumer integration test + renderer source tripwire),
4 P2 (beta-window tabs dropped chart/options/lab state via a hand-rolled query string — found
independently by two lenses; Python↔JS formatter divergence at rounding ties + four
unimplemented JS units; indexed table vs tooltip disagree at .x5 ties; two finance-source
normalizers with opposite contracts while `/tool-b` still emits an `official` link), and ~22
P3/polish: ticker page + Finder degrade instead of 500 on malformed Tool D artifacts;
Portfolio/Lab now behind the same schema guard as other readers; reporting form's
blank-nulls-fields hazard (proven live, data restored byte-exact from backup, then fixed to
blank-means-unchanged + clear checkboxes); humanized "Missing: …" inputs on degraded
resilience; internal-token strings reworded; duplicate spot/basis price collapsed when equal;
`US$` vs `$` vs ISO unified; empty-branch basis line dropped; statement-period rows added to
Data quality; shortened Performance basis strip (detail moved into the chart-data disclosure);
coarse-pointer help-icon overlay excluded inside sortable headers; dead `.data-number`
utilities deleted (dead-selector guard un-blinded); shim/markup drift synced; five stale
pre-Phase-4 test assertions adjudicated (all stale, none regressions — one was Phase 4
*fixing* a false `aria-current`); node-driver codepage + signed-zero test bugs; full-page
composition test with a live dial; end-to-end dual-source sentinel test.

## Deferred (named, not silent)
- **Five line-metric spot cells render "needs the gold dial (JavaScript)" server-side** (P2,
  pre-existing since M3). Correct fix = five persisted `spot_*` columns in the gold-response
  contract (producer already computes them) — a versioned contract change requiring the full
  suite; scheduled as its own change at the Phase 5 boundary.

## Phase 5 carry-overs
`/tool-a` window tabs share the fixed hand-rolled-query root cause (`serve/windows.py:148`);
cross-surface degraded-resilience wording unification (ticker vs `/tool-d`); series
checkboxes+legend merge; page-title vs command-bar identity de-dup; ~35 Phase 4 assertions pin
incidental markup (accepted cost — update deliberately when Phase 5 restyles).

## Record corrections
`phase3_shared_ui_primitives.md` corrected in place: the `.button-like` compat mapping did
restyle the `/tool-b`//`tool-d` gold chips (deliberate improvement; markup unchanged).

## Incident disclosure
While probing the forms journey, a review agent's partial POST to `/ticker/NEM/reporting`
succeeded against the real store and nulled two omitted fields (that behavior is itself the
finding fixed in wave A). The row was restored byte-exact from
`manual_screening.sqlite3.bak.2026-04-24`, corroborated by the CSV mirror and the pre-POST
Tool B artifact; verified net data change: none.
