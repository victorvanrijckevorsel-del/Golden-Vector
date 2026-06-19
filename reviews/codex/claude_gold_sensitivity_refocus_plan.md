# Gold Sensitivity refocus — "Gold Reactors" + horizon selector (plan)

Status: **PLAN / for discussion** (Claude). Nothing built yet. Captures the product redirect we
reached on 2026-06-18/19 after stress-testing the Lab.

## Why this redirect (the honest reckoning)

The core trader job is: **"quickly see which miners react strongly or weakly to gold."** We built a
lot of mathematically-sound machinery that does NOT serve that job, and we proved it the hard way:

- **Capture / convexity (the Lab behaviour engine)** is drift-contaminated — CMM looked "CONVEX, the
  dream" (0.28× down / 2.57× up) only because it folds the company's own multi-year growth into the
  "gold response" and uses a 9-year window. A clean beta shows it's actually low and roughly symmetric.
- **The periodicity blend idea** (mix 1wk/2wk/3wk betas) → noise: longer-interval returns are just
  the same weekly data repackaged into fewer, noisier observations.
- **The Dimson lagged beta** (the principled version of "combine horizons") → also noise: the lag
  terms are small/inconsistent and it's ~2× *less* stable across windows than the plain beta. These
  miners react to gold within the week.

**Conclusion: the simple, already-validated contemporaneous up/down gold beta is the right tool.** It
is drift-clean, stable, and it already passed the scorecard. The work is to *surface it well*, not to
invent a cleverer statistic.

## Decision 1 — Reframe the **Gold Sensitivity (Tool A)** page into a "Gold Reactors" view

A fast, scannable, sortable table — the answer to "who reacts to gold, up vs down, and can I trust it."

- **Lead with the stable 3-year up/down beta**; show the recent shift (12M vs 3Y) as a small ↑/↓/→
  arrow (the honest "is it changing?", without a separate noisy 12M column).
- **New "Gold-link (R²)" column = the master trust signal** — how much of the stock's movement gold
  actually explains. strong / moderate / weak / **none**. Stocks that barely track gold (e.g. CG, PRU
  at R²≈1%) are flagged **"barely tracks gold"**, not shown with a confident-looking beta.
