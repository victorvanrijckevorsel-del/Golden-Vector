# Plan: distribution strips in "Compare on your own terms" + leaderboard ranked list

Status: DRAFT — awaiting Victor's go (scope questions answered 2026-08-14).
Author: Claude. Reviewer: Codex.

## What Victor asked for (decisions already made)

1. **Distribution strips**: to the right of each metric row in the Compare
   section, show where every miner in the universe sits for that metric — the
   same rug-of-ticks + highlighted subject dot as the existing beta strip
   ("Down beta — weeks gold fell (1Y)", `_build_beta_strip_svg`).
2. **Scope** (Victor chose): Compare section **and** the Corporate finance
   section rows, so every percentile on the ticker page reads the same way.
   NOT the Candidate Finder.
3. **Axis** (Victor chose): **actual values**, not percentile positions — so
   clustering/outliers are visible, exactly like the beta strip.
4. **Interaction** (Victor chose): static, like the beta strip. Note: the
   existing strip component already gives hover-identification for free (each
   tick carries a wide hit-area + `<title>` with "TICKER · value", plus the
   collapsed data-table equivalent for keyboard users). We keep that.
5. **Ranked list** (Victor chose): leaderboard style — rank, ticker, score,
   horizontal bar sized by score, subject row highlighted.

## Key facts from the tree (verified 2026-08-14)

- The percentiles artifact **already persists `raw_value`** per
  (ticker, finance_source, metric_key) — `contracts/ticker_page.py`
  `PERCENTILES_COLUMNS`. So no new *source* data is needed.
- But the artifact does **not** persist plot positions or the universe
  min/max domain. Canon: **backend computes, serve renders** — serve may not
  map value → 0..1 fraction (that is arithmetic; the Tool-D static-scan
  guardrail would rightly fail it). The beta strips solved this the same way:
  the model computes `_position` (clamped 0..1) and serve only maps
  fraction → pixel.
- `_build_beta_strip_svg` (`serve/charts.py:163`) is beta-specific in naming
  and label format but structurally exactly what we need (track, rug ticks,
  hover titles, subject marker + label, domain end labels, data-table
  fallback). **Generalize it, never fork it** (one copy of everything).
- `score-builder.js` is parity-locked on its **arithmetic** (mirror + fixtures
  + node execution in `tests/test_ticker_page_js_parity.py`). The DOM
  construction (`renderRankedList`) is not part of the fixture expectations —
  restyling the list is safe provided the math functions are untouched.
- The contributions list already has the bar pattern we want
  (`sb-bar-track` / `sb-bar` with width-as-data inline style) — reuse those
  classes for the leaderboard bar. Sign colours live in the stylesheet.
- Corporate section (`ticker_page/corporate.py`) shows values in tables today;
  its catalog metrics (margin_pct, aisc_margin_yield, ev_ebitda, forward_pe,
  leverage_trailing, aisc, reserve_life, survival_distance, fragility) all
  have percentiles rows.

## Design

### D1 — model: persist strip geometry (the only backend change)

Add to the percentiles artifact (contracts + `model/ticker_page.py` builder):

- `strip_pos` (float64, 0..1, clamped like the beta `_position`): this row's
  raw_value mapped into the metric's universe domain. Null when the row is
  unavailable or rank-ineligible.
- `universe_min`, `universe_max` (float64): the domain — min/max `raw_value`
  across rows that are BOTH `metric_available` AND `rank_eligible` for that
  (metric_key, finance_source). Same value repeated on every row of the
  metric (the artifact is long-format; this mirrors how `eligible_peer_count`
  already works). Null when fewer than 2 eligible values (a strip with no
  spread is not drawn).

Rules, matching canon:
- Only eligible+available rows shape the domain and get ticks — degraded rows
  are **excluded, not down-weighted** (they simply are not on the strip).
- A single-value or empty domain ⇒ nulls ⇒ serve renders no strip for that
  metric (honest absence, no fake spread).
- No new thresholds; nothing configurable here.
- Artifact rebuild required (pipeline percentiles step). Publish is
  all-or-nothing as usual; readers resolve via the manifest.

### D2 — serve: one shared strip component

Generalize `_build_beta_strip_svg` into a metric-agnostic
`build_distribution_strip_svg` in `serve/charts.py`:

- Marks become (ticker, formatted_value_label, position) — the *caller*
  formats values with its unit rules (serve formats, never computes).
- Beta call sites (behaviour section) migrate to the general builder with
  their existing labels/benchmark ticks — behaviour strips must render
  byte-identical or near-identical (assert at render level).
