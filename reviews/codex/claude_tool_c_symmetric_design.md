# Tool C — redesign: symmetric gold sensitivity & behavior ranking (up AND down)

**Author:** Claude Code (Opus 4.8)
**Date:** 2026-06-04
**Supersedes:** the Tool C section of `claude_tool_c_d_plan_v3.md` (which was downside-only).
**Pairs with:** `claude_tool_d_gold_stressed_scorecard_design.md` (Tool D, also now symmetric).
**Why:** Emanuel wants Tool C to rank **both upside and downside** — not just "which stocks fall hardest when gold falls," but also "which stocks rise hardest when gold rises." This matches the whole tool's both-directions philosophy (puts for gold-down, calls for gold-up).

## The reframe
> **Tool C = a symmetric "gold sensitivity & behavior" ranking.** It produces **two** ranks per miner:
> - a **DOWNSIDE rank** — how hard/reliably the stock falls when gold falls (→ the best **put** targets), and
> - an **UPSIDE rank** — how hard/reliably the stock rises when gold rises (→ the best **call** targets).

Tool C is about the **stock's price behavior** (Tool D is about the company's economics — the two are complementary).

## The metrics — mirrored up and down
Both use the same weekly gold-return regimes (worst-N% gold weeks for downside; best-N% gold weeks for upside) over the same weekly series Tool A's betas use.

| Dimension | DOWNSIDE (put targets) | UPSIDE (call targets) |
|---|---|---|
| Beta | `down_beta_core` (falls per 1% gold drop) | `up_beta_core` (rises per 1% gold gain) |
| Relative behavior | **relative weakness:** % of gold-DOWN weeks the stock underperformed gold *and* GDX | **relative strength:** % of gold-UP weeks the stock outperformed gold *and* GDX |
| Hit rate | **downside hit-rate:** % of gold-down weeks the stock fell ≥ X% | **upside hit-rate:** % of gold-up weeks the stock rose ≥ X% |
| Volatility | `downside_volatility_52w` (violent drawdowns) | (upside capture / no "risk" vol — use relative strength instead) |
| Tail (flagged thin) | avg return in the **worst** 10–20% gold weeks | avg return in the **best** 10–20% gold weeks |

Each dimension blends its **robust** metrics (beta, relative behavior, hit-rate; downside vol on the down side) into a **0–100 percentile rank**, with the thin tail metric **shown but flagged low-confidence and excluded from the rank** (same statistics lesson as before).

## Two ranks + the asymmetry
- `tool_c_downside_rank` (0–100) + downside tags (`steep_down_beta`, `persistent_relative_weakness`, `frequent_deep_drops`).
- `tool_c_upside_rank` (0–100) + upside tags (`steep_up_beta`, `persistent_relative_strength`, `frequent_strong_rallies`).
- **The asymmetry is itself the signal.** A miner with a high downside rank but low upside rank = *"falls hard, rises little"* = an ideal **put** target. High upside + low downside = an ideal **call** target. (Tool A already publishes `asymmetry_ratio_core` — surface it alongside as context.)

## How you use it
- **CLI:** `python main.py tool-c` → a parquet with both ranks per ticker.
- The ranks feed the **Candidate Finder**: the **bearish/put lens** ranks by `tool_c_downside_rank`; the **bullish/call lens** ranks by `tool_c_upside_rank`. Combined with usable-puts/calls and Tool D's gold-stressed quality, you get the perfect put target *or* the perfect call target.

## Build notes / reuse
- Reuse Tool A's `build_structural_weekly_series` (one weekly convention, consistent with the betas).
- The gold-regime classifier now produces **both** tails: worst-N% gold weeks (downside) and best-N% gold weeks (upside).
- The relative-weakness function generalizes to relative-weakness (down) and relative-strength (up) — same code, opposite comparison and regime.
- Each metric carries its **own** post-intersection event count; GDX-relative metrics use the intersection date range.

## Honest caveats (unchanged)
- Both ranks are **descriptive, not return forecasts** (Atilgan/Levi-Welch-Karolyi: beta describes behavior, doesn't predict reward). High up-beta ≠ "will earn you more."
- The **tail metrics are thin** (few worst/best gold weeks) — flagged low-confidence, kept out of the headline ranks.

## What changes in the C/D plan
- Tool C's schema (§2d/§2f of the v3 plan) gains the **upside mirror**: `up_beta_core` re-export, `rel_strength_vs_gold_pct`/`rel_strength_vs_gdx_pct` (+counts), `upside_hit_rate_10pct` (+count), `tail_avg_return_best10/20pct` (flagged), and a second rank `tool_c_upside_rank` with upside tags.
- The gold-regime feature computes both tails; relative-behavior generalizes to up/down.
- Everything else (provenance, percentile-helper reuse — the same `oriented_percentile` the Candidate Finder uses, eligibility, config) is unchanged.

## Net: both tools are now symmetric
- **Tool C (symmetric):** stock price behavior — downside rank (puts) + upside rank (calls).
- **Tool D (symmetric):** company economics at a tunable gold price — quality scorecard usable up or down.
- Both feed the Candidate Finder, which already supports a bearish and a bullish lens. The whole system now serves "bet gold down" and "bet gold up" symmetrically.
