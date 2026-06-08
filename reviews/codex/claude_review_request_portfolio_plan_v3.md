# Review request — Portfolio tool plan v3 (architecture + completeness)

**From:** Claude Code · **To:** Codex · **Type:** deep design/architecture review (NOT a build)

## Your task
Review the portfolio-tool **build spec, plan v3**, properly and first-hand. Critique it hard, find what's missing, propose better approaches where you have them, bring new ideas, challenge the decisions, and — above all — **make sure the architecture is the best it can be** before we build. This has already been through a 5-lens design panel (v2) and a 4-critic gap analysis (v3), so don't just re-confirm the obvious — go deeper, especially on architecture, and find what those passes missed.

## Read first-hand (don't skim)
- **The spec:** `reviews/codex/claude_portfolio_tool_plan_v3.md` (start here — this is what you're reviewing).
- **Background (optional):** `claude_portfolio_tool_plan_v2.md` (the reframe + design-panel rationale).
- **The code the plan reuses / touches:**
  - `golden_vector/hedge/portfolio_totals.py` (`compute_portfolio_totals` — the existing gold-drop scenario + totals + coverage engine the plan re-presents), `proxy_hedge.py`, `sensitivity_ranking.py`, `report.py`, `holdings.py` (the `Holding` model — no currency field today).
  - `golden_vector/ingestion/standardize.py` + `golden_vector/normalize/market_snapshot.py` (the FX/pence path). **Note: I just committed a pence fix at the snapshot path (commit `9d26270`) — Yahoo serves LSE in pence; it now divides `GBp` quotes by 100. The price-history path is still in pence (harmless today because Tool A uses returns).**
  - `golden_vector/serve/workspace.py` + `serve/overview_tool_d.py` (how tabs/pages are served; the `/hedge-readiness` endpoint that already emits real £ values).
  - `config/universe.yaml`, `config/benchmarks.yaml` (GDX/GDXJ are **benchmarks**, not Tool A subjects), and `.gitignore`.

## Context (what the tool is)
A **Portfolio tab** that **re-presents the existing `hedge/` engine** (served at `/hedge-readiness`) + adds composition/coverage, a reconciliation gate, and charts. Hedging is ONE section, not the whole tool. The real book ≈ 11 small/mid gold miners (~£270k) across AUD/CAD/GBP, mostly without liquid single-name options (GDX/GDXJ is the hedge path). The user, Emanuel, is a **beginner founder**: plain English, industry-standard recognized metrics only (no invented composites), "simplest thing that works", low duplication, fail-loud + auditable + versioned, backend-computed / serve-reads-only.

## What I specifically want from your review
1. **The 7 blockers (§2) — are they right, complete, and correctly ranked?** Did I miss any failure mode? For each, is my proposed fix the BEST approach or is there a cleaner one? Pressure-test in particular:
   - **B2 (notional formula):** is `notional_usd = local_shares × local_price × fx` correct, and where should the *authoritative current price* come from (the IBKR export's own local price, or our normalized data)? Any double-conversion risk I've missed?
   - **B3 (GDX benchmark-beta):** best way to compute + persist GDX/GDXJ's own gold-down-beta from the existing Tool A estimator **without polluting** the Tool A/B/C/D universe — a separate `benchmark_betas` artifact, or a flag on the Tool A run? Window-mismatch handling (benchmarks `period=max` vs universe 1y weekly)?
   - **B5 (two-stage reconciliation):** is "Stage 1 = re-value with IBKR's OWN prices+FX, gate on that; Stage 2 = live-priced, drift-labeled, non-gating" the right design, or is there a simpler honest gate?
   - **B6 (dual listings):** modeling holdings as broker LINES → value each to USD → group by universe ticker — does this interact badly with the existing `Holding`/`HoldingResolved` (which key on unique ticker and raise on dupes)? Better data model?
   - **B7 (privacy):** artifact gitignore + a non-loopback bind guard + a `portfolio_enabled` flag — is that the right serve-side protection, given `/hedge-readiness/latest.md` already serves real values off disk?
2. **Architecture — is the foundation right?**
   - Is **"re-present the existing hedge engine"** genuinely the best call, or does that engine have limits (it's built around a **markdown report**, not a data API) that make a clean Portfolio tab awkward? If so, what's the right boundary — a shared compute layer both the markdown report and the new HTML tab read from?
   - **Where should the portfolio computation live** — extend the existing hedge refresh step, or a dedicated `portfolio` CLI step? Sequencing vs Tool A/D + the new benchmark-beta step?
   - Are the **artifact schemas (§8)** right and complete? Is the **shared valuation helper** (`normalize/holdings_valuation.py` centralizing FX + pence) the right way to avoid two divergent currency implementations?
   - Sanity-check my **pence fix** (commit `9d26270`): is keying on Yahoo's case-sensitive `GBp` tag the right detection? Should the **history path** be fixed now too, or is deferring it genuinely safe?
3. **New ideas / cuts:** anything that would make this materially more useful for a beginner with a concentrated single-sector book — or anything in the plan to **cut** as over-engineering?
4. **Challenge the locked decisions** (USD base · P&L disabled stub · all 3 charts kept · overshoot hedge gated behind GDX). These are Emanuel's calls, but if you see a strong reason to revisit one, say so with the why — don't silently override.
5. **Hard rules + honesty bar (§6):** does the plan uphold the Golden Vector rules (no mixed-currency analytics without explicit normalization; no opaque composite scores; every transformation testable/versioned/auditable; raw-QA before scoring)?

## Output
Write your review to **`reviews/codex/codex_review_claude_portfolio_plan_v3.md`** — blocker-by-blocker and architecture-section by section, **every finding including nits**, each with a concrete proposed fix and any new design idea sketched concretely. Where you disagree with me, say so plainly with the reasoning so we can reconcile into a comparison table and then build.

## Working rules
- This is a **review** — do NOT build or change code, except the one exception (something literally crashes the app).
- Work on `dev-vic`. **Don't push** (Claude pushes). Stage **only** your review file — never `git add .` (there are sensitive/unstaged files in the tree).
- Independent of the option-signals market-hours validation + the LSE re-run (separate tasks); this review can proceed in parallel.