- **Keep the existing column vocabulary exactly** (Victor 2026-06-19): **Gamma**, **Asymmetry**,
  **Confidence** (HIGH/MEDIUM), **Profile** (LOW_LINKAGE / FRAGILE / DEFENSIVE / …), **Volatility**
  (MODERATE_NOISE / HIGH_DOWNSIDE_RISK / HIGH_NOISE / LOW_NOISE). **Do NOT invent new words** — this
  supersedes the earlier "rename gamma → tilt / torque / fragile / balanced" idea. (Note: Profile's
  `LOW_LINKAGE` already encodes the "barely tracks gold" / low-R² honesty signal I'd proposed.)
- **Every column header carries the same "i" info-tooltip** that Gamma already has — plain-English
  description + a **FORMULA** box + a "Read more" link — applied **consistently to ALL columns**
  (existing ones AND the new beta / R² / horizon columns).
- **NEW — value-level "i" tooltips (Victor 2026-06-19, the main ask).** Clicking the "i" next to a
  *cell value* (LOW_LINKAGE, FRAGILE, DEFENSIVE, MODERATE_NOISE, HIGH_DOWNSIDE_RISK, HIGH/MEDIUM
  confidence, …) opens a little window explaining what that *value* means — exactly like the header
  "i". **Centralised + reuses the existing machinery** (the `help-popover.js` + the "i"-button
  renderer + `column_help.py`): add (1) a **value glossary** (term → meaning, one place), (2) a small
  `help_value(value)` helper that drops the same "i" button next to a known value, (3) wire it into
  the categorical cell renderers. **No new popup/CSS/JS** — only the glossary content + one helper +
  wiring. **General across all tabs** (Profile / Volatility / Confidence here, plus categorical values
  on B / C / D). UX: show the value "i" on cell hover (not 60 visible "i"s at once); same popup on click.
- Sortable on every column, neutral (both directions equally), with **GDX / GDXJ reference rows**.
- **Drop the "Gold Sensitivity Score" composite** (decided 2026-06-19, per the no-invented-composite
  rule). The raw betas + Gamma + Profile speak for themselves; no opaque blended score.
- **Presentation rebuild of `/tool-a` — no new math** (all numbers already in `tool_a_latest`).
- Thin/weak values are flagged, never dressed up (the opposite of the capture card's sin).

## Decision 2 — Horizon selector on **Gold Sensitivity (A)** and **Gold Downside (C)**  *(NEW — Victor 2026-06-19)*

Let the user choose the lookback the betas are measured over, via a **fixed set** of windows:
**6M · 1Y · 2Y · 3Y · 5Y** (Victor 2026-06-19; 1Y = the existing 12M relabelled, 2Y and 5Y are new
computations to add to Tool A). The selector picks which window the table/cards
show and rank by — consistent control across both gold pages (the per-stock detail page already has
6M / 12M / 3Y).

- **Gold Sensitivity (A): cheap.** Betas are already pre-computed at 6M / 12M / 3Y in `tool_a_latest`
  (`up_beta_6m/12m/3y`, `down_beta_*`, `r_squared_*`, `weeks_*`). The selector is a serve/UI change —
  no new math.
- **Gold Downside (C): needs a model change first.** `tool_c_latest` currently stores only the *core*
  blended down/up betas + one `downside_volatility_52w` — **not** multi-window downside betas. So a
  horizon selector on C requires computing + persisting multi-window downside betas (and their R² /
  confidence / sample size) before the UI selector can exist. Sequence C **after** A.

### Deliberately NOT doing
- **No horizon selector on Corporate Finance (B) or Corporate Resilience (D).** Those are point-in-time
  fundamental snapshots (EV/EBITDA, net debt, AISC, FCF yield) — there is no trailing window behind
  them, so a horizon control would be a meaningless category error. Consistency = "same control where
  it applies," not "on every page even when it does nothing."
- **No free-form / custom date range.** Two reasons: (1) it breaks compute-once→persist→serve (betas
  are pre-computed at fixed windows; arbitrary windows force live regression in the request path);
  (2) more importantly it invites **window-shopping** — sliding until a stock looks good — the exact
  cherry-picking self-deception we've fought all along. Fixed windows are a discipline. If 3 feels too
  few, add a couple more *fixed* ones (1Y / 2Y / 5Y).

## Decision 3 — Park (don't delete) the speculative layer

For this goal, **park the Lab capture / convexity / behaviour-trend engine + the Phase 5 backtest.**
Keep **Tool C downside** (validated) and the **scorecard framework** (proven). The frozen Phase 5
spec stays on record (`claude_phase5_behaviour_backtest_spec.md`) but is not the priority; if we ever
want it, it's ready and the acceptance bar is co-signed.

## Honesty rules carried into this design
Lead with the stable/validated number; always show fit/confidence (R²); flag thin/weak data loudly;
no opaque composite scores; descriptive, not a forecast.

## Codex review applied (2026-06-19) — corrected scope & refinements
Codex verdict was NEEDS-CHANGES; corrections folded in:
- **My "5-window selector is cheap" was wrong.** Tool A stores ONLY 6M/12M/3Y and `ScoringConfig`
  hard-validates `structural_windows == ["6M","12M","3Y"]` (pipeline, `ToolAOutputRow`,
  `benchmark_comparison`, the detail switcher, and tests are all 3-window-shaped). So **2Y/5Y is real
  model/schema/config/test work**, split out below.
- **Default window** = **12M (1Y)** — the existing canonical anchor (matches the detail page); the
  selector toggles windows, so **the selector itself is the "is it changing?" mechanism** → drop the
  inline recent-shift arrow (avoids a forecast-y reading; Codex guardrail).
- **Trust = R² *band* + weeks + window_status together**, not R² alone; low-fit / low-status rows
  **sort + display as weak evidence** (reuse `LOW_LINKAGE` / rank-ineligible), not just a warning.
- **Value-tooltip cell contract (Codex MED, blocking):** the "i" button must NOT pollute the cell's
  search/sort text → emit clean `data-search` / `data-order` (raw value) with the button outside the
  searchable text; **accessible on keyboard + touch (NOT hover-only)**; escape via the existing helper;
  glossary content kept consistent with `model/labels.py` + `model/explanations.py`. Add render-level
  DataTables-filter tests for Profile/Confidence/Volatility after value-help is added.
- **GDX + GDXJ reference rows** — same window, benchmark-styled, excluded from miner ranks/counts,
  hidden/degraded when benchmark status != OK.
- **Shared window resolver** — one helper used by the Tool A overview, detail page, and benchmark
  comparison; do not add another hard-coded window list.
- **5Y is not universal** (e.g. AAUC.TO ~2.8y, THX.L ~5.0y of history) → explicit unavailable/thin
  handling for the 2Y/5Y windows.
- Architecture: selector **reads persisted fields only** — no regression computed in the `/tool-a` or
  `/tool-c` request path; 2Y/5Y (A) and windowed C must publish persisted artifacts + update the
  current-state contract.

## Sequencing & complexity (revised)
1. **Phase 1a (serve-only, cheap — start here):** reframe `/tool-a` + horizon selector for **6M / 1Y /
   3Y** (1Y = the stored 12M), default 1Y; drop the composite score; lead with the selected window's
   up/down beta + R²-band + weeks/status; GDX+GDXJ reference rows; **shared window resolver**. Reuses
   existing `tool_a_latest` columns — no model change.
2. **Phase 1b (serve, mostly content):** value-tooltip system — central glossary (consistent with
   labels/explanations) + `help_value()` with clean `data-search`/`data-order` + accessible + tests.
3. **Phase 2 (model change):** add **2Y / 5Y** windows to Tool A via centralized config + output
   columns + `ToolAOutputRow` + benchmark betas + detail switcher + current-state contract + tests +
   5Y thin/unavailable handling → extend the selector to the full 6M/1Y/2Y/3Y/5Y set.
4. **Phase 3 (model change):** persist windowed down/up betas (+ R²/weeks/status/confidence) in Tool C,
   add C descriptive-not-forecast copy, then add the horizon selector to **Gold Downside (C)**.

## Decisions (Victor 2026-06-19)
1. **Window set = 6M · 1Y · 2Y · 3Y · 5Y** (1Y = old 12M; 2Y & 5Y new). ✓
2. **NO tab renames anywhere — all 5 tabs keep their current names.** The page is *already* displayed
   as "Gold Sensitivity" (internal route `/tool-a`); nothing changes. "Gold Reactors" is only an
   internal nickname for the redesigned *table*, NOT a new tab name. ✓
3. **Keep existing column words**; add the "i" info-tooltip to every **column** AND to every
   categorical **value** (the centralised value-glossary, see Decision 1). ✓
4. **Drop the "Gold Sensitivity Score"** composite. ✓

## Still open
- GDXJ reference row alongside GDX? (assumed yes unless told otherwise)
