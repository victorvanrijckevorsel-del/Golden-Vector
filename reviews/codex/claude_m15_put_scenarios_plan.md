# Plan: M1.5 — Put Scenario Calculator + Comparison View

**Author:** Claude Code
**Branch:** `dev-vic`
**Date:** 2026-06-02 (v4 after Emanuel workflow conversation)
**Reviewer:** Codex — graded `NEEDS CHANGES` on v1; v2 addressed every finding; v3 added strategy-generic math + portfolio totals; v4 reflects 2026-06-02 workflow conversation

## v4 changelog (against v3 — based on 2026-06-02 thinking-together session)

Emanuel clarified his actual usage pattern and decision process. Three takeaways shaped v4:

| Insight | Resulting change |
|---|---|
| **Reads the report every few weeks**, not daily; uses it to decide whether to roll positions or place new hedges | Multi-window context (1d/1wk/1mo gold + GDX) confirmed essential and kept as already specified in v3 §2f |
| **Doesn't want binary triggers** ("FIRING/OK" verdicts); prefers to read numbers himself and form his own view | DROPPED the "Decision Triggers" block I'd proposed mid-conversation; DROPPED single-threshold gold-momentum logic; DROPPED portfolio-loss threshold logic. The report stays data-rich, opinion-free. |
| **No portfolio yet**; can't set realistic portfolio-loss thresholds | Portfolio Totals section (v3) stays in the plan but is gracefully skipped when holdings.yaml is empty. No threshold-flag logic added. |
| **The single most useful entry-point view: "list of stocks from more sensitive to less sensitive"** | NEW §2i — **"Sensitivity Ranking" section** added. Sorts all 60 universe tickers by Tool A's existing `down_beta_12m` field (descending). Top of list = most leverage to gold drops = best put-hedge / speculation candidates. NEW module `hedge/sensitivity_ranking.py`. |

The net effect: v4 is **simpler in spirit** (no thresholds, no triggers, no verdict overlays) but adds one new section that maps to how Emanuel actually wants to read the data. This is also a partial preview of Tool C (M3) — the basic sort lives in M1.5; M3 will enrich the same ranking with CVaR-style metrics + relative weakness vs GDX + asymmetry tags.

## v3 changelog (preserved for reference)

## v3 changelog (against v2)

Emanuel locked two scope expansions on 2026-06-02:

| Expansion | Where addressed in v3 |
|---|---|
| **Strategy-generic math layer** — code all 4 cases (buy/sell put/call) so the math is built once and future strategies are small additions | §2b adds `black_scholes_call_price()`. §3 scenarios module gains an internal `OptionStrategy` enum (`LONG_PUT`, `SHORT_PUT`, `LONG_CALL`, `SHORT_CALL`). §4 adds the call price formula + the 4 P&L sign-rules. The **M1.5 REPORT still shows only `LONG_PUT`** (the hedge-the-portfolio use case); other strategies are computable via the public API but not surfaced in the markdown. Adding them to a future report is small. |
| **Portfolio aggregation** — total downside per gold scenario + total hedge cost to protect X% of exposure | New §2h "Portfolio Totals" section and new `portfolio_totals.py` module. New report section between header and per-position grids. Renders only when `holdings.yaml` is non-empty (skipped silently if empty, same as the existing holdings section). |

These expansions add roughly +200 lines code + ~80 lines tests + ~50 lines report formatting. M1.5 grows from 9 steps to 11.

## v2 changelog (against Codex review — preserved for reference)
**Related:**
- [reviews/codex/codex_review_claude_m15_plan.md](codex_review_claude_m15_plan.md) — v1 review (what v2 responds to)
- [reviews/codex/claude_hedge_readiness_plan.md](claude_hedge_readiness_plan.md) — M1 plan v2
- [[inflight-planning-m15-put-speculation]] memory

## v2 changelog (against Codex review)

| Codex finding | Where addressed in v2 |
|---|---|
| R1 — Linear stock + BS combo | Acceptable for v1; §2c column headers now require explicit "model-based scenario, not forecast" framing; the BS-priced column is named distinctly from intrinsic value |
| R2 — Constant IV must be explicit | §2c, §2d column headers REQUIRE "Current value (BS, const-IV)" text — not optional |
| **R3 — Stock-clamp vs BS spot<=0 conflict (BLOCKING)** | §4 redefined: extend `black_scholes_put_price` to handle `spot=0` as the BS limit value (`strike × e^(-rT)`) instead of returning None. Clamped rows now have a current-value column populated cleanly. |
| R4 — Negative/near-zero down-beta breakeven | §4 adds explicit handling: `down_beta <= 0.1` triggers "down-beta does not support gold-down put thesis" annotation; no breakeven number shown for these tickers |
| R5 — 100-share multiplier visibility | §5 report mock and §7 acceptance now require "assumes standard 100-share US equity option multiplier" text visible near every scenario table |
| **R6 — CLI flags scoped but cli.py not in module layout (BLOCKING)** | §2b adds `golden_vector/cli.py` (edit) to the module layout. §3 specifies `--sort-by`, `--quantity`, and `--max-tickers` flag wiring. New tests for argument parsing. |
| R7 — Header verdict thresholds arbitrary | §4 adds explicit "heuristic" labeling in header output; new boundary-condition tests; thresholds NOT yet config-tunable (deferred to a future iteration) |
| **AF1 — M1 only renders candidate grids INSIDE holdings loop (BLOCKING)** | New §2g defines a "Speculation Candidates" section in the report — universe-level, independent of holdings. M1.5 ADDS this section rather than extending the per-position grid. Holdings remains untouched. |
| AF2 — Selection rule undefined | §2g specifies the selection rule: default = all `directly_hedgeable` tier tickers sorted by cross-sectional IV percentile ascending (cheap-IV first). Configurable via `--max-tickers` CLI flag (default 15) and `optionability_tier_min` config field. |
| AF3 — Use `CandidatePut` type, not `dict` | §3 dataclasses now use the `CandidatePut` type from M1's `golden_vector/hedge/candidate_puts.py` |
| AF4 — Header data sources via manifest, not hardcoded | §3 `header_context` reads `latest_options_manifest.refresh_run_id` and `benchmark_snapshot_paths`; graceful "data unavailable" output if either is missing |

---

## 0. The simplest thing that could work

> **Add a P&L scenario module that, for each candidate put already in the M1 report, prints a 5-row table (gold flat / −5% / −10% / −15% / −20%) showing implied stock price, put value at expiry, put value if closed today (Black-Scholes re-priced), per-contract P&L at both horizons, and net P&L for a default quantity (5 contracts, configurable). Add a cross-ticker comparison view sorted by P&L at gold −10%. Add a header bar showing gold + GDX 1d/1wk/1mo moves and per-ticker implied-move-vs-modeled-downside sanity check. No new ingestion. No new UI. ~150 lines of new code + ~80 lines of tests + ~50 lines of report formatting.**

Everything below justifies and scopes that baseline.

---

## 1. Current state (verified 2026-06-01)

### What M1 already produces that M1.5 reads (no re-derivation)

| Source | Field | Used by M1.5 for |
|---|---|---|
| `data/output/tool_a/tool_a_latest.parquet` | `down_beta_core`, `down_beta_12m`, `confidence_score`, `confidence_label`, `r_squared_12m` | Translating gold scenarios into implied stock prices |
| `data/output/tool_b/tool_b_latest.parquet` | `share_price_usd` | Current stock price as the base for scenario calculations |
| `data/intermediate/options_features/<TICKER>.parquet` (M1 step 6) | `atm_iv_30d/60d/90d`, `put_iv_25d_*`, `iv_skew_*`, `implied_move_*`, `optionability_tier` | Implied move per ticker (already computed in M1); IV for BS re-pricing |
| `golden_vector/hedge/candidate_puts.py` (M1 step 8) | `build_candidate_put_grid()` returns 30/60/90d candidates with strike/expiry/bid/ask/mid/OI/volume/IV/delta/delta_gap | The grid M1.5 enriches with scenario tables |
| `data/intermediate/status/latest_options_manifest.json` | `risk_free_rate` | BS re-pricing input |
| `data/runs/<run_id>/snapshots/benchmarks/GDX.parquet` | Daily close history | Header bar GDX moves |
| `data/runs/<run_id>/snapshots/raw_gold.parquet` | Daily gold close | Header bar gold moves |
| `golden_vector/features/black_scholes.py` (M1 step 5) | `black_scholes_delta` (used for delta sign + sanity), `normal_cdf` | BS option-price computation |

