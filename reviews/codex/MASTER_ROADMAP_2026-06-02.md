# Master Roadmap — Three-Milestone Hedge Product (2026-06-02)

**Author:** Claude Code
**Date:** 2026-06-02
**Scope:** This is the master sequencing document for three coordinated milestones that together complete the hedge-readiness product surface.

---

## The three milestones

| Milestone | Goal | Estimated Codex work | Status |
|---|---|---|---|
| **M1.5 v5** — Slim with all Codex blockers fixed + M1 cleanups | Complete the CLI hedge-readiness report: Sensitivity Ranking entry point, all 4 existing modules wired into report.py, Portfolio Totals, Strategy-generic math layer, clean CLI flags | ~18-22 hours | **Plan being written today** |
| **M2** — Workspace UI for hedge-readiness | Add a sortable, filterable `/hedge-readiness` web page mirroring the CLI report; interactive "hedge $X of ticker Y" form | ~10-12 hours | Plan to be written while Codex implements M1.5 |
| **M3 basic** — Tool C v1 ranking pipeline | New `tool_c_latest.parquet` pipeline with three downside metrics (down-only beta, tail conditional loss, relative weakness vs GDX) + CLI command + workspace overview page | ~10-15 hours | Plan to be written after M1.5 ships |

**Total:** ~40-50 hours of Codex work across the three milestones.

---

## Sequencing and dependencies

```
TODAY                          LATER                          FINAL
─────                          ─────                          ─────

M1.5 v5  ────[ships]────►  M2 Workspace UI  ────[ships]────►  M3 Tool C v1
   │                            │                                │
   │                            │ depends on M1.5 ┐               │
   │                            │ section-data layer             │
   │                            │ (the section-builders          │
   │                            │  → emitter refactor)           │
   │                                                              │
   │                                                              │
   └─── M1 H1/H2/H3 cleanups folded in ────────────────────►  M3 ranking
                                                              uses M1 cleanups
```

**Hard dependencies:**
- M2 requires M1.5's section-builders-to-emitter refactor (the architectural seam I called out in `CODE_REVIEW.md` §"Extensibility")
- M3 reads `tool_a_latest.parquet` (existing) + GDX/GDXJ history (already fetched in M1)
- M2 and M3 can ship in either order after M1.5

**Soft dependencies (nice-to-have ordering):**
- M2 ships before M3 so the new tool_c overview page has a UI pattern to copy from M2's `/hedge-readiness` page
- M3 ships after M2 if Codex wants to validate the section-builders pattern in M2 before applying it to Tool C's overview

---

## Why "Big build today" = M1.5 v5

When Emanuel said "I want to start building a really big part today", the right answer is M1.5 v5 because:

1. **It's the foundation for M2 and M3.** Without M1.5's section-builders/emitter seam, M2's workspace UI would duplicate every renderer. Without M1.5's clean math layer, M3's Tool C ranking would need to re-derive scenario math.
2. **Codex already built half of it.** The hedge subpackage has scenarios.py, comparison.py, header_context.py, speculation_section.py from earlier work — they just aren't wired into the report.
3. **It's substantial.** 18-22 hours of Codex work = real progress, but contained in one milestone with three checkpoints, not three milestones with nine checkpoints.
4. **The plan blockers Codex flagged are all addressable in v5.** None require rewriting M1; they're all about plan-document consistency.

M2 and M3 are big *next* — but they need M1.5 v5 first.

---

## What goes in each milestone

### M1.5 v5 (TODAY's build target)

**New code:**
- `golden_vector/hedge/sensitivity_ranking.py` — universe-wide sort by `down_beta_12m`
- `golden_vector/hedge/portfolio_totals.py` — total portfolio downside per gold scenario + hedge cost cards
- `black_scholes_call_price()` in `golden_vector/features/black_scholes.py`
- `OptionStrategy` enum + 4-case P&L sign rules in `golden_vector/hedge/scenarios.py`

**Major edits:**
- `golden_vector/hedge/report.py` — wire 4 existing modules + 2 new modules into the report; reorder sections per M1.5 v5 §2j
- `golden_vector/cli.py` — add `--comparison-sort-by`, `--ranking-sort-by`, `--quantity`, `--max-tickers` (CLEAN separation, no overload)
- `golden_vector/contracts/config_models.py` — add `default_scenarios`, `default_scenario_quantity`, `protection_levels`, `optionability_tier_min`, `max_tickers_speculation_section`
- `config/hedge_readiness.yaml` — populate the new fields

