# Ticker page redesign — agreed requirements and decisions

- **Date:** 2026-08-11 · **Status:** requirements LOCKED by Victor; full implementation plan to follow.
- **Reference mock (v3, approved):** https://claude.ai/code/artifact/1059868b-3d00-42ab-96ff-9a2cfbdd179a
  (built entirely on real NEM data as of 2026-08-10; source kept at
  `.playwright-mcp/mock3.html`, generator inputs in the session scratchpad).
- **Earlier mocks:** v1 https://claude.ai/code/artifact/82f7fc22-8cb0-429c-8254-a586b896ef35 (rejected — read as an options page),
  v2 https://claude.ai/code/artifact/b6256edc-6086-4d33-9340-b84fb4f61a18 (rejected — dropped existing content, bogus beta-derived price, weights confusing).
- **Scope (explicit):** the ticker page `/ticker/<T>` ONLY. One page carrying the company's full profile.
  Other pages are touched only where they would otherwise break.

## 1. What the page is for

"By going into that page the user should feel he has been on Bloomberg — he knows the company
better than he did before he looked at it." Every section shows its headline openly and hides its
depth behind a disclosure.

## 2. Page order (locked)

1. **Performance chart** (visual opener)
2. **Corporate finance** — the first real section, per Victor: "the first part of the page should
   definitely be the corporate finance, not the options"
3. **Market behaviour** (Tool A gold/share relationship + Tool C relative record + Lab history)
4. **Options** (absent entirely when the company has none)
5. **Compare on your own terms** (opt-in score builder)
6. **Your inputs and notes** (four maintenance forms, closed)

## 3. Locked decisions

### Verdicts and scores
- **No compiled/blended score is displayed on this page.** Removed here: Gold Sensitivity Score,
  tool_a_rank, confidence score, fundamental check score/rank, screening verdict, Tool C
  downside/upside ranks, Tool D quality rank.
- Those composites **stay on the other pages** as ordering devices (Victor, Q20) — this is a
  display decision on the ticker page, not a product-wide removal.
- **Statuses stay** (data-quality/eligibility, not opinions): resilience_data_status,
  financial_data_status, score_eligible, put/call status, optionability tier, FX staleness.
- **Screening checks: only surfaced when one FAILS** (Q22), written as a sentence naming the
  measured value and the user's own threshold — never as a label.
  (NEM at spot fails 2 of 7: FCF yield 12.6% vs the 15% floor; forward P/E 10.9x vs the 10x cut-off.)
- **Numbers we do not trust are not shown** (Q21). No confidence display; hide with a short reason.

### Gold scenario dial
- Global dial in the control bar, range **$2,000–$6,000**, default = spot.
- Drives every gold-dependent figure in Corporate finance.
- **Show BOTH values: reported at spot AND at the scenario** — not a % delta alone.
- **Clean by default (Q43):** the scenario column appears only once the dial moves.
- **Gold marks what the dial moves (mock v3 rule — omitted from this document until
  2026-08-13, and therefore silently dropped by the build; see
  `milestones/platform_redesign/gold_marking_gap_2026-08-13.md`).** Dial-driven cards carry a
  gold inline-start edge, dial-driven table rows carry a gold `◆`, and scenario values are
  rendered in the gold accent. Fixed figures carry none of it. The marker is derived from the
  row's Basis text so the symbol and the words can never disagree.
