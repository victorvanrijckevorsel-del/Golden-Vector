# Plan — Symmetric option-chain signals (puts & calls), backend-computed, evidence-based

**Author:** Claude Code (Opus 4.8)
**Status:** for Codex review, then build.
**Goal (Emanuel):** turn the full option chain we already archive into a **strong, useful, honest signal** for each name — **symmetric across puts and calls** — computed **entirely in the backend** and persisted, covering the **single-name miners and the two gold ETFs (GDX, GDXJ)**.

## 1. Principles (non-negotiable)
- **Evidence-based, not folklore.** Use the metrics our own research briefs found actually predict, label each by how strong the evidence is, and present signals as **flags, not guarantees** (`reviews/codex/research_options_methodology_and_predictors.md`).
- **Industry-standard, explainable** (Emanuel's standing rule): no invented composites. The "signal" is a transparent, named classification + a plain-English breakdown (like Tool B's `fundamental_check_summary`), never a black-box score.
- **Symmetric:** every metric reported for both sides; the signal serves a bearish (put) *and* a bullish (call) thesis.
- **Backend-only:** compute at refresh, persist per ticker; the serve layer just reads. No request-path crunching.
- **Build on what exists** (anti-duplication): `features/options.py` already computes `iv_skew_{h}d` (put_IV − call_IV), `iv_rv_ratio_{h}d`, `put_call_oi_ratio_*`, and 25-delta put/call IV. This feature mostly **synthesizes + adds history + presents**, not recomputes.

## 2. The evidence-graded metric set (what the signal is built from)
| Metric | What it says | Evidence | Status |
|---|---|---|---|
| ⭐ **IV skew** (`put_IV − call_IV`, OTM 25Δ) | Market pricing **downside/crash risk**; informed traders buy OTM puts before bad news | **Strong** — Xing-Zhang-Zhao 2010: steepest-smirk names underperform flattest ~10.9%/yr | **Already computed** |
| **IV vs realized vol** (`iv_rv_ratio`) | Are options **expensive right now** (overpaying for premium)? | Moderate, short-horizon (Carr-Wu/Bollerslev VRP) | **Already computed** |
| **IV regime** (IV percentile/rank vs the name's **own history**) | Is current IV cheap/normal/rich for *this* name? | Standard practitioner metric (IV rank) | **NEW — read the archive** |
| **Put/Call OI & volume ratio** | Crude positioning lean | **Weak** — Pan-Poteshman: public P/C ≠ the proprietary signed-flow result; **context only** | Already computed (down-rank it) |
| **Liquidity** (rel. bid-ask spread, both-sides quotes, OI) | Is the signal even trustworthy / tradable? | Dominant liquidity metric = relative spread | Partially exists (`liquidity_tier`) |

**Important honest framing for Emanuel:** your earlier instinct ("are buyers betting the stock goes down?") is right — but the **rigorous version of it is the IV skew, not the put/call ratio.** The public put/call ratio is a *weak* signal (the strong studies used proprietary signed flow we don't have). The **IV skew is the strongest, best-evidenced signal we can build** — and we already compute it. So the headline signal is the skew; the put/call ratio is shown as weak context only.

## 3. The signal layer (the "strong signal") — transparent, symmetric, rule-based
Per name, persist a small set of **named flags** + a plain-English summary (mirrors `fundamental_check_summary`):
- **Downside-risk read (from skew):** `ELEVATED` / `NORMAL` / `LOW` — e.g. *"Puts priced 18% richer than calls (25Δ, 60d) → market pricing elevated downside risk."*
- **Expensiveness read (from IV vs RV + IV rank):** `RICH` / `NORMAL` / `CHEAP` — e.g. *"IV is 1.4× realized and in the 88th percentile of its 1-yr range → options are expensive."*
- **Positioning context (weak, labeled):** put/call OI & volume ratio, shown but tagged "weak signal."
- **Confidence gate:** only emit a signal when the chain is liquid enough (reuse `liquidity_tier`); otherwise `LOW_DATA` with a visible reason. Yahoo IV is noisy — require both-sides non-zero quotes, min OI, fresh quotes.
- **Symmetric summary** so it reads for either thesis: *"Bearish skew + rich IV: the market is positioned for downside and protection is expensive — buying puts here means paying up; selling premium carries the usual crash risk."*
- **One-line headline signal** per name (the "strong signal"): e.g. `DOWNSIDE-PRICED, EXPENSIVE` / `UPSIDE-TILTED, CHEAP` / `NEUTRAL` / `LOW_DATA`.

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

## 7. UI (read-only, symmetric)
- **Per-ticker detail page:** a symmetric Puts-vs-Calls signal block (skew, IV-vs-RV, IV rank, positioning) + the one-line headline signal + the GDX/GDXJ relative read. Pairs with the put/call 60/90/120 candidate sections already there.
- **Option Trading overview:** add a sortable "downside-skew / expensiveness / headline-signal" column set so the user can scan the universe + the two ETFs at a glance.
- Honest labels everywhere: "signal, not a guarantee; in-sample evidence may decay; validate."

## 8. Out of scope / guardrails
- **Don't push short-vol/premium-selling** strategies to a beginner (research refuted "short vol is free money" — real crash risk).
- **No volatility-surface/term-structure model** — research (Dumas-Fleming-Whaley) shows it buys nothing out-of-sample; per-contract IV already absorbs the skew.
- Don't oversell the put/call ratio. Don't present any signal as financial advice.

## 9. Decisions for Emanuel (flag before building)
1. **Headline signal = a descriptive read** ("market is pricing downside; options are expensive"), not a buy/sell call. *(Recommended — honest + matches the evidence; Yahoo data is too noisy for trade calls.)* Confirm.
2. **Surface:** integrate into the existing Option Trading page + per-ticker detail (recommended), vs a brand-new "Option Signals" tab. Confirm.
3. **History at launch:** ship now with current-snapshot signals (skew, IV-vs-RV, positioning) and let the IV-rank/trend metrics strengthen as the archive grows — i.e., don't wait for months of history. *(Recommended.)* Confirm.

## 10. Self-review
Grounded in our own peer-reviewed research (skew = the strong, already-computed signal; put/call ratio explicitly down-ranked; expensiveness via IV-vs-RV/IV-rank) and in the existing code (extends `features/options.py`, reuses `liquidity_tier`, reads the existing archive). It is symmetric, backend-only, honest (flags not guarantees), covers GDX/GDXJ as a sector reference, and avoids a black-box composite. Main risks: (a) Yahoo IV data quality → the liquidity/confidence gate is essential; (b) history thin at launch → label it and protect snapshots from pruning; (c) keep the put/call ratio honestly down-ranked despite its intuitive appeal. Ready for Codex review once Emanuel confirms the §9 decisions.
