# Plan: M1.5 v6 — Hedge Readiness Completion (reconciled with the working tree)

**Author:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Date:** 2026-06-02 (v6, after Codex graded v5 NEEDS CHANGES + an independent Opus 4.8 review against the live working tree)
**Reviewers:**
- Codex — `reviews/codex/codex_review_claude_m15_v5_plan.md` (NEEDS CHANGES, 9 findings)
- Claude (Opus 4.8 self-review against the repo) — `reviews/codex/claude_self_review_m15_v5_plan_opus48.md` (3 blockers + 4 high + 4 medium)
**Supersedes:** `reviews/codex/claude_m15_v5_plan.md`

---

## v6 changelog (what changed since v5, and why)

v6 fixes two classes of problem: (A) Codex's 9 findings on the v5 *text*, and (B) the fact — found by reviewing the plan against the actual repo — that **v5 was written against the committed state (HEAD `a37a013`, 13:18) while the working tree already contained the H1/H2/H3/M4 fixes (made 14:35, uncommitted).** v5 therefore planned work that is already done.

| Source | Finding | Fix in v6 |
|---|---|---|
| **Self-review C1** | Plan describes HEAD, not the working tree; steps 8/9, part of 11, part of 2 already implemented (uncommitted, tests green — 65/65 on the touched files). | New **§0.5 reconciliation** + new **Step 0** (commit existing work as baseline). §1 rewritten against the working tree. Old steps 8 & 9 demoted to *verify-only*. |
| **Self-review C2** | v5's `options_phase` pseudocode increments status *before* persist → double-counts; the real working-tree code already increments *after* the try (correct). Following v5 literally would **regress** correct code. | §3 pseudocode removed; replaced with "already implemented correctly at `options_phase.py:97-136`; do not rewrite." This also makes **Codex #8 moot**. |
| **Self-review C3** | v5's comparison fix (`_NATURAL_DESCENDING["breakeven_gold_pct"] = False`) is wrong *and* unnecessary. The existing default already sorts breakeven closest-to-zero-first (`['NEM','AEM']`, verified by running it), matching Codex #4 and the test already in the tree. `comparison.py` is not even in the working-tree diff. | **No code change to `comparison.py`.** Keep the existing default and the already-added test. Old step 4 dropped. See §2k. |
| **Self-review H-A** | Ranking sorts by `down_beta_12m` but the per-row P&L uses `down_beta_core` (two different existing columns) — ranking key and dollar figure disagree. | Rank by **`down_beta_core`** (the anchor used everywhere else in the hedge pipeline and in the P&L column). Mock relabelled "core". See §2f. |
| **Self-review H-B** | Dataclass naming inconsistent (`SensitivityRankingData` vs `SensitivityRankingBlock`); `SensitivityRow` / `PortfolioTotalsData` each defined twice. | One canonical name and **one definition site** per section type. Naming convention fixed: aggregate-level types use the `…Data` suffix; they are defined once in §2d and only *referenced* in §3. See §2d. |
| **Self-review H-C** | "config-driven `down_beta_min_for_scenario`" won't take effect — the real skip logic is in `_skip_reason`, which reads the module constant; v5 only adds the param to `compute_scenario_bundle`. | §3/§4d explicitly thread the threshold into `_skip_reason`; one source (the param), no leftover constant read. |
| **Self-review M-A** | `target_notional` is undefined in the §2g hedge-cost formula. | Defined explicitly in §2g, using the chosen dollar-exposure rule (below). |
| **Self-review M-B** | CODE_REVIEW M1 (sign-convention) and M5 (surface r=0) were silently dropped despite being scoped "during M1.5." | M5 **re-included** as a data-quality guardrail (§2j) + step. M1 **explicitly deferred** with a stated reason (§8). |
| **Self-review M-C** | `build_sensitivity_ranking(risk_free_rate: float)` can receive `None`. | Typed `float | None`; behaviour defined (§3). |
| **Self-review M-D** | `compute_strategy_pnl` is a 2-way sign flip; intrinsic/strategy can desync silently. | Function computes intrinsic *internally* from `option_type` + `strike` + `underlying`, so strategy and intrinsic can't desync (§2h). |
| **Codex #1** | `HedgeReadinessSections` omits `header` and `sources`. | Both fields added (§2d). |
| **Codex #2** | "8 sections" but lists 9. | Standardised on **9 sections** everywhere (§2e, acceptance, step tests, mock). |
| **Codex #3** | Dollar-exposure hedge-cost rule contradicts itself. | One rule adopted: **share-based**, `target_shares = current_notional × protection_level / current_stock_price`. Dollar-exposure holdings need `current_stock_price` for hedge cost; skip-with-reason if missing (notional still counts toward totals). §2g. |
| **Codex #4** | `breakeven_gold_pct` sort backwards. | Resolved by C3: existing default is already closest-to-zero-first (correct). No change needed beyond the test already present. |
| **Codex #5** | Step references for H1/H2/H3 drifted. | All step references regenerated from the §6 table (single source of truth). |
| **Codex #6** | Stale counts (5 flags not 4; 10 config fields not 7). | Counts corrected throughout (§1, §2b, §3). |
| **Codex #7** | `PortfolioTotalsData` defined twice. | Collapsed to one definition (the richer §2g shape), referenced elsewhere. |
| **Codex #8** | Options isolation pseudocode double-counts. | Moot — real code already correct; see C2 above. |
| **Codex #9** | `_helpers.py` migration vs header_context "no changes". | Clarified: "no *behavioural* changes to `header_context.py`; step 5 only edits its helper imports." |

