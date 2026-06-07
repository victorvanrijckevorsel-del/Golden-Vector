# Claude review — Codex's Tool B Simple Fundamentals plan

**Reviewer:** Claude Code (Opus 4.8), first-hand — verified the plan's load-bearing claims against the actual code.
**Plan:** `reviews/codex/codex_tool_b_simple_fundamentals_plan.md`
**Grade: READY WITH MINOR CHANGES.**

The product direction is right, the dependency map is **accurate** (I verified the key claims), the approach reuses existing logic (no duplication), and downstream coverage is comprehensive. The "minor changes" are mostly *decisions the plan explicitly defers to me* plus hardening one risk we just got burned by. The spine is sound — build it after the items below are settled.

---

## Emanuel's added direction (incorporate into the plan — these are requirements, not options)

### A) Industry-standard ratios only — drop the home-grown ones
Emanuel's rule: **show ratios the industry actually uses, not ratios we invented.** This sharpens the plan's "keep/persist" list, and it *contradicts* part of the plan:
- **Drop `debt_to_mktcap`, `ebitda_to_mktcap`, `revenue_to_mktcap`, `netincome_to_mktcap`.** Codex's plan proposes to persist these four, but they are **not standard headline ratios** — they're home-grown "÷ market cap" inventions. Use the recognized equivalents already in the keep list instead: **Net Debt / EBITDA** (the standard leverage metric — `debt_to_mktcap` is not), **EV/EBITDA**, **forward P/E** (the standard earnings multiple — `netincome_to_mktcap` is just its inverse), and **EV/Sales** if a revenue multiple is wanted. Candidate Finder should rank these standard ratios, not the `_to_mktcap` ones.
- **Forward estimates** (`forward_ebitda_musd`, `forward_net_income_musd`, `sustainable_fcf_musd`) are standard *concepts* computed with simplified in-house formulas. Keep them, but (a) use a transparent, defensible formula, (b) **label them as estimates at the stated gold price** ("EV/EBITDA — estimated at $X/oz"), and (c) prefer reported/trailing figures where the data exists. Never present a home-grown estimate as a precise fact.
- **Net surviving set should be the metrics a mining analyst recognizes on sight:** AISC, cash margin/oz, margin %, EV/EBITDA, forward P/E, FCF yield, Net Debt/EBITDA, reserve life, jurisdiction tier — plus the raw facts (share price, market cap, production, net debt). That's it.

### B) Remove the Combined tool entirely
Emanuel: the Combined view is full of internal blended calculations that aren't simple to explain, and the Candidate Finder does the same job more powerfully. **I agree — and the code supports it:**
- **Combined is a leaf.** Only the `/` home page consumes `combined_score`/`combined_verdict` (`serve/overview_combined.py`). Tool C, Tool D, and the Candidate Finder read the tool outputs directly, **not** Combined. So removal has a small, contained blast radius and can't break the tools you use.
- It's the opaque `average(Tool A score, Tool B score)` (`combined/ranking.py:compute_combined_score`) — the same composite flagged in #2 below. **Removing Combined resolves the Combined-score question outright** (there's no average left to relabel).
- The Candidate Finder is a strict superset (all tools, transparent user-controlled weights).

**Removal scope:** delete the `combined/` module (join, pipeline, ranking), `persist_combined_outputs`, the combined pipeline step + parquet + manifest entry, combined contracts, and combined tests. Note: the combined **verdict** uses `screening_verdict` + `tool_a_score` (not `tool_b_score`), so nothing in the tools depends on the removed score.

**Home-page replacement — DECIDED (Emanuel):** the home page (`/`) **becomes the Candidate Finder**, defaulting to a **"Strong Corporate Finance (good to buy)" preset** — so opening the app immediately surfaces fundamentally strong, reasonably-valued miners that are good to own, with zero setup. Move the refresh button + model-state banner onto this home view.

Proposed default preset (all **industry-standard** fields from the Tool B change; `options_side: none` so it ranks the whole universe, not just names with usable options; weights tunable, start roughly equal):

