# Brainstorming Brief: Tool C + Tool D (Downside / Short / Hedge Finder)

**From:** Claude Code (on behalf of Emanuel)
**To:** Codex
**Date:** 2026-05-29
**Stage:** PRE-PLAN. This is NOT a plan. This is a request for your independent thinking.
**Output you should produce:** `reviews/codex/codex_tool_c_d_ideas_and_critique.md`

---

## What we want from you

Emanuel and I have sketched a direction for two new tools (Tool C and Tool D). Before we commit to a plan, we want **your independent perspective**. Specifically:

1. **Critique our direction.** Where are we wrong? What did we miss? What are we over-engineering? What are we under-engineering?
2. **Suggest alternative framings.** Is there a fundamentally different shape for this work that would serve Emanuel better?
3. **Propose metrics, signals, or features we haven't considered.** You may know things from finance/quant practice we don't.
4. **Identify risks.** Statistical, operational, conceptual. Anywhere a v1 might mislead users.
5. **Tell us what to cut.** Be ruthless. What's nice-to-have masquerading as core?
6. **Tell us what we'd regret skipping.** Same lens, opposite direction.

Think outside the box. Disagree with us. You are not building anything yet — only thinking. Your output is a markdown document, not code.

---

## Background: who Emanuel is and what Golden Vector is

Emanuel is a beginner founder building a gold-mining-stock screening tool for himself and a few peers. He's not a quant. He prefers plain English explanations, low-interruption execution, and structured output. He **deeply mistrusts** anything that smells like over-engineered "predictive" models on small data. He wants tools that are honest about their limitations, explainable line-by-line, and grounded in domain logic rather than statistical magic.

Key things he's said in past conversations:

- *"Predictive is a loaded word"* — he wants us to force the conversation around rule-based forward scores vs. real statistical predictions before building anything called "predictive."
- *"36 months × 60 tickers might not support real ML; rule-based may be the honest answer."*
- *"What is the simplest thing that could work?"* — this is one of his standing rules.
- *"Match rigor to risk"* — UI tweaks get light review; math/data changes get the full plan + review cycle.

## The existing product (don't re-derive — just orient)

Golden Vector currently has two analytical pipelines, both for **finding gold stocks to BUY (long candidates)**:

- **Tool A — structural sensitivity to gold.** Per-ticker weekly regression of stock returns on gold returns. Produces structural delta, gamma, asymmetry, confidence, and up/down beta. Three horizon windows: 6M, 12M, 3Y. Follows the Guo/Leung/Ward framework. Output: `data/output/tool_a/tool_a_latest.parquet`.
- **Tool B — corporate finance screening.** Per-ticker fundamental data (AISC, production, net debt, EBITDA, jurisdiction tier, reserve life, etc.) with screening rules + 4 scenario target prices. Output: `data/output/tool_b/tool_b_latest.parquet`. Inputs come from a manual SQLite store the user maintains.
- **Combined view** at `/` shows both tools' scores side-by-side per ticker.

Both tools rank stocks by **upside attractiveness**. There is currently **nothing that ranks downside risk, hedges, or short candidates.**

Architecture context:
- Universe: 60 active tickers (varies — see `config/universe.yaml`).
- Data: ~36 months of weekly observations per ticker. So ~150 weekly obs per ticker. This is **small** for any tail-statistics work.
- The workspace UI is now lens-aware (recent milestone — see `golden_vector/serve/detail_page.py`). The `?lens=` parameter on the detail page was designed exactly so new tools can plug in without rewriting the page.
- The replay manifest milestone just shipped, so any new pipeline we add will automatically get replay-able provenance.
- Hard rules from `CLAUDE.md`: no mixed-currency analytics, no ad-hoc horizon additions, no composite scores before raw data QA passes, no hidden manual overrides. Every transformation must be testable, versioned, auditable.

## The strategic gap

Emanuel mostly holds long positions in gold miners. If gold drops, his portfolio loses money. He wants a tool — or set of tools — to help him **identify which stocks are most likely to drop hardest when gold drops**, so he can either:

- Buy put options on those names (hedge his long book)
- Short them outright (directional bet)
- Avoid adding to them (defensive screening)

He framed this as "the short/put-finder tool" but on reflection the more honest framing is: **a downside-risk and hedge-candidate tool**. Whether the user shorts or buys puts or just trims is their call; the tool's job is to surface the names.

## The direction we sketched (and explicitly invite you to challenge)

After Q&A with Emanuel, we landed on this:

### Tool C — market-side downside (mirrors Tool A)

- New pipeline producing `data/output/tool_c/tool_c_latest.parquet`.
- New CLI command: `python main.py tool-c`.
- New overview page `/tool-c`. New detail-page lens `?lens=tool-c`.
- **Three downside metrics computed side-by-side per ticker, plus a composite:**
  1. **Down-only beta to gold** — regression of stock returns on gold returns, restricted to weeks where gold dropped. Higher = drops more when gold drops. Tool A already has up/down beta logic; reuse if cleanly possible.
  2. **Tail conditional loss (CVaR-style)** — average stock return in the worst 5% of gold-drop weeks. Captures asymmetric tail risk.
  3. **Max-drawdown frequency** — count of weeks where the stock dropped more than X% (Y to be tuned) AND gold also dropped. Empirical, coarse, robust.
  4. **Composite** — equal-weight z-scores of the three metrics. Simplest defensible weighting.
