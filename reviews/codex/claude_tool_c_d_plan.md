# Plan: Tool C + Tool D (Milestone 2 of the downside-product line)

**Author:** Claude Code
**Branch:** `dev-vic`
**Date:** 2026-05-29
**Reviewer:** Codex (please review before any code is touched)
**Related:**
- [reviews/codex/codex_tool_c_d_ideas_and_critique.md](codex_tool_c_d_ideas_and_critique.md) — Codex's brainstorming critique that locked the design direction. This plan incorporates every substantive recommendation that wasn't already locked.
- [reviews/codex/claude_hedge_readiness_plan.md](claude_hedge_readiness_plan.md) — Milestone 1 (the action-layer companion). M2 builds the universe-wide ranking layer that M1 only covered for the 24 optionable subset.
- [[inflight-planning-tool-c-d]] memory

---

## 0. The simplest thing that could work

> **Add two new ranking pipelines that mirror Tool A and Tool B exactly. Tool C reads `tool_a_latest.parquet` + historical weekly returns + gold history + GDX/GDXJ (already fetched in M1) and computes three downside-event metrics that Tool A doesn't already publish (tail conditional loss on gold-down weeks, relative-weakness during gold-down regimes, downside-event hit rate). Tool D reads `tool_b_latest.parquet` + manual AISC/production/debt fields and computes margin-under-stress (gold ×0.8 / ×0.9 / current) + leverage-tier percentiles. Neither tool re-derives anything Tool A or Tool B already publishes. Output is parquet (per the established pattern) plus risk tags and percentile ranks — NOT z-score composites (per Codex critique). Workspace UI integration is OUT OF SCOPE for M2; that's the M3 milestone that unifies A/B/C/D under one view. CLI commands only: `python main.py tool-c`, `python main.py tool-d`.**

Everything below justifies, scopes, and grounds that baseline.

---

## 1. Current state (verified 2026-05-29)

### Tool A — what we'll consume (NOT re-derive)

`data/output/tool_a/tool_a_latest.parquet` (60 rows × 59 cols) publishes:

| Group | Fields | Tool C uses |
|---|---|---|
| Beta | `up_beta_6m/12m/3y/core`, `down_beta_6m/12m/3y/core` | Down-beta directly; up-beta for asymmetry context |
| Confidence | `r_squared_6m/12m/3y`, `weeks_6m/12m/3y`, `confidence_score`, `confidence_label` | Surfaced everywhere alongside any C ranking |
| Volatility | `total_volatility_52w`, `residual_volatility_52w`, `downside_volatility_52w`, `volatility_context` | Downside vol is a direct input |
| Asymmetry/gamma | `gamma_6m/12m/3y/core`, `asymmetry_ratio_6m/12m/3y/core`, `structural_gamma_core` | Negative asymmetry feeds the composite |
| Score | `tool_a_score`, `tool_a_rank`, `score_eligible`, `score_eligibility_reason` | Eligibility gates Tool C's output (no rank for ineligible names) |
| Stability | `delta_stability_score` | Confidence weighting |

**The duplication concern Codex raised is fully resolved: Tool C reads `tool_a_latest.parquet`, reuses these columns directly, and ONLY computes what Tool A doesn't already publish.**

### Tool B — what we'll consume (NOT re-derive)

`data/output/tool_b/tool_b_latest.parquet` (60 rows × 45 cols) publishes:

| Group | Fields | Tool D uses |
|---|---|---|
| Identity | `ticker`, `as_of_date`, `share_price_usd`, `market_cap_musd` | Universe + position sizing context |
| Forwards | `forward_revenue_musd`, `forward_ebitda_musd`, `forward_net_income_musd`, `forward_eps`, `forward_pe`, `ev_ebitda` | EBITDA stress inputs |
| Cash flow | `sustainable_fcf_musd`, `fcf_yield`, `leverage` | Leverage tier, FCF-vs-debt buffer |
| Verdict | `screening_verdict`, `layer1_status`, `layer1_pass`, `confidence`, `size_category` | Surfaced as context (do NOT use to disqualify) |
| Targets | `best_target_price_usd`, `best_upside_pct`, `tool_b_score`, `tool_b_rank` | Reference only |
| Manual gaps | `missing_manual_fields` | Drives the missing-data confidence reduction |

### Manual screening — Tool D needs AISC / production / debt fields

`data/manual/screening/manual_screening.sqlite3` table `company_inputs` has the fields that aren't in `tool_b_latest.parquet`:

