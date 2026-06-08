# Plan — Corporate Resilience (Tool D) v2: make the gold-stress tool actually stress

**Author:** Claude Code (Opus 4.8)
**Status:** for Codex review, then build. **Sequencing note: build AFTER the option-signals Milestone 1 lands** — that work is editing `contracts/config_models.py`, and this plan also touches it (gold-stress config), so don't run them in parallel.

## 1. The core problem (why Tool D feels flat today)
Corporate Resilience answers "if gold **falls**, who survives and who breaks?" But the page is rendered at **spot gold ($4,315)**, where *every* miner has fat margins — so Headroom is 60–77% for everyone and the table barely differentiates. **The tool only becomes useful when you stress gold DOWN** (e.g. $2,500, $2,000), where high-cost/levered names crack while low-cost ones hold. Today that's impossible — the gold price is fixed to spot with no control.

Good news: Tool D is **already a function of the gold price** — `compute_tool_d_outputs(gold_price=G)` recomputes Tool B in-memory at G and derives every "at G" figure. We just don't expose G.

## 1b. The distinct angle (Emanuel: NOT a second Corporate Finance tab)
A gold slider alone is *not* a new angle — it's the same fundamentals at a different price, which makes Tool D a clone of Corporate Finance. The two must answer **different questions**:
- **Corporate Finance (Tool B):** "Is this a good, well-run, fairly-valued company **right now**?" — a *static fundamentals scorecard* at today's gold.
- **Corporate Resilience (Tool D):** "**How far can gold fall before this company breaks, and how fast does it deteriorate on the way down?**" — *survival thresholds + gold-sensitivity*, which Tool B structurally cannot express.

**Tool D's identity = survival distance + fragility slope, expressed as gold-price thresholds.** Its headline outputs are things Corporate Finance has no concept of:
1. **Breakeven gold** = gold where margin = 0 (`= AISC`). "Survives down to $1,130." A *survival threshold*.
2. **FCF-breakeven gold** = gold where sustainable FCF turns negative (includes sustaining capex) — `AISC + sustaining_capex·1e6/production`. The point they start *burning cash*.
3. **Debt-stress gold** = gold where Net Debt/EBITDA breaches a danger level (e.g. 4×) or interest cover fails. A *fragility threshold*.
4. **Cost-curve position** = AISC percentile across the universe. In a gold crash **the high-cost miners die first** — the single best resilience differentiator (relative, not absolute).
5. **Gold-sensitivity of EBITDA/FCF** = the **slope**: % EBITDA change per % gold change. A high-cost miner's EBITDA collapses far faster — that amplification *is* fragility.

The **Resilience Rank** is built from **survival distance + cost-curve position + deterioration slope + balance-sheet cushion** — none of which is a Corporate Finance metric. The current-state ratios that overlap (EV/EBITDA, FCF yield, current margin) are **demoted to context**; they belong in Corporate Finance.

## 2. The metrics (and their formulas — now shown in the UI)
Already added to the overview as hover tooltips; this plan keeps them visible everywhere:
- **Margin/oz** = `Gold price − AISC`
- **Headroom** = `(Gold price − AISC) / Gold price` — how far gold can fall before breakeven
- **Breakeven gold** = `AISC` (the gold price where margin = 0) — *computed (`breaks_even_at_gold_usd`) but barely surfaced today*
- **Stressed Leverage** = `Net Debt / EBITDA`, EBITDA at G (negative = net cash)
- **EV/EBITDA at G**, **FCF yield**

## 3. What to ADD — the survival/sensitivity columns ARE the product
The page leads with the resilience-unique outputs (§1b), not the fundamentals:
1. **Breakeven gold** (`= AISC`) and **FCF-breakeven gold** (`AISC + sustaining_capex·1e6/production`) — the two survival lines. "Makes money down to **$1,130**; burns cash below **$1,460**." These are the headline columns.
2. **Cost-curve position** — AISC percentile across the universe, shown as a visible rank/band (lowest-cost = survives the deepest crash). The primary differentiator.
3. **Gold-sensitivity (fragility slope)** — % EBITDA (and FCF) change per −10% gold, computed from the model (generalize `ebitda_pct_change_vs_spot` to an elasticity). High = fragile.
4. **Debt-stress gold** — the gold price where Net Debt/EBITDA crosses a danger band (config threshold) or interest cover fails. "Over-levers below **$2,400**."
5. **Resilience Rank** — rebuilt transparently from {survival distance to breakeven, cost-curve position, fragility slope, balance-sheet cushion / net-cash}, with its components shown (not a re-blend of EV/EBITDA & FCF yield).

### How you explore it: the gold-price stress control
A gold-price input + preset buttons — **Spot**, **−15%**, **−25%**, **−35%**, historical anchors (**~$1,830 / ~$1,050**) — + custom. Moving it shows **where each name crosses its thresholds** and recomputes the slope view. **Mirror Tool B's override pattern:** recompute in-memory for the what-if; leave the persisted spot parquet untouched. The slider is the *lens*, the survival thresholds are the *product*.
- **Spot-vs-stress delta** on the key metrics so the erosion is visible.
- **"Who flips" map** — names fine at spot but margin-negative / over-levered at the chosen G (the decision: *which names are secretly fragile*). Reuse `margin_negative_at_G`, `thin_margin_at_G`, `leverage_undefined_at_G`.
- Optional small **survival curve** per name: a metric vs gold from spot down, with the breakeven crossing marked.

