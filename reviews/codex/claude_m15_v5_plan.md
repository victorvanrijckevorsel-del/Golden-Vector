# Plan: M1.5 v5 — Hedge Readiness Completion (full v4 vision, all Codex blockers fixed)

**Author:** Claude Code
**Branch:** `dev-vic`
**Date:** 2026-06-02 (v5 after Codex graded v4 NEEDS CHANGES)
**Reviewer:** Codex — graded v1/v2/v3/v4; v5 addresses every blocker from `codex_review_claude_m15_plan_v4.md`
**Related:**
- [reviews/codex/codex_review_claude_m15_plan_v4.md](codex_review_claude_m15_plan_v4.md) — what v5 fixes
- [reviews/codex/MASTER_ROADMAP_2026-06-02.md](MASTER_ROADMAP_2026-06-02.md) — three-milestone master roadmap
- [CODE_REVIEW.md](../../CODE_REVIEW.md) — Claude's senior-engineer review of the M1 codebase; v5 folds in its H1/H2/H3 cleanups

## v5 changelog (against v4)

| Codex v4 finding | Where addressed in v5 |
|---|---|
| **#1 — CLI `--sort-by` overloaded between comparison view and sensitivity ranking** | Split into TWO flags: `--comparison-sort-by` (controls cross-ticker comparison) and `--ranking-sort-by` (controls sensitivity ranking). Each flag has its own `choices` list. CLI help text is explicit per flag. See §2b CLI scope + §3 cli.py module summary. |
| **#2 — Calls both in scope and out of scope** | RESOLVED to "in scope at math layer, out of scope in report": §3 confirms `black_scholes_call_price` and `OptionStrategy` enum are implemented and tested as math primitives. §8 (out of scope) explicitly says calls/short strategies are NOT surfaced in the M1.5 report — they're math-only. §10 implementation guidance restates this. No more contradiction. |
| **#3 — Report module summary stale vs §2j** | §3 `hedge/report.py` module summary now matches §2j's 8-section ordering exactly. Listed in order: header → sensitivity ranking → portfolio totals (conditional) → per-position scenarios (conditional) → speculation candidates → cross-ticker comparison → proxy hedges (conditional) → run summary. |
| **#4 — Black-Scholes pseudocode regression on spot=0** | §3 `features/black_scholes.py` module summary now matches §4b exactly: put price returns `strike × e^(-rT)` for spot=0, not None. Single source of truth. |
| **#5 — `DOWN_BETA_MIN_FOR_SCENARIO = 0.10 # configurable` but no config field** | RESOLVED: §2b/step 2 add `down_beta_min_for_scenario` config field (default 0.10). The constant in `scenarios.py` reads from config. No "configurable" comment without backing config. |
| **#6 — `--sort-by` choices list incomplete for sensitivity ranking** | Resolved by splitting flags (see #1 above). Each flag's choices list is now correct and complete. |
| **#7 — Header verdict labels need "heuristic" word** | §4e and §3 `header_context.py` module summary both include the word "heuristic" in every verdict string (`"model > market (heuristic)"`, etc.). Confirmed against existing implementation in `header_context.py:217-222`. |
| **#8 — AF4 regression: header_context signature** | §3 `header_context.py` module summary now shows the signature taking `paths` and reading via `latest_options_manifest.refresh_run_id`, NOT taking `gold_history`/`gdx_history` directly. Matches existing implementation. |
| **#9 — Sensitivity Ranking `--max-tickers` overloaded with speculation section** | RESOLVED: §2b CLI scope adds `--ranking-max-tickers` separate from `--speculation-max-tickers`. Each section's cap is independently controlled. Defaults stay at 60 (show all) for ranking, 15 for speculation. |
| **#10 — Sensitivity Ranking `up_beta_12m` sort doesn't make sense for downside** | RESOLVED: `--ranking-sort-by` choices are restricted to `down_beta_12m` only in M1.5 v5. Up-beta is a column shown in the ranking table for asymmetry CONTEXT, not a sort option. Removing the up-beta sort choice makes the section's purpose unambiguous. |
| **#11 — Portfolio Totals doesn't handle dollar_exposure holdings** | §2h schema now explicitly handles BOTH `shares`-mode holdings (need `share_price_usd` to compute notional) AND `dollar_exposure`-mode holdings (notional is directly the exposure). Step 7 tests cover both modes plus missing-price and missing-candidate edge cases. |
| **#12 — §2b file/config tree missing `protection_levels` and v4 modules** | §2b is rewritten as a single coherent tree showing every new file, every edit, every config field. No duplication. |
| **#13 — Implementation guidance says "seven steps"** | §10 corrected to "thirteen steps" (v5 step count). Step references updated throughout. |
| **#14 — Duplicate v2/v3 changelog headings** | §1 simplified: ONE v5 changelog (this section), then ONE consolidated "v2/v3/v4 history" appendix at the end of the document. |
| **Codex caveat in finding #9: "opinion-free should not mean no warnings"** | §2k explicitly distinguishes "decision triggers" (REMOVED — opinion overlays) from "data-quality guardrails" (KEPT — stock-clamp annotations, low-confidence flags, quote-quality gates, stale-context warnings, missing-candidate notes). |
| **M1 H1: cross-sectional IV sort direction** | Step 11 folds this into report.py wiring: cross-sectional ranking sorts ASCENDING (cheap-IV first). |
| **M1 H2: proxy basis-risk 3-tier vs 2-tier** | Step 12 adds the 3-tier implementation per the original plan with new config fields `proxy_low_basis_max_beta_diff`, `proxy_medium_basis_max_beta_diff`, `proxy_low_basis_min_confidence`. |
| **M1 H3: options_phase per-ticker error isolation** | Step 13 wraps each ticker's persist + feature compute in try/except with warning logging. |

---

## 0. The simplest thing that could work

> **Add a Sensitivity Ranking section (sort all 60 tickers by `down_beta_12m` desc) as the report's entry point. Wire the 4 already-built modules (scenarios + comparison + header_context + speculation_section) into report.py per the 8-section order in §2j. Add Portfolio Totals (when holdings exist) covering both shares-mode and dollar-exposure-mode holdings. Add Black-Scholes call price + OptionStrategy enum + 4-case P&L sign rules as math primitives (not yet surfaced in report). Split CLI sort flags cleanly. Refactor render_hedge_readiness_report into section data builders + a markdown emitter so M2 can reuse the data builders directly. Fold in M1 H1/H2/H3 cleanups. 13 steps, 3 checkpoints, ~18-22 Codex hours.**

Everything below justifies and scopes that baseline.

---

## 1. Current state (verified 2026-06-02)

### What exists in the codebase (built under v1/v2 work)

