# Plan — Corporate Resilience (Tool D) v2: make the gold-stress tool actually stress

**Author:** Claude Code (Opus 4.8)
**Status:** for Codex review, then build. **Sequencing note: build AFTER the option-signals Milestone 1 lands** — that work is editing `contracts/config_models.py`, and this plan also touches it (gold-stress config), so don't run them in parallel.

## 1. The core problem (why Tool D feels flat today)
Corporate Resilience answers "if gold **falls**, who survives and who breaks?" But the page is rendered at **spot gold ($4,315)**, where *every* miner has fat margins — so Headroom is 60–77% for everyone and the table barely differentiates. **The tool only becomes useful when you stress gold DOWN** (e.g. $2,500, $2,000), where high-cost/levered names crack while low-cost ones hold. Today that's impossible — the gold price is fixed to spot with no control.

Good news: Tool D is **already a function of the gold price** — `compute_tool_d_outputs(gold_price=G)` recomputes Tool B in-memory at G and derives every "at G" figure. We just don't expose G.

## 2. The metrics (and their formulas — now shown in the UI)
Already added to the overview as hover tooltips; this plan keeps them visible everywhere:
- **Margin/oz** = `Gold price − AISC`
- **Headroom** = `(Gold price − AISC) / Gold price` — how far gold can fall before breakeven
- **Breakeven gold** = `AISC` (the gold price where margin = 0) — *computed (`breaks_even_at_gold_usd`) but barely surfaced today*
- **Stressed Leverage** = `Net Debt / EBITDA`, EBITDA at G (negative = net cash)
- **EV/EBITDA at G**, **FCF yield**

## 3. What to ADD
1. **Gold-price stress control (the headline feature).** A gold-price input + preset scenario buttons — **Spot**, **−15%**, **−25%**, **−35%**, and a historical anchor (**~$1,830 / ~$1,050**) — plus a custom value. Recompute all "at G" figures for the scenario. **Mirror Tool B's override pattern exactly:** recompute in-memory from the snapshot + manual store for the what-if; **leave the persisted daily parquet untouched** (it stays at spot). This is the established, acceptable request-time *scenario* compute — clearly separated from the persisted view.
2. **Breakeven gold, front and center.** "Survives down to **$1,130** gold" is the single most intuitive resilience number — more so than Headroom %. Promote `breaks_even_at_gold_usd` to a prominent column.
3. **Spot-vs-stressed, side by side.** For the chosen stress, show each metric at **spot** and **at G** with the change, so the user *sees* resilience erode (we already compute `ebitda_pct_change_vs_spot`). The delta is the point.
4. **"Who flips" highlight.** Flag names that are fine at spot but turn **margin-negative or over-levered at the stressed gold** — the actual decision: *which names are secretly fragile.* (Reuse the existing tag logic: `margin_negative_at_G`, `thin_margin_at_G`, `leverage_undefined_at_G`.)

## 4. What to REMOVE / FIX
1. **Make "Quality Score" transparent.** It's an opaque composite — literally the **average of three percentile ranks** (Headroom, Stressed Leverage, EV/EBITDA, oriented; `_add_quality_scores`). Same pattern we removed from Tool B. **Keep the rank for sorting, but show the three component ranks** (or a "why this rank" breakdown) so the user sees *what drives it*, not just a blended number. Don't present it as a standalone truth.
2. **Trim Tags** to the resilience-relevant flags (`margin_negative_at_G`, `thin_margin_at_G`, `missing_aisc/production/debt`); drop the noisy `screen_out_context`.
3. **Formulas everywhere** — the overview now has header tooltips; mirror them on the ticker detail page's Corporate Resilience panel.

## 5. Backend / architecture
- The gold-stress recompute is the **Tool B scenario-override pattern** (request-time, in-memory, persisted data untouched) — already precedented and accepted; not new request-path crunching of the persisted artifact.
- Persisted daily Tool D stays spot-based (one coherent run). The stress view is explicitly a *what-if*, labeled with the chosen G.
- No new persisted artifact required for v2 (it reuses Tool D's existing compute at a different G). If we later want to persist a few standard stress scenarios for fast scanning, that's a follow-up.

## 6. UI
- A gold-price control bar on `/tool-d` (scenario buttons + custom input + "reset to spot"), styled like Tool B's override form.
- Prominent **Breakeven gold** column; **spot-vs-G** rendering for the key metrics; the "flips under stress" flag; transparent Quality Score breakdown; formula tooltips.
- Keep rows compact (the Tool B lesson — no inline essays; use tooltips/click-to-expand).

## 7. Tests
- `compute_tool_d_outputs` at several G (spot, −25%, a value below some names' AISC) produces correct Margin/Headroom/Breakeven/Stressed-Leverage and flips the right names to margin-negative.
- The override recompute leaves the persisted parquet unchanged (scenario-only).
- Quality Score equals the mean of its component percentiles (pin the transparency).
- Breakeven gold == AISC.
- Page renders the control + scenario recompute + compact rows.

## 8. Self-review
This makes Corporate Resilience do the one thing it's for — **stress gold down and see who breaks** — by exposing the gold price the model already takes, surfacing the most intuitive number (breakeven gold), showing the spot-vs-stress delta, and flagging who flips. It also applies Emanuel's transparency rule (formulas visible; Quality Score shown by its components, not as a black box), reuses Tool B's accepted override pattern (no new architecture risk), and stays compact. Main judgment call: the default scenario presets and the breakeven/leverage thresholds for the "flips" flag — propose defaults, tune on real data. Build after option-signals Milestone 1 to avoid `config_models.py` collisions.
