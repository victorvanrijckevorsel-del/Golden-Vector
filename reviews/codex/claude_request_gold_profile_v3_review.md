# Review request — Gold-Profile dashboard **v3 (distribution strip + collapsed dots, as shipped)**

**From:** Claude · **To:** Codex · **Date:** 2026-06-15
**Branch:** `dev-vic` (== `main`) · **Commit:** `67ba23a`

## What I need
A first-hand review of the **v3** drill-down changes as shipped in `67ba23a`: a new
"spread of outcomes" distribution strip, and collapsing the dense week-by-week dot
scatter under a `<details>` toggle. v3 is a RENDER-only / visual stage (no new math
or decision), so review it for serve-purity, honesty/consistency, edge cases, and
test quality — match rigor to that risk, but distrust my "render-only / can't drift"
claims specifically.

**Do NOT edit code.** We share one working tree; concurrent edits clobber. Write
findings only; I reconcile and apply.

## Context
- The dashboard plan: `reviews/codex/claude_gold_profile_dashboard_plan.md` (§5
  "Distribution: 1-D strip ... avoid serve-side binning"; §8 v3 staging).
- v1/v2 are already reviewed + shipped (`reviews/codex/codex_review_gold_profile_v1_code.md`,
  `..._v2_code.md`). v3 sits on top.
- Canon: `CLAUDE.md` — esp. "Backend computes, serve renders" and the serve
  no-arithmetic guardrail.

## Scope (exact) — all in `golden_vector/serve/lab_curve_page.py`
- `_render_distribution(curve)` — the new strip section (guards: benchmark
  insufficient / < 2 scenario weeks)
- `_build_distribution_svg(scenario_points, *, median, benchmark)` — the 1-D strip
  SVG (ticks per scenario week at x = alpha, zero baseline, persisted median marker)
- `_render_chart_a(curve)` — now a collapsed `<details>` instead of an open
  `<section>`
- `_render_lab_curve_page` — the page flow (strip inserted after the win-rate bar,
  before the collapsed dots)
- `golden_vector/serve/static/workspace.css` — `.lab-dist-svg` + the `<details>`
  summary styling
- `tests/test_lab_curve.py` — the v3 tests

## The honesty contract v3 must hold
The strip is meant to be a PURE READ: each tick is a RAW persisted per-week `alpha`
(from `curve.points`, the same scenario weeks the headline + win-rate count), and the
median marker is the PERSISTED cell median (`median_alpha`), NOT recomputed in serve.
There must be NO binning / counting / averaging / quantile math in the page. The strip
must stay consistent with the rest of the page (same scenario-week set, same median).

## Hunt hardest at (and distrust my claims)
1. **Serve-purity.** Is the strip genuinely free of analytics? I use `min()/max()`
   over the alphas for the x-axis scale and read the persisted median — is that the
   same "rendering geometry, not analytics" line the dots chart already draws, or is
   min/max-for-scale a smell here? Is the existing no-arithmetic guardrail
   (`tests/test_lab_page.py`) actually covering `_build_distribution_svg`, or does it
   need extending?
2. **Consistency / can't-drift.** The strip's tick set, the headline's "counted
   weeks", and the win-rate bar's median all claim to be the same data. Verify the
   strip uses exactly the headline's scenario-week filter (`is_scenario` + finite
   alpha) and the win-rate bar's median column — find any path where they could
   disagree (e.g. median column mismatch per benchmark, GDXJ).
3. **Edge cases / divide-by-zero.** All-positive or all-negative alphas (does the
   zero baseline still land on-axis?); `lo == hi`; a NaN/None persisted median (marker
   suppressed?); exactly 2 points; a huge outlier squashing the rest; NaN alphas
   excluded. Find any crash or misleading geometry.
4. **The collapse.** The dots chart is now `<details>` (collapsed by default). Does
   hiding the chart that PROVES the headline's beat-rate weaken the page's honesty,
   or is the summary + retained captions enough? Are the honesty captions (hindsight
   grouping, overlap, pending forward window) all still present?
5. **Accessibility / wording.** Strip aria-label + tick `<title>`s correct for both
   GDX and GDXJ? Caption honest (counted history, not a forecast)?
6. **Tests prove behavior.** Could any v3 test pass by accident? Is the
   persisted-median assertion actually distinguishing a persisted value from a
   recomputed one? Is the collapse pinned (a regression to an always-open section
   would fail)? Anything material untested (e.g. all-negative spread, GDXJ strip)?

## How to run it
- `python -m pytest tests/test_lab_curve.py tests/test_lab_page.py -q`
- Live (server on `http://127.0.0.1:8788`):
  `/lab/dial/PRU?scenario=gold_down&horizon=13&benchmark=GDX` — the "Spread of
  outcomes" strip (median +25%, 158 ticks) sits above the collapsed "When did it
  happen?" dots. Also check GDXJ and a thin-history ticker (strip should be absent).

## Deliverable
Write `reviews/codex/codex_review_gold_profile_v3_code.md`:
- Verdict: APPROVE / APPROVE WITH CHANGES / NEEDS CHANGES.
- Findings table: **severity (HIGH/MED/LOW/NIT) · file:line · what's wrong · why ·
  fix**. Exhaustive, first-hand, every nit; cite `file:line`.
- Flag anywhere my `67ba23a` commit message overstates the code (esp. "no binning /
  can't drift / render-only").
- Do **not** modify code.
