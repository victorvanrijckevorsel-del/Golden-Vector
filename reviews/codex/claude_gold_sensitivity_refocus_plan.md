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
- **Tilt** (torque = rises more than falls / fragile = falls more than rises / balanced) shown **only
  when the gold-link is real**; never a verdict on a stock that doesn't track gold.
- **Drop the opaque "Gold Sensitivity Score"** composite (honours the no-invented-composite rule);
  rename "gamma" → plain "tilt".
- Sortable on every column, neutral (both directions equally), with **GDX / GDXJ reference rows**.
- **Presentation rebuild of `/tool-a` — no new math** (all numbers already in `tool_a_latest`).
- Thin/weak values are flagged, never dressed up (the opposite of the capture card's sin).

## Decision 2 — Horizon selector on **Gold Sensitivity (A)** and **Gold Downside (C)**  *(NEW — Victor 2026-06-19)*

Let the user choose the lookback the betas are measured over, via a **fixed, extendable set** of
windows (today 6M / 12M / 3Y; can add 1Y / 2Y / 5Y). The selector picks which window the table/cards
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

## Sequencing & complexity
1. **Phase 1 (easy, data exists):** `/tool-a` → Gold Reactors reframe **+ horizon selector (A)**.
   Presentation/serve only; reuse existing `tool_a_latest` columns.
2. **Phase 2 (small model change):** add 1Y / 2Y / 5Y fixed windows to Tool A if more granularity is
   wanted.
3. **Phase 3 (medium, model change):** compute + persist multi-window downside betas in Tool C, then
   add the horizon selector to **Gold Downside (C)**.

## Open questions (for Victor / Codex)
1. Window set — keep 6M / 12M / 3Y, or add 1Y / 2Y / 5Y now?
2. Rename the tab from internal "Tool A" to a trader-legible "Gold Sensitivity" / "Gold Reactors"?
3. "Tilt" wording — keep torque / fragile / balanced, or plainer ("rises more / falls more / even")?
4. Include a GDXJ reference row alongside GDX?
