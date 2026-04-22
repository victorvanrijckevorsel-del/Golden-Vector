# Claude Code Review — Master Plan Findings

**Reviewer**: Claude Code
**Date**: 2026-04-22
**Target**: `reviews/codex/golden_vector_master_plan.md`
**Cross-checked against**: `AGENTS.md`, `CLAUDE.md`, `claude-python-rebuild-spec-gold-v1.md`, `codex-full-briefing.md`
**Mode**: Read-only. No code changes. No silent assumptions.

---

## 1. Findings

### P1-1: Tool B market-data dependency chain is ambiguous

**Sections involved**: Section 3 (End-State Architecture, "Shared backbone"), Section 8 (Phased Roadmap, Phase 6)

**What the plan says**: Phase 6 (Tool B) depends on "Phase 0 plus market inputs as needed." The Shared backbone row lists "raw ingestion" as shared infrastructure.

**Why it matters**: Tool B needs current share prices in USD, which requires both a price fetch and an FX conversion. Two interpretations exist and the plan doesn't pick one:

- **Option A**: Tool B reuses the shared backbone's latest raw equity prices and FX rates (from Phase 1/2). This means Phase 6 actually depends on Phase 1+2, not just Phase 0. The stated dependency is wrong.
- **Option B**: Tool B does its own lightweight "current snapshot" fetch independent of the historical time-series pipeline. This means the shared backbone isn't fully shared, and Tool B has its own ingestion path.

The friend's Excel tool treats share price and FX as manual inputs (columns E and F in Screening Data). The briefing says these should be API-sourced in the rebuild. But the master plan never specifies the mechanism.

**What needs to change**: Decide explicitly whether Tool B gets current market data from the shared raw pipeline or from its own snapshot fetcher. Update the Phase 6 dependency accordingly. If shared, the dependency is Phase 1+2, not Phase 0. If separate, add a "Tool B market snapshot" component to the architecture.

---

### P1-2: Tool B formula definitions are absent from the master plan

**Sections involved**: Section 5 (Contracts — Tool B output), Section 8 (Phase 6)

**What the plan says**: The Tool B output contract lists field names (forward PE, EV/EBITDA, FCF yield, etc.) but does not define how they are computed. Phase 6 says "Layer 1, Layer 2, scenario target prices, Tool B verdicts" without formulas.

**Why it matters**: The complete formulas exist in `codex-full-briefing.md` Appendix A, but the master plan does not reference them. An implementer following only the master plan would need to invent the earnings model. The rebuild spec (`claude-python-rebuild-spec-gold-v1.md`) explicitly excludes the friend's tool from its scope (Section "What this spec does not include"). So the only authoritative formula source is the briefing — but the master plan doesn't point there.

**What needs to change**: Either inline the Tool B formulas (Layer 1 gates, Layer 2 earnings model, 6 target price scenarios, verdict logic) into the master plan, or add an explicit reference: "Tool B formulas are defined in `codex-full-briefing.md` Appendix A. That appendix is authoritative for Layer 1, Layer 2, and target price computation."

---

### P2-1: Corporate actions handling is implicit, not explicit

**Sections involved**: Section 5 (Contracts — Raw equity daily), Section 7 (Historical Data Strategy), Section 11 (Assumptions)

**What the plan says**: The raw equity daily contract includes "adjusted close local." Section 7 states "Return price basis: Adjusted close." Section 11 says "Corporate-actions behavior should be confirmed on real examples."

**What the rebuild spec requires**: Section 6, item 8 lists "Corporate actions dataset (splits/dividends)" as a required base entity. The foundation gate requires "Corporate actions handling policy explicit."

**Why it matters**: The master plan implicitly handles corporate actions by using Yahoo's adjusted close (which bakes in splits and dividends). This is a valid choice, but it's never stated as a deliberate decision. The rebuild spec demands an explicit policy. An implementer might wonder whether a separate corporate-actions dataset is needed.

**What needs to change**: Add one explicit statement: "Corporate actions (splits, dividends) are handled by using Yahoo's adjusted-close prices, which already account for these events. No separate corporate-actions dataset is required for v1. The price basis (adjusted close vs raw close) is logged in run metadata."

---

### P2-2: `as_of_date` semantics are undefined for Tool B

**Sections involved**: Section 5 (Contracts — Tool B output)