| Module | Status |
|---|---|
| `golden_vector/hedge/holdings.py` | ✅ Built (handles both shares + dollar_exposure) |
| `golden_vector/hedge/candidate_puts.py` | ✅ Built (uses shared `features/options_chain.py`) |
| `golden_vector/hedge/scenarios.py` | ✅ Built (LONG_PUT only; need to extend with strategy enum) |
| `golden_vector/hedge/comparison.py` | ✅ Built (`_sort_key` has a known bug per CODE_REVIEW.md M2 — fixed in step 4) |
| `golden_vector/hedge/header_context.py` | ✅ Built (reads via manifest; has "heuristic" labels per existing line 217-222) |
| `golden_vector/hedge/speculation_section.py` | ✅ Built (universe-level candidate puts) |
| `golden_vector/hedge/proxy_hedge.py` | ✅ Built (2-tier basis labels — H2 from CODE_REVIEW.md; v5 step 12 upgrades to 3-tier) |
| `golden_vector/hedge/expected_downside.py` | ✅ Built (premium-vs-downside cards) |
| `golden_vector/hedge/implied_move.py` | ✅ Built |
| `golden_vector/hedge/report.py` | ✅ Built BUT renders only holdings + cross-sectional + proxy sections; missing M1.5 sections (sensitivity ranking, portfolio totals, integrated scenarios/comparison/speculation/header). |
| `golden_vector/features/black_scholes.py` | ✅ Built (`normal_cdf`, `black_scholes_delta`, `black_scholes_put_price` with spot=0 limit, `strike_for_target_delta`); missing `black_scholes_call_price` |
| `golden_vector/features/options_chain.py` | ✅ Built (shared helpers) |
| `golden_vector/features/options.py` | ✅ Built (computes derived features) |
| `golden_vector/ingestion/options_phase.py` | ✅ Built BUT per-ticker error isolation missing (H3 from CODE_REVIEW.md) |
| `config/hedge_readiness.yaml` | ✅ Built BUT missing `default_scenarios`, `default_scenario_quantity`, `protection_levels`, `optionability_tier_min`, `max_tickers_speculation_section`, `down_beta_min_for_scenario`, proxy 3-tier fields |
| `golden_vector/cli.py` `hedge-readiness` subcommand | ✅ Built BUT has no `--sort-by` / `--quantity` / `--max-tickers` flags yet |

### What needs to be built (v5 deltas)

1. NEW `golden_vector/hedge/sensitivity_ranking.py`
2. NEW `golden_vector/hedge/portfolio_totals.py`
3. EDIT `golden_vector/features/black_scholes.py` — add `black_scholes_call_price`
4. EDIT `golden_vector/hedge/scenarios.py` — add `OptionStrategy` enum + 4-case P&L sign rules; make `DOWN_BETA_MIN_FOR_SCENARIO` config-driven
5. EDIT `golden_vector/hedge/comparison.py` — fix per-column natural sort direction (M2 from CODE_REVIEW.md)
6. EDIT `golden_vector/hedge/proxy_hedge.py` — 3-tier basis-risk labels (M1 H2)
7. EDIT `golden_vector/ingestion/options_phase.py` — per-ticker error isolation (M1 H3)
8. EDIT `golden_vector/hedge/report.py` — wire all 6 hedge modules into the 8-section report ordering; refactor into section builders + markdown emitter
9. EDIT `golden_vector/cli.py` — add 4 new flags: `--comparison-sort-by`, `--ranking-sort-by`, `--quantity`, `--ranking-max-tickers`, `--speculation-max-tickers`
10. EDIT `golden_vector/contracts/config_models.py` — extend `HedgeReadinessConfig` with new fields
11. EDIT `config/hedge_readiness.yaml` — populate new fields with defaults

---

## 2. Architecture

### 2a. Decisions locked

| Decision | Choice | Source |
|---|---|---|
| Calls in M1.5 | Math-layer ONLY (`black_scholes_call_price`, `OptionStrategy.LONG_CALL`/`SHORT_CALL`, P&L sign rules). NOT surfaced in the report. Future M1.6 work surfaces them. | Resolves Codex v4 #2 |
| CLI sort flags | TWO separate flags: `--comparison-sort-by` and `--ranking-sort-by`. No overload. | Resolves Codex v4 #1, #6 |
| CLI max-ticker flags | TWO separate flags: `--ranking-max-tickers` (default 60) and `--speculation-max-tickers` (default 15) | Resolves Codex v4 #9 |
| Sensitivity Ranking sort | `down_beta_12m` only (descending). `up_beta_12m` is a context column, NOT a sort choice. | Resolves Codex v4 #10 |
| Portfolio Totals holdings modes | Handle BOTH shares-mode (need `share_price_usd` to compute notional) AND dollar_exposure-mode. Skip individual rows where required inputs are missing; surface counts in annotations. | Resolves Codex v4 #11 |
| BS put price at spot=0 | Returns `strike × e^(-rT)` (BS limit). Module summary and §4b agree. | Resolves Codex v4 #4 |
| `DOWN_BETA_MIN_FOR_SCENARIO` | Config-driven via `down_beta_min_for_scenario` (default 0.10). | Resolves Codex v4 #5 |
| Header verdict labels | All include "heuristic": `"model > market (heuristic)"`, etc. | Resolves Codex v4 #7 |
| Header context inputs | Reads via `paths.latest_options_manifest_path` + `latest_options_manifest.refresh_run_id` + `benchmark_snapshot_paths`. No direct history args. | Resolves Codex v4 #8 |
| Data-quality guardrails | KEPT (stock-clamp annotations, low-confidence, quote-quality gates, stale-context, missing-candidate). Decision triggers (FIRING/OK verdicts) REMOVED. | Resolves Codex v4 #9 caveat |
| Section-builders to emitter refactor | DONE in step 9. Section data is returned as typed dataclasses; markdown emitter is a thin wrapper. Enables M2 workspace UI to reuse data builders directly. | Architectural seam from CODE_REVIEW.md |

### 2b. File and config tree (single source of truth)