| Criterion | Direction | Why it signals "good to buy" |
|---|---|---|
| `fundamental_check_score` | high_good | more of the explicit checks passed |
| AISC | low_good | lower all-in cost = stronger producer |
| Net Debt / EBITDA | low_good | less leverage = more resilient |
| FCF yield | high_good | more cash generation |
| Margin % | high_good | more profitable at the gold assumption |
| EV/EBITDA | low_good | better value |
| Forward P/E | low_good | better value |

Optional add: reserve life (high_good, durability). The user can re-weight/add criteria or switch to a bearish/options view from the same screen. **Depends on the Tool B migration landing first** (these criteria reference the new persisted fundamental fields).

**Still open (decision #2):** keep the "Dual Pass / High Conviction" classification as a separate Finder preset (screening_verdict = STRONG + high gold beta), or drop it? (Not blocking — the home preset above is the priority.)

*Sequencing note:* Combined removal pairs naturally with this Tool B work (both turn on the opaque-composite question) but is a distinct workstream — suggest it as its own checkpoint so the Tool B migration and the Combined teardown can be tested independently.

---

## Claims I verified (all true)
- **`best_upside_pct` is exactly 30% of `tool_b_score`** — `verdicts.py:compute_tool_b_score` = `100*(0.7*base + 0.3*upside)`. The hidden-valuation-drives-ranking concern is real.
- **`combined_score = (tool_a_score + tool_b_score)/2`** — `combined/ranking.py:compute_combined_score`. Changing the Tool B score directly changes Combined.
- **`evaluate_layer1` already computes the checks** — it derives `cash_margin_usd_per_oz`, `margin_pct`, `fcf_yield`, `leverage` and evaluates `aisc_max / margin_min / fcf_yield_min / reserve_life_min / leverage_max` with a `reasons` list. So the check-score can be *derived from* Layer 1, not reimplemented.
- **`determine_size_category` takes only `market_cap_musd`** (no `peer_benchmarks` dependency) — so keeping `market_cap_bucket` while deleting `peer_benchmarks` is safe.
- **`determine_combined_verdict` uses `screening_verdict` + `tool_a_score`, NOT `tool_b_score`** — important (see below).

## Answers to the 6 questions the plan raises

**1) `fundamental_check_score` vs no score → keep the check-score, but never show it bare.**
A "5 of 7 checks passed" pass-rate is genuinely transparent and rule-based — it does **not** violate Emanuel's "simple true numbers" goal, *provided it is always rendered with the per-check breakdown* (`✓ AISC ✓ Margin ✗ Leverage …`). A bare "Fundamental Checks 71%" with no breakdown would quietly re-introduce opacity. So: keep `fundamental_check_score`, make `fundamental_check_summary` the **primary** display and the % secondary. Don't go to "no score" — the sort and the Combined leg need a number, and this one is defensible.

**2) Should Combined keep a score → DECIDE NOW, and I'd drop/demote the average. (This is the plan's weakest point.)**
Verified: `combined_score` averages Tool A's structural-sensitivity score with the Tool B score. If the Tool B leg becomes a fundamentals *pass-rate*, the average blends two incommensurable units into one number — which is **exactly the opaque composite this whole change is meant to remove**, just relocated to the Combined layer. Relabeling it "Fundamental Checks %" doesn't fix that; the *average* is the problem. Crucially, the **Combined verdict** (HIGH_CONVICTION / DUAL_PASS / …) is driven by `screening_verdict` + `tool_a_score` and does **not** use `tool_b_score` — so the verdict (the real signal) survives untouched, and the `combined_score` average is largely **redundant** with it. **Recommendation:** drop the single `combined_score` average (lowest-risk, most on-goal) and present Gold Sensitivity rank and Fundamental Checks as two separate, explainable columns; if a single sort is truly needed, define it as an explicit gate ("passes fundamentals AND high gold sensitivity"), never an average. Do not defer this — deferring leaves the opacity the change is trying to kill.

**3) Do the simple metrics replace the target scenarios → yes.**
`forward_pe`, `ev_ebitda`, `fcf_yield` are the standard valuation ratios. Showing them raw, with Candidate Finder ranking them **cross-sectionally** (percentile vs the universe), replaces the hidden peer-benchmark "target" with a transparent peer-relative rank — more honest and better aligned. The only thing lost is the misleading absolute "target price," which is the point. Sufficient.