### What does NOT exist yet that M1.5 needs

- Black-Scholes **price** function (we only have delta + CDF). Need `black_scholes_put_price(spot, strike, T, r, sigma)`. ~10 lines.
- Scenario module — computes implied stock price + expiry value + current-value re-pricing.
- Comparison view — flattens scenarios across tickers, sorts.
- Header context module — reads recent gold + GDX history, computes 1d/1wk/1mo deltas.
- Implied-move sanity check — pulls existing `implied_move_60d` from features + computes Tool A's modeled downside, surfaces the comparison.
- Configurable hypothetical quantity — extend `config/hedge_readiness.yaml` (which M1 step 10 just added).
- Integration hooks in `golden_vector/hedge/report.py` (M1 step 11).

### Dependencies (timing)

M1.5 cannot start until M1 ships. Specifically required from M1:
- Step 11 `hedge/report.py` exists with a real markdown-emit function (M1.5 hooks into it)
- Step 10 `config/hedge_readiness.yaml` is committed with the v1 schema (M1.5 adds 2 fields)
- Step 12 — `update-data --options` actually populates options features (so M1.5 has real data to read)

If Codex's M1 self-review surfaces blocking issues, M1.5 timing slips proportionally.

---

## 2. Architecture

### 2a. Decisions locked (from 2026-06-01 thinking-together session)

| Decision | Choice | Why |
|---|---|---|
| Use case framing | Tool serves both hedging AND speculation; same CLI command (`hedge-readiness`) | Same math; no fork |
| P&L valuation horizon | **Both**: expiry value AND current value (Black-Scholes re-priced) | Honest about "if I close early" case; M1 step-5 BS already half-done |
| Default gold scenarios | flat, −5%, −10%, −15%, −20% (configurable) | Standard severity ladder; covers mild to severe |
| Comparison view default sort | P&L at gold −10% | "Meaningful but not catastrophic" anchor |
| Default hypothetical quantity | 5 contracts (configurable in `config/hedge_readiness.yaml`) | Round number; small enough for retail |
| Stock-price model under scenarios | Linear: `current_price × (1 + down_beta_core × gold_pct_change)` | Tool A's down-beta is the published model; using it consistently |
| BS re-pricing IV | Hold IV constant at the chain-observed value | Simplest honest assumption; volatility skew modeling is out of scope |
| BS re-pricing time | Hold time-to-expiry constant ("if this happened today") | "If gold moves before expiry" interpretation; clearer than "T minus some delta" |
| Implied stock price clamping | Clamp to zero — `max(0, current_price × (1 + down_beta × gold_pct))` | Linear model can produce negative prices for extreme scenarios + high beta. Surface a warning when clamping triggers. |
| Naming | Keep `hedge-readiness` command; speculation framing documented in §5 sample output | One door, multiple use cases |

### 2b. New module layout (v2 — adds cli.py per Codex R6)

```
golden_vector/
  hedge/
    scenarios.py            # NEW — implied stock price + put scenario tables per candidate
    comparison.py           # NEW — flatten + sort across tickers for the "best leverage" view
    header_context.py       # NEW — gold/GDX moves + implied-move sanity check per ticker
    speculation_section.py  # NEW (v2 — Codex AF1) — universe-level candidate-puts section
    report.py               # EDIT (M1 step 11) — call into the new modules and emit sections
  features/
    black_scholes.py        # EDIT — add `black_scholes_put_price()` AND `black_scholes_call_price()` (v3 — strategy generic)
  hedge/
    portfolio_totals.py     # NEW (v3) — aggregate per-position scenarios into portfolio downside + hedge-cost cards
    sensitivity_ranking.py  # NEW (v4) — sort universe tickers by Tool A's down_beta_12m, top-down entry-point view
  cli.py                    # EDIT (v2 — Codex R6) — add --sort-by, --quantity, --max-tickers flags to hedge-readiness subcommand
config/
  hedge_readiness.yaml      # EDIT — add fields: default_scenario_quantity, default_scenarios, optionability_tier_min, max_tickers_speculation_section
tests/
  test_scenarios.py            # NEW (covers all 4 OptionStrategy cases per v3)
  test_comparison.py           # NEW
  test_header_context.py       # NEW
  test_speculation_section.py  # NEW (v2 — Codex AF1)
  test_portfolio_totals.py     # NEW (v3) — portfolio aggregation tests
  test_sensitivity_ranking.py  # NEW (v4) — universe-wide sort tests, null/negative beta handling, missing options data
  test_black_scholes.py        # EDIT — put price + call price + spot=0 limit case + put-call parity
  test_hedge_report.py         # EDIT — universe-level section + portfolio totals + CLI flag plumbing
  test_cli_hedge_readiness.py  # NEW (v2 — Codex R6) — argument parsing tests
```

### 2c. Schema additions

Per-candidate-put scenario table (rendered inline in the report, not persisted as a new column — see §8 out-of-scope for why). For each candidate (one of the 30/60/90d candidates already in the report):

| Column | Computation |
|---|---|
| `gold_pct_change` | One of the configured scenarios (e.g., 0.0, -0.05, -0.10, -0.15, -0.20) |
| `implied_stock_price` | `max(0, current_price × (1 + down_beta_core × gold_pct_change))` |
| `expiry_value_per_contract` | `max(0, strike − implied_stock_price)` |
| `current_value_per_contract` | Black-Scholes put price with spot=implied_stock_price, K=strike, T=days_to_expiry/365, r=risk_free_rate, σ=IV |
| `pnl_per_contract_at_expiry` | `expiry_value − premium_paid_per_contract` |
| `pnl_per_contract_if_closed_today` | `current_value − premium_paid_per_contract` |
| `net_pnl_at_expiry` | `pnl_per_contract_at_expiry × quantity × 100` (options multiplier) |
| `net_pnl_if_closed_today` | `pnl_per_contract_if_closed_today × quantity × 100` |
| `stock_clamped_at_zero` | bool — true if `current_price × (1 + down_beta × gold_pct)` was negative |

One additional computed field per candidate (above the table):

- `breakeven_gold_pct_at_expiry`: the gold drop that makes expiry P&L exactly zero. Solve `strike − current_price × (1 + down_beta × x) = premium_paid`. Closed-form: `x = ((strike − premium_paid) / current_price − 1) / down_beta`.

### 2d. Comparison view schema

A separate section in the report, one row per (ticker, horizon) candidate:

| Column | Source |
|---|---|
| `ticker` | Candidate's ticker |
| `horizon` | 30d / 60d / 90d |
| `strike` | From candidate grid |
| `expiry` | From candidate grid |
| `premium_mid` | Mid of bid/ask |
| `delta_gap` | From candidate grid (how far from −0.25 target) |
| `breakeven_gold_pct` | From §2c |
| `pnl_per_contract_at_-5%`, `-10%`, `-20%` | From §2c (these three columns shown; full table available via verbose flag) |
| `pnl_per_dollar_premium_at_-10%` | `pnl_per_contract_at_-10% / premium_paid_per_contract` — return-on-capital metric |

Sortable. Default: `pnl_per_contract_at_-10%` descending. CLI flag `--sort-by` lets user pick a different column.