**What the plan says**: Tool B output is keyed by `ticker, as_of_date, gold_price_assumption`. No definition of what `as_of_date` means for Tool B.

**Why it matters**: For Tool A, `as_of_date` is clear — it's the date from which you look backward across horizons. For Tool B, it's ambiguous. Tool B uses a mix of:
- Current share price (has a date)
- Manual inputs like AISC and production guidance (undated — from press releases at various times)
- A gold price assumption (hypothetical, not date-bound)

Does `as_of_date` mean the pipeline run date? The date of the share price? The date the manual inputs were last updated? An implementer would have to choose.

**What needs to change**: Define `as_of_date` for Tool B. Most likely: "the date of the market data snapshot used (share price, FX rate, market cap). Manual inputs are treated as current regardless of their original source date."

---

### P2-3: Tool B negative-value and edge-case handling is unspecified

**Sections involved**: Section 5 (Contracts — Tool B output), Section 9 (Failure Rules)

**What the plan says**: The QA checks list "incomplete manual mining inputs" but don't address computational edge cases in the earnings model.

**Why it matters**: Several Tool B formulas can produce invalid or misleading results:
- **Negative net income** → negative EPS → negative Forward P/E. The verdict logic (`FwdPE < 8`) would pass for any negative P/E, which is nonsensical.
- **Negative EBITDA** → EV/EBITDA is meaningless or negative.
- **Negative FCF** → negative FCF yield. The FCF target price formula divides by peer FCF yield, which produces a negative target price.
- **Zero shares** → division by zero in EPS.

The friend's Excel handles some of these with IF guards (e.g., `IF(AND(K5<>"",K5>0), ...)`) but the master plan doesn't specify this behavior.

**What needs to change**: Add edge-case rules for Tool B computations. At minimum:
- Negative net income → Forward P/E = N/A, verdict cannot be STRONG CANDIDATE
- Negative EBITDA → EV/EBITDA = N/A, EV/EBITDA target price = N/A
- Negative FCF → FCF yield and FCF-based target prices = N/A
- Zero or missing shares → skip the ticker with INCOMPLETE status

---

### P2-4: Tool B `confidence` field is referenced but never defined

**Sections involved**: Section 5 (Contracts — Tool B output, Manual input files)

**What the plan says**: Tool B output includes a `confidence` field. Manual data rules state "Verification status must flow into Tool B confidence fields." The source verification CSV includes status values.

**Why it matters**: The implementer needs to know the domain of `confidence` and how it's computed. The friend's AISC Verification sheet uses statuses like "verified" and "estimated." But `confidence` in the output could be a per-field flag, a per-ticker aggregate, an enum (HIGH/MEDIUM/LOW), or a numeric score. Not defined.

**What needs to change**: Define the `confidence` values and computation. Suggestion: enum with `VERIFIED` (all critical inputs have verified sources), `ESTIMATED` (some inputs are estimated/unverified), `INCOMPLETE` (required inputs are missing).

---

### P2-5: Codex briefing collaboration workflow is stale relative to CLAUDE.md

**Sections involved**: Cross-document check — `codex-full-briefing.md` Section 9 vs `CLAUDE.md` Codex collaboration section

**What the briefing says**: Section 9 describes the old workflow: "Claude Code builds features/fixes on dev-vic → Claude Code writes milestone handoff → Codex audits and writes review → Claude Code fixes." It calls Codex a "review agent AND coding agent."

**What CLAUDE.md says**: Updated to "Both agents can build features and write code. Either agent can review the other's work." Codex is now a full implementation agent.

**Why it matters**: The briefing is listed as a "Must read" for Codex. If Codex reads the stale section, it might default to review-only behavior, contradicting `AGENTS.md` which says "You are an implementation agent."

**What needs to change**: Update `codex-full-briefing.md` Section 9 to match the current `CLAUDE.md` collaboration workflow.

---

### P3-1: Near-zero gold-return threshold has no default value

**Sections involved**: Section 9 (Failure Rules — Special handling)

**What the plan says**: "Near-zero gold-return rows are emitted but flagged as not eligible for official delta scoring using a threshold in `config/qa.yaml`." No default value provided.

**Why it matters**: Low impact — an implementer can pick a reasonable default (e.g., |GoldRet| < 0.001). But this is exactly the kind of "implementer makes a product decision" that the checklist warns against.