**4) Does it avoid duplicated check logic → yes, if built as written.**
Derive the check statuses from `evaluate_layer1`'s existing threshold evaluation (surface the per-check pass/fail it already computes via `reasons`), and add the single `forward_pe` check next to the verdict logic. Do **not** re-evaluate thresholds in a new place. The plan's instruction is correct; the acceptance test should assert the check-score and Layer 1 agree (a Layer-1 FAIL must not show all checks passed).

**5) Stale artifacts → under-specified; harden it (we just shipped this exact class of bug).**
After the code migration, the persisted Tool B parquet still has the **old** schema (target columns, `tool_b_score`, no `fundamental_*`) until a refresh runs — and the new UI/Candidate Finder/Combined code expects the new fields. "Readers must not silently mix" as prose isn't enough. **Require:** (a) "run `python main.py refresh` immediately after migration" as an explicit step; (b) the Tool B reader **fails loud** on schema mismatch (old target columns present OR new fundamental columns absent) with an actionable "Tool B output is stale — re-run refresh" message — reuse the no-silent-failure guard pattern we just added to the Candidate Finder join. This is the same failure mode as the collision bug (silent blanks); don't let it recur.

**6) AISC/leverage directions → the catch is right; make the fix concrete.**
Verified: `aisc` and `leverage` default to `high_good` in `candidate_finder.yaml` (because the bearish-put screen wants fragility). For a general Corporate Finance view that's backwards. **Fix:** set the field `default_direction` to the **quality** interpretation (`low_good` — lower cost/debt is better) and have the `bearish_put` preset **explicitly override to `high_good`**. That makes the default intuitive and the bearish intent explicit, instead of a confusing global default. Keep the direction visible/user-controlled in the UI as the plan says.

## Additional findings (not in the plan)
- **F-a (low):** the check-score has low resolution — 7 checks = only 8 possible values (0/7…7/7). Most quality miners pass 6–7, so the **rank is dominated by the tie-breakers** (`margin_pct`, `fcf_yield`, …), not the headline score. Fine, but reinforces #1: show the breakdown so "Fundamental Rank #3" isn't read as a precise quality score.
- **F-b (low):** two different "confidence" fields exist — Tool A's `confidence_score` (structural, in the Gold Sensitivity finder group) and Tool B's `confidence` (manual-data). The plan keeps Tool B's. Label them distinctly in the UI so "Confidence" isn't ambiguous across pages.
- **F-c (low):** removing `best_upside` from the `bullish_call` preset (and adding margin/fcf replacements) changes preset results — re-validate both presets return sensible lists after the change (presets silently broke once already).
- **F-d (nit):** the override-label renames (`Fwd P/E Target (<)` → `Strong P/E cutoff (<)`, etc.) are good — also double-check no logic keys off the old label strings.

## What's strong (keep as-is)
Accurate dependency map; reuse of `evaluate_layer1`; comprehensive downstream coverage (Candidate Finder, Tool D, Combined, contracts, tests); guards-before-delete ordering; config removed last; the size-bucket extraction; and good self-identified risks. The schema/`rg`-contract test that fails if any target field returns is exactly right.

## Bottom line
**READY WITH MINOR CHANGES** for the Tool B core, **plus two added requirements** from Emanuel (sections A & B above):
- **A) Industry-standard ratios only** — drop the home-grown `*_to_mktcap` ratios; keep only metrics a mining analyst recognizes (AISC, cash margin/oz, EV/EBITDA, forward P/E, FCF yield, Net Debt/EBITDA, reserve life), with forward estimates clearly labeled as estimates at the stated gold price.
- **B) Remove the Combined tool** — it's a leaf (only the home page uses it), it's the opaque blended average, and the Candidate Finder supersedes it. This **resolves** the Combined-score question (#2) outright. Make the Candidate Finder the home page with a sensible default preset.

Then the original items: (1) check-score always shown with its per-check breakdown; (5) fail-loud stale-artifact handling + a mandatory post-migration refresh; (6) AISC/leverage default to the quality direction with explicit bearish overrides.

Everything else is solid and accurate. With A + B folded in, this genuinely delivers Emanuel's goal — simple, explainable, **industry-standard** numbers — and removes the last opaque composite instead of relocating it.