---

## 0. The simplest thing that could work

> **Most of the M1 cleanup is already in the working tree (uncommitted): proxy 3-tier (H2), options per-ticker isolation (H3), cross-sectional IV sort flip (H1), and same-day re-run dedup (M4). Commit that first as the baseline. Then: add the Sensitivity Ranking section (sort the universe by `down_beta_core` desc) as the entry point; wire the 4 already-built modules (scenarios + comparison + header_context + speculation_section) into `report.py` in the 9-section order; add Portfolio Totals (both shares-mode and dollar-exposure-mode); add `black_scholes_call_price` + an `OptionStrategy` enum + 4-case P&L as math-only primitives; split the CLI sort/cap flags cleanly; surface the r=0 risk-free fallback honestly; and refactor `render_hedge_readiness_report` into section-data builders + a markdown emitter so M2 reuses the builders. No code change to `comparison.py`.**

---

## 0.5. Reconciliation with the working tree (read this first)

At review time the working tree had **uncommitted** changes (10 files, +267/−30) that v5 did not account for. Verified by `git diff HEAD` and by running the touched tests (**65/65 green**):

| Already done (uncommitted) | Files | v5 thought it was… |
|---|---|---|
| **H2 — proxy 3-tier basis-risk** with confidence weighting + config fields + validators + tests | `proxy_hedge.py`, `config_models.py`, `hedge_readiness.yaml`, `test_proxy_hedge.py` | "to do" in step 12/8 |
| **H3 — options per-ticker isolation** (correct: status counted *after* the try) + test | `options_phase.py`, `test_options_phase.py` | "missing" / to do in step 13/9 |
| **H1 — cross-sectional IV sort → ascending (cheap-first)** | `report.py:327` | "to do" in step 11 |
| **M4 — same-day re-run feature-row dedup on `run_id`** | `options_phase.py` | not even scoped |
| **breakeven sort test** (asserts closest-to-zero-first) — note `comparison.py` itself is *unchanged* | `test_comparison.py` | step 4 wanted to change `comparison.py` |

**Implication:** the real remaining scope is smaller than v5's "13 steps / 18-22 hrs." v6 re-baselines below.

---

## 1. Current state (re-verified against the working tree, 2026-06-02)

### Already built AND already fixed (uncommitted — commit in Step 0)
- `proxy_hedge.py` — **3-tier** basis-risk (`low`/`medium`/`high`) with confidence weighting. ✅
- `options_phase.py` — per-ticker try/except isolation **and** same-day dedup. ✅
- `report.py` — cross-sectional IV sorts **ascending** (cheap-first). ✅
- `config_models.py` / `hedge_readiness.yaml` — proxy 3-tier fields + validators. ✅

### Built earlier, correct, not yet wired into the report
- `scenarios.py` (LONG_PUT P&L; extend with strategy enum + config threshold)
- `comparison.py` (**correct as-is** — do not modify; default sort already closest-to-zero-first for breakeven)
- `header_context.py` (manifest-based; has "heuristic" labels)
- `speculation_section.py`, `expected_downside.py`, `implied_move.py`
- `candidate_puts.py`, `holdings.py` (handles shares + dollar_exposure)
- `black_scholes.py` (`normal_cdf`, `black_scholes_delta`, `black_scholes_put_price` with spot=0 limit, `strike_for_target_delta`); **missing `black_scholes_call_price`**

### Still to build (v6 deltas)
1. NEW `golden_vector/hedge/sensitivity_ranking.py`
2. NEW `golden_vector/hedge/portfolio_totals.py`
3. NEW `golden_vector/hedge/_helpers.py` (consolidate duplicated `_as_float`/`_row_float`/index helpers — CODE_REVIEW M3)
4. EDIT `black_scholes.py` — add `black_scholes_call_price`
5. EDIT `scenarios.py` — `OptionStrategy` enum + `compute_strategy_pnl`; thread `down_beta_min_for_scenario` from config into `compute_scenario_bundle` **and** `_skip_reason`
6. EDIT `report.py` — wire all 9 sections; refactor into section-data builders + markdown emitter; surface r=0 fallback (M5)
7. EDIT `cli.py` — add **5** flags
8. EDIT `config_models.py` + `hedge_readiness.yaml` — add the **7** non-proxy fields (the 3 proxy fields already exist)