- User sees all four columns so they can compare metrics and notice disagreements.

### Tool D — corporate-finance fragility (mirrors Tool B)

- New pipeline producing `data/output/tool_d/tool_d_latest.parquet`.
- Reuses Tool B's manual inputs (AISC, production, net debt, EBITDA, cash). **No new data collection in v1.**
- **Two signal groups for v1:**
  1. **Margin compression** — AISC / spot gold ratio. High = thin margin, vulnerable to gold price drops.
  2. **Balance-sheet fragility** — net debt, cash position, net debt / EBITDA. Highly levered companies break first when revenue compresses.
- **Explicitly out of scope for v1:**
  - Operating resilience (reserve life, jurisdiction tier) — could add later
  - Production momentum / guidance miss risk — needs new data, deferred

### Combined view

- Tool C and Tool D are NEVER fused at the data layer. They're two independent pipelines.
- Combined view shows both rankings side-by-side per ticker.
- A composite Tool C+D score may come later in the UI (not in v1).

## Data constraints to keep honest

- 60 tickers × ~150 weekly observations each.
- 5% tail at 150 obs = ~7 observations. Tail-CVaR is noisy on this data.
- Gold-drop weeks are a subset of those 150 obs; the conditional subsets are smaller still.
- Some tickers have shorter history (new IPOs, post-merger, etc.).
- Manual Tool B inputs are user-maintained and may be stale or incomplete.

## Honest tensions in our sketch — we want you to weigh in

These are things Emanuel and I haven't resolved well:

1. **Is a separate Tool C even the right shape?** Tool A already computes up/down beta. Could Tool C be a "downside lens" on Tool A's existing output instead of a new pipeline? The latter is more code; the former might be too thin a re-projection.
2. **Are three metrics + composite the right number?** Too few = single point of failure. Too many = unhelpful complexity for a beginner user.
3. **Tail CVaR on 7 weekly observations is statistically thin.** Should we lengthen the tail (e.g., worst 10% instead of 5%) to get ~15 observations? Or drop tail-stats entirely in favor of more robust alternatives?
4. **Max-drawdown threshold X% — what's the right value?** −5% per week? −10%? Tunable in config but the default matters a lot.
5. **Tool D's "balance sheet fragility" overlaps Tool B's screening.** What's the actual incremental signal Tool D provides over what a user already sees in Tool B?
6. **Is the AISC/spot-gold ratio a stock-specific signal or a sector signal?** If gold drops, every miner's margin compresses. The ratio's spread across tickers may be the real signal, not the level.
7. **Are we missing macro / cross-sectional signals?** E.g., relative-strength vs. the GDX ETF, correlation breakdowns, factor exposures.
8. **Are we missing options-implied signals?** Implied vol skew is the market's own downside estimate. Out of scope unless paid data, but worth flagging as a deliberate gap.
9. **Composite weighting** — equal-weight z-scores is our default. Is there a better simple choice (PCA, rank-aggregation, voting)? Or is equal-weight actually best because it's transparent?

## What we'd LIKE to see in your response

Structure your output document however you think works best. Suggested sections, but adapt:

- **Verdict on the C/D split.** Does the architectural shape hold up, or is there a better framing?
- **Critique of the three Tool C metrics.** Which would you keep, drop, replace?
- **Critique of Tool D's scope.** Is "margin compression + balance sheet" sufficient? Too much?
- **Metrics or signals we haven't considered.** Be specific. Cite where they'd live.
- **Risks.** Where will this v1 mislead users? What's the most likely "this looks scary but actually means nothing" pattern?
- **What to cut.** What's nice-to-have we should defer?
- **What to add.** What's load-bearing we'd regret skipping?
- **Open questions for Emanuel.** Things that aren't your call but he should answer before the plan is written.

## Format and length

- Markdown file at `reviews/codex/codex_tool_c_d_ideas_and_critique.md`.
- Aim for ~1000–2000 words. Long enough to be substantive, short enough to be readable in one sitting.
- Use file:line references when relevant to existing code.
- No code in this document — only ideas, prose, and tables.
- Be specific. "Add more signals" is not useful; "add a measure of relative-strength vs. GDX, which would surface stocks underperforming the sector before a broader drop" is useful.

## What happens after your document

Emanuel reads your document. He decides what to incorporate. Then I write the actual plan (`reviews/codex/claude_tool_c_d_plan.md`) drawing on both your ideas and our original sketch. You will then review THAT plan before implementation starts, in the usual cycle.

This brainstorming step is about generating ideas. The next step (plan) is about converging.

Go.