**What needs to change**: State a default: "Default near-zero threshold: |GoldRet_h| < 0.005 (0.5%). Configurable in `config/qa.yaml`."

---

### P3-2: Combined score and verdict formulas are deferred

**Sections involved**: Section 5 (Contracts — Combined output), Section 8 (Phase 7)

**What the plan says**: Combined output includes `combined_score` and `combined_verdict` but no formula. Phase 7 lists "combined score logic, combined verdict logic" as deliverables.

**Why it matters**: This is Phase 7, well after Tool A and Tool B ship independently. Deferring the formula is reasonable for an engine-first v1 — the tools are useful on their own. But the implementer will eventually need to decide how to weight Tool A score vs Tool B verdict.

**Action**: Acceptable to defer. Flag for Phase 7 design work.

---

### P3-3: Build-sequence numbering differs between master plan and briefing

**Sections involved**: Master plan Section 8 (Phases 0–8) vs briefing Section 7 (Phases 1–9)

**Why it matters**: Cosmetic. The master plan is more detailed and should be considered authoritative. But if someone reads the briefing's "Phase 6: Screening Tool integration" and the master plan's "Phase 6: Tool B standalone outputs," the scope is similar but the numbering and phase boundaries differ.

**Action**: No change needed to the master plan. The briefing should eventually note that the master plan supersedes its build sequence.

---

### P3-4: `compare-horizons` output format is unspecified

**Sections involved**: Section 3 (Runtime commands)

**What the plan says**: `python main.py compare-horizons --ticker NEM --horizons 5D,10D,3M` produces an "Exploratory comparison only."

**Why it matters**: Minor — the implementer needs to decide the output shape (table? CSV? chart?). Since this is exploratory and doesn't affect scoring, low risk.

**Action**: Add a one-liner: "Outputs a comparison table to stdout and optionally to CSV."

---

### P3-5: Incremental refresh strategy is not defined

**Sections involved**: Section 7 (Historical Data Strategy — Storage policy)

**What the plan says**: "Later runs should refresh incrementally where possible."

**Why it matters**: For v1, full backfill is fine. Incremental refresh is a performance optimization for later. But "where possible" is vague. Does it mean append-only? Re-fetch last N days? Full re-fetch with dedup?

**Action**: Acceptable to defer for v1. Note: "Incremental refresh design is deferred. V1 uses full re-fetch on each run. Cached Parquet files serve as the local store."

---

## 2. Residual Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Yahoo Finance rate limiting or symbol gaps on first 61-ticker backfill | Medium | Medium | Plan acknowledges this. Add retry logic and per-symbol error isolation in Phase 1. |
| `GC=F` gold symbol may have gaps or timezone issues | Low | High | Plan flags this for confirmation. Test early in Phase 1. |
| Manual mining data maintenance burden (61 tickers × 11 manual fields) | High | Medium | Inherent to the model. No mitigation beyond clear INCOMPLETE handling. |
| Peer benchmarks from "Operating Manual v2 Appendix B" are unverified | Medium | Medium | Plan stores them as config. Emanuel should confirm or update values before Tool B ships. |
| Adjusted-close basis may behave unexpectedly for some international tickers | Low | Medium | Plan flags for confirmation. Test on a few non-US tickers in Phase 2. |

---

## 3. Implementation Readiness

**Verdict: `READY WITH MINOR CHANGES`**

The master plan is well-structured, internally consistent on all major points, and faithfully implements the lessons from the rebuild spec. Tool A and Tool B independence is clearly designed. The horizon system (core vs custom with scoring eligibility flags) is solid. QA gates are explicit and the failure rules are strong enough to block false confidence. The phased roadmap is practical and the milestones are achievable.

The two P1 findings should be resolved before handing this to an implementer:
1. **Tool B's market-data source** — pick shared backbone vs independent snapshot and fix the Phase 6 dependency.
2. **Tool B formula reference** — either inline the formulas or add an explicit pointer to the briefing's Appendix A.

The P2 findings (corporate actions policy, `as_of_date` for Tool B, negative-value handling, `confidence` definition, stale briefing section) are real gaps but each has an obvious resolution. They could be fixed in 30 minutes of editing.

After those changes, the plan is implementation-ready. No product, architecture, or sequencing decisions would remain unresolved for the implementer.