### 2e bis. Speculation Candidates section (NEW in v2 — Codex AF1)

**This is the headline change in v2.** M1's report only renders candidate grids inside the holdings loop (verified at `golden_vector/hedge/report.py:196`). When `holdings.yaml` is empty (Emanuel's reframed case), there are zero candidate grids. M1.5 cannot "extend" something that isn't rendered.

The fix: M1.5 adds a new **"Speculation Candidates"** section that always renders, independent of holdings. It iterates over the optionable subset of the universe and, for each ticker, emits the candidate-puts grid (reused via M1's `build_candidate_put_grid`) plus M1.5's scenario tables.

**Selection rule (per Codex AF2):**
1. Filter universe tickers to those with `optionability_tier == "directly_hedgeable"` (from M1's options features file). Config field `optionability_tier_min` lets the user lower the bar to `"thin"`.
2. Sort by `iv_percentile_cross_sectional` ascending (cheap-IV first). Cheap IV is more relevant for buying puts.
3. Cap at `--max-tickers` (default 15, config-tunable). Below the cap, the speculation section stays scannable; users wanting more drop the cap or rerun with a larger value.

**Behavior with holdings:**
- When `holdings.yaml` is non-empty, both sections render: per-position grids (M1's existing behavior, unchanged) AND the speculation section.
- A small deduplication note: tickers present in holdings still appear in the speculation section. This is intentional — speculation framing (raw scenarios across candidates) is distinct from hedging framing (coverage % vs target). The cost is repetition; the win is the universe view stays complete.

**Section ordering:**
1. Header context
2. Holdings section (if any)
3. Proxy hedges (M1's existing section, holdings-only)
4. **Speculation Candidates (M1.5 NEW)**
5. Cross-ticker comparison view (M1.5 NEW)
6. Run summary (M1's existing)

### 2h. Portfolio Totals section (NEW in v3)

When `holdings.yaml` is non-empty, the report adds a "Portfolio Totals" block between the header and per-position grids. When holdings is empty, this section is skipped silently.

For each gold scenario in `default_scenarios`:
- `portfolio_value_at_scenario` — sum of `shares × implied_stock_price` across all holdings (uses Tool A down-beta per ticker, same linear model as §4a)
- `portfolio_loss_dollars` — `current_total_value − portfolio_value_at_scenario`
- `portfolio_loss_pct` — `portfolio_loss_dollars / current_total_value`

Plus hedge-cost calculations for each `protection_level` in config (default `[0.5, 1.0]`):
- For each protection level X, compute the cost to buy `LONG_PUT` candidates that cover X% of each position's notional at the 60d horizon. Sum across positions.
- Output: `hedge_cost_for_<X%>` dollars + as % of portfolio.

A short interpretive note appended: e.g. *"Hedging 50% of exposure costs 1.7% of portfolio value at current premiums"*.

Schema (rendered in report, not persisted):

| Column | Notes |
|---|---|
| `gold_pct_change` | One scenario row each |
| `portfolio_value_at_scenario` | After-shock value, summed across positions |
| `portfolio_loss_dollars` | Current value − scenario value |
| `portfolio_loss_pct` | Loss as % of current value |
| `hedge_cost_50pct` | $ premium to buy 60d LONG_PUTs covering ~50% of each position's notional |
| `hedge_cost_100pct` | $ premium to cover 100% |

### 2j. Final report section order (NEW in v4 — explicit, was implicit before)

The full M1.5 report renders in this order. Sections marked `[conditional]` are skipped silently if their data is unavailable; the rest always render.

1. **Header context** — gold + GDX 1d/1wk/1mo moves; implied-move-vs-modeled-downside table (v3 §2f)
2. **Sensitivity Ranking** — universe-wide sort by `down_beta_12m` (v4 §2i) — **the user's entry point**
3. **Portfolio Totals** `[conditional: holdings non-empty]` — total downside per gold scenario + hedge cost (v3 §2h)
4. **Per-position scenarios** `[conditional: holdings non-empty]` — for each holding, candidate puts + scenario tables
5. **Speculation Candidates** — universe-level candidate puts + scenarios for top-N optionable tickers (v2 §2e bis)
6. **Cross-ticker comparison view** — flat sortable table across all candidates (§2d)
7. **Proxy hedges** `[conditional: holdings non-empty AND contains non-optionable names]` — down-beta similarity mappings (M1 baseline)
8. **Run summary** — provenance (M1 baseline)

The sensitivity ranking deliberately comes BEFORE portfolio-specific sections because Emanuel's reframed primary workflow is "see what's most sensitive, decide what to do" — universe-wide context first, position-specific drill-down second.

### 2i. Sensitivity Ranking section (NEW in v4)

The single most useful entry-point view for Emanuel's workflow: a universe-wide list of all 60 tickers sorted by Tool A's `down_beta_12m` descending. Top of list = stocks that move MOST when gold drops = best leverage for put hedges and gold-down speculation.

This is a **partial preview of Tool C (M3)**. Tool C will replace this with richer downside metrics (CVaR-style tail averages, GDX relative weakness, asymmetry composite). M1.5 ships the simplest version because Tool A already publishes everything needed.

**Renders unconditionally** — works with empty holdings (Emanuel's current case) AND when holdings are populated.

Schema (rendered in the report, not persisted as new parquet — pure presentation):

| Column | Source / computation |
|---|---|
| `rank` | 1-indexed position in the sorted list. Ineligible names (Tool A `score_eligible=False`) get rank `null` and sort to the bottom. |
| `ticker` | Universe ticker symbol |
| `down_beta_12m` | Read directly from `tool_a_latest.parquet`. Null if Tool A had no data. |
| `up_beta_12m` | Read directly from `tool_a_latest.parquet`. Surfaced for asymmetry context — a stock with high down-β AND low up-β is a stronger put-hedge candidate (asymmetric exposure) than one with high down-β AND high up-β (just volatile). |
| `confidence_label` | From Tool A (`high` / `medium` / `low`) — tells the user whether the beta estimate is trustworthy |
| `iv_percentile_cross_sectional` | From M1's options features. Tells the user if puts are cheap RIGHT NOW on this name. Null for non-optionable. |
| `pnl_at_minus10_60d` | P&L per contract for the 60d ~25-delta put at the gold −10% scenario. Reuses the scenarios module from §3 (with `strategy=LONG_PUT`). Null when no usable 60d candidate exists. |
| `optionability_tier` | `directly_hedgeable` / `thin` / `none` — from M1's options features |
| `notes` | List of short tags: `foreign listing` / `low confidence` / `no usable 60d candidate` / `down-beta too small` (per §4c) — empty list when nothing to flag |

**Sort behavior:**
- Default: `down_beta_12m` descending (most-sensitive first)
- Ineligible names (Tool A `score_eligible=False`) sort to the bottom regardless
- Null down-beta values sort to the bottom (with a note explaining why)
- Configurable via `--sort-by` CLI flag (existing v2 flag — extended to accept `down_beta_12m` and `up_beta_12m` choices)

**No truncation by default.** All 60 universe tickers appear. The user gets a top-to-bottom view of the entire investable universe ordered by structural gold sensitivity. If the user wants a shorter view, the existing `--max-tickers` flag (v2) caps the section.

### 2f. Header context schema

A small block at the top of the report:

```
Gold: $2,058/oz   (1d -0.4%   1wk -2.1%   1mo -3.5%)
GDX:  $32.40      (1d -0.6%   1wk -3.4%   1mo -5.8%)

Implied-move-vs-modeled-downside (60d horizon, optionable tickers):
  Ticker    Implied move    Modeled (gold -10%)    Verdict
  NEM       ±5.8%           -14.2%                 model > market (puts look attractive)
  AEM       ±6.4%           -12.7%                 model > market
  KGC       ±7.2%           -11.5%                 model ~= market
  ...
```

"Verdict" rule: `model_downside > 1.5 × implied_move` → "model > market"; within ±50% → "model ~= market"; `model_downside < 0.67 × implied_move` → "market > model".

This single block tells you at a glance whether the options market is pricing more or less downside than Tool A's structural model. **High-information density.**

---

## 3. Module summaries

### `golden_vector/features/black_scholes.py` (edit)

Add one function (~10 lines):

```python
def black_scholes_put_price(
    *,
    spot: float, strike: float, time_to_expiry_years: float,
    risk_free_rate: float, implied_volatility: float | None,
) -> float | None:
    """European put price via standard Black-Scholes. Returns None for degenerate inputs."""
    if spot <= 0 or strike <= 0 or time_to_expiry_years <= 0:
        return None
    if implied_volatility is None or implied_volatility <= 0:
        return None
    sigma_sqrt_t = implied_volatility * math.sqrt(time_to_expiry_years)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * implied_volatility ** 2) * time_to_expiry_years) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t
    return strike * math.exp(-risk_free_rate * time_to_expiry_years) * normal_cdf(-d2) - spot * normal_cdf(-d1)
```

Uses the existing `normal_cdf`. No scipy. Returns None for the same degenerate inputs as `black_scholes_delta`.

### `golden_vector/hedge/scenarios.py` (~180 lines — expanded in v3 for strategy-generic math)

```python
from enum import Enum
from golden_vector.hedge.candidate_puts import CandidatePut  # v2 — Codex AF3

class OptionStrategy(Enum):
    """v3 — strategy-generic math. M1.5 report uses only LONG_PUT.
    Other strategies are computable via the public API for future use.
    """
    LONG_PUT = "long_put"
    SHORT_PUT = "short_put"
    LONG_CALL = "long_call"
    SHORT_CALL = "short_call"

@dataclass(frozen=True)
class ScenarioRow:
    gold_pct_change: float
    implied_stock_price: float
    stock_clamped_at_zero: bool
    expiry_value_per_contract: float
    current_value_per_contract: float  # never None now (BS spot=0 limit per Codex R3)
    pnl_per_contract_at_expiry: float
    pnl_per_contract_if_closed_today: float
    net_pnl_at_expiry: float
    net_pnl_if_closed_today: float

@dataclass(frozen=True)
class CandidateScenarioBundle:
    ticker: str
    horizon: str
    candidate: CandidatePut  # v2 — typed, not dict
    rows: list[ScenarioRow]
    breakeven_gold_pct: float | None
    down_beta_used: float
    confidence_label: str
    skipped_reason: str | None  # set if down_beta_core <= threshold per Codex R4

def compute_scenario_bundle(
    *, candidate: CandidatePut, current_stock_price: float,
    down_beta_core: float | None, confidence_label: str,
    risk_free_rate: float,
    strategy: OptionStrategy = OptionStrategy.LONG_PUT,  # v3 — generic
    gold_scenarios: tuple[float, ...] = (0.0, -0.05, -0.10, -0.15, -0.20),
    quantity: int = 5,
) -> CandidateScenarioBundle:
    """For one candidate, compute P&L scenarios at multiple gold drops.
    Supports all 4 OptionStrategy cases (v3). M1.5 report passes LONG_PUT
    everywhere; other strategies callable via public API for future use.
    When down_beta_core is None or too small (per Codex R4), returns a bundle
    with skipped_reason set and rows=[].
    """
```

### `golden_vector/hedge/sensitivity_ranking.py` (NEW in v4) (~120 lines)

```python
@dataclass(frozen=True)
class SensitivityRow:
    rank: int | None  # None for ineligible/null-beta names
    ticker: str
    down_beta_12m: float | None
    up_beta_12m: float | None
    confidence_label: str
    confidence_score: float | None
    iv_percentile_cross_sectional: float | None
    pnl_at_minus10_60d: float | None
    optionability_tier: str
    notes: list[str]

@dataclass(frozen=True)
class SensitivityRankingBlock:
    rows: list[SensitivityRow]
    sort_by: str  # "down_beta_12m" / "up_beta_12m" / etc.
    total_count: int
    score_eligible_count: int

def build_sensitivity_ranking(
    *, tool_a_frame: pd.DataFrame,
    options_features: dict[str, pd.DataFrame],
    candidate_grids: dict[str, list[CandidatePut]],
    risk_free_rate: float,
    sort_by: str = "down_beta_12m",
    descending: bool = True,
    max_tickers: int | None = None,
) -> SensitivityRankingBlock:
    """Sort the entire universe by gold-downside sensitivity.

    For each ticker:
      - Read down_beta_12m, up_beta_12m, confidence from tool_a_latest.parquet
      - Read iv_percentile_cross_sectional + optionability_tier from options features
      - For optionable names with a 60d candidate, compute LONG_PUT P&L at gold -10%
        (reuses scenarios.compute_scenario_bundle internally)
      - Build a notes list for any flagged conditions

    Ineligible names (Tool A score_eligible=False) get rank=None and sort to the bottom.
    Null down_beta values sort to the bottom with a 'down-beta unavailable' note.
    """
```

This is the lightest possible Tool C preview — just a sort. Tool C (M3) will replace this implementation with a richer composite score (CVaR-style tail averages, GDX relative weakness, asymmetry composite), but the SHAPE of the section stays the same. Future-compatible.

### `golden_vector/hedge/portfolio_totals.py` (NEW in v3) (~150 lines)

```python
@dataclass(frozen=True)
class PortfolioScenarioRow:
    gold_pct_change: float
    portfolio_value_at_scenario: float
    portfolio_loss_dollars: float
    portfolio_loss_pct: float
    hedge_costs: dict[float, float]  # protection_level → cost in $

@dataclass(frozen=True)
class PortfolioTotalsBlock:
    holdings_count: int
    current_total_value: float
    scenario_rows: list[PortfolioScenarioRow]
    interpretive_notes: list[str]

def compute_portfolio_totals(
    *, holdings: list[Holding],
    tool_a_frame: pd.DataFrame, tool_b_frame: pd.DataFrame,
    candidate_grids: dict[str, list[CandidatePut]],  # per-ticker grids from M1
    risk_free_rate: float,
    gold_scenarios: tuple[float, ...],
    protection_levels: tuple[float, ...] = (0.5, 1.0),
) -> PortfolioTotalsBlock | None:
    """Aggregate per-position scenarios into portfolio downside + hedge cost.
    Returns None when holdings is empty (caller renders nothing).

    For each holding:
      stock_value_under_scenario = shares × implied_stock_price_at_scenario
    Portfolio value = sum across holdings.

    Hedge cost at protection level X% for a holding:
      target_notional = current_stock_price × shares × X
      contracts_needed = ceil(target_notional / (strike × 100))  # for 60d candidate
      cost = contracts_needed × candidate.mid × 100
    Sum across holdings.
    """
```

A small helper inside this module computes the per-holding scenario contribution by reusing `scenarios.compute_scenario_bundle()` math but parameterized with the holding's share count.

### `golden_vector/hedge/comparison.py` (~80 lines)

```python
@dataclass(frozen=True)
class ComparisonRow:
    ticker: str
    horizon: str
    strike: float
    expiry: str
    premium_mid: float
    delta_gap: float
    breakeven_gold_pct: float | None
    pnl_per_contract_minus5: float
    pnl_per_contract_minus10: float
    pnl_per_contract_minus20: float
    pnl_per_dollar_premium_minus10: float | None  # None if premium=0

def build_comparison_table(
    *, bundles: list[CandidateScenarioBundle],
    sort_by: str = "pnl_per_contract_minus10",
    descending: bool = True,
) -> list[ComparisonRow]:
    """Flatten one bundle per candidate into the comparison row list, sorted."""
```

### `golden_vector/hedge/header_context.py` (~80 lines)

```python
@dataclass(frozen=True)
class HeaderContext:
    gold_price: float
    gold_change_1d: float | None
    gold_change_1w: float | None
    gold_change_1m: float | None
    gdx_price: float
    gdx_change_1d: float | None
    gdx_change_1w: float | None
    gdx_change_1m: float | None
    implied_vs_modeled_rows: list["ImpliedVsModeledRow"]

@dataclass(frozen=True)
class ImpliedVsModeledRow:
    ticker: str
    implied_move_60d: float | None
    modeled_downside_at_minus10: float | None
    verdict: str  # "model > market" / "model ~= market" / "market > model"

def build_header_context(
    *, paths: ProjectPaths, options_features: dict[str, pd.DataFrame],
    tool_a_frame: pd.DataFrame, gold_history: pd.DataFrame, gdx_history: pd.DataFrame,
) -> HeaderContext:
    """Compute the header context block."""
```

### `golden_vector/hedge/speculation_section.py` (NEW in v2 — Codex AF1) (~100 lines)

```python
def build_speculation_section(
    *, paths: ProjectPaths,
    options_features: dict[str, pd.DataFrame],
    tool_a_frame: pd.DataFrame, tool_b_frame: pd.DataFrame,
    raw_options_by_ticker: dict[str, pd.DataFrame],
    risk_free_rate: float,
    config: HedgeReadinessConfig,
    sort_by: str = "pnl_per_contract_minus10",
    quantity: int | None = None,
    max_tickers: int | None = None,
) -> list[SpeculationTickerBlock]:
    """Universe-level candidate-puts section. Independent of holdings.

    Selection rule:
      1. Filter to tickers with optionability_tier == "directly_hedgeable"
         (configurable via config.optionability_tier_min).
      2. Sort by iv_percentile_cross_sectional ascending (cheap first).
      3. Cap at max_tickers (default from config, CLI flag can override).

    For each selected ticker:
      - Reuse M1's build_candidate_put_grid() to get 30d/60d/90d candidates
      - For each candidate, compute_scenario_bundle()
      - Bundle into a SpeculationTickerBlock
    """

@dataclass(frozen=True)
class SpeculationTickerBlock:
    ticker: str
    current_stock_price: float
    optionability_tier: str
    iv_percentile_cross_sectional: float | None
    down_beta_core: float | None
    confidence_label: str
    candidates: list[CandidatePut]
    scenario_bundles: list[CandidateScenarioBundle]
    annotations: list[str]  # per-block warnings ("down-beta too small", "stock clamped", etc.)
```

### `golden_vector/cli.py` (EDIT in v2 — Codex R6) (~30 lines added)

Add three flags to the existing `hedge-readiness` subparser:

```python
hedge_parser.add_argument(
    "--sort-by",
    default="pnl_per_contract_minus10",
    choices=["pnl_per_contract_minus5", "pnl_per_contract_minus10",
             "pnl_per_contract_minus20", "pnl_per_dollar_premium_minus10",
             "breakeven_gold_pct"],
    help="Comparison view sort column.",
)
hedge_parser.add_argument(
    "--quantity",
    type=int, default=None,
    help="Hypothetical put-contract quantity for P&L. Default from config.",
)
hedge_parser.add_argument(
    "--max-tickers",
    type=int, default=None,
    help="Cap on speculation-section tickers. Default from config.",
)
```

CLI args propagate through `run_hedge_readiness(...)` into the report-builder. New tests in `test_cli_hedge_readiness.py` confirm argument parsing + default fallback to config.

### `golden_vector/hedge/report.py` (edit — M1 step 11)

Inject four new sections into the report:

1. **Top of report:** header context block (replacing or augmenting whatever step-11 produces today)
2. **Per holding's existing grid (when holdings exist):** the 5-row scenario table from §2c, inline after each per-position candidate grid
3. **NEW Speculation Candidates section (per §2e bis):** independent of holdings; renders for the selected universe tickers
4. **Bottom of report (before run summary):** the comparison view table from §2d, drawing from BOTH holdings-scoped candidates AND speculation-section candidates

These are pure-presentation additions — no change to report file path, file name, or stdout summary format.

---

## 4. The math — concrete

### 4a. Implied stock price under a gold scenario

```
gold_pct_change ∈ {0, -0.05, -0.10, -0.15, -0.20}
raw_implied = current_stock_price × (1 + down_beta_core × gold_pct_change)
implied_stock_price = max(0, raw_implied)
stock_clamped_at_zero = (raw_implied < 0)
```

**Honesty note:** this assumes a linear price response (not lognormal) and constant beta across scenarios. For mining stocks under gold-down scenarios, this is the same assumption Tool A's published model uses, so consistency wins over theoretical refinement.

### 4b. Put values (v2 — Codex R3 handles spot=0 limit)

```
expiry_value = max(0, strike - implied_stock_price)
current_value = black_scholes_put_price(
    spot=implied_stock_price,
    strike=strike,
    time_to_expiry_years=days_to_expiry / 365.0,
    risk_free_rate=risk_free_rate,  # from M1 latest_options_manifest
    implied_volatility=iv,  # from the chain row for this strike
)
```

**Special case for `spot == 0` (when down-beta scenario clamps the stock to zero):** Standard BS returns the limit value of a put when the underlying is worthless — the option will pay full strike at expiry, discounted to today.

```python
# Inside black_scholes_put_price:
if spot == 0:
    return strike * math.exp(-risk_free_rate * time_to_expiry_years)
```

This keeps the clamped row's current-value column populated cleanly (no nulls) and matches the limiting behavior of the BS formula. Tested explicitly.

Note: `time_to_expiry_years` does NOT shrink across scenarios. This is the "if gold moved today, what's the put worth right now" model. The current-value column header must say **"Current value (BS, const-IV)"** per Codex R2 — the constant-IV assumption is visible at every appearance.

### 4b ter. Black-Scholes call price + 4-strategy P&L (NEW in v3)

```python
def black_scholes_call_price(*, spot, strike, time_to_expiry_years, risk_free_rate, implied_volatility):
    if spot == 0:
        return 0.0  # call on a zero-spot underlying is worthless
    # standard params + degenerate checks same as put
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return spot * normal_cdf(d1) - strike * math.exp(-r * T) * normal_cdf(d2)
```

**Put-call parity test (mandatory):** `call_price + strike × e^(-rT) ≈ put_price + spot` at multiple input combinations. Tested explicitly.

**P&L sign rules (the generic part):**

```python
# Per contract, given premium paid/received and intrinsic value at scenario:
if strategy == OptionStrategy.LONG_PUT:
    pnl_per_contract = expiry_intrinsic - premium_paid      # pay premium, earn payoff
elif strategy == OptionStrategy.SHORT_PUT:
    pnl_per_contract = premium_received - expiry_intrinsic  # collect premium, owe payoff
elif strategy == OptionStrategy.LONG_CALL:
    pnl_per_contract = expiry_intrinsic - premium_paid
elif strategy == OptionStrategy.SHORT_CALL:
    pnl_per_contract = premium_received - expiry_intrinsic
```

Where `expiry_intrinsic` is `max(0, strike - implied_stock)` for puts and `max(0, implied_stock - strike)` for calls.

For "current value if closed today", substitute `current_value` (BS-re-priced) for `expiry_intrinsic` in the formulas above.

**Risk to flag** (in §9 v3 additions): short positions have asymmetric risk profiles. SHORT_PUT max loss = `strike × 100 × quantity − premium_received` (if stock goes to zero). SHORT_CALL max loss is unbounded. The math computes scenarios correctly but doesn't display warnings — that's a report-layer concern for whenever short strategies start showing in the report.

### 4c. Down-beta near-zero handling (v2 — Codex R4)

For tickers where `down_beta_core` is small or zero:

```python
DOWN_BETA_MIN_FOR_SCENARIO = 0.10  # configurable

if down_beta_core is None or down_beta_core <= DOWN_BETA_MIN_FOR_SCENARIO:
    annotation = (
        "Down-beta is too small to model meaningful gold-down scenarios "
        f"(value: {down_beta_core}). This ticker's stock does not move "
        "with gold in the way a put thesis would require."
    )
    # Skip scenario rows for this ticker. Emit the candidate grid + annotation only.
    return None  # signal to renderer to skip scenario block
```

No breakeven number is shown for these tickers — it would be misleading. The candidate grid still appears so the user sees there ARE listed puts; they just aren't useful for a gold-down bet on this name.

### 4c. P&L

```
premium_paid_per_contract = candidate.mid_price  # one contract = 100 shares of stock
pnl_per_contract_at_expiry = expiry_value - premium_paid_per_contract
pnl_per_contract_if_closed_today = current_value - premium_paid_per_contract  # None if current_value None
net_pnl_at_expiry = pnl_per_contract_at_expiry × quantity × 100
net_pnl_if_closed_today = pnl_per_contract_if_closed_today × quantity × 100
```

### 4d. Breakeven gold % move

```
# Expiry P&L = 0 when expiry_value = premium_paid
# strike - implied_stock_price = premium_paid
# strike - current_price × (1 + down_beta × x) = premium_paid
# Solve for x:
breakeven_gold_pct = ((strike - premium_paid) / current_price - 1) / down_beta
```

If `down_beta` is None or zero, breakeven is undefined (None). If the resulting `breakeven_gold_pct > 0` (put is already in-the-money via positive gold move — impossible scenario), surface a "put is already ITM" annotation.

### 4e. Implied-move-vs-modeled-downside verdict

```
implied_move_60d = features.implied_move_60d  # already computed in M1 step 6
modeled_downside_at_minus10 = abs(current_price × down_beta × -0.10) / current_price  # = abs(down_beta × 0.10)
# Implied move from straddle is a one-sigma ±X% move; modeled downside is a directional drop estimate.
# Compare magnitudes:
if modeled_downside_at_minus10 > 1.5 × implied_move_60d:
    verdict = "model > market"
elif modeled_downside_at_minus10 < 0.67 × implied_move_60d:
    verdict = "market > model"
else:
    verdict = "model ~= market"
```

---

## 5. Report format — worked example

What the user sees after `python main.py hedge-readiness` runs (M1.5 additions in bold; everything else is M1 baseline).

```
Hedge Readiness Report  (2026-06-01 morning run)

═══ HEADER ═══
Gold: $2,058/oz   (1d -0.4%   1wk -2.1%   1mo -3.5%)            [M1.5 NEW]
GDX:  $32.40      (1d -0.6%   1wk -3.4%   1mo -5.8%)            [M1.5 NEW]

Implied-move-vs-modeled-downside (60d, optionable tickers):    [M1.5 NEW]
  Ticker  Implied move 60d   Modeled (gold -10%)   Verdict
  NEM     ±5.8%              -14.2%                model > market (puts attractive)
  AEM     ±6.4%              -12.7%                model > market
  KGC     ±7.2%              -11.5%                model ~= market
  GOLD    ±4.2%              -7.8%                  model ~= market
  ...

═══ STOCKS RANKED BY GOLD-DOWNSIDE SENSITIVITY ═══           [v4 NEW]
Sorted by structural down-beta (12m). Higher = more sensitive to gold drops.

Rank  Ticker  Down-β (12m)  Up-β (12m)  Confidence  IV %-tile  60d Put @ -10%   Optionable  Notes
 1    KGC     1.85          1.21        high        45th       +$4.50/c         yes         —
 2    NEM     1.42          1.18        high        38th       +$13.20/c        yes         most liquid options
 3    CDE     1.39          1.42        medium      61st       +$8.10/c         yes         —
 4    EQX     1.31          1.20        medium      53rd       +$5.40/c         yes         —
 5    AGI     1.28          1.04        high        47th       +$6.80/c         yes         royalty-light
 6    HMY     1.22          1.14        medium      58th       +$3.40/c         yes         —
 7    IAG     1.19          1.07        medium      52nd       +$5.10/c         yes         —
 8    AU      1.17          1.02        medium      49th       +$3.80/c         yes         —
 9    PRU     1.13          1.05        medium      41st       +$2.90/c         yes         —
 10   MUX     1.10          0.95        low         62nd       +$1.10/c         yes         low confidence
 ...
 11   GOLD    0.72          0.78        high        29th       +$5.80/c         yes         Barrick (lower beta)
 12   FNV     0.61          0.55        high        51st       +$2.10/c         yes         royalty company
 ...
 24   B       0.92          0.88        high        43rd       +$8.40/c         yes         Barrick affiliate
 [24 directly-hedgeable + thin tier ends here]
 25   NGD     0.65          0.62        low         —          —                no          dual-listed, no options
 ...
 60   [40 foreign listings without options data, sorted by down-β if available]

Top of list = puts give you most leverage per gold move.
Bottom of list = name moves less with gold; puts cost less but pay less.
Use this as the entry point — pick top-ranked names, then drill into candidate puts below.

═══ HOLDINGS (skipped — holdings.yaml empty) ═══

═══ CANDIDATE PUTS — by ticker (speculation section) ═══

▍NEM (Newmont) — current $147.50, optionability=directly_hedgeable
Down-β 1.42 (high confidence, r²=0.81), Tool A score eligible

  Horizon  Expiry      Strike  Δ      Δ-gap  Bid    Ask    Mid    OI    Premium % spot
  30d      2026-06-30  145     -0.28  0.03   1.95   2.10   2.03   1240  1.38%
  60d      2026-07-31  142     -0.25  0.00   2.10   2.30   2.20   940   1.49%
  90d      2026-08-29  140     -0.24  0.01   2.95   3.20   3.08   720   2.09%

  ─── P&L scenarios for 60d 142P @ $2.20 mid (quantity 5) ───       [M1.5 NEW]
  Gold scenario    Stock     Expiry value    Current value    P&L/contract (exp)   P&L/contract (now)   Net P&L (5x, exp)
  flat             $147.50   $0.00           $1.85            -$2.20               -$0.35               -$1,100
  -5%              $137.05   $4.95           $5.10            +$2.75               +$2.90                +$1,375
  -10%             $126.60   $15.40          $14.85           +$13.20              +$12.65               +$6,600
  -15%             $116.15   $25.85          $25.20           +$23.65              +$23.00               +$11,825
  -20%             $105.70   $36.30          $35.65           +$34.10              +$33.45               +$17,050
  Breakeven gold move (at expiry): -2.1%

▍AEM — current $180.00, optionability=directly_hedgeable
  [same shape: candidate grid + scenarios per candidate]

▍GFI — current $14.40, optionability=thin
  [thinner grid, scenarios where computable, otherwise "no usable contract at this horizon"]

═══ PROXY HEDGES (for non-optionable tickers) ═══
[M1 baseline — unchanged]

═══ CROSS-TICKER COMPARISON — best leverage for gold -10% ═══       [M1.5 NEW]
Sorted by P&L per contract at gold -10% (descending). Quantity=5 contracts.

Ticker  Horizon  Strike  Expiry      Mid    Δ-gap  Break.   P&L/c -5%   P&L/c -10%   P&L/c -20%   P&L/$ premium -10%
NEM     60d      142     2026-07-31  $2.20  0.00   -2.1%    +$2.75      +$13.20      +$34.10      $6.00 per $1
B       60d      48      2026-07-31  $0.95  0.02   -1.8%    +$1.45      +$8.40       +$22.80      $8.84 per $1
SSRM    60d      8       2026-07-31  $0.30  0.05   -3.9%    +$0.20      +$3.10       +$8.40       $10.33 per $1
GOLD    60d      18      2026-07-31  $0.95  0.01   -1.7%    +$1.10      +$5.80       +$14.20      $6.11 per $1
KGC     60d      12      2026-07-31  $0.40  0.04   -2.6%    +$0.85      +$4.50       +$11.20      $11.25 per $1
...

═══ RUN SUMMARY ═══
[M1 baseline — unchanged]
```

The comparison view tells you instantly: SSRM and KGC give the highest return-on-capital at gold −10%, but NEM gives the largest absolute P&L per contract. Lets you pick by risk preference (small cap, high leverage vs large cap, more stable).

---

## 6. Order of operations

**v4 order: 12 steps (added sensitivity_ranking module).**

| # | Step | Test gate |
|---|---|---|
| 1 | Add `black_scholes_put_price()` AND `black_scholes_call_price()` to `features/black_scholes.py`. Both handle `spot=0` correctly (put returns BS limit, call returns 0). Tests including **put-call parity** (`call + K·e^(-rT) ≈ put + spot`), degenerate inputs, spot=0 cases, reference values. | Suite green; ~10 new tests |
| 2 | Extend `config/hedge_readiness.yaml` with `default_scenario_quantity` (5), `default_scenarios` (list), `optionability_tier_min` (`"directly_hedgeable"`), `max_tickers_speculation_section` (15), **`protection_levels` (list, default `[0.5, 1.0]`)** (v3). Extend `HedgeReadinessConfig` schema. | Suite green |
| 3 | Add `hedge/scenarios.py`. **Includes `OptionStrategy` enum + strategy-generic P&L math (v3)** — supports `LONG_PUT`, `SHORT_PUT`, `LONG_CALL`, `SHORT_CALL`. Tests cover all 4 strategies plus all v2 edge cases. | Suite green |
| 4 | Add `hedge/comparison.py`. Tests for sort by different columns, empty input, single-candidate input. | Suite green |
| 5 | Add `hedge/header_context.py`. Reads paths via `latest_options_manifest.refresh_run_id` + `benchmark_snapshot_paths`. Tests for verdict-band boundaries + graceful missing-data handling. | Suite green |
| 6 | Add `hedge/speculation_section.py` — universe-level candidate-puts section independent of holdings (Codex AF1). | Suite green |
| 7 | Add `hedge/portfolio_totals.py` (v3) — aggregate per-position scenarios + hedge-cost math. Tests: empty holdings returns None, single-position correctness, hedge-cost calculation matches sum-of-positions, ceil-rounding of contracts-needed. | Suite green |
| 8 | **NEW (v4)**: Add `hedge/sensitivity_ranking.py` — universe-wide sort by Tool A's `down_beta_12m`. Tests: standard sort happy path, ineligible names sink to bottom, null-beta names sink with note, missing 60d candidate → null pnl_at_minus10_60d column, foreign listings appear with "no options" note, configurable sort_by. | Suite green |
| 9 | Edit `cli.py` to add `--sort-by`, `--quantity`, `--max-tickers` flags (v2 — Codex R6). v4: `--sort-by` choices extended to accept `down_beta_12m` and `up_beta_12m` for the sensitivity ranking. Tests in `test_cli_hedge_readiness.py`. | Suite green |
| 10 | Edit `hedge/report.py` to inject all sections in the order specified in §2j. Tests assert: sensitivity ranking always renders (v4), empty-holdings still produces speculation section + comparison; non-empty also produces portfolio totals + per-position scenarios; all required labels present (BS const-IV, 100-share multiplier, heuristic, etc.). | Suite green; manual smoke run produces complete report |
| 11 | Manual smoke against current data: write a 2-position `holdings.yaml`, run `hedge-readiness`, verify sensitivity ranking + portfolio totals + per-position + speculation all render correctly with sensible numbers. Run with empty holdings, verify sensitivity ranking + speculation + comparison still render. | Manual smoke captured in progress log |
| 12 | Update `docs/` with: dual-use framing (hedge OR speculate), strategy-generic math note (4 cases coded, only LONG_PUT in v1 report), sensitivity ranking walkthrough (v4 — note it's a Tool C preview), portfolio totals walkthrough, CLI flag reference. | Suite green |

Each step = one commit. Progress log committed alongside each step.

---

## 7. Acceptance criteria

M1.5 is done when **all** of the following hold:

- `python main.py hedge-readiness` produces a markdown report that includes:
  - Header bar with gold + GDX prices and 1d/1wk/1mo moves
  - Implied-move-vs-modeled-downside table for all optionable tickers with a 60d candidate
  - **A "Speculation Candidates" section that renders even when `holdings.yaml` is empty** (v2 — Codex AF1), showing up to `max_tickers` directly-hedgeable tickers sorted by IV percentile ascending, each with their candidate-puts grid + scenario tables
  - Per-candidate scenario table (5 gold scenarios × 7 output columns), with column header "Current value (BS, const-IV)" (Codex R2)
  - Cross-ticker comparison view at the end, sorted by P&L at gold −10% by default
  - Visible "Assumes standard 100-share US equity option multiplier" note near every scenario table (Codex R5)
- `python main.py hedge-readiness --sort-by pnl_per_dollar_premium_minus10` reorders the comparison view correctly (Codex R6)
- `python main.py hedge-readiness --quantity 10` overrides the default contract quantity
- `python main.py hedge-readiness --max-tickers 5` reduces the speculation section appropriately
- Tickers with `down_beta_core <= 0.10` show their candidate grid + a clear annotation (no breakeven, no scenario rows) per Codex R4
- Tickers where the linear stock model clips to zero get a `[stock clamped at $0]` annotation, and the BS current-value column still populates correctly (using the spot=0 limit, per Codex R3)
- `black_scholes_put_price` passes put-call parity tests AND a spot=0 limit case test (Codex R3)
- Breakeven gold % at expiry is computed and shown per candidate (omitted for low-beta tickers per Codex R4)
- Header verdict labels include the word "heuristic" so the thresholds aren't read as precise (Codex R7)
- Header context module reads paths via `latest_options_manifest.refresh_run_id` and `benchmark_snapshot_paths`, with graceful "data unavailable" output if either is missing (Codex AF4)
- **v3 — Strategy-generic math:** `OptionStrategy` enum supports all 4 strategies; `scenarios.compute_scenario_bundle(strategy=...)` returns correct P&L for `LONG_PUT`, `SHORT_PUT`, `LONG_CALL`, `SHORT_CALL`. Tests cover all 4 paths.
- **v3 — Put-call parity test:** `black_scholes_call_price + strike × e^(-rT) ≈ black_scholes_put_price + spot` holds at multiple input combinations (verified in `test_black_scholes.py`).
- **v3 — Portfolio Totals section:** when `holdings.yaml` is non-empty, the report includes a Portfolio Totals block with rows for each gold scenario (portfolio value, loss $, loss %) and a hedge-cost line for each `protection_level` (default 50% and 100%). Skipped silently when holdings empty.
- **v3 — Manual smoke required:** Codex runs `hedge-readiness` once with a 2-position fixture holdings file and once with empty holdings, confirms both produce expected sections, captures result in the progress log.
- **v4 — Sensitivity Ranking section:** the report ALWAYS renders the Sensitivity Ranking section (regardless of holdings), sorted by `down_beta_12m` descending by default. Ineligible names sort to the bottom with notes. Each row includes: rank, ticker, down_beta_12m, up_beta_12m, confidence label, IV percentile, P&L at gold -10% for the 60d candidate, optionability tier, notes list.
- **v4 — Section ordering:** report renders sections in the order specified in §2j (header → sensitivity ranking → portfolio totals → per-position → speculation → comparison → proxies → run summary). Conditional sections skip cleanly when their data is absent.
- Full test suite passes with the new fixture-based tests; no live Yahoo calls in the suite

---

## 8. Out of scope (deliberately)

- **Persisting scenario rows as new parquet columns.** Scenarios are deterministic functions of existing data; recomputing them at report time is fine. Persisting would create another schema-versioning surface.
- **Greeks beyond delta** (vega/theta/rho). Vega would matter if we modeled "what if IV rises with the move." Skipped — IV constant per §2a.
- **Spread strategies** (vertical, calendar, etc.). One-leg puts only. If you eventually want spread P&L, that's a future milestone.
- **Workspace UI integration.** M2 territory.
- **Auto-updating quantity to match a premium budget.** Considered but rejected — confusing to display "buy 3 of NEM but 7 of KGC for same $ premium." Fixed-quantity is simpler. User can re-run with `--quantity N` to override.
- **Calls.** Speculation tool focuses on puts (gold-down bets) for v1. Adding calls is symmetric — defer until requested.
- **Historical scenario backtests** ("what would this put have paid in past gold-down weeks?"). Needs replay infrastructure to be more mature.

---

**v2 status:** Codex's 7 v1 risks (R1-R7) and 4 additional findings (AF1-AF4) are all addressed in v2 per the changelog at top. The risks below are smaller and listed for Codex's re-review focus.

1. **Speculation section selection rule reasonable?** Sorting by `iv_percentile_cross_sectional` ascending (cheap-IV first) assumes the user wants to find underpriced puts. An alternative (more aggressive) would be: sort by down-beta descending (most leverage first). Codex: better default?
2. **Quantity default of 5 in `default_scenario_quantity`.** Is 5 the right starting anchor, or should it scale with stock price (e.g., quantity such that notional protection ≈ $10k)? Latter is more comparable across tickers but harder to read.
3. **Spot=0 limit case for BS put price** — when down-beta clamps the stock to zero, BS returns `strike × e^(-rT)`. Mathematically correct, but does showing a sizeable current-value number when "stock would be worth $0" risk being misleading? Maybe annotate the row in the report so the user sees the limit was used.
4. **Dedup decision between holdings + speculation section.** When `NEM` is in holdings AND in the speculation section, both render. This is the intentional design (different framings) but the report becomes longer. Codex: acceptable, or should the speculation section exclude held names?
5. **CLI `--sort-by` choices list is fixed.** Hard-coded enum in argparse. If we want users to sort by an arbitrary scenario column later, we'd need to refactor. Acceptable for v1?
6. **Skip-block rendering for low-beta tickers** — when scenario rows are skipped, we still render the candidate grid + annotation. Is showing the grid alone (without scenarios) useful, or just visual noise? Codex: preference?

---

## 10. Implementation guidance (for Codex)

Same operational rules as M1. Repeating the critical ones so this file is self-contained.

### Git workflow
- Branch `dev-vic`. Confirm with `git branch --show-current`.
- One commit per step in §6. Seven steps → seven commits.
- Commit message format: `m15 put scenarios step <N>: <one-line description>`
- Progress log committed alongside every step.
- No amend, no rebase, no force-push, no skip-hooks, no `git push` — Emanuel pushes.
- One commit = one stated purpose. Side improvements get their own commits.

### Test gate
- `python -m pytest -q` between every step. All green, no new warnings, test count ≥ baseline + new tests this step.
- If a step breaks tests, STOP. Revert with `git reset --soft HEAD~1`, fix, re-commit. 15-minute fix cap.

### Self-cross-check rhythm (MANDATORY — same as M1 §10)

**Before committing step N — read your own diff:**
1. `git diff --staged` end-to-end. Read every line.
2. For each chunk: does this match the step? touched any file outside its scope? any comment/whitespace edit not in the plan? any imports added I don't use? any "improvement" slipped in?
3. Fix anything that doesn't belong in this commit before staging.

**After committing step N — verify:**
1. Re-run tests.
2. Re-read the relevant plan section. Explicitly check that step N's acceptance is met.
3. If you find a bug, fix it **before starting step N+1.** Either amend a follow-up commit or squash a trivial fix.

**Stop conditions** (any → halt and report):
- Test count dropped
- A test went from green to errored/skipped
- A grep verification fails
- Your own diff has changes you can't explain in one sentence
- 15-minute fix cap reached

**Past failure modes to actively look for** (these have caught real issues in prior milestones):
- Unicode → ASCII normalization
- Defensive duplicate calls without comments
- "Improvements" bundled into a fix commit
- Unused imports left behind
- Stray blank lines accumulating

### Progress log
Create `reviews/codex/codex_m15_progress.md` at session start with baseline. Append one line per step:
```
Step <N> (<step-name>): committed <sha>. Tests: <pass>/<total>. Notes: <one line>.
```

### Checkpoints — STOP and report at each
- **CHECKPOINT A** — after step 8 (all math/feature modules in place — scenarios, comparison, header_context, speculation_section, portfolio_totals, sensitivity_ranking — not yet integrated into the report or CLI). Report: tests added, all passing, fixture smoke against each module. Wait for "continue."
- **CHECKPOINT B** — after step 10 (full report + CLI flags + sensitivity ranking always renders + portfolio totals when holdings exist). Report: paste TWO real markdown reports — one with empty `holdings.yaml` (so sensitivity ranking + speculation + comparison appear but no portfolio totals or per-position sections), one with a 2-position fixture. Demonstrate `--sort-by`, `--quantity`, `--max-tickers`. Wait for "continue."
- **CHECKPOINT C** — after step 12 (final). Write the completion report. Wait for review.

### Out of scope — DO NOT do any of these
- Workspace UI work — that's M2
- Calls (only puts)
- Spread strategies (only one-leg)
- Persisting scenarios as new parquet columns
- Calling external paid APIs
- Anything outside the files in §2b except `docs/` per step 7 and `config/hedge_readiness.yaml` per step 2

### Start now
1. Confirm branch + baseline test count
2. Create `reviews/codex/codex_m15_progress.md` with baseline
3. Confirm M1 has shipped and `python main.py hedge-readiness` works against current data (if not, M1.5 cannot start — flag and wait)
4. Re-read this plan
5. Begin step 1
6. Stop at **CHECKPOINT A**

---

## 11. Completion report (write at CHECKPOINT C)

Write `reviews/codex/codex_m15_completion_report.md` covering:

1. **Final file changes** — list every file added/modified with line counts
2. **Deviations from the plan** — every judgment call not specified, with `file:line` references. If none, say so explicitly
3. **Worked example** — paste a real per-candidate scenario table from running `hedge-readiness` against current data
4. **Comparison view example** — paste the top 10 rows of the comparison view from current data
5. **Header context example** — paste the header bar + implied-move-vs-modeled-downside table from current data
6. **Test deltas** — baseline pass count, final pass count, new test files added
7. **Edge cases verified** — table mapping (missing down-beta, missing IV, low confidence, stock clamping, IV unavailable BS price, etc.) to its covering test
8. **Risks resolved** — for each of the 7 risks in §9, what you decided + where it lives in code
9. **Open questions for the reviewer** — anything you want Claude to focus on

---

## 12. Why this plan is shaped this way

| Principle | How it shows up |
|---|---|
| Simplest thing first | §0 states the no-frills version: extend the M1 report with three sections, no new ingestion. |
| Match rigor to risk | New decision math feeding real money decisions → full plan + Codex review. |
| No premature abstraction | Three small modules + one BS function. No plugin system, no scenario registry. |
| Don't redo work | Reuses every M1 output (candidate puts, options features, manifest, Black-Scholes delta). |
| Honest about limitations | §9 explicitly names the linear-vs-lognormal inconsistency, constant-IV simplification, breakeven edge cases. |
| Verifiable | The CLI report is the proof. Tests + fixture cover behavior. Put-call parity tests anchor the new BS function. |
| User value first | Scenario table + comparison view turn "data about puts" into "decision about which put to buy." |
| Plain English | Schema docstrings, plain-English verdict labels, no jargon in the report output. |
