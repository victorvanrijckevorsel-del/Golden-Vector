# Review — Option Candidate Redesign Plan

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** `reviews/codex/codex_option_candidate_redesign_plan.md`
**Cross-checked against:** the shipped liquidity engine (`hedge/options_liquidity.py`), the Candidate Finder (`serve/candidate_finder_data.py` — which depends on slot semantics), and the options-selection research (`research_option_selection_liquidity_and_design.md`).
**Grade: READY WITH CHANGES.** The shape is right — a compact 4-slot matrix, sign-aware OTM, no junk rows, strict→relaxed. Three things need nailing before coding, the first because it silently affects a tool you've already built.

## Endorsed as-is (good calls)
- **4 slots per horizon** (put/call × near-ATM/directional), dropping the "5 labels, 1 contract" collapse. ✅
- **Sign-aware OTM** (puts below spot, calls above; never ITM in these slots) — correct; `moneyness_pct` (absolute) is genuinely insufficient. ✅
- **No untradable/rejected rows in the table** → "No liquid candidate" + reason. ✅ (matches the research's "never force a candidate.")
- **Dedup by contract identity `(option_type, expiration, strike)`**, not bucket label. ✅ (the current `_unique_candidates` dedup-by-label is exactly the bug behind AEM's repeated 155.)
- **60/90/120 only, flexible bands, liquidity-aware expiry** (a 70d can win ~60d). ✅
- **"Candidate" language**, Yahoo honest fallback ("Open Yahoo options" if exact-expiry isn't guaranteed), side-neutral bucket IDs + `option_type`. ✅

---

## Findings to resolve

### F1 (High) — The Watch/`is_usable_candidate` decision must keep the shared primitive STRICT (this touches the Candidate Finder)
This is the most important point, and you flagged it (§14.1, §15). Here's the precise situation in the current code:
- A slot gets `slot.candidate` **only when `is_usable_candidate()` passes** (which requires `tier == tradable`). Relaxed/wide contracts become `rejected_candidate`.
- The **Candidate Finder** (`candidate_finder_data._has_usable_slots`) counts a name as having a usable put/call iff **`slot.candidate is not None`** — i.e., it relies on "candidate present ⇒ genuinely tradable."

The plan proposes making **relaxed Watch candidates populate `slot.candidate`** so they're Select-able in the detail UI (§4 step 4). If you do that *without* changing `_has_usable_slots`, **Watch-only names would silently start counting as "usable" in the Candidate Finder** — widening "usable puts/calls" to include 35–45%-spread junk. That breaks the whole point of the side-aware filter.

**Required fix (and the answer to your §15 open question):**
- **Keep `is_usable_candidate()` strict = `tradable`.** Do not loosen the shared primitive.
- If a Watch candidate is made selectable, the slot must expose **both the candidate and its tier**, and every "is this usable?" consumer must check **`tier == "tradable"`**, not just `candidate is not None`:
  - **Candidate Finder side filter → tradable only** (agree with your rec). Update `_has_usable_slots` to `slot.candidate is not None AND slot.liquidity_tier == "tradable"`, with a **regression test** that a Watch-only ticker is NOT counted usable.
  - **Ticker-detail Select → tradable OR watch** (agree — selectable).
  - **Overview status → three states** (`Tradable candidate` / `Watch candidate` / `No liquid candidate`) driven by the same tier rule (agree).
- This keeps overview, detail, and the Finder **consistent** (your risk #8) on one tier-based definition.

### F2 (Medium) — Don't lose the gold-scenario tie when you drop `model_fit`
Dropping `tail` is fine. But **`model_fit` is the one bucket that connects the option to the *gold* thesis** — the whole reason this tool exists (bet on gold via miners). Removing it as a *row* is acceptable for a beginner UI, **but the gold-move reasoning must survive** in the **sizing/scenario calculator** (gold −10% → stock ≈ −X% via beta → P&L). Don't let "what does this contract do if gold moves" disappear. (Helpful framing: the directional 15–20% OTM range is roughly where a ~2-beta miner sits after a meaningful gold move, so model-fit is *implicitly* folded into "directional" — say that, and keep the explicit scenario P&L.)

### F3 (Medium) — Keep delta as context + a lottery flag (OTM% alone can reintroduce the lottery problem)
Switching strike buckets from **delta** to **OTM %** is great for legibility (and you chose it) — but OTM% doesn't control for IV/time the way delta does. A "15–20% OTM" put on a 90%-IV junior miner can be a low-delta lottery ticket, exactly what the research warns against. **Keep delta as a context column**, and **flag "lottery" when a directional pick is deep-OTM-equivalent + high-IV + short-dated** (the research's lottery signal). OTM% drives the bucket; delta + the flag keep it honest.

### F4 (Medium) — DTE band overlaps put the same contract in two horizon groups
Proposed bands overlap: 60d `40–80` and 90d `75–110` share 75–80; 90d and 120d share 105–110. A 78-DTE contract qualifies for both ~60d and ~90d → the **same contract can appear under two horizon targets** (dedup is per-(horizon,side), so it won't catch this). Decide: **non-overlapping bands** (e.g. 60d `40–74`, 90d `75–104`, 120d `105–150`) **or** assign each contract to its **nearest target** only. Either is fine; pick one so a contract never shows twice across groups.

### F5 (Medium) — Watch candidates need the "you'll likely overpay" warning, not just a tier label
A relaxed pass allowing **45% spread** means a buyer can lose ~**22%** to the half-spread on a round trip. The research is blunt that this illiquidity cost is first-order. A `Watch` row that's selectable must carry a **prominent "wide spread — you'll likely overpay" note** at the point of selection (and in the sizing calculator), not just a yellow tier badge. Transparency + opt-in is fine; silent acceptance is not.

### F6 (Low) — Scoring weights & the half-spread column
- The new slot-selection score (`0.35 spread + 0.25 otm_fit + 0.20 OI + 0.10 dte_fit + 0.05 vol + 0.05 monthly`) is reasonable for a *within-slot fit* score — spread is still the largest single weight. Keep it that way, keep it **explainable not predictive** (your risk #3), and keep the pure `liquidity_score` (used for tiers) conceptually distinct from this fit score. Fine.
- **Removing the half-spread *column* is OK** because the **Spread % column stays** (the cost proxy is still visible). Just make sure spread% is prominent — it's the single most decision-relevant cost number for a buyer.

---

## Direct answer to your §15 open question
> Should relaxed `Watch` candidates count as "available" for detail Select / overview / Candidate Finder?
- **Detail Select: yes** (selectable, with the F5 overpay warning).
- **Overview: separate `Watch candidate` status** (three-state).
- **Candidate Finder side filter: NO — strict `tradable` only.** And the implementation must enforce it via `tier == "tradable"` (F1), with a regression test — otherwise making Watch a `.candidate` silently widens the Finder.

Your recommendations are right; F1 is the implementation discipline that makes them safe.

## Bottom line
Good, well-scoped UX refinement. The must-do is **F1** (keep the shared primitive strict; make the Finder's usable-check tier-aware, tested) because it protects the Candidate Finder you just shipped. **F2–F5** keep it honest (gold tie, delta/lottery context, no double-listing, overpay warning). Everything else — the 4-slot matrix, sign-aware OTM, no-junk-rows, dedup-by-identity, strict→relaxed — is the right call. After these, it's ready to build.