- Keep: rug hover `<title>`s, subject marker + "TICKER value · Nth
  percentile" label, domain end labels, `data_table_id` text equivalent.
- Compare/corporate strips pass no benchmark ticks (GDX/GDXJ betas are a
  behaviour-section concept).
- Compact variant (height/width) for in-row use, via parameters — one
  builder, two sizes, no fork.

### D3 — Compare section strips

- `compare.py` `_metric_row_html` gains a strip cell on the right (per
  Victor's sketch), server-rendered from persisted columns only:
  ticks = peers' (`strip_pos`, `raw_value`), subject = its `strip_pos`,
  label = "TICKER raw_value · Nth percentile" using the percentile that
  matches the metric's **default** direction (`pct_high_good` when
  `default_high_good`, else `pct_low_good`). The strip is static and does
  not follow the direction toggle — the axis and ticks don't move with
  direction anyway; only the wording of "good" does, and that lives in the
  toggle + help entries. (Called out for Codex: cheap to revisit later if
  Victor wants the label to flip live.)
- Unavailable metric ⇒ no strip (the row already shows the reason).
- Peers' strip data comes from the same frame pass `_peer_entries` already
  does — extend it, don't add a second scan. The strip needs peers that are
  eligible for the *metric* even when the payload cell is null for scoring —
  it does not: same eligibility rule (available AND rank_eligible), so the
  strip population and the scoring population are identical. One rule.
- Layout: CSS grid addition to the `sb-metric` row; strips wrap under the
  controls on narrow screens (`max-width:100%`).
- The 19 SVGs are server HTML — no new JS, no payload growth beyond the
  strip columns already being read.

### D4 — Corporate section strips

- The corporate tables gain the same compact strip beside each catalog
  metric's value cell, same component, same data source (percentiles rows
  for the page's finance_source). Metrics without percentiles rows render
  exactly as today.
- Wording/help: reuse existing help keys; add none.

### D5 — leaderboard ranked list (JS + CSS only)

In `score-builder.js` `renderRankedList` (DOM only, math untouched):

- Each ranked `li` gains a `sb-bar-track` + `sb-bar` whose width is
  `display_score`% — the score is already 0..100 by construction (weighted
  average of percentiles), so width IS the score, no new arithmetic beyond
  the same `formatNumber(x, 1) + "%"` presentation the contributions bars
  already use.
- Row layout: `#rank  TICKER  ▬▬▬▬▬▬  score  [tied]`, subject row keeps
  `is-subject` and gets the highlighted treatment; unranked rows keep their
  note and get no bar.
- CSS in the ticker-page stylesheet using existing design tokens (the
  contributions bar tokens); `test_design_tokens.py` stays green.
- DOM contract header comment in the JS updated (roles unchanged; only inner
  structure of list items grows).

## What this does NOT do (non-goals)

- No Candidate Finder change (Victor's scope answer).
- No new hover behaviour beyond what the existing component ships.
- No dial interaction — the whole Compare section stays "at spot".
- No change to scoring/rank/stability math; parity fixtures untouched.
- No new config thresholds.

## Test plan (blast-radius scoped)

- `tests/test_ticker_page_compare.py`: strip present for an available metric;
  **exclusion test** — an otherwise-healthy subject with one degraded peer
  row: that peer has no tick while a healthy control peer does; no strip when
  domain is null; direction-default percentile label asserted at render
  level.
- New/extended model test: `strip_pos`/`universe_min`/`universe_max`
  computed correctly incl. ties and NA values; single-value domain ⇒ null.
- `tests/test_ticker_page_js_parity.py`: full suite green (node layer proves
  the JS still runs; fixtures unchanged by construction).
- Behaviour-section render test: beta strips still render with benchmarks +
  subject label after the component generalization.
- Corporate render test: strip beside a catalog metric; absent when no row.
- Serve-arithmetic static-scan guardrails stay green (no arithmetic added to
  serve).
- Real-run check: rebuild percentiles via the pipeline, load NEM's page,
  confirm per-step seconds/rows self-report.

## Order of work

1. Contracts + model columns + model tests → rebuild artifact.
2. Generalize strip builder; migrate behaviour call sites; render tests.
3. Compare-section strips + tests.
4. Corporate-section strips + tests.
5. Leaderboard list (JS DOM + CSS) + render tests.
6. Self-review loop (build → review → fix), then Codex review of this file's
   delta vs what shipped.

## Open items for Codex review

- Is repeating `universe_min`/`universe_max` per row acceptable vs a separate
  per-metric table? (Chosen for consistency with `eligible_peer_count` and to
  avoid a new artifact.)
- Static direction-default percentile label on the strip vs following the
  direction toggle live (deliberately deferred).