## 4. What to REMOVE / FIX
1. **De-duplicate Corporate Finance (the whole point).** Demote the overlapping current-state ratios — **EV/EBITDA, FCF yield, current margin/oz** — to secondary context (or drop from the main table); they're Corporate Finance's job. The Corporate Resilience table should *lead* with the survival/sensitivity columns (§3), so the two tabs read as clearly different tools, not twins.
2. **Rebuild & expose the rank as a Resilience Rank.** Today's `tool_d_quality_score` is the **average of three percentile ranks (Headroom, Stressed Leverage, EV/EBITDA)** — half of which is a valuation ratio, not resilience. Rebuild it from {breakeven distance, cost-curve position, fragility slope, balance-sheet cushion}, and **show its components** (the Tool B transparency lesson) — never a standalone blended number.
3. **Trim Tags** to the resilience-relevant flags (`margin_negative_at_G`, `thin_margin_at_G`, `missing_aisc/production/debt`); drop the noisy `screen_out_context`.
4. **Formulas everywhere** — the overview now has header tooltips; mirror them on the ticker detail page's Corporate Resilience panel.

## 5. Backend / architecture — single source of truth, serve computes nothing (Emanuel's guardrail)
**All calculus lives in the backend, in exactly one place each, and is never re-implemented in the UI.**
- **One module owns the resilience formulas.** Breakeven gold, FCF-breakeven gold, debt-stress gold, the fragility slope, and cost-curve position are computed **only** in `model/tool_d.py` (the existing Tool D pipeline). Nothing else implements them.
- **No duplication of the fundamentals.** Tool D does **not** re-derive EBITDA/FCF/margin — it already reuses `compute_tool_b_in_memory(...)` at the stressed gold (the formulas live once, in Tool B). The stress just calls that same function with a different `gold_price`.
- **The serve/UI layer computes no formula.** It either (a) reads the **persisted** spot values, or (b) calls the one backend function `compute_tool_d_outputs(gold_price=G)` for the interactive what-if. It never does arithmetic on AISC/EBITDA/debt itself. (Contrast: the pre-existing `detail_panels.py:1453` OLS — we do **not** add that pattern here.)
- **Daily state is backend-computed + persisted** (spot, one coherent run). The slider is an explicit, labeled *scenario* — the **one** request-time compute, and it's bounded, deterministic, reuses the same backend code (zero duplicate logic), and leaves the persisted parquet untouched. This is exactly Tool B's already-accepted override pattern.
- **Decided (Emanuel): live override, no pre-compute.** Recompute on demand via `compute_tool_d_outputs(gold_price=G)` — the Tool B Apply-form pattern (scenario buttons + a gold input you apply). Expected fast: Tool B's in-memory compute for ~60 tickers is already a few-seconds path, and the resilience derivation is cheap on top. **Measure it, don't assume** (our standing lesson): instrument the recompute time. If a full-universe recompute ever feels slow, fall back to apply-on-submit (not live-drag) or recompute only the filtered/visible set — but do **not** pre-compute fixed scenarios.
- **Guardrail test:** a test asserts the serve layer contains no resilience arithmetic (no AISC/EBITDA/debt math in `serve/overview_tool_d.py`); the formulas are only in `model/tool_d.py`, exercised by both the refresh and the scenario path.

## 6. UI
- A gold-price control bar on `/tool-d` (scenario buttons + custom input + "reset to spot"), styled like Tool B's override form.
- Prominent **Breakeven gold** column; **spot-vs-G** rendering for the key metrics; the "flips under stress" flag; transparent Quality Score breakdown; formula tooltips.
- Keep rows compact (the Tool B lesson — no inline essays; use tooltips/click-to-expand).

## 7. Tests
- **Breakeven gold == AISC**; **FCF-breakeven gold == AISC + sustaining_capex·1e6/production** (and ≥ breakeven gold).
- **Cost-curve position** = AISC percentile is correct and orients low-cost = most resilient.
- **Fragility slope**: a high-AISC name shows a steeper EBITDA/FCF drop per −10% gold than a low-AISC name.
- **Debt-stress gold**: the gold price where Net Debt/EBITDA crosses the danger band is found correctly (and `N/A` for net-cash names).
- `compute_tool_d_outputs` at several G (spot, −25%, below some names' AISC) flips the right names to margin-negative / over-levered.
- The override recompute leaves the persisted parquet unchanged (scenario-only).
- Resilience Rank equals the mean of its (survival/cost/slope/cushion) component percentiles — transparency pinned.
- Page renders the gold control + scenario recompute + compact rows; the table leads with survival columns, not the Corporate Finance ratios.

## 8. Self-review
The reframe is the point: Corporate Resilience now answers a question Corporate Finance **can't** — *how far can gold fall before this miner breaks, and how fast does it deteriorate* — via survival thresholds (breakeven / FCF-breakeven / debt-stress gold), cost-curve position, and the fragility slope, with the gold slider as the lens. The overlapping current-state ratios are demoted so the two tabs are clearly different tools, not twins. It keeps Emanuel's transparency rule (formulas visible; the rank shown by its components), reuses Tool B's accepted override pattern (no new architecture risk), and stays compact. Judgment calls: the default scenario presets, the debt-danger band, and the slope normalization (per −10% gold) — propose defaults, tune on real data. Build after option-signals Milestone 1 to avoid `config_models.py` collisions.