```
ticker, production_oz, aisc_usd_per_oz, cash_cost_usd_per_oz, royalty_rate,
sustaining_capex_musd, da_musd, interest_expense_musd, tax_rate,
reserve_life_years, net_debt_musd, ebitda_ltm_musd
```

**Tool D reads from the manual store directly (read-only)** via the existing `golden_vector/screening/manual_data.py` loader. No new persistence; no copying into Tool B's parquet.

### Historical inputs — already retained per run

| Input | Path | Use |
|---|---|---|
| Per-ticker weekly returns | `data/intermediate/usd_equities/<run>.parquet` (or equivalent intermediate) | Tail-event averages + relative weakness |
| Gold weekly close | `data/runs/<run_id>/snapshots/raw_gold.parquet` (6,436 rows back to 2000-08-30) | Gold-down regime identification |
| GDX/GDXJ history | `data/runs/<run_id>/snapshots/benchmarks/*.parquet` (NEW in M1) | Relative weakness vs sector ETF |

These all exist or land via M1; M2 doesn't add new fetchers.

---

## 2. Architecture

### 2a. Decisions locked (from earlier conversations + Codex critique + memory)

| Decision | Choice | Why |
|---|---|---|
| Tool C/D as separate pipelines | YES — parallel to Tool A/B | User decision; gives independent provenance + cleaner backtest story |
| Read existing Tool A/B outputs | YES — both tools read their predecessor's `latest.parquet` | Codex's duplication critique — same pattern as Combined |
| Composite scoring approach | **Percentile ranks + risk tags, NOT z-scores** | Codex critique: z-scores on 60 tickers are sensitive to outliers + false precision |
| Sample-size / confidence columns | Visible everywhere alongside every rank | Codex critique: false precision is the main user risk |
| Missing data behavior | Reduce confidence + tag explicitly; never silently neutral | Codex critique |
| Tail conditional loss | "Average stock return in worst 10–20% gold-drop weeks" (NOT formal 5% CVaR) with event count + low-confidence flag if events < threshold | Codex critique: 7-event tail is statistically thin |
| Max-drawdown threshold | DROPPED. Replaced with event-based RELATIVE measure ("when gold is in worst N weeks, how often does stock underperform gold/GDX") | Codex critique: hard-coded thresholds are brittle |
| Margin under stress (Tool D centerpiece) | Compute estimated margin at current gold, gold −10%, gold −20% from production × (gold − AISC) | Codex's strongest single proposal |
| Net debt normalization | Use net_debt/EBITDA, net_debt/market_cap, cash/market_cap — NEVER raw net debt | Codex critique |
| AISC display | Both absolute margin cushion AND universe percentile | Codex critique |
| Combined view | M3, not M2 | Keeps M2 focused; combined view lands when A/B/C/D all exist |
| Naming | "Tool C" / "Tool D" internally; user-facing names "Downside Risk Ranking" (C) and "Fragility Ranking" (D) | Memory locked |
| Workspace UI | OUT OF SCOPE for M2 (CLI commands only) | Per the same low-risk M1 pattern; UI integration is a separate concern |

### 2b. Module layout (target after this milestone)

```
golden_vector/
  model/
    tool_c.py                    # NEW — Tool C metric computation (tail conditional, relative weakness, hit rate)
    tool_d.py                    # NEW — Tool D metric computation (margin stress, leverage tiers, AISC percentile)
  features/
    gold_regime.py               # NEW — identify gold-down weeks at multiple severity thresholds (worst-10%, worst-20%, etc.)
    relative_weakness.py         # NEW — stock-return vs gold/GDX/peer during gold-down weeks
    margin_stress.py             # NEW — pure math: production × (gold − AISC) scenario computation
    percentile_ranks.py          # NEW — cross-sectional ranking + risk tags
  ingestion/
    persist_tool_c.py            # NEW — write Tool C parquet + latest pointer (mirrors persist_tool_a)
    persist_tool_d.py            # NEW — same for Tool D
  app/
    paths.py                     # EDIT — add tool_c_output_dir, tool_d_output_dir, latest tool_c/d parquet paths
  cli.py                         # EDIT — add `tool-c`, `tool-d` subparsers + dispatch
  contracts/
    config_models.py             # EDIT — add ToolCConfig + ToolDConfig models
config/
  tool_c.yaml                    # NEW — tunable thresholds (event quantiles, min-events confidence threshold, weights)
  tool_d.yaml                    # NEW — tunable (stress-scenario steps, leverage tier boundaries)
tests/
  test_tool_c.py                 # NEW
  test_tool_d.py                 # NEW
  test_gold_regime.py            # NEW
  test_relative_weakness.py      # NEW
  test_margin_stress.py          # NEW
  test_percentile_ranks.py       # NEW
  test_cli_tool_c.py             # NEW
  test_cli_tool_d.py             # NEW
  test_persist_tool_c.py         # NEW
  test_persist_tool_d.py         # NEW
  fixtures/tool_c_inputs/        # NEW — sample tool_a + gold + equity history
  fixtures/tool_d_inputs/        # NEW — sample tool_b + manual data + gold
```

