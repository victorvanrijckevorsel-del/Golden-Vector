# Codex — review the Gold Sensitivity refocus PLAN (design/product, not code)

**You are Codex, reviewing a product + UI plan — not an implementation.** Read
`reviews/codex/claude_gold_sensitivity_refocus_plan.md` in full. Nothing is built yet; judge whether
the plan is sound, honest, feasible on the existing code, and correctly scoped. Do NOT file "X isn't
implemented" — that's the point of a plan.

## Context you need
The plan is a redirect: after stress-testing the Lab, the simple, already-validated **up/down gold
beta** (Tool A) is the right "which miners react to gold" tool; the capture/convexity/behaviour-trend
+ Phase 5 layer is parked. The plan reframes the **Gold Sensitivity** page (`/tool-a`) into a
scannable table, adds a **horizon selector** to Gold Sensitivity (A) and Gold Downside (C), and adds
**value-level "i" tooltips**.

## Verify these factual claims first-hand (they drive the plan's effort estimates)
- **Tool A already stores per-window betas** — `up_beta_6m/12m/3y`, `down_beta_*`, `r_squared_*`,
  `weeks_*` in `tool_a_latest.parquet` (so the A horizon selector is presentation-only). Confirm.
- **Tool C does NOT store windowed downside betas** — only a blended `*_core` + `downside_volatility_52w`
  (so C needs a model change to add 6M/1Y/2Y/3Y/5Y downside betas + their R²/weeks before its selector
  can exist). Confirm in `tool_c_latest` / `golden_vector/model/tool_c.py`.
- **The "i" tooltip machinery is reusable for cell values** — `golden_vector/serve/column_help.py`
  (the `ColumnHelp` registry + the "i"-button renderer with `data-help-*` attributes) and the shared
  `help-popover.js` already power the header tooltips. Confirm a value-level glossary + a `help_value()`
  helper can reuse this with **no new popup/CSS/JS**, only content + wiring. Check `overview_tool_a.py`
  + `model/explanations.py`/`labels.py` for where the categorical values (LOW_LINKAGE, FRAGILE,
  DEFENSIVE, MODERATE_NOISE, HIGH_DOWNSIDE_RISK, …) are produced.
- **Tool B / Tool D are point-in-time snapshots** (no windowed columns) — so a horizon selector is
  meaningless there. Confirm.

## Review dimensions
1. **Strategic soundness** — is "lead with the validated contemporaneous up/down beta; park the
   capture/convexity/Phase 5 layer" the right call? Any value being thrown away?
2. **Table redesign** — leading with the stable 3Y beta + a recent-shift arrow + an R²/"gold-link"
   trust column + keeping the existing vocabulary (Gamma/Asymmetry/Confidence/Profile/Volatility) +
   dropping the composite score. Honest? Useful? Anything misleading (e.g. the recent-shift arrow,
   the down-side thin-data handling)?
3. **Horizon selector** — is the A-cheap / C-needs-compute split right? Is "fixed set 6M/1Y/2Y/3Y/5Y,
   NO custom range (window-shopping risk), NOT on B/D" the correct scope? Any data-availability issue
   (do all names have 5Y of weekly returns; is 6M down-beta too thin to offer)?
4. **Value-tooltip system** — is the centralised approach (one value glossary + `help_value()` +
   reuse help-popover) genuinely low-effort and correct? Any gotcha (sorting, accessibility, the
   `data-help-*` contract, escaping, mobile/hover)? Is a glossary the right single source of truth, or
   should value meanings come from `model/explanations.py`?
5. **Honesty / architecture** — compute-once→persist→serve respected (no request-time regression)?
   Does the down-side stay honestly flagged when thin? Any one-copy/duplication risk?
6. **Anything missing.**

## Deliverable
Write `reviews/codex/codex_review_gold_sensitivity_refocus_plan.md`: a short findings table
(severity | area | issue | why | fix), answers to the dimension questions (esp. the feasibility
confirmations and the C model-change scope), the **GDXJ-reference-row** call, and a final verdict —
**SOUND TO BUILD** or **NEEDS CHANGES** (with the blocking list). Recommend; don't edit the plan.
