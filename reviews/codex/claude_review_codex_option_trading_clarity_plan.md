# Review — Codex "Option Trading Clarity Plan"

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** `reviews/codex/codex_option_trading_clarity_plan.md`
**Cross-checked against:** the in-flight shipping-safety fixes brief (`claude_codex_shipping_safety_fixes_brief.md`), the shipped Option Trading UI + candidate-selection code (`candidate_puts.py`, `options_chain.py`, `features/options.py`), the Tool C/D v3 plan, the Candidate Finder plan, and the research docs.
**Grade: READY WITH CHANGES.** The problem is real and the UX direction is right. Don't start coding until the 5 coordination/scoping fixes below are settled — mostly because this plan and work Codex may *already be doing* (shipping-safety) both heavily edit the same overview + detail panel.

## The core problem is real and well-diagnosed
I verified the selection bug against the code. `build_candidate_grid` does: nearest expiry → tradability filter → `strike_for_target_delta` picks the **closest delta to target among whatever survived** — with **no check that the chosen delta is actually near the target.** So a −0.02-delta put can be returned for a −0.25 target. And the configured `delta_gap_warning_threshold: 0.10` exists but is **never used in selection** — the plan is right about that. So the fix is justified. ✅

---

## Findings (resolve before coding)

### F1 (High) — This plan COLLIDES with the shipping-safety fixes you already sent Codex
Both edit the **same files** (`serve/detail_panels.py`, `serve/overview_option_trading.py`, `hedge/report.py`) with overlapping-but-different intent:
- Shipping-safety **adds** `iv_skew` / `iv_rv_ratio` context and "modeled value" labels and the negative-expectancy disclosure.
- This plan **removes** the P&L columns from the overview and **restructures** the candidate tables.
If both run as independent streams they'll conflict and may contradict each other (e.g., shipping-safety surfacing skew *into* the overview while this plan simplifies the overview). **Decision needed:** either (a) **fold this clarity plan into the shipping-safety pass** as one coordinated Option-Trading-UI effort, or (b) **sequence explicitly** — finish shipping-safety first, then do clarity *aware of the new state*. My recommendation: **(b)**, and have this plan note where `iv_skew`/`iv_rv_ratio` land given the simplified overview (likely the **detail** panel, not the overview).

### F2 (High) — Adding 120d silently downgrades many tickers from "directly hedgeable" to "thin"
`_optionability_tier` (`features/options.py`) returns `directly_hedgeable` only when **every** target horizon has a usable 25-delta put: `all(put_iv_25d_{h}d is not None for h in target_horizons_days)`. Adding **120d** to `target_horizons_days` means a ticker now needs a liquid **120d** put too — and many miners won't have one. So this change will **reclassify currently-hedgeable names as "thin"**, which also feeds the Candidate Finder's "has options" filter and this very overview. **Fix:** decouple `optionability_tier` from the *full* horizon set (base it on a core horizon, e.g. 60d) **before** adding 120d — otherwise you'll quietly shrink the optionable universe. Flag this explicitly in the plan.

### F3 (High) — Split the Refresh Button into its own milestone
The refresh button is a **different beast** from the rest of this plan: it's backend/infra (spawning a full `update-data` + Tool A + Tool B run from a web click), and it has real risks the UI work doesn't:
- A **synchronous POST will time out** — a full refresh fetches every ticker's prices + options and recomputes A/B; that's minutes, not seconds. So option 1 in the plan is not viable for the real workload.
- Clicking a button to fetch **live market data** is exactly the "calls external APIs" action that CLAUDE.md says needs care (rate limits, the double-click guard the plan rightly includes).
- Spawning a subprocess from the WSGI server is an architecture decision worth its own design.
**Recommendation:** **carve the refresh button out into a separate, focused plan.** Let the high-value, low-risk clarity fixes (selection gates, labels, 120d, Yahoo links, cached-data header) ship now without being blocked by the gnarly refresh architecture. When you do build it, the **background-process-plus-status-page** shape (option 2) is the only one that survives a real full refresh; synchronous will hang.