```
golden_vector/
  features/
    black_scholes.py            # EDIT — add `black_scholes_call_price()`
  hedge/
    scenarios.py                # EDIT — add OptionStrategy enum + 4-case P&L; config-driven down-beta min
    comparison.py               # EDIT — per-column natural sort direction
    proxy_hedge.py              # EDIT — 3-tier basis-risk labels (M1 H2)
    report.py                   # REWRITE — section builders + markdown emitter; integrate 8 sections
    sensitivity_ranking.py      # NEW — universe-wide sort by down_beta_12m
    portfolio_totals.py         # NEW — total portfolio downside per scenario + hedge cost cards
    _helpers.py                 # NEW — centralized _as_float / _row_float / _index_by_ticker (M3 from CODE_REVIEW.md)
  ingestion/
    options_phase.py            # EDIT — per-ticker try/except (M1 H3)
  contracts/
    config_models.py            # EDIT — extend HedgeReadinessConfig
  cli.py                        # EDIT — add 4 flags + plumb through run_hedge_readiness
config/
  hedge_readiness.yaml          # EDIT — add 7 new fields:
                                #   default_scenarios: [0.0, -0.05, -0.10, -0.15, -0.20]
                                #   default_scenario_quantity: 5
                                #   protection_levels: [0.5, 1.0]
                                #   optionability_tier_min: "directly_hedgeable"
                                #   speculation_max_tickers_default: 15
                                #   ranking_max_tickers_default: 60
                                #   down_beta_min_for_scenario: 0.10
                                #   proxy_low_basis_max_beta_diff: 0.10
                                #   proxy_medium_basis_max_beta_diff: 0.30
                                #   proxy_low_basis_min_confidence: 0.70
tests/
  test_sensitivity_ranking.py   # NEW
  test_portfolio_totals.py      # NEW
  test_strategy_generic_math.py # NEW (4-strategy P&L tests + put-call parity)
  test_black_scholes.py         # EDIT — add call-price tests
  test_scenarios.py             # EDIT — add OptionStrategy parameterization
  test_comparison.py            # EDIT — add breakeven_gold_pct sort case (M2 from CODE_REVIEW.md)
  test_proxy_hedge.py           # EDIT — add 3-tier tests (M1 H2)
  test_options_phase.py         # EDIT — add per-ticker failure test (M1 H3)
  test_hedge_report.py          # EDIT — add tests for 8-section ordering, both holdings modes
  test_cli_hedge_readiness.py   # EDIT — add tests for 4 new flags
```

### 2c. CLI scope (per Codex v4 #1, #6, #9)

```bash
python main.py hedge-readiness [OPTIONS]

OPTIONS:
  --comparison-sort-by CHOICE   Comparison view sort column.
                                Choices: pnl_per_contract_minus5,
                                         pnl_per_contract_minus10 (default),
                                         pnl_per_contract_minus20,
                                         pnl_per_dollar_premium_minus10,
                                         breakeven_gold_pct
  --ranking-sort-by CHOICE      Sensitivity ranking sort column.
                                Choices: down_beta_12m (default and only)
  --ranking-max-tickers N       Cap on sensitivity ranking table rows.
                                Default: 60 (show all).
  --speculation-max-tickers N   Cap on speculation candidates section.
                                Default: from config (default 15).
  --quantity N                  Hypothetical put-contract quantity for P&L.
                                Default: from config (default 5).
```

CLI plumbs each flag through `run_hedge_readiness()` → `write_hedge_readiness_report()` → into the appropriate section builder.

### 2d. Section data dataclasses (new in v5 — enables M2 workspace UI)

Per Codex critique on §3 and the CODE_REVIEW.md architectural seam, `render_hedge_readiness_report` is refactored so that EACH section returns a typed dataclass, and a separate markdown emitter turns those into text. M2 will add an HTML emitter consuming the same dataclasses.

```python
@dataclass(frozen=True)
class SnapshotSummaryData:
    as_of_date: str
    refresh_run_id: str
    risk_free_rate: float | None
    holdings_count: int
    holdings_mode: str  # "shares" | "dollar_exposure" | "mixed" | "empty"
    optionability_counts: dict[str, int]
    context_alignment: ContextAlignment

@dataclass(frozen=True)
class SensitivityRankingData:
    rows: list[SensitivityRow]
    sort_by: str
    total_count: int
    score_eligible_count: int

@dataclass(frozen=True)
class PortfolioTotalsData:
    holdings_count: int
    current_total_value: float
    scenario_rows: list[PortfolioScenarioRow]
    interpretive_notes: list[str]

@dataclass(frozen=True)
class HeldPositionsData:
    holdings: list[HoldingPositionData]

@dataclass(frozen=True)
class SpeculationCandidatesData:
    blocks: list[SpeculationTickerBlock]
    sort_by: str
    max_tickers_applied: int

@dataclass(frozen=True)
class ComparisonViewData:
    rows: list[ComparisonRow]
    sort_by: str

@dataclass(frozen=True)
class ProxyHedgesData:
    by_target: dict[str, list[ProxyMatch]]

@dataclass(frozen=True)
class HedgeReadinessSections:
    summary: SnapshotSummaryData
    sensitivity_ranking: SensitivityRankingData
    portfolio_totals: PortfolioTotalsData | None  # None when holdings empty
    held_positions: HeldPositionsData | None       # None when holdings empty
    speculation_candidates: SpeculationCandidatesData
    comparison: ComparisonViewData
    proxy_hedges: ProxyHedgesData | None           # None when no non-optionable held
```

`build_hedge_readiness_sections(...)` returns `HedgeReadinessSections`. `render_markdown(sections)` returns the markdown string. `write_hedge_readiness_report` orchestrates: load data → build sections → render markdown → write to file. M2 will add `render_html(sections)` reusing the same dataclasses.

### 2e. Section ordering (per Codex v4 #3, confirmed)

The 8 sections in `render_markdown` order:

1. **Header** (gold/GDX 1d/1wk/1mo + implied-vs-modeled-downside heuristic verdicts)
2. **Snapshot Summary** (run id, dates, optionability counts, context alignment)
3. **Sensitivity Ranking** (universe-wide sort by `down_beta_12m` — NEW v5 entry point)
4. **Portfolio Totals** (conditional: only when holdings non-empty — NEW v5)
5. **Held Positions** (conditional: per-position scenarios when holdings non-empty)
6. **Speculation Candidates** (universe-level candidate puts for top-N optionable; always renders)
7. **Cross-ticker Comparison View** (sortable flat table; always renders)
8. **Proxy Hedges** (conditional: only when held non-optionable names exist)
9. **Sources / Run summary** (provenance)

### 2f. Sensitivity Ranking schema (per Codex v4 #10, restricted to down-beta only)

```python
@dataclass(frozen=True)
class SensitivityRow:
    rank: int | None  # None for ineligible/null-beta names (sink to bottom)
    ticker: str
    down_beta_12m: float | None
    up_beta_12m: float | None        # CONTEXT column, not sort choice
    confidence_label: str
    confidence_score: float | None
    iv_percentile_cross_sectional: float | None
    pnl_at_minus10_60d: float | None
    optionability_tier: str
    notes: list[str]
```

Columns: rank, ticker, down-β (12m), up-β (12m), confidence, IV percentile, 60d Put @ -10% P&L, optionability, notes.

Sort: `down_beta_12m` descending only. Most-sensitive-first. The `--ranking-sort-by` CLI flag exists for future extensibility but currently only has one choice.

### 2g. Portfolio Totals schema (per Codex v4 #11 — handles both holdings modes)

