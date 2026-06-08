# Plan — Symmetric option-chain signals (puts & calls), backend-computed, evidence-based

**Author:** Claude Code (Opus 4.8)
**Status:** for Codex review, then build.
**Goal (Emanuel):** turn the full option chain we already archive into a **strong, useful, honest signal** for each name — **symmetric across puts and calls** — computed **entirely in the backend** and persisted, covering the **single-name miners and the two gold ETFs (GDX, GDXJ)**.

## 1. Principles (non-negotiable)
- **Evidence-based, and blunt — no safe wording (Emanuel).** State what the data shows directly: *"the options market is pricing significant downside risk in AEM."* No defensive "this may not be a guarantee" hedging. Being truthful also means being accurate about strength — lead with the strong signals (skew, OI flow), and don't dress up a weak one (the static put/call *level*) as strong. (Grounding: `reviews/codex/research_options_methodology_and_predictors.md`.)
- **Industry-standard, explainable** (Emanuel's standing rule): no invented composites. The "signal" is a transparent, named classification + a plain-English breakdown (like Tool B's `fundamental_check_summary`), never a black-box score.
- **Symmetric:** every metric reported for both sides; the signal serves a bearish (put) *and* a bullish (call) thesis.
- **Backend-only:** compute at refresh, persist per ticker (including the data behind the charts); the serve layer just reads and plots. No request-path crunching.
- **Build on what exists** (anti-duplication): `features/options.py` already computes `iv_skew_{h}d` (put_IV − call_IV), `iv_rv_ratio_{h}d`, `put_call_oi_ratio_*`, and 25-delta put/call IV. This feature mostly **synthesizes + adds OI-flow & history + charts + presents**, not recomputes.