---

## 2. Architecture

### 2a. Decisions locked (v6)

| Decision | Choice | Source |
|---|---|---|
| Working-tree baseline | Commit the existing H1/H2/H3/M4 work first (Step 0), then build on it. | Self-review C1 |
| `comparison.py` | **Unchanged.** Existing default already sorts breakeven closest-to-zero-first (correct for a put buyer). Keep the already-added test. | Self-review C3, Codex #4 |
| Sensitivity ranking beta | **`down_beta_core`** (same beta the P&L column and the whole hedge pipeline use). | Self-review H-A |
| Section count | **9 sections**, stated identically everywhere. | Codex #2 |
| `HedgeReadinessSections` | Includes `header` and `sources`. | Codex #1 |
| Dollar-exposure hedge cost | **Share-based:** `target_shares = current_notional × protection_level / current_stock_price`; `contracts = ceil(target_shares / 100)`; `cost = contracts × candidate.mid × 100`. Dollar-exposure mode needs `current_stock_price` for hedge cost (skip-with-reason if absent); notional still counts toward totals. | Codex #3, self-review M-A |
| `down_beta_min_for_scenario` | Config-driven, threaded into both `compute_scenario_bundle` and `_skip_reason`. | Self-review H-C, Codex #5 |
| `OptionStrategy` P&L | `compute_strategy_pnl` computes intrinsic internally from `option_type`+`strike`+`underlying` (no desync). Report consumes LONG_PUT only. | Self-review M-D, Codex #2 |
| r=0 risk-free fallback | Surfaced honestly in Snapshot Summary + per-scenario note when used. | CODE_REVIEW M5, self-review M-B |
| Gold-scenario sign convention (M1) | **Deferred** (see §8) — not load-bearing for this milestone and out of the put-scenario path. | self-review M-B |
| Section-builders → emitter | Done in the report refactor step (§6). Builders return typed dataclasses; markdown emitter is a thin wrapper; M2 adds `render_html`. | CODE_REVIEW seam |

### 2b. File and config tree (single source of truth)

```
golden_vector/
  features/
    black_scholes.py            # EDIT — add black_scholes_call_price()
  hedge/
    scenarios.py                # EDIT — OptionStrategy enum + compute_strategy_pnl; thread down-beta-min into compute_scenario_bundle AND _skip_reason
    proxy_hedge.py              # NO further change (3-tier already in tree; committed in Step 0)
    comparison.py               # NO change (default already correct)
    report.py                   # REWRITE — section-data builders + markdown emitter; wire 9 sections; surface r=0 (M5)
    sensitivity_ranking.py      # NEW — universe sort by down_beta_core
    portfolio_totals.py         # NEW — totals + share-based hedge cost; both holdings modes
    _helpers.py                 # NEW — consolidate _as_float/_row_float/_row_string/index-by-ticker (CODE_REVIEW M3)
  ingestion/
    options_phase.py            # NO further change (isolation + dedup already in tree; committed in Step 0)
  contracts/
    config_models.py            # EDIT — add the 7 non-proxy fields (3 proxy fields already present)
  cli.py                        # EDIT — add 5 flags + plumb through run_hedge_readiness
config/
  hedge_readiness.yaml          # EDIT — add the 7 non-proxy fields:
                                #   default_scenarios: [0.0, -0.05, -0.10, -0.15, -0.20]
                                #   default_scenario_quantity: 5
                                #   protection_levels: [0.5, 1.0]
                                #   optionability_tier_min: "directly_hedgeable"
                                #   speculation_max_tickers_default: 15
                                #   ranking_max_tickers_default: 60
                                #   down_beta_min_for_scenario: 0.10
                                # (proxy_low_basis_max_beta_diff / _medium_ / _min_confidence already present)
tests/
  test_sensitivity_ranking.py   # NEW
  test_portfolio_totals.py      # NEW
  test_strategy_generic_math.py # NEW (4-strategy P&L + put-call parity)
  test_black_scholes.py         # EDIT — add call-price tests
  test_scenarios.py             # EDIT — OptionStrategy + threshold threading tests
  test_hedge_report.py          # EDIT — 9-section ordering, both holdings modes, r=0 note
  test_cli_hedge_readiness.py   # EDIT — 5 new flags
  # test_comparison.py, test_proxy_hedge.py, test_options_phase.py, test_config_models.py
  # already updated in the working tree; committed in Step 0.
```