- **Precomputed grid** — see §5 (a live recompute is 3.2–6.5 s; unusable).
- P/E and EV/EBITDA **invert** (rise as gold falls: earnings shrink, price doesn't). Must be
  explained in their "?" text or users misread them.

### Charts
- **One performance chart, two views:** "Compare" (all series indexed to 100 — Victor liked the
  existing rebased overlay) and "Share price" (the stock alone, in dollars).
- Horizon selector 1Y / 3Y / 5Y, **independent of the beta window**.
- Series: stock, gold, GDX, GDXJ, with legend toggles. S&P/Nasdaq deferred (needs new data, Q5).
- Keep the existing **up vs down beta bars** (stock vs GDX vs GDXJ) and the **percentile rugs**
  ("where its gold beta ranks vs the miner universe") — Victor sent both as wanted.

### Lab (market-behaviour history)
- Lives **inside the market-behaviour section, behind a disclosure** (Q27) — it is counted history
  on a **survivor-only** sample and must not sit beside measured betas as an equal.
- Three charts, all requested: **beat-rate by gold scenario** (with uncertainty bars),
  **spread of outcomes** (one tick per scenario week, green beat / red lagged, median marked),
  **when did it happen** (week-by-week forward performance, scenario weeks highlighted).
- Controls: look-ahead **4/8/13/26 weeks, default 8**; benchmark GDX/GDXJ; gold scenario bucket
  from "down >15%" through "up >15%".
- **Why 8 weeks is the default (measured, not preference):** across all 61 miners, 8w yields a
  median 17.8 independent observations and CI width 0.317, versus 13w's 12.5 and 0.373. Longer
  look-aheads overlap more, so they have *less* independent information despite more calendar weeks.
- Scatter trimmed to **2016 onward** (Q44).
- Buckets with too little history render **empty with a reason**, never guessed.

### Options
- **Section is absent entirely when the company has no listed options** — no empty tables, and
  **no proxy/fallback suggestion** (Q38).
- **Always visible:** put/call open-interest ratio + its trend, puts/calls/total open interest,
  implied vol vs its own history, implied move, daily volume.
- **The put/call ratio must be self-explanatory.** Show puts and calls as separate lines plus the
  total, and state the meaning in words. Both ratios are shown because they disagree and the
  disagreement is the insight:
  - whole chain 0.66 (211,900 puts vs 322,506 calls) → more calls, positioning leans bullish;
  - out-of-the-money only 1.42 → puts outnumber calls where speculation and hedging live.
- **Contracts:** the most liquid tradable contract per side, at-the-money and directional, per
  expiry, with an expiry selector. Others behind a disclosure (Q31).
- **Sizing tool (hidden by default):** budget → number of contracts → **value at expiry**.
  The input is a **share-price slider** (Q40) — NOT a gold price. Victor rejected deriving the
  share price from beta: "that is very bogus". Also show a price ladder (break-even and outcomes
  across a range).
- **Greeks:** present, behind a disclosure (Q39).

### Compare on your own terms (score builder)
- **Opt-in: nothing is scored until the user builds it** (Q24). No presets (Q26).
  **Ticker page only — must not influence any other page's ordering** (Q25).
- **Two categories: Trading behaviour and Corporate finance** (Q23).
- **Weights are a 100-point budget** that rebalances as it is allocated — the ×1/×2/×3 bars were
  confusing and are removed.
- Each metric: user-controlled direction (higher/lower is better); metrics the company lacks are
  disabled and simply not counted.
- Output: the company's score and rank, **contribution bars** (what carries it, what drags it),
  a **clickable ranked list of all miners**, and a **stability warning** when a 10-point shift in
  any one weight moves the rank materially.
- Mechanism: each metric converted to its **percentile across the universe** (so units can mix),
  then combined by the user's weights.

## 4. Progressive disclosure — what is open vs closed

**Open by default:** performance chart; corporate-finance headline cards; the failing-checks
notice; beta bars + percentile rugs; all option market context (ratios, OI, IV, implied move,
volume) and the most-liquid contracts; the score builder's controls.

**Closed by default (Victor, 2026-08-11 — same treatment as "How it behaved in past gold moves"):**
- Earnings and cash at this gold price
- Valuation
- Balance sheet, cost and scale
- Resilience — at what gold price does this break?
- How often it beat gold and the ETFs
- Data quality and sources
- Where the crowd is positioned (OI by strike, skew)
- Work out a position (sizing)
- Greeks and full chain
- Full research detail
- Your inputs and notes

All the numbers are present; none of them shout.

## 5. Architecture constraints (carried from the repo canon)

- **Centralise — Victor's explicit instruction: "be careful not to create plenty of logic
  everywhere if it can be centralised."** One implementation each for: gold-scenario resolution,
  percentile ranking, metric formatting/units, the "?" explainer registry, disclosure/section
  rendering, chart primitives (line, rug, bar, scatter), and the failing-check sentence builder.
  Grep before writing any helper; extend rather than fork.
- **Backend computes, serve renders.** No arithmetic, ranking, or fallback resolution in `serve/`.
- **Nothing computes in a request path.** The gold dial is served from a **precomputed grid**
  artifact; the score builder combines **precomputed percentiles** via a model-layer function.
- **Every threshold in config, once.** Includes the grid range/step and the Lab default look-ahead.
- **Label every number with its basis** (gold price used, window, as-of date, source).
- **Degraded data is excluded, not merely flagged.**
- **"?" explainers everywhere they help** (Victor): each should state what the number is, how it is
  calculated, and — where relevant — which direction is good. Registry-driven, not inline strings.

## 6. Known data issues to fix as part of this work

1. **IV-vs-realised is wrong by 100x** — `iv_rv_ratio_60d` divides implied vol as a fraction
   (0.4992) by realised vol as a percent (109.86), giving 0.0045 where the true ratio is 0.45.
   One normalize boundary violation.
2. **IV/skew/implied-move series have gaps and outliers** (an IV of 0.0; another of 111.87 against
   a ~48 baseline; skew of 72.8). Needs a quality gate before display.
3. **Options history needs a published artifact**: `options_features` is an intermediate file, not
   manifest-registered. Same-day duplicates exist and at least one partial capture (NEM 2026-08-10
   shows 354,079 OI against the real 534,406) would draw a fake 33% collapse. Dedupe per day,
   exclude partial captures, publish properly.
4. **Tool D's `fcf_yield` is copied from the spot run**, not the stressed one — wrong beside
   correctly-stressed neighbours.
5. **Tool C tag thresholds are hardcoded inline** (0.5, 1.5, 0.6, 0.25) rather than in config.
6. **`put_status`/`call_status` has three dead branches** that all return the same value.

## 7. Deferred (explicitly, not forgotten)

- S&P / Nasdaq comparison lines (needs new market data).
- Peer-percentile bars beside individual financial metrics (Q14 unanswered).
- Ticker-to-ticker navigation: search box and previous/next through a ranked list (Q17 unanswered).
- Currency handling for AUD/CAD/GBP names — native vs USD vs both (Q18 unanswered).
- Marking earnings/production dates and owned lots on the price chart (Q10 unanswered).
- Portfolio position block (NEM is not held; the shape was not settled).

## 8. Addendum — decisions resolved 2026-08-11 (after Codex's plan review)

Codex's review of the implementation plan (`codex_review_claude_ticker_page_plan.md`) correctly
required that deviations from this file be decided by Victor, not by the plan. Victor resolved
them on 2026-08-11; these amendments override the corresponding text above.

1. **Gold dial mechanism — "precomputed grid" is amended to "precomputed exact lines +
   in-browser evaluation."** §3's "precomputed grid" contradicted the approved mock v3, which
   evaluates exact backend-built lines in the browser. Victor chose the mock's behaviour:
   backend computes everything hard (line coefficients, constants, true-spot display values);
   a narrow, documented client-side layer combines them. Same for the score builder's weighted
   sum and the sizing tool's intrinsic-value ladder. The exception is limited to three
   first-party JS modules consuming only backend-resolved values, locked by backend-parity
   fixtures and real-browser behavioural tests, and recorded in `ARCHITECTURE_FOUNDATIONS.md`.
2. **Contracts control is named "Target window", not "expiry selector."** Selection stays
   horizon-bucketed (existing machinery); every contract row shows its actual expiry date and
   days-to-expiry; put and call rows may legitimately show different expiries.
3. **Failing-check sentences stay fixed and are labelled "at spot gold"** while the dial moves
   other numbers. Scenario-aware sentences are explicitly deferred.
4. **The 8-week Lab default applies to the ticker page only.** Standalone `/lab` pages keep
   their current 13-week default; no shared-Lab behaviour changes inside this project.
5. **Clarification (not a change):** the dial lives in the global control bar, as §3 already
   said; plan v1's section-toolbar wording was drift and is corrected.