## 2. The evidence-graded metric set (what the signal is built from)
| Metric | What it says | Evidence | Status |
|---|---|---|---|
| ⭐ **IV skew** (`put_IV − call_IV`, OTM 25Δ) | Market pricing **downside/crash risk**; informed traders buy OTM puts before bad news | **Strong** — Xing-Zhang-Zhao 2010: steepest-smirk names underperform flattest ~10.9%/yr | **Already computed** |
| **IV vs realized vol** (`iv_rv_ratio`) | Are options **expensive right now** (overpaying for premium)? | Moderate, short-horizon (Carr-Wu/Bollerslev VRP) | **Already computed** |
| ⭐ **Open-interest change, per side** (Δ put-OI, Δ call-OI vs prior refresh; also volume surge) | **New money / conviction entering** — put OI surging = downside bets being opened in size | Real positioning signal; **strongest when it agrees with the skew**. Unsigned (can't split buy- vs sell-to-open), so read it *with* the skew, not alone | **NEW — from the archive** |
| **IV regime** (IV percentile/rank vs the name's **own history**) | Is current IV cheap/normal/rich for *this* name? | Standard practitioner metric (IV rank) | **NEW — read the archive** |
| Put/Call OI *level* ratio | Crude static lean | Weak on its own (Pan-Poteshman: public *level* ≠ signed flow) — context, not headline | Already computed |
| **Liquidity** (rel. bid-ask spread, both-sides quotes, OI) | Is the signal even trustworthy / tradable? | Dominant liquidity metric = relative spread | Partially exists (`liquidity_tier`) |

**The truth, plainly:** your instinct ("are buyers betting the stock goes down?") is right, and there are **two strong ways to see it** — the **IV skew** (puts priced richer than calls) and the **change in open interest** (new put contracts being opened in size). Those are the two headline signals, and they're best read together: skew steepening *and* put OI surging is a much stronger downside read than either alone. The one thing that is *not* a strong signal is the **static** put/call *ratio* level (a snapshot number) — the studies that found it predictive used proprietary signed flow we don't have, so we show the level as context only and let the **OI change** carry the positioning signal.

## 3. The signal layer (the "strong signal") — transparent, symmetric, rule-based
Per name, persist a small set of **named flags** + a blunt plain-English summary (mirrors `fundamental_check_summary`). Two headline signals + supporting reads:
- ⭐ **Skew (direction):** `DOWNSIDE` / `NEUTRAL` / `UPSIDE` — *"Puts are 18% richer than calls (25Δ, 60d): the market is pricing real downside risk."*
- ⭐ **OI flow (conviction):** `BUILDING_DOWNSIDE` / `BUILDING_UPSIDE` / `QUIET` — *"Put open interest jumped 40% since last refresh; call OI flat: downside bets are being opened in size."* (Strongest when it agrees with the skew → the summary says so explicitly.)
- **Expensiveness (IV vs RV + IV rank):** `RICH` / `NORMAL` / `CHEAP` — *"IV is 1.4× realized and in the 88th percentile of its 1-yr range: options are expensive right now."*
- **Static positioning context:** put/call OI/volume *level* ratio, shown but tagged "weak — context only."
- **Confidence gate:** emit a real signal only when the chain is liquid enough (reuse `liquidity_tier`); otherwise `LOW_DATA` with the reason shown (Yahoo IV is noisy — require both-sides non-zero quotes, min OI, fresh quotes). State it plainly: *"Not enough liquid options to read a signal."*
- **One-line headline** per name (the "strong signal"): e.g. `DOWNSIDE — building, expensive` / `UPSIDE — building, cheap` / `NEUTRAL` / `LOW_DATA`. The skew + OI-flow agreement drives it; the summary spells out exactly why in one blunt sentence.

This is a **classification, not a number** — fully explainable from the components shown.

## 4. GDX / GDXJ as the sector reference (high-value, low-cost)
The ETFs have **far more liquid, reliable** options than single-name miners (per the liquidity research). Compute the same metrics for GDX/GDXJ and use them two ways:
- **Sector gauge:** "the gold-miner sector skew is steep/flat right now" — a clean, trustworthy read where single names are noisy.
- **Relative read per name:** *"AEM's downside skew is steeper than GDX's → name-specific downside concern beyond the sector."* This is genuinely useful and honest (separates sector from idiosyncratic).

## 5. The evolution / history piece (and its launch caveat)
IV regime (IV rank/percentile vs own history) and spread/IV trends read **across the run-stamped option snapshots** the archive already saves. **Caveat to flag clearly:** the archive only recently started, so history-based metrics (IV rank, trend) are **thin at launch and strengthen over weeks** — show them with a "limited history" note until enough refreshes accumulate, and **protect the option snapshots from pruning** (the retention gap flagged earlier) so the archive actually accumulates.

## 6. Backend architecture
- Add an option-signals computation in the **refresh/option-artifact phase** (extend `features/options.py` + the option artifact builder), persisting a per-ticker **option-signals** artifact (the flags, the component values, the symmetric summary, the GDX/GDXJ comparison, a confidence/liquidity tag, and a "history depth" indicator).
- The serve layer **reads** this artifact only — no IV/skew/percentile math in the request path. (Note: there's a pre-existing request-time OLS in `detail_panels.py:1453`; keep new analytics out of that pattern.)
- Schema-contract + fail-loud on stale, consistent with the Tool B `schema.py` pattern.

## 7. UI — integrated into the Option Trading tab (Emanuel: confirmed), read-only, symmetric
The signals live in the **Option Trading** page (overview) and the per-ticker detail — not a new tab.
- **Option Trading overview:** add sortable columns — headline signal, skew (direction + magnitude), OI-flow, expensiveness — so the user can scan all names + GDX/GDXJ at a glance and sort by "most downside-skewed" etc.
- **Per-ticker detail:** a symmetric Puts-vs-Calls signal block (skew, OI-flow, IV-vs-RV, IV rank) + the one-line headline + the GDX/GDXJ relative read, beside the put/call 60/90/120 candidate sections already there.

### Charts (Emanuel: "show graphs so it's easy to see the skew going one way or the other")
Three small charts; the **chart data points are computed and persisted at refresh**, the UI only plots them (same split as the existing beta-history chart that reads persisted structural metrics — reuse `serve/charts.py`):
1. **Skew curve (the headline visual):** IV plotted across moneyness/strike — put wing on the left, call wing on the right. A higher put wing = downside skew you can *see*. ATM marked. One line per horizon (60/90/120d), or a horizon toggle.
2. **Skew over time:** `put_IV − call_IV` plotted across refreshes — a rising line = skew steepening = downside risk building. The clearest "which way is it tilting" view; thickens as the archive grows.
3. **Open interest by strike, puts vs calls:** mirrored bars showing where the crowd is positioned, with the latest OI *change* highlighted (the new money).
- Labels are blunt and direct (no "not a guarantee" boilerplate) — they state what the chart shows.

## 8. Out of scope / guardrails
- **Don't push short-vol/premium-selling** strategies to a beginner (research refuted "short vol is free money" — real crash risk).
- **No volatility-surface/term-structure model** — research (Dumas-Fleming-Whaley) shows it buys nothing out-of-sample; per-contract IV already absorbs the skew.
- Don't oversell the put/call ratio. Don't present any signal as financial advice.

## 9. Decisions — resolved by Emanuel
1. **No safe wording — state the truth directly.** The signal bluntly says what the data shows ("the market is pricing real downside risk; options are expensive"). It is *not* a buy/sell call (that's a prediction, not a fact) — it reports what the options market is doing, in plain, confident language, no hedging boilerplate.
2. **Surface = the Option Trading tab** (overview + per-ticker detail), not a new tab. ✅
3. **Open-interest *change* is a headline signal** (not just context), read together with the skew. ✅
4. **Charts included** — skew curve, skew-over-time, OI-by-strike. ✅
5. **Launch now** with current-snapshot signals (skew, OI flow, IV-vs-RV); the history-based metrics (IV rank, skew trend) strengthen as the archive grows — ship rather than wait. *(Default unless Emanuel says otherwise.)*

## 10. Self-review
Grounded in our own peer-reviewed research (two strong signals — skew *and* OI-change/flow; expensiveness via IV-vs-RV/IV-rank; static put/call *level* honestly down-ranked) and in the existing code (extends `features/options.py`, reuses `liquidity_tier`, reads the existing archive). It is symmetric, backend-only, blunt (states the truth, no hedging), covers GDX/GDXJ as a sector reference, includes the three charts Emanuel asked for (data computed at refresh, UI only plots), and avoids a black-box composite. Main risks: (a) Yahoo IV/OI data quality → the liquidity/confidence gate is essential, and OI change needs two clean consecutive snapshots; (b) history/flow thin at launch → label it and **protect option snapshots from pruning** so the archive accumulates; (c) keep the static put/call ratio honestly down-ranked while the OI *change* carries the positioning signal. All §9 decisions resolved — ready for Codex review.