Counts: **5 CLI flags**, **7 new config fields** (plus the 3 proxy fields already in the tree = 10 total proxy+new).

### 2c. CLI scope (5 flags)

```bash
python main.py hedge-readiness [OPTIONS]

  --comparison-sort-by CHOICE   Choices: pnl_per_contract_minus5,
                                pnl_per_contract_minus10 (default),
                                pnl_per_contract_minus20,
                                pnl_per_dollar_premium_minus10, breakeven_gold_pct
  --ranking-sort-by CHOICE      Choices: down_beta_core (default and only)
  --ranking-max-tickers N       Cap on ranking rows. argparse default None → config ranking_max_tickers_default (60).
  --speculation-max-tickers N   Cap on speculation section. argparse default None → config (15).
  --quantity N                  Put-contract quantity for P&L. argparse default None → config default_scenario_quantity (5).
```

Each flag's argparse default is `None`; the builder falls back to the config field. (Naming note: flag `--quantity` ↔ config `default_scenario_quantity`; flag `--ranking-max-tickers` ↔ config `ranking_max_tickers_default`. Kept for back-compat; documented so completion reports don't disagree.)

### 2d. Section data dataclasses (defined once here; only referenced in §3)

```python
@dataclass(frozen=True)
class HeaderContextData:        # the existing header_context output, wrapped for the emitter
    ...                          # gold/GDX moves + implied-vs-modeled heuristic verdicts

@dataclass(frozen=True)
class SnapshotSummaryData:
    as_of_date: str
    refresh_run_id: str
    risk_free_rate: float | None
    risk_free_rate_is_fallback: bool      # True when r=0 fallback used (M5)
    holdings_count: int
    holdings_mode: str                    # "shares" | "dollar_exposure" | "mixed" | "empty"
    optionability_counts: dict[str, int]
    context_alignment: ContextAlignment

@dataclass(frozen=True)
class SensitivityRow:
    rank: int | None                      # None for ineligible/null-beta names (sink to bottom)
    ticker: str
    down_beta_core: float | None
    up_beta_core: float | None            # CONTEXT column, not a sort choice
    confidence_label: str
    confidence_score: float | None
    iv_percentile_cross_sectional: float | None
    pnl_at_minus10_60d: float | None
    optionability_tier: str
    notes: list[str]

@dataclass(frozen=True)
class SensitivityRankingData:
    rows: list[SensitivityRow]
    sort_by: str                          # always "down_beta_core" in M1.5
    total_count: int
    score_eligible_count: int

@dataclass(frozen=True)
class HoldingResolved:
    ticker: str
    mode: str                             # "shares" | "dollar_exposure"
    shares: float | None
    dollar_exposure: float | None
    current_stock_price: float | None
    current_notional: float | None        # shares×price (shares mode) OR dollar_exposure (dollar mode)
    down_beta_core: float | None
    candidate_60d: CandidatePut | None
    skipped_reason: str | None

@dataclass(frozen=True)
class PortfolioScenarioRow:
    gold_pct_change: float
    portfolio_value_at_scenario: float
    portfolio_loss_dollars: float
    portfolio_loss_pct: float
    hedge_cost_by_protection: dict[float, float]   # protection_level → cost

@dataclass(frozen=True)
class PortfolioTotalsData:                # the ONE definition (richer shape)
    holdings_count: int
    holdings_resolved_count: int
    holdings_skipped: list[tuple[str, str]]        # (ticker, reason)
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
class SourcesData:
    run_id: str
    options_snapshot_run_id: str
    risk_free_rate: float | None
    risk_free_rate_is_fallback: bool
    replay_manifest_path: str

@dataclass(frozen=True)
class HedgeReadinessSections:
    header: HeaderContextData                       # Codex #1
    summary: SnapshotSummaryData
    sensitivity_ranking: SensitivityRankingData
    portfolio_totals: PortfolioTotalsData | None    # None when holdings empty
    held_positions: HeldPositionsData | None        # None when holdings empty
    speculation_candidates: SpeculationCandidatesData
    comparison: ComparisonViewData
    proxy_hedges: ProxyHedgesData | None            # None when no non-optionable held
    sources: SourcesData                            # Codex #1
```

`build_hedge_readiness_sections(...) -> HedgeReadinessSections`. `render_markdown(sections, paths) -> str`. `write_hedge_readiness_report(...)` orchestrates: load → build → render → write. M2 adds `render_html(sections)` over the same dataclasses.

### 2e. Section ordering (9 sections, in `render_markdown` order)