```python
@dataclass(frozen=True)
class HoldingResolved:
    ticker: str
    mode: str  # "shares" | "dollar_exposure"
    shares: float | None
    dollar_exposure: float | None
    current_stock_price: float | None  # from Tool A / Tool B / chain
    current_notional: float | None  # shares × price (shares mode) OR dollar_exposure (dollar mode)
    down_beta_core: float | None
    candidate_60d: CandidatePut | None
    skipped_reason: str | None  # populated when required inputs are missing

@dataclass(frozen=True)
class PortfolioScenarioRow:
    gold_pct_change: float
    portfolio_value_at_scenario: float
    portfolio_loss_dollars: float
    portfolio_loss_pct: float
    hedge_cost_by_protection: dict[float, float]  # protection_level → cost

@dataclass(frozen=True)
class PortfolioTotalsData:
    holdings_count: int
    holdings_resolved_count: int  # how many we could include in totals
    holdings_skipped: list[tuple[str, str]]  # (ticker, reason)
    current_total_value: float
    scenario_rows: list[PortfolioScenarioRow]
    interpretive_notes: list[str]  # e.g., "Hedging 50% costs 1.7% of portfolio"
```

**Per-holding resolution logic:**
- `shares` mode: needs `current_stock_price`. If missing, mark `skipped_reason="missing share price"`.
- `dollar_exposure` mode: notional is the exposure directly; doesn't need price. Always resolvable.
- For hedge cost: needs `candidate_60d`. If missing, mark with `skipped_reason="no 60d candidate"` and exclude from hedge-cost calculation.
- For scenario downside: needs `down_beta_core`. If missing OR below `down_beta_min_for_scenario`, mark with `skipped_reason="down-beta unavailable or too small"`.

**Aggregate logic:**
- `current_total_value = sum(current_notional for h in resolved holdings)`
- `portfolio_value_at_scenario = sum(notional × (1 + down_beta × gold_pct) for resolved holdings)` with stock clamping at zero
- `hedge_cost_at_X% = sum(ceil(target_notional / (strike × 100)) × candidate.mid × 100 for resolved holdings with candidate_60d)`

If `holdings_resolved_count < holdings_count`, the report includes a note listing skipped tickers + reasons.

### 2h. OptionStrategy enum + 4-case P&L (per Codex v4 #2 — math only, no report)

```python
class OptionStrategy(Enum):
    LONG_PUT = "long_put"
    SHORT_PUT = "short_put"
    LONG_CALL = "long_call"
    SHORT_CALL = "short_call"

def compute_strategy_pnl(
    *, strategy: OptionStrategy, intrinsic_value: float, premium: float
) -> float:
    """Per-contract P&L for any of the 4 single-leg strategies."""
    if strategy == OptionStrategy.LONG_PUT:
        return intrinsic_value - premium
    if strategy == OptionStrategy.SHORT_PUT:
        return premium - intrinsic_value
    if strategy == OptionStrategy.LONG_CALL:
        return intrinsic_value - premium
    if strategy == OptionStrategy.SHORT_CALL:
        return premium - intrinsic_value
    raise ValueError(f"Unknown strategy: {strategy}")
```

Where `intrinsic_value`:
- For puts: `max(0, strike - underlying)`
- For calls: `max(0, underlying - strike)`

The M1.5 report consumes ONLY `LONG_PUT`. The other 3 are tested as math primitives but not surfaced.

### 2i. M1 cleanups folded in (per CODE_REVIEW.md H1/H2/H3)

- **H1 — Cross-sectional IV sort:** flip to `ascending=True` (cheap-IV first). Update test in `test_hedge_report.py`. Done in step 11 (report rewrite).
- **H2 — Proxy 3-tier basis-risk:** implement 3-tier with config-driven thresholds. New config fields `proxy_low_basis_max_beta_diff` (0.10), `proxy_medium_basis_max_beta_diff` (0.30), `proxy_low_basis_min_confidence` (0.70). Done in step 12 with new tests in `test_proxy_hedge.py`.
- **H3 — `options_phase` per-ticker isolation:** wrap each ticker's persist + feature compute in try/except with `LOGGER.warning`. Add a test in `test_options_phase.py` simulating a mid-loop persist failure. Done in step 13.

### 2j. Decision triggers vs data-quality guardrails (per Codex v4 caveat)

**Decision triggers (REMOVED — opinion overlays):**
- ❌ "FIRING / OK" verdict block at top of report
- ❌ Gold-momentum binary threshold flag
- ❌ Portfolio-loss binary threshold flag

**Data-quality guardrails (KEPT — surfaced honestly):**
- ✅ Stock-clamp annotations when implied stock price hits zero
- ✅ Low-confidence flags from Tool A
- ✅ Quote-quality gates (bid > 0, ask > 0, spread threshold, OI threshold)
- ✅ Stale-context warnings when Tool A/B snapshot run_id ≠ options manifest run_id
- ✅ Missing-candidate notes when no usable 60d / 30d / 90d candidate exists
- ✅ Down-beta-too-small skip annotation (`down_beta_min_for_scenario` threshold)
- ✅ Holdings skipped from portfolio totals + reasons
- ✅ Header heuristic labels (always include "heuristic" word)

---

## 3. Module summaries (corrected per Codex v4 review)

### `golden_vector/features/black_scholes.py` (edit — add call price)

```python
def normal_cdf(x: float) -> float: ...  # existing
def black_scholes_delta(...) -> float | None: ...  # existing
def black_scholes_put_price(*, spot: float, strike: float, time_to_expiry_years: float,
                            risk_free_rate: float, implied_volatility: float | None) -> float | None:
    """European put price. Returns strike × e^(-rT) when spot==0 (BS limit).
    Returns None for: strike <= 0, time <= 0, spot < 0, or IV None/<=0 (when spot > 0).
    """  # existing

def black_scholes_call_price(*, spot: float, strike: float, time_to_expiry_years: float,
                             risk_free_rate: float, implied_volatility: float | None) -> float | None:
    """European call price. Returns 0.0 when spot == 0 (BS limit).
    Returns None for: strike <= 0, time <= 0, spot < 0, or IV None/<=0 (when spot > 0).
    """  # NEW

def strike_for_target_delta(...) -> dict[str, object] | None: ...  # existing
```

**Put-call parity test (REQUIRED):** `call_price + strike × e^(-rT) ≈ put_price + spot` at multiple input combinations.

### `golden_vector/hedge/scenarios.py` (edit — strategy enum + config-driven threshold)

```python
class OptionStrategy(Enum):
    LONG_PUT = "long_put"
    SHORT_PUT = "short_put"
    LONG_CALL = "long_call"
    SHORT_CALL = "short_call"

@dataclass(frozen=True)
class ScenarioRow: ...  # unchanged
@dataclass(frozen=True)
class CandidateScenarioBundle: ...  # unchanged

def compute_scenario_bundle(
    *,
    candidate: CandidatePut,
    current_stock_price: float,
    down_beta_core: float | None,
    confidence_label: str,
    risk_free_rate: float,
    strategy: OptionStrategy = OptionStrategy.LONG_PUT,  # NEW — defaults to LONG_PUT
    down_beta_min_for_scenario: float = 0.10,  # NEW — config-driven, was hardcoded
    gold_scenarios: tuple[float, ...] = (0.0, -0.05, -0.10, -0.15, -0.20),
    quantity: int = 5,
) -> CandidateScenarioBundle:
    """Compute model-based P&L scenarios for one listed candidate.
    Supports all 4 OptionStrategy cases (v5). M1.5 report only calls with LONG_PUT.
    """
```

