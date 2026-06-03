Grade: READY

M1 status: shipped. `python main.py hedge-readiness` runs against current data and correctly emits the M1 context-alignment warning because local Tool A/B outputs are older than the latest options snapshot. That is not a blocker for M1.5.

## Re-Grade Summary

Plan v2 resolves the two v1 blockers. The new Speculation Candidates section in `reviews/codex/claude_m15_put_scenarios_plan.md:154` fixes the no-holdings use case by making the candidate-put workflow universe-level instead of holdings-dependent. `cli.py` is now in scope at `reviews/codex/claude_m15_put_scenarios_plan.md:103`, with `--sort-by`, `--quantity`, and `--max-tickers` specified at `reviews/codex/claude_m15_put_scenarios_plan.md:360`. The corrected Black-Scholes spot-zero behavior is explicit in §4b at `reviews/codex/claude_m15_put_scenarios_plan.md:413`, and low/negative down-beta handling is explicit in §4b bis at `reviews/codex/claude_m15_put_scenarios_plan.md:438`.

## Focus Findings

Speculation Candidates: READY. The selection rule is pragmatic: directly hedgeable first, cheap-IV first, capped for readability. Keeping held names in the speculation section is acceptable because the user is looking at a universe-level buying screen, not only portfolio hedging. If the report gets too long later, the `--max-tickers` flag is the right relief valve.

CLI Scope: READY. Adding `cli.py` to §2b resolves the prior scope mismatch. The fixed `--sort-by` choices are acceptable for v1 because they match the comparison schema and prevent typo-driven empty output.

Black-Scholes Spot Zero: READY. The §3 pseudocode still contains stale `spot <= 0 -> None` wording at lines 211-222, but §4b and step 1 clearly supersede it with the limit value `strike * exp(-rT)`. Treat §4b as authoritative during implementation and test the limit case.

Low Down-Beta: READY. Skipping scenario rows while still showing the candidate grid plus annotation is the right behavior. It prevents fake breakeven math while still revealing that listed puts exist.

Step Order: READY. The 9-step order is now coherent, and CHECKPOINT A after step 6 is the right stop: all pure math/selection modules exist before report and CLI integration.

## Implementation Notes

Do not add a new config field for the down-beta minimum unless the plan is updated; use the stated constant `0.10` for M1.5. Preserve ASCII in new report text even where the plan examples use symbols like beta or minus signs. No implementation should start beyond step 6 before CHECKPOINT A.