1. **Header** — gold/GDX 1d/1wk/1mo + implied-vs-modeled-downside heuristic verdicts
2. **Snapshot Summary** — run id, dates, optionability counts, context alignment, risk-free rate (+ fallback flag)
3. **Sensitivity Ranking** — universe sort by `down_beta_core` desc (NEW entry point)
4. **Portfolio Totals** — conditional: holdings non-empty (NEW)
5. **Held Positions** — conditional: per-position scenarios when holdings non-empty
6. **Speculation Candidates** — universe candidate puts for top-N optionable; always renders
7. **Cross-ticker Comparison View** — sortable flat table; always renders
8. **Proxy Hedges** — conditional: held non-optionable names exist
9. **Sources / Run Summary** — provenance

Tests assert this exact 9-heading order.

### 2f. Sensitivity Ranking schema

Sort: **`down_beta_core` descending only.** `up_beta_core` is a context column. For each ticker with a 60d candidate, compute LONG_PUT P&L at gold −10% **using the same `down_beta_core`** (so the ranking key and the P&L column agree — self-review H-A). Ineligible/null-beta names sink to the bottom with a `notes` entry. `--ranking-sort-by` keeps a single choice for future extensibility.

### 2g. Portfolio Totals — both holdings modes, share-based hedge cost

Per-holding resolution:
- **shares mode:** `current_notional = shares × current_stock_price`. Needs `current_stock_price`; else `skipped_reason="missing share price"`.
- **dollar_exposure mode:** `current_notional = dollar_exposure` (no price needed for notional).
- **scenario downside:** needs `down_beta_core`; if missing or `<= down_beta_min_for_scenario`, `skipped_reason="down-beta unavailable or too small"` (holding still counts toward `current_total_value`, just not the scenario loss).
- **hedge cost (both modes):** needs `current_stock_price` **and** `candidate_60d`. If either missing, `skipped_reason="no hedge-cost inputs"` and the holding is excluded from hedge-cost only.

Aggregates:
```
current_total_value          = sum(current_notional for resolved holdings)
portfolio_value_at_scenario  = sum(current_notional × (1 + down_beta_core × gold_pct) for resolved)   # clamp factor at 0
target_shares(h, level)      = current_notional(h) × level / current_stock_price(h)
contracts(h, level)          = ceil(target_shares(h, level) / 100)
hedge_cost_at_level          = sum(contracts(h, level) × candidate_60d(h).mid × 100 for hedge-eligible holdings)
```
If `holdings_resolved_count < holdings_count`, the report lists skipped tickers + reasons.

### 2h. OptionStrategy enum + P&L (math only — no desync)

```python
class OptionStrategy(Enum):
    LONG_PUT = "long_put"
    SHORT_PUT = "short_put"
    LONG_CALL = "long_call"
    SHORT_CALL = "short_call"

def compute_strategy_pnl(*, strategy: OptionStrategy, underlying: float, strike: float, premium: float) -> float:
    """Per-contract P&L. Intrinsic is computed here from the strategy's option type,
    so strategy and intrinsic can never desync (self-review M-D)."""
    if strategy in (OptionStrategy.LONG_PUT, OptionStrategy.SHORT_PUT):
        intrinsic = max(0.0, strike - underlying)
    else:
        intrinsic = max(0.0, underlying - strike)
    long_side = strategy in (OptionStrategy.LONG_PUT, OptionStrategy.LONG_CALL)
    return (intrinsic - premium) if long_side else (premium - intrinsic)
```

The M1.5 report consumes **LONG_PUT only**; the other three are tested primitives, not surfaced. Docstring states this.

### 2i. M1 cleanups status (per CODE_REVIEW.md)

- **H1 (cross-sectional IV ascending):** ✅ already in tree → committed in Step 0; keep test.
- **H2 (proxy 3-tier):** ✅ already in tree → committed in Step 0; tests present.
- **H3 (options isolation, counted after try):** ✅ already in tree → committed in Step 0; test present.
- **M3 (helper consolidation):** done in the `_helpers.py` step (§6).
- **M4 (feature-row dedup):** ✅ already in tree → committed in Step 0.
- **M5 (surface r=0):** done in the report-refactor step (§6); guardrail in §2j.
- **M1 (gold-scenario sign convention):** deferred — see §8.

### 2j. Decision triggers vs data-quality guardrails

**Removed (opinion overlays):** FIRING/OK verdict block; gold-momentum binary flag; portfolio-loss binary flag.

**Kept (surfaced honestly):** stock-clamp annotations; Tool A low-confidence flags; quote-quality gates; stale-context warnings (Tool A/B run_id ≠ options manifest run_id); missing-candidate notes; down-beta-too-small skip; holdings-skipped reasons; header heuristic labels; **risk-free-rate fallback note (M5 — NEW in v6)**.

### 2k. Why `comparison.py` is not modified