### `golden_vector/hedge/sensitivity_ranking.py` (NEW)

```python
@dataclass(frozen=True)
class SensitivityRow:
    rank: int | None
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
    sort_by: str  # always "down_beta_12m" in M1.5 v5
    total_count: int
    score_eligible_count: int

def build_sensitivity_ranking(
    *, tool_a_frame: pd.DataFrame,
    options_features: pd.DataFrame | dict[str, pd.DataFrame],
    candidate_grids: dict[str, list[CandidatePut]],
    risk_free_rate: float,
    sort_by: str = "down_beta_12m",
    max_tickers: int | None = None,
) -> SensitivityRankingBlock:
    """Universe-wide sort by down-beta. Ineligible names sort to bottom with notes.
    For each ticker with a 60d candidate, compute LONG_PUT P&L at gold -10%.
    """
```

### `golden_vector/hedge/portfolio_totals.py` (NEW — handles both holdings modes)

```python
@dataclass(frozen=True)
class HoldingResolved: ...  # per §2g
@dataclass(frozen=True)
class PortfolioScenarioRow: ...  # per §2g
@dataclass(frozen=True)
class PortfolioTotalsData: ...  # per §2g

def compute_portfolio_totals(
    *, holdings: list[Holding],
    tool_a_frame: pd.DataFrame,
    tool_b_frame: pd.DataFrame,
    candidate_grids: dict[str, list[CandidatePut]],
    risk_free_rate: float,
    config: HedgeReadinessConfig,
) -> PortfolioTotalsData | None:
    """Aggregate scenarios + hedge costs across resolved holdings.
    Handles BOTH shares-mode (needs price) and dollar_exposure-mode (notional direct).
    Returns None when holdings is empty.
    Includes skipped_reason for each holding that couldn't be resolved.
    """
```

### `golden_vector/hedge/proxy_hedge.py` (edit — 3-tier basis-risk per M1 H2)

```python
def _basis_risk_label(
    *, beta_diff: float,
    target_confidence: float | None,
    proxy_confidence: float | None,
    config: HedgeReadinessConfig,
) -> str:
    target_conf = target_confidence or 0.0
    proxy_conf = proxy_confidence or 0.0
    if (beta_diff <= config.proxy_low_basis_max_beta_diff
        and target_conf >= config.proxy_low_basis_min_confidence
        and proxy_conf >= config.proxy_low_basis_min_confidence):
        return "low_basis_risk"
    if (beta_diff <= config.proxy_medium_basis_max_beta_diff
        and max(target_conf, proxy_conf) >= config.proxy_low_basis_min_confidence):
        return "medium_basis_risk"
    return "high_basis_risk"
```

### `golden_vector/hedge/comparison.py` (edit — per-column natural sort direction per M2 from CODE_REVIEW.md)

```python
_NATURAL_DESCENDING = {
    "pnl_per_contract_minus5": True,
    "pnl_per_contract_minus10": True,
    "pnl_per_contract_minus20": True,
    "pnl_per_dollar_premium_minus10": True,
    "breakeven_gold_pct": False,  # smaller (more negative) is better
}

def _sort_key(row: ComparisonRow, sort_by: str) -> tuple[bool, float]:
    descending = _NATURAL_DESCENDING.get(sort_by, True)
    value = getattr(row, sort_by)
    if value is None:
        return (True, 0.0)
    return (False, -value if descending else value)
```

### `golden_vector/hedge/report.py` (REWRITE — section builders + emitter pattern)

```python
def build_hedge_readiness_sections(
    *, paths: ProjectPaths, run_context: RunContext, app_config: AppConfig,
    holdings: list[Holding],
    comparison_sort_by: str,
    ranking_sort_by: str,
    ranking_max_tickers: int | None,
    speculation_max_tickers: int | None,
    quantity: int | None,
) -> HedgeReadinessSections:
    """Pure data builder. Returns typed dataclasses ready for any emitter (markdown, HTML, JSON)."""

def render_markdown(sections: HedgeReadinessSections, paths: ProjectPaths) -> str:
    """Markdown emitter. Pure function: sections in, string out."""

def write_hedge_readiness_report(
    *, paths: ProjectPaths, run_context: RunContext, app_config: AppConfig,
    comparison_sort_by: str = "pnl_per_contract_minus10",
    ranking_sort_by: str = "down_beta_12m",
    ranking_max_tickers: int | None = None,
    speculation_max_tickers: int | None = None,
    quantity: int | None = None,
) -> HedgeReportResult:
    """Orchestrate: load holdings → build sections → render markdown → write to disk."""
```

Section ordering inside `render_markdown` exactly matches §2e: header → snapshot summary → sensitivity ranking → portfolio totals → held positions → speculation candidates → comparison view → proxy hedges → sources.

### `golden_vector/hedge/header_context.py` (edit — confirm AF4 alignment)

Already implemented correctly per current code (`header_context.py` reads `latest_options_manifest_path` directly). v5 step 5 has no changes to this module; the change is to the §3 module summary text to match the existing implementation.

### `golden_vector/ingestion/options_phase.py` (edit — per-ticker isolation per M1 H3)

```python
for ticker in active_tickers:
    try:
        result = fetch_options_chain(...)
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        if result.status == OPTIONS_STATUS_ERROR:
            LOGGER.warning("Options fetch failed for %s: %s", ticker, result.message)
        record = persist_options_snapshot(...)
        snapshot_records.append(record)
        feature_rows.append(_compute_feature_row(...))
    except Exception as exc:  # noqa: BLE001 - per-ticker isolation
        LOGGER.warning("Options pipeline failed for %s: %s", ticker, exc)
        status_counts[OPTIONS_STATUS_ERROR] = status_counts.get(OPTIONS_STATUS_ERROR, 0) + 1
        continue
```

### `golden_vector/cli.py` (edit — 4 new flags)

```python
hedge_parser = subparsers.add_parser("hedge-readiness", ...)
hedge_parser.add_argument(
    "--comparison-sort-by",
    choices=["pnl_per_contract_minus5", "pnl_per_contract_minus10",
             "pnl_per_contract_minus20", "pnl_per_dollar_premium_minus10",
             "breakeven_gold_pct"],
    default="pnl_per_contract_minus10",
    help="Comparison view sort column.",
)
hedge_parser.add_argument(
    "--ranking-sort-by",
    choices=["down_beta_12m"],
    default="down_beta_12m",
    help="Sensitivity ranking sort column. (Only down_beta_12m supported in M1.5.)",
)
hedge_parser.add_argument("--ranking-max-tickers", type=int, default=None,
                         help="Cap on sensitivity ranking rows. Default: show all.")
hedge_parser.add_argument("--speculation-max-tickers", type=int, default=None,
                         help="Cap on speculation candidates section. Default: from config.")
hedge_parser.add_argument("--quantity", type=int, default=None,
                         help="Hypothetical put-contract quantity for P&L. Default: from config.")
```

