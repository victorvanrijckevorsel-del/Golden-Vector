# Review request for Codex — options-review fixes + site-wide ⓘ help + concise notes

Branch: `dev-vic` (pushed). Diff against `main`. Full suite: **1255 passed**, ruff clean.

Please review first-hand and write findings to `reviews/codex/codex_review_options_ui_and_completion.md`.
Agent fan-out is welcome. The horizon selector (Part A of
`claude_option_overview_horizon_and_ui_plan.md`) is **NOT built yet** — it is the next
step after this review, so it is out of scope here.

## What changed (commit groups on dev-vic)

**A. Codex options multiagent-review fixes** (`9652af9`, `0876832`, `a85e83c`, `ff0fb1b`,
`7bf8ed3`, `6021603`, `c2448f3`, `245745c`, `931a13b`, `8ba09d4`) — your review's findings:
- H2 all-or-nothing option publish (stage run-stamped → persist history → flip aliases last).
- H5 activity "confirmation" → "volume pulse" (Emanuel's call: keep volume detection, drop
  the positioning-confirmation framing).
- M2 most-liquid default must be candidate-backed; M4 option freshness MISALIGNED when
  alignment warns; M7 corrupt manifest-resolved finder source → friendly 503; M8 skip
  diagnostic contract-metrics on serve; M9 drop never-populated OI-change fields; M10 BS
  zero-dividend disclosure; M11 feature-snapshot schema contract; M12 optionability =
  chain coverage clarification; L2/L3/L4/L5/L6.
- **Deferred with reasons (please opine):** H1 short-term guard shipped (fail-loud feature
  loader) but the full run-stamped feature artifact is deferred; H3 done; **M1** (mixed-
  refresh option build) left as a *visible warning* rather than a hard-block — it conflicts
  with a deliberate warn-and-publish design + ~25 tests; CLAUDE.md's "exclude not flag"
  canon leans toward block, so this is a real call for Emanuel — your read welcome. **M5/M6**
  (pre-compute candidate-finder scenarios / persist option scenario ladders) deferred as
  milestone-sized; for a local single-user tool the bounded request-time compute is
  acceptable.

**B. Site-wide ⓘ click-to-explain** (`00a72f5`, `eff8b7a`, `a122052`) — wire every plain
table `<th>` across all 9 workspace pages to the one central registry
(`golden_vector/serve/column_help.py`, now 158 entries):
- Option overview, Tool A/B/C/D, Lab, Candidate Finder, ticker detail, Portfolio.
- Reuse existing keys where the concept matches; new entries carry meaning / calculation /
  direction; config-driven thresholds resolve **live** via callables (no hardcoded numbers).
- **Highest-priority check: explanation ACCURACY — verify the direction ("higher/lower is
  better") and meaning of each entry against the code that computes the column.** An
  inverted direction is the cardinal sin here. I already ran an adversarial pass (all clean)
  and hand-verified the one flag (`tool_d_cost_curve`); please re-verify independently.
- **Pre-existing question for your opinion:** `cost_curve_aisc_percentile` is computed with
  `oriented_percentile(..., high_good=True)` (so low AISC → low percentile = cheaper) while
  `config.tool_d.quality_components["cost_curve_aisc_percentile"] == "low_good"`. The ⓘ text
  matches the *displayed* value (low percentile = cheaper). Is the orientation vs the
  `low_good` config intended in the quality-rank combination, or a latent model bug? (Out of
  scope to fix here; flagging for your read.)

**C. Concise notes** (`eebe887`) — new `collapsible_text_td()` (in `format_helpers.py`):
short text inline, long/multi notes collapse behind a `<details>` summary (full text
retained, HTML-escaped). Applied to option overview Notes, Tool C tags, portfolio hedge Note.

## What to scrutinize
1. ⓘ explanation accuracy (directions/meanings vs code) — every page.
2. Central-registry discipline: no hardcoded threshold numbers in text; reuse not duplication;
   `test_every_thresholds_callable_resolves_against_real_config` still green.
3. Backend-computes / serve-renders boundary held for the new serve code (no analytics in
   serve; the new guardrails + existing ones still pass).
4. Concise-notes helper: full text always retained, escaping correct, no row-render breakage.
5. Any regression in the option-publish (H2) staging order or the freshness (M4) MISALIGNED path.