Running the current code: `build_comparison_table(..., sort_by="breakeven_gold_pct")` returns `['NEM', 'AEM']` with breakevens `−1.4%` then `−8.9%` — i.e. **closest-to-zero-first**, which is exactly the put-buyer-correct order (Codex #4) and what `test_build_comparison_table_sorts_breakeven_by_smallest_required_drop_first` (already in the tree) asserts. v5's proposed `_NATURAL_DESCENDING["breakeven_gold_pct"] = False` would invert this to `['AEM','NEM']` and fail that test. Therefore: **no change**; keep the default and the test.

---

## 3. Module summaries

### `features/black_scholes.py` (edit — add call price)
Add `black_scholes_call_price(*, spot, strike, time_to_expiry_years, risk_free_rate, implied_volatility) -> float | None`: returns `0.0` when `spot == 0`; `None` for `strike<=0 | T<=0 | spot<0` or (with `spot>0`) `IV None/<=0`. **Put-call parity test required:** `call + strike·e^(-rT) ≈ put + spot` at ≥5 input combinations (including spot=0: `0 + Ke^{-rT} == Ke^{-rT} + 0`).

### `hedge/scenarios.py` (edit)
- Add `OptionStrategy` + `compute_strategy_pnl` (§2h).
- `compute_scenario_bundle(..., strategy: OptionStrategy = LONG_PUT, down_beta_min_for_scenario: float = 0.10, ...)`.
- **Thread `down_beta_min_for_scenario` into `_skip_reason`** (replace the module-constant read). Keep `DOWN_BETA_MIN_FOR_SCENARIO` only as the default value of the param, not as the live threshold inside `_skip_reason`.

### `hedge/sensitivity_ranking.py` (NEW)
```python
def build_sensitivity_ranking(
    *, tool_a_frame: pd.DataFrame,
    options_features: pd.DataFrame | dict[str, pd.DataFrame],
    candidate_grids: dict[str, list[CandidatePut]],
    risk_free_rate: float | None,                 # may be None → r=0 fallback (M-C)
    down_beta_min_for_scenario: float,
    sort_by: str = "down_beta_core",
    max_tickers: int | None = None,
) -> SensitivityRankingData: ...
```
Sort by `down_beta_core` desc; P&L column uses the same `down_beta_core`; ineligible names sink with notes.

### `hedge/portfolio_totals.py` (NEW)
`compute_portfolio_totals(*, holdings, tool_a_frame, tool_b_frame, candidate_grids, risk_free_rate, config) -> PortfolioTotalsData | None` per §2g. Returns `None` when holdings empty.

### `hedge/report.py` (REWRITE — builders + emitter)
`build_hedge_readiness_sections(...) -> HedgeReadinessSections`; `render_markdown(sections, paths) -> str`; `write_hedge_readiness_report(..., comparison_sort_by, ranking_sort_by, ranking_max_tickers, speculation_max_tickers, quantity) -> HedgeReportResult`. Order = §2e. Includes the M5 r=0 surfacing. (H1 already done; no re-sort needed.)

### `hedge/proxy_hedge.py`, `ingestion/options_phase.py`
**No further change** — 3-tier (H2) and per-ticker isolation + dedup (H3/M4) already implemented correctly in the working tree (`options_phase.py:97-136` already increments status *after* the successful try). Just commit in Step 0. **Do not rewrite from v5's pseudocode** (it would regress the count logic — self-review C2, Codex #8).

### `cli.py` (edit — 5 flags)
`--comparison-sort-by` (choices per §2c), `--ranking-sort-by` (choices `["down_beta_core"]`), `--ranking-max-tickers`, `--speculation-max-tickers`, `--quantity` — all argparse `default=None`, falling back to config.

### `header_context.py`
**No behavioural changes.** Step 5 only edits its helper imports to use `_helpers.py` (Codex #9). Verdict labels already include "heuristic".

---

## 4. Math

### 4a. Implied stock price under a gold scenario
```
raw_implied = current_stock_price × (1 + down_beta_core × gold_pct_change)
implied_stock_price = max(0, raw_implied);  stock_clamped_at_zero = (raw_implied < 0)
```

### 4b. Black-Scholes prices
Put: spot=0 → `strike·e^(-rT)`. Call: spot=0 → `0.0`. Both → `None` for `strike<=0 | T<=0 | spot<0` or (spot>0) `IV None/<=0`.

### 4c. Strategy P&L — see §2h (intrinsic computed inside the function).

### 4d. Down-beta threshold (config-driven, threaded into `_skip_reason`)
```python
def _skip_reason(*, current_stock_price, down_beta_core, premium_mid, quantity, down_beta_min_for_scenario):
    ...
    if down_beta_core is None or down_beta_core <= down_beta_min_for_scenario:
        return "Down-beta too small to model meaningful gold-down scenarios."
```

### 4e. Header verdict labels — all include "heuristic" (unchanged; already in code).

---

## 5. Report format (worked mock — 9 sections)

```
# Hedge Readiness Report

## Header
Gold: $2,058/oz (1d -0.4% 1wk -2.1% 1mo -3.5%)   GDX: $32.40 (1d -0.6% 1wk -3.4% 1mo -5.8%)
Implied-move-vs-modeled-downside (60d): NEM ±5.8% vs -14.2% → model > market (heuristic)

## Snapshot Summary
Tickers in manifest: 64 | Directly hedgeable: 19 | Thin: 5 | None: 40
Holdings: 0 | Context alignment: OK | Risk-free rate: 4.28%

## Stocks Ranked By Gold-Downside Sensitivity
Sorted by structural down-beta (core). Higher = more sensitive. Showing all 60 (--ranking-max-tickers to cap).
| Rank | Ticker | Down-β(core) | Up-β(core) | Confidence | IV %-tile | 60d Put @ -10% | Optionable | Notes |
| 1    | KGC    | 1.85         | 1.21       | high       | 45th      | +$4.50/c       | yes        | —     |

## Portfolio Totals            (skipped — holdings.yaml empty)
## Held Positions              (skipped — holdings.yaml empty)

## Candidate Puts (Speculation Section)
For 15 directly-hedgeable tickers, cheap-IV first.
▍NEM (Newmont) — $147.50, IV %-tile 38th, down-β(core) 1.42 (high) [grid + scenarios]

## Cross-Ticker Comparison View
Sorted by pnl_per_contract_minus10 desc (--comparison-sort-by to change).
| Ticker | Horizon | Strike | Mid | Δ-gap | Break. | P&L -5% | P&L -10% | P&L -20% | P&L/$ -10% |

## Proxy Hedges               (skipped — no held non-optionable names)

## Sources / Run Summary
Run id … | Options snapshot run … | Risk-free rate: 4.28% | Replay manifest: …
```
*If the ^IRX fetch failed, Snapshot Summary and Sources show "Risk-free rate: unavailable — using 0% (prices understated)" and each scenario block carries a one-line r=0 note (M5).* Standard 100-share multiplier throughout.

---

## 6. Order of operations (10 steps)

| # | Step | Test gate |
|---|---|---|
| 0 | **Commit the existing working-tree work** as the M1 punch-list baseline (H1 sort, H2 3-tier, H3 isolation, M4 dedup + their tests). One commit: `m15 v6 step 0: commit M1 punch-list (H1/H2/H3/M4)`. | `pytest -q` green at the new baseline; record count. |
| 1 | `black_scholes_call_price()` + put-call parity tests (incl. spot=0). | +~6 tests |
| 2 | Extend `config_models.py` + `hedge_readiness.yaml` with the **7** non-proxy fields. Schema-validation tests. | green |
| 3 | `OptionStrategy` + `compute_strategy_pnl` (§2h); thread `down_beta_min_for_scenario` into `compute_scenario_bundle` **and** `_skip_reason`. | +~12 tests (4 strategies, parity, threshold threading) |
| 4 | NEW `_helpers.py`; migrate `report.py`/`speculation_section.py`/`header_context.py`/`proxy_hedge.py` to import from it (no behavioural change). Keep `_helpers.py` dependency-light (no AppConfig/ProjectPaths/hedge imports — avoids cycles). | green |
| 5 | NEW `sensitivity_ranking.py` (§2f/§3). Tests: happy path, ineligible/null-beta sink, missing 60d candidate → null P&L, foreign listings "no options", `max_tickers` cap, `risk_free_rate=None`. | +~9 tests |
| 6 | NEW `portfolio_totals.py` (§2g). Tests: empty→None, shares mode, dollar_exposure mode, mixed, missing-price skip, missing-candidate skip, low-beta skip, single-position, hedge-cost = sum-of-positions, ceil rounding, dollar-exposure-without-price hedge-cost skip but notional counted. | +~11 tests |
| 7 | Add the **5** CLI flags; plumb through `run_hedge_readiness`. Tests: parse, config fallback, invalid choice rejected, plumbing. | +~6 tests |
| 8 | **REWRITE** `report.py` → builders + emitter; wire 9 sections (§2e); surface r=0 (M5). Tests: 9-heading order, ranking always renders, portfolio/held conditional on holdings, both holdings modes, r=0 note present when fallback, heuristic labels present. | +~12 tests; manual `hedge-readiness` runs |
| 9 | Manual smoke: 2-position `holdings.yaml` (one shares, one dollar_exposure) → all 9 sections; empty holdings → graceful; exercise all 5 flags incl. `--quantity 10`, `--ranking-max-tickers 5`. Then **docs** (`docs/`): dual-use framing, ranking walkthrough (Tool C preview), portfolio-totals walkthrough (both modes + share-based hedge cost), strategy-generic math note (4 coded, LONG_PUT surfaced), r=0 behaviour, CLI flag reference. | manual smoke captured; suite green |

One commit per step. Progress log alongside.

## 7. Acceptance criteria

- `hedge-readiness` produces markdown at `data/output/hedge_readiness/<date>_<run>.md` + `latest.md` with **all 9 sections** in §2e order.
- Sensitivity Ranking always renders, sorted by `down_beta_core` desc; P&L column uses the same beta.
- Portfolio Totals handles both modes; share-based hedge cost; dollar-exposure-without-price skips hedge cost (with reason) but still counts notional; skipped tickers listed.
- 5 CLI flags work; invalid choices argparse-rejected.
- `black_scholes_call_price` passes put-call parity; spot=0 → 0.0.
- `compute_strategy_pnl` computes intrinsic internally; 4 strategies tested; report uses LONG_PUT.
- Proxy 3-tier, options isolation, cross-sectional cheap-first, M4 dedup — present (from Step 0).
- r=0 fallback surfaced in Snapshot Summary + per-scenario note.
- Header verdicts include "heuristic". Decision triggers (FIRING/OK) absent.
- `comparison.py` unchanged; breakeven sorts closest-to-zero-first.
- `HedgeReadinessSections` includes `header` and `sources`.
- Full suite green, no live Yahoo. Tests grow from the Step-0 baseline by ~55-60.

## 8. Out of scope (deliberately)

- Workspace UI for hedge-readiness — M2.
- Tool C ranking pipeline — M3.
- **Gold-scenario sign-convention reconciliation (CODE_REVIEW M1)** — deferred: `expected_downside.py` (positive magnitudes) and `scenarios.py` (signed) both work and are independently tested; unifying them is a cross-cutting refactor unrelated to the put-scenario path, better done when a third consumer appears. Documented here so it isn't lost.
- Calls/short strategies **in the report** (math only in M1.5); spreads; Greeks beyond delta; vol skew; US ADR mapping; paid feeds; 52-week IV percentile maturity.

## 9. Risks for the reviewer to pry at

1. **Step 0 commit hygiene.** The working tree mixes H1/H2/H3/M4. Confirm the single Step-0 commit contains exactly those and nothing stray before building on top.
2. **`down_beta_core` everywhere.** Confirm Tool A actually exposes `down_beta_core` and `up_beta_core` per row for the ranking (it does in `data_models.py`), and that the ranking P&L and the sort key use the same column.
3. **Report refactor scope (step 8).** Largest step. Define the full `HedgeReadinessSections` (incl. header + sources) before moving renderer code.
4. **Portfolio dollar-exposure hedge cost.** Share-based rule needs `current_stock_price`; verify skip-with-reason path and that notional still counts.
5. **Threshold threading.** Verify `_skip_reason` reads the param, not the old constant — else the config field is dead.
6. **r=0 surfacing.** Verify the fallback flag flows from `options_phase` summary → SnapshotSummaryData/SourcesData → emitter.

## 10. Implementation guidance

- Branch `dev-vic`; confirm `git branch --show-current`. **10 steps → 10 commits** (`m15 v6 step <N>: …`). No amend/rebase/force-push/`git push`.
- `pytest -q` between every step; green, no new warnings, count ≥ baseline + new.
- Self-cross-check before each commit: read `git diff --staged`; nothing out of scope; no stray whitespace/import/"improvement". After: re-run tests, re-verify acceptance.
- Past failure modes to watch: Unicode→ASCII, defensive duplicate calls, bundled "improvements", unused imports, stray blank lines.
- **Checkpoints:** **A** after step 6 (all module work) — report tests-per-step; wait. **B** after step 8 (CLI + report) — paste TWO real reports (empty + 2-position mixed) and demo all 5 flags; wait. **C** after step 9 (smoke + docs) — completion report; wait.
- Progress log: `reviews/codex/codex_m15_v6_progress.md`.

## 11. Completion report (at Checkpoint C)
Cover: final file changes + line counts; deviations (with `file:line`); two sample reports; test deltas; the `HedgeReadinessSections` shape (confirm M2 can consume it); tick every Codex v5 finding + every self-review finding + every CODE_REVIEW M1 item; open questions.

---

## Appendix — version history
v1→v4: see git history of `claude_m15_*` plans. v5: `reviews/codex/claude_m15_v5_plan.md` (Codex NEEDS CHANGES). v6 (this doc) reconciles v5 with the working tree and resolves Codex's 9 findings + the Opus-4.8 self-review's 11 findings. v6 is authoritative.