---

## 4. Math

### 4a. Implied stock price under a gold scenario (unchanged from v4)

```
gold_pct_change ∈ {0, -0.05, -0.10, -0.15, -0.20}
raw_implied = current_stock_price × (1 + down_beta_core × gold_pct_change)
implied_stock_price = max(0, raw_implied)
stock_clamped_at_zero = (raw_implied < 0)
```

### 4b. Black-Scholes prices (per Codex v4 #4 — consistent across §3 and §4)

```python
def black_scholes_put_price(spot, strike, T, r, sigma):
    if strike <= 0 or T <= 0 or spot < 0:
        return None
    if spot == 0:
        return strike * exp(-r * T)  # BS limit, NOT None
    if sigma is None or sigma <= 0:
        return None
    # ... standard BS formula

def black_scholes_call_price(spot, strike, T, r, sigma):
    if strike <= 0 or T <= 0 or spot < 0:
        return None
    if spot == 0:
        return 0.0  # call is worthless when underlying is zero
    if sigma is None or sigma <= 0:
        return None
    # ... standard BS formula
```

### 4c. 4-strategy P&L (per Codex v4 #2 — math only)

```
intrinsic_value = max(0, strike - underlying)  for puts
                  max(0, underlying - strike)  for calls

LONG_PUT  : pnl = intrinsic - premium    (paid premium)
SHORT_PUT : pnl = premium - intrinsic    (collected premium)
LONG_CALL : pnl = intrinsic - premium
SHORT_CALL: pnl = premium - intrinsic
```

### 4d. Down-beta near-zero handling (per Codex v4 #5 — config-driven)

```python
if down_beta_core is None or down_beta_core <= config.down_beta_min_for_scenario:
    return CandidateScenarioBundle(
        rows=[],
        skipped_reason="Down-beta too small to model meaningful gold-down scenarios."
    )
```

### 4e. Header verdict labels (per Codex v4 #7 — always include "heuristic")

```python
if (implied_move_60d is None or implied_move_60d <= 0
    or modeled_downside_at_minus10 is None):
    return "data unavailable (heuristic)"
if modeled_downside_at_minus10 > 1.5 * implied_move_60d:
    return "model > market (heuristic)"
if modeled_downside_at_minus10 < 0.67 * implied_move_60d:
    return "market > model (heuristic)"
return "model ~= market (heuristic)"
```

---

## 5. Report format (worked mock)

```
# Hedge Readiness Report

## Header
Gold: $2,058/oz  (1d -0.4%   1wk -2.1%   1mo -3.5%)
GDX:  $32.40     (1d -0.6%   1wk -3.4%   1mo -5.8%)

Implied-move-vs-modeled-downside (60d, optionable tickers)
| Ticker | Implied move 60d | Modeled at gold -10% | Verdict                       |
| NEM    | ±5.8%            | -14.2%               | model > market (heuristic)    |
| ...                                                                              |

## Snapshot Summary
| Tickers in options manifest: 64 | Directly hedgeable: 19 | Thin: 5 | None: 40 |
| Holdings loaded: 0              | Context alignment: OK                       |

## Stocks Ranked By Gold-Downside Sensitivity
Sorted by structural down-beta (12m). Higher = more sensitive to gold drops.
Showing all 60 tickers (use --ranking-max-tickers to cap).

| Rank | Ticker | Down-β | Up-β | Confidence | IV %-tile | 60d Put @ -10% | Optionable | Notes |
| 1    | KGC    | 1.85   | 1.21 | high       | 45th      | +$4.50/c       | yes        | —    |
| 2    | NEM    | 1.42   | 1.18 | high       | 38th      | +$13.20/c      | yes        | most liquid |
| ...                                                                                |

## Portfolio Totals
(skipped — holdings.yaml is empty)

## Held Positions
(skipped — holdings.yaml is empty)

## Candidate Puts (Speculation Section)
For 15 directly-hedgeable tickers sorted by cheap-IV first.

▍NEM (Newmont) — current $147.50, IV percentile 38th
Down-β 1.42 (high confidence)
[candidate grid + scenario tables per §2c of v4]

▍AEM (Agnico Eagle) — current $180.00, IV percentile 31st
[...]

## Cross-Ticker Comparison View
Sorted by pnl_per_contract_minus10 descending (default; --comparison-sort-by to change).

| Ticker | Horizon | Strike | Mid  | Δ-gap | Break.  | P&L -5%  | P&L -10% | P&L -20% | P&L/$ -10% |
| NEM    | 60d     | 142    | 2.20 | 0.00  | -2.1%   | +$2.75   | +$13.20  | +$34.10  | $6.00      |
| ...                                                                                  |

## Proxy Hedges
(skipped — no held non-optionable tickers)

## Sources / Run Summary
- Run id: 20260602T080000Z-hedge-readiness-...
- Options snapshot run: 20260602T060000Z-update-data-...
- Risk-free rate: 4.28%
- Replay manifest: data/runs/.../replay_manifest.json
```

Assumes standard 100-share US equity option multiplier throughout.

---

## 6. Order of operations (13 steps)