### F4 (Medium) — Simplify the three hard gates to ONE principled gate + explanation
The plan proposes three hard gates (moneyness, delta-gap, scenario-distance). That's redundant and over-engineered — and a tiny delta already encodes deep-OTM-ness. **Make `delta_gap` the single hard gate:** the `OptionCandidate.delta_gap` field **already exists**, and the unused `delta_gap_warning_threshold` was meant for exactly this. A `candidate_max_delta_gap` (e.g. 0.10–0.15) rejects the AEM 50-strike cleanly (gap 0.23) with one rule. Then use **moneyness ("71% OTM") and the scenario price ("gold −10% → stock ~152, so a ~155 put makes sense") as user-facing *explanation*, not as additional hard gates.** This matches "prefer the simplest thing that works" and keeps the selection logic easy to reason about. (Keep the quality labels Good/Acceptable/Poor/Rejected — those are great.)

### F5 (Medium) — Diagnose *why* only a strike-50 put survived, before assuming it's pure selection logic
AEM is a **liquid** name — near-the-money puts should easily pass the tradability filter. If the *only* survivor was a 50-strike, that hints the **cached chain itself was sparse/stale**, or the normalization/liquidity filter is wrongly dropping good contracts — not just that selection picked "the least bad." The gates will correctly turn this into "no acceptable candidate" either way, but **confirm the root cause first**: if good contracts are being filtered out, that's a separate bug the gates would *mask*. Add a quick diagnostic step ("for AEM, how many puts survived tradability, and at what strikes?") before settling thresholds.

---

## Smaller notes
- **View-model approach (right call):** keeping UI fields (`moneyness_label`, `quality`, `yahoo_chain_url`, …) in a view model rather than bloating `OptionCandidate` is consistent with our clean-separation principle. ✅ Note `last_price` isn't on `OptionCandidate` today (it's on the normalized chain as `last_price`) — it'll need to flow through.
- **Yahoo links:** read-only, user-initiated, fine. Keep the "cached prices may differ" warning. Build from expiry date; the plan already flags Yahoo URL fragility. ✅
- **Confidence rename + status language:** "Tool A Confidence" and plain-English statuses are good and align with the shipping-safety "descriptive, not predictive" framing. Coordinate the wording so the two efforts don't fight.
- **Coherence with Candidate Finder:** the clarity overview ("which tickers are worth opening") and the Candidate Finder both rank optionable names — different tabs, no conflict, but **keep the optionability/status language identical across both** so the user doesn't learn two vocabularies.

---

## Answers to your 5 open questions
1. **Hide bad candidates vs show rejected reason?** → **Show the horizon row** with "No acceptable candidate" + a one-line reason. Agree with Codex — transparent and educational, and it's *why* the user trusts the tool.
2. **Moneyness guardrails?** → Make **delta-gap the hard gate** (see F4); use moneyness as a *secondary loose sanity bound + explanation*, not the primary mechanism. Config-driven, conservative. The 50/175 case must fail (it does, on delta-gap).
3. **Scenario-aware vs delta selection?** → **Keep delta/liquidity for selection; delta-gap for rejection; scenario price as the user-facing *reason*** ("gold −10% → ~152, so ~155 put"). Don't replace delta selection. Agree with Codex's instinct, just don't make scenario-distance a third hard gate.
4. **Refresh architecture?** → **Split it out (F3).** When built: background process + status page; synchronous will time out; guard double-clicks; treat the live-fetch as the approval-sensitive action it is.
5. **Stock price for every optionable ticker in the overview?** → **Yes.** Agree — it's the single biggest legibility win and costs nothing.

---

## Recommended shape
- **Plan A (do now, low risk, high value):** candidate-selection delta-gap gate + quality labels + "no acceptable candidate" rows; cached-data header with stock price; ITM/OTM + moneyness + Last/Bid/Ask/Mid in the candidate table; status/confidence language; Yahoo chain links; 120d **after** fixing the optionability-tier coupling (F2). **Coordinated with / sequenced after the shipping-safety fixes (F1).**
- **Plan B (separate milestone):** the refresh button, with a proper background-job + status design.

Net: the plan is genuinely good and the AEM failure is exactly the kind of thing that erodes trust — worth fixing. The changes above are about **not colliding with in-flight work, not over-engineering the gates, not silently shrinking the optionable universe, and not bundling a hard infra problem (refresh) with easy UI wins.**
