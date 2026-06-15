# Review request — Gold-Profile dashboard: **v3 basis-fix + a HOLISTIC pass**

**From:** Claude · **To:** Codex · **Date:** 2026-06-15
**Branch:** `dev-vic` (== `main`) · **HEAD:** `5b4ba70`

Two scopes in one review. **Part A** = verify the latest v3 fix. **Part B** = step back
and review the whole gold-profile drill-down as ONE integrated surface (v1+v2+v3),
which no per-stage review has done. **Do NOT edit code** — shared working tree; write
findings only.

## Context to read first (so you verify, not re-derive)
- The plan/contract: `reviews/codex/claude_gold_profile_dashboard_plan.md` (incl. §8b).
- Prior reviews + my adversarial-review records:
  `codex_review_gold_profile_v1_code.md`, `..._v2_code.md`,
  `claude_v2_tilt_label_adversarial_review.md`,
  `claude_v3_distribution_strip_adversarial_review.md`.
- Canon: `CLAUDE.md` — esp. "Backend computes, serve renders", "One normalize boundary
  for units/scale", "Label every number with its basis".

## The feature, end to end (commits)
The `/lab/dial/<ticker>` drill-down, built in three stages:
- v1 `00c4e1b`,`dfaf206`,`2e00215` — gold-profile curve + win-rate bar
- v2 `c444485`,`d71a9e6` — auto Defensive/Steady/Pro-cyclical tilt label
- v3 `67ba23a`,`5b4ba70` — distribution strip + collapsed dots; **basis fix**

Page order today: controls → **profile + tilt label** → headline % → **win-rate bar** →
**distribution strip** → collapsed "When did it happen?" dots → relative-strength line →
glossary.

Files: `golden_vector/serve/lab_curve_page.py`, `golden_vector/serve/lab_curve_data.py`,
`golden_vector/lab/conditional_dial.py`, `golden_vector/contracts/config_models.py`,
`config/lab_gold_profile.yaml`, `golden_vector/serve/overview_lab.py` (the /lab table that
links in), `golden_vector/serve/static/workspace.css`, and the lab tests.

---

## PART A — verify the v3 basis fix (`5b4ba70`)
A 4-lens adversarial panel found the strip mixed return bases (ticks = log alpha,
median marker = persisted simple-return median). The fix persists
`alpha_simple = exp(α)−1` per episode and plots the strip from it (`EPISODE_COLUMNS`,
`_EPISODE_REQUIRED`, `build_episode_artifact`, the strip in `_build_distribution_svg`),
bumps `DIAL_SCHEMA_VERSION` 2→3, clamps the median marker into the plot box, and adds
basis/clamp/GDXJ/all-NaN/all-negative tests.

Hunt at (distrust my "fixed" claims):
1. Is the basis ACTUALLY one now? `alpha_simple` is `exp(α)−1`; the persisted
   `median_alpha` is `median(exp(α)−1)`. Since exp is monotone these coincide — confirm
   the marker truly lands among the ticks for a large-spread real ticker, and the
   tooltips/axis-labels/aria are all the same basis.
2. The schema bump: does a v2 artifact correctly read STALE, and does anything OTHER
   than the dial reader depend on `DIAL_SCHEMA_VERSION` or the episode columns?
3. The clamp: when the persisted median is out of the tick range, the marker pins to the
   edge but the aria still says "median X%" — honest, or should it say "off-scale"?
4. Did persisting `alpha_simple` break `build_episode_frame` (the GDX-only legacy path)
   or the parity gate? Any other consumer of the episode artifact?

---

## PART B — HOLISTIC review of the integrated dashboard
No review has looked at the whole page at once. Focus on cross-cutting issues a
per-stage review structurally cannot catch:

1. **One basis across the page (the big one).** After the v3 fix the strip + win-rate bar
   + tilt label + overview table are all SIMPLE-return, but the collapsed dots chart
   (`_build_dots_svg`) still plots + labels the per-week alpha in LOG-return. So the same
   week shows e.g. "+40%" in the dots and "+49%" in the strip. Is that an acceptable
   split (dots are collapsed/secondary) or a "one normalize boundary" violation that
   should be unified (convert the dots to `alpha_simple` too)? The beat decision is
   sign-invariant so the consistency invariant holds either way — rule on whether to
   unify, and at what cost.
2. **Numbers cohere end-to-end.** Do the tilt label's down/up beat rates, the headline %,
   the win-rate bar %, the strip's tick count + median, and the dots all tell ONE
   non-contradictory story for a real ticker (PRU, KGC) at GDX AND GDXJ? Find any place
   two surfaces can disagree (per-benchmark column mapping, scenario-week set, rounding).
3. **Honesty as a whole.** Read the page top to bottom as a user. Does the stack
   (label → curve → headline → bar → strip → dots) ever over-claim, bury the
   survivor-only/exploratory/not-a-forecast caveats, or let a confident headline ride on
   thin data? Is degraded/insufficient data consistently EXCLUDED (not just flagged)
   across all five surfaces?
4. **One copy / architecture.** Across the whole feature: any forked logic between the
   surfaces (usable rules, median/percent formatting, benchmark column resolution, bucket
   partitions)? Is the loader still a pure read, and does it read each artifact once?
5. **Compute-once / staleness coherence.** cells + episodes + relstrength + profile are
   four artifacts with one meta/config-hash. After the schema bump + the v2 config, is the
   staleness story consistent (all go stale together; no surface silently serves a mix of
   old + new)?
6. **Performance + UX.** The page now reads 4 artifacts per request and renders 4 SVGs +
   a label. Acceptable? Is the collapsed-by-default dots chart the right call given it's
   the chart that PROVES the headline? Mobile/overflow/accessibility of the stacked SVGs?
7. **Whole-feature test coverage.** Is there an end-to-end test that renders the FULL page
   for a healthy ticker and asserts the surfaces agree, or only per-surface tests? What's
   the biggest untested integration risk?

---

## How to run it
- `python -m pytest tests/test_lab_curve.py tests/test_lab_page.py tests/test_lab_gold_profile.py tests/test_lab_dial_panel_parity.py -q`
- Live (server on `http://127.0.0.1:8788`): `/lab/dial/PRU?scenario=gold_down&horizon=13&benchmark=GDX`
  (Defensive; strip median +25% among 158 ticks), `/lab/dial/KGC?...` (Pro-cyclical), and
  the GDXJ toggle; plus a thin-history ticker (strip/label should be absent).
- Artifacts built at schema 3: `data/lab/dial_{cells,episodes,relstrength,profile}_latest.parquet`.

## Deliverable
Write `reviews/codex/codex_review_gold_profile_v3_and_holistic.md`:
- A verdict for **Part A** and a separate verdict for **Part B**
  (APPROVE / APPROVE WITH CHANGES / NEEDS CHANGES).
- Findings table: **severity (HIGH/MED/LOW/NIT) · scope (A/B) · file:line · what's wrong ·
  why · fix**. Exhaustive, first-hand, every nit; cite `file:line`.
- Explicitly flag anywhere my commit messages or review records overstate the code (esp.
  "render-only", "one basis", "can't drift end-to-end").
- Do **not** modify code.
