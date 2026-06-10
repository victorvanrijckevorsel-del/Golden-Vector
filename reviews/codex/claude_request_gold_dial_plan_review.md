# Request to Codex — review the gold-dial + auto-pull fundamentals PLAN

**This is a PLAN REVIEW, not coding.** Read `reviews/codex/claude_gold_dial_and_fundamentals_plan.md` and write your review to `reviews/codex/codex_review_claude_gold_dial_and_fundamentals_plan.md` with a clear verdict (APPROVE / READY WITH CHANGES / NEEDS REWORK) and severity-ranked findings (HIGH / MEDIUM / NIT), each citing the real `file:line` it concerns. Be honest and critical — if something won't work or is underspecified, say so and propose the fix. **This is read-only and can run now, in parallel with the Phase 6 commit** (different files).

Ground every finding in the actual code — verify the plan's claims against the repo, don't trust them.

## PRIORITY 1 — build it in the BACKEND (Emanuel's explicit ask)
- Confirm the plan keeps as much as possible in the backend with serve only rendering. Flag anywhere it would push gold/EBITDA/ratio arithmetic, ranking, or the `coalesce(official, our-view)` resolution into serve or templates.
- Confirm the gold dial reuses the SINGLE Tool B model (no forked gold math) and Tool D's existing `compute_tool_d_outputs(gold_price=G)` override pattern (in-memory, no persist, presets, provenance, instrumented), not a parallel copy.
- Confirm the dual-layer resolution (Official vs Our view) and the "compute every ratio twice" logic live in the model layer, persisted/computed backend-side, serve reads only.

## PRIORITY 2 — will it actually work (fatal gaps / forgotten pieces)
- **Dual-store data model (§B4):** is `fetched_fundamentals` (official) + the user's overrides layer + the existing `source_verification` table sufficient? Is the migration of today's MIXED `company_inputs` (financials + operational inputs) into official / our-view / operational-single-source safe and reversible? What happens to the values already entered by hand?
- **Spot default (§A1)** depends on the staleness fix — confirm spot gold is resolved from the FRESH foundation everywhere, no other resolution site missed. (Phase 1 staleness is now shipped.)
- **Ranking determinism (§2/§A6):** are the existing tie-break rules in Tool B / Candidate Finder reusable for live re-rank, or will the dial jitter? Name the exact sort/tie-break code. Tool A betas must NOT move with the dial — confirm that boundary is real.
- **The Candidate Finder spot-gold guardrail** (`candidate_finder_data.py:809`) — does defaulting the saved run to spot + allowing dial-driven non-spot runs break its assumptions?
- **Auto-pull mapping (§B1/§B2):** are the yfinance fields (`.income_stmt` / `.balance_sheet` / `.cashflow`) named and reliable as assumed? Net-debt / EBITDA derivation correct? Currency/units (the LSE-pence family) for foreign names handled at the ONE standardize boundary, not ad-hoc?
- **The three axes (gold price dial × forward-vs-trailing rank basis × Official-vs-Our-view) compose** — are there incoherent combinations that should be DISALLOWED, and is the control bar sane (the §B6 UX note)?
- **The §4a / §B3b discipline is implementable:** degraded/stale/missing auto-pulled financials must be FLAGGED **and EXCLUDED** from confident headlines + rankings (the H1 lesson), thresholds single-sourced in config (M1), per-item degrade (M3). Confirm the plan's hooks for these are real, not hand-wave.

## PRIORITY 3 — general depth
Anything forgotten; any contradiction with the shipped completion plan; any test gap; any architecture-guardrail violation; any ambiguity where two engineers would build it differently. Is Phase A or B too big for one PR — suggest a split. Nits too.

## Context
- The plan's two product decisions are LOCKED (Emanuel, 2026-06-09): normalized gold = trailing 3-yr average (auto, config-overridable); ranking layer = a toggle (Official | Our view) driving display + sort. Don't re-litigate these; review the design *around* them.
- Build order after approval: **Phase A (the gold dial) first** (ships independently, fixes the EV/EBITDA confusion), then **Phase B (auto-pull)**.

Do NOT start implementing. Review only. When your review is written, ping Emanuel — Claude will patch the plan for your findings, then hand off Phase A to build.