| # | Step | Test gate |
|---|---|---|
| 1 | Add `golden_vector/features/black_scholes.py::black_scholes_call_price()`. Tests for: standard call price, spot=0 returns 0.0, degenerate inputs return None, put-call parity holds at 5+ input combinations. | Suite green; ~6 new tests |
| 2 | Extend `golden_vector/contracts/config_models.py::HedgeReadinessConfig` with new fields: `default_scenarios`, `default_scenario_quantity`, `protection_levels`, `optionability_tier_min`, `speculation_max_tickers_default`, `ranking_max_tickers_default`, `down_beta_min_for_scenario`, `proxy_low_basis_max_beta_diff`, `proxy_medium_basis_max_beta_diff`, `proxy_low_basis_min_confidence`. Update `config/hedge_readiness.yaml`. Tests: schema validation, value coercion. | Suite green |
| 3 | Add `OptionStrategy` enum + `compute_strategy_pnl()` to `scenarios.py`. Refactor `compute_scenario_bundle` to accept `strategy` parameter (default `LONG_PUT`) and `down_beta_min_for_scenario` parameter (from config). Tests: all 4 strategies parameterized, put-call parity preserved, threshold behavior. | Suite green; +10 tests |
| 4 | Fix `comparison.py::_sort_key` with per-column natural direction (per M2 from CODE_REVIEW.md). Test `breakeven_gold_pct` sort case. | Suite green; +2 tests |
| 5 | Add `golden_vector/hedge/_helpers.py` consolidating `_as_float`, `_row_float`, `_row_string`, `_rows_by_ticker_dict`, `_rows_by_ticker_series` (per M3 from CODE_REVIEW.md). Migrate all 4 hedge modules to import from `_helpers.py` instead of having private copies. Tests preserved. | Suite green |
| 6 | Add `golden_vector/hedge/sensitivity_ranking.py` per §3 module summary. Tests: standard sort happy path, ineligible names sink to bottom, null-beta names sink with note, missing 60d candidate → null `pnl_at_minus10_60d`, foreign listings appear with "no options" note, configurable `max_tickers` cap. | Suite green; +8 tests |
| 7 | Add `golden_vector/hedge/portfolio_totals.py` per §2g. Tests: empty holdings returns None, shares-mode holdings, dollar_exposure-mode holdings, mixed-mode, missing-price skip, missing-candidate skip, low-down-beta skip, single-position correctness, hedge-cost calculation matches sum-of-positions, ceil rounding of contracts-needed. | Suite green; +10 tests |
| 8 | Update `golden_vector/hedge/proxy_hedge.py` to 3-tier basis-risk labels per §3 module summary (M1 H2 fix). Tests: low/medium/high tier boundaries, confidence-weighted downgrades. | Suite green; +6 tests |
| 9 | Add per-ticker error isolation to `golden_vector/ingestion/options_phase.py` per M1 H3 fix. Test simulating a mid-loop persist failure. | Suite green; +2 tests |
| 10 | Update `golden_vector/cli.py` to add 4 new flags. Plumb through `run_hedge_readiness()`. Tests in `test_cli_hedge_readiness.py` for: each flag parses correctly, default fallback to config, invalid choice rejected, plumbing into report. | Suite green; +6 tests |
| 11 | **REFACTOR** `golden_vector/hedge/report.py` per §2d section-builders + emitter pattern. Wire all 8 sections in order per §2e. Includes M1 H1 fix (cross-sectional IV ascending sort, cheap-first). Tests assert: 8-section ordering, sensitivity ranking always renders, portfolio totals conditional on holdings, holdings-mode handling, all required labels present (heuristic, 100-share multiplier, BS const-IV). | Suite green; +12 tests; manual `python main.py hedge-readiness` produces complete report |
| 12 | Manual smoke against current data: write a 2-position `holdings.yaml` (one shares-mode, one dollar_exposure-mode), run `hedge-readiness`, verify all 8 sections + Portfolio Totals + Held Positions + Speculation + Comparison + Proxy. Run with empty holdings, verify graceful fallback. Run `--ranking-sort-by`, `--quantity 10`, `--ranking-max-tickers 5`. | Manual smoke captured in progress log |
| 13 | Update `docs/` with: dual-use framing (hedge OR speculate), Sensitivity Ranking walkthrough (note it's a Tool C preview), Portfolio Totals walkthrough (covering both modes), strategy-generic math note (4 cases coded, only LONG_PUT in v1 report), CLI flag reference. | Suite green |

Each step is one commit. Progress log committed alongside.

---

## 7. Acceptance criteria

The milestone is done when **all** of the following hold:

- `python main.py hedge-readiness` produces a markdown report at `data/output/hedge_readiness/<date>_<run>.md` + `latest.md` alias with all 8 sections in the order specified in §2e.
- The **Sensitivity Ranking section always renders** (regardless of holdings), sorted by `down_beta_12m` descending. Each row includes: rank, ticker, down_beta_12m, up_beta_12m, confidence_label, IV percentile, P&L at gold -10% for 60d candidate, optionability_tier, notes list.
- **Portfolio Totals** renders when `holdings.yaml` non-empty; handles BOTH shares-mode and dollar_exposure-mode holdings; skips individual holdings cleanly when required inputs are missing with explicit `skipped_reason` annotations.
- **Cross-ticker comparison view** is correctly sorted; `--comparison-sort-by breakeven_gold_pct` produces ascending order (most-negative-first).
- **CLI flags** all work: `--comparison-sort-by`, `--ranking-sort-by`, `--ranking-max-tickers`, `--speculation-max-tickers`, `--quantity`. Invalid choices rejected with argparse error.
- **`black_scholes_call_price`** passes put-call parity at multiple input combinations. spot=0 returns 0.0. Module summary in §3 matches the function definition exactly.
- **`OptionStrategy` enum** supports all 4 strategies. Math primitives tested. Report uses only LONG_PUT.
- **Proxy 3-tier basis-risk** labels fire correctly per the threshold rules in §2i. New config fields validate.
- **Options ingestion per-ticker error isolation** — one ticker's failure doesn't crash the phase.
- **Cross-sectional IV ranking** sorts ascending (cheap-IV first) per M1 H1.
- **Header verdicts** all include the word "heuristic".
- **Data-quality guardrails** all present: stock-clamp, low-confidence, quote-quality, stale-context, missing-candidate, down-beta-too-small, holdings-skipped notes.
- **Decision triggers** (FIRING/OK) NOT present anywhere in the report.
- **Section-builders refactor done:** `build_hedge_readiness_sections()` returns typed dataclasses. M2's HTML emitter will reuse the same dataclasses.
- **Full test suite passes**, no live Yahoo calls.
- Tests increase from 446 to ~500+ (estimated +50-60 new tests across all 13 steps).

---

## 8. Out of scope (deliberately)

- **Workspace UI for hedge-readiness** (`/hedge-readiness` page, interactive forms, sortable tables) — M2 territory
- **Tool C ranking pipeline** (richer downside metrics than just `down_beta_12m`) — M3 basic
- **Trade journal / position tracking** — M4
- **Multi-week comparison** ("what changed since last visit") — M2 workspace surface
- **Correlation matrix** — M3.5
- **Calls in the REPORT** — math implemented in M1.5 v5; surfacing in report is future work
- **Spread strategies** (vertical, calendar) — single-leg only
- **Greeks beyond delta** (vega, theta) — out of scope
- **Vol skew modeling** — labeled as constant-IV v1 limitation
- **US ADR mapping** for foreign listings
- **Paid options feeds**
- **52-week IV percentile** maturity (auto-activates over time)

---

## 9. Risks Codex should pry at

1. **Section-builders refactor scope.** §3 + step 11 require rewriting `render_hedge_readiness_report` from a markdown-emit function to a data-builder + emitter pair. This is structurally significant. The risk: if the dataclass shapes I specified aren't quite right, M2's HTML emitter will need to reshape them. Codex should check whether the §2d dataclasses cover everything the markdown emitter currently produces.
2. **Section ordering between v4 and current report.** The current report's section order is: holdings → cross-sectional → proxy → sources. v5 changes it to header → snapshot summary → sensitivity ranking → portfolio totals → held positions → speculation → comparison → proxy → sources. Existing tests in `test_hedge_report.py` may need updating in step 11. Confirm no test assumes the old order.
3. **Sensitivity Ranking computing P&L at gold -10% per ticker.** This involves calling `compute_scenario_bundle` for the 60d candidate of EACH of 60 tickers. For non-optionable tickers (40 of them), there's no candidate → null P&L. For low-down-beta tickers, the scenario is skipped. The right behavior is documented in §2f's `notes` column. Confirm the test cases cover all the skip paths.
4. **Portfolio Totals + dollar_exposure mode.** When a holding has `dollar_exposure: 50000` and no shares, the "current notional" is 50000 directly. But for hedge cost calculation, we still need a share count to know how many contracts to buy: `target_shares = dollar_exposure × X% / current_stock_price`. If current_stock_price is missing, we can't compute hedge cost. Confirm the skip logic and tests.
5. **OptionStrategy enum without report integration.** All 4 strategies are math primitives, but only LONG_PUT shows in the report. Could a future Codex reader confuse "implemented" with "user-facing"? §8 explicitly says calls/short strategies are NOT in the report. Should we add a docstring on the enum noting "report consumption: LONG_PUT only in M1.5"?
6. **Proxy 3-tier vs Tool B verdict.** §2i 3-tier labels look at beta_diff + confidence. The plan doesn't use Tool B verdict in the tier decision. Codex's prior critique said Tool B verdict should be SURFACED but NOT disqualify. Current implementation surfaces it as context. Confirm this is still right under 3-tier.
7. **CLI flag defaults living in config vs CLI.** `--quantity` falls back to `config.default_scenario_quantity`. `--ranking-max-tickers` falls back to `config.ranking_max_tickers_default`. The pattern is consistent but the config field names are different from the flag names (`default_scenario_quantity` vs `--quantity`). Worth flagging for naming consistency.

---

## 10. Implementation guidance for Codex

### Git workflow
- Branch `dev-vic`. Confirm with `git branch --show-current`.
- One commit per step. **13 steps → 13 commits.**
- Commit message format: `m15 v5 step <N>: <one-line description>`
- Progress log committed alongside each step.
- No amend, no rebase, no force-push, no skip-hooks, no `git push` — Emanuel handles pushing.
- One commit = one stated purpose.

### Test gate
- `python -m pytest -q` between every step. All green, no new warnings, test count ≥ baseline + new tests this step.
- If a step breaks tests, STOP. Revert with `git reset --soft HEAD~1`, fix, re-commit. 15-minute fix cap.

### Self-cross-check rhythm (MANDATORY)
Same rhythm that worked on all prior milestones. **Before committing step N:**
1. Read `git diff --staged` end-to-end.
2. For each chunk: matches the step? touched any out-of-scope file? any whitespace/comment/import edit not in the plan? any "improvement" slipped in?
3. Fix anything that doesn't belong before staging.

**After committing step N:**
1. Re-run tests.
2. Re-read the relevant plan section. Explicitly verify acceptance.
3. If you find a bug, fix it before starting step N+1.

**Stop conditions** (any → halt and report):
- Test count dropped
- Test errored / skipped
- Grep verification fails
- Diff has changes you can't explain in one sentence
- 15-minute fix cap reached

**Past failure modes to actively look for** (have caught real issues in prior milestones):
- Unicode → ASCII normalization
- Defensive duplicate calls without comments
- "Improvements" bundled into a fix commit
- Unused imports left behind
- Stray blank lines accumulating

### Progress log
Create `reviews/codex/codex_m15_v5_progress.md` at session start with baseline. Append one line per step.

### Checkpoints — STOP and report at each
- **CHECKPOINT A** — after step 9 (all individual module work done: BS call price, config extensions, OptionStrategy, comparison fix, _helpers, sensitivity_ranking, portfolio_totals, proxy 3-tier, options_phase isolation). Report: tests added per step, all passing. Wait for "continue."
- **CHECKPOINT B** — after step 11 (CLI flags + full report integration). Report: paste TWO real markdown reports — one with empty `holdings.yaml`, one with a 2-position mixed-mode fixture. Demonstrate all 4 new CLI flags. Wait for "continue."
- **CHECKPOINT C** — after step 13 (final + docs). Write the completion report. Wait for review.

### Out of scope — DO NOT do any of these
- Workspace UI work (HTML, lenses, detail page, overview pages) — M2
- Surfacing calls/short strategies in the report (math primitives only in M1.5)
- New ingestion pipelines (Tool C is M3, not M1.5)
- Trade journal / option position tracking
- Anything outside the files in §2b except `docs/` per step 13

### Start now
1. Confirm branch: `git branch --show-current` → `dev-vic`
2. Baseline: `python -m pytest -q` and record pass count (should be 446)
3. Create `reviews/codex/codex_m15_v5_progress.md` with baseline
4. Re-read this plan v5; confirm the v4 blockers from your prior review are all addressed
5. Begin step 1
6. Stop at **CHECKPOINT A** (after step 9)

---

## 11. Completion report (write at CHECKPOINT C)

Write `reviews/codex/codex_m15_v5_completion_report.md` covering:

1. **Final file changes** — list every file added/modified with line counts
2. **Deviations from the plan** — every judgment call not specified, with `file:line` references. If none, say so explicitly.
3. **Sample reports** — paste one report with empty holdings and one with a 2-position mixed-mode fixture
4. **Test deltas** — baseline 446 → final pass count, new test files added, modified tests
5. **Section-builders refactor result** — paste the `HedgeReadinessSections` dataclass + any other dataclass changes; confirm M2 can consume these directly
6. **Codex v4 blockers + this review's findings** — tick each of the 14 v4 findings from `codex_review_claude_m15_plan_v4.md` and confirm fixed; tick the 3 M1 cleanups from `CODE_REVIEW.md`
7. **Open questions** — anything you want Claude to look at specifically

---

## 12. Why this plan is shaped this way

| Principle | How it shows up |
|---|---|
| Simplest thing first | §0 states the no-frills version. Each addition justified. |
| Match rigor to risk | Real-money decision math → full plan + Codex review (right rigor). |
| No premature abstraction | Two new modules (sensitivity_ranking, portfolio_totals); no plugin system, no strategy registry, no rule engine. |
| Don't redo work | Reuses every M1 output. 4 hedge modules already built — just wired. M1 H1/H2/H3 fixed in the same milestone. |
| Honest about limitations | §8 explicitly defers calls-in-report, Tool C, trade journal. §9 names structural risks. |
| Verifiable | All-CLI-flags + 8 sections + put-call parity test = the proof. |
| User value first | Sensitivity Ranking is the entry point. Comparison view is the choice tool. Portfolio Totals is the aggregate. All decision-useful. |
| Plain English | Plan reads end-to-end without jargon. Mock report in §5 shows the actual output. |
| Sets up M2 cleanly | Section-builders → emitter refactor means M2 workspace UI just adds `render_html(sections)`. |
| Folds in CODE_REVIEW.md findings | M1 H1/H2/H3 + M2 (comparison sort) + M3 (helper consolidation) all addressed in this milestone. |

---

## Appendix — v1/v2/v3/v4 changelog history (preserved)

[v2 changelog from the prior version of this plan]
[v3 changelog from the prior version of this plan]
[v4 changelog from the prior version of this plan]

These are preserved as project history. v5 supersedes them; the changelog at the TOP of this document (v5 changelog vs v4) is the authoritative summary.
