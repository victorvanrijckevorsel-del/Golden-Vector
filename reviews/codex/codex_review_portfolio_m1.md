# Codex Review - Portfolio M1 In V4

Grade: READY WITH MINOR CHANGES

M1 is buildable. The v4 plan fixes the material v3 architecture issue: Portfolio is now a first-class persisted data product under `golden_vector/portfolio/`, and the serve layer reads artifacts instead of leaning on the hedge-readiness markdown report. That is the right boundary for real portfolio values.

The only minor design adjustment I am applying while building is to make `portfolio.enabled` a small config object with a safe default. The page and write endpoints can exist, but holdings-bearing content is gated behind that flag, and non-loopback binding is refused when portfolio is enabled. That keeps privacy explicit without blocking tests or existing local workspace startup.

M1 should stay narrow: manual lots, grouped positions, local P&L, USD book totals at current FX, immutable artifacts, checked readers, and a simple positions page. I am not building benchmark betas, history pence fixes, broker import, cash modeling, reconciliation, charts, or hedge sizing in this milestone.