**M1 cleanups folded in:**
- H1: flip cross-sectional IV sort to ascending (cheap first)
- H2: implement proxy basis-risk 3-tier OR document 2-tier as intentional
- H3: wrap each ticker's options ingestion in try/except

**Architectural seam (essential for M2):**
- Split `render_hedge_readiness_report` into pure data builders (returning typed dataclasses per section) and a markdown emitter

**Acceptance:** `python main.py hedge-readiness` produces a markdown report with all 8 sections (header / sensitivity ranking / portfolio totals when holdings / per-position scenarios when holdings / speculation candidates / cross-ticker comparison / proxy hedges / run summary), all CLI flags work cleanly, 446 → ~480 tests passing.

### M2 Workspace UI for hedge-readiness (after M1.5)

**New code:**
- `golden_vector/serve/overview_hedge_readiness.py` — new overview page
- `golden_vector/serve/hedge_readiness_lens.py` — new detail-page lens for `?lens=hedge-readiness`
- `golden_vector/serve/hedge_readiness_html.py` — HTML emitter for the same section data M1.5's markdown emitter consumes

**Major edits:**
- `golden_vector/serve/workspace.py` — register the new route + lens
- `golden_vector/serve/page_shell.py` — nav link
- `static/workspace.css` — minor styles for the new page

**Optional add-on:** "Hedge $X of ticker Y" interactive form (uses the same scenario math but with user-supplied dollar amount → contracts).

**Acceptance:** open `/hedge-readiness` in the workspace, see sortable DataTables of all 8 sections, drill into a ticker via `/ticker/AEM?lens=hedge-readiness`.

### M3 basic Tool C (after M2)

**New code:**
- `golden_vector/model/tool_c.py` — Tool C pipeline orchestration
- `golden_vector/features/gold_regime.py` — gold-down regime identification (worst-N%-of-rolling-window)
- `golden_vector/features/relative_weakness.py` — stock-vs-gold-vs-GDX during gold-down weeks
- `golden_vector/ingestion/persist_tool_c.py` — parquet writer

**Major edits:**
- `golden_vector/cli.py` — `tool-c` subcommand
- `golden_vector/serve/overview_tool_c.py` — new overview page
- `golden_vector/contracts/config_models.py` — `ToolCConfig`
- `config/tool_c.yaml` — thresholds

**Out of scope for M3 basic:** Tool D (fragility ranking) — comes in a separate later milestone.

**Acceptance:** `python main.py tool-c` produces `data/output/tool_c/tool_c_latest.parquet` with rank, down_beta_core, tail event averages, relative weakness vs GDX, sample-size confidence flags. `/tool-c` workspace page renders the ranking.

---

## Today's path forward

1. **Right now:** I'm writing `claude_m15_v5_plan.md` (the slim-but-complete M1.5 with every Codex blocker fixed and M1 cleanups folded in). Will hand off to you in ~30 min.
2. **You send M1.5 v5 to Codex** for re-review. Codex should grade READY this time (or maybe READY WITH MINOR CHANGES — much smaller).
3. **Codex implements M1.5 v5** while I write M2 and M3 plans in parallel.
4. **M1.5 v5 ships,** you push to main per the CLAUDE.md workflow.
5. **Codex picks up M2** from the plan I write today.
6. **M2 ships,** then **Codex picks up M3**.

Total wall-clock: probably 3-5 days of Codex work depending on how fast each milestone goes through its review cycles.

---

## Risks and tradeoffs

- **M1.5 v5 is the biggest single milestone we've ever attempted** (~18-22 hrs). Three checkpoints help, but if the architectural seam refactor is harder than expected, M2 timing slips.
- **The section-builders refactor is structural.** Done right, M2 + M3 are easy. Done wrong, every future product surface duplicates renderer logic. Worth getting right in M1.5.
- **M3 basic Tool C uses Tool A's existing `down_beta_core`** for the basic sort. A richer Tool C (CVaR-style, full asymmetry composite) is a future enhancement, not in M3 basic.
- **Plan-writing budget today:** ~3-4 hours of Claude time to write M1.5 v5 plus the two M2/M3 plan stubs. Reasonable.
- **All three plans need Codex review.** I'll write tight v1 drafts and let Codex catch what I miss before each implementation begins.