### 2c. Tool C schema (`data/output/tool_c/tool_c_latest.parquet`)

| Column | Notes |
|---|---|
| `ticker`, `as_of_date`, `run_id` | Identity |
| `source_tool_a_run_id` | Which Tool A run was consumed (provenance) |
| `score_eligible` | Inherited from Tool A — false here too if false there |
| `score_eligibility_reason` | Inherited |
| `weeks_observed_12m` | Sample size for the 12m window (from Tool A) |
| **Inherited from Tool A (re-exported for convenience, NOT recomputed):** | |
| `down_beta_core`, `up_beta_core` | Read from `tool_a_latest.parquet` |
| `asymmetry_ratio_core` | Same |
| `downside_volatility_52w` | Same |
| `r_squared_12m`, `confidence_score`, `confidence_label` | Same |
| **NEW computations (the actual Tool C work):** | |
| `gold_down_weeks_12m`, `gold_down_weeks_3y` | Count of weeks where gold was in worst 20% of its rolling 12m / 3y distribution |
| `tail_avg_return_worst10pct` | Average ticker weekly return during worst 10% gold weeks (rolling 3y). Null when event count < `min_events` threshold (config). |
| `tail_avg_return_worst20pct` | Same for worst 20% gold weeks (gives more events → more reliable). |
| `tail_event_count_worst10pct`, `tail_event_count_worst20pct` | Sample sizes — surfaced explicitly per Codex critique |
| `tail_confidence_flag` | `"high"` / `"medium"` / `"low"` based on event count + history length |
| `rel_weakness_vs_gold_pct` | During gold-down weeks (worst 20%), what % of those weeks did the stock underperform gold? |
| `rel_weakness_vs_gdx_pct` | Same vs GDX (uses M1's benchmark history) |
| `rel_weakness_event_count` | Sample size |
| `downside_hit_rate_5pct`, `downside_hit_rate_10pct` | % of weeks the stock dropped ≥ 5% / 10% during gold-down regimes (still relative, threshold is on STOCK move, not absolute) |
| `tool_c_percentile_rank` | 0–100 cross-sectional rank (higher = more downside risk) |
| `tool_c_risk_tags` | List of tags: `"steep_down_beta"`, `"high_tail_loss"`, `"persistent_relative_weakness"`, `"thin_history"`, `"low_confidence"`, `"score_ineligible"` |
| `tool_c_explanation` | Plain-English summary of why this rank/tag |
| `missing_inputs` | List of fields that couldn't be computed and why |

### 2d. Tool D schema (`data/output/tool_d/tool_d_latest.parquet`)

| Column | Notes |
|---|---|
| `ticker`, `as_of_date`, `run_id` | Identity |
| `source_tool_b_run_id` | Which Tool B run was consumed |
| **Inherited from Tool B (re-exported for context, NOT recomputed):** | |
| `share_price_usd`, `market_cap_musd`, `screening_verdict`, `confidence` | From `tool_b_latest.parquet` |
| `leverage`, `fcf_yield`, `sustainable_fcf_musd` | Same |
| `missing_manual_fields` | Same |
| **NEW computations (Tool D work):** | |
| `aisc_usd_per_oz`, `production_oz` | Read from manual store (read-only) |
| `spot_gold_usd_per_oz` | Latest from foundation snapshot |
| `aisc_to_spot_ratio` | `aisc / spot_gold` |
| `aisc_universe_percentile` | Cross-sectional rank of AISC ratio across universe (higher = closer to break-even = more fragile) |
| `estimated_margin_per_oz_current` | `spot_gold − aisc` |
| `estimated_margin_per_oz_gold_minus10` | `(spot_gold × 0.9) − aisc` |
| `estimated_margin_per_oz_gold_minus20` | `(spot_gold × 0.8) − aisc` |
| `estimated_annual_ebitda_current_musd` | `production_oz × margin_per_oz_current ÷ 1e6` |
| `estimated_annual_ebitda_minus10_musd` | Same at gold −10% |
| `estimated_annual_ebitda_minus20_musd` | Same at gold −20% |
| `ebitda_pct_change_minus10` | % drop in estimated EBITDA at gold −10% vs current |
| `ebitda_pct_change_minus20` | Same at −20% |
| `net_debt_musd` | Read from manual store |
| `net_debt_to_ebitda_current`, `net_debt_to_ebitda_minus10`, `net_debt_to_ebitda_minus20` | Leverage ratio under each scenario |
| `breaks_even_at_gold_usd` | Computed: `aisc * production / production = aisc`. Stock is break-even when gold = AISC. Shows headroom to break-even. |
| `headroom_to_breakeven_pct` | `(spot_gold − aisc) / spot_gold` — how much gold can drop before this company is break-even |
| `tool_d_percentile_rank` | 0–100 cross-sectional rank (higher = more fragile) |
| `tool_d_risk_tags` | `"thin_margin"`, `"high_leverage_after_stress"`, `"breakeven_within_15pct"`, `"missing_aisc"`, `"missing_production"`, `"missing_debt"` |
| `tool_d_explanation` | Plain-English summary |
| `missing_inputs` | List of fields that couldn't be computed |

### 2e. Ranking + risk tags — the v1 surface (NOT a z-score composite)

Per Codex critique, the published rank is a **percentile** within the eligible universe. Each ticker also gets a list of **risk tags** that explain which dimensions triggered the ranking. This is much more interpretable than a single number.

**Tool C tags trigger conditions (configurable):**
- `steep_down_beta`: down_beta_core > 75th percentile
- `high_tail_loss`: tail_avg_return_worst20pct in worst 25% (more negative)
- `persistent_relative_weakness`: rel_weakness_vs_gold_pct > 60%
- `thin_history`: weeks_observed_12m < threshold OR tail_event_count_worst20pct < threshold
- `low_confidence`: confidence_score < threshold
- `score_ineligible`: Tool A flagged ineligible; no rank assigned

**Tool D tags trigger conditions (configurable):**
- `thin_margin`: headroom_to_breakeven_pct < 15%
- `high_leverage_after_stress`: net_debt_to_ebitda_minus10 > 5 or net_debt_to_ebitda_minus20 > 10
- `breakeven_within_15pct`: spot can drop < 15% before margin = 0
- `missing_aisc` / `missing_production` / `missing_debt`: required field absent in manual store
- `screen_out_context`: Tool B verdict is SCREEN_OUT (informational only — Tool D does NOT disqualify on this)

**Composite rank computation (the only "score"):**
For each tool independently, rank is `percentile(weighted_average(component_percentiles))` where weights live in `config/tool_c.yaml` and `config/tool_d.yaml` and default to equal-weighted. The composite is computed for explanation only; the **published rank is the percentile**, not a raw z-score. Ineligible names are excluded from the ranking entirely (not assigned a low rank).

---

## 3. Module summaries (public API sketches)

### `golden_vector/features/gold_regime.py` (~60 lines)

```python
def identify_gold_down_regimes(
    *, gold_weekly: pd.DataFrame, severities: tuple[float, ...] = (0.10, 0.20),
    rolling_window_weeks: int = 156  # 3y
) -> pd.DataFrame:
    """For each week, classify whether gold's return puts it in the worst N% of its
    rolling distribution. Returns frame indexed by week with boolean columns:
    `gold_in_worst_10pct`, `gold_in_worst_20pct`, etc.
    """
```

### `golden_vector/features/relative_weakness.py` (~80 lines)

```python
def compute_relative_weakness(
    *, ticker_weekly: pd.DataFrame, gold_weekly: pd.DataFrame,
    benchmark_weekly: pd.DataFrame | None,  # GDX or GDXJ; None to skip
    gold_down_mask: pd.Series,
) -> RelativeWeaknessResult:
    """During gold-down weeks, compute:
    - rel_weakness_vs_gold_pct: % of weeks ticker_return < gold_return
    - rel_weakness_vs_benchmark_pct: same vs benchmark when available
    - event count
    """
```

### `golden_vector/features/margin_stress.py` (~50 lines, pure math)

```python
def estimate_margin_under_stress(
    *, spot_gold_usd_per_oz: float, aisc_usd_per_oz: float,
    production_oz: float, gold_scenarios: tuple[float, ...] = (1.0, 0.9, 0.8),
) -> dict:
    """Returns dict with margin_per_oz and annual_ebitda_musd at each gold scenario.
    Returns None values when AISC or production is missing.
    """
```

### `golden_vector/features/percentile_ranks.py` (~80 lines)

```python
def compute_percentile_rank(values: pd.Series, *, eligible_mask: pd.Series | None) -> pd.Series:
    """Returns 0-100 percentile rank within the eligible subset.
    Ineligible names get NaN, NOT a low rank.
    """

def assign_risk_tags(
    *, row: dict, tag_rules: list[TagRule]
) -> list[str]:
    """Apply each rule to the row; return list of triggered tags."""
```

### `golden_vector/model/tool_c.py` (~250 lines)

```python
def compute_tool_c(
    *, paths: ProjectPaths, run_context: RunContext, config: ToolCConfig,
) -> pd.DataFrame:
    """Read tool_a_latest.parquet + gold history + per-ticker weekly returns +
    GDX/GDXJ history (from M1's persisted benchmarks). Compute the Tool C schema
    rows. Persist via persist_tool_c. Return the frame.
    """
```

### `golden_vector/model/tool_d.py` (~200 lines)

```python
def compute_tool_d(
    *, paths: ProjectPaths, run_context: RunContext, config: ToolDConfig,
) -> pd.DataFrame:
    """Read tool_b_latest.parquet + manual store (read-only via existing loader)
    + foundation snapshot for spot gold. Compute the Tool D schema rows.
    Persist via persist_tool_d. Return the frame.
    """
```

### `golden_vector/ingestion/persist_tool_c.py`, `persist_tool_d.py` (~80 lines each)

Mirror the existing `persist_tool_a.py` pattern exactly:
- Write `tool_c_output_<run_id>.parquet` (full output) and `tool_c_latest_<run_id>.parquet` (latest per-ticker snapshot)
- Update `tool_c_latest.parquet` pointer
- Record artifacts in run metadata

### `cli.py` (~30 lines added per tool)

```python
# New subcommand
tool_c_parser = subparsers.add_parser("tool-c", help="Compute downside risk ranking (consumes tool_a_latest).")
tool_d_parser = subparsers.add_parser("tool-d", help="Compute fragility ranking (consumes tool_b_latest + manual store).")

# Dispatch
if args.command == "tool-c":
    return run_tool_c(paths)
if args.command == "tool-d":
    return run_tool_d(paths)
```

Both commands call `RunContext.start()` (auto-writes replay manifest), load configs, run the computation, persist, and finalize. Same pattern as `run_tool_a`.

---

## 4. The specific math

### 4a. Gold-down regime identification

For each week `w` in the gold history (already in `data/runs/<run>/snapshots/raw_gold.parquet`):
1. Compute weekly return: `gold_return_w = (gold_close_w - gold_close_{w-1}) / gold_close_{w-1}`
2. Within a rolling window (3y = 156 weeks), compute the 10th and 20th percentile of `gold_return`
3. `gold_in_worst_10pct_w = (gold_return_w <= 10th_percentile_w)`
4. Same for 20%

This produces a boolean mask per week. Mask is applied to per-ticker weekly returns to compute tail averages.

### 4b. Tail conditional loss

```
For each ticker:
  weekly_returns = ticker's weekly close-to-close returns aligned to gold weeks
  worst10_mask = gold_in_worst_10pct over the same date range
  events = weekly_returns[worst10_mask]
  if len(events) < min_events_threshold (config, default 8):
    tail_avg_return_worst10pct = None
    tail_confidence_flag = "low"
  else:
    tail_avg_return_worst10pct = events.mean()
    tail_confidence_flag = "high" if len(events) >= 15 else "medium"
  tail_event_count_worst10pct = len(events)
```

Same for worst20pct (will always have more events → more reliable).

### 4c. Relative weakness

```
For each ticker, during gold-down weeks (worst 20%):
  ticker_returns = ticker_weekly_return during those weeks
  gold_returns = gold_weekly_return during those weeks
  underperform_count = sum(ticker_returns < gold_returns)
  rel_weakness_vs_gold_pct = underperform_count / len(ticker_returns) * 100
```

Same for GDX/GDXJ when available. Skip the benchmark version if benchmark history doesn't cover the date range.

### 4d. Margin under stress (Tool D centerpiece)

For each ticker, read AISC and production from manual store:
```
margin_per_oz_current = spot_gold - aisc_usd_per_oz
margin_per_oz_minus10 = (spot_gold * 0.9) - aisc_usd_per_oz
margin_per_oz_minus20 = (spot_gold * 0.8) - aisc_usd_per_oz

annual_ebitda_current = production_oz * margin_per_oz_current / 1_000_000  # → M$
annual_ebitda_minus10 = production_oz * margin_per_oz_minus10 / 1_000_000
annual_ebitda_minus20 = production_oz * margin_per_oz_minus20 / 1_000_000

if annual_ebitda_current is positive:
  ebitda_pct_change_minus10 = (annual_ebitda_minus10 - annual_ebitda_current) / annual_ebitda_current * 100
  # Similarly for -20

if net_debt_musd is available and annual_ebitda_X is positive:
  net_debt_to_ebitda_X = net_debt_musd / annual_ebitda_X

headroom_to_breakeven_pct = (spot_gold - aisc) / spot_gold * 100
```

Negative-margin cases (gold below AISC) are explicitly surfaced — that's the "this company breaks at this gold level" signal.

### 4e. Percentile rank + tags

Compute the eligible mask (intersection of Tool A's score_eligible + Tool B's screening_verdict != error for Tool D). For each component metric:
1. Compute percentile (0-100) within eligible subset
2. Apply the tag rules from config
3. Composite rank = percentile of the equal-weighted average of component percentiles
4. Ineligible names: NaN rank, but still appear in output with their tags + missing_inputs

---

## 5. Order of operations

**Per the v2 lesson from Hedge Readiness: storage + provenance ordering matters. Feature modules before model wrappers. Tests gate every step.**

| # | Step | Test gate |
|---|---|---|
| 1 | Add `config/tool_c.yaml` + `config/tool_d.yaml` + `ToolCConfig` + `ToolDConfig` models in `contracts/config_models.py`. Tests for schema validation. NO computation yet. | Suite green; new schema tests pass |
| 2 | Add `features/gold_regime.py` (pure data manipulation, no I/O). Tests against fixture gold series. | Suite green; ~6 new tests |
| 3 | Add `features/relative_weakness.py` (pure compute, no I/O). Tests against fixture ticker + gold + benchmark series. | Suite green |
| 4 | Add `features/margin_stress.py` (pure math). Tests including missing inputs, negative margin, zero production. | Suite green |
| 5 | Add `features/percentile_ranks.py` (pure compute). Tests for ineligible exclusion, tag application, ties. | Suite green |
| 6 | Add `ingestion/persist_tool_c.py` + `ingestion/persist_tool_d.py` (write parquet, update latest pointer, record artifacts). Tests using tmp_path. | Suite green |
| 7 | Add `model/tool_c.py` (orchestrates inputs → features → schema rows → persist). Tests use fixture Tool A output + fixture gold/equity history. | Suite green |
| 8 | Add `model/tool_d.py` (same shape). Tests use fixture Tool B output + fixture manual store + fixture gold. | Suite green |
| 9 | Add `tool-c` CLI subcommand + handler. Tests render a small frame against fixture inputs. | Suite green |
| 10 | Add `tool-d` CLI subcommand + handler. Tests render a small frame against fixture inputs. | Suite green |
| 11 | Manual smoke: run `python main.py tool-c` and `python main.py tool-d` against real data. Verify parquet outputs exist, columns match schema, sample rows look reasonable. | Suite green; manual smoke captured in progress log |
| 12 | Update `docs/` with brief "Tool C and Tool D" section. Note that the combined view (M3) hasn't shipped yet. | Suite green |

Each step = one commit. Progress log committed alongside per the established pattern.

---

## 6. Acceptance criteria

The milestone is done when **all** of the following hold:
- `python main.py tool-c` produces `data/output/tool_c/tool_c_latest.parquet` with the schema in §2c.
- `python main.py tool-d` produces `data/output/tool_d/tool_d_latest.parquet` with the schema in §2d.
- Both commands fail loudly if the prerequisite Tool A / Tool B output doesn't exist (e.g., "Tool A output not found; run `python main.py tool-a` first").
- Tool C's tail-conditional fields are null with `tail_confidence_flag="low"` when event count is below threshold (no false precision).
- Tool D's margin-stress fields are computed for every ticker that has AISC + production in the manual store; absent fields produce explicit `missing_inputs` entries.
- Risk tags fire on the threshold rules from config; no ticker silently gets an empty tag list when it should have one.
- Percentile ranks exclude ineligible names rather than placing them at the bottom.
- Both commands use `RunContext.start()` so the replay manifest auto-captures their provenance.
- Full test suite passes with the new tests; no live external data calls.
- The combined `/` overview page is NOT modified in M2 — that's M3.

---

## 7. Out of scope (deliberately)

- **Workspace UI integration** (`/tool-c` / `/tool-d` overview pages + detail-page lenses) — that's the M3 milestone.
- **Combined view evolution** to show A + B + C + D side-by-side — M3.
- **Hedge Readiness re-use of Tool C/D rankings** — the M1 hedge report uses lightweight internal ranking; integrating with Tool C/D fully is M3 work.
- **z-score composite** — explicitly rejected per Codex critique.
- **Backtest framework** — replay manifest enables it; not part of M2.
- **Predictive scoring** — vague direction, separate planning needed.
- **IV percentile maturation** — auto-activates in M1 over time; no M2 work needed.
- **Tool D inputs from anywhere other than `tool_b_latest.parquet` + manual store** — no new data fetching in M2.

---

## 8. Risks Codex should pry at

1. **Tail confidence thresholds.** I picked `min_events=8` for "computable at all" and `>=15` for "high confidence." With 156 weeks of 3y history × 10% tail = 15-16 events typically. Is the threshold logic right, or do we need a longer history before publishing?
2. **Per-ticker weekly returns source.** I assume they're already in `data/intermediate/usd_equities/` per run. If they're not in the published latest pointer, Tool C needs to read run-local snapshots. Path is plausibly already in `ProjectPaths` but verify before implementing.
3. **GDX/GDXJ history coverage.** M1 just shipped these. If GDX history is shorter than the universe ticker history (likely — GDX is ~2006+), what's the right behavior for `rel_weakness_vs_gdx_pct` on older windows? Probably: compute over the intersection date range, skip if intersection < min_events.
4. **Margin-under-stress with negative current margin.** Some high-cost producers may already be below break-even. Math still works (negative margin × production = negative EBITDA) but `ebitda_pct_change` is undefined when starting from zero or negative. Need explicit handling.
5. **Tool D and Tool B verdict context.** Codex was clear that Tool B's SCREEN_OUT verdict should NOT disqualify a Tool D ranking (a fragile company is still informative). Plan currently surfaces verdict as context only. Confirm this is the right call.
6. **Net debt / EBITDA division-by-zero / sign.** When stress EBITDA is zero or negative, the ratio is undefined. Tag explicitly rather than producing a null number.
7. **Eligibility intersection logic.** Tool C eligible = Tool A score_eligible. Tool D eligible = some Tool B status. What about a ticker that's Tool A ineligible but Tool B eligible (or vice versa)? Probably: each tool's eligibility is independent, but the user should be able to see both.

---

## 9. Implementation guidance (this is for Codex to follow during coding)

Same operational rules as the hedge-readiness plan §10. Repeating the critical ones here so Codex doesn't need to bounce between files:

### Git workflow
- Branch `dev-vic`. Confirm with `git branch --show-current`.
- One commit per step. Twelve steps → twelve commits.
- Commit message format: `tool c/d step <N>: <one-line description>`
- Progress log committed alongside every step (two files per commit minimum).
- No amend, no rebase, no force-push, no skip-hooks, no `git push` — Emanuel pushes.
- One commit = one stated purpose. Side improvements get their own commits.

### Test gate
- `python -m pytest -q` between every step. All green, no new warnings, test count ≥ baseline.
- If a step breaks tests, STOP. Revert with `git reset --soft HEAD~1`, fix, re-commit. 15-minute fix cap.

### Self-cross-check rhythm at every step (MANDATORY — same as Hedge Readiness plan §10)

**Before committing step N — read your own diff:**
1. `git diff --staged` end-to-end. Read every line. Not skim.
2. For each chunk, ask: does this match what step N said? touched any file the step didn't mention? any comment/docstring/type-hint/whitespace edit I didn't intend? any imports added or removed beyond what step required? any "small improvement" I slipped in?
3. If anything doesn't belong, **fix it in this commit before staging.**

**After committing step N — verify your own work:**
1. Re-run tests.
2. Re-read the relevant plan section. Explicitly check that step N's acceptance is met.
3. If you find a bug, fix it **before starting step N+1.** Either amend a follow-up commit or squash a trivial fix.
4. **Do NOT proceed with known bugs in step N.**

**Stop conditions** (any of these → halt and report):
- Test count dropped
- A test that was green now errors or skips
- A grep verification fails
- Your own diff has changes you can't explain in one sentence
- 15-minute fix cap reached

**Past failure modes to actively look for:**
- Unicode → ASCII normalization in moved or copied text
- Defensive duplicate calls without comments
- "Improvements" bundled into a fix commit
- Unused imports left behind
- Stray blank lines accumulating

### Progress log
Create `reviews/codex/codex_tool_c_d_progress.md` at session start with baseline. Append one line per step:
```
Step <N> (<step-name>): committed <sha>. Tests: <pass>/<total>. Smoke: <yes/no/n-a>. Notes: <one line>.
```

### Checkpoints — STOP and report at each
- **CHECKPOINT A** — after step 6 (all features + persistence modules in place, no model orchestration yet). Report: tests added, all passing, fixtures committed. Wait for "continue."
- **CHECKPOINT B** — after step 10 (Tool C + Tool D + CLI commands working). Report: paste a sample of `tool_c_latest.parquet` and `tool_d_latest.parquet`. Wait for "continue."
- **CHECKPOINT C** — after step 12 (final). Write the completion report (see §10). Wait for review.

### Out of scope — DO NOT do any of these
- Workspace UI work (HTML, lenses, detail page, overview pages) — that's M3
- Combined view changes
- Hedge Readiness integration with Tool C/D outputs — M3
- Backfilling historical Tool C/D runs
- Predictive scoring of any kind
- Anything outside the files named in §2b except `docs/` per step 12

### If anything is ambiguous
Stop and ask. The plan is specific by design.

### Start now
1. Confirm branch: `git branch --show-current` → `dev-vic`
2. Baseline: `python -m pytest -q` and record pass count
3. Create `reviews/codex/codex_tool_c_d_progress.md` with baseline
4. Re-read this plan; confirm the design is consistent with your earlier brainstorming critique
5. Begin step 1
6. Stop at **CHECKPOINT A** and report

---

## 10. Completion report (write at CHECKPOINT C)

Write `reviews/codex/codex_tool_c_d_completion_report.md` covering:

1. **Final file changes** — list every file added/modified with line counts
2. **Deviations from the plan** — every judgment call not specified, with `file:line` references. If none, say so explicitly
3. **Schema example** — paste real rows from `tool_c_latest.parquet` and `tool_d_latest.parquet`
4. **Risk tag distribution** — across the 60-ticker universe, how many tickers triggered each tag?
5. **Eligibility tally** — how many tickers eligible for Tool C, for Tool D, for both, for neither?
6. **Test deltas** — baseline pass count, final pass count, new test files added
7. **Edge cases verified** — table mapping each (missing AISC, missing production, ineligible, no GDX overlap, all-time-negative margin, etc.) to its covering test
8. **Risks resolved** — for each of the 7 risks in §8, what you decided + where it lives in code
9. **Open questions for the reviewer** — anything you want Claude to focus on

---

## 11. Why this plan is shaped this way

| Principle | How it shows up |
|---|---|
| Simplest thing first | §0 states the no-frills version: two pipelines, no UI, ranks + tags only |
| Match rigor to risk | New analytical outputs feeding real money decisions → full plan + Codex review (correct rigor) |
| No premature abstraction | Each tool is a single module; no plugin system; no shared base class; no combined-view work |
| Don't redo work | Tool C reads `tool_a_latest.parquet`; Tool D reads `tool_b_latest.parquet` + manual store. Zero formula duplication. Same pattern as Combined. |
| Honest about limitations | §2a explicitly states tail-CVaR is statistically thin; §2c surfaces event counts; §4b sets `min_events` thresholds with low-confidence flags |
| Verifiable | Both CLI commands produce inspectable parquets; tests use fixtures, no live data; manual smoke at step 11 |
| User value first | The risk tags ("thin_margin", "high_tail_loss", "persistent_relative_weakness") tell the user WHY a name ranks high. Not just a number. |
| Plain English | Schema docstrings, explanation columns, plain-English tag names |
