# Codex Final Confirm - Claude Option Signals Plan v2

**Grade: READY WITH MINOR CHANGES**

V2 resolves the v1 blockers: sector-relative 25-delta skew is now the headline, OI is confirmation rather than "flow," signal artifacts are explicit, stale quotes fail closed, history has a retained store and a minimum-sample rule, interpretation is asymmetric, and the scheduler is split out of Milestone 1.

## Default Thresholds Accepted

- Sector-relative skew residual: `+/-0.03` IV points. Positive means downside puts are richer than the sector reference; negative means calls are richer.
- Signal-area quote coverage: `60%` minimum, measured only on 45-150 DTE contracts with 10-35 delta, sane IV, and nonzero underlying.
- Minimum signal-area contracts before judging stale coverage: `4`.
- IV-rank minimum history: `20` clean daily snapshots per ticker.
- Activity confirmation: side volume/open-interest at least `10%`, and at least `1.5x` the opposite side.

## Minor Implementation Refinement

For Milestone 1, the fail-closed publish blocker should be keyed to stale benchmark ETF signal coverage (GDX/GDXJ), because those chains are the sector-relative reference and the market-hours canary. A stale or untradable single-name row should be marked unavailable (`STALE_QUOTES`, `LOW_LIQUIDITY`, or `SPARSE`) without blocking the entire universe from publishing. If GDX/GDXJ are stale, the build should fail before publishing signal artifacts or advancing model state.

## Build Scope Confirmed

Build Milestone 1 only: persisted four-lane signals, artifact contracts and migration, sector-relative skew, signal-area stale guard, retained daily history with `LIMITED_HISTORY` until the sample threshold, overview heatmap columns, and per-ticker signal card plus sector-skew overlay. Do not build the scheduler, row-level carry-forward, or volatility-surface modeling in this milestone.
